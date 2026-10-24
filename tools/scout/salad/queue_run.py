#!/usr/bin/env python3
"""ЗАДАНИЯ ЧЕРЕЗ ОЧЕРЕДЬ SALAD вместо SSH-терминала (план mesh-18, T-20261024-03) — транспорт `queue` раздатчика.

ЗАЧЕМ. Ночь 23→24.10: 108 из 202 прогретых машин раздатчик не увидел (54 % оплаты), проба 24.10: вход SSH Salad рвёт
соединение до приветствия при живом контейнере. Очередь Salad (Job Queue) везёт задание ИЗНУТРИ машины: воркер очереди
в контейнере (`queue_entry.sh`) берёт задание и шлёт его на наш `/generate`. SSH для работы не нужен вовсе.

КАК УСТРОЕНО. Учёт заданий — тот же, что у SSH (`ssh_run.Jobs`: попытки, пауза повтора, курсор, спул, журнал
`mesh-run-progress.jsonl`, `<снимок>.done`, карантин входа, приёмник). Вместо потока на машину — «слоты очереди»: поток
берёт задание (`Jobs.take`), кладёт его в очередь группы, где есть место, и опрашивает его до конца. Место — по
ГОТОВЫМ инстансам группы (`ready` из API = прошла проба `/ready`, то есть модель прогрета): на машину не больше
`PER_READY` заданий в очереди (одно в работе, одно ждёт), — иначе отменять при остановке пришлось бы сотни.

ЧТО СЧИТАЕТСЯ РЕЗУЛЬТАТОМ. Salad ставит `succeeded` на ЛЮБОЙ ответ 200, а наш воркер отвечает 200 и на логический отказ
(`worker.py`: `status: failed`, `input_failed`, `bad_cutout` …, Codex § 2). Поэтому итог задания — поле `status` ответа
воркера (`output`), его судит прежняя политика (`node_health.classify`). `failed`/`cancelled` самой очереди (Salad сдался
после 4 попыток, или задание снято) — транспортный сбой `queue/…`: задание вернётся в очередь нашим повтором.

ПОВТОР БЕЗ ДВОЙНОЙ ОПЛАТЫ. Каждое положенное в очередь задание — строка в `mesh-queue-jobs.jsonl` (id задания Salad,
sku, seed), конец — строка `end`. Раздатчик упал и поднялся — незакрытое задание того же (sku, seed) он ДООПРАШИВАЕТ, а
не кладёт второй раз. Отмена (`DELETE`) снимает только ждущее: начатое Salad не останавливает (документация) — его
результат дождёмся или его подхватит `complete.json` приёмника (`worker.py` already_done).

    ~/venvs/scout/bin/python queue_run.py --status mesh-q <id>          # одно задание очереди: статус, события, ответ
    ~/venvs/scout/bin/python queue_run.py --jobs mesh-q                 # задания очереди (первая страница)
    ~/venvs/scout/bin/python queue_run.py --cancel mesh-q <id>          # снять ждущее задание
    ~/venvs/scout/bin/python queue_run.py --submit mesh-q job.json      # канарейка: одно задание из файла
    ~/venvs/scout/bin/python queue_run.py --follow mesh-q <id>          # следить до конца (итог — ответ воркера)
    ~/venvs/scout/bin/python queue_run.py --selftest                    # без сети
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import salad_groups as SG  # noqa: E402

API = 'https://api.salad.com/api/public'
ORG, PROJECT = 'prodstore', 'dmodel'
LEDGER = os.environ.get('MESH_QUEUE_LEDGER') or os.path.join(HERE, '..', 'mesh-queue-jobs.jsonl')
PER_READY = int(os.environ.get('MESH_QUEUE_PER_READY', '2'))         # заданий в очереди на готовую машину
MAX_INFLIGHT = int(os.environ.get('MESH_QUEUE_MAX_INFLIGHT', '120'))  # слотов (потоков) на прогон
POLL_S = float(os.environ.get('MESH_QUEUE_POLL_S', '20'))             # опрос одного задания
READY_POLL_S = float(os.environ.get('MESH_QUEUE_READY_POLL_S', '30'))  # опрос готовых инстансов групп
# Задание дольше — сдаёмся (ждущее снимаем, начатое не остановить); 3 ч: прогрев замены ~35 мин + генерация до ~20 мин
# + переезд с прерванной машины (Salad замечает обрыв по истечении аренды, «несколько минут» — документация).
JOB_MAX_S = float(os.environ.get('MESH_QUEUE_JOB_MAX_S', '10800'))
STALL_S = float(os.environ.get('MESH_QUEUE_STALL_S', '1800'))         # нет готовых машин и движения — закрываем остаток
_led_lock = threading.Lock()


def key() -> str:
    k = os.environ.get('SALAD_API_KEY')
    if not k:
        sys.exit('нет SALAD_API_KEY')
    return k


def req(method: str, path: str, body: dict | None = None, timeout: int = 40) -> tuple[int, dict]:
    """(HTTP-код, тело). Сеть/таймаут — код 0: решает вызывающий (повторить опрос, а не закрыть задание)."""
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    r = urllib.request.Request(f'{API}/organizations/{ORG}/projects/{PROJECT}{path}', data=data, method=method,
                               headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0',
                                        'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {'detail': raw[:200].decode(errors='replace')}
    except Exception as e:  # noqa: BLE001 — сеть: код 0
        return 0, {'detail': f'{type(e).__name__}: {str(e)[:160]}'}


def submit(queue: str, job: dict, meta: dict) -> tuple[str | None, str]:
    """Положить задание в очередь: (id, '') или (None, причина). Метаданные — строки (у Salad до 20 полей)."""
    code, d = req('POST', f'/queues/{queue}/jobs', {'input': job, 'metadata': {k: str(v) for k, v in meta.items()}})
    if code in (200, 201) and d.get('id'):
        return d['id'], ''
    return None, f'HTTP {code}: {str(d.get("detail") or d)[:160]}'


def get(queue: str, qid: str) -> tuple[int, dict]:
    return req('GET', f'/queues/{queue}/jobs/{qid}')


def cancel(queue: str, qid: str) -> int:
    """Снять задание. 202 — принято (начатое Salad доделает и ответ выбросит), 404 — его уже нет."""
    return req('DELETE', f'/queues/{queue}/jobs/{qid}')[0]


def ready_by_group(groups: list[str]) -> dict:
    """Готовые инстансы по группам: `ready` из API — прошла проба `/ready` группы (модель прогрета), без SSH.
    Группа не прочиталась — None (не ноль: «не знаем» не должно закрывать прогон как «машин нет»)."""
    out = {}
    for g in groups:
        code, d = req('GET', f'/containers/{g}/instances')
        out[g] = (sum(1 for i in d.get('instances') or [] if i.get('state') == 'running' and i.get('ready'))
                  if code == 200 else None)
    return out


def to_result(qj: dict, job: dict) -> dict:
    """Итог задания очереди → результат в формате воркера (как у SSH-транспорта: его судит `node_health.classify`)."""
    st = qj.get('status')
    sku = job.get('sku')
    if st == 'succeeded':
        out = qj.get('output')
        if isinstance(out, str):
            try:
                out = json.loads(out)
            except ValueError:
                out = None
        if isinstance(out, dict) and out.get('status'):
            return out
        return {'sku': sku, 'status': 'transport_failed',
                'error': f'queue/no_output: succeeded без ответа воркера ({str(qj.get("output"))[:120]})'}
    tries = sum(1 for e in qj.get('events') or [] if e.get('action') == 'started')
    return {'sku': sku, 'status': 'transport_failed', 'error': f'queue/{st}: попыток Salad {tries}'}


def ledger_write(rec: dict) -> None:
    try:
        with _led_lock, open(LEDGER, 'a', encoding='utf-8') as f:
            f.write(json.dumps({**rec, 'at': round(time.time())}, ensure_ascii=False) + '\n')
    except OSError as e:
        print(f'  !! {LEDGER}: не записан ({type(e).__name__}) — при падении раздатчика задание может уйти дважды',
              flush=True)


def ledger_open() -> dict:
    """(sku, seed) → (очередь, id) положенных и НЕ закрытых заданий: их доопрашиваем, а не кладём снова."""
    out, ended = {}, set()
    try:
        lines = open(LEDGER, encoding='utf-8').read().splitlines()
    except FileNotFoundError:
        return {}
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get('ev') == 'end':
            ended.add(r.get('qid'))
        elif r.get('ev') == 'submit' and r.get('qid'):
            out[(r.get('sku'), int(r.get('seed') or 0))] = (r.get('queue'), r['qid'])
    return {k: v for k, v in out.items() if v[1] not in ended}


class Slots:
    """Где есть место: группа с очередью, у которой заданий в работе меньше `PER_READY` × готовых машин."""

    def __init__(self, groups: dict):
        self.queue_of = dict(groups)                 # группа → очередь
        self.ready = {g: None for g in groups}       # группа → готовых машин (None — не знаем)
        self.used = {g: 0 for g in groups}
        self.cv = threading.Condition()
        self.moved_at = time.time()                  # последнее движение: новое задание, смена статуса, итог

    def update(self, ready: dict) -> None:
        with self.cv:
            for g, n in ready.items():
                if n is not None or self.ready.get(g) is None:
                    self.ready[g] = n
            self.cv.notify_all()

    def total_ready(self) -> int:
        with self.cv:
            return sum(n or 0 for n in self.ready.values())

    def acquire(self, stop: threading.Event) -> str | None:
        """Группа со свободным местом (ждём, пока появится); None — прогон останавливается."""
        with self.cv:
            while not stop.is_set():
                free = [(self.ready[g] * PER_READY - self.used[g], g) for g in self.queue_of
                        if self.ready.get(g) and self.used[g] < self.ready[g] * PER_READY]
                if free:
                    g = max(free)[1]
                    self.used[g] += 1
                    return g
                self.cv.wait(timeout=5)
            return None

    def release(self, g: str) -> None:
        with self.cv:
            self.used[g] = max(0, self.used[g] - 1)
            self.cv.notify_all()

    def swap(self, old: str, new: str) -> None:
        with self.cv:
            self.used[old] = max(0, self.used[old] - 1)
            self.used[new] += 1
            self.cv.notify_all()

    def moved(self) -> None:
        with self.cv:
            self.moved_at = time.time()


def follow(queue: str, qid: str, job: dict, stop: threading.Event, slots: Slots, js) -> tuple[dict, dict]:
    """Опрашивать задание до конца. (задание очереди, результат). Остаток закрыт (`js.stalled`) или срок вышел —
    ждущее снимаем; начатое Salad не остановить — закрываем транспортным сбоем, повторит следующая пачка."""
    t0, last, seen = time.time(), {}, None
    while True:
        code, qj = get(queue, qid)
        if code == 200:
            last = qj
            if qj.get('status') != seen:
                seen = qj.get('status')
                slots.moved()
            if seen in ('succeeded', 'failed', 'cancelled'):
                return qj, to_result(qj, job)
        elif code == 404:
            return {}, {'sku': job.get('sku'), 'status': 'transport_failed', 'error': 'queue/lost: задания нет в очереди'}
        why = 'остаток пачки закрыт' if js.stalled else ('срок задания вышел' if time.time() - t0 > JOB_MAX_S else '')
        if why:
            st = last.get('status')
            c = cancel(queue, qid) if st in (None, 'pending') else None
            return last, {'sku': job.get('sku'), 'status': 'transport_failed',
                          'error': f'queue/abandoned: {why}, статус {st}' + (f', снято HTTP {c}' if c else '')}
        stop.wait(POLL_S)


def run(S, js, jobs: list, n_pre: int, keep_alive: bool) -> int:
    """Прогон `ssh_run` по очереди Salad. `S` — модуль `ssh_run` (учёт, журнал, приёмник, стоп групп — общие).
    Коды возврата — тот же контракт с конвейером: 0 — закрыто всё, 75 — нет ёмкости, 1 — остались нерешённые."""
    groups = {}
    for g in S.GROUPS:
        q = SG.queue_of(g)
        if q:
            groups[g] = q
        else:
            print(f'  группа {g}: без очереди в rules/salad-groups.json — в прогон очереди не беру', flush=True)
    if not groups:
        print('!! транспорт queue: ни у одной группы SALAD_GROUP нет очереди (`queue` в rules/salad-groups.json)', flush=True)
        return 2
    slots = Slots(groups)
    slots.update(ready_by_group(list(groups)))
    print(f'очередь: группы {groups}, готовых машин {slots.ready}', flush=True)
    if not slots.total_ready():
        print('нет прогретых нод', flush=True)        # та же строка и тот же код, что у SSH: конвейер ждёт и повторит
        return S.EXIT_NO_CAPACITY
    reuse = ledger_open()
    stop = threading.Event()
    closed = [n_pre]
    t_start = time.time()

    def account(it: dict, r: dict, group: str, queue: str, qid: str | None, qj: dict) -> None:
        job = it['job']
        q_until = S.IQ.note(job, r)
        sink_ok = None
        if S.NH.infra_suspect(r):
            sink_ok = S.sink_poll(force=True)
            if not sink_ok:
                n_closed = js.close_rest(S._SINK['why'])
                print(f'!! ПРИЁМНИК не принимает ({S._SINK["why"]}) — закрываю остаток пачки ({n_closed}) как инфра-сбой',
                      flush=True)
                S.SH.alert_throttled(f'Меши: приёмник не принимает результаты — {S._SINK["why"]}. Пачка остановлена '
                                     f'(транспорт очереди), конвейер стащит и почистит.')
                stop.set()
        fault = S.NH.classify(r, sink_ok)
        ecls = S.NH.error_class(r)
        terminal = fault in (S.NH.FAULT_NONE, S.NH.FAULT_JOB) or bool(q_until)
        ev = qj.get('events') or []
        rec = {**r, 'node': 'queue', 'attempt': it['attempts'], 'fault': fault, 'group': group,
               'at': round(time.time()), **({'status': S.IQ.STATUS} if q_until else {})}
        # журнал — ДО `js.done` (как у SSH: `done` последнего задания отпускает `wait_all`)
        S.checkpoint({'sku': job.get('sku'), 'role': job.get('role'), 'status': rec.get('status'),
                      'attempt': it['attempts'], 'node': 'queue', 'prefix': r.get('prefix'),
                      'sec': (r.get('timings_s') or {}).get('total'), 'gpu': (r.get('gpu') or {}).get('name'),
                      'seed': job.get('seed'), 'instance': None, 'group': group,
                      'transport': 'queue', 'queue': queue, 'queue_job': qid,
                      'queue_status': qj.get('status'), 'queue_tries': sum(1 for e in ev if e.get('action') == 'started'),
                      'fault': fault, 'err_class': ecls, 'error': str(r.get('error') or '')[:700], 'at': round(time.time()),
                      **({'quarantine_until': round(q_until)} if q_until else {})})
        if r.get('status') in ('ok', 'cached'):
            S.mark_done(job.get('sku'), job.get('seed'))
        with S._lock:
            closed[0] += 1
            t = (r.get('timings_s') or {}).get('total')
            print(f'  [{closed[0]}/{len(jobs)}] {str(job.get("role")):14s} {rec.get("status", "?"):16s} '
                  f'{"" if t is None else str(t) + "с"} {group} {str(r.get("error") or "")[:60]}', flush=True)
        js.done(it, rec, terminal)

    def slot(n: int):
        while not stop.is_set():
            g = slots.acquire(stop)
            if g is None:
                return
            it = js.take(f'queue-{n}')
            if it is None:
                slots.release(g)
                return
            job, q = it['job'], groups[g]
            k = (job.get('sku'), int(job.get('seed') or 0))
            qid = None
            if k in reuse:                      # положено прошлым раздатчиком и не закрыто — доопрашиваем
                q0, qid0 = reuse.pop(k)
                if q0 in groups.values():
                    q, qid = q0, qid0
                    g0 = next(x for x, y in groups.items() if y == q0)
                    if g0 != g:                 # место занимает группа той очереди, где задание уже лежит
                        slots.swap(g, g0)
                        g = g0
                    print(f'  {k[0]}: задание очереди {qid[:8]} осталось от прошлого раздатчика — доопрашиваю', flush=True)
            if qid is None:
                qid, why = submit(q, job, {'sku': job.get('sku'), 'seed': k[1], 'attempt': it['attempts']})
                if not qid:
                    slots.release(g)
                    account(it, {'sku': job.get('sku'), 'status': 'transport_failed', 'error': f'queue/submit: {why}'},
                            g, q, None, {})
                    stop.wait(POLL_S)
                    continue
                ledger_write({'ev': 'submit', 'qid': qid, 'queue': q, 'group': g, 'sku': job.get('sku'), 'seed': k[1]})
            slots.moved()
            try:
                qj, r = follow(q, qid, job, stop, slots, js)
            finally:
                slots.release(g)
            ledger_write({'ev': 'end', 'qid': qid, 'queue': q, 'status': qj.get('status'), 'result': r.get('status')})
            account(it, r, g, q, qid, qj)

    def watch():
        """Готовые машины — раз в READY_POLL_S. Нет ни одной и ничего не движется STALL_S — закрываем остаток:
        ждущие снимаются (`follow`), конвейер получит 75 и подождёт ёмкость, как при SSH."""
        while not stop.wait(READY_POLL_S):
            if js.pending() == 0:
                return
            slots.update(ready_by_group(list(groups)))
            S.sink_poll()
            if slots.total_ready() == 0 and time.time() - slots.moved_at > STALL_S:
                n = js.close_rest(f'нет готовых машин {int(STALL_S)} с (очередь)')
                print(f'!! нет готовых машин {int(STALL_S / 60)} мин — закрываю остаток ({n}), ждущие в очереди снимаю',
                      flush=True)
                return

    n_slots = max(1, min(MAX_INFLIGHT, len(jobs) - n_pre))
    for n in range(n_slots):
        threading.Thread(target=slot, args=(n,), daemon=True).start()
    threading.Thread(target=watch, daemon=True).start()
    js.wait_all()
    stop.set()

    s = js.summary()
    rows = js.results()
    S.spool_unresolved(rows)
    state = {'transport': 'queue', 'queues': groups, 'at': time.time(), 'wall_s': round(time.time() - t_start),
             'summary': s, 'results': [{k: v for k, v in r.items() if k != 'job'} for r in rows]}
    json.dump(state, open(S.RESULTS, 'w'), ensure_ascii=False, indent=1)
    S.report(state)
    print('RUN_SUMMARY ' + json.dumps(s), flush=True)
    if not keep_alive:
        S.stop_group()
    if js.stalled:
        return S.EXIT_NO_CAPACITY
    return 0 if s['unresolved'] == 0 else 1


def selftest() -> int:
    """Без сети: разбор ответа очереди и журнал положенных заданий."""
    import tempfile
    fails = []

    def check(c, what):
        print(('  ✓ ' if c else '  ✗ ') + what)
        if not c:
            fails.append(what)

    j = {'sku': 's1', 'seed': 0}
    check(to_result({'status': 'succeeded', 'output': {'status': 'ok', 'sku': 's1'}}, j)['status'] == 'ok',
          'succeeded + ответ воркера ok → ok')
    check(to_result({'status': 'succeeded', 'output': {'status': 'failed', 'error': 'x'}}, j)['status'] == 'failed',
          'succeeded + логический отказ воркера → failed воркера (не успех)')
    check(to_result({'status': 'succeeded', 'output': '{"status": "cached"}'}, j)['status'] == 'cached',
          'ответ строкой JSON разбирается')
    r = to_result({'status': 'succeeded', 'output': None}, j)
    check(r['status'] == 'transport_failed' and r['error'].startswith('queue/no_output'), 'succeeded без ответа → транспорт')
    r = to_result({'status': 'failed', 'events': [{'action': 'started'}] * 4}, j)
    check(r['status'] == 'transport_failed' and 'попыток Salad 4' in r['error'], 'failed очереди → транспорт, попытки видны')
    global LEDGER
    keep = LEDGER
    with tempfile.TemporaryDirectory() as d:
        LEDGER = os.path.join(d, 'l.jsonl')
        ledger_write({'ev': 'submit', 'qid': 'a', 'queue': 'q', 'sku': 's1', 'seed': 0})
        ledger_write({'ev': 'submit', 'qid': 'b', 'queue': 'q', 'sku': 's2', 'seed': 1})
        ledger_write({'ev': 'end', 'qid': 'a'})
        check(ledger_open() == {('s2', 1): ('q', 'b')}, 'журнал: открыто только незакрытое задание')
    LEDGER = keep
    print('queue_run: ВСЁ ЗЕЛЁНОЕ' if not fails else f'queue_run: ПРОВАЛ {len(fails)}')
    return 1 if fails else 0


def main() -> int:
    a = sys.argv[1:]
    if '--selftest' in a:
        return selftest()
    if '--status' in a:
        q, qid = a[a.index('--status') + 1], a[a.index('--status') + 2]
        code, d = get(q, qid)
        print(f'HTTP {code}: статус {d.get("status")}, события '
              f'{[(e.get("action"), e.get("time")) for e in d.get("events") or []]}, ответ {str(d.get("output"))[:300]}')
        return 0 if code == 200 else 1
    if '--jobs' in a:
        q = a[a.index('--jobs') + 1]
        code, d = req('GET', f'/queues/{q}/jobs')
        for j in d.get('items') or []:
            print(f'  {j.get("id")} {j.get("status"):10s} {j.get("create_time")} {j.get("metadata")}')
        return 0 if code == 200 else 1
    if '--submit' in a:                 # канарейка (п.3): одно задание из файла, id — в журнал очереди
        q, path = a[a.index('--submit') + 1], a[a.index('--submit') + 2]
        job = json.load(open(path, encoding='utf-8'))
        qid, why = submit(q, job, {'sku': job.get('sku'), 'seed': job.get('seed', 0), 'by': 'canary'})
        if qid:
            ledger_write({'ev': 'submit', 'qid': qid, 'queue': q, 'group': 'canary', 'sku': job.get('sku'),
                          'seed': int(job.get('seed') or 0)})
        print(f'положено: {qid}' if qid else f'!! не положено: {why}')
        return 0 if qid else 1
    if '--follow' in a:                 # статус задания до конца, печать на каждой смене
        q, qid = a[a.index('--follow') + 1], a[a.index('--follow') + 2]
        seen, t0 = None, time.time()
        while True:
            code, d = get(q, qid)
            st = d.get('status') if code == 200 else f'HTTP {code}'
            if st != seen:
                seen = st
                print(f'{time.strftime("%H:%M:%S", time.gmtime())} UTC +{time.time() - t0:.0f} с: {st}', flush=True)
            if st in ('succeeded', 'failed', 'cancelled') or code == 404:
                r = to_result(d, {}) if code == 200 else {}
                print(f'итог воркера: {json.dumps(r, ensure_ascii=False)[:400]}')
                return 0 if r.get('status') in ('ok', 'cached') else 1
            time.sleep(POLL_S)
    if '--cancel' in a:
        q, qid = a[a.index('--cancel') + 1], a[a.index('--cancel') + 2]
        print(f'снять {qid}: HTTP {cancel(q, qid)}')
        return 0
    print(__doc__)
    return 0


if __name__ == '__main__':
    sys.exit(main())

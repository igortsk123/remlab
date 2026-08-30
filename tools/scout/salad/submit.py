#!/usr/bin/env python3
"""Отправка заданий пилота на ноды Salad и учёт денег. Запускается ЛОКАЛЬНО.

ПОЧЕМУ ПРЯМОЙ HTTP, А НЕ ОЧЕРЕДЬ ПЛАТФОРМЫ. Job Queue у Salad не привязалась: группа ссылается
на очередь, но у очереди `container_groups` остаётся пустым, PATCH отвечает 200 и ничего не
меняет, задание висит в `pending` часами при готовом инстансе (проверено 28.08). Ковырять
недокументированное поведение дороже, чем слать задания самим: воркер и так HTTP-сервис.
Взамен получаем то, что для пилота важнее — ошибку видно сразу, параллельность держим сами,
и нет зависимости от фичи, которая не работает.

Плата за это — ретраи теперь наши. Они дёшевы, потому что задание идемпотентно: повтор
сначала спрашивает у приёмника `complete.json` и, если работа сделана, GPU не тратит.

Считаем не «цену за генерацию», а фактические расходы: в знаменатель идут только годные
ассеты, в числитель — ВСЕ попытки, включая неуспешные.

  ~/venvs/scout/bin/python submit.py --dry-run              # что уйдёт, без отправки
  ~/venvs/scout/bin/python submit.py --canary               # одно задание, для проверки
  ~/venvs/scout/bin/python submit.py --run --limit 10 -j 2  # 10 заданий в 2 потока
  ~/venvs/scout/bin/python submit.py --report               # деньги и отказы
"""
import json
import os
import queue
import sys
import threading
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, '..', 'mesh-pilot-sample.json')
RESULTS = os.path.join(HERE, '..', 'mesh-pilot-results.json')

MAX_JOBS = 600            # предохранитель: пилот не должен незаметно стать полным прогоном
API = 'https://api.salad.com/api/public'
ORG = os.environ.get('SALAD_ORG', 'prodstore')
PROJECT = os.environ.get('SALAD_PROJECT', 'dmodel')
GROUP = os.environ.get('SALAD_GROUP', 'mesh-run3')

# Тарифы batch-приоритета, сверены по API 28.08 (`GET /organizations/<org>/gpu-classes`).
# Сравнивать карты можно только на ОДНОМ приоритете: на high те же 4090 стоят $0.30, и
# «карта дороже» окажется артефактом тарифа, а не железа.
RATE_PER_HOUR = {'RTX 4090': 0.16, 'RTX 5090': 0.25, 'RTX 3090': 0.09,
                 'RTX A5000': 0.09, 'RTX 3090 Ti': 0.10}
_lock = threading.Lock()


def key() -> str:
    k = os.environ.get('SALAD_API_KEY')
    if not k:
        sys.exit('нет SALAD_API_KEY (см. .memory_bank/_secrets/ACCESS.md)')
    return k


def api(path: str) -> dict:
    req = urllib.request.Request(f'{API}/organizations/{ORG}/projects/{PROJECT}/{path}',
                                 headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0'})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read() or b'{}')


def stop_group() -> None:
    """Гасим группу СРАЗУ после прогона.

    Тарификация посекундная и по состоянию инстанса, а не по загрузке карты: пока нода в
    `running`, счёт идёт, даже если заданий нет. Забытая нода 28.08 простояла 15 часов и
    съела ~$2.4, не сделав ни одной генерации. Остановка счёт прекращает полностью;
    образ остаётся в кэше сети (до 30 дней), поэтому следующий запуск быстрый.
    """
    req = urllib.request.Request(
        f'{API}/organizations/{ORG}/projects/{PROJECT}/containers/{GROUP}/stop',
        data=b'', method='POST', headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
        print(f'группа {GROUP} остановлена — счёт больше не идёт')
    except Exception as e:  # noqa: BLE001 — не смогли: СКАЖИ ГРОМКО, это деньги
        print(f'!! ГРУППУ НЕ ОСТАНОВИТЬ ({type(e).__name__}: {str(e)[:120]}) — '
              f'останови вручную в портале, иначе она тарифицируется', flush=True)


def endpoint() -> str:
    g = api(f'containers/{GROUP}')
    dns = (g.get('networking') or {}).get('dns')
    if not dns:
        sys.exit(f'у группы {GROUP} нет публичного адреса — создана без networking?')
    return f'https://{dns}'


def warm_ready(base: str) -> tuple[bool, dict]:
    """Прогрет ли воркер — спрашиваем ЕГО, а не платформу.

    Флаг готовности Salad оказался ненадёжен: он выставляется по пробе с ограниченным
    бюджетом (задержка максимум 1200с), а старт занимает ~35 минут. Инстанс при живом
    сервисе навсегда остаётся "неготовым". Тело /health говорит правду.
    """
    req = urllib.request.Request(f'{base}/health', headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read() or b'{}')
        return bool(d.get('warm')), d
    except Exception as e:  # noqa: BLE001
        return False, {'error': f'{type(e).__name__}: {str(e)[:150]}'}


def jobs_from_sample(limit: int | None = None) -> list[dict]:
    """Одно задание на (товар, seed): прерывание не должно убивать сразу три прогона."""
    s = json.load(open(SAMPLE, encoding='utf-8'))
    out = []
    for j in s['jobs']:
        for seed in j['seeds']:
            out.append({'sku': j['sku'], 'role': j['role'], 'image_url': j['image_url'],
                        'dims_cm': j['dims_cm'], 'seed': seed, 'strata': j['strata'],
                        'params': {}})
    if len(out) > MAX_JOBS:
        sys.exit(f'ПРЕДОХРАНИТЕЛЬ: заданий {len(out)} > лимита {MAX_JOBS}')
    return out[:limit] if limit else out


def send(base: str, job: dict, attempts: int = 3) -> dict:
    """Одно задание. Ретраим только сетевые сбои и 5xx: содержательный отказ воркера
    (мёртвое фото, брак вырезки) повтором не лечится и повторять его — жечь деньги."""
    body = json.dumps(job).encode()
    last = None
    for n in range(1, attempts + 1):
        t0 = time.time()
        req = urllib.request.Request(f'{base}/generate', data=body, method='POST',
                                     headers={'Salad-Api-Key': key(), 'User-Agent': 'remlab-mesh/1.0',
                                              'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=1200) as r:
                res = json.loads(r.read() or b'{}')
            res['attempts'] = n
            res['wall_s'] = round(time.time() - t0, 1)
            return res
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code}: {e.read()[:200].decode(errors="replace")}'
            if e.code < 500:
                break
        except Exception as e:  # noqa: BLE001 — сеть/таймаут: пробуем ещё
            last = f'{type(e).__name__}: {str(e)[:200]}'
        time.sleep(5 * n)
    return {'sku': job['sku'], 'status': 'transport_failed', 'error': last, 'attempts': attempts}


def run(limit: int | None, workers: int) -> None:
    base = endpoint()
    warm, h = warm_ready(base)
    print(f'адрес: {base} | прогрет: {warm} | {json.dumps(h, ensure_ascii=False)[:220]}')
    if not warm:
        sys.exit('воркер ещё греется (веса ~32 мин + прогон) — повтори позже')
    jobs = jobs_from_sample(limit)
    print(f'заданий: {len(jobs)} в {workers} поток(ов)')

    q: queue.Queue = queue.Queue()
    for j in jobs:
        q.put(j)
    results, t_start = [], time.time()

    def worker():
        while True:
            try:
                job = q.get_nowait()
            except queue.Empty:
                return
            r = send(base, job)
            with _lock:
                results.append({**r, 'role': job['role'], 'seed': job['seed']})
                n = len(results)
                st = r.get('status')
                t = (r.get('timings_s') or {}).get('total')
                print(f'  [{n}/{len(jobs)}] {job["role"]:14s} {st:16s} '
                      f'{"" if t is None else str(t) + "с"} {str(r.get("error") or "")[:80]}',
                      flush=True)
            q.task_done()

    ts = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    [t.start() for t in ts]
    [t.join() for t in ts]

    state = {'endpoint': base, 'at': time.time(), 'wall_s': round(time.time() - t_start),
             'results': results}
    json.dump(state, open(RESULTS, 'w'), ensure_ascii=False, indent=1)
    report(state)
    if '--keep-alive' not in sys.argv:
        stop_group()   # по умолчанию гасим: забыть выключенное нельзя, забыть включённое — легко


def report(state: dict | None = None) -> None:
    state = state or json.load(open(RESULTS, encoding='utf-8'))
    rows = state['results']
    ok = [r for r in rows if r.get('status') in ('ok', 'cached')]
    gpu_s, by_gpu = 0.0, {}
    for r in rows:
        t = (r.get('timings_s') or {}).get('total')
        if t:
            g = (r.get('gpu') or {}).get('name', '?')
            by_gpu[g] = by_gpu.get(g, 0.0) + float(t)
            gpu_s += float(t)
    cost = sum(s / 3600 * RATE_PER_HOUR.get(g, 0.16) for g, s in by_gpu.items())

    print(f'\nзаданий {len(rows)}, сгенерировано {len(ok)}, календарь {state.get("wall_s")}с')
    print(f'GPU-секунд {round(gpu_s)}, потрачено ${cost:.3f}, '
          f'${cost / max(len(ok), 1):.4f} за генерацию')
    print('это цена за ГЕНЕРАЦИЮ; цена за ГОДНЫЙ ассет — после приёмки '
          '(mesh_gate + mesh_gate_pbr), она и есть ответ пилота')

    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r.get('status', '?')] = by_status.get(r.get('status', '?'), 0) + 1
    print('статусы:', by_status)

    bad = [r for r in rows if r.get('status') == 'bad_cutout']
    if bad:
        print(f'брак вырезки ({len(bad)}) — лечится другой вырезкой, не повтором генерации:')
        for r in bad[:10]:
            print(f'   {r.get("role","?"):14s} {r["sku"]}  {str(r.get("error"))[:70]}')

    st = [r for r in rows if (r.get('timings_s') or {}).get('total')]
    if st:
        ts = sorted(float(r['timings_s']['total']) for r in st)
        sh = [float(r['timings_s'].get('shape', 0)) for r in st]
        pa = [float(r['timings_s'].get('paint', 0)) for r in st]
        pk = [float((r.get('gpu') or {}).get('paint_gb', 0)) for r in st]
        print(f'время на модель: медиана {ts[len(ts) // 2]:.0f}с '
              f'(форма {sum(sh) / len(sh):.0f}с, покраска {sum(pa) / len(pa):.0f}с)')
        print(f'пик VRAM на покраске: {max(pk):.1f} ГБ '
              f'(гипотеза стадийности: должно быть ≈21, а не 29)')


def main() -> None:
    if '--dry-run' in sys.argv:
        js = jobs_from_sample()
        roles: dict[str, int] = {}
        for j in js:
            roles[j['role']] = roles.get(j['role'], 0) + 1
        print(f'заданий к отправке: {len(js)} (лимит {MAX_JOBS})')
        print(json.dumps(roles, ensure_ascii=False, indent=1))
    elif '--canary' in sys.argv:
        run(1, 1)
    elif '--run' in sys.argv:
        lim = int(sys.argv[sys.argv.index('--limit') + 1]) if '--limit' in sys.argv else None
        w = int(sys.argv[sys.argv.index('-j') + 1]) if '-j' in sys.argv else 1
        run(lim, w)
    elif '--report' in sys.argv:
        report()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()

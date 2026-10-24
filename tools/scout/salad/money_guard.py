#!/usr/bin/env python3
"""СТОРОЖ ДЕНЕГ: гасит группу Salad, если работающие ноды долго ничего не выдают.

ЗАЧЕМ (владелец 02.09, перед сном: «главное сделай так чтобы деньги просто так не
откручивали»). За сутки 02.09 пул выдал 22 меша, простояв девять часов из пятнадцати: ноды
докладывали `Running`, платились по тарифу и не считали ничего (`gpu_seconds: 0.0` при uptime
279 минут). Конвейер такую ситуацию переживал молча — он ждал тёплых нод, а счётчик тикал.

ПРАВИЛО — В НОДО-МИНУТАХ, А НЕ В ЧАСАХ НА СТЕНЕ. Платим мы за время в состоянии `running`
(закачка образа у Salad не тарифицируется), поэтому и терпение считаем в нём: сколько
оплаченных нодо-минут прошло с последнего успешного меша. Здоровая нода отдаёт меш за ~3.5
минуты, так что бюджет в 120 нодо-минут молчания — это уже не «не повезло», а поломка.

Сторож ЖИВЁТ ОТДЕЛЬНО от конвейера: если конвейер упадёт или зависнет, ноды всё равно не
будут крутиться до утра впустую. Он только ГАСИТ группу (`/stop`), никогда не удаляет её и
не трогает задания — разбор утром по логу.
"""
from __future__ import annotations

import collections
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import salad_groups as SG  # noqa: E402 — тариф/цена группы: ОДИН источник (rules/salad-groups.json)
import mesh_price as MP    # noqa: E402 — ₽ за меш по группам за сутки (план mesh-15)
import proc_run as PR      # noqa: E402 — шаг оболочки без сирот
import sink_health as SH   # noqa: E402 — приёмник: красный = общая беда, а не вина нод
import ssh_run as SR       # noqa: E402 — ОДНА цепочка уборки приёмника на всех
JOURNAL = os.path.join(HERE, '..', 'mesh-run-progress.jsonl')
SNAPSHOT = os.path.expanduser('~/scout-scenes/salad-groups-snapshot.json')
HEARTBEAT_H = int(os.environ.get('MESH_GUARD_HEARTBEAT_H', '8'))   # UTC
STATE = os.path.expanduser('~/scout-scenes/mesh-money-guard.json')
# Запрет на подъём группы: его читает `batch_show.halt_reason()` и НЕ стартует группу, пока
# файл на месте. Снимает человек — руками, разобравшись в причине простоя.
HALT = os.path.expanduser('~/scout-scenes/mesh-group-halt.json')
# ПЕРЕПИСЬ ПУЛА: строка на каждый тик по каждой группе. Нужна, чтобы ответить на вопрос
# владельца «в какие часы на дешёвом тарифе дают машины» цифрами, а не на глаз: 03.09 данных
# хватило лишь на догадку (лучший час 21:00 измерен ОДИН раз, 42 часа наблюдений на трое
# суток при разном числе реплик). Сторож и так опрашивает API каждые 5 минут — дописать
# строку стоит ноль.
CENSUS = os.path.join(HERE, '..', 'mesh-pool-census.jsonl')
ALERT = os.path.join(HERE, '..', 'alert.sh')     # телеграм-бот remlab, ключи в `.env.alert`

# ОБВАЛ СВЯЗИ — ОТДЕЛЬНОЕ ПРАВИЛО (владелец 04.09: «если обрывы то гасить ноды и сообщать»).
# 03.09 в 20:31 у всех нод разом пошло `URLError: EOF occurred in violation of protocol` —
# 104 отказа подряд: приёмник на минуту стал недостижим, а машины продолжали считать за наши
# деньги и сдавать результат в никуда. Правило «40 минут тишины» это поймало, но лишь через
# 50 минут. Одинаковая ошибка у многих заданий — свидетельство более сильное, чем тишина, и
# ждать полчаса незачем.
BURST_N = int(os.environ.get('MESH_GUARD_BURST_N', '25'))      # отказов одного вида
BURST_MIN = float(os.environ.get('MESH_GUARD_BURST_MIN', '15'))  # за столько минут

# Сколько ОПЛАЧЕННЫХ нодо-минут молчания терпим. 120 ≈ 35 мешей, которые здоровый пул успел бы
# сделать за это время: если их нет, дело не в невезении.
BUDGET_NODE_MIN = float(os.environ.get('MESH_GUARD_NODE_MIN', '120'))
# ВТОРОЕ УСЛОВИЕ — ВРЕМЯ НА СТЕНЕ (03.09). Одних нодо-минут мало: они копятся тем быстрее, чем
# больше пул, и при десяти нодах бюджет в 120 выбирается за 12 минут — то есть прямо на прогреве,
# когда мешей ещё физически не может быть. При пятидесяти это 2.4 минуты. Гасим, только если
# молчание длится и по-настоящему долго: полный прогрев ноды укладывается в 5–8 минут, генерация
# меша — ещё 4, так что 40 минут тишины при живых нодах — это уже поломка, а не разогрев.
MIN_WALL_MIN = float(os.environ.get('MESH_GUARD_WALL_MIN', '40'))
TICK_S = float(os.environ.get('MESH_GUARD_TICK_S', '300'))
# РАННЯЯ ТРЕВОГА — ЗАДОЛГО ДО ГАШЕНИЯ (05.09, цель владельца «меш не дороже 1.5 ₽»).
# Порог гашения (120 нодо-минут + 40 мин тишины) — предохранитель от разорения, а не инструмент
# цены. Пока он ждёт, простой уже сделан: 05.09 пул простоял ~30 минут на переполненном приёмнике
# и превратил час по 0.8 ₽ за меш в час по 2.4–3.9 ₽. Цену портит НЕ тариф, а остановки: платим
# за `running` всегда, а мешей в это время нет. Поэтому кричим и пробуем лечить рано — на 40
# оплаченных нодо-минутах и 8 минутах тишины, то есть примерно втрое раньше гашения.
ALARM_NODE_MIN = float(os.environ.get('MESH_GUARD_ALARM_NODE_MIN', '40'))
ALARM_WALL_MIN = float(os.environ.get('MESH_GUARD_ALARM_WALL_MIN', '8'))
API = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers'
# СОСТАВ ГРУПП ПЕРЕЧИТЫВАЕМ НА КАЖДОМ ТИКЕ (T-20261020-24). Сторож — вечный цикл, а `SALAD_GROUP` он брал из окружения
# один раз на старте. 20.10 группы пересоздали (только A5000) и сменили salad.env: сторож с 19:00 опрашивал удалённые
# группы (HTTPError), писал «работающих нод нет — не платим» и новую группу с живой нодой не видел. Ключи по-прежнему
# из окружения крона; из файла берём ТОЛЬКО `SALAD_GROUP`.
SALAD_ENV = os.environ.get('MESH_ENV') or os.path.expanduser('~/scout-scenes/salad.env')
# СЛЕПОТА — НЕ «НЕ ПЛАТИМ». Ни одна группа не ответила столько тиков подряд → тревога: платим ли — неизвестно.
BLIND_N = int(os.environ.get('MESH_GUARD_BLIND_N', '3'))
# ПРИЧИНА ОСТАНОВКИ ПУЛА — ТОЛЬКО ПО ФАКТАМ (20.10: «вероятнее всего кончились кредиты» ввело в заблуждение ведущего
# и владельца, кредиты были). Про кредиты — только если старт вернул no_credits (`batch_show` пишет маркер, урок 404);
# остальное — что нашлось в журналах сторожей за последние CLUE_H часов.
CLUE_H = float(os.environ.get('MESH_GUARD_CLUE_H', '6'))
NO_CREDITS = os.path.expanduser('~/scout-scenes/mesh-no-credits.json')   # пишет batch_show на no_credits_available
IDLE_LOG = os.path.expanduser('~/scout-scenes/idle-guard.log')           # idle_guard.sh: «ГАШУ ГРУППЫ»
WINDOW_LOG = os.path.expanduser('~/remlab-logs/batch-window.log')        # batch_window.sh: «стоп <группа>»


def _api(path: str, method: str = 'GET') -> dict:
    req = urllib.request.Request(f'{API}/{path}', method=method,
                                 headers={'Salad-Api-Key': os.environ['SALAD_API_KEY'],
                                          'User-Agent': 'remlab-mesh/1.0'})
    if method == 'POST':
        req.data = b''
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read()
    return json.loads(body) if body else {}


def groups() -> list[str]:
    """Все группы под охраной (из SALAD_GROUP, без умолчания). Их бывает несколько: 03.09 владелец
    поставил рядом две по 10 реплик — на тарифах `batch` и `low` — чтобы сравнить их живьём."""
    return SG.groups_or_empty()


def env_groups(path: str | None = None) -> list[str] | None:
    """`SALAD_GROUP` из salad.env (последняя строка с ним; `export` и кавычки допускаются). None — файла нет или строки
    нет/пустая: тогда оставляем прежний список, а не сторожим пустоту."""
    try:
        with open(path or SALAD_ENV, encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    val = None
    for ln in lines:
        s = ln.strip()
        if s.startswith('export '):
            s = s[len('export '):].lstrip()
        if s.startswith('SALAD_GROUP='):
            val = s.split('=', 1)[1].strip().strip('"\'')
    gs = [g.strip() for g in (val or '').split(',') if g.strip()]
    return gs or None


def regroup(st: dict, group: str) -> dict:
    """Сменился состав групп — терпение считаем заново, а ОПЛАЧЕННЫЕ нодо-минуты переживают: это книга расходов, её
    обнулять нельзя (04.09). Тот же состав — состояние как есть."""
    if st.get('group') == group:
        return st
    return {'group': group, 'idle_node_min': 0.0, 'silent_since': 0.0,
            'last_seen_mesh': last_mesh_at(), 'paid_node_min': st.get('paid_node_min') or {},
            'price_floor': st.get('price_floor') or {}}


def blind_update(st: dict, counts: dict) -> bool:
    """Тик слепой — опрос ВСЕХ групп не удался (-1 у каждой). Счёт слепых тиков подряд — в `st`; ответила хоть одна —
    счёт и флаг тревоги сброшены."""
    blind = bool(counts) and all(v < 0 for v in counts.values())
    st['blind_ticks'] = st.get('blind_ticks', 0) + 1 if blind else 0
    if not blind:
        st['blind_alerted'] = False
    return blind


def _recent_line(path: str, needle: str, fmt: str, since: float) -> str:
    """Последняя строка журнала с `needle`, если её отметка времени (префикс в формате `fmt`, местное время, как пишет
    `date`) не старше `since`. Без года в формате — год текущий."""
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            tail = f.read().splitlines()[-300:]
    except OSError:
        return ''
    width = len(time.strftime(fmt, time.localtime(0)))
    for ln in reversed(tail):
        if needle not in ln:
            continue
        stamp = ln[:width]
        if '%Y' not in fmt:
            stamp, fmt = f'{time.localtime().tm_year} {stamp}', f'%Y {fmt}'
        try:
            at = time.mktime(time.strptime(stamp, fmt))
        except ValueError:
            return ''
        return ln.strip()[:160] if at >= since else ''
    return ''


def known_stops(gs: list[str], now: float | None = None) -> dict[str, str]:
    """Группы, которые стоят ПО ПЛАНУ, и почему: запрет подъёма по цене меша (`SG.PRICE_HALT`) или вне своего окна
    batch. Свой стоп-файл (`HALT`) проверяется отдельно — он гасит весь пул."""
    out: dict[str, str] = {}
    for g in gs:
        why = SG.price_halted(g)
        win = SG.info(g).get('window_utc')
        if why:
            out[g] = f'запрет по цене: {why}'
        elif win and not SG.allowed_now(g, now):
            out[g] = f'вне окна batch {int(win[0]):02d}–{int(win[1]):02d} UTC'
    return out


def stop_clues(now: float | None = None) -> tuple[bool, list[str]]:
    """Что известно о том, почему все группы стоят: (старт вернул no_credits?, факты из журналов за CLUE_H часов)."""
    now = now or time.time()
    since = now - CLUE_H * 3600
    clues: list[str] = []
    credits = False
    try:
        d = json.load(open(NO_CREDITS, encoding='utf-8'))
        if float(d.get('at') or 0) >= since:
            credits = True
            clues.append(f'старт группы в {time.strftime("%H:%M", time.localtime(float(d["at"])))} Salad отклонил: '
                         f'{d.get("why") or "no_credits_available"}')
    except Exception:  # noqa: BLE001 — маркера нет или битый: про кредиты молчим
        pass
    line = _recent_line(IDLE_LOG, 'ГАШУ ГРУППЫ', '%Y-%m-%d %H:%M', since)
    if line:
        clues.append(f'сторож простоя: «{line}»')
    line = _recent_line(WINDOW_LOG, ' стоп ', '%d.%m %H:%M', since)
    if line:
        clues.append(f'окно batch: «{line}»')
    try:
        w = (json.load(open(LEASE, encoding='utf-8')).get('waves') or [])[-1]
        if w.get('closed') and float(w['closed']) >= since:
            clues.append(f'волна закрыта в {time.strftime("%H:%M", time.localtime(float(w["closed"])))}: '
                         f'{w.get("why") or "без причины"}')
    except Exception:  # noqa: BLE001 — нет разрешения или волн: не довод
        pass
    if not conveyor_alive():
        clues.append('конвейер не запущен (штатный финал волны тоже гасит группы)')
    return credits, clues


def snapshot_groups(gs: list[str]) -> None:
    """Снимок живых групп (образ, тариф, реплики, карты) вместо мёртвого container-group.json,
    который никто не читал и который врал. И сверка: тариф из API ≠ тариф в rules/salad-groups.json
    → предупреждение — имя группы не контракт, а JSON правит окном и ценой."""
    snap = {}
    for g in gs:
        try:
            d = _api(g)
        except Exception as e:  # noqa: BLE001
            print(f'снимок группы {g}: не получен ({type(e).__name__})', flush=True)
            continue
        c = d.get('container') or {}
        snap[g] = {'image': c.get('image'), 'priority': d.get('priority'), 'replicas': d.get('replicas'),
                   'memory': (c.get('resources') or {}).get('memory'),
                   'gpu_classes': len((c.get('resources') or {}).get('gpu_classes') or []),
                   'at': round(time.time())}
        if d.get('priority') and SG.tier(g) not in ('?', d.get('priority')):
            print(f'!! группа {g}: тариф в API «{d.get("priority")}», а в rules/salad-groups.json '
                  f'«{SG.tier(g)}» — цена и окно считаются НЕВЕРНО, поправь JSON', flush=True)
    try:
        with open(SNAPSHOT, 'w', encoding='utf-8') as f:
            json.dump(snap, f, ensure_ascii=False, indent=1)
    except Exception:  # noqa: BLE001
        pass


def census(group: str) -> dict:
    """Состав группы по состояниям + запись в перепись. -1 в `running` — опрос не удался."""
    try:
        ins = _api(f'{group}/instances').get('instances') or []
    except Exception as e:  # noqa: BLE001 — сеть не должна гасить сторожа
        print(f'{time.strftime("%H:%M")} опрос {group} не удался ({type(e).__name__})',
              flush=True)
        return {'running': -1}
    by: dict[str, int] = {}
    for i in ins:
        st = str(i.get('state') or '?')
        by[st] = by.get(st, 0) + 1
    row = {'at': round(time.time()), 'group': group, 'total': len(ins), **by}
    try:
        with open(CENSUS, 'a', encoding='utf-8') as f:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    except Exception:  # noqa: BLE001 — перепись не должна ронять сторожа
        pass
    return by


def running_count(group: str) -> int:
    return census(group).get('running', 0)


def conveyor_alive() -> bool:
    """Жив ли конвейер. ЧЕРЕЗ `ps -eo args`, А НЕ `pgrep -f`: pgrep -f матчит собственную
    команду обёртки и убивает сессию агента (урок 399, гард в PreToolUse)."""
    try:
        r = subprocess.run(['ps', '-eo', 'args'], capture_output=True, text=True, timeout=20)
        return any('batch_show.py' in ln for ln in r.stdout.splitlines())
    except Exception:  # noqa: BLE001 — не смогли посмотреть: не утверждаем, что мёртв
        return True


def relief() -> None:
    """Попробовать вылечить простой самим: та же цепочка, что у конвейера (стащить → реестр →
    пометка в базе → чистка). Фоном, чтобы не задерживать тик сторожа; drain защищён своим
    замком, поэтому наложение на конвейер безопасно."""
    def work() -> None:
        for step, cmd in SR.SINK_RELIEF_CHAIN:
            rc, out = PR.run_step(cmd, timeout=1800)
            last = (out.strip().splitlines() or [''])[-1][:120]
            print(f'  [сторож: уборка] {step}: rc={rc} {last}', flush=True)
    threading.Thread(target=work, daemon=True).start()


def notify(text: str) -> bool:
    """Сообщение владельцу в телеграм. Молчаливая остановка пула стоила 10 часов простоя в
    ночь на 04.09: сторож честно погасил группы в 21:22, а узнали мы об этом утром.

    Возвращает, ДОСТАВЛЕНО ли (04.09): `alert.sh` теперь отдаёт 0 — TG принял, 1 — TG не ответил,
    2 — TG не настроен (тогда текст лёг в `refresh-alert.log`). Защитное действие сторожа от
    результата не зависит — гасим всё равно; но в логе должно быть видно, узнает ли человек.
    """
    try:
        r = subprocess.run(['bash', ALERT, text], timeout=30, capture_output=True, check=False)
        rc = r.returncode
    except Exception as e:  # noqa: BLE001 — не доставили: не повод ронять сторожа
        print(f'{time.strftime("%H:%M")} телеграм не отправлен ({type(e).__name__})', flush=True)
        return False
    if rc == 0:
        print(f'{time.strftime("%H:%M")} телеграм: доставлено', flush=True)
        return True
    why = 'TG не ответил' if rc == 1 else 'TG не настроен (.env.alert)' if rc == 2 else f'rc={rc}'
    print(f'{time.strftime("%H:%M")} телеграм: НЕ доставлено — {why}, текст в refresh-alert.log',
          flush=True)
    return False


def failure_burst() -> tuple[str, int]:
    """Одинаковая ошибка у многих заданий за последние BURST_MIN минут. ('', 0) — тихо."""
    now = time.time()
    seen: collections.Counter = collections.Counter()
    good = 0
    try:
        with open(JOURNAL, encoding='utf-8') as f:
            for line in f:
                if 'warmup' in line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get('kind'):   # служебные строки (прогрев, уход машины с малой ОЗУ) — не задания
                    continue
                if r.get('at', 0) < now - BURST_MIN * 60:
                    continue
                # `cached` — не новый меш, но живой транспорт и живой приёмник: в счёт «успехов»
                # для правила обвала он идёт (Codex 04.09 №10), а в `last_mesh_at` — нет.
                if r.get('status') in ('ok', 'cached'):
                    good += 1
                    continue
                ecls = str(r.get('err_class') or '')
                # подклассы транспорта/инфры группируем по классу, иначе подробные тексты
                # (`ssh/empty rc=255: …хвост…`) раздробили бы счётчик и обвал бы не собрался
                err = ecls if ecls.startswith(('ssh/', 'infra/')) else str(r.get('error') or '').strip()[:80]
                if err:
                    seen[err] += 1
    except FileNotFoundError:
        return '', 0
    if not seen:
        return '', 0
    err, n = seen.most_common(1)[0]
    # ОБВАЛ — ЭТО СООТНОШЕНИЕ, А НЕ ПРОСТО ЧИСЛО ОТКАЗОВ. Сама по себе частая ошибка аварии не
    # доказывает: «нет маркера в выводе» (обрыв SSH на отобранной ноде) — штатный спутник
    # дешёвого тарифа, за сутки её набирается три сотни, и пул при этом прекрасно работает
    # (проверено на журнале: рабочий час — 70 успехов при 23 таких отказах).
    # Требовать НОЛЬ успехов тоже неверно: в аварию 03.09 20:31 один запоздалый меш всё-таки
    # доехал, и правило с нулём её бы пропустило. Считаем аварией десятикратный перевес
    # отказов над успехами: тогда та авария — 78 против 1 — ловится, а рабочие часы нет.
    if n < BURST_N or good * 10 >= n:
        return '', 0
    return err, n


def last_mesh_at() -> float:
    """Время последнего успешного меша по журналу прогона. 0 — мешей вообще нет."""
    best = 0.0
    try:
        with open(JOURNAL, encoding='utf-8') as f:
            for line in f:
                if '"ok"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get('status') == 'ok' and r.get('at', 0) > best:
                    best = float(r['at'])
    except FileNotFoundError:
        pass
    return best


def repeats(since: float) -> tuple[int, str]:
    """Повторы после `since`: ok, чей job_id (хвост prefix) уже был ok раньше. job_id = вход + параметры + seed
    (`manifest.job_id`), а законная переделка меняет seed (владелец, перегон приёмки) или фото — значит, и job_id.
    Тот же job_id второй раз — всегда оплаченный повтор (план mesh-13: 29 % денег пула за 31.08–21.10).
    → (сколько, пример job_id)."""
    rows = []
    try:
        with open(JOURNAL, encoding='utf-8') as f:
            for line in f:
                if '"ok"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get('status') == 'ok':
                    rows.append(r)
    except FileNotFoundError:
        return 0, ''
    seen, n, ex = set(), 0, ''
    for r in sorted(rows, key=lambda r: float(r.get('at') or 0)):
        j = str(r.get('prefix') or '').rsplit('/', 1)[-1]
        if not j:
            continue
        if j in seen and float(r.get('at') or 0) > since:
            n += 1
            ex = ex or j
        seen.add(j)
    return n, ex


def heartbeat(st: dict, gs: list[str], counts: dict, sink: dict) -> None:
    """Раз в сутки в HEARTBEAT_H UTC — короткая сводка владельцу. Ловит и «оповещения молча
    сломаны»: не пришёл пульс — значит сторож или телеграм мертвы."""
    now = time.gmtime()
    today = time.strftime('%Y-%m-%d', now)
    if now.tm_hour != HEARTBEAT_H or st.get('heartbeat_day') == today:
        return
    day_ago = time.time() - 86400
    ok = cached = 0
    try:
        with open(JOURNAL, encoding='utf-8') as f:
            for line in f:
                if '"ok"' not in line and '"cached"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get('at', 0) >= day_ago:
                    ok += r.get('status') == 'ok'
                    cached += r.get('status') == 'cached'
    except FileNotFoundError:
        pass
    paid = st.get('paid_node_min') or {}
    usd = sum(paid.get(g, 0) / 60 * (SG.price(g) or 0) for g in paid)
    rub = usd * SG.usd_rub()
    halt = ''
    try:
        h = json.load(open(HALT, encoding='utf-8'))
        halt = f' ЗАПРЕТ стоит: {h.get("why")}'
    except Exception:  # noqa: BLE001
        pass
    rep, _ = repeats(day_ago)
    try:   # ₽ ЗА МЕШ ПО ГРУППАМ ЗА СУТКИ (план mesh-15) — без окна сторожа, как есть: пульс — отчёт, а не суд
        price = MP.summary(MP.by_group(gs, census=CENSUS, journal=JOURNAL))
    except Exception as e:  # noqa: BLE001 — сводка не должна ронять пульс
        price = f'не посчитано ({type(e).__name__})'
    notify(f'Пульс мешей: за сутки ok {ok}, из кэша {cached}, повторы {rep}; работает нод {sum(v for v in counts.values() if v > 0)} '
           f'{counts}; оплачено всего {sum(paid.values()) / 60:.1f} нодо-ч ≈ ${usd:.2f} ({rub:.0f} ₽); '
           f'₽ за меш по группам за сутки: {price}; '
           f'приёмник {"ок" if sink["ok"] else "КРАСНЫЙ: " + sink["why"]}, свободно {sink.get("free_gb", 0):.1f} ГБ.{halt}')
    st['heartbeat_day'] = today


LEASE = os.path.expanduser('~/scout-scenes/wave-lease.json')   # разрешение владельца на волну (`wave_guard.py`)


def price_tick(st: dict, gs: list[str], now: float | None = None) -> list[str]:
    """ПОТОЛОК ЦЕНЫ МЕША (план mesh-15, владелец 21.10: «меш не дороже 1,5 рубля»). Каждый тик — ₽ за меш по группам за
    окно правила (`mesh_price.by_group`); дорогая группа гасится ОДНА (не весь пул, как у правил тишины и обвала), до
    остановки — запрет её подъёма в `SG.PRICE_HALT` (иначе конвейер или расписание batch поднимут её обратно). Снимает
    запрет человек. → список погашенных за тик.

    ОКНО ГРУППЫ — НЕ РАНЬШЕ `price_floor[группа]`: первого тика, когда сторож её увидел, и последнего гашения по цене.
    История до запуска правила не судится (20.10–21.10 A5000 платила за повторы — дефект конвейера mesh-13, не группы:
    по новым мешам 1,70 ₽, по разным 0,80 ₽, `~/remlab-logs/t21-01-cost.md`); после снятия запрета — суд заново."""
    now = now or time.time()
    rule = SG.price_ceiling()
    if not rule:
        return []
    floor = st.setdefault('price_floor', {})
    held = st.setdefault('price_held', [])
    for g in gs:
        floor.setdefault(g, now)
        # ЗАПРЕТ СНЯЛИ — СУД ЗАНОВО С ЭТОЙ МИНУТЫ (T-20261022-10/4): `floor` гашения остаётся в прошлом, и окно `judge_after_h`
        # считалось бы от него — группа, простоявшая под запретом сутки, шла бы под суд на первом же нодо-часе
        if SG.price_halted(g):
            if g not in held:
                held.append(g)
        elif g in held:
            held.remove(g)
            floor[g] = now
            print(f'{time.strftime("%H:%M")} запрет цены {g} снят — суд заново с этой минуты', flush=True)
    res = MP.by_group(gs, now, floor, CENSUS, JOURNAL)
    st['price'] = {'at': round(now), 'groups': res}
    hour = time.strftime('%Y-%m-%d %H', time.gmtime(now))
    if st.get('price_log_h') != hour:          # строка в журнал раз в час — цифра видна без запроса
        st['price_log_h'] = hour
        print(f'{time.strftime("%H:%M")} ₽ за меш по группам (потолок {rule["rub_per_mesh"]} ₽): {MP.summary(res)}',
              flush=True)
    stopped = []
    for g, v in res.items():
        if v['state'] != 'дорого' or SG.price_halted(g):
            continue
        per = f'{v["per_mesh"]:.2f} ₽' if v['per_mesh'] is not None else 'ни одного нового'
        hours = (now - max(float(floor.get(g, now)), now - float(rule.get('window_h') or 24) * 3600)) / 3600
        why = (f'меш {per} при потолке {v["ceil"]} ₽: потрачено {v["rub"]:.1f} ₽ ({v["node_min"]:.0f} нодо-мин), '
               f'новых мешей {v["meshes"]} за {hours:.1f} ч (остановлено {time.strftime("%d.%m %H:%M")})')
        print(f'{time.strftime("%H:%M")} !! ДОРОГАЯ ГРУППА {g}: {why}', flush=True)
        try:                                   # ЗАПРЕТ ДО ОСТАНОВКИ — как у общего стоп-файла (ночь на 03.09)
            try:
                d = json.load(open(SG.PRICE_HALT, encoding='utf-8'))
            except (OSError, ValueError):
                d = {}
            d = d if isinstance(d, dict) else {}
            d[g] = {'why': why, 'at': round(now), **{k: v[k] for k in ('rub', 'per_mesh', 'meshes', 'node_min')}}
            tmp = SG.PRICE_HALT + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False, indent=1)
            os.replace(tmp, SG.PRICE_HALT)
        except OSError as e:
            print(f'{time.strftime("%H:%M")} !! не смог записать запрет цены ({e}) — конвейер может поднять {g} обратно',
                  flush=True)
        try:
            _api(f'{g}/stop', 'POST')
            census(g)                          # финальная точка переписи: интервал оплаты закрыт здесь
            print(f'{time.strftime("%H:%M")} группа {g} остановлена по цене меша', flush=True)
        except Exception as e:  # noqa: BLE001
            print(f'{time.strftime("%H:%M")} !! НЕ СМОГ ПОГАСИТЬ {g} ({type(e).__name__}: {e}) — нужен человек', flush=True)
        floor[g] = now                         # снимут запрет — судим заново, а не по тем же суткам
        notify(f'Меши: группа {g} ОСТАНОВЛЕНА — дорого. {why}. Остальные группы работают. Поднять: убрать {g} из '
               f'{SG.PRICE_HALT} — но сперва разберись, почему меш дорогой (сбои, простой, повторы).')
        stopped.append(g)
    return stopped


def paid_usd(st: dict) -> float:
    """Оплачено всего, $ — по книге расходов сторожа (нодо-минуты в `running` × тариф группы). Оценка: тариф из
    `rules/salad-groups.json`, неизвестный тариф — 0 (тогда выключатель по сумме сработает позже — пишем в журнал)."""
    paid = st.get('paid_node_min') or {}
    return sum(paid[g] / 60 * (SG.price(g) or 0) for g in paid)


def budget_breach(st: dict, lease: dict | None) -> str:
    """Потолок волны выбран? '' — нет. Волна открыта, пока у последней записи `waves` нет `closed`; потрачено =
    книга расходов сейчас − отметка на старте (`usd_mark`). Чистая функция (план conv-11 п.4)."""
    waves = (lease or {}).get('waves') or []
    if not waves or waves[-1].get('closed') or 'usd_cap' not in waves[-1]:
        return ''
    w = waves[-1]
    spent = paid_usd(st) - float(w.get('usd_mark', 0))
    if spent < float(w['usd_cap']):
        return ''
    return f'ПОТОЛОК ВОЛНЫ: потрачено ≈ ${spent:.2f} из разрешённых ${float(w["usd_cap"]):.2f}'


def load() -> dict:
    try:
        return json.load(open(STATE, encoding='utf-8'))
    except Exception:  # noqa: BLE001 — нет состояния или битое: начинаем с чистого
        return {}


def save(d: dict) -> None:
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(d, f)
    os.replace(tmp, STATE)


def single_instance() -> object | None:
    """Ровно один сторож. Крон зовёт его раз в 5 минут, а `main()` — вечный цикл: без замка к 14.10 их висело
    420 (4 ГБ памяти), и в 08:00 UTC каждый слал свой «пульс» — 466 одинаковых сообщений владельцу. Замок держится,
    пока жив процесс; следующий вызов крона видит его и тихо выходит — крон остаётся «воскрешателем» упавшего."""
    import fcntl  # noqa: PLC0415
    f = open(STATE + '.lock', 'w')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def main() -> int:
    lock = single_instance()
    if lock is None:
        return 0                            # другой сторож уже на посту — молча выходим (не засоряем журнал)
    gs = env_groups() or groups()
    if not gs or not os.environ.get('SALAD_API_KEY'):
        print('нет SALAD_GROUP или SALAD_API_KEY', flush=True)
        return 2
    group = ','.join(gs)
    st = regroup(load(), group)
    snapshot_groups(gs)
    print(f'сторож денег: группы {group}, бюджет молчания {BUDGET_NODE_MIN:.0f} нодо-минут '
          f'И не меньше {MIN_WALL_MIN:.0f} мин тишины, тик {TICK_S / 60:.0f} мин', flush=True)
    while True:
        new = env_groups()
        if new and new != gs:
            print(f'{time.strftime("%H:%M")} состав групп сменился: {group} → {",".join(new)} (salad.env) — '
                  f'сторожу новые, терпение заново, книга расходов сохранена', flush=True)
            gs, group = new, ','.join(new)
            os.environ['SALAD_GROUP'] = group
            st = regroup(st, group)
            snapshot_groups(gs)
        counts = {g: running_count(g) for g in gs}
        n = sum(v for v in counts.values() if v > 0)
        blind = blind_update(st, counts)
        if blind:
            print(f'{time.strftime("%H:%M")} !! опрос всех групп не удался ({group}) — платим ли, не знаю: '
                  f'слепой тик {st["blind_ticks"]} из {BLIND_N}', flush=True)
            if st['blind_ticks'] >= BLIND_N and not st.get('blind_alerted'):
                st['blind_alerted'] = True
                print(f'{time.strftime("%H:%M")} !! СТОРОЖ СЛЕП: {st["blind_ticks"]} тиков подряд ни одна группа '
                      f'не ответила', flush=True)
                notify(f'🔴 Меши: сторож денег СЛЕП — {st["blind_ticks"]} опросов подряд ни одна группа Salad ({group}) '
                       f'не ответила. Платим ли сейчас — неизвестно: проверь портал Salad и SALAD_GROUP в salad.env '
                       f'(удалённая или переименованная группа?).')
        # ПРИЁМНИК — раз в тик. Красный приёмник — общая беда: оповестить (дроссель — общий с
        # конвейером), в стоп-файле пометить `shared_infra`, чтобы человек не искал вину в нодах.
        sink = SH.check()
        if not sink['ok']:
            print(f'{time.strftime("%H:%M")} приёмник красный: {sink["why"]}', flush=True)
            if n > 0:
                SH.alert_throttled(f'Меши: приёмник не принимает — {sink["why"]}; работает нод {n}. '
                                   f'Конвейер сам стаскивает и чистит; если не проходит — нужен человек.')
        heartbeat(st, gs, counts, sink)
        # ОПЛАЧЕННОЕ ВРЕМЯ, А НЕ ПОЛЕЗНОЕ (владелец 03.09: «за видеокарты мы платим по часам их
        # работы»). Счёт по секундам генерации занижал цену меша вдвое — 0.0079 против 0.0151,
        # потому что не видел ни прогрева (7 мин на ноду), ни пауз, ни нод, которые часами стоят
        # прогретыми без единого задания. Копим здесь, потому что сторож и так опрашивает группы
        # каждые 5 минут; этот счётчик НИКОГДА не обнуляется — по нему считает `tier_compare`.
        paid = st.setdefault('paid_node_min', {})
        for g, c in counts.items():
            if c > 0:
                paid[g] = round(paid.get(g, 0.0) + c * (TICK_S / 60.0), 1)
        # ЧЕТВЁРТЫЙ ПОВОД — ЦЕНА МЕША (план mesh-15): гасит одну дорогую группу, не пул; сбой подсчёта не роняет сторожа
        try:
            for g in price_tick(st, gs):
                counts[g] = 0
            n = sum(v for v in counts.values() if v > 0)
        except Exception as e:  # noqa: BLE001
            print(f'{time.strftime("%H:%M")} !! цена меша не посчитана ({type(e).__name__}: {e})', flush=True)
        mesh_at = last_mesh_at()
        # ПОВТОРЫ — строка в лог за каждый тик, где они появились (план mesh-13). Отсчёт — с прошлой проверки;
        # первый тик после старта сторожа историю не судит.
        rep_since = st.setdefault('repeats_at', time.time())
        if mesh_at > rep_since:
            rep, rep_ex = repeats(rep_since)
            if rep:
                print(f'{time.strftime("%H:%M")} !! ПОВТОРЫ: {rep} меш(ей) сделаны второй раз — тот же вход и seed '
                      f'(пример {rep_ex}); курсор или `<снимок>.done` не сработали', flush=True)
            st['repeats_at'] = mesh_at
        if mesh_at > st.get('last_seen_mesh', 0):
            # Пошли меши — терпение обнуляем целиком: пул работает, платим за дело.
            if st['idle_node_min'] > 0:
                print(f'{time.strftime("%H:%M")} меши пошли — счётчик молчания сброшен '
                      f'(был {st["idle_node_min"]:.0f} нодо-мин)', flush=True)
            st['idle_node_min'] = 0.0
            st['silent_since'] = 0.0
            st['last_seen_mesh'] = mesh_at
            st['alarmed'] = False       # эпизод простоя закончился — тревожить можно снова
            st['down_alerted'] = False  # пул ожил: о следующем падении сказать снова
        elif n > 0:
            st['idle_node_min'] += n * (TICK_S / 60.0)
            if not st.get('silent_since'):
                st['silent_since'] = time.time()
            wall = (time.time() - st['silent_since']) / 60.0
            print(f'{time.strftime("%H:%M")} работающих нод {n} {counts}, мешей нет: '
                  f'{st["idle_node_min"]:.0f} из {BUDGET_NODE_MIN:.0f} нодо-минут, '
                  f'тишина {wall:.0f} из {MIN_WALL_MIN:.0f} мин', flush=True)
        elif n == 0 and not blind:
            # Никто не работает — деньги не идут, терпение не тратим. И ЧАСЫ ТИШИНЫ ТОЖЕ СБРАСЫВАЕМ
            # (04.09): условие «40 минут тишины» существует, чтобы не гасить пул на прогреве, то
            # есть меряет молчание, ПОКА МЫ ПЛАТИМ. Без сброса выходило так: 12:36 кончились кредиты
            # Salad, все группы упали, час никто не работал — а часы тишины продолжали идти. В 13:52
            # поднялась одна нода, счётчик нодо-минут мгновенно добрал бюджет при уже «набежавших»
            # 75 минутах, и сторож записал запрет на подъём. Гасить было нечего: пула не было вовсе,
            # а человеку осталось разбираться с запретом, которому нет причины.
            deaf = [g for g, v in counts.items() if v < 0]
            deaf_s = f' (не ответили: {",".join(deaf)})' if deaf else ''
            if st.get('silent_since'):
                print(f'{time.strftime("%H:%M")} работающих нод нет — не платим{deaf_s}; часы тишины сброшены '
                      f'(шли {(time.time() - st["silent_since"]) / 60:.0f} мин)', flush=True)
                st['silent_since'] = 0.0
            else:
                print(f'{time.strftime("%H:%M")} работающих нод нет — не платим{deaf_s}, жду', flush=True)
            # ПУЛ ЛЁГ САМ ПО СЕБЕ — ЭТО ТОЖЕ ПОВОД КРИЧАТЬ (05.09). 15:20 на Salad кончились
            # кредиты, все три группы разом стали `stopped`, машин ноль. Сторож честно писал
            # «не платим, жду» и молчал — тревога у него привязана к тому, что мы ПЛАТИМ, а тут
            # мы как раз не платим. Узнали случайно, при ручной проверке, через 20 минут.
            # Молчание тут стоит не денег, а простоя: пока никто не знает, никто и не пополнит.
            # Стоп-файл сторожа — исключение: тогда пул погасили мы сами и причина известна.
            if not st.get('down_alerted') and not os.path.exists(HALT):
                stopped = []
                for g in gs:
                    try:
                        stopped.append((_api(g).get('current_state') or {}).get('status') == 'stopped')
                    except Exception:  # noqa: BLE001 — не смогли спросить: не выдумываем диагноз
                        stopped.append(False)
                planned = known_stops(gs)
                if stopped and all(stopped) and set(gs) <= set(planned):
                    # ВСЕ СТОЯТ ПО ПЛАНУ (T-20261024-01): 24.10 00:42 сторож цены сам остановил mesh-low-10, batch был
                    # вне окна — а в 00:47 ушла тревога «причина неизвестна». Тревога о цене уже была; здесь — строка.
                    st['down_alerted'] = True
                    print(f'{time.strftime("%H:%M")} пул стоит по плану: '
                          + '; '.join(f'{g} — {w}' for g, w in planned.items()), flush=True)
                elif stopped and all(stopped):
                    st['down_alerted'] = True
                    # ДИАГНОЗ — ТОЛЬКО ПО ФАКТАМ (T-20261020-24): про кредиты — лишь когда старт вернул no_credits
                    credits, clues = stop_clues()
                    clues = [f'{g} — {w}' for g, w in planned.items()] + clues
                    head = 'Salad отклонил старт: нет кредитов' if credits else 'причина неизвестна'
                    known = '; '.join(clues) or 'в журналах сторожей причины не нашёл'
                    print(f'{time.strftime("%H:%M")} !! ВСЕ ГРУППЫ ОСТАНОВЛЕНЫ, запрета сторожа нет — {head}. '
                          f'Известно: {known}', flush=True)
                    notify(f'Меши: пул стоит — все группы Salad остановлены ({group}), машин ноль, запрета '
                           f'сторожа нет. ' + ('Salad отклонил старт: нет кредитов — пополните баланс, конвейер '
                                              'поднимет группы сам. ' if credits else 'Причина неизвестна. ')
                           + f'Известно: {known}. Деньги сейчас не тратятся.')
        wall_min = (time.time() - st['silent_since']) / 60.0 if st.get('silent_since') else 0.0
        # РАННЯЯ ТРЕВОГА: платим и не производим — сказать человеку и попробовать вылечить самим,
        # не дожидаясь порога гашения. Один раз на эпизод простоя (флаг снимается, когда пошли меши).
        if (n > 0 and not st.get('alarmed')
                and st['idle_node_min'] >= ALARM_NODE_MIN and wall_min >= ALARM_WALL_MIN):
            st['alarmed'] = True
            alive = conveyor_alive()
            why = (f'приёмник: {sink["why"]}' if not sink['ok']
                   else 'конвейер не запущен' if not alive else 'причина неясна')
            print(f'{time.strftime("%H:%M")} !! ПЛАТИМ И НЕ ПРОИЗВОДИМ: {n} нод, '
                  f'{st["idle_node_min"]:.0f} нодо-минут, тишина {wall_min:.0f} мин — {why}', flush=True)
            notify(f'Меши: платим и не производим. Нод {n}, тишина {wall_min:.0f} мин, '
                   f'{st["idle_node_min"]:.0f} оплаченных нодо-минут без меша. {why.capitalize()}. '
                   f'Гашение — на {BUDGET_NODE_MIN:.0f} нодо-минутах.')
            if not sink['ok']:
                relief()
        save(st)
        burst_err, burst_n = failure_burst() if n > 0 else ('', 0)
        # ДВА НЕЗАВИСИМЫХ ПОВОДА ГАСИТЬ:
        #  1) тишина: оплаченные нодо-минуты И долгий простой по часам (медленный, надёжный);
        #  2) обвал: одна и та же ошибка у многих заданий (быстрый — ловит сетевые аварии,
        #     когда ноды считают, но результат сдать не могут).
        stop_why = ''
        try:
            lease = json.load(open(LEASE, encoding='utf-8')) if os.path.exists(LEASE) else None
        except Exception:  # noqa: BLE001 — битое разрешение не отменяет остальные правила
            lease = None
        over = budget_breach(st, lease) if n > 0 else ''
        if over:
            # Третий повод (conv-11): деньги, разрешённые владельцем на волну, выбраны — гасим, даже если меши идут.
            stop_why = over
        elif burst_n:
            stop_why = (f'ОБВАЛ СВЯЗИ: {burst_n} отказов подряд с одной ошибкой за '
                        f'{BURST_MIN:.0f} мин — «{burst_err}»')
        elif st['idle_node_min'] >= BUDGET_NODE_MIN and wall_min >= MIN_WALL_MIN:
            stop_why = (f'{st["idle_node_min"]:.0f} нодо-минут и {wall_min:.0f} мин тишины '
                        f'без единого меша')
        if stop_why:
            why = f'{stop_why} (остановлено {time.strftime("%d.%m %H:%M")})'
            print(f'{time.strftime("%H:%M")} !! ГАШУ ПУЛ: {why} · группы {group}', flush=True)
            notify(f'Меши: пул ОСТАНОВЛЕН. {why}. Работало нод: {n}. ' + (
                'Деньги, разрешённые на волну, выбраны; следующая волна — по новому разрешению.' if over else
                'Поднять: rm ~/scout-scenes/mesh-group-halt.json — но сперва разберись, почему не было мешей.'))
            # СТОП-ФАЙЛ ПИШЕМ ДО ОСТАНОВКИ. Иначе конвейер успеет поднять группу обратно —
            # ровно так и вышло в ночь на 03.09: сторож погасил, `ensure_group_started` через
            # минуту поднял, сторож (тогда одноразовый) вышел, и семь часов ноды крутились
            # впустую. Снимает запрет человек, разобравшись в причине.
            try:
                with open(HALT, 'w', encoding='utf-8') as f:
                    json.dump({'why': why, 'group': group, 'at': time.time(),
                               'kind': 'budget' if over else 'shared_infra' if not sink['ok'] else 'silence',
                               'sink': sink}, f, ensure_ascii=False)
                print(f'{time.strftime("%H:%M")} запрет на подъём записан: {HALT}', flush=True)
            except Exception as e:  # noqa: BLE001
                print(f'{time.strftime("%H:%M")} !! не смог записать запрет ({e}) — конвейер '
                      f'может поднять группу обратно', flush=True)
            for g in gs:
                try:
                    _api(f'{g}/stop', 'POST')
                    census(g)            # финальная точка переписи: интервал оплаты закрыт здесь
                    print(f'{time.strftime("%H:%M")} группа {g} остановлена, деньги не идут',
                          flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f'{time.strftime("%H:%M")} !! НЕ СМОГ ПОГАСИТЬ {g} '
                          f'({type(e).__name__}: {e}) — нужен человек', flush=True)
            # НЕ ВЫХОДИМ. Сторож остаётся на посту: группу могут поднять руками или автостартом,
            # и тогда сторожить снова некому. Счётчик обнуляем — следующий бюджет считается
            # заново, с момента подъёма.
            st['idle_node_min'] = 0.0
            st['silent_since'] = 0.0
            save(st)
        time.sleep(TICK_S)


if __name__ == '__main__':
    sys.exit(main())

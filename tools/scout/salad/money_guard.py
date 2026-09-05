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
    notify(f'Пульс мешей: за сутки ok {ok}, из кэша {cached}; работает нод {sum(v for v in counts.values() if v > 0)} '
           f'{counts}; оплачено всего {sum(paid.values()) / 60:.1f} нодо-ч ≈ ${usd:.2f} ({rub:.0f} ₽); '
           f'приёмник {"ок" if sink["ok"] else "КРАСНЫЙ: " + sink["why"]}, свободно {sink.get("free_gb", 0):.1f} ГБ.{halt}')
    st['heartbeat_day'] = today


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


def main() -> int:
    gs = groups()
    if not gs or not os.environ.get('SALAD_API_KEY'):
        print('нет SALAD_GROUP или SALAD_API_KEY', flush=True)
        return 2
    group = ','.join(gs)
    st = load()
    if st.get('group') != group:            # сменился состав групп — терпение считаем заново,
        # а ОПЛАЧЕННЫЕ нодо-минуты переживают: это книга расходов, её обнулять нельзя (04.09)
        st = {'group': group, 'idle_node_min': 0.0, 'silent_since': 0.0,
              'last_seen_mesh': last_mesh_at(), 'paid_node_min': st.get('paid_node_min') or {}}
    snapshot_groups(gs)
    print(f'сторож денег: группы {group}, бюджет молчания {BUDGET_NODE_MIN:.0f} нодо-минут '
          f'И не меньше {MIN_WALL_MIN:.0f} мин тишины, тик {TICK_S / 60:.0f} мин', flush=True)
    while True:
        counts = {g: running_count(g) for g in gs}
        n = sum(v for v in counts.values() if v > 0)
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
        mesh_at = last_mesh_at()
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
        elif n == 0:
            # Никто не работает — деньги не идут, терпение не тратим. И ЧАСЫ ТИШИНЫ ТОЖЕ СБРАСЫВАЕМ
            # (04.09): условие «40 минут тишины» существует, чтобы не гасить пул на прогреве, то
            # есть меряет молчание, ПОКА МЫ ПЛАТИМ. Без сброса выходило так: 12:36 кончились кредиты
            # Salad, все группы упали, час никто не работал — а часы тишины продолжали идти. В 13:52
            # поднялась одна нода, счётчик нодо-минут мгновенно добрал бюджет при уже «набежавших»
            # 75 минутах, и сторож записал запрет на подъём. Гасить было нечего: пула не было вовсе,
            # а человеку осталось разбираться с запретом, которому нет причины.
            if st.get('silent_since'):
                print(f'{time.strftime("%H:%M")} работающих нод нет — не платим; часы тишины сброшены '
                      f'(шли {(time.time() - st["silent_since"]) / 60:.0f} мин)', flush=True)
                st['silent_since'] = 0.0
            else:
                print(f'{time.strftime("%H:%M")} работающих нод нет — не платим, жду', flush=True)
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
                if stopped and all(stopped):
                    st['down_alerted'] = True
                    print(f'{time.strftime("%H:%M")} !! ВСЕ ГРУППЫ ОСТАНОВЛЕНЫ, а запрета сторожа '
                          f'нет — вероятнее всего кончились кредиты Salad', flush=True)
                    notify('Меши: пул стоит — ВСЕ группы Salad остановлены, машин ноль, а запрета '
                           'сторожа нет. Чаще всего это кончившиеся кредиты Salad: пополните баланс, '
                           'конвейер поднимет группы сам. Деньги сейчас не тратятся.')
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
        if burst_n:
            stop_why = (f'ОБВАЛ СВЯЗИ: {burst_n} отказов подряд с одной ошибкой за '
                        f'{BURST_MIN:.0f} мин — «{burst_err}»')
        elif st['idle_node_min'] >= BUDGET_NODE_MIN and wall_min >= MIN_WALL_MIN:
            stop_why = (f'{st["idle_node_min"]:.0f} нодо-минут и {wall_min:.0f} мин тишины '
                        f'без единого меша')
        if stop_why:
            why = f'{stop_why} (остановлено {time.strftime("%d.%m %H:%M")})'
            print(f'{time.strftime("%H:%M")} !! ГАШУ ПУЛ: {why} · группы {group}', flush=True)
            notify(f'Меши: пул ОСТАНОВЛЕН. {why}. Работало нод: {n}. '
                   f'Поднять: rm ~/scout-scenes/mesh-group-halt.json — но сперва разберись, '
                   f'почему не было мешей.')
            # СТОП-ФАЙЛ ПИШЕМ ДО ОСТАНОВКИ. Иначе конвейер успеет поднять группу обратно —
            # ровно так и вышло в ночь на 03.09: сторож погасил, `ensure_group_started` через
            # минуту поднял, сторож (тогда одноразовый) вышел, и семь часов ноды крутились
            # впустую. Снимает запрет человек, разобравшись в причине.
            try:
                with open(HALT, 'w', encoding='utf-8') as f:
                    json.dump({'why': why, 'group': group, 'at': time.time(),
                               'kind': 'shared_infra' if not sink['ok'] else 'silence',
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

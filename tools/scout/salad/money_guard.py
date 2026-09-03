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

import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(HERE, '..', 'mesh-run-progress.jsonl')
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
    """Все группы под охраной. Их бывает несколько: 03.09 владелец поставил рядом две по
    10 реплик — на тарифах `batch` и `low` — чтобы сравнить их живьём."""
    return [g.strip() for g in os.environ.get('SALAD_GROUP', '').split(',') if g.strip()]


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
    if st.get('group') != group:            # сменился состав групп — терпение считаем заново
        st = {'group': group, 'idle_node_min': 0.0, 'silent_since': 0.0,
              'last_seen_mesh': last_mesh_at()}
    print(f'сторож денег: группы {group}, бюджет молчания {BUDGET_NODE_MIN:.0f} нодо-минут '
          f'И не меньше {MIN_WALL_MIN:.0f} мин тишины, тик {TICK_S / 60:.0f} мин', flush=True)
    while True:
        counts = {g: running_count(g) for g in gs}
        n = sum(v for v in counts.values() if v > 0)
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
        elif n > 0:
            st['idle_node_min'] += n * (TICK_S / 60.0)
            if not st.get('silent_since'):
                st['silent_since'] = time.time()
            wall = (time.time() - st['silent_since']) / 60.0
            print(f'{time.strftime("%H:%M")} работающих нод {n} {counts}, мешей нет: '
                  f'{st["idle_node_min"]:.0f} из {BUDGET_NODE_MIN:.0f} нодо-минут, '
                  f'тишина {wall:.0f} из {MIN_WALL_MIN:.0f} мин', flush=True)
        elif n == 0:
            # Никто не работает — деньги не идут, терпение не тратим.
            print(f'{time.strftime("%H:%M")} работающих нод нет — не платим, жду', flush=True)
        save(st)
        wall_min = (time.time() - st['silent_since']) / 60.0 if st.get('silent_since') else 0.0
        # ОБА условия сразу: и оплаченные нодо-минуты, и долгая тишина по часам.
        if st['idle_node_min'] >= BUDGET_NODE_MIN and wall_min >= MIN_WALL_MIN:
            why = (f'{st["idle_node_min"]:.0f} нодо-минут и {wall_min:.0f} мин тишины без '
                   f'единого меша (остановлено {time.strftime("%d.%m %H:%M")})')
            print(f'{time.strftime("%H:%M")} !! ПРЕВЫШЕН БЮДЖЕТ МОЛЧАНИЯ ({why}) — ГАШУ ГРУППУ '
                  f'{group}. Разбор: почему ноды не отдавали меши.', flush=True)
            # СТОП-ФАЙЛ ПИШЕМ ДО ОСТАНОВКИ. Иначе конвейер успеет поднять группу обратно —
            # ровно так и вышло в ночь на 03.09: сторож погасил, `ensure_group_started` через
            # минуту поднял, сторож (тогда одноразовый) вышел, и семь часов ноды крутились
            # впустую. Снимает запрет человек, разобравшись в причине.
            try:
                with open(HALT, 'w', encoding='utf-8') as f:
                    json.dump({'why': why, 'group': group, 'at': time.time()}, f,
                              ensure_ascii=False)
                print(f'{time.strftime("%H:%M")} запрет на подъём записан: {HALT}', flush=True)
            except Exception as e:  # noqa: BLE001
                print(f'{time.strftime("%H:%M")} !! не смог записать запрет ({e}) — конвейер '
                      f'может поднять группу обратно', flush=True)
            for g in gs:
                try:
                    _api(f'{g}/stop', 'POST')
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

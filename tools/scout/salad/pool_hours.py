#!/usr/bin/env python3
"""КОГДА НА ТАРИФЕ ДАЮТ МАШИНЫ: карта пула по часам суток.

ЗАЧЕМ (владелец 03.09: «может быть, мы время найдём, когда они появляются, замерим и будем
только в это время включать»). Машины Salad — чужие домашние компьютеры, и у их доступности
должен быть суточный ритм. Проверить это по журналу прогона не вышло: там видны только ноды,
успевшие что-то сделать, наблюдения размазаны по трём суткам при РАЗНОМ числе реплик, и лучший
час (21:00) был измерен ровно один раз. На таком материале расписание не строят.

Поэтому сторож денег ведёт перепись (`mesh-pool-census.jsonl`): раз в тик — строка на группу с
разбивкой по состояниям. Здесь она сворачивается в карту «час суток → сколько машин РАБОТАЛО в
среднем», и рядом всегда печатается число наблюдений: час, измеренный один раз, — не факт.

    ~/venvs/scout/bin/python pool_hours.py [--days 7] [--min-obs 3]
"""
from __future__ import annotations

import collections
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
CENSUS = os.path.join(HERE, '..', 'mesh-pool-census.jsonl')
# Тариф группы: имя — не контракт, держим явную карту (та же, что в `tier_compare`).
TIER = {'mesh-batch-1': 'batch', 'mesh-batch-2': 'batch',
        'mesh-low-2': 'low', 'mesh-low-3': 'low'}
# Ниже этого числа наблюдений час не считаем измеренным — только показываем серым.
MIN_OBS = int(os.environ.get('MESH_HOURS_MIN_OBS', '3'))


def load(days: float) -> list[dict]:
    now = time.time()
    out = []
    try:
        with open(CENSUS, encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get('at', 0) >= now - days * 86400:
                    out.append(r)
    except FileNotFoundError:
        pass
    return out


def main() -> int:
    days = 7.0
    if '--days' in sys.argv:
        days = float(sys.argv[sys.argv.index('--days') + 1])
    min_obs = MIN_OBS
    if '--min-obs' in sys.argv:
        min_obs = int(sys.argv[sys.argv.index('--min-obs') + 1])

    rows = load(days)
    if not rows:
        print(f'переписи за {days:.0f} дн. нет — сторож денег ещё не накопил '
              f'({CENSUS}). Данные появляются раз в 5 минут.')
        return 0

    # час суток → тариф → список «сколько машин работало» в каждом замере
    work: dict[tuple[int, str], list[int]] = collections.defaultdict(list)
    slots: dict[tuple[int, str], set] = collections.defaultdict(set)
    for r in rows:
        tier = TIER.get(r.get('group', ''), '?')
        lt = time.localtime(r['at'])
        key = (lt.tm_hour, tier)
        work[key].append(int(r.get('running') or 0))
        slots[key].add((lt.tm_yday, lt.tm_hour))

    tiers = sorted({t for _, t in work})
    span = (max(r['at'] for r in rows) - min(r['at'] for r in rows)) / 3600
    print(f'=== карта пула по часам: {len(rows)} замеров за {span:.0f} ч ===')
    print(f'{"час":>4s}  ' + '  '.join(f'{t:>18s}' for t in tiers))
    for h in range(24):
        cells, any_data = [], False
        for t in tiers:
            v = work.get((h, t))
            if not v:
                cells.append(f'{"—":>18s}')
                continue
            any_data = True
            obs = len(slots[(h, t)])
            avg = statistics.mean(v)
            mark = ' ' if obs >= min_obs else '?'      # «?» = наблюдений мало, не верить
            cells.append(f'{avg:6.1f} маш {mark}({obs:2d}д)')
        if any_data:
            print(f'{h:02d}ч   ' + '  '.join(cells))

    print()
    print(f'«?» — час наблюдался меньше {min_obs} суток: это ещё не измерение, а случай.')
    for t in tiers:
        good = [(statistics.mean(v), h) for (h, tt), v in work.items()
                if tt == t and len(slots[(h, tt)]) >= min_obs]
        if not good:
            print(f'{t}: надёжно измеренных часов пока НЕТ — нужно больше суток наблюдений.')
            continue
        good.sort(reverse=True)
        top = ', '.join(f'{h:02d}ч ({a:.1f})' for a, h in good[:5])
        bot = ', '.join(f'{h:02d}ч ({a:.1f})' for a, h in good[-3:])
        print(f'{t}: лучшие часы — {top}; худшие — {bot}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

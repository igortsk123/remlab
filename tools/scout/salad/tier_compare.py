#!/usr/bin/env python3
"""СРАВНЕНИЕ ТАРИФОВ Salad бок о бок: что реально даёт `batch` против `low`.

ЗАЧЕМ (владелец 03.09: «пусть 10 машин на lowest и 10 на low работает, потом сравним»).
Оценка доступности в панели Salad («3 at lowest, 93 at low») — прогноз, а не факт: на batch у
нас в тот момент работало 5 машин при обещанных 3. Спорить с прогнозом бесполезно, поэтому две
группы одинакового размера пущены рядом, а решение принимается по журналу прогона.

ЧТО СЧИТАЕМ. Тариф НЕ меняет скорость ноды: меш занимает свои ~195 с на любой. Он меняет то,
сколько машин удаётся УДЕРЖАТЬ. Поэтому главные числа — не «медиана секунд», а сколько нод
реально считали и сколько мешей вышло; цена за меш из них и получается.

ОГРАНИЧЕНИЕ ЧЕСТНОСТИ. Нодо-часы считаются по журналу (сумма времени генераций), то есть это
ОПЛАЧЕННОЕ ПОЛЕЗНОЕ время, а не всё время в состоянии `running`. Простой прогретой ноды сюда не
попадает, значит настоящая цена за меш ВЫШЕ расчётной — насколько, показывает доля занятости
(`gpu_seconds` из `/health` ноды). Цифру внизу читать как нижнюю границу, а не как факт.

    ~/venvs/scout/bin/python tier_compare.py [--hours 6]
"""
from __future__ import annotations

import collections
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
JOURNAL = os.path.join(HERE, '..', 'mesh-run-progress.jsonl')

# Цены Salad за час, взяты из API (`/organizations/<org>/gpu-classes`) 03.09. Карты у нас все на
# 24 ГБ, приходят в основном RTX 3090 — берём её тариф; 4090 дороже, но встречается реже.
PRICE = {'batch': 0.090, 'low': 0.143, 'medium': 0.197, 'high': 0.250}
# Какая группа на каком тарифе. Не выводим из имени: имя — не контракт.
TIER = {'mesh-batch-1': 'batch', 'mesh-low-2': 'low', 'mesh-low-1': 'low'}
# ЧИСТАЯ ПАРА ДЛЯ СРАВНЕНИЯ (03.09): `mesh-batch-1` и `mesh-low-2` подняты на ОДНОМ образе
# `localpaint` (прогрев 116 с вместо 242) и почти одновременно — различаются только тарифом.
# `mesh-low-1` осталась на старом образе и работает с утра: её числа в сравнение тарифов не
# берём, иначе возраст нод и медленный прогрев выдадут себя за влияние тарифа.
IMAGE = {'mesh-batch-1': 'localpaint', 'mesh-low-2': 'localpaint', 'mesh-low-1': 'dino'}
FAIR = ('mesh-batch-1', 'mesh-low-2')     # только эти две сравнимы напрямую


def load(hours: float) -> list[dict]:
    now = time.time()
    rows = []
    try:
        with open(JOURNAL, encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get('at', 0) >= now - hours * 3600:
                    rows.append(r)
    except FileNotFoundError:
        pass
    return rows


def main() -> int:
    hours = 6.0
    if '--hours' in sys.argv:
        hours = float(sys.argv[sys.argv.index('--hours') + 1])
    rows = load(hours)
    if not rows:
        print(f'за последние {hours:.0f} ч в журнале пусто')
        return 0

    by = collections.defaultdict(list)
    for r in rows:
        by[r.get('group') or '<без группы>'].append(r)

    print(f'=== сравнение тарифов за {hours:.0f} ч ===')
    print(f'{"группа":14s} {"тариф":7s} {"мешей":>6s} {"медиана":>8s} {"нод":>4s} '
          f'{"сбоев":>6s} {"$/меш":>8s}')
    totals = {}
    for grp, rs in sorted(by.items()):
        ok = [r for r in rs if r.get('status') == 'ok' and r.get('sec')]
        bad = [r for r in rs if r.get('status') != 'ok']
        tier = TIER.get(grp, '?')
        price = PRICE.get(tier)
        med = statistics.median([r['sec'] for r in ok]) if ok else 0
        nodes = len({r.get('node') for r in ok})
        # Нодо-часы полезной работы: сумма длительностей генераций.
        node_h = sum(r['sec'] for r in ok) / 3600
        per = (node_h * price / len(ok)) if ok and price else 0
        totals[grp] = {'ok': len(ok), 'nodes': nodes, 'node_h': node_h, 'tier': tier}
        print(f'{grp:14s} {tier:7s} {len(ok):6d} {med:7.0f}с {nodes:4d} {len(bad):6d} '
              f'{per:8.4f}' if ok else
              f'{grp:14s} {tier:7s} {0:6d} {"—":>8s} {0:4d} {len(bad):6d} {"—":>8s}')

    print()
    live = {g: t for g, t in totals.items() if t['ok']}
    if len(live) < 2:
        print('ВЫВОД: пока работает одна группа — сравнивать не с чем. Дай обеим набрать мешей.')
        return 0
    pair = {g: t for g, t in live.items() if g in FAIR}
    if len(pair) == 2:
        print('ЧИСТАЯ ПАРА (один образ, один возраст) — по ней и судим о тарифе:')
        for g, t in sorted(pair.items()):
            print(f'  {g:14s} {t["tier"]:7s} мешей {t["ok"]:4d}, нод считали {t["nodes"]:3d}, '
                  f'мешей на ноду {t["ok"] / max(t["nodes"], 1):.1f}')
        print()
    best = max(live.items(), key=lambda kv: kv[1]['ok'])
    print(f'Больше мешей выдала {best[0]} ({best[1]["tier"]}): {best[1]["ok"]} против '
          + ', '.join(f'{g} {t["ok"]}' for g, t in live.items() if g != best[0]))
    print('ГЛАВНОЕ ЧИСЛО — не медиана секунды (она одинакова на любом тарифе), а сколько нод '
          'реально считали:')
    for g, t in sorted(live.items()):
        print(f'  {g:14s} {t["tier"]:7s} нод считали: {t["nodes"]}, полезных нодо-часов: '
              f'{t["node_h"]:.1f}')
    print('Цена за меш ниже настоящей: простой прогретой ноды в журнал не попадает.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

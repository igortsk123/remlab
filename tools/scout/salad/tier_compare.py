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
import sys
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
JOURNAL = os.path.join(HERE, '..', 'mesh-run-progress.jsonl')

import salad_groups as SG  # noqa: E402 — тариф/цена группы: ОДИН источник (rules/salad-groups.json)
CENSUS = os.path.join(HERE, '..', 'mesh-pool-census.jsonl')
TICK_S = float(os.environ.get('MESH_GUARD_TICK_S', '300'))
# Образ у групп с 04.09 один (localpaint) — сравнение по тарифу честное без оговорок.
FAIR = tuple((SG.load().get('groups') or {}).keys())


def paid_hours(hours: float) -> dict:
    """ОПЛАЧЕННЫЕ нодо-часы по группам из переписи сторожа (строка на группу на тик: `running`, `at`).
    Это ОЦЕНКА, не бухгалтерия (Codex 04.09 №11): интервал = до следующей строки той же группы,
    но не больше 2×TICK; разрыв длиннее — `unknown`, а не экстраполяция (сторож стоял — сколько
    работали ноды, мы не знаем). Возвращает {группа: {'h': часы, 'unknown_h': часы_без_данных}}."""
    now = time.time()
    rows = collections.defaultdict(list)
    try:
        with open(CENSUS, encoding='utf-8') as f:
            for line in f:
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if r.get('at', 0) >= now - hours * 3600 and r.get('group'):
                    rows[r['group']].append((float(r['at']), int(r.get('running') or 0)))
    except FileNotFoundError:
        return {}
    out = {}
    for g, pts in rows.items():
        pts.sort()
        h = unk = 0.0
        for (a, n), (b, _) in zip(pts, pts[1:] + [(min(now, pts[-1][0] + TICK_S), 0)]):
            dt = b - a
            if dt <= 2 * TICK_S:
                h += n * dt / 3600
            elif n:
                unk += n * (dt - TICK_S) / 3600      # что было в разрыве — неизвестно
                h += n * TICK_S / 3600
        out[g] = {'h': h, 'unknown_h': unk}
    return out


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
    warm = collections.defaultdict(list)
    for r in rows:
        g = r.get('group') or '<без группы>'
        # Строки прогрева — не задания: в счёт мешей и сбоев они попасть НЕ должны
        # (`kind: warmup`, пишет супервизор `ssh_run` при подключении ноды).
        if r.get('kind') == 'warmup':
            if r.get('warmup_s'):
                warm[g].append(float(r['warmup_s']))
            continue
        by[g].append(r)

    paid = paid_hours(hours)
    rub = SG.usd_rub()
    print(f'=== сравнение тарифов за {hours:.0f} ч ===')
    print(f'{"группа":14s} {"тариф":7s} {"мешей":>6s} {"медиана":>8s} {"нод":>4s} {"сбоев":>6s} '
          f'{"$/меш низ":>10s} {"опл.ч":>7s} {"$/меш опл":>10s} {"₽/меш":>7s}')
    totals = {}
    for grp, rs in sorted(by.items()):
        ok = [r for r in rs if r.get('status') == 'ok' and r.get('sec')]
        bad = [r for r in rs if r.get('status') not in ('ok', 'cached')]
        tier = SG.tier(grp)
        price = SG.price(grp)
        med = statistics.median([r['sec'] for r in ok]) if ok else 0
        nodes = len({r.get('node') for r in ok})
        node_h = sum(r['sec'] for r in ok) / 3600        # полезные секунды — нижняя граница
        per = (node_h * price / len(ok)) if ok and price else 0
        ph = paid.get(grp, {}).get('h', 0.0)
        unk = paid.get(grp, {}).get('unknown_h', 0.0)
        per_paid = (ph * price / len(ok)) if ok and price and ph else 0
        totals[grp] = {'ok': len(ok), 'nodes': nodes, 'node_h': node_h, 'tier': tier,
                       'paid_h': ph, 'per_paid': per_paid}
        if ok:
            print(f'{grp:14s} {tier:7s} {len(ok):6d} {med:7.0f}с {nodes:4d} {len(bad):6d} {per:10.4f} '
                  f'{ph:7.1f} {per_paid:10.4f} {per_paid * rub:7.2f}' + (f'  (?{unk:.1f}ч)' if unk else ''))
        else:
            print(f'{grp:14s} {tier:7s} {0:6d} {"—":>8s} {0:4d} {len(bad):6d} {"—":>10s} {ph:7.1f} {"—":>10s} {"—":>7s}')

    if warm:
        print()
        print('ПРОГРЕВ (замеры с живых нод; образ localpaint читает веса с диска):')
        for g, v in sorted(warm.items()):
            print(f'  {g:14s} {SG.tier(g):7s} n={len(v):3d}  медиана {statistics.median(v):5.0f}с  '
                  f'мин {min(v):.0f}  макс {max(v):.0f}')
    print()
    live = {g: t for g, t in totals.items() if t['ok']}
    if len(live) < 2:
        print('ВЫВОД: пока работает одна группа — сравнивать не с чем. Дай обеим набрать мешей.')
        return 0
    pair = {g: t for g, t in live.items() if g in FAIR}
    if len(pair) >= 2:
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
    print('«$/меш низ» — по секундам генерации (нижняя граница); «опл» — по оплаченным нодо-часам\n'
          'из переписи сторожа (оценка; «?» — часы в разрывах переписи, что там было — неизвестно).')
    return 0


if __name__ == '__main__':
    sys.exit(main())

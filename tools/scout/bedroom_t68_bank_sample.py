#!/usr/bin/env python3
"""Выборка банка спальни «до / после» норм проходов (T-20261112-68, ADR-0394).

Каждый второй набор банка (`sets-bedroom.json`, 30 из 60): та же комната (`compose_bedroom._room_model`) и те же предметы
(Ш×Г×В из раскладки банка) — заново движком групп (`solve_bedroom(..., engine='groups')`) кодом из каталога солвера SOLVER.
Запуск дважды — с солвером «до» (чистая копия коммита) и «после» (рабочая копия), потом сравнение:

  python bedroom_t68_bank_sample.py run <SOLVER> <out.json> [<bank>]
  python bedroom_t68_bank_sample.py compare <before.json> <after.json> <out.md>
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BANK = '/home/pakar/igor/remlab/tools/scout/sets-bedroom.json'     # не в git — основная копия
FURN = ('кровать', 'тумба', 'шкаф', 'комод', 'стол', 'стул', 'туалетный')


def run(solver, out, bank_path=BANK):
    sys.path.insert(0, os.path.abspath(solver))
    sys.path.insert(1, HERE)
    import compose_bedroom as CB
    from planner.bedroom import solve_bedroom
    from planner.models import Item, Severity
    bank = json.load(open(bank_path, encoding='utf-8'))
    bank = bank.get('sets', bank) if isinstance(bank, dict) else bank
    rows = []
    for s in bank[::2]:
        lay = s['layout']
        model = CB._room_model(lay['_room'], s['purpose'])
        roles = [r for r in lay if not r.startswith('_') and r.split(' ')[0] in FURN]
        items = [Item(role=r, w_cm=lay[r]['w'], d_cm=lay[r]['d'], h_cm=lay[r]['h'], side_back=lay[r].get('side_back'))
                 for r in roles]
        res = solve_bedroom(model, items, s['purpose'], engine='groups')
        m = res.meta or {}
        cl = m.get('clearance') or {}
        rows.append({'id': f"{s['room_id']}|{s['purpose']}|{s['style']}|{s.get('tier')}",
                     'level': (m.get('composition') or {}).get('level'),
                     'mode': cl.get('mode'), 'refusal': cl.get('refusal') or m.get('reason'),
                     'blockers': cl.get('bed_blockers'),
                     'placed': sorted(p.role for p in res.placements), 'unplaced': sorted(res.unplaced),
                     'hard': sorted({v.code for v in res.violations if v.severity is Severity.HARD}),
                     'allow': [a['text'] for a in m.get('allowances') or []]})
        print(rows[-1]['id'], rows[-1]['level'], rows[-1]['mode'], rows[-1]['unplaced'], flush=True)
    json.dump(rows, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def _refused(r):
    return r['mode'] == 'refused' or not any(p.startswith('кровать') for p in r['placed'])


def compare(before, after, out):
    b = {r['id']: r for r in json.load(open(before, encoding='utf-8'))}
    a = {r['id']: r for r in json.load(open(after, encoding='utf-8'))}
    L = ['| набор | уровень было → стало | проход стало | не встало было → стало | допуск покупателю |', '|---|---|---|---|---|']
    lvl = comp = tgt = ref_b = ref_a = lost = 0
    for k in b:
        x, y = b[k], a[k]
        lvl += x['level'] != y['level']
        comp += y['mode'] == 'compact'
        tgt += y['mode'] == 'target'
        ref_b += _refused(x)
        ref_a += _refused(y)
        lost += len(set(y['unplaced']) - set(x['unplaced']))
        mode = {'target': 'цель', 'compact': 'compact', 'refused': '✗ ' + ', '.join(y['refusal'] or [])}.get(y['mode'], y['mode'] or '—')
        L.append(f"| {k} | {x['level'] or '—'} → {y['level'] or '—'} | {mode} | {', '.join(x['unplaced']) or '—'} → "
                 f"{', '.join(y['unplaced']) or '—'} | {'; '.join(dict.fromkeys(y['allow'])) or '—'} |")
    head = [f'# Банк спальни: выборка {len(b)} наборов до / после норм проходов (T-20261112-68)', '',
            f'- сменили уровень: **{lvl}**', f'- по цели: **{tgt}**, с допуском compact: **{comp}**',
            f'- отказов было → стало: **{ref_b} → {ref_a}**', f'- предметов потеряно сверх прежнего: **{lost}**', '']
    open(out, 'w', encoding='utf-8').write('\n'.join(head + L) + '\n')
    print('\n'.join(head))


if __name__ == '__main__':
    a = sys.argv[1:]
    if a[0] == 'run':
        run(*a[1:])
    else:
        compare(*a[1:])

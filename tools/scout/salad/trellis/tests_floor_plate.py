#!/usr/bin/env python3
"""Тесты правила G (`mesh_clean.floor_plate`, «коврик под ножками», T-20261118-91/1/2): условия ①–④ и предохранитель, на синтетических коробках.
Только numpy: `floor_plate` работает по массивам вершин и граней (без trimesh, сети и видеокарты). ID товаров в тестах нет.

  python3 tools/scout/salad/trellis/tests_floor_plate.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import mesh_clean as MC  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def box(cx, cz, y0, y1, hx, hz):
    """Коробка: 8 вершин, 12 граней (своя связная часть)."""
    v = np.array([[cx + sx * hx, y, cz + sz * hz] for y in (y0, y1) for sx in (-1, 1) for sz in (-1, 1)], dtype=float)
    q = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    f = np.array([t for a, b, c, d in q for t in ((a, b, c), (a, c, d))], dtype=int)
    return v, f


def build(parts):
    vs, fs, o = [], [], 0
    spans = []
    for v, f in parts:
        vs.append(v)
        fs.append(f + o)
        spans.append((sum(len(x) for x in fs[:-1]), sum(len(x) for x in fs)))
        o += len(v)
    return np.concatenate(vs), np.concatenate(fs), spans


def scene(plate_thick=0.004, plate_hx=0.5, plate_hz=0.225, legs=True, solid=False, legs_below=False, body_hx=0.5, plate_y0=0.0):
    """Коврик (парит на уровне пола) + корпус на ножках (или сплошным низом) — как комод после срезанной плиты."""
    py1 = plate_y0 + plate_thick
    parts = [box(0, 0, plate_y0, py1, plate_hx, plate_hz)]
    if legs:
        for sx in (-1, 1):
            for sz in (-1, 1):
                parts.append(box(sx * 0.45, sz * 0.18, (-0.05 if legs_below else py1), 0.1, 0.015, 0.015))
    parts.append(box(0, 0, py1 if solid else 0.1, 0.5, body_hx, 0.225))
    return build(parts)


# 1. коврик на полу, тело на ножках: коврик снят, ножки и корпус целы
v, f, sp = scene()
g, info = MC.floor_plate(v, f, np.zeros(len(f), dtype=bool), max_share=0.5)
ok('коврик снят целиком', bool(g[sp[0][0]:sp[0][1]].all()), str(info))
ok('ножки и корпус не тронуты', not g[sp[0][1]:].any())
ok('кандидат записан с причиной «снят»', any(c.get('removed') and c.get('reason') == 'снят' for c in info['candidates']))

# 2. ① не горизонтальный (узкая высокая пластина): остаётся
v, f, sp = scene(plate_hx=0.025, plate_thick=0.004)
g, info = MC.floor_plate(v, f, np.zeros(len(f), dtype=bool), max_share=0.5, horiz_share=0.95)
ok('① менее 95 % горизонтальных — не снимает', not g.any() and not info['candidates'], str(info))

# 3. ② толстая плита (4 % высоты): остаётся
v, f, sp = scene(plate_thick=0.02)
g, info = MC.floor_plate(v, f, np.zeros(len(f), dtype=bool), max_share=0.5)
ok('② толще 1 % высоты — не снимает', not g.any(), str(info))

# 4. ③ тело стоит сплошным низом на плите: остаётся (цоколь)
v, f, sp = scene(legs=False, solid=True)
g, info = MC.floor_plate(v, f, np.zeros(len(f), dtype=bool), max_share=0.5)
ok('③ сплошное основание — плита остаётся', not g.any() and any(c.get('reason') == 'тело опирается сплошным низом' for c in info['candidates']), str(info))

# 5. ③ ножки уходят ниже плиты: плита не самая нижняя — остаётся
v, f, sp = scene(legs_below=True)
g, info = MC.floor_plate(v, f, np.zeros(len(f), dtype=bool), max_share=0.5)
ok('③ не самый нижний кусок — не снимает', not g.any(), str(info))

# 6. ④ план плиты шире тела на 30 %: остаётся; на 3 % — снимается
v, f, sp = scene(plate_hx=0.65)
g, info = MC.floor_plate(v, f, np.zeros(len(f), dtype=bool), max_share=0.5)
ok('④ шире тела на 30 % — не снимает', not g.any() and any(c.get('reason') == 'план шире тела больше допуска' for c in info['candidates']), str(info))
v, f, sp = scene(plate_hx=0.515)
g, info = MC.floor_plate(v, f, np.zeros(len(f), dtype=bool), max_share=0.5)
ok('④ шире тела на 3 % — снимает', bool(g[sp[0][0]:sp[0][1]].all()), str(info))

# 7. предохранитель: стандартные 3 % площади — плита здесь ≈ 29 % → ничего и причина отказа
v, f, sp = scene()
g, info = MC.floor_plate(v, f, np.zeros(len(f), dtype=bool))
ok('предохранитель 3 % — ничего не снимает', not g.any() and info['refused'] and 'предохранитель' in info['refused'], str(info))

# 8. маска E: уже снятое не считается телом (пол — от низа ОСТАВШЕГОСЯ): плита под снятой плитой-основанием
v, f, sp = scene()
under = np.zeros(len(f), dtype=bool)
g, info = MC.floor_plate(v, f, under, max_share=0.5)
ok('прогон по пустой маске — тот же результат, что в п.1', bool(g[sp[0][0]:sp[0][1]].all()))
# уже удалённая плита — G нечего снимать
under[sp[0][0]:sp[0][1]] = True
g, info = MC.floor_plate(v, f, under, max_share=0.5)
ok('плита уже снята ранее — G не трогает ничего', not g.any())

# 9. пустой остаток и повтор не падают
g, info = MC.floor_plate(v, f, np.ones(len(f), dtype=bool))
ok('весь меш снят — без падения, пусто', not g.any())

# 10. в коде нет ID товаров (правило общее)
src = open(os.path.join(HERE, 'mesh_clean.py'), encoding='utf-8').read()
import re  # noqa: E402
body = src[src.index('def floor_plate'):src.index('def slab_rule_e')]
ok('в floor_plate нет ID товаров', not re.search(r'\d{5,6}[:_]\d{10,}', body))

print('ИТОГО:', 'всё в норме' if not bad else f'{bad} провалов')
sys.exit(1 if bad else 0)

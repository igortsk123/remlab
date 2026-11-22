#!/usr/bin/env python3
"""Тесты ref_zone (Ш8м, T-187/4): тот же меш, решения по свойствам с not_applicable, гейт по свойству, продолжение зон по сваренным вершинам и отказ при споре.
  python3 tools/scout/salad/trellis/tests_ref_zone.py"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ref_zone as RZ  # noqa: E402

FAILS = []


def ok(cond, msg):
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        FAILS.append(msg)


def strip(n_quads: int, split: bool):
    """Полоса из 2n треугольников; split=True — у каждой грани свои вершины (как у GLB, разрезанного по швам UV)."""
    V, F = [], []
    for i in range(n_quads + 1):
        V += [[i, 0, 0], [i, 1, 0]]
    for i in range(n_quads):
        F += [[2 * i, 2 * i + 1, 2 * i + 2], [2 * i + 1, 2 * i + 3, 2 * i + 2]]
    V, F = np.array(V, float), np.array(F)
    if split:
        V = V[F].reshape(-1, 3)
        F = np.arange(len(V)).reshape(-1, 3)
    return V, F


def agg(hf=2.0, pat=0.0, period=None, ang=None, uni=5.0, n=10):
    return {'n': n, 'hf': hf, 'macro': 3.0 if pat else 0.2, 'pat_share': pat, 'period': period, 'dir_share': 1.0 if ang is not None else 0.0, 'ang': ang, 'uniform': uni, 'meanL': 50.0}


def test_same_mesh():
    print('образец = наш меш:')
    V, F = strip(3, False)
    g = {'V': V, 'F': F, 'UV': np.random.default_rng(0).random((len(V), 2))}
    h = {k: v.copy() for k, v in g.items()}
    ok(RZ.same_mesh([g], [h])['same'], 'те же вершины, грани и UV — тот же меш')
    h2 = dict(h, UV=h['UV'] + 0.01)
    ok(not RZ.same_mesh([g], [h2])['same'], 'сдвиг UV — другой меш')
    h3 = dict(h, F=F[:-1])
    ok(not RZ.same_mesh([g], [h3])['same'], 'другое число граней — другой меш')


def test_decide():
    print('решения по свойствам, not_applicable, воздержание:')
    d = RZ.decide(None, agg())
    ok(all(v['decision'] == 'unknown' for v in d.values()), 'мало окон с видимой стороны — всё unknown')
    d = RZ.decide(agg(hf=2.0), agg(hf=2.2))
    ok(d['texture']['decision'] == 'same', 'сила фактуры 2,0 и 2,2 — texture same')
    ok(d['pattern']['decision'] == 'same' and d['scale']['decision'] == 'not_applicable' and d['direction']['decision'] == 'not_applicable', 'мотива нет с обеих сторон — масштаб и направление not_applicable')
    d = RZ.decide(agg(hf=2.0), agg(hf=0.3))
    ok(d['texture']['decision'] == 'different', 'фактура 2,0 против 0,3 (ниже пола шума) — texture different')
    d = RZ.decide(agg(pat=0.0), agg(pat=0.9, period=20.0, ang=10.0))
    ok(d['pattern']['decision'] == 'different' and d['scale']['decision'] == 'not_applicable', 'мотив только с одной стороны — pattern different, масштаб not_applicable')
    d = RZ.decide(agg(pat=0.9, period=20.0, ang=10.0), agg(pat=0.9, period=21.0, ang=15.0))
    ok(d['scale']['decision'] == 'same' and d['direction']['decision'] == 'same', 'период 20 и 21, угол 5° — масштаб и направление same')
    d = RZ.decide(agg(pat=0.9, period=20.0, ang=10.0), agg(pat=0.9, period=50.0, ang=100.0))
    ok(d['scale']['decision'] == 'different' and d['direction']['decision'] == 'different', 'период 20 и 50, угол 90° — different')


def test_gate_per_property():
    print('голос образца по свойству: провал выключает только это свойство:')
    g = RZ.gate(agg(hf=2.0, pat=0.0, uni=5.0), agg(hf=2.1, pat=0.9, period=20.0, uni=5.2))
    ok(g['pattern'][0] is False, 'на фото мотив есть, у образца нет — pattern выключен')
    ok(g['texture'][0] and g['uniform'][0], 'texture и uniform остаются включёнными')
    g2 = RZ.gate(None, agg())
    ok(not any(v[0] for v in g2.values()), 'мало окон для сверки с фото — все выключены')


def test_propagate():
    print('продолжение зон по сваренным вершинам, спор → -1:')
    for split in (False, True):
        V, F = strip(12, split)
        fz = np.full(len(F), -1, np.int32)
        fz[0], fz[-1] = 0, 1
        out = RZ.propagate_zones(V, F, fz, None)
        ok(out[1] == 0 and out[-2] == 1, f'split={split}: грани рядом с ярлыком берут его зону')
        mid = len(F) // 2
        ok(out[mid] == -1, f'split={split}: грань на равном расстоянии от двух разных зон — спорно (-1)')
    V, F = strip(6, True)
    fz = np.full(len(F), -1, np.int32)
    fz[0] = 0
    out = RZ.propagate_zones(V, F, fz, None)
    ok((out == 0).all(), 'один ярлык на всю связную часть — все грани получают его (острова UV сварены)')
    parts = np.zeros(len(F), np.int32)
    parts[6:] = 1
    ok((RZ.propagate_zones(V, F, fz, parts)[6:] == -1).all(), 'другая геометрическая часть — зона не переходит')


def main():
    for f in (test_same_mesh, test_decide, test_gate_per_property, test_propagate):
        f()
    print(f'tests_ref_zone: ошибок {len(FAILS)}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    raise SystemExit(main())

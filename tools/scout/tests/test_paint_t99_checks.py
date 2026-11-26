#!/usr/bin/env python3
"""T-99/11: автопроверки Fable 14 §4 (№1, 2, 3, 7) — paint_t99_checks.py. Синтетика, ID товаров нет.
Запуск: python tools/scout/tests/test_paint_t99_checks.py   (numpy, opencv)"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import numpy as np  # noqa: E402
import paint_t99_checks as C  # noqa: E402

FAILS = []


def ok(cond, msg):
    print(('ok: ' if cond else 'FAIL: ') + msg)
    if not cond:
        FAILS.append(msg)


R = C.load_rules()
ok(R['keep']['ratio_min'] == 0.9 and R['keep']['changed_marked_max'] == 0 and R['light']['L_ratio'] == [0.92, 1.08] and R['no_flat']['share_of_median_min'] == 0.5, 'пороги Fable 14 §4 в rules/t99-checks.json')
src = open(os.path.join(HERE, '..', 'paint_t99_checks.py'), encoding='utf-8').read()
ok('112923' not in src, 'в коде нет ID товаров')

# рисунок: полоски против ровной
rng = np.random.default_rng(0)
yy = np.arange(256)[:, None] * np.ones((1, 256), np.float32)
L_fiber = (50 + 3.0 * np.sin(2 * np.pi * yy / 8.0)).astype(np.float32)
L_flat = np.full((256, 256), 50.0, np.float32)
m = np.ones((256, 256), bool)
pf, p0 = C.pattern(L_fiber, m, R), C.pattern(L_flat, m, R)
ok(pf is not None and pf > 1.5 and p0 is not None and p0 < 0.01, f'pattern: волокно {pf:.2f}, ровная грань {p0:.3f}')
ok(C.pattern(L_fiber, np.zeros((256, 256), bool), R) is None, 'pattern: мало текселей → None (нет оценки)')

# №1
b = {('тумба', 'бок+x', '—'): {'n': 1000, 'L': 50, 'pattern': 1.0}, ('плита', 'верх', '—'): {'n': 1000, 'L': 50, 'pattern': 1.2}}
a_ok = {('тумба', 'бок+x', '—'): {'n': 1000, 'L': 50, 'pattern': 0.95}, ('плита', 'верх', '—'): {'n': 1000, 'L': 50, 'pattern': 1.3}}
a_bad = {('тумба', 'бок+x', '—'): {'n': 1000, 'L': 50, 'pattern': 0.2}, ('плита', 'верх', '—'): {'n': 1000, 'L': 50, 'pattern': 1.3}}
ok(C.check_keep(b, a_ok, 0, R)['ok'], '№1: рисунок после/до ≥ 0,9 и 0 изменённых с меткой → ок')
r = C.check_keep(b, a_bad, 0, R)
ok(not r['ok'] and r['faces_below'] == ['тумба/бок+x/—'], '№1: грань, где зерно стёрто (0,2 от прежнего) → стоп, названа грань')
ok(not C.check_keep(b, a_ok, 5, R)['ok'], '№1: изменённые тексели с меткой зерна → стоп')
ok(C.check_keep({('тумба', 'бок+x', '—'): {'n': 9, 'L': 50, 'pattern': 0.05}}, {('тумба', 'бок+x', '—'): {'n': 9, 'L': 50, 'pattern': 0.0}}, 0, R)['ok'], '№1: грань без рисунка и ДО — не судится (нечего стирать)')
t0 = np.zeros((8, 8, 3), np.uint8)
t1 = t0.copy()
t1[2, 2] = 10
mk = np.zeros((8, 8), bool)
mk[2, 2] = True
ok(C.changed_marked_count(t0, t1, mk, 2) == 1 and C.changed_marked_count(t0, t1, ~mk, 2) == 0, 'changed_marked_count: считает только изменённые на метке')

# №2
rows = {('тумба', 'бок+x', '—'): {'n': 1, 'L': 1, 'pattern': 1.0}, ('тумба', 'бок+z', '—'): {'n': 1, 'L': 1, 'pattern': 1.1}, ('плита', 'верх', '—'): {'n': 1, 'L': 1, 'pattern': 0.9}}
ok(C.check_no_flat(rows, R)['ok'], '№2: у всех граней рисунок рядом с медианой → ок')
rows[('тумба', 'бок-x', '—')] = {'n': 1, 'L': 1, 'pattern': 0.05}
r = C.check_no_flat(rows, R)
ok(not r['ok'] and r['flat_faces'] == ['тумба/бок-x/—'], '№2: ровная грань деревянной группы → стоп, названа')
rows2 = dict(rows)
rows2[('плита', 'низ', '—')] = {'n': 1, 'L': 1, 'pattern': 0.0}
ok(C.check_no_flat({k: v for k, v in rows2.items() if k[1] != 'бок-x'}, R)['ok'], '№2: низ плиты в счёт не идёт')

# №3
ok(C.check_light(1.0, 1.0, 1.0, R)['ok'] and not C.check_light(0.85, 1.0, 1.0, R)['ok'] and not C.check_light(1.0, 1.3, 1.0, R)['ok'] and not C.check_light(1.0, 1.0, 5.0, R)['ok'], '№3: L 0,92–1,08, C 0,9–1,15, оттенок ≤3° — границы')

# №7
t = C.judge_tone({'hue_diff_deg': 1.0, 'chroma_over_L_rel': 0.05, 'channel_gain_spread': 1.05, 'group_median_shift': 1.0, 'top_deviating_texels_pct': 0.1}, R)
ok(t['ok'] is True and not t['not_measured'], '№7: все числа в пределах → ок')
t = C.judge_tone({'hue_diff_deg': 6.0, 'top_deviating_texels_pct': 4.7}, R)
ok(t['ok'] is False and t['parts']['hue_diff_deg'] is False and t['parts']['top_deviating_texels_pct'] is False and 'channel_gain_spread' in t['not_measured'], '№7: оттенок 6°, верх 4,7 % (Келвин до исправления) → стоп; не измеренное не «ок»')
ok(C.judge_tone({}, R)['ok'] is None, '№7: чисел нет → None, не «ок»')
print('ИТОГО: %d провалов' % len(FAILS))
sys.exit(1 if FAILS else 0)

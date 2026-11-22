"""Сторож `bed_headboard_fringe` (T-20261119-106, П1.98): гало цвета подушки над подушками на мягком изголовье кровати.
Без сети, базы и моделей: точки и цвет — синтетика (плита, матрас, две подушки, полоса над подушками).

  python tools/scout/tests/test_bed_headboard_fringe.py

Что держит: ровная светлая полоса (дизайн) → НЕТ флага; рваная светлая → флаг; ажурное изголовье/нет эталона → `not_applicable`, не «ok»;
режим только `observe`; пороги — в одном словаре `THRESHOLDS`; ID товаров в коде сторожа нет; эталон узорной плиты (MAD > порога) флаг не даёт."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))

import numpy as np  # noqa: E402

import bed_headboard_fringe as B  # noqa: E402

fails = 0


def ok(name, cond):
    global fails
    print(('  ok  ' if cond else '  FAIL ') + name)
    fails += 0 if cond else 1


P, C = B._synthetic(band_light=False)
ok('чистая плита → ok', B.analyze(P, C)['verdict'] == 'ok')
P, C = B._synthetic(band_light=True, band_ragged=False)
r = B.analyze(P, C)
ok('ровная светлая полоса → нет флага (разброс ΔL мал)', r['verdict'] == 'ok' and r['share_light'] >= 0.15 and r['spread_dl'] < B.THRESHOLDS['spread_min'])
P, C = B._synthetic(band_light=True, band_ragged=True)
r = B.analyze(P, C)
ok('рваная светлая полоса → fringe', r['verdict'] == 'fringe' and r['share_light'] >= B.THRESHOLDS['share_min'] and r['spread_dl'] >= B.THRESHOLDS['spread_min'])
P, C = B._synthetic(band_light=True, band_ragged=True, openwork=True)
ok('ажурное изголовье (нет плиты для эталона) → not_applicable, не ok', B.analyze(P, C)['verdict'] == 'not_applicable')
# порог из словаря действует: строже dl_min — рваная полоса (ΔL ≈ 28) больше не флаг
P, C = B._synthetic(band_light=True, band_ragged=True)
ok('порог берётся из словаря: dl_min=40 → нет флага', B.analyze(P, C, {'dl_min': 40.0})['verdict'] == 'ok')
# узорная плита: эталон с большим разбросом светлоты → флаг не ставим
P, C = B._synthetic(band_light=True, band_ragged=True)
rng = np.random.default_rng(3)
C2 = C.copy()
up = P[:, 1] > 0.75
C2[up] = np.clip(C2[up] + rng.choice([-0.3, 0.3], size=(int(up.sum()), 1)), 0, 1)
r = B.analyze(P, C2)
ok('узорная плита (MAD эталона > порога) → нет флага', r['verdict'] == 'ok' and r['ref_mad_l'] > B.THRESHOLDS['ref_mad_max'])
ok('режим только observe', B.MODE == 'observe')
ok('все пороги — числа в одном словаре', all(isinstance(v, (int, float)) for v in B.THRESHOLDS.values()))
src = open(os.path.join(HERE, '..', 'bed_headboard_fringe.py'), encoding='utf-8').read()
body = src.split('"""', 2)[2]    # без шапки-пояснения
ok('ID товаров в коде сторожа нет (нет длинных цифровых ключей и «shop_mid_ext»)', not re.search(r'(?<![\d.])\d{6,}(?![\d.])|\b\d{5,}_\d{5,}\b', body))
print('FAILS:', fails)
sys.exit(1 if fails else 0)

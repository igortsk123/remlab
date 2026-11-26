#!/usr/bin/env python3
"""T-99/11 шаг 2: яркость Ш4а под свет сайта (site_light_gain.py). Без браузера: кривая из правил, перекладка яркости, отпечаток света, выключатель.
  python tools/scout/tests_site_light_gain.py"""
import copy
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import part_material as PM  # noqa: E402
import site_light_gain as SLG  # noqa: E402

FAILS = []


def check(cond, msg):
    print(('ok: ' if cond else 'FAIL: ') + msg)
    if not cond:
        FAILS.append(msg)


rules = json.load(open(os.path.join(HERE, 'rules', 'part-material.json'), encoding='utf-8'))
sl = rules['fit']['site_light']
check(sl['enabled'] is False, 'в rules-json site_light.enabled=false по умолчанию (выкл = как в main)')
check(SLG.current_curve(rules) == (None, 'выкл'), 'выкл → кривой нет, Ш4а ничего не перекладывает')
site = SLG.site_spec()
check(sl['light_sha'] == SLG.light_sha(site), 'отпечаток света сайта в правилах сходится с data/flat3d/sides-sheet.json (%s) — сменили свет, пересними: site_light_gain.py --write' % sl['light_sha'])
c = sl['curve']
check(c is not None and len(c['a']) == len(sl['plate_srgb']) and all(len(c[k]) == len(c['a']) for k in ('neutral', 'site')), 'кривая в правилах: %d уровней серого, по три канала' % len(c['a']))
check(all(np.all(np.diff(np.asarray(c[k], float).mean(1)) > 0) for k in ('neutral', 'site')), 'отклик плашки растёт с уровнем серого (обратимость кривой)')
# вкл: стухший отпечаток → ошибка (Ш4а воздержится)
r2 = copy.deepcopy(rules)
r2['fit']['site_light']['enabled'] = True
cur, why = SLG.current_curve(r2)
check(cur is not None and why == 'ok', 'вкл → кривая отдаётся')
r2['fit']['site_light']['light_sha'] = 'старый'
try:
    SLG.current_curve(r2)
    check(False, 'не сошёлся отпечаток — должна быть ошибка')
except ValueError as e:
    check('свет сайта изменился' in str(e), 'не сошёлся отпечаток света — воздержание с причиной')
r2['fit']['site_light']['light_sha'] = SLG.light_sha(site)
site2 = copy.deepcopy(site)
site2['light']['sun'] = 2.0
check(SLG.light_sha(site2) != SLG.light_sha(site), 'отпечаток меняется вместе с числами света')
# перекладка яркости
x = PM.srgb2lin(np.array([[187, 157, 113], [100, 80, 60], [30, 30, 30], [220, 220, 220], [0, 0, 0]]))
y = SLG.remap_lin(x, c)
Y = lambda a: 0.2126 * a[:, 0] + 0.7152 * a[:, 1] + 0.0722 * a[:, 2]  # noqa: E731
check(bool((Y(y[:4]) > Y(x[:4]) * 0.999).all()), 'под светом сайта (темнее подгонки) альбедо светлее: яркость растёт')
mid = Y(y[:3]) / Y(x[:3])
check(bool((mid[:2] > 1.2).all() and (mid[:2] < 2.2).all() and mid[2] > mid[1]), 'множитель яркости на средних тонах 1,2…2,2, на очень тёмных больше (носок тонмаппинга сайта): %s' % np.round(mid, 2))
ch = (y[0] / y[0].sum()) - (x[0] / x[0].sum())
check(float(np.abs(ch).max()) < 1e-6 or bool((y[0] >= 1.0).any()), 'цветность (отношение каналов) не меняется — оттенок и насыщенность фото')
check(bool((y[4] == 0).all()), 'чёрный остаётся чёрным')
tex = np.array([[[187, 157, 113], [10, 10, 10]]], np.uint8)
mask = np.array([[True, False]])
out = SLG.remap_srgb8(tex, mask, c)
check((out[0, 1] == tex[0, 1]).all() and (out[0, 0] != tex[0, 0]).any(), 'вне маски покрашенных — байт в байт; внутри — перекладка')
# множитель на уровне серого — отчётная строка
m = SLG.multipliers(c, 128)
check(len(m) == 3 and all(1.2 < v < 2.2 for v in m), 'множители на 128: %s' % m)
check('site_light' in open(os.path.join(HERE, 'part_material_stage.py'), encoding='utf-8').read() and 'SLG.current_curve(rules)' in open(os.path.join(HERE, 'part_material_stage.py'), encoding='utf-8').read(), 'Ш4а вызывает перекладку (ключ fit.site_light)')
src = open(os.path.join(HERE, 'part_material_stage.py'), encoding='utf-8').read()
check(src.index('rep[\'gate\'] = gate') < src.index('SLG.remap_srgb8(tex, painted, site_curve)') < src.index('PM.swap_tex_glb(src_glb, tex, vis)'), 'перекладка — ПОСЛЕ ворот и метрик, ДО записи текстуры (ворота судят как раньше)')
print('ИТОГО: %d провалов' % len(FAILS))
sys.exit(1 if FAILS else 0)

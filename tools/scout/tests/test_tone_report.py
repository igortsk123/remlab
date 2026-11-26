#!/usr/bin/env python3
"""Отчёт о тоне по шагам (T-99/7): tone_report.py. Синтетика (куб с UV и заливкой известного цвета) + сверка с таблицей step-tone.txt на Хостере и Келвине (если прогон руки A лежит на диске).
Запуск: python3 tools/scout/tests/test_tone_report.py   (нужны numpy, cv2, trimesh, Pillow)"""
import json
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_tone_report')
import tone_report as TR  # noqa: E402
import paint_stage as PS  # noqa: E402

FAIL = 0


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    if not cond:
        FAIL += 1


def _glb(path, rgb):
    import trimesh
    from PIL import Image
    box = trimesh.creation.box(extents=(1, 0.5, 0.5))
    uv = np.column_stack([(box.vertices[:, 0] + 0.5), (box.vertices[:, 2] + 0.25) * 2.0]).clip(0, 1)
    tex = Image.fromarray(np.full((64, 64, 4), list(rgb) + [255], dtype=np.uint8))
    box.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=tex))
    box.export(path)


def test_synthetic():
    with tempfile.TemporaryDirectory() as d:
        run = os.path.join(d, 'run')
        sd = os.path.join(run, 'sku-t')
        for sub, fn, rgb in (('06-visible', 'visible.pre-partmaterial.glb', (180, 120, 70)), ('06-visible', 'visible.pre-owner.glb', (200, 120, 60)), ('06-visible', 'visible.glb', (200, 120, 60)),
                             ('07-fill', 'filled.glb', (210, 120, 50)), ('08-material', 'material.glb', (210, 120, 50))):
            os.makedirs(os.path.join(sd, sub), exist_ok=True)
            _glb(os.path.join(sd, sub, fn), rgb)
        for sub, st in (('06-visible', '06-visible'), ('07-fill', '07-fill'), ('08-material', '08-material')):
            PS.write_check(os.path.join(sd, sub), st, 'sku-t', passed=False, reason='тестовый отказ', metrics={'m': {'value': 1, 'threshold': 2, 'op': '>='}}, outputs=['x.glb'])
        gen = os.path.join(d, 'gen.glb')
        _glb(gen, (150, 120, 90))
        from PIL import Image
        ph = os.path.join(d, 'ph.png')
        im = np.zeros((20, 20, 4), np.uint8)
        im[5:15, 5:15] = [190, 120, 60, 255]
        Image.fromarray(im).save(ph)
        rep = TR.run_report(run, 'sku-t', ph, gen)
        by = {r['step']: r for r in rep['steps']}
        ok(by['06 перенос фото']['C'] > rep['generator']['C'], 'C шага 06 выше генератора (180,120,70 против 150,120,90)')
        ok(abs(by['Ш4а']['L'] - TR._lab_stats(np.full((2, 2, 3), (200, 120, 60), np.uint8))['L']) < 0.05, 'L куба = L заливки (охват — вся развёртка куба)')
        ok(by['зерно'].get('note') == 'нет файла' and by['шов'].get('note') == 'нет файла', 'нет файла шага — строка «нет файла», не падение')
        ok(by['07 fill']['dC'] == round(by['07 fill']['C'] - by['gutter']['C'], 2), 'ΔC считается к предыдущему измеренному шагу (07 fill к gutter)')
        ok(rep['photo']['n'] == 100, 'фото: только непрозрачные пиксели (100 из 400)')
        c = PS.read_check(os.path.join(sd, '07-fill'))
        ok(c['passed'] is False and c['reason'] == 'тестовый отказ' and c['outputs'] == ['x.glb'] and 'm' in c['metrics'], 'check.json: passed/reason/мерки/outputs как были (отчёт ничего не меняет)')
        ok(c['extra']['tone']['report_only'] is True and c['extra']['tone']['step'] == '07 fill' and 'C' in c['extra']['tone'], 'check.json 07-fill: extra.tone с L/C/h и пометкой report_only')
        ok(os.path.exists(os.path.join(sd, '08-material', 'tone_report.json')), 'tone_report.json лежит у этапа 08')
        ok('нет файла' in TR.table(rep), 'таблица для отчёта прогона строится')


def test_failure_does_not_raise():
    import subprocess
    r = subprocess.run([sys.executable, '-I', os.path.join(HERE, '..', 'tone_report.py'), 'run', '--run', '/нет/такого', '--sku', 'x'], capture_output=True, text=True)
    ok(r.returncode == 0, 'сбой измерения (нет папки) — код выхода 0, этап не падает')


# числа step-tone.txt (T-99/7, 26.11): шаг → C; допуск ±0,1 (L не сверяем — в таблице он был только в тексте)
REAL = {
    '112923_10397032738411993': {'06 перенос фото': 26.7, 'Ш4а': 29.9, 'owner': 34.7, 'зерно': 35.4, 'gutter': 35.4, '07 fill': 36.7, 'шов': 36.6, '08 материал': 36.6},
    '112923_8848759860942472233': {'06 перенос фото': 18.8, 'Ш4а': 19.6, 'owner': 19.2, 'зерно': 19.1, 'gutter': 19.0, '07 fill': 26.1, 'шов': 25.9, '08 материал': 25.9},
}


def test_real_tables():
    base = os.path.expanduser('~/remlab-logs/t99-formy/kraska/arms/A/sh0')
    for sku, want in REAL.items():
        if not os.path.isdir(os.path.join(base, sku, '08-material')):
            print(f'  – прогона руки A ({sku}) нет на диске: сверка с таблицей пропущена')
            continue
        rep = TR.build(base, sku)
        got = {r['step']: r.get('C') for r in rep['steps']}
        bad = {k: (got.get(k), v) for k, v in want.items() if got.get(k) is None or abs(got[k] - v) > 0.1}
        ok(not bad, f'{sku[-6:]}: C по 8 шагам = таблица step-tone.txt ±0,1' + (f' (расхождения {bad})' if bad else ''))


if __name__ == '__main__':
    for t in (test_synthetic, test_failure_does_not_raise, test_real_tables):
        print(t.__name__)
        t()
    print(f'tone_report tests: ошибок {FAIL}')
    sys.exit(1 if FAIL else 0)

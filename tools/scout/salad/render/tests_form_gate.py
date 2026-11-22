#!/usr/bin/env python3
"""Тесты шага form_gate (Ш0, T-184/9): запись form_checks.json и сводки form_gate.tsv, строка «к глазам»; без сети и без реальных товаров. Запуск: python tests_form_gate.py (numpy, trimesh, pillow)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import trimesh
    from PIL import Image
    import form_gate as FG
except ImportError as exc:                                                      # pragma: no cover
    raise SystemExit(f'нет зависимостей: {exc}')


def mk(tmp, sku, role_box=(1.0, 1.0, 0.5)):
    glbs = os.path.join(tmp, 'glbs')
    out = os.path.join(tmp, 'out')
    os.makedirs(glbs, exist_ok=True)
    os.makedirs(os.path.join(out, sku))
    trimesh.creation.box(extents=role_box).export(os.path.join(glbs, f'{sku}-hd.glb'))
    for n in ('01_az000_clay.png', '05_az180_clay.png'):
        Image.new('RGB', (64, 48), (120, 120, 120)).save(os.path.join(out, sku, n))
    return glbs, out


class T(unittest.TestCase):
    def test_writes_report_and_summary_without_photo(self):
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        glbs, out = mk(tmp, 's_1')
        recs = FG.gate(out, glbs, ['s_1', 'нет_кадров'], {'s_1': 'шкаф'}, find_glb=lambda g, s: os.path.join(g, f'{s}-hd.glb'))
        self.assertEqual([r['sku'] for r in recs], ['s_1'])                          # без кадров товар не считается
        rec = json.load(open(os.path.join(out, 's_1', 'form_checks.json'), encoding='utf-8'))
        self.assertIn('status', rec)
        self.assertIn('body_skew', [c['name'] for c in rec['checks']])               # корпусная роль — проверка перекоса идёт
        rows = open(os.path.join(out, 'form_gate.tsv'), encoding='utf-8').read().splitlines()
        self.assertEqual(rows[0].split('\t'), list(FG.COLS))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].split('\t')[0:2], ['s_1', 'шкаф'])

    def test_eye_row_flags_needs_review_only(self):
        ok = {'sku': 'a', 'status': 'pass', 'flags': [], 'checks': []}
        self.assertEqual(FG.eye_row(ok, 'шкаф')[3], 'нет')
        bad = {'sku': 'b', 'status': 'needs_review', 'flags': ['vlm_no_gaps_check'], 'checks': [{'name': 'vlm_no_gaps_check', 'flag': True, 'note': '«да» в 1 из 3'}]}
        row = FG.eye_row(bad)
        self.assertEqual((row[3], row[4]), ('да', 'vlm_no_gaps_check'))
        self.assertIn('«да» в 1 из 3', row[5])
        cam = {'sku': 'c', 'status': 'camera_or_mask_uncertain', 'flags': ['sil_iou'], 'checks': []}
        self.assertEqual(FG.eye_row(cam)[3], 'нет')                                  # чисто камерное — не брак формы


if __name__ == '__main__':
    unittest.main()

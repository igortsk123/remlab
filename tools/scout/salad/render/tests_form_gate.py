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
    import vlm_judge as VJ
except ImportError as exc:                                                      # pragma: no cover
    raise SystemExit(f'нет зависимостей: {exc}')


def mk(tmp, sku, role_box=(1.0, 1.0, 0.5), gray=120):
    glbs = os.path.join(tmp, 'glbs')
    out = os.path.join(tmp, 'out')
    os.makedirs(glbs, exist_ok=True)
    os.makedirs(os.path.join(out, sku))
    trimesh.creation.box(extents=role_box).export(os.path.join(glbs, f'{sku}-hd.glb'))
    for n in ('01_az000_clay.png', '02_az000_clay_graze.png', '03_az090_clay.png', '05_az180_clay.png', '07_az225_clay.png', '09_top40_clay.png'):
        Image.new('RGB', (64, 48), (gray, gray, gray)).save(os.path.join(out, sku, n))
    os.makedirs(os.path.join(tmp, 'forms-inputs'), exist_ok=True)                      # фото рядом с прогоном: <glbs>/../forms-inputs
    Image.new('RGBA', (64, 48), (200, 50, 50, 255)).save(os.path.join(tmp, 'forms-inputs', f'{sku}.hd.rgba.png'))
    return glbs, out


class Chat:
    """Подмена llm_gateway.chat: всегда «нет»; помнит, какие виды спрашивали."""
    def __init__(self):
        self.calls, self.kinds = 0, set()

    def __call__(self, model, messages, **kw):
        self.calls += 1
        txt = messages[0]['content'][0]['text']
        ks = [k for k in VJ.KINDS if f'"{k}":' in txt.split('Отвечай строго')[1]]
        self.kinds |= set(ks)
        ans = {k: {'verdict': 'нет', 'where': '', 'photo': '', 'model': ''} for k in ks}
        return {'choices': [{'message': {'content': json.dumps(ans, ensure_ascii=False)}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}


def go(tmp, skus, roles, **kw):
    glbs, out = os.path.join(tmp, 'glbs'), os.path.join(tmp, 'out')
    return FG.gate(out, glbs, skus, roles, find_glb=lambda g, s: os.path.join(g, f'{s}-hd.glb'), log=lambda x: None, **kw)


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

    def test_default_three_kinds_cabinet_only_and_cached(self):
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        mk(tmp, 'k_1')
        ch = Chat()
        recs = go(tmp, ['k_1'], {'k_1': 'шкаф'}, chat=ch)
        self.assertEqual(ch.kinds, {'no_gaps', 'skewed_body', 'count_mismatch'})      # по умолчанию только 3 observe-вида
        self.assertEqual(ch.calls, 6)                                                 # группы b и c × 3 прогона
        self.assertNotIn('vlm_skipped_budget', [c['name'] for c in recs[0]['checks']])
        ch2 = Chat()
        go(tmp, ['k_1'], {'k_1': 'шкаф'}, chat=ch2)
        self.assertEqual(ch2.calls, 0)                                                # повтор — из кэша, бесплатно

    def test_non_cabinet_without_vlm_unless_vlm_all(self):
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        mk(tmp, 'd_1')
        ch = Chat()
        recs = go(tmp, ['d_1'], {'d_1': 'диван'}, chat=ch)
        self.assertEqual(ch.calls, 0)                                                 # некорпусная роль — оценщика нет
        self.assertIn('для роли «диван» видов нет', ' '.join(c['note'] for c in recs[0]['checks'] if c['name'] == 'vlm_judge'))
        ch2 = Chat()
        go(tmp, ['d_1'], {'d_1': 'диван'}, chat=ch2, vlm_all=True)
        self.assertGreater(ch2.calls, 0)                                              # --vlm-all — и другие виды для всех ролей
        self.assertIn('invented_detail', ch2.kinds)

    def test_budget_ceiling_skips_group_with_flag_not_error(self):
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        mk(tmp, 'k_1')
        ch = Chat()
        recs = go(tmp, ['k_1'], {'k_1': 'шкаф'}, chat=ch, vlm_budget=0.0005)
        self.assertEqual(ch.calls, 0)                                                 # потолок меньше одной группы — вызовов нет
        c = [x for x in recs[0]['checks'] if x['name'] == 'vlm_skipped_budget']
        self.assertEqual(len(c), 2)                                                   # обе группы (b, c) пропущены
        self.assertTrue(all(x['flag'] for x in c))
        self.assertEqual(recs[0]['status'], 'needs_review')                           # не оценено — «к глазам», не падение

    def test_budget_is_shared_across_forms_in_one_run(self):
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        mk(tmp, 'k_1')
        mk(tmp, 'k_2', gray=90)                                                       # другие кадры — иначе второй ответ берётся из кэша бесплатно
        ch = Chat()
        recs = go(tmp, ['k_1', 'k_2'], {'k_1': 'шкаф', 'k_2': 'комод'}, chat=ch)        # потолок по умолчанию $0,02: на форму ≈ $0,0136 — вторая не влезает
        self.assertEqual(ch.calls, 9)                                                 # первая форма — обе группы (6 вызовов), у второй остаток $0,0064: группа b (≈$0,0083) не влезла, c (≈$0,0052) — да
        self.assertNotIn('vlm_skipped_budget', [c['name'] for c in recs[0]['checks']])
        names1 = [c['name'] for c in recs[1]['checks']]
        self.assertIn('vlm_skipped_budget', names1)
        self.assertNotIn('vlm_no_gaps', names1)
        self.assertIn('vlm_count_mismatch', names1)
        log = open(os.path.join(tmp, 'out', 'form_gate.log'), encoding='utf-8').read()
        self.assertIn('vlm оценка до запуска', log)                                   # оценка расхода — строкой в лог до вызовов
        self.assertIn('vlm итог', log)


if __name__ == '__main__':
    unittest.main()

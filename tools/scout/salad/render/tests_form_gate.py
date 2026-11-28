#!/usr/bin/env python3
"""Тесты шага form_gate (Ш0, T-184/9): запись form_checks.json и сводки form_gate.tsv, строка «к глазам»; без сети и без реальных товаров. Запуск: python tests_form_gate.py (numpy, trimesh, pillow)."""
from __future__ import annotations
import os as _rt_os  # noqa: E402
import sys as _rt_sys  # noqa: E402
_rt_sys.path.append(_rt_os.path.join(_rt_os.path.dirname(_rt_os.path.abspath(__file__)), '../..'))
import remlab_tmp  # noqa: E402,I001  — временное теста на диске и с уборкой при выходе (T-20261107-13)
remlab_tmp.use('tests_form_gate')

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
        recs = FG.gate(out, glbs, ['s_1', 'нет_кадров'], {'s_1': 'шкаф'}, find_glb=lambda g, s: os.path.join(g, f'{s}-hd.glb'), vlm=False)      # без оценщика: mk() кладёт фото рядом, иначе — живой вызов шлюза без ключа (CI 22.11)
        self.assertEqual([r['sku'] for r in recs], ['s_1'])                          # без кадров товар не считается
        rec = json.load(open(os.path.join(out, 's_1', 'form_checks.json'), encoding='utf-8'))
        self.assertIn('status', rec)
        self.assertIn('body_skew', [c['name'] for c in rec['checks']])               # корпусная роль — проверка перекоса идёт
        rows = open(os.path.join(out, 'form_gate.tsv'), encoding='utf-8').read().splitlines()
        self.assertEqual(rows[0].split('\t'), list(FG.COLS))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1].split('\t')[0:2], ['s_1', 'шкаф'])

    def test_gate_without_find_glb_reaches_annotate(self):
        """Путь `forms_render --accept` → `form_gate.gate()` БЕЗ `find_glb`: `forms_render` подключается своим именем и не перекрывает `form_reseed` (T-20261127-175/Ш0-fix: `FR.annotate` падал AttributeError на каждой форме)."""
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        glbs, out = mk(tmp, 'n_1')
        recs = FG.gate(out, glbs, ['n_1'], {'n_1': 'шкаф'}, vlm=False, log=lambda x: None)                  # find_glb не передан — берётся forms_render.find_glb_
        self.assertEqual([r['sku'] for r in recs], ['n_1'])
        self.assertTrue(os.path.isfile(os.path.join(out, 'n_1', 'form_checks.json')))                       # дошли до annotate и записи отчёта
        self.assertIn('status', json.load(open(os.path.join(out, 'n_1', 'form_checks.json'), encoding='utf-8')))
        self.assertTrue(os.path.isfile(os.path.join(out, 'form_gate.tsv')))

    def alpha_frames(self, out, sku):
        """Кадры с альфой, как их кладёт рендер: `<sku>/alpha/<то же имя>` (форма — прямоугольник, шумный рельеф внутри)."""
        import numpy as np
        os.makedirs(os.path.join(out, sku, 'alpha'), exist_ok=True)
        rs = np.random.RandomState(7)
        for n in ('02_az000_clay_graze.png', '05_az180_clay_graze.png'):
            g = np.clip(128 + rs.normal(0, 30, (240, 320)), 0, 255).astype(np.uint8)
            Image.fromarray(g).save(os.path.join(out, sku, n))
            m = np.zeros((240, 320, 4), np.uint8)
            m[30:210, 40:280, 3] = 255
            Image.fromarray(m).save(os.path.join(out, sku, 'alpha', n))

    def test_gate_passes_alpha_dir_and_computes_mask_checks(self):
        """T-20261127-175/Ш0-fix-2: form_gate отдаёт папку кадра в run_sku → при кадрах с альфой relief_graze/back_relief посчитаны (раньше alpha_dir=None — проверок не было вовсе)."""
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        glbs, out = mk(tmp, 'a_1')
        self.alpha_frames(out, 'a_1')
        rec = go(tmp, ['a_1'], {'a_1': 'шкаф'}, vlm=False)[0]
        ch = {c['name']: c for c in rec['checks']}
        self.assertIsNotNone(ch['relief_graze']['value'])
        self.assertIsNotNone(ch['back_relief']['value'])
        self.assertEqual(rec['not_run'], [])
        self.assertEqual(json.load(open(os.path.join(out, 'a_1', 'form_checks.json'), encoding='utf-8'))['not_run'], [])

    def test_gate_without_alpha_says_not_run(self):
        """Без альфа-кадров — «не выполнена: нет альфа-кадра» в form_checks.json и в `not_run`, а не молчание и не «прошла»."""
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        glbs, out = mk(tmp, 'b_1')
        rec = go(tmp, ['b_1'], {'b_1': 'шкаф'}, vlm=False)[0]
        self.assertEqual(rec['not_run'], ['relief_graze', 'back_relief', 'back_dup_mask'])
        saved = json.load(open(os.path.join(out, 'b_1', 'form_checks.json'), encoding='utf-8'))
        ch = {c['name']: c for c in saved['checks']}
        for n in saved['not_run']:
            self.assertIsNone(ch[n]['value'])
            self.assertIn('не выполнена: нет альфа-кадра', ch[n]['note'])
            self.assertFalse(ch[n]['flag'])

    def test_main_prints_not_run_line(self):
        """CLI form_gate: итог говорит «проверки НЕ ВЫПОЛНЕНЫ у N из M форм» (подпроцесс настоящего form_gate на заглушках)."""
        import subprocess
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        glbs, out = mk(tmp, 'c_1')
        p = subprocess.run([sys.executable, '-I', '-W', 'ignore', os.path.join(HERE, 'form_gate.py'), '--out', out, '--glbs', glbs, '--skus', 'c_1', '--no-vlm', '--no-cards', '--roles', ''],
                           capture_output=True, text=True, cwd=tmp)
        self.assertEqual(p.returncode, 3, p.stderr[-400:])                          # не выполнено → код 3, не 0
        self.assertIn('проверки НЕ ВЫПОЛНЕНЫ у 1 из 1 форм', p.stdout)
        self.assertIn('back_relief', p.stdout)

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
        recs = go(tmp, ['k_1', 'k_2'], {'k_1': 'шкаф', 'k_2': 'комод'}, chat=ch, vlm_budget=0.02)        # общий потолок задан явно $0,02: на форму ≈ $0,0136 — вторая не влезает
        self.assertEqual(ch.calls, 9)                                                 # первая форма — обе группы (6 вызовов), у второй остаток $0,0064: группа b (≈$0,0083) не влезла, c (≈$0,0052) — да
        self.assertNotIn('vlm_skipped_budget', [c['name'] for c in recs[0]['checks']])
        names1 = [c['name'] for c in recs[1]['checks']]
        self.assertIn('vlm_skipped_budget', names1)
        self.assertNotIn('vlm_no_gaps', names1)
        self.assertIn('vlm_count_mismatch', names1)
        log = open(os.path.join(tmp, 'out', 'form_gate.log'), encoding='utf-8').read()
        self.assertIn('vlm оценка до запуска', log)                                   # оценка расхода — строкой в лог до вызовов
        self.assertIn('vlm итог', log)

    def test_default_budget_is_per_form_and_capped(self):
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        skus = [f'p_{i}' for i in range(10)]
        for i, s in enumerate(skus):
            mk(tmp, s, gray=20 + 10 * i)                                              # у каждой формы свои кадры — кэш не помогает
        ch = Chat()
        recs = go(tmp, skus, {s: 'шкаф' for s in skus}, chat=ch)
        self.assertEqual(ch.calls, 60)                                                # 10 форм × 6 вызовов: потолок 10 × $0,015 = $0,15 ≥ 10 × ≈$0,0136 — никто не пропущен
        self.assertFalse(any(c['name'] == 'vlm_skipped_budget' for r in recs for c in r['checks']))
        log = open(os.path.join(tmp, 'out', 'form_gate.log'), encoding='utf-8').read()
        self.assertIn('оцениваемых 10', log)
        self.assertIn('потолок $0.1500', log)

    def test_per_form_budget_counts_only_judged_forms_and_hard_max(self):
        tmp = tempfile.mkdtemp(prefix='tests_fg_')
        mk(tmp, 'k_1')
        mk(tmp, 'd_1', gray=60)
        ch = Chat()
        go(tmp, ['k_1', 'd_1'], {'k_1': 'шкаф', 'd_1': 'диван'}, chat=ch)
        log = open(os.path.join(tmp, 'out', 'form_gate.log'), encoding='utf-8').read()
        self.assertIn('оцениваемых 1', log)                                          # диван не оценивается — на него потолок не прибавляется
        self.assertIn('потолок $0.0150', log)
        tmp2 = tempfile.mkdtemp(prefix='tests_fg_')
        mk(tmp2, 'k_1')
        go(tmp2, ['k_1'], {'k_1': 'шкаф'}, chat=Chat(), vlm_budget=5.0)               # явный потолок выше общего предела — обрезается до $0,30
        log2 = open(os.path.join(tmp2, 'out', 'form_gate.log'), encoding='utf-8').read()
        self.assertIn('потолок $0.3000', log2)
        self.assertIn('предел сработал', log2)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
"""Тесты правила повтора формы (T-20261126-99/8): выбор лучшего из ВСЕХ образцов, класс Н не повторяется, «не удалось проверить» не повторяется, флаг выкл — запись побайтно та же.
Часть — на синтетических записях проверок, часть — на СОХРАНЁННЫХ проверках образцов T-99/1 (fixtures/t99_reseed_checks.json: без GLB, новых генераций нет). Запуск: python tests_form_reseed.py (numpy, trimesh, pillow — для проверки гейта)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import form_reseed as FR  # noqa: E402

R = FR.load_rules()
FIX = os.path.join(HERE, 'fixtures', 't99_reseed_checks.json')


def ck(name, value=1.0, flag=False, would=None):
    c = {'name': name, 'value': value, 'thr': 1, 'flag': flag, 'note': ''}
    if would is not None:
        c['would_flag'] = would
    return c


def rec(*checks, base=3):
    pad = [ck(f'ok{i}') for i in range(max(0, base))]                      # три измеренные «чистые» проверки: иначе «мало измерено»
    return {'sku': 'x', 'checks': pad + list(checks)}


class Mode(unittest.TestCase):
    def test_default_and_unknown_are_off(self):
        self.assertEqual(FR.mode({}), '0')
        self.assertEqual(FR.mode({'FORM_RESEED': 'yes'}), '0')
        self.assertEqual(FR.mode({'FORM_RESEED': 'shadow'}), 'shadow')
        self.assertEqual(FR.mode({'FORM_RESEED': '1'}), '1')

    def test_off_returns_same_object_without_new_keys(self):
        r = rec(ck('thin_width', 0.3, would=True))
        before = json.dumps(r, ensure_ascii=False, indent=1)
        out = FR.annotate(r, {})
        self.assertIs(out, r)
        self.assertEqual(json.dumps(out, ensure_ascii=False, indent=1), before)
        self.assertNotIn('reseed', out)

    def test_shadow_only_adds_plan_and_executes_nothing(self):
        r = rec(ck('thin_width', 0.3, would=True))
        out = FR.annotate(r, {'FORM_RESEED': 'shadow'})
        self.assertEqual(out['reseed']['action'], 'reseed')
        self.assertFalse(out['reseed']['executed'])
        self.assertEqual(out['reseed']['mode'], 'shadow')


class PlanOne(unittest.TestCase):
    def test_clean_form_kept(self):
        self.assertEqual(FR.plan_one(rec(), R)['action'], 'keep')

    def test_would_flag_counts_when_allowed(self):
        r = rec(ck('thin_width', 0.3, would=True))
        self.assertEqual(FR.plan_one(r, R)['class'], 'Т')
        off = dict(R, use_would_flag=False)
        self.assertEqual(FR.plan_one(r, off)['action'], 'keep')

    def test_class_n_is_quarantine_no_reseed(self):
        p = FR.plan_one(rec(ck('legs_match', 2.0, flag=True)), R)
        self.assertEqual((p['action'], p['quarantine'], p['reason']), ('refuse', 'quarantine_n', R['reasons']['quarantine_n']))
        self.assertNotIn('n_new', p)

    def test_class_n_wins_over_other_classes(self):
        p = FR.plan_one(rec(ck('thin_width', 0.3, would=True), ck('legs_match', 2.0, flag=True)), R)
        self.assertEqual((p['class'], p['action']), ('Н', 'refuse'))

    def test_derived_legs_flag_is_class_n(self):
        self.assertEqual(FR.plan_one(rec(ck('legs~', -1.0)), R)['class'], 'Н')
        self.assertEqual(FR.plan_one(rec(ck('legs~', 0.0)), R)['action'], 'keep')

    def test_reseed_classes_get_n_new(self):
        for name, cls in (('thin_len', 'Т'), ('detached', 'Л'), ('open_edges', 'У'), ('sil_miss', 'С')):
            p = FR.plan_one(rec(ck(name, 9.0, flag=True)), R)
            self.assertEqual((p['action'], p['class'], p['n_new']), ('reseed', cls, R['n_new_max']), name)

    def test_unnamed_class_from_vlm_is_reseeded_and_lower_priority(self):
        p = FR.plan_one(rec(ck('vlm_table_shape', 3, flag=True)), R)
        self.assertEqual((p['action'], p['class']), ('reseed', '?'))
        p2 = FR.plan_one(rec(ck('vlm_table_shape', 3, flag=True), ck('detached', 1, flag=True)), R)
        self.assertEqual(p2['class'], 'Л')                                             # названный класс сильнее «?»
        p3 = FR.plan_one(rec(ck('vlm_table_shape', 3, flag=True), ck('vlm_count_mismatch', 3, flag=True)), R)
        self.assertEqual((p3['class'], p3['action']), ('Н', 'refuse'))

    def test_cannot_check_is_refused_without_reseed(self):
        for r in (rec(ck('glb_sane', None, flag=True)), {'sku': 'x', 'checks': [ck('a'), ck('b')]}, rec(ck('mystery', 1.0, flag=True))):
            p = FR.plan_one(r, R)
            self.assertEqual((p['action'], p['reason']), ('refuse', R['reasons']['unverifiable']))
            self.assertNotIn('n_new', p)


class Decide(unittest.TestCase):
    def test_best_of_all_not_first_passing(self):
        bad2 = rec(ck('detached', 1, flag=True), ck('open_edges', 1, flag=True))          # счёт 2
        bad1 = rec(ck('detached', 1, flag=True))                                          # счёт 1 — лучше, но не проходит
        d = FR.decide([bad2, bad1, bad2], R)
        self.assertEqual((d['action'], d['reason']), ('refuse', R['reasons']['none_passed']))
        self.assertEqual(d['best'], 1)

    def test_pick_good_new_sample(self):
        d = FR.decide([rec(ck('thin_len', 3, flag=True)), rec(ck('thin_len', 3, flag=True), ck('detached', 1, flag=True)), rec()], R)
        self.assertEqual((d['action'], d['chosen']), ('pick', 2))

    def test_lowest_score_wins_even_if_later(self):
        r0 = rec(ck('thin_len', 3, flag=True), ck('detached', 1, flag=True), ck('open_edges', 1, flag=True))
        r1 = rec(ck('thin_len', 3, flag=True), ck('detached', 1, flag=True))
        r2 = rec()
        d = FR.decide([r0, r1, r2, rec()], R)
        self.assertEqual(d['chosen'], 2)                                                  # второй новый, четвёртый не рассматривается (n_new_max = 2)

    def test_tie_prefers_original(self):
        a, b = rec(), rec()
        self.assertEqual(FR.decide([a, b], R)['chosen'], 0)

    def test_class_n_not_repeated_even_if_new_samples_are_clean(self):
        d = FR.decide([rec(ck('legs_match', 2.0, flag=True)), rec(), rec()], R)
        self.assertEqual((d['action'], d['quarantine'], d['chosen']), ('refuse', 'quarantine_n', None))

    def test_unverifiable_not_repeated(self):
        d = FR.decide([rec(ck('glb_sane', None, flag=True)), rec(), rec()], R)
        self.assertEqual((d['action'], d['reason']), ('refuse', R['reasons']['unverifiable']))

    def test_unverifiable_new_sample_is_not_a_candidate(self):
        few = {'sku': 'x', 'checks': [ck('a'), ck('b')]}                                  # счёт 0, но измерено мало — кандидатом быть не может
        d = FR.decide([rec(ck('thin_len', 3, flag=True)), few, rec(ck('detached', 1, flag=True), ck('open_edges', 1, flag=True))], R)
        self.assertEqual((d['action'], d['best']), ('refuse', 0))

    def test_only_original_and_reseed_needed_means_reseed_plan(self):
        self.assertEqual(FR.decide([rec(ck('thin_len', 3, flag=True))], R)['action'], 'reseed')


class Saved(unittest.TestCase):
    """На сохранённых проверках образцов T-99/1 (без GLB): правило отрабатывает по всем 40 размеченным формам, детерминированно, без обращений к сети и генерации."""

    @classmethod
    def setUpClass(cls):
        cls.fx = json.load(open(FIX, encoding='utf-8'))

    def test_shadow_runs_on_all_saved_samples(self):
        sh = FR.shadow(self.fx['raw'], self.fx['eye'], self.fx['key'], R)
        self.assertEqual(len(sh['forms']), 40)
        self.assertEqual(len(sh['items']), 8)
        self.assertEqual(sh['forms'], FR.shadow(self.fx['raw'], self.fx['eye'], self.fx['key'], R)['forms'])

    def test_class_n_items_are_never_reseeded(self):
        sh = FR.shadow(self.fx['raw'], self.fx['eye'], self.fx['key'], R)
        for x in sh['items']:
            if x['first_class'] == 'Н':
                self.assertEqual((x['action'], x['quarantine']), ('refuse', 'quarantine_n'))

    def test_best_of_all_is_minimum_score_on_saved(self):
        sh = FR.shadow(self.fx['raw'], self.fx['eye'], self.fx['key'], R)
        by = {(f['item'], f['kind']): f for f in sh['forms']}
        for x in sh['items']:
            if x['action'] != 'pick':
                continue
            sc = {k: FR.verdict(self.fx['raw'][f"{x['item']}:{k}"]['rec'], R)['score'] for k in x['names']}
            self.assertEqual(sc[x['chosen']], min(v for k, v in sc.items() if not by[(x['item'], k)]['unverifiable']))


class Gate(unittest.TestCase):
    """Гейт с выключенным флагом пишет form_checks.json побайтно так же, как до правила; с shadow — те же байты плюс один ключ."""

    def run_gate(self, env):
        import trimesh
        from PIL import Image
        import form_gate as FG
        old = os.environ.get('FORM_RESEED')
        os.environ.pop('FORM_RESEED', None)
        if env is not None:
            os.environ['FORM_RESEED'] = env
        try:
            with tempfile.TemporaryDirectory() as tmp:
                glbs, out = os.path.join(tmp, 'glbs'), os.path.join(tmp, 'out')
                os.makedirs(glbs)
                os.makedirs(os.path.join(out, 's1'))
                trimesh.creation.box(extents=(1.0, 1.0, 0.5)).export(os.path.join(glbs, 's1-hd.glb'))
                os.makedirs(os.path.join(tmp, 'forms-inputs'))
                Image.new('RGBA', (64, 48), (200, 50, 50, 255)).save(os.path.join(tmp, 'forms-inputs', 's1.hd.rgba.png'))
                FG.gate(out, glbs, ['s1'], {}, vlm=False, cards=None, find_glb=lambda g, s: os.path.join(g, f'{s}-hd.glb'))
                return open(os.path.join(out, 's1', 'form_checks.json'), 'rb').read()
        finally:
            os.environ.pop('FORM_RESEED', None)
            if old is not None:
                os.environ['FORM_RESEED'] = old

    def test_off_is_byte_identical_to_unset_and_has_no_reseed_key(self):
        a, b = self.run_gate(None), self.run_gate('0')
        self.assertEqual(a, b)
        self.assertNotIn(b'reseed', a)

    def test_shadow_adds_only_reseed_key(self):
        base = json.loads(self.run_gate(None))
        sh = json.loads(self.run_gate('shadow'))
        self.assertIn('reseed', sh)
        sh.pop('reseed')
        self.assertEqual(sh, base)


if __name__ == '__main__':
    unittest.main(verbosity=1)

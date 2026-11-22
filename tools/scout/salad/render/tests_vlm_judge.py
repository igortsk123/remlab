#!/usr/bin/env python3
"""Тесты оценщика формы по картинке (T-184/9, observe): шлюз подменён, синтетические кадры; без сети, без ключа, без реальных товаров. Запуск: python tests_vlm_judge.py (нужны pillow, numpy, trimesh)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    from PIL import Image
    import form_checks as FC
    import vlm_judge as VJ
except ImportError as exc:                                                      # pragma: no cover
    raise SystemExit(f'нет зависимостей: {exc}')

RULES = FC.load_rules()
J = RULES['vlm_judge']


def mk_inputs():
    d = tempfile.mkdtemp(prefix='tests_vj_')
    fr = os.path.join(d, 'frames')
    os.makedirs(fr)
    for g in J['groups'].values():
        for f in g['frames']:
            Image.new('RGB', (64, 48), (120, 120, 120)).save(os.path.join(fr, f))
    ph = os.path.join(d, 'p.png')
    Image.new('RGBA', (64, 48), (200, 50, 50, 255)).save(ph)
    glb = os.path.join(d, 'a.glb')
    open(glb, 'wb').write(b'glb-bytes')
    return d, fr, ph, glb


class Chat:
    """Подмена llm_gateway.chat: отвечает «да» по видам из `yes` (в каждом прогоне, либо только в первом при once)."""
    def __init__(self, yes, once=False):
        self.yes, self.once, self.calls = set(yes), once, 0

    def __call__(self, model, messages, **kw):
        self.calls += 1
        txt = messages[0]['content'][0]['text']
        ks = [k for k in VJ.KINDS if f'"{k}":' in txt.split('Отвечай строго')[1]]
        on = self.yes if not (self.once and self.calls > 1 and False) else set()
        if self.once and self.calls % 2 == 0:
            on = set()
        ans = {k: ({'verdict': 'да', 'where': 'верх'} if k in on else {'verdict': 'нет', 'where': ''}) for k in ks}
        return {'choices': [{'message': {'content': json.dumps(ans, ensure_ascii=False)}}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}


class T(unittest.TestCase):
    def test_roles_pick_kinds(self):
        k = J['kinds']
        self.assertIn('no_gaps', VJ.applicable('Комод', k))
        self.assertNotIn('faceted', VJ.applicable('Комод', k))
        self.assertIn('faceted', VJ.applicable('ваза', k))
        self.assertEqual(VJ.applicable('диван', k), ['invented_detail'])

    def test_no_ids_in_rules(self):
        import re
        self.assertIsNone(re.search(r'\d{5,}_\d{6,}', json.dumps(J)))

    def test_flag_only_when_all_runs_yes_and_cache_hits(self):
        d, fr, ph, glb = mk_inputs()
        cache = os.path.join(d, 'c')
        ch = Chat({'ragged_facade'})
        out = VJ.judge('s', glb, ph, fr, 'шкаф', J, cache, ch)
        by = {c['name']: c for c in out}
        self.assertTrue(by['vlm_ragged_facade']['flag'])
        self.assertEqual(by['vlm_ragged_facade']['value'], 2)
        self.assertFalse(by['vlm_no_gaps']['flag'])
        self.assertEqual(ch.calls, 4)                       # группа a и b × 2 прогона
        out2 = VJ.judge('s', glb, ph, fr, 'шкаф', J, cache, ch)
        self.assertEqual(ch.calls, 4)                       # кэш: повтор бесплатный
        self.assertEqual([c['flag'] for c in out], [c['flag'] for c in out2])

    def test_one_yes_is_not_flag(self):
        d, fr, ph, glb = mk_inputs()
        out = VJ.judge('s', glb, ph, fr, 'шкаф', J, os.path.join(d, 'c'), Chat({'no_gaps'}, once=True))
        c = next(x for x in out if x['name'] == 'vlm_no_gaps')
        self.assertEqual(c['value'], 1)
        self.assertFalse(c['flag'])

    def test_version_change_invalidates_cache(self):
        d, fr, ph, glb = mk_inputs()
        cache = os.path.join(d, 'c')
        ch = Chat(set())
        VJ.judge('s', glb, ph, fr, 'диван', J, cache, ch)
        n = ch.calls
        VJ.judge('s', glb, ph, fr, 'диван', dict(J, version='другая'), cache, ch)
        self.assertGreater(ch.calls, n)

    def test_missing_frames_and_role_without_kinds_are_explicit(self):
        d, fr, ph, glb = mk_inputs()
        os.remove(os.path.join(fr, J['groups']['b']['frames'][2]))
        out = VJ.judge('s', glb, ph, fr, 'шкаф', J, os.path.join(d, 'c'), Chat(set()))
        c = next(x for x in out if x['name'] == 'vlm_b')
        self.assertIsNone(c['value'])
        self.assertIn('нет кадров', c['note'])
        none = VJ.judge('s', glb, ph, fr, 'шкаф', dict(J, kinds={'ragged_facade': {'group': 'a', 'roles': ['ваза']}}), os.path.join(d, 'c2'), Chat(set()))
        self.assertIn('видов нет', none[0]['note'])

    def test_run_sku_adds_vlm_checks_without_blocking(self):
        d, fr, ph, glb = mk_inputs()
        rec = FC.run_sku('s', os.path.join(d, 'нет.glb'), ph, fr, RULES, None, None, 'шкаф', os.path.join(d, 'c'), Chat({'ragged_facade'}))
        names = [c['name'] for c in rec['checks']]
        self.assertIn('vlm_ragged_facade', names)
        self.assertNotIn('vlm_ragged_facade', RULES['block'])


if __name__ == '__main__':
    unittest.main(verbosity=1)

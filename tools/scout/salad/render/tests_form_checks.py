#!/usr/bin/env python3
"""Тесты автопроверок формы (T-184/3, режим observe): синтетические меши и кадры, без видеокарты и без реальных товаров. Запуск: python tests_form_checks.py (venv scout: numpy, Pillow, scipy, trimesh)."""
from __future__ import annotations

import inspect
import json
import os
import re
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import numpy as np
    import trimesh
    from PIL import Image
    import form_checks as FC
except ImportError as exc:                                                      # pragma: no cover
    raise SystemExit(f'нет зависимостей: {exc}')

RULES = FC.load_rules()
R = RULES['thresholds']


def box(ext=(1.0, 0.5, 0.4), at=(0, 0, 0)):
    m = trimesh.creation.box(extents=ext)
    m.apply_translation(at)
    return m


def by(checks, name):
    return next(c for c in checks if c['name'] == name)


class Rules(unittest.TestCase):
    def test_block_list_and_complete(self):
        self.assertFalse(RULES['observe'])
        self.assertEqual(sorted(RULES['block']), ['detached', 'glb_sane', 'open_edges'])          # block — только GLB-проверки с 0 ложных на 27 годных (T-184/7)
        for k in ('alpha_min', 'mask_erode', 'relief_graze', 'back_relief', 'back_dup_mask', 'flat_back_roles'):
            self.assertIn(k, R)
        for k in ('min_extent', 'open_edge_share', 'detached_share', 'detached_piece_min', 'detached_gap', 'az_step', 'sil_points', 'holes_extra', 'leg_band', 'leg_fill', 'leg_min_w',
                  'back_dup_corr', 'bd_win', 'bd_sigma', 'bd_energy', 'relief_energy', 'sil_extra', 'sil_miss'):
            self.assertIn(k, R)

    def test_no_product_ids_in_code_or_rules(self):
        self.assertNotRegex(inspect.getsource(FC), r'\d{9,}')
        self.assertNotRegex(json.dumps(RULES), r'\d{9,}')


class Geometry(unittest.TestCase):
    def test_unreadable_and_zero_flagged(self):
        self.assertTrue(FC.glb_sane(None, 'сломан', R)['flag'])
        flat = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces=[[0, 1, 2]])
        self.assertTrue(FC.glb_sane(flat, '', R)['flag'])                       # нулевая толщина
        self.assertFalse(FC.glb_sane(box(), '', R)['flag'])

    def test_closed_box_no_open_edges_and_removed_faces_flagged(self):
        m = box()
        self.assertFalse(FC.open_edges(m, R)['flag'])
        holey = m.copy()
        holey.update_faces(np.arange(len(holey.faces)) % 3 != 0)                 # выбили треть граней
        self.assertTrue(FC.open_edges(holey, R)['flag'])

    def test_floating_piece_flagged_touching_leg_not(self):
        body = box((1, 0.4, 0.4), (0, 0.5, 0))
        leg = box((0.05, 0.3, 0.05), (0.4, 0.15, 0))                             # ножка упирается в корпус
        self.assertFalse(FC.detached(trimesh.util.concatenate([body, leg]), R)['flag'])
        far = box((0.3, 0.3, 0.3), (3.0, 3.0, 3.0))                              # парящий кусок далеко от корпуса
        self.assertTrue(FC.detached(trimesh.util.concatenate([body, far]), R)['flag'])
        tiny = box((0.02, 0.02, 0.02), (3.0, 3.0, 3.0))                          # мелкая пылинка — ниже detached_piece_min
        self.assertFalse(FC.detached(trimesh.util.concatenate([body, tiny]), R)['flag'])


class Silhouette(unittest.TestCase):
    def photo(self, w=200, h=100, inset=0):
        a = np.zeros((h, w, 4), np.uint8)
        a[inset:h - inset, inset:w - inset, 3] = 255
        d = tempfile.mkdtemp(prefix='tests_fc_')
        p = os.path.join(d, 'p.png')
        Image.fromarray(a).save(p)
        return p

    def test_best_azimuth_matches_box_and_values_present(self):
        m = box((1.0, 0.5, 0.2))
        pts = FC.surface_points(m, 60000)
        pm = FC.photo_mask(self.photo(200, 100))
        fs, az = FC.best_front(pts, pm, R)
        ch = FC.sil_checks(fs, pm, R, az)
        self.assertIn(az, (0.0, 180.0))
        self.assertLess(by(ch, 'sil_extra~')['value'], 0.1)
        self.assertLess(by(ch, 'sil_miss~')['value'], 0.1)

    def test_approx_values_do_not_flag_by_default(self):
        pts = FC.surface_points(box((1.0, 0.5, 0.2)), 60000)
        pm = FC.photo_mask(self.photo(200, 100))
        pm = pm.copy()
        pm[:, : pm.shape[1] // 2] = False
        pm[:pm.shape[0] // 2, pm.shape[1] // 2:] = False                          # фото с вырезанной «Г»-формой: у формы-коробки есть лишнее
        fs, az = FC.best_front(pts, pm, R)
        ch = FC.sil_checks(fs, pm, R, az)
        self.assertFalse(R['approx_flag'])
        self.assertFalse(any(c['flag'] for c in ch if c['name'].endswith('~')))
        strict = dict(R, approx_flag=True, sil_extra=0.0, sil_miss=0.0)
        self.assertTrue(any(c['flag'] for c in FC.sil_checks(fs, pm, strict, az) if c['name'].endswith('~')))

    def test_holes_extra_flagged(self):
        form = np.ones((100, 100), bool)
        form[10:90, 10:90] = False                                               # сквозное окно в силуэте формы (рамка 10 px)
        photo = np.ones((100, 100), bool)
        ch = FC.sil_checks(form, photo, R, 0.0)
        self.assertTrue(by(ch, 'holes')['flag'])
        self.assertFalse(by(FC.sil_checks(photo, photo, R, 0.0), 'holes')['flag'])

    def test_legs_runs(self):
        m = np.zeros((100, 100), bool)
        m[:80] = True
        m[80:, 10:20] = True
        m[80:, 70:80] = True
        self.assertEqual(FC.runs(m, R), 2)
        m2 = np.zeros((100, 100), bool)
        m2[:90] = True
        self.assertEqual(FC.runs(m2, R), 1)


class Pose(unittest.TestCase):
    def test_reads_stage04_and_flags_by_its_thresholds(self):
        root = tempfile.mkdtemp(prefix='tests_fc_pose_')
        d = os.path.join(root, 'g0', 's1', '04-camera')
        os.makedirs(d)
        c = {'metric': {'name': 'iou_silhouette', 'value': 0.7, 'threshold': 0.85, 'op': '>='},
             'metrics': {'extra': {'value': 0.02, 'threshold': 0.1, 'op': '<='}, 'miss': {'value': 0.2, 'threshold': 0.08, 'op': '<='}, 'miss_bottom': {'value': 0.1, 'threshold': 0.4, 'op': '<='}}}
        json.dump(c, open(os.path.join(d, 'check.json'), 'w'))
        ch = FC.pose_checks('s1', [root])
        self.assertTrue(by(ch, 'sil_iou')['flag'])
        self.assertTrue(by(ch, 'sil_miss')['flag'])
        self.assertFalse(by(ch, 'sil_extra')['flag'])
        self.assertFalse(by(ch, 'legs')['flag'])
        self.assertEqual(FC.pose_checks('нет', [root]), [])


class Frames(unittest.TestCase):
    def frames(self, a, b):
        d = tempfile.mkdtemp(prefix='tests_fc_fr_')
        Image.fromarray(a.astype(np.uint8)).save(os.path.join(d, '01_az000_clay.png'))
        Image.fromarray(b.astype(np.uint8)).save(os.path.join(d, '05_az180_clay.png'))
        return d

    def noise(self, seed, amp):
        return np.clip(128 + np.random.RandomState(seed).normal(0, amp, (240, 320)), 0, 255)

    def test_relief_flagged_only_when_rough(self):
        smooth = FC.back_dup(self.frames(self.noise(1, 1.0), self.noise(2, 1.0)), R)
        rough = FC.back_dup(self.frames(self.noise(1, 40.0), self.noise(2, 40.0)), R)
        self.assertFalse(by(smooth, 'relief')['flag'])
        self.assertTrue(by(rough, 'relief')['flag'])

    def test_back_dup_copy_detected_when_flag_on_and_off_by_rule(self):
        a = self.noise(3, 20.0)
        d = self.frames(a, a)
        on = FC.back_dup(d, dict(R, back_dup_flag=True))
        self.assertGreater(by(on, 'back_dup')['value'], 0.9)
        self.assertTrue(by(on, 'back_dup')['flag'])
        self.assertFalse(by(FC.back_dup(d, dict(R, back_dup_flag=False)), 'back_dup')['flag'])      # по умолчанию — только значение (не отделяет копию от симметрии)

    def test_back_dup_not_applicable_on_flat(self):
        flat = np.full((240, 320), 128.0)
        ch = FC.back_dup(self.frames(flat, flat), R)
        self.assertFalse(by(ch, 'back_dup')['flag'])
        self.assertIn('не применима', by(ch, 'back_dup')['note'])

    def test_missing_frames(self):
        ch = FC.back_dup(tempfile.mkdtemp(prefix='tests_fc_none_'), R)
        self.assertIsNone(ch[0]['value'])


class MaskChecks(unittest.TestCase):
    """Проверки по кадрам с альфой (T-184/7): синтетические кадры, без видеокарты."""

    def sku_dir(self, a0, a180, same_mask=True):
        d = tempfile.mkdtemp(prefix='tests_fc_mask_')
        os.makedirs(os.path.join(d, 'alpha'))
        for n, a in (('02_az000_clay_graze.png', a0), ('06_az180_clay_graze.png', a180)):
            Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).save(os.path.join(d, n))
            m = np.zeros((a.shape[0], a.shape[1], 4), np.uint8)
            m[30:210, 40:280, 3] = 255                                                # форма — прямоугольник; вне него альфа 0
            Image.fromarray(m).save(os.path.join(d, 'alpha', n))
        return d

    def noise(self, seed, amp):
        return 128 + np.random.RandomState(seed).normal(0, amp, (240, 320))

    def test_values_inside_mask_only(self):
        a = self.noise(1, 1.0)
        b = self.noise(2, 1.0)
        loud_bg = self.noise(3, 60.0)
        loud_bg[30:210, 40:280] = 128                                                # шум только ВНЕ маски — на значение не влияет
        ch = FC.mask_checks(self.sku_dir(loud_bg, b), 'шкаф', dict(R, relief_graze=5.0, back_relief=5.0))
        self.assertFalse(by(ch, 'relief_graze')['flag'])
        self.assertLess(by(ch, 'relief_graze')['value'], 1.0)

    def test_flat_back_role_flagged_on_rough_back_only(self):
        smooth, rough = self.noise(1, 1.0), self.noise(2, 40.0)
        rules = dict(R, back_relief=10.0)
        self.assertTrue(by(FC.mask_checks(self.sku_dir(smooth, rough), 'шкаф', rules), 'back_relief')['flag'])
        self.assertFalse(by(FC.mask_checks(self.sku_dir(smooth, rough), 'торшер', rules), 'back_relief')['flag'])   # роль без плоской спины — не применима
        self.assertFalse(by(FC.mask_checks(self.sku_dir(smooth, smooth), 'шкаф', rules), 'back_relief')['flag'])

    def test_back_dup_mask_copy_only_for_flat_back(self):
        a = self.noise(5, 30.0)
        rules = dict(R, back_dup_mask=0.9)
        ch = FC.mask_checks(self.sku_dir(a, a), 'комод', rules)
        self.assertTrue(by(ch, 'back_dup_mask')['flag'])
        self.assertFalse(by(FC.mask_checks(self.sku_dir(a, a), 'ваза', rules), 'back_dup_mask')['flag'])
        self.assertFalse(by(FC.mask_checks(self.sku_dir(a, self.noise(6, 30.0)), 'комод', rules), 'back_dup_mask')['flag'])

    def test_no_alpha_frames_gives_nothing(self):
        self.assertEqual(FC.mask_checks(tempfile.mkdtemp(prefix='tests_fc_none_'), 'шкаф', R), [])


class Status(unittest.TestCase):
    def test_status_levels(self):
        ck = lambda *names: [FC.check(n, 1.0, 0.5, True) for n in names]
        self.assertEqual(FC.status_of([], ['open_edges']), 'pass')
        self.assertEqual(FC.status_of(ck('open_edges'), ['open_edges']), 'shape_reject')
        self.assertEqual(FC.status_of(ck('sil_iou', 'sil_extra'), ['open_edges']), 'camera_or_mask_uncertain')   # провал контура этапа 04 — не доказательство брака формы
        self.assertEqual(FC.status_of(ck('sil_iou', 'relief'), ['open_edges']), 'needs_review')
        self.assertEqual(FC.status_of(ck('sil_iou', 'open_edges'), ['open_edges']), 'shape_reject')

    def test_summary_counts_caught_and_false(self):
        recs = [{'sku': 'a', 'checks': [FC.check('x', 1, 0, True)]}, {'sku': 'b', 'checks': [FC.check('x', 1, 0, True)]}, {'sku': 'c', 'checks': [FC.check('x', 0, 0, False)]}]
        t = FC.summary(recs, {'a': {'verdict': 'брак'}, 'b': {'verdict': 'годна'}, 'c': {'verdict': 'годна'}})
        self.assertIn('| x | 1 | 1 |', t)


class Run(unittest.TestCase):
    def test_block_status_for_unreadable_glb(self):
        d = tempfile.mkdtemp(prefix='tests_fc_blk_')
        rec = FC.run_sku('s', os.path.join(d, 'нет.glb'), None, None, RULES)
        self.assertEqual(rec['status'], 'shape_reject')
        self.assertFalse(rec['observe'])

    def test_observe_verdict_written_not_blocking(self):
        d = tempfile.mkdtemp(prefix='tests_fc_run_')
        g = os.path.join(d, 'a.glb')
        box().export(g)
        rec = FC.run_sku('s', g, None, None, RULES)
        self.assertEqual(rec['status'], rec['status'] if rec['auto'] == 'flag' else 'pass')
        self.assertIn(rec['auto'], ('ok', 'flag'))
        self.assertTrue(by(rec['checks'], 'open_edges'))
        bad = FC.run_sku('s2', os.path.join(d, 'нет.glb'), None, None, RULES)
        self.assertEqual(bad['auto'], 'flag')
        self.assertEqual(bad['flags'], ['glb_sane'])

    def test_table_counts_agreement(self):
        recs = [{'sku': 'a', 'auto': 'ok', 'flags': [], 'checks': []}, {'sku': 'b', 'auto': 'ok', 'flags': [], 'checks': []}]
        t = FC.table(recs, {'a': {'verdict': 'годна'}, 'b': {'verdict': 'брак'}}, ['relief'])
        self.assertIn('совпало с глазом: 1 из 2', t)


if __name__ == '__main__':
    unittest.main(verbosity=1)

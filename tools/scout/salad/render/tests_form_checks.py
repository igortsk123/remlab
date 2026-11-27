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
        self.assertNotIn('observe', RULES)               # мёртвый ключ удалён (T-175/В-реестр): режим задаёт список `block`, а `observe` в записи = not block (form_checks.py:646)
        self.assertEqual(sorted(RULES['block']), ['detached', 'glb_sane', 'open_edges'])          # block — только GLB-проверки с 0 ложных на 27 годных (T-184/7)
        for k in ('alpha_min', 'mask_erode', 'relief_graze', 'back_relief', 'back_dup_mask', 'flat_back_roles'):
            self.assertIn(k, R)
        for k in ('min_extent', 'open_edge_share', 'detached_share', 'detached_piece_min', 'detached_gap', 'az_step', 'sil_points', 'holes_extra', 'holes_table_legs', 'holes_table_iou', 'leg_band', 'leg_fill', 'leg_min_w',
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

    def table_form(self):
        """Стол на 4 ножках с перекладинами: столешница сверху, 4 ножки, две перекладины → просветы между ножками (как у формы, ложно звонившей)."""
        f = np.zeros((100, 100), bool)
        f[:10] = True
        for x in (0, 30, 60, 90):
            f[10:, x:x + 10] = True
        f[50:60] = True
        f[75:85] = True
        return f

    def weak_photo(self):
        p = np.zeros((100, 100), bool)
        p[:30, 20:80] = True                                                      # фото со слабо похожим силуэтом (IoU формы < 0,5), у фото просветов нет
        return p

    def test_holes_table_on_legs_poor_iou_does_not_ring(self):
        form = self.table_form()
        self.assertEqual(FC.runs(FC.norm(form), R), 4)
        h = by(FC.sil_checks(form, self.weak_photo(), R, 75.0), 'holes')
        self.assertGreater(h['value'], R['holes_extra'])                         # значение пишется честно
        self.assertFalse(h['flag'])
        self.assertTrue(h.get('would_flag'))
        self.assertIn('НЕ звонит', h['note'])

    def test_holes_table_good_iou_still_rings(self):
        form = self.table_form()
        photo = np.ones((100, 100), bool)                                        # фото — сплошная плита во весь кадр: IoU с формой ≈ 0,58 ≥ порога, просветы формы — настоящая дыра
        h = by(FC.sil_checks(form, photo, R, 0.0), 'holes')
        self.assertGreater(h['value'], R['holes_extra'])
        self.assertTrue(h['flag'])                                                # IoU ≥ порога → правило не включается
        self.assertNotIn('would_flag', h)

    def test_holes_real_hole_without_legs_still_rings(self):
        form = np.ones((100, 100), bool)
        form[10:90, 10:90] = False                                               # настоящая сквозная дыра, опор нет (рамка)
        h = by(FC.sil_checks(form, self.weak_photo(), R, 0.0), 'holes')          # IoU низкий, но опор < 3 → правило не включается
        self.assertTrue(h['flag'])
        self.assertNotIn('would_flag', h)

    def test_holes_table_rule_is_configurable(self):
        off = dict(R, holes_table_legs=99)
        self.assertTrue(by(FC.sil_checks(self.table_form(), self.weak_photo(), off, 75.0), 'holes')['flag'])

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


class LegsMatch(unittest.TestCase):
    """«Ножки» (T-184/8): синтетические маски; логика р.3."""

    def masks(self, shift=0, n_mesh=3):
        pa = np.zeros((200, 300), bool)
        pa[10:140, 20:280] = True
        for x in (30, 140, 250):
            pa[140:190, x:x + 14] = True
        S = np.zeros_like(pa)
        S[10:140, 20:280] = True
        for x in (30, 140, 250)[:n_mesh]:
            S[140:190, x + shift:x + shift + 14] = True
        return S, pa

    def test_matching_legs_ok_shifted_flagged(self):
        S, pa = self.masks(0)
        self.assertFalse(FC.legs_match(S, pa, R)['flag'])
        S, pa = self.masks(shift=30)
        c = FC.legs_match(S, pa, R)
        self.assertTrue(c['flag'])                                               # сдвиг 30 px при толщине ножки 14 px: ошибка/толщина ≈ 2 > 0,5; силуэт-IoU такого почти не видит
        self.assertGreater(c["value"], 0.6)
        S, pa = self.masks(shift=3)
        self.assertFalse(FC.legs_match(S, pa, R)['flag'])                        # 3 px при толщине 14 — 0,21 < 0,5: годная

    def test_different_count_flagged_single_leg_not_counted(self):
        S, pa = self.masks(0, n_mesh=2)
        c = FC.legs_match(S, pa, R)
        self.assertTrue(c['flag'])                                               # число ножек фото/формы 3/2 — провал сверки (T-191/3)
        one = np.zeros((100, 100), bool)
        one[:90, 20:80] = True
        c1 = FC.legs_match(one, one, R)
        self.assertIsNone(c1['value'])                                           # одна широкая ножка/цоколь — не применима
        self.assertFalse(c1['flag'])

    def test_no_run_gives_nothing(self):
        self.assertEqual(FC.legs_checks('нет', None, [tempfile.mkdtemp(prefix='tests_fc_legs_')], R), [])


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

    def test_no_alpha_frames_is_not_run_not_silent(self):
        """Нет альфа-кадра — НЕ пусто и не «прошла»: три записи «не выполнена: нет альфа-кадра» (T-20261127-175/Ш0-fix-2)."""
        ch = FC.mask_checks(tempfile.mkdtemp(prefix='tests_fc_none_'), 'шкаф', R)
        self.assertEqual([c['name'] for c in ch], list(FC.MASK_NAMES))
        for c in ch:
            self.assertTrue(c.get('skipped'))
            self.assertIsNone(c['value'])
            self.assertFalse(c['flag'])                                              # OBSERVE: статус формы не меняется
            self.assertIn('не выполнена: нет альфа-кадра', c['note'])

    def test_run_sku_records_not_run_without_alpha(self):
        """run_sku без папки альфа-кадров: в записи `not_run` и три «не выполнена»; с кадрами — `not_run` пуст, значения посчитаны."""
        rec = FC.run_sku('s', None, None, None, RULES)
        self.assertEqual(rec['not_run'], list(FC.MASK_NAMES))
        self.assertIn('не выполнена', by(rec['checks'], 'back_relief')['note'])
        d = self.sku_dir(self.noise(1, 1.0), self.noise(2, 40.0))
        rec2 = FC.run_sku('s', None, None, None, RULES, alpha_dir=d, role='шкаф')
        self.assertEqual(rec2['not_run'], [])
        self.assertIsNotNone(by(rec2['checks'], 'relief_graze')['value'])
        self.assertIsNotNone(by(rec2['checks'], 'back_relief')['value'])

    def test_no_frames_0_180_is_not_run(self):
        d = tempfile.mkdtemp(prefix='tests_fc_nof_')
        os.makedirs(os.path.join(d, 'alpha'))                                        # папка есть, кадров 0°/180° нет
        ch = FC.mask_checks(d, 'шкаф', R)
        self.assertEqual([c['name'] for c in ch], list(FC.MASK_NAMES))
        self.assertTrue(all(c.get('skipped') and 'не выполнена' in c['note'] for c in ch))


def card(w=100.0, d=40.0, h=200.0, **kw):
    return dict({'w': w, 'd': d, 'h': h, 'len': None, 'dia': None, 'src': {'w': 'param', 'd': 'param', 'h': 'param'}}, **kw)


class DimsVsCard(unittest.TestCase):
    """T-20261124-11: мерка «габарит формы ÷ габарит карточки по трём осям» (паспорт #130/#132/#145), observe."""

    @staticmethod
    def form(w=1.0, d=0.4, h=2.0):
        return box((w, h, d))                                                    # trimesh: extents по (x, y, z); y — вертикаль

    def test_rules_have_all_dims_thresholds_and_observe_by_default(self):
        for k in ('dims_flag', 'dims_points', 'dims_pct', 'dims_rot_step', 'dims_anchor', 'dims_depth_over', 'dims_depth_under', 'dims_axis_dev'):
            self.assertIn(k, R)
        self.assertFalse(R['dims_flag'])                                          # observe: флага нет, пока не откалиброван порог
        self.assertNotIn('dims_depth', RULES['block'])
        self.assertNotIn('dims_axes', RULES['block'])

    def test_exact_form_is_clean_control(self):
        d, a = FC.dims_vs_card(self.form(), card(), R)
        self.assertEqual((d['name'], a['name']), ('dims_depth', 'dims_axes'))
        self.assertAlmostEqual(d['value'], 0.0, delta=0.03)
        self.assertLess(a['value'], 0.03)
        self.assertFalse(d['would_flag'] or a['would_flag'] or d['flag'] or a['flag'])

    def test_thick_depth_would_flag_but_observe_has_no_flag(self):
        d, a = FC.dims_vs_card(self.form(d=0.52), card(), R)                      # +30 % глубины при верных ширине и высоте (шкаф-ящик)
        self.assertAlmostEqual(d['value'], 0.30, delta=0.03)
        self.assertTrue(d['would_flag'])
        self.assertTrue(a['would_flag'])
        self.assertFalse(d['flag'] or a['flag'])                                  # observe
        self.assertIn('глубина', d['note'])

    def test_flag_appears_only_when_switched_on(self):
        on = dict(R, dims_flag=True)
        d, a = FC.dims_vs_card(self.form(d=0.52), card(), on)
        self.assertTrue(d['flag'] and a['flag'])

    def test_just_under_threshold_is_not_flagged(self):
        d, a = FC.dims_vs_card(self.form(d=0.44), card(), R)                      # +10 % — медиана по каталогу, не брак
        self.assertFalse(d['would_flag'] or a['would_flag'])

    def test_thin_form_is_caught_by_under_threshold(self):
        d, _a = FC.dims_vs_card(self.form(d=0.1), card(), R)                      # лента/стержень: −75 % глубины
        self.assertLess(d['value'], -R['dims_depth_under'])
        self.assertTrue(d['would_flag'])

    def test_rotation_about_vertical_does_not_change_result(self):
        import trimesh
        for deg in (90, 37, 45):
            m = self.form(d=0.52)
            m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(deg), [0, 1, 0]))
            d, _ = FC.dims_vs_card(m, card(), R)
            self.assertAlmostEqual(d['value'], 0.30, delta=0.04, msg=f'поворот {deg}°')

    def test_square_footprint_has_no_axis_ambiguity(self):
        d, a = FC.dims_vs_card(self.form(w=1.0, d=1.0), card(w=100, d=100), R)    # у PCA ось квадрата произвольна и раздувала бы габарит в √2
        self.assertLess(abs(d['value']), 0.03)
        self.assertLess(a['value'], 0.03)

    def test_small_floating_piece_is_trimmed_by_percentiles(self):
        body = self.form()
        far = box((0.02, 0.02, 0.02), at=(3.0, 0, 3.0))                           # крошечный выброс далеко: меньше 0,3 % площади
        d, a = FC.dims_vs_card(trimesh_concat(body, far), card(), R)
        self.assertLess(a['value'], 0.05)
        self.assertFalse(a['would_flag'])

    def test_derived_axis_is_not_a_reference(self):
        c = card(src={'w': 'param', 'd': 'role_prior', 'h': 'param'})             # глубина выведена приором — сверять форму с её же приором нельзя
        d, a = FC.dims_vs_card(self.form(d=0.52), c, R)
        self.assertIsNone(d['value'])
        self.assertIsNone(a['value'])
        self.assertIn('горизонтальных', d['note'])
        self.assertFalse(d['would_flag'])
        c2 = card(src={'w': 'param', 'd': 'param', 'h': 'mesh_ratio'})
        self.assertIn('высоты', FC.dims_vs_card(self.form(), c2, R)[0]['note'])

    def test_not_reference_list_is_the_single_one_from_dimless(self):
        rx = FC.reference_rx()                                                     # добавляет tools/scout в путь импорта
        import dimless
        self.assertEqual(rx.pattern, dimless.NOT_REFERENCE_RX)

    def test_no_card_gives_reason_not_a_number(self):
        for c in ({}, None):
            d, a = FC.dims_vs_card(self.form(), c, R)
            self.assertIsNone(d['value'])
            self.assertIn('нет карточки', a['note'])

    def test_diameter_card_is_skipped_by_default_and_counted_when_enabled(self):
        c = {'w': None, 'd': 25.0, 'h': 150.0, 'len': None, 'dia': 30.0, 'src': {'d': 'param', 'h': 'param', 'dia': 'param'}}
        m = box((0.9, 1.5, 0.3))                                                   # дуга торшера: след шире диаметра в 3 раза
        d, a = FC.dims_vs_card(m, c, R)
        self.assertIsNone(d['value'])                                              # по умолчанию диаметр не сверяем с габаритом следа (замер: +130 % при верной высоте)
        self.assertIn('диаметру', d['note'])
        on = dict(R, dims_dia_axes=True)
        d2, a2 = FC.dims_vs_card(box((0.3, 1.5, 0.3)), c, on)                      # круглая опора: след = диаметр
        self.assertEqual(d2['basis'], 'dia')
        self.assertLess(abs(d2['value']), 0.03)
        self.assertLess(a2['value'], 0.03)

    def test_basis_is_recorded(self):
        d, a = FC.dims_vs_card(self.form(), card(), R)
        self.assertEqual((d['basis'], a['basis']), ('wd', 'wd'))
        c = card(d=None, len=40.0)                                                 # длина вместо глубины
        c['src']['len'] = 'param'
        self.assertEqual(FC.dims_vs_card(self.form(), c, R)[0]['basis'], 'wl')

    def test_median_anchor_survives_wrong_card_height(self):
        c = card(h=300.0)                                                          # высота карточки завышена в 1,5 раза; ширина и глубина верны
        by_h = FC.dims_vs_card(self.form(), c, R)[0]['value']
        by_med = FC.dims_vs_card(self.form(), c, dict(R, dims_anchor='median'))[0]['value']
        self.assertLess(abs(by_med), 0.03)                                         # по медиане трёх осей ошибка высоты не портит глубину
        self.assertGreater(abs(by_h), 0.3)

    def test_run_sku_adds_dims_only_when_card_is_given(self):
        import trimesh
        with tempfile.TemporaryDirectory() as td:
            g = os.path.join(td, 's-hd.glb')
            self.form(d=0.52).export(g)
            names = lambda rec: [c['name'] for c in rec['checks']]
            self.assertNotIn('dims_depth', names(FC.run_sku('s', g, None, None, RULES)))                     # старые вызовы без карточки — как прежде
            rec = FC.run_sku('s', g, None, None, RULES, card=card())
            self.assertIn('dims_depth', names(rec))
            self.assertEqual(rec['status'], 'pass')                                                           # would_flag не меняет статус (observe)
            self.assertNotIn('dims_depth', rec['flags'])
            nocard = FC.run_sku('s', g, None, None, RULES, card={})
            self.assertIsNone(next(c for c in nocard['checks'] if c['name'] == 'dims_depth')['value'])

    def test_cards_from_db_parses_rows_and_skips_bad_ids(self):
        seen = {}

        def runner(sql):
            seen['sql'] = sql
            return ('{"k":"1_2","w":100,"d":40,"h":200,"len":null,"dia":null,"src":{"w":"param","d":"param","h":"param","len":null,"dia":null}}\n'
                    'мусор\n')
        out = FC.cards_from_db(['1:2', "3_4'; drop table x;--", 'abc'], runner)
        self.assertEqual(sorted(out), ['1_2'])
        self.assertEqual(out['1_2']['h'], 200)
        self.assertNotIn('drop', seen['sql'])                                      # в запрос идут только числовые ключи
        self.assertEqual(FC.cards_from_db([], runner), {})

    def test_cards_from_db_failure_is_empty_not_crash(self):
        def boom(_sql):
            raise OSError('нет docker')
        self.assertEqual(FC.cards_from_db(['1_2'], boom), {})


class ThinVsPhoto(unittest.TestCase):
    """T-20261124-17: мерка по силуэту фото для тонких лент/стержней (паспорт #145), observe. Известная толщина — синтетика: стол (столешница + ножки-цилиндры), «фото» — маска фронта, нарисованная точно."""

    @staticmethod
    def table(leg_r=0.012, n_legs=4):
        top = trimesh.creation.box(extents=(1.0, 0.08, 0.6))
        top.apply_translation((0, 0.96, 0))
        legs = []
        for x, z in ((-0.42, -0.22), (0.42, -0.22), (-0.42, 0.22), (0.42, 0.22))[:n_legs]:
            c = trimesh.creation.cylinder(radius=leg_r, height=0.92, sections=24)
            c.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [1, 0, 0]))     # ось цилиндра у trimesh — Z, нужна вертикаль (Y)
            c.apply_translation((x, 0.46, z))
            legs.append(c)
        return trimesh.util.concatenate([top] + legs)

    @staticmethod
    def photo(leg_w=0.024, xs=(-0.42, 0.42), H=700, top_h=0.08):
        W = H
        m = np.zeros((H, W), bool)
        m[: int(top_h * H), :] = True
        lw = max(int(round(leg_w * H)), 1)
        for x in xs:
            cx = int((x + 0.5) * W)
            m[int(top_h * H):, max(cx - lw // 2, 0): cx - lw // 2 + lw] = True
        return m

    def front(self, **kw):
        return FC.sil_at(FC.surface_points(self.table(**kw), int(R['thin_points']), seed=1), 0.0, int(R['thin_grid']))

    def test_rules_have_thresholds_and_observe_by_default(self):
        for k in ('thin_flag', 'thin_points', 'thin_grid', 'thin_h', 'thin_r', 'thin_comp_min', 'thin_min_len', 'thin_pair_dist', 'thin_pair_len', 'thin_min_pairs', 'thin_w_lo', 'thin_w_hi', 'thin_len_lo', 'thin_len_hi'):
            self.assertIn(k, R)
        self.assertFalse(R['thin_flag'])                                          # observe: флага нет, пока не откалиброван порог
        self.assertNotIn('thin_width', RULES['block'])
        self.assertNotIn('thin_len', RULES['block'])
        self.assertLess(R['thin_w_lo'], 1.0 < R['thin_w_hi'])

    def test_thin_parts_finds_legs_not_body(self):
        a = FC.thin_parts(self.photo(0.024), R)
        self.assertEqual(a['n'], 2)                                               # две ножки; столешница 8 % высоты — «толстая» (кругу радиуса 3 % она по высоте больше)
        self.assertAlmostEqual(a['w'], 0.024, delta=0.003)                        # толщина ножки в долях высоты — по определению, без дрожания на чётных/нечётных пикселях
        self.assertAlmostEqual(a['len'], 2 * 0.92, delta=0.25)
        fat = np.ones((200, 300), bool)                                           # сплошной прямоугольник — тонких частей нет
        self.assertEqual(FC.thin_parts(fat, R)['n'], 0)
        self.assertIsNone(FC.thin_parts(fat, R)['w'])

    def test_crumbs_at_rough_edge_are_not_ribbons(self):
        rng = np.random.default_rng(1)
        m = np.zeros((300, 300), bool)
        m[20:280, 20:280] = True
        edge = rng.random((300, 300)) < 0.08
        m |= np.roll(m, 3, axis=1) & edge                                           # рваный край толстого тела
        self.assertEqual(FC.thin_parts(m, R)['n'], 0)

    def test_exact_form_is_clean_control(self):
        d = FC.thin_checks(self.front(leg_r=0.012), self.photo(0.024), R, 0.0)
        w, ln = by(d, 'thin_width'), by(d, 'thin_len')
        self.assertAlmostEqual(w['value'], 1.0, delta=0.12)                       # в замере на разных толщинах 1,02–1,08 (точечный силуэт формы чуть «жирнее» точной маски)
        self.assertAlmostEqual(ln['value'], 1.0, delta=0.1)
        self.assertFalse(w['would_flag'] or ln['would_flag'] or w['flag'] or ln['flag'])
        self.assertEqual(w['pairs'], 2)

    def test_form_thicker_than_photo_would_flag_but_observe_has_no_flag(self):
        d = FC.thin_checks(self.front(leg_r=0.012), self.photo(0.012), R, 0.0)    # ножка формы вдвое толще, чем на фото
        w = by(d, 'thin_width')
        self.assertAlmostEqual(w['value'], 2.0, delta=0.35)
        self.assertTrue(w['would_flag'])
        self.assertFalse(w['flag'])                                                # observe
        self.assertIn('пар 2', w['note'])

    def test_form_thinner_than_photo_would_flag(self):
        d = FC.thin_checks(self.front(leg_r=0.012), self.photo(0.048), R, 0.0)    # ножка формы вдвое тоньше, чем на фото (лента/стержень)
        w = by(d, 'thin_width')
        self.assertAlmostEqual(w['value'], 0.5, delta=0.1)
        self.assertTrue(w['would_flag'])

    def test_moderate_deviation_inside_tolerance_is_quiet(self):
        w = by(FC.thin_checks(self.front(leg_r=0.012), self.photo(0.019), R, 0.0), "thin_width")     # на фото ножка на 20 % тоньше: перспектива и поворот
        self.assertFalse(w['would_flag'])
        w = by(FC.thin_checks(self.front(leg_r=0.012), self.photo(0.029), R, 0.0), "thin_width")     # на 20 % толще
        self.assertFalse(w['would_flag'])

    def test_flag_appears_only_when_switched_on(self):
        on = dict(R, thin_flag=True)
        w = by(FC.thin_checks(self.front(leg_r=0.012), self.photo(0.048), on, 0.0), 'thin_width')
        self.assertTrue(w['flag'] and w['would_flag'])

    def test_photo_without_thin_parts_is_not_applicable(self):
        d = FC.thin_checks(self.front(leg_r=0.012), np.ones((300, 400), bool), R, 0.0)
        w = by(d, 'thin_width')
        self.assertIsNone(w['value'])
        self.assertFalse(w['would_flag'] or w['flag'])
        self.assertIn('мерка неприменима', w['note'])

    def test_form_lost_thin_parts_is_reported_by_length_not_width(self):
        blob = np.ones((300, 300), bool)                                            # форма без ножек (плита), на фото ножки
        d = FC.thin_checks(blob, self.photo(0.024), R, 0.0)
        self.assertIsNone(by(d, 'thin_width')['value'])
        self.assertIn('пропали', by(d, 'thin_width')['note'])
        self.assertEqual(by(d, 'thin_len')['value'], 0.0)
        self.assertTrue(by(d, 'thin_len')['would_flag'])

    def test_legs_in_other_places_are_not_paired(self):
        d = FC.thin_checks(self.front(leg_r=0.012), self.photo(0.024, xs=(-0.1, 0.1)), R, 0.0)    # ножки фото далеко от ножек формы (другой ракурс/поза) — не пара
        w = by(d, 'thin_width')
        self.assertIsNone(w['value'])
        self.assertEqual(w['pairs'], 0)
        self.assertIn('пар', w['note'])

    def test_scale_invariance(self):
        a = FC.thin_checks(self.front(leg_r=0.012), self.photo(0.024, H=500), R, 0.0)
        b = FC.thin_checks(self.front(leg_r=0.012), self.photo(0.024, H=1400), R, 0.0)
        self.assertAlmostEqual(by(a, 'thin_width')['value'], by(b, 'thin_width')['value'], delta=0.08)

    def test_run_sku_writes_thin_checks_with_photo_and_skips_without(self):
        d = tempfile.mkdtemp(prefix='tests_fc_thin_')
        g = os.path.join(d, 't.glb')
        self.table().export(g)
        a = np.zeros((700, 700, 4), np.uint8)
        a[:, :, 3] = self.photo(0.024).astype(np.uint8) * 255
        p = os.path.join(d, 'p.png')
        Image.fromarray(a).save(p)
        rec = FC.run_sku('s', g, p, None, RULES)
        names = [c['name'] for c in rec['checks']]
        self.assertIn('thin_width', names)
        self.assertIn('thin_len', names)
        self.assertNotIn('thin_width', rec['flags'])                                # observe: флагом не становится
        self.assertEqual(rec['status'], 'pass' if rec['auto'] == 'ok' else rec['status'])
        none = FC.run_sku('s', g, None, None, RULES)
        self.assertIsNone(by(none['checks'], 'thin_width')['value'])
        self.assertIn('нет маски фото', by(none['checks'], 'thin_width')['note'])

    def test_run_is_independent_of_card_and_pose(self):
        # мерка толщины не зависит от карточки (dims_*) и позы этапа 04: работает на любом товаре с маской фото
        src = inspect.getsource(FC.thin_checks) + inspect.getsource(FC.thin_parts) + inspect.getsource(FC.thin_pairs)
        self.assertNotIn('card', src)
        self.assertNotIn('pose', src)


def trimesh_concat(*ms):
    import trimesh
    return trimesh.util.concatenate(list(ms))


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

    def test_body_skew_box_ok_and_wedge_flagged(self):
        import trimesh
        box_m = trimesh.creation.box(extents=(1.0, 2.0, 0.5))
        self.assertFalse(FC.body_skew(box_m, 'шкаф', RULES['thresholds'])[0]['flag'])
        wedge = box_m.copy()
        v = wedge.vertices.copy()
        top = v[:, 1] > 0
        v[top, 0] *= 0.7                                           # верх уже низа → стенки не параллельны (трапеция)
        wedge.vertices = v
        c = FC.body_skew(wedge, 'шкаф', RULES['thresholds'])[0]
        self.assertTrue(c['flag'])
        self.assertGreater(c['value'], RULES['thresholds']['body_skew_deg'])
        self.assertEqual(FC.body_skew(wedge, 'диван', RULES['thresholds']), [])          # не корпусная роль — не считаем

    def test_body_skew_ignores_wide_flared_legs(self):
        import trimesh
        body = trimesh.creation.box(extents=(1.0, 1.0, 0.5)); body.apply_translation((0, 1.0, 0))   # корпус y 0.5…1.5
        legs = [trimesh.creation.box(extents=(0.1, 0.5, 0.1)) for _ in range(4)]
        for lg, (x, z) in zip(legs, ((-0.7, -0.2), (0.7, -0.2), (-0.7, 0.2), (0.7, 0.2))):         # ножки шире корпуса, ниже 45 % высоты
            lg.apply_translation((x, 0.25, z))
        m = trimesh.util.concatenate([body] + legs)
        self.assertFalse(FC.body_skew(m, 'комод', RULES['thresholds'])[0]['flag'])

    def test_table_counts_agreement(self):
        recs = [{'sku': 'a', 'auto': 'ok', 'flags': [], 'checks': []}, {'sku': 'b', 'auto': 'ok', 'flags': [], 'checks': []}]
        t = FC.table(recs, {'a': {'verdict': 'годна'}, 'b': {'verdict': 'брак'}}, ['relief'])
        self.assertIn('совпало с глазом: 1 из 2', t)


def seat_stool(groove_cm: float):
    """Табурет-«стул»: ножки 37 см, сиденье 40×40 см (верх на 43 см), спинка до 80 см; на верхе сиденья борозды глубиной groove_cm с шагом 6 см (0 — гладкий)."""
    from trimesh.remesh import subdivide_to_size
    seat = trimesh.creation.box(extents=(40, 6, 40))
    seat.apply_translation((0, 40, 0))
    back = trimesh.creation.box(extents=(40, 40, 3))
    back.apply_translation((0, 60, -18.5))
    legs = []
    for x in (-17.0, 17.0):
        for z in (-17.0, 17.0):
            lg = trimesh.creation.box(extents=(4, 37, 4))
            lg.apply_translation((x, 18.5, z))
            legs.append(lg)
    parts = []
    for b in [seat, back] + legs:
        v, f = subdivide_to_size(b.vertices, b.faces, max_edge=0.6)
        parts.append(trimesh.Trimesh(v, f, process=True))
    s = parts[0]
    v = np.array(s.vertices)
    top = v[:, 1] > 42.99
    v[top, 1] -= groove_cm * np.maximum(0.0, np.sin(2 * np.pi * v[top, 0] / 6.0)) ** 2
    s = trimesh.Trimesh(v, s.faces, process=False)
    m = trimesh.util.concatenate([s] + parts[1:])
    m.merge_vertices()
    return m


class StitchDepth(unittest.TestCase):
    """T-20261124-57 (П1.160): мерка глубоких борозд стёжки — ± контроль на синтетике, тип и высота, режим OBSERVE."""

    def test_grooved_seat_would_flag_smooth_not(self):
        bad = by(FC.stitch_depth(seat_stool(0.9), 'стул', {'h': 80.0}, R), 'stitch_p95')
        good = by(FC.stitch_depth(seat_stool(0.0), 'стул', {'h': 80.0}, R), 'stitch_p95')
        self.assertTrue(bad['would_flag'], bad)
        self.assertGreater(bad['value'], R['stitch_p95_cm'])
        self.assertFalse(good['would_flag'], good)
        self.assertLess(good['value'], 0.1)

    def test_observe_flag_is_off(self):
        self.assertFalse(R['stitch_flag'])
        c = by(FC.stitch_depth(seat_stool(0.9), 'стул', {'h': 80.0}, R), 'stitch_p95')
        self.assertFalse(c['flag'])
        self.assertTrue(c['would_flag'])
        c = by(FC.stitch_depth(seat_stool(0.9), 'стул', {'h': 80.0}, dict(R, stitch_flag=True)), 'stitch_p95')
        self.assertTrue(c['flag'])

    def test_not_applicable_type_and_missing_height(self):
        m = seat_stool(0.9)
        c = by(FC.stitch_depth(m, 'шкаф', {'h': 80.0}, R), 'stitch_p95')
        self.assertIsNone(c['value'])
        self.assertFalse(c['would_flag'] or c['flag'])
        self.assertIn('не применима', c['note'])
        c = by(FC.stitch_depth(m, 'кресло', None, R), 'stitch_p95')
        self.assertIsNone(c['value'])
        self.assertIn('высоты', c['note'])

    def test_mesh_not_changed(self):
        m = seat_stool(0.9)
        before = np.array(m.vertices).copy()
        FC.stitch_depth(m, 'стул', {'h': 80.0}, R)
        self.assertTrue((before == np.array(m.vertices)).all())


def chair_sil(wave_amp_px: float = 0.0, period: float = 70.0, bow_px: float = 0.0, w: int = 30, legs_n: int = 2) -> np.ndarray:
    """Силуэт «сбоку»: корпус-сиденье 300×60 px сверху, под ним `legs_n` ножек шириной w и длиной 300 px; край одной ножки идёт синусоидой (wave_amp_px, период в строках) и/или дугой (bow_px)."""
    H, Wd = 400, 320
    m = np.zeros((H, Wd), bool)
    m[0:60, 10:310] = True
    xs = [30, 250] if legs_n == 2 else [30]
    yy = np.arange(60, 360)
    for k, x0 in enumerate(xs):
        for y in yy:
            off = 0.0
            if k == 0:
                off = wave_amp_px * np.sin(2 * np.pi * (y - 60) / period) + bow_px * (1 - ((y - 210) / 150.0) ** 2)
            a = int(round(x0 + off))
            m[y, a:a + w] = True
    return m


class LegWave(unittest.TestCase):
    """T-20261124-57 (П1.160): мерка волнистой ножки — прямая и дуга не срабатывают, длинная волна срабатывает; тип без ножек — None; OBSERVE."""

    def test_wavy_leg_would_flag_straight_and_arc_not(self):
        bad = by(FC.leg_wave(chair_sil(wave_amp_px=3.0), R), 'leg_wave')
        straight = by(FC.leg_wave(chair_sil(), R), 'leg_wave')
        arc = by(FC.leg_wave(chair_sil(bow_px=6.0), R), 'leg_wave')
        self.assertTrue(bad['would_flag'], bad)
        self.assertGreaterEqual(bad['value'], R['lw_amp'])
        self.assertFalse(straight['would_flag'], straight)
        self.assertFalse(arc['would_flag'], arc)                         # плавная дуга — законная форма ножки (сабля), не волна

    def test_two_humps_with_big_amplitude_not_flagged_only_by_hump_count(self):
        """Запас мерки (директор, T-57/2–3): ножка с амплитудой выше порога, но всего ДВА горба, не метится — её держит именно правило «≥ lw_min_ext горбов» (на 29: контроль с амплитудой 0,081 при 2 горбах)."""
        c = by(FC.leg_wave(chair_sil(wave_amp_px=4.0, period=160.0), R), 'leg_wave')
        lg = max(c['legs'], key=lambda l: l['amp'])
        self.assertGreaterEqual(lg['amp'], R['lw_amp'], c)              # амплитуда сама по себе выше порога
        self.assertLess(lg['n_ext'], R['lw_min_ext'], c)                # но горбов меньше трёх
        self.assertFalse(lg['wavy'] or c['would_flag'], c)
        self.assertEqual(c['value'], 0.0, c)
        c3 = by(FC.leg_wave(chair_sil(wave_amp_px=4.0, period=70.0), R), 'leg_wave')
        lg3 = max(c3['legs'], key=lambda l: l['amp'])
        self.assertGreaterEqual(lg3['n_ext'], R['lw_min_ext'], c3)      # та же амплитуда при трёх и более горбах — метка
        self.assertTrue(c3['would_flag'], c3)
        c_off = by(FC.leg_wave(chair_sil(wave_amp_px=4.0, period=160.0), dict(R, lw_min_ext=2)), 'leg_wave')
        self.assertTrue(c_off['would_flag'], c_off)                     # снять правило горбов — метка появилась бы: держит именно оно

    def test_observe_flag_off(self):
        self.assertFalse(R['leg_wave_flag'])
        c = by(FC.leg_wave(chair_sil(wave_amp_px=3.0), R), 'leg_wave')
        self.assertFalse(c['flag'])
        self.assertTrue(c['would_flag'])
        c = by(FC.leg_wave(chair_sil(wave_amp_px=3.0), dict(R, leg_wave_flag=True)), 'leg_wave')
        self.assertTrue(c['flag'])

    def test_no_legs_is_none(self):
        m = np.zeros((300, 300), bool)
        m[50:250, 20:280] = True                                         # плита/шкаф без ножек
        c = by(FC.leg_wave(m, R), 'leg_wave')
        self.assertIsNone(c['value'])
        self.assertFalse(c['would_flag'] or c['flag'])
        self.assertIn('ножек', c['note'])

    def test_input_not_changed(self):
        m = chair_sil(wave_amp_px=3.0)
        before = m.copy()
        FC.leg_wave(m, R)
        self.assertTrue((before == m).all())


def old_bbox_rule(m, R: dict) -> bool:
    """Прежнее правило detached (до 27.11) — для отрицательного контроля: тест обязан различать «вне габарита главного» и «без касания»."""
    comps = trimesh.graph.connected_components(m.face_adjacency, nodes=np.arange(len(m.faces)), min_len=1)
    area = m.area_faces
    order = sorted(range(len(comps)), key=lambda i: -float(area[comps[i]].sum()))
    main = m.vertices[np.unique(m.faces[comps[order[0]]])]
    gap = R['detached_gap'] * float(np.linalg.norm(m.extents))
    lo, hi = main.min(0) - gap, main.max(0) + gap
    tot_far = 0.0
    for i in order[1:]:
        sh = float(area[comps[i]].sum()) / float(area.sum())
        v = m.vertices[np.unique(m.faces[comps[i]])]
        if sh >= R['detached_piece_min'] and (np.any(v.max(0) < lo) or np.any(v.min(0) > hi)):
            tot_far += sh
    return tot_far > R['detached_share']


def disk_table(gap: float = 0.0):
    """Стол «плита + стойка + диск основания»: плита сверху (главный кусок), стойка, диск основания; куски раздельные. `gap` — зазор между стойкой и диском основания."""
    top = box((1.0, 0.04, 1.0), (0, 1.0, 0))
    base = box((0.8, 0.04, 0.8), (0, 0.02, 0))
    y0 = 0.04 + gap
    stem = box((0.1, 0.98 - y0, 0.1), (0, (0.98 + y0) / 2, 0))
    return trimesh.util.concatenate([top, stem, base])


class DetachedTouch(unittest.TestCase):
    """Правило detached на все товары (директор 27.11, P-064): «парящий» = БЕЗ касания (зазор > detached_gap габарита) с главным куском, прямо или цепочкой; не «вне габарита главного»."""

    def test_params_in_rules(self):
        for k in ('detached_gap', 'detached_share', 'detached_piece_min', 'detached_samples', 'detached_bridge_min', 'detached_nodes'):
            self.assertIn(k, R)
        self.assertEqual((R['detached_gap'], R['detached_share'], R['detached_piece_min']), (0.01, 0.03, 0.01))       # пороги НЕ подняты (директор)

    def test_base_disk_touching_stem_is_not_floating_negative_control(self):
        m = disk_table(0.0)
        self.assertTrue(old_bbox_rule(m, R), 'контроль: прежнее правило флагало бы диск основания — тест должен это различать')
        c = FC.detached(m, R)
        self.assertFalse(c['flag'], c)
        self.assertEqual(c['value'], 0.0, c)

    def test_base_with_gap_over_one_percent_is_floating_positive(self):
        c = FC.detached(disk_table(0.03), R)                                       # 3 / 174 = 1,7 % диагонали
        self.assertTrue(c['flag'], c)
        self.assertGreater(c['value'], R['detached_share'], c)
        self.assertIn('парящих', c['note'])

    def test_gap_under_one_percent_counts_as_touching(self):
        self.assertFalse(FC.detached(disk_table(0.008), R)['flag'])                # 0,46 % диагонали — касание

    def test_pair_touching_each_other_but_not_main_is_floating(self):
        body = box((1, 0.4, 0.4), (0, 0.5, 0))
        a, b = box((0.3, 0.3, 0.3), (3.0, 3.0, 3.0)), box((0.3, 0.3, 0.3), (3.3, 3.0, 3.0))
        c = FC.detached(trimesh.util.concatenate([body, a, b]), R)
        self.assertTrue(c['flag'], c)
        self.assertIn('парящих (без касания с главным, зазор > 1 % габарита) 2', c['note'])

    def test_chain_through_two_tiny_pieces_is_touching(self):
        """Codex 27.11: мелкие куски сами не опрашивались — цепочка main → пылинка → пылинка → крупный кусок не находилась (ложный блок). Теперь опрашиваются куски от detached_bridge_min."""
        body = box((1, 0.4, 0.4), (0, 0.5, 0))
        t1, t2 = box((0.03, 0.03, 0.03), (0.515, 0.5, 0)), box((0.03, 0.03, 0.03), (0.545, 0.5, 0))
        far = box((0.3, 0.3, 0.3), (0.71, 0.5, 0))
        m = trimesh.util.concatenate([body, t1, t2, far])
        self.assertFalse(FC.detached(m, R)['flag'], FC.detached(m, R))
        self.assertTrue(FC.detached(trimesh.util.concatenate([body, t1, far]), R)['flag'])       # звено выбито — между t1 и far зазор: парит

    def test_chain_through_tiny_piece_is_touching(self):
        body = box((1, 0.4, 0.4), (0, 0.5, 0))
        tiny = box((0.02, 0.02, 0.02), (0.51, 0.5, 0))                              # мостик ниже detached_piece_min: в долю не идёт, но касается обоих
        far = box((0.3, 0.3, 0.3), (0.67, 0.5, 0))
        self.assertFalse(FC.detached(trimesh.util.concatenate([body, tiny, far]), R)['flag'])
        self.assertTrue(FC.detached(trimesh.util.concatenate([body, far]), R)['flag'])       # без мостика зазор 2 % диагонали — парит

    def test_legs_touching_body_still_fine_and_dust_ignored(self):
        body = box((1, 0.4, 0.4), (0, 0.5, 0))
        leg = box((0.05, 0.3, 0.05), (0.4, 0.15, 0))
        dust = box((0.02, 0.02, 0.02), (3.0, 3.0, 3.0))
        self.assertFalse(FC.detached(trimesh.util.concatenate([body, leg, dust]), R)['flag'])

    def test_single_piece_is_clean(self):
        self.assertEqual(FC.detached(box(), R)['value'], 0.0)

    def test_deterministic(self):
        m = disk_table(0.03)
        self.assertEqual(FC.detached(m, R), FC.detached(m, R))


class CheckFailsLoudly(unittest.TestCase):
    """«Проверка сломана/не запустилась → говорит об этом» (урок дня 27.11): запись check_failed с причиной, статус needs_review (не shape_reject), main() → код 3 и строка с причиной."""

    def setUp(self):
        self.d = tempfile.mkdtemp(prefix='tests_fc_fail_')
        box().export(os.path.join(self.d, 's1-hd.glb'))
        a = np.zeros((100, 200, 4), np.uint8)
        a[:, :, 3] = 255
        Image.fromarray(a).save(os.path.join(self.d, 's1.hd.rgba.png'))

    def test_detached_crash_is_reported_not_swallowed(self):
        from unittest import mock
        with mock.patch.object(FC, 'detached', side_effect=RuntimeError('нет scipy')):
            rec = FC.run_sku('s1', os.path.join(self.d, 's1-hd.glb'), None, None, RULES)
        c = by(rec['checks'], FC.FAILED)
        self.assertTrue(c['flag'])
        self.assertIn('ПРОВЕРКА НЕ ВЫПОЛНЕНА: detached: RuntimeError: нет scipy', c['note'])
        self.assertEqual(rec['status'], 'needs_review')                                  # сломанный код не бракует форму
        self.assertEqual(FC.failed_skus([rec]), ['s1'])

    def test_holes_crash_is_reported(self):
        from unittest import mock
        with mock.patch.object(FC, 'sil_checks', side_effect=ValueError('пустая маска')):
            rec = FC.run_sku('s1', os.path.join(self.d, 's1-hd.glb'), os.path.join(self.d, 's1.hd.rgba.png'), None, RULES)
        self.assertIn('ПРОВЕРКА НЕ ВЫПОЛНЕНА: holes: ValueError: пустая маска', by(rec['checks'], FC.FAILED)['note'])
        self.assertNotIn('holes', [c['name'] for c in rec['checks']])                    # молчаливого «holes ок» нет

    def test_photo_prep_crash_is_reported(self):
        """Codex 27.11: photo_mask/surface_points/best_front были вне защиты — исключение валило весь запуск без записи. Теперь — check_failed с причиной."""
        from unittest import mock
        glb, ph = os.path.join(self.d, 's1-hd.glb'), os.path.join(self.d, 's1.hd.rgba.png')
        for name, exc in (('photo_mask', OSError('битый PNG')), ('surface_points', MemoryError('нет памяти')), ('best_front', ValueError('пустая маска'))):
            with mock.patch.object(FC, name, side_effect=exc):
                rec = FC.run_sku('s1', glb, ph, None, RULES)
            c = by(rec['checks'], FC.FAILED)
            self.assertIn('ПРОВЕРКА НЕ ВЫПОЛНЕНА: силуэты по фото: подготовка', c['note'], name)
            self.assertIn(type(exc).__name__, c['note'], name)
            self.assertEqual(rec['status'], 'needs_review', name)

    def test_corrupt_photo_file_is_reported_not_crash(self):
        bad = os.path.join(self.d, 'bad.png')
        open(bad, 'wb').write(b'not a png')
        rec = FC.run_sku('s1', os.path.join(self.d, 's1-hd.glb'), bad, None, RULES)
        self.assertIn('ПРОВЕРКА НЕ ВЫПОЛНЕНА', by(rec['checks'], FC.FAILED)['note'])
        self.assertEqual(FC.failed_skus([rec]), ['s1'])

    def test_main_returns_3_with_reason_and_0_when_healthy(self):
        import contextlib
        import io
        from unittest import mock
        argv = ['form_checks.py', '--glbs', self.d, '--photos', self.d, '--skus', 's1', '--out', os.path.join(self.d, 'out')]
        buf = io.StringIO()
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(FC, 'detached', side_effect=RuntimeError('сломано')), contextlib.redirect_stdout(buf):
            rc = FC.main()
        self.assertEqual(rc, 3)
        self.assertIn('ПРОВЕРКА НЕ ВЫПОЛНЕНА у 1 из 1: s1', buf.getvalue())
        with mock.patch.object(sys, 'argv', argv), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(FC.main(), 0)


if __name__ == '__main__':
    unittest.main(verbosity=1)

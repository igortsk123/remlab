"""Тесты этапа 6 (tex_visible): синтетическая коробка; «камера этапа 4» — растр лицевой грани (id, UV, cos, маска) и фото красно-синее. Бесплатно, секунды."""
import json
import os
import sys
import tempfile
import unittest

import numpy as np
from scipy.ndimage import binary_erosion, distance_transform_edt
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]
import tex_visible as TV  # noqa: E402

PX = 200
Q0, Q1 = 40, 160       # лицевой квадрат в кадре, пиксели


def box_geom(w=1.0, h=1.0, d=0.6, T=256):
    """Коробка (6 граней по 2 треугольника; перед — первый, грани 0 и 1); развёртка — сетка 3×2 ячеек, перед — ячейка 0 (внизу слева)."""
    x, y, z = w / 2, h / 2, d / 2
    quads = [
        [(-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)],
        [(x, -y, -z), (-x, -y, -z), (-x, y, -z), (x, y, -z)],
        [(x, -y, z), (x, -y, -z), (x, y, -z), (x, y, z)],
        [(-x, -y, -z), (-x, -y, z), (-x, y, z), (-x, y, -z)],
        [(-x, y, z), (x, y, z), (x, y, -z), (-x, y, -z)],
        [(-x, -y, -z), (x, -y, -z), (x, -y, z), (-x, -y, z)],
    ]
    V, F, UV = [], [], []
    for cell, pts in enumerate(quads):
        i0 = len(V)
        cx, cy = cell % 3, cell // 3
        for k, p in enumerate(pts):
            V.append(p)
            u0, v0 = [(0, 0), (1, 0), (1, 1), (0, 1)][k]
            UV.append(((cx + 0.05 + 0.9 * u0) / 3.0, (cy + 0.05 + 0.9 * v0) / 2.0))
        F += [[i0, i0 + 1, i0 + 2], [i0, i0 + 2, i0 + 3]]
    return [{'name': 'box', 'V': np.array(V, float), 'F': np.array(F), 'UV': np.array(UV), 'tex': np.full((T, T, 3), 128, np.uint8)}]


def fake_stage(cos_front=1.0, cos_band=None):
    """Растр «камеры»: лицевая грань видна фронтально в квадрате Q0..Q1; cos_band=(x0, x1, cos) — полоса пониженного cos (вскользь)."""
    ids = np.full((PX, PX), -1, np.int32)
    uv = np.zeros((PX, PX, 2), np.float32)
    cos = np.zeros((PX, PX), np.float32)
    ys, xs = np.mgrid[Q0:Q1, Q0:Q1]
    fx = (xs + 0.5 - Q0) / (Q1 - Q0)
    fy = 1.0 - (ys + 0.5 - Q0) / (Q1 - Q0)
    ids[Q0:Q1, Q0:Q1] = np.where(fx >= fy, 0, 1)
    u = (0.05 + 0.9 * fx) / 3.0
    v = (0.05 + 0.9 * fy) / 2.0
    uv[Q0:Q1, Q0:Q1, 0] = u
    uv[Q0:Q1, Q0:Q1, 1] = 1.0 - v
    cos[Q0:Q1, Q0:Q1] = cos_front
    if cos_band:
        cos[Q0:Q1, cos_band[0]:cos_band[1]] = cos_band[2]
    mask = ids >= 0
    depth = np.where(mask, 3.0, 0.0).astype(np.float32)                 # лицевая плоскость на глубине 3 (единицы куба)
    return {'ids': ids, 'uv': uv, 'depth': depth, 'px_len': 0.01, 'cos': cos, 'mask': mask, 'px': PX, 'P': np.eye(3), 'camera': {'kind': 'test'}, 'iou_frame': 1.0}


def photo_red_blue():
    a = np.zeros((PX, PX, 4), np.uint8)
    a[Q0:Q1, Q0:Q1, 3] = 255
    a[Q0:Q1, Q0:(Q0 + Q1) // 2, :3] = (220, 30, 30)
    a[Q0:Q1, (Q0 + Q1) // 2:Q1, :3] = (30, 30, 220)
    return a


class TestTexVisible(unittest.TestCase):
    def setUp(self):
        self.geoms = box_geom()

    def _transfer(self, st):
        prgb, pm = TV.photo_to_frame(photo_red_blue(), st['P'], PX)
        return TV.transfer(self.geoms, st, prgb, pm), prgb, pm

    def test_photo_to_frame_identity_keeps_mask(self):
        prgb, pm = TV.photo_to_frame(photo_red_blue(), np.eye(3), PX)
        self.assertEqual(int(pm.sum()), (Q1 - Q0) ** 2)
        self.assertTrue((np.abs(prgb[100, 50].astype(int) - [220, 30, 30]) <= 2).all())
        self.assertTrue((np.abs(prgb[100, 150].astype(int) - [30, 30, 220]) <= 2).all())

    def test_transfer_front_photo_colours_rest_untouched(self):
        tr, _p, _m = self._transfer(fake_stage())
        tex, known = tr['tex'][0], tr['known'][0]
        T = tex.shape[0]
        fr = (slice(T // 2, T), slice(0, T // 3))                # ячейка 0: нижний ряд текстуры (v вверх), левая треть
        kf = known[fr]
        self.assertGreater(kf.mean(), 0.5)
        cell = tex[fr]
        w3 = T // 3                                              # ячейка шириной T/3, содержимое — со столбца 0,05·w3 по 0,95·w3: левая половина — красная
        left = cell[:, int(w3 * 0.15):int(w3 * 0.40)][kf[:, int(w3 * 0.15):int(w3 * 0.40)]]       # середина половин (без каймы силуэта и стыка цветов)
        right = cell[:, int(w3 * 0.60):int(w3 * 0.85)][kf[:, int(w3 * 0.60):int(w3 * 0.85)]]
        self.assertGreater(len(left), 100)
        self.assertTrue((np.abs(left.mean(0) - [220, 30, 30]) < 30).all())
        self.assertTrue((np.abs(right.mean(0) - [30, 30, 220]) < 30).all())
        rest = known.copy()
        rest[fr] = False
        self.assertEqual(int(rest.sum()), 0)                    # ничего вне лицевой ячейки не «известно»
        back = tex[T // 2:, T // 3: 2 * T // 3]
        self.assertTrue((np.abs(back.reshape(-1, 3).astype(int) - 128) <= 1).mean() > 0.95)    # зад — серая заготовка

    def _top_tone(self, top_rgb, cos=0.2, tone=True):
        """Лицо — красное, фронтально; над ним полоса кадра (строки 20..Q0) — верхняя грань коробки (ячейка 4, грани 8/9) под острым углом cos, фото в ней — top_rgb.
        Возвращает (tr, маска ячейки верха в текстуре: строки 0..T/2, столбцы T/3..2T/3)."""
        st = fake_stage()
        R0 = 20
        ys, xs = np.mgrid[R0:Q0, Q0:Q1]
        fx = (xs + 0.5 - Q0) / (Q1 - Q0)
        fy = 1.0 - (ys + 0.5 - R0) / (Q0 - R0)
        st['ids'][R0:Q0, Q0:Q1] = np.where(fx >= fy, 8, 9)
        st['uv'][R0:Q0, Q0:Q1, 0] = (1 + 0.05 + 0.9 * fx) / 3.0
        st['uv'][R0:Q0, Q0:Q1, 1] = 1.0 - (1 + 0.05 + 0.9 * fy) / 2.0
        st['cos'][R0:Q0, Q0:Q1] = cos
        st['mask'] = st['ids'] >= 0
        st['depth'] = np.where(st['mask'], 3.0, 0.0).astype(np.float32)
        ph = np.zeros((PX, PX, 4), np.uint8)
        ph[Q0:Q1, Q0:Q1] = (220, 30, 30, 255)
        ph[R0:Q0, Q0:Q1] = (*top_rgb, 255)
        prgb, pm = TV.photo_to_frame(ph, st['P'], PX)
        tr = TV.transfer(self.geoms, st, prgb, pm, tone=tone)
        T = tr['tex'][0].shape[0]
        cell = np.zeros((T, T), bool)
        cell[: T // 2, T // 3: 2 * T // 3] = True
        return tr, cell

    def test_oblique_band_gets_tone_with_provenance_not_photo_texture(self):
        tr, cell = self._top_tone((130, 20, 20))                                    # верх виден вскользь и темнее (130,20,20) при красной опоре лица (220,30,30)
        pv, tex = tr['prov'][0], tr['tex'][0]
        self.assertGreater(int(((pv == TV.PROV['synth']) & cell).sum()), 2500)       # верх закрашен тоном (ячейка ~76×76 текселей), провенанс synth
        self.assertEqual(int((tr['known_photo'][0] & cell).sum()), 0)               # с фото на верхе ничего не взято (острый угол)
        self.assertTrue(tr['known'][0][pv == TV.PROV['synth']].all())               # но known включает тон (этап 7 не перекрашивает)
        col = tex[cell & (pv == TV.PROV['synth'])].astype(float).mean(0)
        self.assertTrue(120 < col[0] < 220)                                         # не копия опоры (220): тон взят с наблюдения
        self.assertTrue(abs(col[0] - 130) < abs(col[0] - 220))                      # у самой наблюдавшейся грани доверие 1,0 (tone_near_frac): цвет ≈ наблюдение, не светлее фото
        st0 = tr['stats'][0]
        self.assertEqual(st0['known'], int(tr['known_photo'][0].sum()))             # known_share считается без synth
        self.assertGreater(st0['known_synth'], 0)
        self.assertEqual(st0['known_synth'], int((pv == TV.PROV['synth']).sum()))

    def test_tone_off_is_old_behaviour(self):
        tr, cell = self._top_tone((130, 20, 20), tone=False)
        self.assertEqual(int((tr['known'][0] & cell).sum()), 0)
        self.assertEqual(int((tr['prov'][0] == TV.PROV['synth']).sum()), 0)
        self.assertEqual(tr['stats'][0]['known_synth'], 0)

    def test_tone_not_painted_where_observation_is_other_material(self):
        tr, cell = self._top_tone((20, 200, 20))                                    # зелёное при красной опоре: ΔE00 > tone_max_de — другой материал, оставить неизвестным
        self.assertEqual(int((tr['prov'][0][cell] == TV.PROV['synth']).sum()), 0)
        self.assertGreater(tr['stats'][0]['tone_dropped_de'], 0)

    def test_tone_spreads_over_surface_but_not_beyond_reach(self):
        tr, cell = self._top_tone((130, 20, 20))
        T = tr['tex'][0].shape[0]
        pv = tr['prov'][0]
        bottom = np.zeros((T, T), bool)
        bottom[: T // 2, 2 * T // 3:] = True                                        # нижняя грань (ячейка 5): через всю коробку от наблюдавшегося верха, дальше tone_reach_frac·габарит
        back = np.zeros((T, T), bool)
        back[T // 2:, T // 3: 2 * T // 3] = True                                    # задняя грань (ячейка 1)
        self.assertEqual(int(((pv == TV.PROV['synth']) & bottom).sum()), 0)
        self.assertEqual(int(((pv == TV.PROV['synth']) & back).sum()), 0)
        self.assertGreater(int(((pv == TV.PROV['synth']) & cell).sum()), 0)

    def test_tone_below_min_cos_is_not_observed(self):
        tr, cell = self._top_tone((130, 20, 20), cos=0.03)                          # луч почти вдоль поверхности (cos < tone_cos_min) — наблюдение ничего не стоит
        self.assertEqual(int((tr['prov'][0] == TV.PROV['synth']).sum()), 0)

    def test_grazing_band_not_taken(self):
        tr, _p, _m = self._transfer(fake_stage(cos_band=(80, 100, 0.1)))     # полоса вскользь (cos<0,34) — текстура с фото не берётся (тон — отдельно, known_photo)
        T = tr['tex'][0].shape[0]
        k = tr['known_photo'][0][T // 2:, : T // 3]
        cols = np.arange(T // 3)
        band = (cols > T // 3 * (80 - Q0) / (Q1 - Q0) * 0.95 + 8) & (cols < T // 3 * (100 - Q0) / (Q1 - Q0) * 0.95 - 8)
        self.assertEqual(int(k[:, band].sum()), 0)

    def test_wrong_shape_for_camera_is_refused(self):
        st = fake_stage()
        st['ids'][50, 50] = 9999
        with self.assertRaises(ValueError):
            self._transfer(st)

    def test_gate_and_check_json(self):
        m = {'silhouette_iou': 0.93, 'known_visible_share': 0.8, 'edge_corr': 0.97, 'lab_dE': 1.2}
        mm, why = TV.gate(m)
        self.assertEqual(why, [])
        mm, why = TV.gate({**m, 'silhouette_iou': 0.5, 'edge_corr': 0.1})
        self.assertEqual(len(why), 2)
        mm, why = TV.gate({**m, 'silhouette_iou': 0.758}, thin_pass=True)
        self.assertTrue(not why and mm['silhouette_iou'].get('thin_not_a_measure'), f'тонкий предмет (камера по контуру): IoU площади 0,758 не отказ ({why})')
        mm, why = TV.gate({**m, 'silhouette_iou': 0.758})
        self.assertTrue(any('silhouette_iou' in w for w in why), 'без тонкого IoU 0,758 — отказ как прежде')
        mm, why = TV.gate({'silhouette_iou': 0.9})                 # нет измерений ≠ «ок»
        self.assertTrue(any('known_visible_share' in w for w in why))

    def test_gate_reads_visible_share_not_texel_share(self):
        """T-215: порог — по доле истинно видимого (known_visible_share); прежняя known_share (доля всех текселей) гейта не решает ни в плюс, ни в минус."""
        m = {'silhouette_iou': 0.93, 'known_visible_share': 0.8, 'edge_corr': 0.97, 'lab_dE': 1.2}
        self.assertNotIn('known_share', TV.GATE)
        mm, why = TV.gate({**m, 'known_share': 0.03})              # мало текселей всей развёртки (зад, невидимое), но видимое покрыто → проход
        self.assertEqual(why, [], f'малая доля текселей при покрытом видимом не должна валить гейт ({why})')
        thr = TV.GATE['known_visible_share'][0]
        mm, why = TV.gate({**m, 'known_visible_share': thr / 2, 'known_share': 0.9})   # видимое не покрыто — отказ, как бы ни было с текселями
        self.assertEqual(len(why), 1)
        self.assertIn('known_visible_share', why[0])

    def test_gate_threshold_comes_from_rules(self):
        rules = json.load(open(os.path.join(TV.HERE, '..', '..', 'rules', 'tex-visible.json'), encoding='utf-8'))
        self.assertEqual(TV.GATE['known_visible_share'], (float(rules['gate']['known_visible_share'][0]), '>='))
        self.assertTrue(rules['_gate_doc'].strip(), 'у числа порога должна быть строка обоснования')

    def _write_pose_run(self, d, iou_claim=1.0):
        st = fake_stage()
        rd = os.path.join(d, 'pose', 'stages', 'render_view0')
        os.makedirs(rd)
        np.savez_compressed(os.path.join(rd, 'ids.npz'), ids=st['ids'])
        np.savez_compressed(os.path.join(rd, 'uv.npz'), uv=st['uv'], mask=st['mask'])
        np.savez_compressed(os.path.join(rd, 'depth.npz'), depth=st['depth'], px_len=np.float64(st['px_len']))
        Image.fromarray((st['cos'] * 65535).round().astype(np.uint16)).save(os.path.join(rd, 'aoi_cos16.png'))
        Image.fromarray(st['mask'].astype(np.uint8) * 255).save(os.path.join(rd, 'mask.png'))
        json.dump({'registration': {'P': list(np.eye(3).ravel()), 'iou': iou_claim}, 'camera': {'kind': 'test'}}, open(os.path.join(d, 'pose', 'stage_loss.json'), 'w', encoding='utf-8'))
        return os.path.join(d, 'pose')

    def test_full_stage_writes_outputs(self):
        import trimesh
        from trimesh.visual import TextureVisuals
        with tempfile.TemporaryDirectory() as d:
            g = self.geoms[0]
            m = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
            m.visual = TextureVisuals(uv=g['UV'])
            glb = os.path.join(d, 'shape.glb')
            m.export(glb)
            photo = os.path.join(d, 'p.png')
            Image.fromarray(photo_red_blue()).save(photo)
            pose = self._write_pose_run(d)
            r = TV.run(glb, photo, pose, os.path.join(d, 'run'), 'sku:1')
            sd = os.path.join(d, 'run', 'sku_1', '06-visible')
            for f in ('visible.glb', 'known.png', 'check.json', 'frame.png'):
                self.assertTrue(os.path.exists(os.path.join(sd, f)), f)
            with open(os.path.join(sd, 'check.json'), encoding='utf-8') as fh:
                ch = json.load(fh)
            self.assertEqual(ch['stage'], '06-visible')
            self.assertIn('needs_qwen', ch['extra'])
            self.assertEqual(ch['passed'], r['passed'])
            self.assertGreater(ch['metric']['value'], 0.85)
            self.assertGreater(r['metrics']['edge_corr'], 0.5)         # перенос не потерян при записи GLB (резкая синтетическая кромка + жёсткая эрозия 2 px по краю: мера на 200-пиксельном кадре низкая по построению)
            self.assertGreater(r['metrics']['known_share'], 0.15)
            self.assertGreater(r['metrics']['known_visible_share'], TV.GATE['known_visible_share'][0])   # мерка гейта (T-215) в check
            self.assertIn('known_visible_share', ch['metrics'])
            self.assertNotIn('known_share', ch['metrics'])                # прежняя — справочно, в extra_metrics
            self.assertIn('known_share', ch['extra']['extra_metrics'])
            self.assertLess(r['metrics']['lab_dE'], 1.0)
            self.assertIn('frayed_share', r['metrics'])                  # мерка рваности попадает в check
            self.assertIn('frayed_share', ch['extra']['extra_metrics'])

    def test_camera_failed_is_fail_closed(self):
        import trimesh
        from trimesh.visual import TextureVisuals
        with tempfile.TemporaryDirectory() as d:
            g = self.geoms[0]
            m = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
            m.visual = TextureVisuals(uv=g['UV'])
            glb = os.path.join(d, 'shape.glb')
            m.export(glb)
            ph = photo_red_blue()
            ph[Q0:Q1, Q0:Q0 + 60] = 0                                # фото уже формы на треть: IoU < 0,85
            photo = os.path.join(d, 'p.png')
            Image.fromarray(ph).save(photo)
            pose = self._write_pose_run(d, iou_claim=(Q1 - Q0 - 60) / (Q1 - Q0))
            r = TV.run(glb, photo, pose, os.path.join(d, 'run'), 'sku:2')
            self.assertFalse(r['passed'])
            sd = os.path.join(d, 'run', 'sku_2', '06-visible')
            self.assertFalse(os.path.exists(os.path.join(sd, 'visible.glb')))      # перенос не делался
            with open(os.path.join(sd, 'check.json'), encoding='utf-8') as fh:
                self.assertTrue(json.load(fh)['extra']['camera_failed'])

    def test_body_cut_carries_form_defect(self):
        """T-20261124-02: камера не прошла гейт только по низу (ножки формы ≠ фото), верх лёг → body_cut годен и несёт флаг брака формы; не только по низу или верх не лёг → None."""
        with tempfile.TemporaryDirectory() as td:
            def cam(name, extra, metrics):
                d = os.path.join(td, name, '04-camera')
                os.makedirs(d)
                json.dump({'passed': False, 'metrics': metrics, 'extra': extra}, open(os.path.join(d, 'check.json'), 'w'))
                json.dump({'frame_px': 400}, open(os.path.join(td, name, 'stage_loss.json'), 'w'))
                return os.path.join(td, name)
            bad_bottom = {'miss_bottom': {'ok': False}, 'extra_bottom': {'ok': True}, 'iou': {'ok': True}}
            ex = {'bottom_shape_mismatch': True, 'strip_rows': [300, 351], 'iou_top': 0.96, 'bottom_top_iou_min': 0.85}
            bc = TV.body_cut(cam('ok', ex, bad_bottom))
            self.assertIsNotNone(bc)
            self.assertTrue(bc['bottom_shape_mismatch'])
            self.assertEqual(bc['row'], 300)
            self.assertIsNone(TV.body_cut(cam('top', dict(ex, iou_top=0.5), bad_bottom)))
            self.assertIsNone(TV.body_cut(cam('body', ex, dict(bad_bottom, iou={'ok': False}))))
            self.assertIsNone(TV.body_cut(cam('noflag', dict(ex, bottom_shape_mismatch=False), bad_bottom)))

    def test_camera_gate_failed_refuses_even_if_silhouette_matches(self):
        import trimesh
        from trimesh.visual import TextureVisuals
        with tempfile.TemporaryDirectory() as d:
            g = self.geoms[0]
            m = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
            m.visual = TextureVisuals(uv=g['UV'])
            glb = os.path.join(d, 'shape.glb')
            m.export(glb)
            photo = os.path.join(d, 'p.png')
            Image.fromarray(photo_red_blue()).save(photo)
            pose = self._write_pose_run(d)
            os.makedirs(os.path.join(pose, '04-camera'), exist_ok=True)
            with open(os.path.join(pose, '04-camera', 'check.json'), 'w', encoding='utf-8') as fh:
                json.dump({'passed': False, 'metric': {'name': 'iou_silhouette', 'value': 0.669, 'threshold': 0.85, 'op': '>=', 'ok': False},
                           'metrics': {'miss': {'value': 0.18, 'threshold': 0.08, 'op': '<=', 'ok': False}}}, fh)
            r = TV.run(glb, photo, pose, os.path.join(d, 'run'), 'sku:4')
            self.assertFalse(r['passed'])
            self.assertEqual(r['reason'], 'camera_gate')
            sd = os.path.join(d, 'run', 'sku_4', '06-visible')
            self.assertFalse(os.path.exists(os.path.join(sd, 'visible.glb')))
            ch = json.load(open(os.path.join(sd, 'check.json'), encoding='utf-8'))
            self.assertIn('не прошла свой гейт', ch['reason'])
            self.assertIn('iou_silhouette 0.669', ch['reason'])
            # с passed=true — идёт как обычно
            with open(os.path.join(pose, '04-camera', 'check.json'), 'w', encoding='utf-8') as fh:
                json.dump({'passed': True}, fh)
            r2 = TV.run(glb, photo, pose, os.path.join(d, 'run'), 'sku:5')
            self.assertNotEqual(r2.get('reason'), 'camera_gate')

    def test_depth_jump_band_is_not_taken(self):
        st = fake_stage()
        mid = (Q0 + Q1) // 2
        st['depth'] = st['depth'].copy()
        st['depth'][:, mid:] += 50.0 * st['px_len']                  # ступенька глубины посередине (край складки)
        band = TV.depth_band(st)
        self.assertTrue(band[mid, mid - 1] and band[mid, mid])       # у разрыва — полоса
        self.assertFalse(band[mid, Q0 + 3])                          # далеко от него — нет
        self.assertTrue(TV.depth_band(fake_stage()).sum() == 0)      # ровная поверхность — полосы нет

    def test_edge_bg_fringe_rejects_background_coloured_edge_for_dark_and_cream_fabric(self):
        n = 200
        pm = np.zeros((n, n), bool); pm[20:180, 20:180] = True
        inner = np.zeros((n, n), bool); inner[24:176, 24:176] = True            # кайма 4 px у края фото
        for fabric in ((30, 60, 120), (214, 206, 192)):                           # тёмная ткань и кремовая (почти как фон)
            prgb = np.full((n, n, 3), 255, np.uint8)
            prgb[inner] = fabric
            st = {'mask': pm.copy(), 'cos': np.ones((n, n), np.float32)}
            fr = TV.edge_bg_fringe(st, prgb, pm)
            self.assertTrue(fr[pm & ~inner].all(), fabric)                         # белая кайма у края — отброшена
            self.assertFalse(fr[inner].any(), fabric)                              # сама ткань — нет, даже кремовая
        white = np.full((n, n, 3), 255, np.uint8); white[inner] = (246, 246, 244)       # белая ткань на белом фоне: «светлее фона» — сама ткань, правило не режет и мерка N/A
        self.assertFalse(TV.edge_bg_fringe({'mask': pm.copy(), 'cos': np.ones((n, n), np.float32)}, white, pm).any())

    def _two_material_photo(self, halo: bool):
        """Синтетика Марти-2: синяя обивка (большая) + светлое дерево (ножка 40 px) на белом фоне; halo — белый ореол 3 px у края ТКАНИ."""
        n = 300
        pm = np.zeros((n, n), bool)
        blue = np.zeros((n, n), bool); blue[20:120, 20:280] = True
        wood = np.zeros((n, n), bool); wood[130:280, 120:160] = True
        pm = blue | wood
        prgb = np.full((n, n, 3), 255, np.uint8)
        prgb[blue] = (30, 60, 120)
        prgb[wood] = (205, 160, 110)
        if halo:
            edge = blue & ~binary_erosion(blue, iterations=3)                     # 3 px по краю синего блока — белёсый ореол вырезки
            prgb[edge] = (250, 250, 250)
        return n, pm, blue, wood, prgb, {'mask': pm.copy(), 'cos': np.ones((n, n), np.float32)}

    def test_edge_bg_local_reference_two_materials_wood_is_not_background(self):
        """Дефект мерки (T-20261124-10/2): одна медиана ткани принимала светлое дерево рядом с синей обивкой за «фон вырезки»; опора — ближайшее ядро: дерево сравнивается с деревом."""
        n, pm, blue, wood, prgb, st = self._two_material_photo(halo=False)
        lab = TV._lab(prgb)
        near_wood = wood & (distance_transform_edt(pm) <= 6)
        old = TV.bg_like(lab, TV.core_median(st, prgb, pm)) & near_wood
        self.assertTrue(int(old.sum()) > 100)        # прежняя опора: дерево у края — «фон» (это и есть дефект)
        ref = TV.local_reference(st, prgb, pm)
        self.assertEqual(ref.shape, (n, n, 3))
        new = TV.bg_like(lab, ref) & near_wood
        self.assertEqual(int(new.sum()), 0)                                                  # локальная опора: ни одного пикселя дерева
        self.assertTrue(abs(float(ref[200, 140, 0]) - float(TV._lab(np.array([[[205, 160, 110]]], np.uint8))[0, 0, 0])) < 2.0)   # у ножки опора — цвет дерева
        self.assertTrue(abs(float(ref[60, 150, 0]) - float(TV._lab(np.array([[[30, 60, 120]]], np.uint8))[0, 0, 0])) < 2.0)      # у спинки — цвет обивки

    def test_edge_bg_local_fringe_keeps_wood_and_still_catches_halo_on_fabric(self):
        old_flag = TV.EDGE_BG_LOCAL
        try:
            n, pm, blue, wood, prgb, st = self._two_material_photo(halo=True)
            TV.EDGE_BG_LOCAL = False
            fr_old = TV.edge_bg_fringe(st, prgb, pm)
            TV.EDGE_BG_LOCAL = True
            fr_new = TV.edge_bg_fringe(st, prgb, pm)
            halo = blue & ~binary_erosion(blue, iterations=3)
            self.assertTrue(fr_old[wood].sum() > 100)                                         # прежнее правило режет дерево
            self.assertEqual(int(fr_new[wood].sum()), 0)                                      # новое — не режет
            self.assertTrue(fr_new[halo].mean() > 0.95)                                       # настоящий ореол на ткани ловится
            self.assertFalse(fr_new[blue & ~halo].any())                                      # сама обивка не режется
            TV.EDGE_BG_LOCAL = True
            for fabric in ((30, 60, 120), (214, 206, 192)):                                    # одноматериальный контроль (как у прежнего теста): кайма ловится, ткань нет
                m = np.zeros((200, 200), bool); m[20:180, 20:180] = True
                inner = np.zeros((200, 200), bool); inner[24:176, 24:176] = True
                p2 = np.full((200, 200, 3), 255, np.uint8); p2[inner] = fabric
                f2 = TV.edge_bg_fringe({'mask': m.copy(), 'cos': np.ones((200, 200), np.float32)}, p2, m)
                self.assertTrue(f2[m & ~inner].all(), fabric)
                self.assertFalse(f2[inner].any(), fabric)
        finally:
            TV.EDGE_BG_LOCAL = old_flag

    def test_frayed_share_counts_known_pixels_next_to_unknown_only(self):
        n = 100
        mask = np.zeros((n, n), bool); mask[10:90, 10:90] = True
        solid = mask.copy()                                                  # сплошное известное: рваности нет
        self.assertEqual(TV.frayed_share(solid, mask)['frayed_share'], 0.0)
        holey = mask.copy(); holey[48:52, 10:90] = False                     # щель в 4 px поперёк: известное в 3 px от неё — рваное
        r = TV.frayed_share(holey, mask)
        self.assertAlmostEqual(r['frayed_share'], 6 / 76, places=3)           # 3 известные строки с каждой стороны щели из 76
        self.assertEqual(TV.frayed_share(mask & False, mask), {})            # нечего мерить — мерки нет, не ноль

    def test_multi_material_is_decided_by_bimodal_lightness_not_by_product(self):
        rng = np.random.default_rng(0)
        two = np.concatenate([rng.normal(25, 4, 4000), rng.normal(80, 4, 4000)])       # дерево + светлая обивка в одной части
        one = rng.normal(60, 6, 8000)                                                    # одна ткань
        rare = np.concatenate([rng.normal(85, 4, 7600), rng.normal(30, 4, 400)])         # узор: тёмных пикселей мало
        tail = np.concatenate([rng.normal(88, 4, 5500), rng.uniform(40, 80, 2500)])      # одна ткань с длинным хвостом (дерево/узор/тени), без второго пика
        self.assertTrue(TV.multi_material(two))
        self.assertFalse(TV.multi_material(one))
        self.assertFalse(TV.multi_material(rare))
        self.assertFalse(TV.multi_material(tail))

    def test_import_error_writes_failed_check_instead_of_raising(self):
        with tempfile.TemporaryDirectory() as d:
            photo = os.path.join(d, 'p.png')
            Image.fromarray(photo_red_blue()).save(photo)
            r = TV.run(os.path.join(d, 'нет-такой-формы.glb'), photo, d, os.path.join(d, 'run'), 'sku:3')
            self.assertFalse(r['passed'])
            with open(os.path.join(d, 'run', 'sku_3', '06-visible', 'check.json'), encoding='utf-8') as fh:
                ch = json.load(fh)
            self.assertFalse(ch['passed'])
            self.assertIn('этап 6 не выполнен', ch['reason'])

    def test_missing_ids_asks_to_recompute_camera(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, 'stages', 'render_view0'))
            with self.assertRaises(FileNotFoundError) as cm:
                TV.load_stage(d)
            self.assertIn('ids.npz', str(cm.exception))

    def test_side_views_follow_camera_azimuth(self):
        """Ракурсы «слева/справа» — от азимута найденной камеры, не от осей формы (владелец TG 1586: Босс az 170,6° показывал спину)."""
        sv = TV.side_view_angles({'az': 170.6, 'el': -4.3})
        self.assertAlmostEqual(sv['az_cam'], 170.6, places=1)
        self.assertAlmostEqual(sv['left']['az'], 130.6, places=1)
        self.assertAlmostEqual(sv['right']['az'], 210.6, places=1)
        self.assertAlmostEqual(sv['right']['yaw'], -210.6, places=1)       # yaw рендера = −az (рендер вращает предмет)
        self.assertAlmostEqual(sv['pitch'], -4.3, places=1)                 # высота камеры та же
        w = TV.side_view_angles({'az': 350.0, 'el': 5.0})                   # 350° = −10°: нормировка в (−180, 180]
        self.assertAlmostEqual(w['az_cam'], -10.0, places=1)
        self.assertAlmostEqual(w['left']['az'], -50.0, places=1)
        self.assertAlmostEqual(w['right']['az'], 30.0, places=1)
        z = TV.side_view_angles({'az': 0.0, 'el': 10.0})                    # фронтальная камера = прежние ±40° и 10°
        self.assertEqual((z['left']['yaw'], z['right']['yaw'], z['pitch']), (40.0, -40.0, 10.0))
        n = TV.side_view_angles(None)                                       # камеры нет — как раньше
        self.assertEqual((n['az_cam'], n['pitch']), (0.0, 10.0))


    def _grating_contrast(self, photo_period, scale=1.0, amp=60.0):
        """Фото — решётка известной частоты (период photo_period px фото), камера смотрит на лицевую грань; возвращает σ(текстуры)/σ(истины) на взятых текселях ячейки."""
        n = int(PX * scale)
        xs = np.arange(n)[None, :].repeat(n, 0)
        g = 128.0 + amp * np.sin(2 * np.pi * (xs + 0.5) / photo_period)
        ph = np.zeros((n, n, 4), np.uint8)
        a0, a1 = int(Q0 * scale), int(Q1 * scale)
        ph[a0:a1, a0:a1, :3] = np.clip(g[a0:a1, a0:a1, None], 0, 255).astype(np.uint8)
        ph[a0:a1, a0:a1, 3] = 255
        st = fake_stage()
        P = np.diag([scale, scale, 1.0])                                   # кадр → фото (фото мельче кадра в 1/scale раз)
        prgb, pm = TV.photo_to_frame(ph, P, PX)
        tr = TV.transfer(self.geoms, st, prgb, pm)
        tex, known = tr['tex'][0], tr['known'][0]
        T = tex.shape[0]
        w3 = T // 3
        fr = (slice(T // 2 + 8, T - 8), slice(int(w3 * 0.20), int(w3 * 0.80)))   # ячейка 0 без каймы у шва/силуэта
        k = known[fr]
        self.assertGreater(k.mean(), 0.9)
        v = tex[fr][..., 1][k].astype(np.float64)
        return float(v.std() / (amp / np.sqrt(2.0)))

    def test_fine_contrast_survives_photo_transfer(self):
        """Мелкий контраст (T-197): решётка периодом 4 px фото (вдвое длиннее периода Найквиста), фото вдвое мельче кадра — текстура несёт ≥90 % контраста истины; прежний путь (линейный перевод и выборка) давал ~82 %."""
        keep = (TV.PHOTO_INTERP, TV.SAMPLE_ORDER)
        try:
            new = self._grating_contrast(4.0, scale=0.5)
            eq = self._grating_contrast(4.0, scale=1.0)
            TV.PHOTO_INTERP, TV.SAMPLE_ORDER = 'linear', 1
            old = self._grating_contrast(4.0, scale=0.5)
        finally:
            TV.PHOTO_INTERP, TV.SAMPLE_ORDER = keep
        self.assertGreaterEqual(new, 0.90, f'фото вдвое мельче кадра: {new:.3f}')
        self.assertGreaterEqual(eq, 0.90, f'фото = кадр: {eq:.3f}')
        self.assertLess(old, new - 0.03, f'контроль: линейная {old:.3f} должна быть хуже бикубики {new:.3f}')

    def test_hatch_is_soft_veil_not_stripes(self):
        """Лист 06: непросмотренное — цвет заготовки с лёгкой светлой вуалью (без штриховки: она читалась как «трещины»), просмотренное не тронуто; подпись не роняет."""
        tex = np.zeros((32, 32, 3), np.uint8)
        tex[:] = (20, 50, 90)
        known = np.zeros((32, 32), bool)
        known[:, :16] = True
        out = TV.hatch(tex, known)
        self.assertTrue((out[:, :16] == tex[:, :16]).all(), 'просмотренное изменено')
        miss = out[:, 16:].reshape(-1, 3).astype(int)
        self.assertEqual(len(np.unique(miss, axis=0)), 1, 'вуаль должна быть однородной, без штриховки')
        self.assertTrue((miss[0] > np.array([20, 50, 90])).all(), 'вуаль светлее заготовки')
        self.assertLess(int(np.abs(miss[0] - np.array([20, 50, 90])).max()), 120, 'остаётся цвет заготовки, не белое')
        self.assertEqual(TV.caption(np.full((120, 160, 3), 255, np.uint8), 'тест').shape, (120, 160, 3))

    def _stage_on_cell(self, cell, cos=1.0):
        """Растр, где в квадрате лицевой области «видна» грань ячейки cell (0 — перёд; 1 — задняя стенка: ошибка рисования без z-буфера у двойной стенки)."""
        st = fake_stage(cos_front=cos)
        ys, xs = np.mgrid[Q0:Q1, Q0:Q1]
        fx = (xs + 0.5 - Q0) / (Q1 - Q0)
        fy = 1.0 - (ys + 0.5 - Q0) / (Q1 - Q0)
        cx, cy = cell % 3, cell // 3
        st['ids'][Q0:Q1, Q0:Q1] = np.where(fx >= fy, 2 * cell, 2 * cell + 1)
        st['uv'][Q0:Q1, Q0:Q1, 0] = (cx + 0.05 + 0.9 * fx) / 3.0
        st['uv'][Q0:Q1, Q0:Q1, 1] = 1.0 - (cy + 0.05 + 0.9 * fy) / 2.0
        return st

    def test_back_facing_face_is_not_a_photo_source(self):
        """Двойная стенка: растр показывает ЗАДНЮЮ грань (нормаль от камеры) на месте лицевой — с неё ничего не берётся (знаковая нормаль), контроль — лицевая берётся."""
        pr, pm = TV.photo_to_frame(photo_red_blue(), np.eye(3), PX)
        T = self.geoms[0]['tex'].shape[0]
        cell = lambda c: (slice((1 - c // 3) * T // 2, (2 - c // 3) * T // 2), slice((c % 3) * T // 3, (c % 3 + 1) * T // 3))      # строка текстуры = 1 − v
        ok = TV.transfer(self.geoms, self._stage_on_cell(0), pr, pm)
        self.assertGreater(int(ok['known'][0][cell(0)].sum()), 2000)
        bad = TV.transfer(self.geoms, self._stage_on_cell(1), pr, pm)
        self.assertEqual(int(bad['known'][0][cell(1)].sum()), 0, 'с задней грани взято фото')
        self.assertGreater(bad['stats'][0]['back_faces_visible'], 0)
        keep = TV.BACK_ON
        try:
            TV.BACK_ON = False
            old = TV.transfer(self.geoms, self._stage_on_cell(1), pr, pm)
        finally:
            TV.BACK_ON = keep
        self.assertGreater(int(old['known'][0][cell(1)].sum()), 2000, 'контроль: без правила задняя грань берётся (это и был дефект)')

    def test_big_panel_with_few_known_texels_loses_them(self):
        """Страховка: крупная панель (верх коробки), где с фото известна горстка текселей (< 5 %), теряет их; контроль — без правила остаются."""
        st = fake_stage()
        ys, xs = np.mgrid[Q0:Q0 + 6, Q0:Q0 + 6]
        st['ids'][:] = -1
        st['mask'][:] = False
        st['ids'][ys, xs] = 8                                                       # верх коробки: клочок 6×6 пикселей, фронтально (cos 1)
        st['uv'][ys, xs, 0] = (1 + 0.5) / 3.0
        st['uv'][ys, xs, 1] = 1.0 - (1 + 0.5) / 2.0
        st['cos'][:] = 0.0
        st['cos'][ys, xs] = 1.0
        st['mask'] = st['ids'] >= 0
        st['depth'] = np.where(st['mask'], 3.0, 0.0).astype(np.float32)
        pr, pm = TV.photo_to_frame(photo_red_blue(), np.eye(3), PX)
        keep = (TV.BACK_ON, TV.PRUNE_ON)
        try:
            TV.BACK_ON, TV.PRUNE_ON = False, True
            raw = TV.transfer(self.geoms, st, pr, pm, tone=False)
            TV.BACK_ON = True
            fixed = TV.transfer(self.geoms, st, pr, pm, tone=False)
            TV.PRUNE_ON = False                                                     # правило выключено — клочок остаётся (так и в rules/tex-visible.json по умолчанию, T-201)
            off = TV.transfer(self.geoms, st, pr, pm, tone=False)
        finally:
            TV.BACK_ON, TV.PRUNE_ON = keep
        self.assertGreater(int(raw['known'][0].sum()), 0, 'контроль: без правила клочок известен')
        self.assertEqual(int(fixed['known'][0].sum()), 0)
        self.assertGreater(fixed['stats'][0]['known_pruned_panels'], 0)
        self.assertEqual(int(off['known'][0].sum()), int(raw['known'][0].sum()))
        self.assertEqual(off['stats'][0]['known_pruned_panels'], 0)

    def test_panel_prune_is_off_in_rules(self):
        """Мерка T-201 (8 товаров): страховка панелей снимает настоящее фото с крупных панелей (фасад −2…−3 % известного у двух товаров из восьми) и ничего не даёт сверх z-буфера и знаковой нормали — в правилах выключена."""
        self.assertFalse(bool(TV._rules()['back_prune_panels']))

    def _shifted_square_alpha(self, dx, dy, ss=8):
        """Фото-вырезка: квадрат Q0..Q1, сдвинутый на (dx, dy) px кадра, с антиалиасингом по площади (сэмплинг ss×ss)."""
        big = np.zeros((PX * ss, PX * ss), np.float32)
        r0, r1 = int(round((Q0 + dy) * ss)), int(round((Q1 + dy) * ss))
        c0, c1 = int(round((Q0 + dx) * ss)), int(round((Q1 + dx) * ss))
        big[r0:r1, c0:c1] = 1.0
        a = big.reshape(PX, ss, PX, ss).mean((1, 3))
        ph = np.zeros((PX, PX, 4), np.uint8)
        ph[..., :3] = 128
        ph[..., 3] = np.round(a * 255).astype(np.uint8)
        return ph

    def test_fit_registration_recovers_subpixel_shift(self):
        """Подгонка регистрации (T-197/2): сдвиг фото относительно камеры на доли пикселя находится с точностью ≤0,15 px; точная регистрация — нулевой сдвиг."""
        st = fake_stage()
        for dx, dy in ((0.0, 0.0), (0.6, -0.4), (-1.25, 0.75), (2.0, 1.5)):
            fr = TV.fit_registration(self._shifted_square_alpha(dx, dy), st['P'], st['mask'])
            self.assertLessEqual(abs(fr['dx'] + dx), 0.15, 'dx %.3f вместо %.3f' % (fr['dx'], -dx))          # сдвиг подгонки = поправка: обратен сдвигу фото
            self.assertLessEqual(abs(fr['dy'] + dy), 0.15, 'dy %.3f вместо %.3f' % (fr['dy'], -dy))
        fr0 = TV.fit_registration(self._shifted_square_alpha(0.0, 0.0), st['P'], st['mask'])
        self.assertLess(fr0['gain'], TV.REG_MIN_GAIN)                     # точная регистрация: подгонка не применяется
        fr1 = TV.fit_registration(self._shifted_square_alpha(1.5, 0.0), st['P'], st['mask'])
        self.assertGreaterEqual(fr1['gain'], TV.REG_MIN_GAIN)             # заметный сдвиг: применяется
        far = TV.fit_registration(self._shifted_square_alpha(5.0, 0.0), st['P'], st['mask'])
        self.assertLessEqual(abs(far['dx']), TV.REG_MAX_PX + 1e-6)         # больше потолка не берём

    def test_fit_registration_convention_of_pixel_centres(self):
        """Соглашение пикселя (T-197/3): фото = кадр, уменьшенный вдвое по центрам пикселей (PIL), P с поправкой 0,5·(s−1) — подгонка находит ≤0,03 px (в коде этапа сдвига нет);
        P «угловая» (как `pose_fit.canvas_P`, без поправки) даёт сдвиг (1−s)/(2s) = 0,5 px кадра — это известное соглашение, камеры подогнаны под него, менять нельзя."""
        st = fake_stage()
        s = 0.5
        big = Image.fromarray((st['mask'] * 255).astype(np.uint8))
        small = np.asarray(big.resize((int(PX * s), int(PX * s)), Image.LANCZOS))
        ph = np.zeros((small.shape[0], small.shape[1], 4), np.uint8)
        ph[..., 3] = small
        off = 0.5 * (s - 1.0)
        Pc = np.array([[s, 0, off], [0, s, off], [0, 0, 1.0]])
        fc = TV.fit_registration(ph, Pc, st['mask'])
        self.assertLessEqual(abs(fc['dx']), 0.03, fc)
        self.assertLessEqual(abs(fc['dy']), 0.03, fc)
        fk = TV.fit_registration(ph, np.diag([s, s, 1.0]), st['mask'])           # угловая P
        want = (1.0 - s) / (2.0 * s)
        self.assertLessEqual(abs(fk['dx'] - want), 0.08, fk)
        self.assertLessEqual(abs(fk['dy'] - want), 0.08, fk)

    def test_legs_cut_reads_04_flag_and_blocks_all_but_trusted_legs(self):
        """T-191/3: ножки не совпали → фото ниже корпуса не берём, кроме рамок прошедших сверку; пол сдвинут — ни одной; флага нет — None."""
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, '04-camera'))
            ck = os.path.join(d, '04-camera', 'check.json')
            json.dump({'passed': True, 'extra': {}}, open(ck, 'w', encoding='utf-8'))
            self.assertIsNone(TV.legs_cut(d))
            ex = {'legs_mismatch': True, 'legs_block': True, 'legs_cut_row': 100, 'legs_trusted_boxes': [[10, 110, 20, 150]], 'legs_match': {'floor_ok': True, 'why': 'ножек не годных 1 из 2'}}
            json.dump({'passed': True, 'extra': ex}, open(ck, 'w', encoding='utf-8'))
            json.dump({'frame_px': 200}, open(os.path.join(d, 'stage_loss.json'), 'w', encoding='utf-8'))
            ex0 = dict(ex, legs_block=False)
            json.dump({'passed': True, 'extra': ex0}, open(ck, 'w', encoding='utf-8'))
            self.assertIsNone(TV.legs_cut(d))                                    # observe: legs_mismatch есть, legs_block нет — 06 фото не блокирует
            json.dump({'passed': True, 'extra': ex}, open(ck, 'w', encoding='utf-8'))
            lc = TV.legs_cut(d)
            self.assertEqual((lc['row'], lc['frame_px'], lc['boxes']), (100, 200, [[10, 110, 20, 150]]))
            blk, r = TV.leg_block_mask((200, 200), lc['row'], lc['boxes'])
            self.assertEqual(r, 96)                                              # граница − 4 px запаса
            self.assertTrue(blk[96:, 50:].all() and not blk[:96].any())          # корпус выше границы не блокируется, ножки без пары — да
            self.assertFalse(blk[110:151, 10:21].any())                          # прошедшая сверку ножка — открыта
            blk2, _ = TV.leg_block_mask((100, 100), lc['row'], lc['boxes'], scale=0.5)
            self.assertFalse(blk2[55:75, 5:10].any() and blk2[:46].any())        # масштаб кадра: граница 100·0,5 − 4 = 46
            ex['legs_match']['floor_ok'] = False
            json.dump({'passed': True, 'extra': ex}, open(ck, 'w', encoding='utf-8'))
            self.assertEqual(TV.legs_cut(d)['boxes'], [])                        # пол сдвинут — доверенных ножек нет

    def test_legs_observe_default_is_bit_identical_to_no_legs_flags(self):
        """T-191/3: по умолчанию (legs_block нет, только запись legs_mismatch) этап 06 даёт тот же результат, что и без полей ножек в 04 — и обычный, и --body-only."""
        import trimesh
        from trimesh.visual import TextureVisuals
        with tempfile.TemporaryDirectory() as d:
            g = self.geoms[0]
            m = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
            m.visual = TextureVisuals(uv=g['UV'])
            glb = os.path.join(d, 'shape.glb')
            m.export(glb)
            photo = os.path.join(d, 'p.png')
            Image.fromarray(photo_red_blue()).save(photo)
            pose = self._write_pose_run(d)
            os.makedirs(os.path.join(pose, '04-camera'), exist_ok=True)
            ck = os.path.join(pose, '04-camera', 'check.json')
            obs = {'legs_mismatch': True, 'legs_cut_row': 20, 'legs_trusted_boxes': [], 'legs_match': {'floor_ok': False, 'why': 'тест'}}
            for bo in (False, True):
                outs = []
                for ex in ({}, obs):
                    json.dump({'passed': True, 'extra': ex}, open(ck, 'w', encoding='utf-8'))
                    run_dir = os.path.join(d, f'run_{int(bo)}_{len(ex)}')
                    TV.run(glb, photo, pose, run_dir, 'sku:1', body_only=bo)
                    sd = os.path.join(run_dir, 'sku_1', '06-visible')
                    gg = TV.load_shape(os.path.join(sd, 'visible.glb'))
                    ch = json.load(open(os.path.join(sd, 'check.json'), encoding='utf-8'))
                    outs.append(([np.asarray(x['tex']).tobytes() for x in gg], open(os.path.join(sd, 'known.png'), 'rb').read(), ch['extra'].get('legs_block')))
                self.assertEqual(outs[0][0], outs[1][0])                         # текстуры бит-в-бит
                self.assertEqual(outs[0][1], outs[1][1])                         # карта «взято с фото» бит-в-бит
                self.assertIsNone(outs[1][2])                                    # блокировки в отчёте нет

CAM = {'az': 0.0, 'el': 0.0, 'd': 3.0, 'f': 1.3, 'cx': 0.5, 'cy': 0.5}      # настоящая перспективная камера (az/el/d/f/cx/cy, как у этапа 4)


def _quad(p, uv0, uv1):
    """Четырёхугольник p[0..3] → два треугольника; UV — прямоугольник uv0..uv1 текстуры (грани 2k и 2k+1)."""
    (u0, v0), (u1, v1) = uv0, uv1
    return np.array(p, float), np.array([(u0, v0), (u1, v0), (u1, v1), (u0, v1)], float)


def z_scene(kind):
    """Геометрии для проверки z-буфера (одна геометрия, текстура 256²):
    'double' — большой наклонный треугольник A (грань 0, ближний край справа) и плоский квадрат B позади него (грани 1, 2, z = −0,1): средняя глубина B ближе средней глубины A — кадр «дальние первыми» рисует B ПОВЕРХ A.
    'closed' — две плоскости одного размера: перед (грани 0, 1, z = +0,1) закрывает зад (грани 2, 3, z = −0,1) целиком.
    'hole'   — то же, но у перед вырезана середина (грани 0–3 рамка), зад виден через окно."""
    V, F, UV = [], [], []

    def add_quad(p, uv0, uv1):
        i = len(V)
        q, uvs = _quad(p, uv0, uv1)
        V.extend(q.tolist())
        UV.extend(uvs.tolist())
        F.extend([[i, i + 1, i + 2], [i, i + 2, i + 3]])

    if kind == 'double':
        V.extend([(-0.5, -0.5, -0.5), (0.5, -0.5, 0.6), (0.0, 0.5, -0.5)])
        UV.extend([(0.05, 0.05), (0.45, 0.05), (0.25, 0.45)])
        F.append([0, 1, 2])
        add_quad([(0.1, -0.45, -0.1), (0.3, -0.45, -0.1), (0.3, -0.3, -0.1), (0.1, -0.3, -0.1)], (0.55, 0.05), (0.95, 0.45))
    elif kind == 'closed':
        add_quad([(-0.4, -0.4, 0.1), (0.4, -0.4, 0.1), (0.4, 0.4, 0.1), (-0.4, 0.4, 0.1)], (0.05, 0.05), (0.45, 0.45))
        add_quad([(-0.4, -0.4, -0.1), (0.4, -0.4, -0.1), (0.4, 0.4, -0.1), (-0.4, 0.4, -0.1)], (0.55, 0.05), (0.95, 0.45))
    elif kind == 'hole':
        for (x0, x1, y0, y1) in ((-0.4, 0.4, -0.4, -0.1), (-0.4, 0.4, 0.1, 0.4)):             # рамка: нижняя и верхняя полосы перед (окно −0,1…0,1 по высоте)
            add_quad([(x0, y0, 0.1), (x1, y0, 0.1), (x1, y1, 0.1), (x0, y1, 0.1)], (0.05, 0.05), (0.45, 0.45))
        add_quad([(-0.4, -0.4, -0.1), (0.4, -0.4, -0.1), (0.4, 0.4, -0.1), (-0.4, 0.4, -0.1)], (0.55, 0.05), (0.95, 0.45))
    return [{'name': 'z', 'V': np.array(V, float), 'F': np.array(F), 'UV': np.array(UV, float), 'tex': np.full((256, 256, 3), 128, np.uint8)}]


def z_stage(geoms, cam=CAM, n=PX):
    """Кадр камеры этапа 4 по форме: тем же `pose_fit.render_persp` («дальние первыми»), форма — в кубе `mv_geometry.to_cube`."""
    import mv_geometry as MG
    import pose_fit as PF
    P = MG.to_cube(geoms[0]['V'], 0.0)[0]
    r = PF.render_persp({'V': P, 'F': geoms[0]['F'], 'UV': geoms[0]['UV'], 'N': PF.smooth_normals(P, geoms[0]['F'])}, cam, n)
    return {'ids': r['ids'], 'uv': r['uv'], 'depth': r['depth'], 'px_len': r['px_len'], 'cos': r['cos'], 'mask': r['mask'], 'px': n, 'P': np.eye(3), 'camera': cam, 'iou_frame': 1.0}


def z_photo(n=PX):
    pm = np.zeros((n, n), bool)
    pm[6:n - 6, 6:n - 6] = True
    return np.where(pm[..., None], np.array([200, 40, 40], np.uint8), 0).astype(np.uint8), pm


def known_on(geoms, tr, faces):
    """Сколько текселей известно с фото на гранях `faces`."""
    import tex_coverage as TC
    g = geoms[0]
    T = g['tex'].shape[0]
    fid, _ = TC.raster(np.stack([g['UV'][:, 0] * T, (1.0 - g['UV'][:, 1]) * T], 1), g['F'], T)
    fid = fid.reshape(T, T)
    return int((tr['known_photo'][0] & np.isin(fid, list(faces))).sum())


class TestZBuffer(unittest.TestCase):
    """Z-буфер видимости (T-201): кадр этапа 4 без z-буфера рисует ближние позади дальних, если у ближней грани средняя глубина больше."""

    def setUp(self):
        self.keep = (TV.BACK_ON, TV.ZBUF_ON)
        TV.BACK_ON, TV.ZBUF_ON = False, True                       # правило «спиной к камере» выключено: проверяем именно z-буфер

    def tearDown(self):
        TV.BACK_ON, TV.ZBUF_ON = self.keep

    def _nearest(self, geoms, st):
        """Независимый z-буфер теста: id грани и глубина ближайшей в каждом пикселе."""
        import mv_geometry as MG
        import pose_fit as PF
        import tex_coverage as TC
        P = MG.to_cube(geoms[0]['V'], 0.0)[0]
        x, y, Z = PF.project(P, st['camera'])
        n = st['px']
        ids, zb = TC.raster(np.stack([x * n, y * n], 1), geoms[0]['F'], n, 1.0 / Z)
        return ids.reshape(n, n), np.where(np.isfinite(zb), 1.0 / np.maximum(zb, 1e-12), 0.0).reshape(n, n)

    def test_double_wall_painter_error_fixed(self):
        """Двойная стенка: кадр рисует заднюю грань B (1, 2) поверх лицевой A (0) → B берёт фото, A теряет его под B. С z-буфером: B не видна, фото — на A; допуск — из правил."""
        g = z_scene('double')
        st = z_stage(g)
        ids_n, z_n = self._nearest(g, st)
        wrong = np.isin(st['ids'], (1, 2)) & (ids_n == 0)
        self.assertGreater(int(wrong.sum()), 50, 'предусловие: кадр без z-буфера должен ошибиться на этой сцене')
        fixed, info = TV.zbuffer_fix(g, st)
        self.assertEqual(info['zbuf'], 'вкл')
        self.assertGreaterEqual(info['zbuf_px_fixed'], int(wrong.sum()))
        self.assertFalse(np.isin(fixed['ids'], (1, 2)).any(), 'задняя грань осталась видимой')
        self.assertTrue((fixed['ids'][wrong] == 0).all())
        self.assertTrue((fixed['depth'][wrong] < st['depth'][wrong]).all(), 'глубина в исправленных пикселях должна стать ближе')
        self.assertTrue((fixed['uv'][wrong, 0] < 0.5).all(), 'UV исправленных пикселей — из лицевой ячейки (u < 0,5)')
        pr, pm = z_photo()
        old = TV.transfer(g, st, pr, pm, tone=False)
        new = TV.transfer(g, fixed, pr, pm, tone=False)
        self.assertGreater(known_on(g, old, (1, 2)), 200, 'контроль: без z-буфера задняя грань получает фото')
        self.assertEqual(known_on(g, new, (1, 2)), 0, 'с z-буфером зад не получает ни текселя')
        self.assertGreater(known_on(g, new, (0,)), known_on(g, old, (0,)), 'лицевая грань под задней вернула фото')

    def test_closed_front_face_hides_the_rear(self):
        """Закрытая передняя грань: перед (0, 1) закрывает зад (2, 3) целиком — растр верен, z-буфер его не трогает, на заде фото нет совсем."""
        g = z_scene('closed')
        st = z_stage(g)
        fixed, info = TV.zbuffer_fix(g, st)
        self.assertEqual(info['zbuf_px_fixed'], 0)
        self.assertTrue(fixed['ids'] is st['ids'] or (fixed['ids'] == st['ids']).all())
        pr, pm = z_photo()
        tr = TV.transfer(g, fixed, pr, pm, tone=False)
        self.assertGreater(known_on(g, tr, (0, 1)), 2000)
        self.assertEqual(known_on(g, tr, (2, 3)), 0)

    def test_hole_shows_only_through_the_window(self):
        """Окно в передней стенке: зад получает фото только там, где он виден камере (не по всей площади)."""
        g = z_scene('hole')
        st = z_stage(g)
        fixed, _info = TV.zbuffer_fix(g, st)
        pr, pm = z_photo()
        tr = TV.transfer(g, fixed, pr, pm, tone=False)
        rear, front = known_on(g, tr, (4, 5)), known_on(g, tr, (0, 1, 2, 3))
        self.assertGreater(rear, 200, 'через окно зад виден — фото на нём честное')
        import tex_coverage as TC
        T = g[0]['tex'].shape[0]
        fid, _ = TC.raster(np.stack([g[0]['UV'][:, 0] * T, (1.0 - g[0]['UV'][:, 1]) * T], 1), g[0]['F'], T)
        occ_rear = int(np.isin(fid, (4, 5)).sum())
        self.assertLess(rear, 0.5 * occ_rear, 'зад не должен быть известен весь: большая часть закрыта передней стенкой')
        self.assertGreater(front, 1000)

    def test_one_face_per_pixel_nothing_shows_through(self):
        """«Полупрозрачного нет»: после исправления в КАЖДОМ пикселе одна грань — ближайшая (с допуском из правил); ни одна грань не просвечивает сквозь ближнюю."""
        for kind in ('double', 'closed', 'hole'):
            g = z_scene(kind)
            st = z_stage(g)
            fixed, _info = TV.zbuffer_fix(g, st)
            ids_n, z_n = self._nearest(g, st)
            m = st['mask'] & (fixed['ids'] >= 0) & (ids_n >= 0)
            behind = (fixed['depth'] - z_n)[m] / st['px_len']
            self.assertLessEqual(float(behind.max()), TV.ZBUF_TOL + 0.5, f'{kind}: в пикселе видна грань глубже ближайшей на {behind.max():.1f} px')
            self.assertTrue((fixed['mask'] == st['mask']).all(), 'силуэт не меняется')

    def test_tolerance_is_from_rules_and_keeps_near_ties(self):
        """Допуск — из rules/tex-visible.json; грани глубже ближайшей меньше чем на допуск растр не меняют (шум разных правил закраски краёв)."""
        rules = TV._rules()
        self.assertEqual(TV.ZBUF_TOL, float(rules['z_buffer_tol_px']))
        g = z_scene('double')
        st = z_stage(g)
        keep = TV.ZBUF_TOL
        try:
            TV.ZBUF_TOL = 1e6                                      # допуск огромный: «рядом» — всё, растр обязан остаться как есть
            same, info = TV.zbuffer_fix(g, st)
        finally:
            TV.ZBUF_TOL = keep
        self.assertEqual(info['zbuf_px_fixed'], 0)
        self.assertTrue((same['ids'] == st['ids']).all())

    def test_tie_back_face_yields_to_the_nearest(self):
        """Ничья по глубине (двойная стенка тоньше допуска): грань спиной к камере (знаковая нормаль, замкнутая форма с согласованным обходом) не бывает видимой поверхностью — в пикселе берётся ближайшая;
        без этого правила (`ZBUF_BACK` выкл.) допуск оставил бы её, как есть."""
        V = np.array([(-.5, -.5, -.5), (.5, -.5, -.5), (.5, .5, -.5), (-.5, .5, -.5), (-.5, -.5, .5), (.5, -.5, .5), (.5, .5, .5), (-.5, .5, .5)], float)
        F = np.array([(0, 3, 2), (0, 2, 1), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (3, 7, 6), (3, 6, 2), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)])
        g = [{'name': 'cube', 'V': V, 'F': F, 'UV': np.stack([V[:, 0] + .5, V[:, 1] + .5], 1) * .9 + .05, 'tex': np.full((64, 64, 3), 128, np.uint8)}]
        st = z_stage(g)
        keep = TV.BACK_ON
        TV.BACK_ON = True
        try:
            back, _note = TV.back_face_mask(g, st)
            self.assertIsNotNone(back, 'знаковая нормаль куба должна считаться')
            front = int(np.bincount(st['ids'][st['mask']].ravel()).argmax())
            self.assertFalse(back[front])
            rear = int(np.nonzero(back)[0][0])
            px = st['mask'] & (st['ids'] == front)
            self.assertGreater(int(px.sum()), 500)
            bad = dict(st, ids=st['ids'].copy(), depth=st['depth'].copy())
            bad['ids'][px] = rear                                     # «растр ошибся в ничью»: грань спиной, глубже ближайшей на 1 px предмета (< допуска)
            bad['depth'][px] += 1.0 * st['px_len']
            self.assertLess(1.0, TV.ZBUF_TOL)
            keep_b = TV.ZBUF_BACK
            try:
                TV.ZBUF_BACK = False
                same, info0 = TV.zbuffer_fix(g, bad)
                self.assertEqual(info0['zbuf_px_fixed'], 0, 'допуск ничью не трогает')
                self.assertTrue((same['ids'][px] == rear).all())
                TV.ZBUF_BACK = True
                fixed, info1 = TV.zbuffer_fix(g, bad)
            finally:
                TV.ZBUF_BACK = keep_b
            self.assertGreaterEqual(info1['zbuf_px_back_tie'], int(0.99 * px.sum()))             # пара краевых пикселей закрашивается у cv2 и у нашего растра по-разному
            self.assertGreaterEqual(float((fixed['ids'][px] == front).mean()), 0.9, 'в ничью побеждает грань, обращённая к камере (у диагонали квадрата — второй его треугольник)')
            left = px & (fixed['ids'] >= 0)
            self.assertLess(float(back[fixed['ids'][left]].mean()), 0.01, 'грань спиной остаётся лишь там, где и ближайшая в z-буфере — спиной (краевые пиксели силуэта)')
            self.assertTrue((fixed['ids'][~px] == st['ids'][~px]).all(), 'остальное не тронуто')
        finally:
            TV.BACK_ON = keep

    def test_skips_without_perspective_camera_or_with_other_shape(self):
        """Нет перспективной камеры (ортография, тестовая) и форма не та, что у растра — растр остаётся, причина в пометке."""
        g = z_scene('double')
        st = z_stage(g)
        st_o = dict(st, camera={'kind': 'test'})
        out, info = TV.zbuffer_fix(g, st_o)
        self.assertIs(out, st_o)
        self.assertIn('не перспективная', info['zbuf'])
        other = z_scene('closed')
        out2, info2 = TV.zbuffer_fix(other, st)                    # растр от другой формы
        self.assertIs(out2, st)
        self.assertIn('пропуск', info2['zbuf'])
        TV.ZBUF_ON = False
        out3, info3 = TV.zbuffer_fix(g, st)
        self.assertIs(out3, st)
        self.assertEqual(info3['zbuf'], 'выключено')

    def test_visible_known_share_denominator_is_silhouette_not_texels(self):
        """T-215: закрытая форма — перед виден и покрыт фото, зад скрыт и фото не получает. Доля текселей (прежняя known_share) ≈ половина (зад в знаменателе), доля видимого ≈ 1:
        гейт по ней не режет форму, у которой видимое покрыто целиком."""
        g = z_scene('closed')
        st, _ = TV.zbuffer_fix(g, z_stage(g))
        pr, pm = z_photo()
        tr = TV.transfer(g, st, pr, pm, tone=False)
        share, vis = TV.visible_known_share(g, st, tr)
        self.assertEqual(vis, int(st['mask'].sum()))
        texel = sum(s['known'] for s in tr['stats']) / max(sum(s['occupied'] for s in tr['stats']), 1)
        self.assertLess(texel, 0.6, 'контроль: прежняя мера занижена задом в знаменателе')
        self.assertGreater(share, 0.85, f'видимое покрыто почти целиком, а доля {share}')
        self.assertGreater(share, 1.5 * texel)

    def test_visible_known_share_tracks_photo_coverage_of_silhouette(self):
        """Фото закрывает лишь левую половину силуэта → доля видимого ≈ 0,5 (знаменатель — весь силуэт), а не доля занятых текселей."""
        g = z_scene('closed')
        st, _ = TV.zbuffer_fix(g, z_stage(g))
        pr, pm = z_photo()
        pm = pm.copy()
        pm[:, PX // 2:] = False
        pr = np.where(pm[..., None], pr, 0).astype(np.uint8)
        tr = TV.transfer(g, st, pr, pm, tone=False)
        share, _ = TV.visible_known_share(g, st, tr)
        full, _ = TV.visible_known_share(g, st, TV.transfer(g, st, *z_photo(), tone=False))
        self.assertLess(share, 0.6 * full, f'половина фото — заметно меньше полной ({share} против {full})')
        self.assertGreater(share, 0.3 * full)

    def test_no_known_gives_zero_share_and_empty_mask_does_not_divide(self):
        g = z_scene('closed')
        st, _ = TV.zbuffer_fix(g, z_stage(g))
        tr = TV.transfer(g, st, np.zeros((PX, PX, 3), np.uint8), np.zeros((PX, PX), bool), tone=False)
        self.assertEqual(TV.visible_known_share(g, st, tr)[0], 0.0)
        empty = dict(st, mask=np.zeros_like(st['mask']))
        self.assertEqual(TV.visible_known_share(g, empty, tr), (0.0, 0))


class FrontCheck(unittest.TestCase):
    """Перёд/зад после переноса (T-20261123-43): вердикт по долям известного и кромкам камеры; без правил — не применимо."""

    def setUp(self):
        self.g = box_geom()
        self.tr = {'known': [np.ones((16, 16), bool)]}
        self.cam = {'az': 10.0}

    def run_check(self, shares, agree, flipped, ref=0.5):
        return TV.front_check(self.g, self.tr, self.cam, '/нет', shares_fn=lambda *a, **k: shares, flipped_fn=lambda sh: flipped, agree=agree, ref=ref)

    def test_flipped_and_weak_edges_refuse(self):
        r = self.run_check({'перед': 0.25, 'зад': 0.36}, 0.39, True)
        self.assertEqual(r['state'], 'flipped')
        self.assertIn('кромок', r['why'])

    def test_flipped_but_edges_fine_is_not_refusal(self):
        r = self.run_check({'перед': 0.29, 'зад': 0.40}, 0.56, True)
        self.assertEqual(r['state'], 'ok')
        self.assertIn('перёд не определён', r['why'])

    def test_not_flipped_ok(self):
        self.assertEqual(self.run_check({'перед': 0.74, 'зад': 0.03}, 0.2, False)['state'], 'ok')

    def test_edges_unknown_is_not_refusal(self):
        self.assertEqual(self.run_check({'перед': 0.2, 'зад': 0.4}, None, True)['state'], 'ok')

    def test_no_camera_or_no_witness_not_applicable(self):
        self.assertEqual(TV.front_check(self.g, self.tr, None, '/нет')['state'], 'n/a')
        def boom(*a, **k):
            raise KeyError('front_guard')
        r = TV.front_check(self.g, self.tr, self.cam, '/нет', shares_fn=boom, flipped_fn=lambda sh: False, agree=0.1, ref=0.5)
        self.assertEqual(r['state'], 'n/a')
        self.assertIn('front_guard', r['why'])

    def test_one_edge_ref_source(self):
        src = open(os.path.join(HERE, 'tex_visible.py'), encoding='utf-8').read()
        self.assertIn("camera-check.json", src)
        self.assertIsInstance(TV.edge_ref(), float)


class ProductJsonCli(unittest.TestCase):
    """`tex_visible.main --product-json`: после 06 запускается «зад корпусной» (T-43/❓2), только если этап прошёл и роль есть; роль — из product.json."""

    def _main(self, passed, pj_content):
        import json as _json
        import tempfile
        calls = []
        with tempfile.TemporaryDirectory() as t:
            pj = os.path.join(t, 'product.json')
            if pj_content is not None:
                open(pj, 'w', encoding='utf-8').write(_json.dumps(pj_content))
            old_run, old_bp, old_argv = TV.run, TV.BPS.run_stage, sys.argv
            TV.run = lambda *a, **k: {'passed': passed}
            TV.BPS.run_stage = lambda run, sku, role, **k: calls.append((role, k)) or {'applied': True, 'reason': ''}
            sys.argv = ['tex_visible.py', 'm.glb', 'p.png', 'pose', t, 'sku1', '--product-json', pj]
            try:
                import contextlib
                import io
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    rc = TV.main()
            finally:
                TV.run, TV.BPS.run_stage, sys.argv = old_run, old_bp, old_argv
        return rc, calls, out.getvalue()

    def test_role_from_product_json_after_passed_stage(self):
        rc, calls, out = self._main(True, {'role': 'комод'})
        self.assertEqual(rc, 0)
        self.assertEqual(calls, [('комод', {'keep_original': False, 'pose_run': 'pose', 'refusal': ''})])      # pose_run — откуда берётся согласие кромок на ноде (в папке товара pose.json нет)
        self.assertIn('back_panel', out)

    def test_failed_stage_still_records_refusal_and_no_file(self):
        rc, calls, _ = self._main(False, {'role': 'комод'})                                  # этап отказал: шаг зовётся с причиной → запись правила «этап 6 не прошёл», зад не трогается
        self.assertEqual(rc, 1)
        self.assertEqual(calls, [('комод', {'keep_original': False, 'pose_run': 'pose', 'refusal': 'отказ без причины'})])
        rc, calls, _ = self._main(True, None)                                                  # нет файла: роль пустая → шаг отработает воздержанием (причина в back_panel.json), не падение
        self.assertEqual(calls, [('', {'keep_original': False, 'pose_run': 'pose', 'refusal': ''})])


class TestToneSameSide(unittest.TestCase):
    """T-28/1: тон Ш3б не красит грани другой стороны формы (зад/верх/бок) — иначе 07 держит их «известными» кусками тона фасада."""

    def test_box_front_source_paints_only_front_plane(self):
        g = box_geom()[0]
        src = np.zeros(len(g['F']), np.int64)                     # источник тона у всех граней — грань 0 (перед)
        ok = TV.tone_same_side(g['V'], g['F'], src, 0.7)
        self.assertTrue(ok[0] and ok[1], 'вся лицевая плоскость (две грани) красится')
        self.assertFalse(ok[2:].any(), 'зад, бока, верх и низ коробки (90° и 180°) не красятся')

    def test_unreached_faces_stay_unpainted_and_off_switch(self):
        g = box_geom()[0]
        src = np.full(len(g['F']), -1, np.int64)
        src[0] = 0
        self.assertEqual(int(TV.tone_same_side(g['V'], g['F'], src, 0.7).sum()), 1)
        src_all = np.zeros(len(g['F']), np.int64)
        self.assertTrue(TV.tone_same_side(g['V'], g['F'], src_all, 0.0).all(), 'порог 0 — прежнее поведение (все достигнутые красятся)')

    def test_bevel_chain_blocked_by_source_not_by_edge(self):
        """Скос из 5 граней по 20° каждая: по одному ребру пройти можно (cos 0,94), но от источника цепочка уходит за порог — рёберный запрет это обходил."""
        V = np.zeros((14, 3))
        ang, pos = 0.0, np.zeros(3)
        V[0], V[1] = (0, 0, 0), (0, 1, 0)
        for i in range(1, 7):
            ang += np.radians(20.0)
            pos = pos + np.array([np.cos(ang), 0.0, np.sin(ang)])
            V[2 * i], V[2 * i + 1] = pos, pos + np.array([0, 1.0, 0])
        F = []
        for i in range(6):
            a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
            F += [[a, c, d], [a, d, b]]
        F = np.array(F)
        src = np.zeros(len(F), np.int64)
        ok = TV.tone_same_side(V, F, src, 0.7)
        self.assertTrue(ok[:4].all(), 'ближние грани (до ~40°) красятся')
        self.assertFalse(ok[-2:].any(), 'дальний конец скоса (> 45° от источника) не красится')


if __name__ == '__main__':
    unittest.main()

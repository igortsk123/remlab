"""Тесты этапа 6 (tex_visible): синтетическая коробка; «камера этапа 4» — растр лицевой грани (id, UV, cos, маска) и фото красно-синее. Бесплатно, секунды."""
import json
import os
import sys
import tempfile
import unittest

import numpy as np
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
        self.assertTrue(130 < col[0] < 220)                                         # не копия наблюдения и не копия опоры
        self.assertTrue(abs(col[0] - 220) < abs(col[0] - 130))                      # ближе к опоре: светлота доверена слабо (WL=0,3)
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
        m = {'silhouette_iou': 0.93, 'known_share': 0.3, 'edge_corr': 0.97, 'lab_dE': 1.2}
        mm, why = TV.gate(m)
        self.assertEqual(why, [])
        mm, why = TV.gate({**m, 'silhouette_iou': 0.5, 'edge_corr': 0.1})
        self.assertEqual(len(why), 2)
        mm, why = TV.gate({'silhouette_iou': 0.9})                 # нет измерений ≠ «ок»
        self.assertTrue(any('known_share' in w for w in why))

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

if __name__ == '__main__':
    unittest.main()

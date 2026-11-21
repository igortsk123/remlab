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

    def test_grazing_band_not_taken(self):
        tr, _p, _m = self._transfer(fake_stage(cos_band=(80, 100, 0.1)))     # полоса вскользь (cos<0,34) — не берётся
        T = tr['tex'][0].shape[0]
        k = tr['known'][0][T // 2:, : T // 3]
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


if __name__ == '__main__':
    unittest.main()

"""Тесты этапа 6 (tex_visible): синтетический предмет — плоский лист лицом к камере и коробка с боками; фото — красно-синее. Бесплатно, секунды."""
import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]
import tex_visible as TV  # noqa: E402


def box_geom(w=1.0, h=1.0, d=0.6, T=256):
    """Коробка w×h×d (лицом +Z), у каждой стороны свой квадрат развёртки в сетке 3×2: перед — (0,1) нижний ряд слева."""
    x, y, z = w / 2, h / 2, d / 2
    quads = {  # сторона: 4 угла (против часовой, если смотреть снаружи), номер ячейки
        'front': ([(-x, -y, z), (x, -y, z), (x, y, z), (-x, y, z)], 0),
        'back': ([(x, -y, -z), (-x, -y, -z), (-x, y, -z), (x, y, -z)], 1),
        'right': ([(x, -y, z), (x, -y, -z), (x, y, -z), (x, y, z)], 2),
        'left': ([(-x, -y, -z), (-x, -y, z), (-x, y, z), (-x, y, -z)], 3),
        'top': ([(-x, y, z), (x, y, z), (x, y, -z), (-x, y, -z)], 4),
        'bottom': ([(-x, -y, -z), (x, -y, -z), (x, -y, z), (-x, -y, z)], 5),
    }
    V, F, UV = [], [], []
    for name, (pts, cell) in quads.items():
        i0 = len(V)
        cx, cy = cell % 3, cell // 3
        for k, p in enumerate(pts):
            V.append(p)
            u0, v0 = [(0, 0), (1, 0), (1, 1), (0, 1)][k]
            UV.append(((cx + 0.05 + 0.9 * u0) / 3.0, (cy + 0.05 + 0.9 * v0) / 2.0))
        F += [[i0, i0 + 1, i0 + 2], [i0, i0 + 2, i0 + 3]]
    return [{'name': 'box', 'V': np.array(V, float), 'F': np.array(F), 'UV': np.array(UV), 'tex': np.full((T, T, 3), 128, np.uint8)}]


def photo_red_blue(n=300):
    a = np.zeros((n, n, 4), np.uint8)
    a[..., 3] = 255
    a[:, : n // 2, :3] = (220, 30, 30)
    a[:, n // 2:, :3] = (30, 30, 220)
    return a


class TestTexVisible(unittest.TestCase):
    def test_transfer_paints_front_only(self):
        geoms = box_geom()
        cam = TV.Camera(geoms, 0.0, 0.0, 240)
        ids, zb, nc = TV.shape_buffers(geoms, cam)
        import color_o2 as CO
        import recolor_lp as LP
        prgb0, pm0 = CO.align_photo(photo_red_blue(), ids >= 0)
        prgb, pm, al = LP.refine_align(prgb0, pm0, ids >= 0)
        self.assertGreater(al['iou'], 0.9)
        tr = TV.transfer(geoms, cam, zb, prgb, pm)
        tex, known = tr['tex'][0], tr['known'][0]
        self.assertGreater(known.sum(), 0)
        T = tex.shape[0]
        # передняя ячейка развёртки (0,0): внизу слева; v вверх → строки с конца
        front = tex[T // 2:, : T // 3]                     # нижний ряд текстуры = v∈[0,0.5] (картинка перевёрнута по v)
        kf = known[T // 2:, : T // 3]
        self.assertGreater(kf.mean(), 0.5)
        left, right = front[:, : front.shape[1] // 2][kf[:, : kf.shape[1] // 2]], front[:, front.shape[1] // 2:][kf[:, kf.shape[1] // 2:]]
        self.assertTrue((np.abs(left.mean(0) - [220, 30, 30]) < 25).all() or (np.abs(left.mean(0) - [30, 30, 220]) < 25).all())
        self.assertGreater(np.abs(left.mean(0) - right.mean(0)).max(), 150)      # две половины фото разные: красная и синяя (зеркало по u допустимо — это проверка переноса, не ориентации)
        # задняя сторона НЕ трогается: серая заготовка, не «известна»
        back_known = known[T // 2:, T // 3: 2 * T // 3]
        self.assertEqual(int(back_known.sum()), 0)
        back = tex[T // 2:, T // 3: 2 * T // 3]
        self.assertTrue((np.abs(back.reshape(-1, 3).astype(int) - 128) <= 1).mean() > 0.95)

    def test_grazing_side_not_taken(self):
        geoms = box_geom()
        cam = TV.Camera(geoms, 0.0, 0.0, 240)             # боковые грани параллельны лучу: cos≈0 → вскользь
        ids, zb, nc = TV.shape_buffers(geoms, cam)
        import color_o2 as CO
        import recolor_lp as LP
        prgb0, pm0 = CO.align_photo(photo_red_blue(), ids >= 0)
        prgb, pm, _al = LP.refine_align(prgb0, pm0, ids >= 0)
        tr = TV.transfer(geoms, cam, zb, prgb, pm)
        T = tr['known'][0].shape[0]
        for cell_x, cell_y in ((2, 0), (0, 1)):          # right, left
            r0 = (1 - cell_y) * T // 2                       # строка текстуры идёт вниз, v вверх: ряд 0 развёртки — нижняя половина картинки
            k = tr['known'][0][r0:r0 + T // 2, cell_x * T // 3:(cell_x + 1) * T // 3]
            self.assertEqual(int(k.sum()), 0)

    def test_gate_and_check_json(self):
        m = {'silhouette_iou': 0.93, 'known_share': 0.3, 'edge_corr': 0.97, 'lab_dE': 1.2}
        mm, why = TV.gate(m)
        self.assertEqual(why, [])                           # inner_edge_agree неприменима — не провал
        self.assertNotIn('inner_edge_agree', mm)
        mm, why = TV.gate({**m, 'silhouette_iou': 0.5, 'inner_edge_agree': 0.1})
        self.assertEqual(len(why), 2)
        mm, why = TV.gate({'silhouette_iou': 0.9})           # нет измерений ≠ «ок»
        self.assertTrue(any('known_share' in w for w in why))

    def test_full_stage_writes_outputs(self):
        import trimesh
        with tempfile.TemporaryDirectory() as d:
            g = box_geom()[0]
            m = trimesh.Trimesh(vertices=g['V'], faces=g['F'], process=False)
            from trimesh.visual import TextureVisuals
            m.visual = TextureVisuals(uv=g['UV'])
            glb = os.path.join(d, 'shape.glb')
            m.export(glb)
            photo = os.path.join(d, 'p.png')
            Image.fromarray(photo_red_blue()).save(photo)
            r = TV.run(glb, photo, os.path.join(d, 'run'), 'sku:1', pose=(0.0, 0.0), size=240)
            sd = os.path.join(d, 'run', 'sku_1', '06-visible')
            for f in ('visible.glb', 'known.png', 'check.json', 'frame.png'):
                self.assertTrue(os.path.exists(os.path.join(sd, f)), f)
            import json
            ch = json.load(open(os.path.join(sd, 'check.json'), encoding='utf-8'))
            self.assertEqual(ch['stage'], '06-visible')
            self.assertIn('needs_qwen', ch['extra'])
            self.assertEqual(ch['passed'], r['passed'])
            self.assertGreater(ch['metric']['value'], 0.85)


if __name__ == '__main__':
    unittest.main()

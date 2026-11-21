#!/usr/bin/env python3
"""Тест голосования частей по кадрам облёта (paint-photo-fill-01, этап 3, T-20261120-169): без torch и Blender, на синтетической «ножке + столешнице».
Нужны numpy, scipy. Запуск: python3 tools/assets/tests/test_parts_vote.py"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import parts_colour as pcol  # noqa: E402
import parts_refine as pr  # noqa: E402
import part_shapes as shp  # noqa: E402
import parts_vote as pv  # noqa: E402

RULES = pv.load_rules()


def strip_mesh(n: int):
    """Лента из n квадратов (2n треугольников) по оси X: соседние грани делят ребро; вершины задвоены на стыках — как швы развёртки."""
    verts, faces = [], []
    for i in range(n):
        base = len(verts)
        verts += [(i, 0, 0), (i + 1, 0, 0), (i + 1, 1, 0), (i, 1, 0)]
        faces += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    return np.array(verts, dtype=np.float32), np.array(faces, dtype=np.int64)


class PartsVote(unittest.TestCase):
    def setUp(self):
        self.verts, self.faces = strip_mesh(50)               # 100 граней: 0..59 «столешница», 60..99 «ножки»
        self.nf = len(self.faces)
        self.top = np.arange(self.nf) < 60
        self.w = np.ones(self.nf, dtype=np.float32)

    def regions(self, perm, hide=None):
        reg = np.where(self.top, perm[0], perm[1]).astype(np.int32)
        if hide is not None:
            reg[hide] = -1
        return reg

    def test_same_part_with_different_numbers_is_merged(self):
        views = [self.regions((0, 1)), self.regions((5, 2)), self.regions((1, 0))]
        vis = [np.ones(self.nf, dtype=bool)] * 3
        res = pv.run_vote(views, vis, [self.w] * 3, self.verts, self.faces, RULES)
        part = res["part"]
        self.assertEqual(len(np.unique(part)), 2, "две части: столешница и ножки")
        self.assertTrue((part[self.top] == part[0]).all() and (part[~self.top] == part[-1]).all())
        self.assertNotEqual(part[0], part[-1])
        self.assertAlmostEqual(float(res["agree"].mean()), 1.0, places=3)

    def test_face_unseen_by_all_views_takes_neighbour_part(self):
        hide = np.zeros(self.nf, dtype=bool)
        hide[[10, 11, 70]] = True
        views = [self.regions((0, 1), hide), self.regions((3, 4), hide)]
        vis = [~hide, ~hide]
        res = pv.run_vote(views, vis, [self.w] * 2, self.verts, self.faces, RULES)
        part = res["part"]
        self.assertTrue((part >= 0).all(), "все грани получили часть")
        self.assertEqual(part[10], part[0])
        self.assertEqual(part[70], part[-1])
        self.assertEqual(int(res["seen_any"].sum()), self.nf - 3, "невиденные считаются отдельно")

    def test_island_without_neighbours_takes_nearest_part(self):
        verts = np.concatenate([self.verts, self.verts[self.faces[60:70]].reshape(-1, 3) + np.array([0.0, 0.0, 5.0])])   # остров, не связанный с лентой
        k = len(self.verts)
        isl = np.arange(k, k + 30).reshape(10, 3)
        faces = np.concatenate([self.faces, isl])
        part = np.concatenate([np.where(self.top, 0, 1), np.full(10, -1)]).astype(np.int32)
        adj = pv.weld_adjacency(verts, faces)
        self.assertTrue((pv.fill_unlabeled(part, adj)[-10:] < 0).all(), "заливка по соседству остров не берёт")
        out = pv.fill_nearest(pv.fill_unlabeled(part, adj), verts, faces)
        self.assertTrue((out >= 0).all() and (out[-10:] == 1).all(), "остров над «ножками» берёт часть ближайших граней")

    def test_agreement_counts_merged_raw_parts_together(self):
        views = [self.regions((0, 1)), self.regions((2, 3))]        # одна физическая часть = разные сырые номера в разных кадрах
        vis = [np.ones(self.nf, dtype=bool)] * 2
        mapping, n = pv.merge_regions(views, vis, RULES)
        raw, ag, acc = pv.vote_faces(views, [{0: 0, 1: 1}, {2: 2, 3: 3}], [self.w] * 2, 4, with_acc=True)   # сведение не удалось — 4 сырые части
        self.assertLess(float(ag.mean()), 0.75)
        final = np.where(self.top, 0, 1).astype(np.int32)           # а итог — две части
        self.assertAlmostEqual(float(pv.final_agreement(acc, raw, final).mean()), 1.0, places=3)

    def test_tiny_part_goes_to_neighbour(self):
        part = np.where(self.top, 0, 1).astype(np.int32)
        part[30] = 2                                            # одна грань = 1 % — на границе порога → меньше доли
        adj = pv.weld_adjacency(self.verts, self.faces)
        out = pv.small_parts_to_neighbours(part, adj, 0.02)
        self.assertEqual(len(np.unique(out)), 2)
        self.assertEqual(out[30], 0)

    def test_label_map_small_over_big_and_filters(self):
        h = w = 40
        obj = np.ones((h, w), dtype=bool)
        big = np.zeros((h, w), dtype=bool)
        big[:, :30] = True
        small = np.zeros((h, w), dtype=bool)
        small[10:20, 10:20] = True
        speck = np.zeros((h, w), dtype=bool)
        speck[0, 0] = True                                      # меньше min_area_share — прочь
        whole = np.ones((h, w), dtype=bool)                     # больше max_area_share — прочь
        lm = pv.label_map([speck, small, big, whole], obj, RULES)
        self.assertEqual(lm[15, 15], 1, "мелкая область — поверх крупной")
        self.assertEqual(lm[0, 0], 0, "прыщ отброшен, пиксель принадлежит крупной")
        self.assertEqual(lm[0, 35], -1, "вне крупной и без целой маски — нет")

    def test_geometry_overlap_names_legs(self):
        part = np.where(self.top, 0, 1).astype(np.int32)
        legs = ~self.top
        g = pv.geometry_overlap(part, legs, RULES)
        self.assertEqual(g["roles"][1]["role"], "legs")
        self.assertIsNone(g["roles"][0]["role"])
        self.assertEqual(g["legs_iou"], 1.0)
        none = pv.geometry_overlap(part, np.zeros(self.nf, dtype=bool), RULES)
        self.assertIsNone(none["roles"][1]["role"], "геометрия без ножек — роль не даём")

    def test_quality_verdicts(self):
        part = np.where(self.top, 0, 1).astype(np.int32)
        ok = pv.quality(part, np.ones(self.nf, dtype=np.float32), np.ones(self.nf, dtype=bool), RULES)
        self.assertTrue(ok["ok"], ok["reason"])
        one = pv.quality(np.zeros(self.nf, dtype=np.int32), np.ones(self.nf, dtype=np.float32), np.ones(self.nf, dtype=bool), RULES)
        self.assertFalse(one["ok"])
        self.assertIn("число частей", one["reason"])
        unsure = pv.quality(part, np.full(self.nf, 0.3, dtype=np.float32), np.ones(self.nf, dtype=bool), RULES)
        self.assertFalse(unsure["ok"])
        self.assertIn("спорят", unsure["reason"])
        empty = pv.quality(np.full(self.nf, -1, dtype=np.int32), np.zeros(self.nf, dtype=np.float32), np.zeros(self.nf, dtype=bool), RULES)
        self.assertFalse(empty["ok"], "пустой результат не проходит")

    def test_colourless_input_is_refused_with_reason(self):
        self.assertFalse(pv.colour_verdict(False, None, RULES)[0])
        self.assertIn("без цвета", pv.colour_verdict(False, None, RULES)[1])
        self.assertFalse(pv.colour_verdict(True, 0.4, RULES)[0], "плоская текстура — отказ")
        self.assertFalse(pv.colour_verdict(True, None, RULES)[0])
        self.assertTrue(pv.colour_verdict(True, 40.0, RULES)[0])

    def test_part_colours_split_wood_from_fabric(self):
        lab = pcol.rgb_to_lab(np.array([[255, 255, 255], [0, 0, 0], [200, 160, 110]]))
        self.assertAlmostEqual(float(lab[0, 0]), 100.0, delta=0.5)
        self.assertAlmostEqual(float(lab[1, 0]), 0.0, delta=0.5)
        part = np.where(self.top, 0, 1).astype(np.int32)
        rgb = np.where(self.top[:, None], np.array([230, 225, 215]), np.array([120, 80, 45])).astype(np.uint8)
        cols = pcol.part_colours(part, rgb)
        self.assertGreater(cols[0]["lab_median"][0], cols[1]["lab_median"][0] + 30, "обивка светлее дерева")
        self.assertEqual(pcol.mixed_parts(cols, RULES), [])
        rgb2 = rgb.copy()
        rgb2[:30] = np.array([120, 80, 45])                       # в части «обивка» дерево
        rgb2[30:60:2] = np.array([40, 30, 20])
        self.assertIn(0, pcol.mixed_parts(pcol.part_colours(part, rgb2), RULES), "два цвета в одной части — помечена")

    @staticmethod
    def chair_like():
        """Объёмная «спинка+сиденье» (плотная точечная плита-куб) и тонкая «ножка» (стержень) — по точкам-граням: центры граней = сэмпл, вершины — крошечные треугольники."""
        rng = np.random.default_rng(1)
        body = rng.uniform([-0.5, 0.0, -0.5], [0.5, 0.35, 0.5], size=(9000, 3))
        rod = np.column_stack([rng.normal(0.0, 0.003, 1500) + 0.3, rng.uniform(-0.7, 0.0, 1500), rng.normal(0.0, 0.003, 1500) + 0.3])
        c = np.concatenate([body, rod])
        d = 0.002
        verts = np.concatenate([c + [0, 0, 0], c + [d, 0, 0], c + [0, d, 0]]).astype(np.float32)
        n = len(c)
        faces = np.column_stack([np.arange(n), np.arange(n) + n, np.arange(n) + 2 * n])
        return verts, faces, np.arange(n) >= len(body)

    def test_thin_rod_is_split_off_from_blob_part(self):
        verts, faces, is_rod = self.chair_like()
        part = np.zeros(len(faces), dtype=np.int32)                    # SAM2 склеил всё в одну часть
        adj = pv.weld_adjacency(verts, faces, 5)
        kind, _, _ = shp.face_shapes(verts, faces, RULES["shape"])
        self.assertGreater(float((kind[is_rod] == shp.LINEAR).mean()), 0.8, "стержень — linear")
        self.assertLess(float((kind[~is_rod] == shp.LINEAR).mean()), 0.1, "объём — не linear")
        self.assertGreater(pr.linear_in_blob_share(part, kind), 0.9)
        # соседство по сваренным вершинам у случайных точек пустое — свяжем ближайшими: рёбра между центрами в радиусе
        from scipy import sparse
        from scipy.spatial import cKDTree
        c = verts[faces].mean(axis=1)
        pairs = cKDTree(c).query_pairs(0.03, output_type="ndarray")
        adj = sparse.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(c), len(c))).tocsr()
        adj = (adj + adj.T).tocsr()
        new, rep = pr.refine(part, verts, faces, adj, None, RULES)
        self.assertGreaterEqual(rep["parts_after"], 2)
        self.assertLess(rep["linear_in_blob_part_share"], 0.1, rep)
        self.assertGreater(rep["linear_in_blob_part_share_before"], 0.9)
        rod_parts = np.unique(new[is_rod])
        self.assertTrue(len(rod_parts) <= 2 and (new[is_rod] != new[~is_rod][0]).mean() > 0.8, "ножка — своя часть")

    def test_small_part_of_same_kind_and_colour_merges_but_thin_stays(self):
        verts, faces, is_rod = self.chair_like()
        from scipy import sparse
        from scipy.spatial import cKDTree
        c = verts[faces].mean(axis=1)
        pairs = cKDTree(c).query_pairs(0.03, output_type="ndarray")
        adj = sparse.coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(len(c), len(c))).tocsr()
        adj = (adj + adj.T).tocsr()
        kind, _, _ = shp.face_shapes(verts, faces, RULES["shape"])
        part = np.where(is_rod, 1, 0).astype(np.int32)
        speck = (~is_rod) & (c[:, 0] > 0.40) & (c[:, 2] > 0.40)         # мозаичный кусок объёмной части того же цвета
        part[speck] = 2
        lab = np.tile(np.array([[80.0, 0.0, 0.0]]), (len(faces), 1))
        out = pr.merge_small(part, kind, adj, lab, RULES, RULES["refine"]["colour_merge_max_share"], RULES["refine"]["colour_merge_de"])
        self.assertTrue((out[speck] == 0).all(), "кусок того же цвета и вида влился в соседа")
        self.assertTrue((out[is_rod] == 1).all(), "тонкая часть не влилась в объёмную")
        lab2 = lab.copy()
        lab2[speck] = [40.0, 30.0, 20.0]
        out2 = pr.merge_small(part, kind, adj, lab2, RULES, RULES["refine"]["colour_merge_max_share"], RULES["refine"]["colour_merge_de"])
        self.assertTrue((out2[speck] == 2).all(), "другой цвет — не сливается")

    def test_rules_have_no_product_ids_and_are_complete(self):
        import json
        raw = json.dumps({k: v for k, v in RULES.items() if not k.startswith("_")})
        self.assertNotRegex(raw, r"\d{6,}", "ID товаров в правилах не нужны")
        for k in ("orbit", "sam", "region", "merge", "geometry", "check"):
            self.assertIn(k, RULES)
        self.assertGreaterEqual(sum(len(v["az_deg"]) for v in RULES["orbit"]["views"]), 8)
        self.assertLessEqual(sum(len(v["az_deg"]) for v in RULES["orbit"]["views"]), 14)


if __name__ == "__main__":
    unittest.main(verbosity=2)

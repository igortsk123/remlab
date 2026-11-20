#!/usr/bin/env python3
"""Тест голосования частей по кадрам облёта (paint-photo-fill-01, этап 3, T-20261120-169): без torch и Blender, на синтетической «ножке + столешнице».
Нужны numpy, scipy. Запуск: python3 tools/assets/tests/test_parts_vote.py"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
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

    def test_rules_have_no_product_ids_and_are_complete(self):
        import json
        raw = json.dumps({k: v for k, v in RULES.items() if not k.startswith("_")})
        self.assertNotRegex(raw, r"\d{6,}", "ID товаров в правилах не нужны")
        for k in ("orbit", "sam", "region", "merge", "geometry", "check"):
            self.assertIn(k, RULES)
        self.assertGreaterEqual(sum(len(v["az_deg"]) for v in RULES["orbit"]["views"]), 8)
        self.assertLessEqual(sum(len(v["az_deg"]) for v in RULES["orbit"]["views"]), 12)


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Ш4 (T-181) — чистая часть three_layers.py: карта фото→грани, распространение по форме, зоны, края."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import three_layers as tl  # noqa: E402


def strip_adj(n):
    from scipy import sparse
    a = sparse.lil_matrix((n, n))
    for i in range(n - 1):
        a[i, i + 1] = a[i + 1, i] = 1
    return a.tocsr()


class FaceRegion(unittest.TestCase):
    def test_majority_conflict_and_invisible(self):
        ids = -np.ones((4, 4), np.int32)
        lab = -np.ones((4, 4), np.int32)
        ids[0, :4], lab[0, :4] = 0, [1, 1, 1, 1]                      # грань 0 — целиком область 1
        ids[1, :4], lab[1, :4] = 1, [1, 2, 2, 3]                      # грань 1: 2 из 4 — доля 0.5 < 0.6 → спор
        reg, tot, c = tl.face_region_from_photo(ids, lab, 3)
        self.assertEqual(list(reg), [1, -1, -2])                      # грань 2 не видна на фото
        self.assertEqual(c["faces_conflict"], 1)


class Propagate(unittest.TestCase):
    def test_flat_spreads_crease_blocks_conflict_marks(self):
        n = np.tile([0.0, 0.0, 1.0], (6, 1))
        n[3:] = [0.0, 1.0, 0.0]                                        # излом 90° между гранями 2 и 3
        reg = np.array([5, -2, -2, -2, -2, -2])
        lab, c = tl.propagate(reg, strip_adj(6), n)
        self.assertEqual(list(lab[:3]), [5, 5, 5])
        self.assertTrue((lab[3:] == -3).all())                          # за изломом метка не прошла
        reg2 = np.array([1, -2, 2, -2, -2, -2])
        lab2, _ = tl.propagate(reg2, strip_adj(6), np.tile([0.0, 0.0, 1.0], (6, 1)))
        self.assertEqual(lab2[1], -1)                                   # две разные метки претендуют → спор


class Zones(unittest.TestCase):
    def test_front_rear_top_under_interior(self):
        nrm = np.array([[0, 0, 1], [0, 0, -1], [0, 1, 0], [0, -1, 0], [1, 0, 0]], float)
        photo = np.array([0, -2, -2, -2, -2])                           # фото видит только грань 0 → камера смотрит вдоль +z
        z = tl.surface_zones(nrm, photo, np.ones(5), np.array([1, 1, 1, 1, 0], bool))
        self.assertEqual([tl.ZONES[i] for i in z], ["front", "rear", "top", "underside", "interior"])


class Edges(unittest.TestCase):
    def test_boundary_on_photo_edge(self):
        grey = np.zeros((40, 40), np.float32)
        grey[:, 20:] = 200
        obj = np.ones((40, 40), bool)
        on = np.where(np.arange(40)[None, :] < 20, 0, 1) * np.ones((40, 1), int)
        off = np.where(np.arange(40)[None, :] < 8, 0, 1) * np.ones((40, 1), int)
        self.assertGreater(tl.edge_agreement(on, grey, obj)["on_photo_edge"], 0.9)
        self.assertLess(tl.edge_agreement(off, grey, obj)["on_photo_edge"], 0.1)


if __name__ == "__main__":
    unittest.main()

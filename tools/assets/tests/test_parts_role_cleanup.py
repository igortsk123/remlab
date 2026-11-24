"""Чистка меток ролей до покраски и мерки границ (T-20261124-64, Ш1): острова вливаются, зубцы сглаживаются по пологим рёбрам, острые рёбра и мелкое контрастное (ручки) не трогаются; мерки считают то, что просил советник.
Синтетика — плоская сетка и сгиб под 90°, без Salad и весов."""
import os
import re
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.append(os.path.join(HERE, "..", "..", "scout"))
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_parts_role_cleanup")
import parts_role_cleanup as prc  # noqa: E402

RULES = prc.load_rules()
N = 60


def grid(fold_at=None):
    """Сетка N×N клеток в плоскости z=0 (x вправо); при fold_at — правая часть x>fold_at загнута вверх под 90° (острое ребро на x=fold_at). Грани 2k, 2k+1 — клетка k=(i*N+j); центр клетки — (xs, ys)."""
    v, f, xs, ys = [], [], [], []
    for i in range(N + 1):
        for j in range(N + 1):
            x, y = i / N, j / N
            if fold_at is not None and x > fold_at:
                v.append([fold_at, y, x - fold_at])
            else:
                v.append([x, y, 0.0])
    for i in range(N):
        for j in range(N):
            k = i * (N + 1) + j
            f += [[k, k + 1, k + N + 1], [k + 1, k + N + 2, k + N + 1]]
            xs += [(i + 0.5) / N] * 2
            ys += [(j + 0.5) / N] * 2
    return np.array(v, float), np.array(f, int), np.array(xs), np.array(ys)


def jagged_roles(xs, ys, seed=1):
    """Левая половина «facade», правая «side»; граница x=0,5 рваная: каждая клетка у границы (±3 клетки) случайно та или другая."""
    rng = np.random.default_rng(seed)
    role = np.where(xs < 0.5, "facade", "side").astype(object)
    near = np.abs(xs - 0.5) < 3.0 / N
    flip = rng.random(len(xs)) < 0.5
    role[near & flip] = np.where(xs[near & flip] < 0.5, "side", "facade")
    return role.astype(str)


class Cleanup(unittest.TestCase):
    def test_smoothing_cuts_ragged_boundary(self):
        v, f, xs, ys = grid()
        eg = prc.edge_graph(v, f)
        role = jagged_roles(xs, ys)
        known = {"facade", "side"}
        before = prc.boundary_metrics(eg, role, known, RULES)
        new, rep = prc.clean_roles(eg, role, known, RULES)
        after = prc.boundary_metrics(eg, new, known, RULES)
        self.assertGreater(before["boundary_len"], after["boundary_len"] * 1.5)       # зубчатая граница стала в разы короче
        self.assertGreater(rep["faces_smoothed"], 0)
        self.assertLess(after["boundary_len"], 0.2 * before["boundary_len"])         # было 10,8 → стало ~1,5 (прямая — 1,0)
        self.assertTrue(after["ok"]["islands"])
        self.assertFalse(before["ok"]["islands"])
        self.assertTrue(set(new) <= known)                                             # новых ролей чистка не создаёт

    def test_island_merged_but_keep_roles_stay(self):
        v, f, xs, ys = grid()
        eg = prc.edge_graph(v, f)
        role = np.where(xs < 0.5, "facade", "side").astype(object)
        k = int((10 * N + 10)) * 2                                                     # клетка в левой половине: остров «side» в «facade»
        role[k:k + 2] = "side"
        k2 = int((20 * N + 40)) * 2                                                    # клетка в левой половине: «ручка» (роль из keep_roles)
        role[k2:k2 + 2] = "handles"
        role = role.astype(str)
        known = {"facade", "side", "handles"}
        m = prc.boundary_metrics(eg, role, known, RULES)
        self.assertGreaterEqual(m["islands"]["count"], 1)
        new, rep = prc.clean_roles(eg, role, known, RULES)
        self.assertEqual(set(new[k:k + 2]), {"facade"})                                # остров влит в соседа
        self.assertEqual(set(new[k2:k2 + 2]), {"handles"})                             # ручка осталась
        self.assertGreaterEqual(rep["islands_merged"], 1)

    def test_sharp_edge_boundary_untouched_and_counted(self):
        v, f, xs, ys = grid(fold_at=0.5)
        eg = prc.edge_graph(v, f)
        role = np.where(xs < 0.5, "facade", "side").astype(str)                        # граница ровно по сгибу под 90°
        known = {"facade", "side"}
        m = prc.boundary_metrics(eg, role, known, RULES)
        self.assertGreaterEqual(m["sharp_share"], 0.99)
        self.assertTrue(m["ok"]["sharp"])
        self.assertTrue(m["ok"]["islands"])
        new, rep = prc.clean_roles(eg, role, known, RULES)
        self.assertTrue((new == role).all())                                           # чистить нечего

    def test_flat_boundary_is_not_sharp(self):
        v, f, xs, ys = grid()
        eg = prc.edge_graph(v, f)
        role = np.where(xs < 0.5, "facade", "side").astype(str)
        m = prc.boundary_metrics(eg, role, {"facade", "side"}, RULES)
        self.assertEqual(m["sharp_share"], 0.0)
        self.assertFalse(m["ok"]["sharp"])

    def test_rules_intact_no_ids(self):
        self.assertIn("handles", RULES["keep_roles"])
        self.assertEqual(RULES["ragged_max"], 1.3)
        self.assertEqual(RULES["sharp_share_min"], 0.8)
        for path in (prc.RULES, prc.__file__):
            with open(path, encoding="utf-8") as fh:
                self.assertIsNone(re.search(r"\d{5,}_\d{10,}|\b\d{9,}\b", fh.read()), path)


if __name__ == "__main__":
    unittest.main()

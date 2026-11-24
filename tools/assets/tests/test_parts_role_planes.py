"""Граница частей плоскостью (T-20261124-64): склейка почти копланарных граней, снап ролей к плоскости, keep-роли и unknown не трогаем, мерки до/после. Синтетика — сетки, без Salad и весов."""
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
remlab_tmp.use("test_parts_role_planes")
import parts_role_cleanup as prc  # noqa: E402
import parts_role_planes as prp  # noqa: E402
from test_parts_role_cleanup import N, grid  # noqa: E402

PR = prp.load_rules()
CR = prc.load_rules()


def bumpy(v, amp=0.0008, seed=3):
    """Почти плоская сетка: малый шум по z (как у меша TRELLIS) — вершины сдвинуты на доли процента габарита."""
    rng = np.random.default_rng(seed)
    w = v.copy()
    w[:, 2] += rng.normal(0, amp, len(v))
    return w


class Planes(unittest.TestCase):
    def test_noisy_plane_is_one_plane_and_fold_is_two(self):
        v, f, xs, ys = grid(fold_at=0.5)
        pl = prp.merge_planes(bumpy(v), f, PR["ang_deg"], PR["tol_rel"], PR["min_share"])
        sig = np.nonzero(pl.significant)[0]
        self.assertEqual(len(sig), 2)                                                  # две стенки под 90°, не одна и не сотни
        self.assertGreater(float((pl.face_plane >= 0).mean()), 0.99)
        left = pl.face_plane[xs < 0.5]
        right = pl.face_plane[xs > 0.5]
        self.assertEqual(len(set(left.tolist())), 1)
        self.assertEqual(len(set(right.tolist())), 1)
        self.assertNotEqual(left[0], right[0])

    def test_vote_snaps_noisy_boundary_into_plane_edge(self):
        v, f, xs, ys = grid(fold_at=0.5)
        pl = prp.merge_planes(v, f, PR["ang_deg"], PR["tol_rel"], PR["min_share"])
        eg = prc.edge_graph(v, f)
        rng = np.random.default_rng(5)
        role = np.where(xs < 0.5, "facade", "side").astype(object)
        flip = rng.random(len(xs)) < 0.15                                              # 15 % граней — чужая роль, где угодно (шум меток)
        role[flip] = np.where(xs[flip] < 0.5, "side", "facade")
        role = role.astype(str)
        known = {"facade", "side"}
        new, rep = prp.plane_vote(pl.face_plane, eg["area"], role, known, PR, keep=set(CR["keep_roles"]))
        self.assertEqual(set(new[xs < 0.5]), {"facade"})
        self.assertEqual(set(new[xs > 0.5]), {"side"})
        self.assertEqual(rep["planes_voted"], 2)
        after = prc.boundary_metrics(eg, new, known, CR)
        self.assertGreaterEqual(after["sharp_share"], 0.99)                            # граница теперь ровно на сгибе
        self.assertTrue(after["ok"]["sharp"] and after["ok"]["islands"])
        self.assertLessEqual(after["ragged_ratio"], CR["ragged_max"])

    def test_keep_unknown_and_undecided_untouched(self):
        v, f, xs, ys = grid()
        pl = prp.merge_planes(v, f, PR["ang_deg"], PR["tol_rel"], PR["min_share"])
        eg = prc.edge_graph(v, f)
        role = np.full(len(f), "facade", dtype=object)
        k = 2 * (10 * N + 10)
        role[k:k + 2] = "handles"                                                      # ручка в плоскости фасада
        role[k + 10:k + 12] = "unknown"
        role = role.astype(str)
        new, rep = prp.plane_vote(pl.face_plane, eg["area"], role, {"facade", "handles"}, PR, keep=set(CR["keep_roles"]))
        self.assertEqual(set(new[k:k + 2]), {"handles"})
        self.assertEqual(set(new[k + 10:k + 12]), {"unknown"})
        half = np.where(xs < 0.5, "facade", "side").astype(str)                        # 50/50 — победителя нет, плоскость не меняется
        new2, rep2 = prp.plane_vote(pl.face_plane, eg["area"], half, {"facade", "side"}, PR, keep=set())
        self.assertTrue((new2 == half).all())
        self.assertEqual(rep2["planes_undecided"], 1)
        self.assertEqual(rep2["faces_snapped"], 0)

    def test_snap_and_clean_runs_and_creates_no_new_roles(self):
        v, f, xs, ys = grid(fold_at=0.5)
        pl = prp.merge_planes(v, f, PR["ang_deg"], PR["tol_rel"], PR["min_share"])
        eg = prc.edge_graph(v, f)
        role = np.where(xs < 0.5, "facade", "side").astype(str)
        role[(xs > 0.8) & (ys > 0.8)] = "back"                                         # кусок третьей роли, целиком внутри плоскости «side»
        new, rep = prp.snap_and_clean(eg, pl.face_plane, role, {"facade", "side", "back"}, PR, CR)
        self.assertTrue(set(new) <= {"facade", "side", "back"})
        self.assertEqual(set(new[xs > 0.5]), {"side"})                                 # «back» (менее 0,6 площади плоскости) влит в плоскость
        self.assertGreaterEqual(rep["changed_faces"], 1)

    def test_rules_intact_no_ids(self):
        self.assertEqual(PR["vote_min"], 0.6)
        for path in (prp.RULES, prp.__file__):
            with open(path, encoding="utf-8") as fh:
                self.assertIsNone(re.search(r"\d{5,}_\d{10,}|\b\d{9,}\b", fh.read()), path)


if __name__ == "__main__":
    unittest.main()

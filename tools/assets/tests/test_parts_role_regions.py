"""Роли по областям слитой части корпусной (T-20261124-64, Ш1): верх/фасад/бок/зад/корпус по панелям и сторонам (готовый ref_zone), камера лишь подтверждает; стол и мелкие части не режем; unknown числом.
Синтетика — комод и стол из параллелепипедов (как в test_parts_names_roles); GLB и Salad не нужны."""
import json
import os
import re
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scout", "salad", "parts"))
sys.path.append(os.path.join(HERE, "..", "..", "scout"))
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_parts_role_regions")
import parts_names_roles as pn  # noqa: E402
import parts_role_regions as prr  # noqa: E402
import parts_roles as pro  # noqa: E402
import part_shapes as shp  # noqa: E402,F401
from parts_vote import weld_adjacency  # noqa: E402
import parts_features as pf  # noqa: E402
from test_parts_features import box, assemble  # noqa: E402

RR = prr.load_rules()
KINDS = {0: "body", 1: "thin"}


def chest():
    """Комод: ОДНА слитая крупная часть «Drawer» (корпус+фасад+бока+зад) и маленькая «ножка», оторванная от пола."""
    v, f, part = assemble([box(0, 0.5, 0, 1.0, 0.8, 0.5, n=16), box(0.4, 0.3, 0.0, 0.05, 0.15, 0.05, n=4)])
    kind = np.zeros(len(f), dtype=np.int8)
    return v, f, part, kind


def feats_for(v, f, part, kind, az):
    return pf.part_features(part, v, f, kind, KINDS, adj=weld_adjacency(v, f), contact_eps=0.03, cam_az=az)


def face_normals_z(v, f):
    """+1 — грань лежит на плоскости +z (перёд коробки), −1 — на плоскости −z (зад), 0 — остальные."""
    t = v[f]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return np.where(np.abs(n[:, 2]) > 0.9, np.sign(t.mean(1)[:, 2]), 0.0)


def run(role, az, names=None):
    v, f, part, kind = chest()
    ft = feats_for(v, f, part, kind, az)
    res = prr.build_roles(v, f, part, names or ["Drawer", "Leg"], role, {"legs"}, {}, az, feats=ft)
    return v, f, res


class Regions(unittest.TestCase):
    def test_facade_side_back_top_by_geometry_camera_confirms(self):
        v, f, res = run("комод", 0.0)
        d = res["doc"]
        big = d["parts"][0]
        self.assertEqual(big["source"], "region")                              # мост ничего не поставил (unknown), режет области
        self.assertEqual(big["bridge_role"], "unknown")
        roles = {p["role"] for p in big["pieces"]}
        self.assertTrue({"facade", "back", "side", "top"} <= roles, roles)      # бок — отдельная роль, не фасад и не зад
        nz = face_normals_z(v, f)
        fr = res["face_role"]
        n = 6 * 16 * 16 * 2                                                    # грани корпуса идут первыми (часть 0), ножка — после
        self.assertEqual(set(fr[:n][nz[:n] > 0]), {"facade"})
        self.assertEqual(set(fr[:n][nz[:n] < 0]), {"back"})
        self.assertEqual(big["facade"]["camera"], "agree")
        fac = [p for p in big["pieces"] if p["role"] == "facade"][0]
        self.assertAlmostEqual(fac["conf"], RR["conf"]["facade_camera_agree"], places=3)
        sides = [p for p in big["pieces"] if p["role"] == "side"]
        self.assertAlmostEqual(sides[0]["conf"], RR["conf"]["side"], places=3)

    def test_camera_decides_front_back_tie(self):
        """У ровной коробки перёд и зад равны по площади — перёд решает камера: с другой стороны фасад и зад меняются местами; бока остаются боками."""
        v0, f0, r0 = run("комод", 0.0)
        v1, f1, r1 = run("комод", 180.0)
        n = 6 * 16 * 16 * 2
        nz = face_normals_z(v0, f0)
        self.assertEqual(set(r0["face_role"][:n][nz[:n] > 0]), {"facade"})
        self.assertEqual(set(r1["face_role"][:n][nz[:n] > 0]), {"back"})
        self.assertEqual(set(r1["face_role"][:n][nz[:n] < 0]), {"facade"})
        nx = np.abs(v0[f0][:n].mean(1)[:, 0]) > 0.49
        self.assertEqual(set(r0["face_role"][:n][nx]), {"side"})
        self.assertEqual(set(r1["face_role"][:n][nx]), {"side"})

    def test_no_camera_tie_is_unsure_and_counted(self):
        """Камеры нет, перёд и зад равны: фасад выбран неуверенно (conf ниже min_known) — площадь честно не считается «с ролью», флаг в файле."""
        _, _, res = run("комод", None)
        big = res["doc"]["parts"][0]
        self.assertIn("ambiguous_side", big["region_flags"])
        self.assertEqual(big["facade"]["camera"], "none")
        fac = [p for p in big["pieces"] if p["role"] == "facade"][0]
        self.assertLess(fac["conf"], RR["conf"]["min_known"])
        s = res["doc"]["summary"]
        self.assertLess(s["area_with_role"], 0.9)
        self.assertGreater(s["area_unknown"], 0.0)                              # не прячем

    def test_table_and_small_parts_are_not_cut(self):
        _, _, tbl = run("стол обеденный", 0.0)
        self.assertNotIn("region", tbl["doc"]["summary"]["area_by_source"])     # стол: резку «плита | ножки» даёт мост (R-PART-ROLES-GEOM-03), здесь не режем
        _, _, ch = run("комод", 0.0)
        leg = ch["doc"]["parts"][1]
        self.assertEqual(leg["source"], "unknown")                              # мелкая «Leg» без роли остаётся unknown, корпусом не подменяется
        self.assertEqual(leg["pieces"][0]["role"], "unknown")
        self.assertIn("unknown", ch["doc"]["summary"]["area_by_source"])

    def test_handles_decide_front_back_tie_before_camera(self):
        """Ручки — признак фасада: сторона, куда смотрят ручки, = фасад, даже когда камера смотрит с другой стороны; ambiguous снимается, conf не ниже порога."""
        v, f, part, kind = chest()
        area = prr._face_areas(v, f)
        cen = prr._face_centers(v, f)
        side, pid, dirs = prr.mesh_sides(v, f, part, 0.0)
        n = 6 * 16 * 16 * 2
        idx = np.arange(n)
        mid = 0.5 * (v.min(0) + v.max(0))
        hidx = np.nonzero(face_normals_z(v, f)[:n] > 0)[0][:200]                # «ручки» — грани на передней плоскости +z
        hf = prr.handle_fractions(area, prr._face_normals(v, f), cen, mid, dirs, hidx)
        self.assertGreater(hf[-1], 0.9)                                         # ручки смотрят на сторону «перёд» (+z при az 0)
        sp = prr.split_part(idx, area, side, pid, dirs, RR, 180.0, hf)         # камера с обратной стороны
        self.assertEqual(sp["facade"]["by_handles"], True)
        self.assertFalse(sp["facade"]["ambiguous"])
        self.assertEqual(sp["facade"]["camera"], "disagree")
        self.assertIn("camera_disagrees", sp["flags"])
        nz = face_normals_z(v, f)
        self.assertEqual(set(sp["labels"][nz[:n] > 0]), {"facade"})             # ручки перевесили камеру
        self.assertEqual(set(sp["labels"][nz[:n] < 0]), {"back"})
        sp0 = prr.split_part(idx, area, side, pid, dirs, RR, None, hf)         # без камеры ручки сами решают и уверенность выше порога
        self.assertFalse(sp0["facade"]["ambiguous"])
        self.assertGreaterEqual(float(sp0["conf"][nz[:n] > 0].min()), RR["conf"]["min_known"])
        self.assertEqual(prr.handle_fractions(area, prr._face_normals(v, f), cen, mid, dirs, np.array([], dtype=int)), {})

    def test_which_parts_are_cut(self):
        """Режем: слитую крупную без роли; плоскую панель ≥ panel_min_area_share без роли; общую роль body моста у плоской панели (refine_bridge_body). Мелкую не-плиту, ножки и роли моста — нет."""
        P = RR["part"]
        big = {"area_share": 0.5, "plate_horizontal": 0.0, "plate_vertical": 0.0}
        door = {"area_share": 0.03, "plate_horizontal": 0.0, "plate_vertical": 0.9}
        leg = {"area_share": 0.05, "plate_horizontal": 0.0, "plate_vertical": 0.1}
        unk = {"role": "unknown", "unknown_reason": "name_geometry"}
        self.assertTrue(prr._cut_part(unk, big, P))
        self.assertTrue(prr._cut_part(unk, door, P))
        self.assertFalse(prr._cut_part(unk, leg, P))                              # «Leg» без роли — корпусом не подменяем
        self.assertFalse(prr._cut_part({"role": "unknown", "unknown_reason": "no_channel"}, big, P))
        self.assertTrue(prr._cut_part({"role": "body"}, door, P))                  # панель корпуса с общей ролью → бок/зад/фасад
        self.assertFalse(prr._cut_part({"role": "body"}, big, P))                  # не плита — не трогаем
        self.assertFalse(prr._cut_part({"role": "legs"}, door, P))
        self.assertFalse(prr._cut_part({"role": "body"}, door, dict(P, refine_bridge_body=False)))

    def test_faces_file_matches_pieces(self):
        v, f, res = run("комод", 0.0)
        self.assertEqual(len(res["face_role"]), len(f))
        pieces = {p["piece"]: p["role"] for e in res["doc"]["parts"] for p in e["pieces"]}
        for k, role in pieces.items():
            self.assertEqual(set(res["face_role"][res["face_piece"] == k]), {role})
        self.assertAlmostEqual(sum(p["area_share"] for e in res["doc"]["parts"] for p in e["pieces"]), 1.0, places=2)

    def test_rules_intact_and_no_product_ids(self):
        for need in ("top", "facade", "side", "back", "body"):
            self.assertIn(need, pro.load_rules()["roles"])
        self.assertEqual(RR["groups"], ["case"])                                # режем только корпусную
        self.assertEqual(RR["metric"]["min"], 0.9)
        for path in (prr.RULES, prr.__file__):
            txt = open(path, encoding="utf-8").read()
            self.assertIsNone(re.search(r"\d{5,}_\d{10,}|\b\d{9,}\b", txt), path)    # ID товаров в код/правила не попадают


if __name__ == "__main__":
    unittest.main()

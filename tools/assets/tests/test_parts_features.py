"""Признаки частей (parts_features) и роли (parts_roles) на синтетике: стол, комод с ручкой, люстра; числа — доли габарита и площади."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import part_shapes as shp  # noqa: E402
import parts_features as pf  # noqa: E402
import parts_roles as pr  # noqa: E402
from parts_vote import weld_adjacency  # noqa: E402


def box(cx, cy, cz, sx, sy, sz, n=6):
    """Параллелепипед, грани разбиты на n×n квадратов (по 2 треугольника)."""
    v, f = [], []
    for a, b, c in ((0, 1, 2), (1, 2, 0), (2, 0, 1)):
        for sgn in (-1, 1):
            base = len(v)
            for i in range(n + 1):
                for j in range(n + 1):
                    p = [0.0, 0.0, 0.0]
                    p[a], p[b], p[c] = sgn * 0.5, i / n - 0.5, j / n - 0.5
                    v.append(p)
            for i in range(n):
                for j in range(n):
                    k = base + i * (n + 1) + j
                    f += [[k, k + 1, k + n + 1], [k + 1, k + n + 2, k + n + 1]]
    return np.array(v) * np.array([sx, sy, sz]) + np.array([cx, cy, cz]), np.array(f)


def assemble(boxes):
    vs, fs, part, off = [], [], [], 0
    for i, (v, f) in enumerate(boxes):
        vs.append(v)
        fs.append(f + off)
        part += [i] * len(f)
        off += len(v)
    return np.vstack(vs), np.vstack(fs), np.array(part)


def table(lift=0.0):
    """Плита наверху (часть 0) и четыре прута (1–4); lift — на сколько ножки оторваны от пола."""
    top = box(0, 1.0, 0, 1.0, 0.06, 1.0, n=40)
    legs = [box(x, 0.485 + lift / 2, z, 0.05, 0.97 - lift, 0.05, n=4) for x in (-0.45, 0.45) for z in (-0.45, 0.45)]
    return assemble([top] + legs)


def feats(v, f, part, kinds, **kw):
    kind = np.zeros(len(f), dtype=np.int8)
    return pf.part_features(part, v, f, kind, kinds, adj=weld_adjacency(v, f), contact_eps=0.03, **kw)


class Features(unittest.TestCase):
    def setUp(self):
        self.v, self.f, self.part = table()
        self.kinds = {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}

    def test_top_and_legs(self):
        r = feats(self.v, self.f, self.part, self.kinds)
        self.assertTrue(r[0]["is_largest"])
        self.assertGreaterEqual(r[0]["up_q10"], 0.9)
        self.assertTrue(r[0]["obb"]["slab"])
        self.assertGreaterEqual(r[0]["plate_horizontal"], 0.6)
        for p in (1, 2, 3, 4):
            self.assertLess(r[p]["up_min"], 0.04)
            self.assertTrue(r[p]["supports_body"])                          # касается пола и плиты, плита от пола оторвана
            self.assertEqual(r[p]["symmetry_group"], 4)
            self.assertLessEqual(r[p]["obb"]["thin_ratio"], 0.1)
        self.assertFalse(r[0]["supports_body"])

    def test_scale_and_area_weighting(self):
        a = feats(self.v, self.f, self.part, self.kinds)
        b = feats(self.v * 37.0, self.f, self.part, self.kinds)
        for p in a:
            for k in ("area_share", "up_q10", "up_q90"):
                self.assertAlmostEqual(a[p][k], b[p][k], places=3)

    def test_colour_only_report(self):
        lab = np.zeros((len(self.f), 3))
        lab[self.part == 1] = [30, 40, 0]
        r = feats(self.v, self.f, self.part, self.kinds, lab=lab)
        self.assertAlmostEqual(r[1]["delta_e_main"], 50.0, places=1)

    def test_front_from_camera(self):
        v = self.v.copy()
        v[self.f[self.part == 1]] += np.array([0, 0, 0.3])
        self.assertIsNone(feats(v, self.f, self.part, self.kinds)[1]["front"])           # без камеры фронта нет
        r = feats(v, self.f, self.part, self.kinds, cam_az=0.0)                             # az=0: камера на +Z
        rb = feats(v, self.f, self.part, self.kinds, cam_az=180.0)
        self.assertGreater(r[1]["front"], r[3]["front"])
        self.assertAlmostEqual(r[1]["front"], -rb[1]["front"], places=2)
        r90 = feats(v, self.f, self.part, self.kinds, cam_az=90.0)                          # камера на +X
        self.assertGreater(r90[3]["front"], 0.5)
        self.assertLess(r90[1]["front"], -0.5)


class Roles(unittest.TestCase):
    rules = pr.load_rules()

    def test_table_legs_and_top(self):
        v, f, part = table()
        kinds = {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}
        ft = feats(v, f, part, kinds)
        r = pr.assign_roles(ft, self.rules, "столик", {"legs"})
        self.assertEqual(r[0]["role"], "top")
        for p in (1, 2, 3, 4):
            self.assertEqual(r[p]["role"], "legs")
        self.assertEqual(pr.known_role_area_share(ft, r), 1.0)

    def test_plinth_feet_are_not_support(self):
        body = box(0, 0.4, 0, 1.0, 0.8, 0.5, n=12)                          # корпус стоит на полу сам (цоколь): мелочи под ним корпус от пола не отрывают
        feet = [box(x, 0.02, z, 0.04, 0.04, 0.04, n=3) for x in (-0.45, 0.45) for z in (-0.2, 0.2)]
        v, f, part = assemble([body] + feet)
        r = pr.assign_roles(feats(v, f, part, {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}), self.rules, "комод", {"legs"})
        for p in (1, 2, 3, 4):
            self.assertNotEqual(r[p]["role"], "legs")

    def test_unknown_type_gets_any_group(self):
        v, f, part = self._chest()
        kinds = {0: "body", 1: "body", 2: "thin", 3: "thin", 4: "thin", 5: "thin"}
        r = pr.assign_roles(feats(v, f, part, kinds), self.rules, None, set())
        self.assertEqual(r[2]["role"], "legs")                              # группа any: ножки по опоре
        self.assertEqual(r[0]["role"], "body")
        self.assertEqual(r[1]["role"], "body")                              # без типа ручку не выделяем — всё объёмное body

    def test_table_non_largest_body_is_unknown(self):
        v, f, part = assemble([box(0, 1.0, 0, 1.0, 0.06, 1.0, n=20), box(0, 0.4, 0, 0.4, 0.8, 0.4, n=10)])   # плита и толстая тумба
        r = pr.assign_roles(feats(v, f, part, {0: "body", 1: "body"}), self.rules, "стол обеденный", {"legs"})
        self.assertEqual(r[0]["role"], "top")
        self.assertEqual(r[1]["role"], "unknown")                           # у стола body нет вовсе: тумба — материал каталог не называет
        self.assertEqual(r[1]["unknown_reason"], "body_scope")

    def test_thick_plinth_under_sofa_is_unclear(self):
        body = box(0, 0.6, 0, 1.0, 0.8, 0.6, n=24)                          # главная часть над полом
        plinth = box(0, 0.1, 0, 0.45, 0.2, 0.3, n=12)                        # толстый цоколь на полу — ни ножки, ни обивка наверняка
        v, f, part = assemble([body, plinth])
        lab = np.zeros((len(f), 3))
        lab[part == 1] = [30, 0, 0]                                         # цоколь заметно темнее обивки — вето снимает body
        r = pr.assign_roles(feats(v, f, part, {0: "body", 1: "body"}, lab=lab), self.rules, "диван", {"legs"})
        self.assertEqual(r[0]["role"], "body")
        self.assertEqual(r[1]["role"], "unknown")
        self.assertEqual(r[1]["unknown_reason"], "support_unclear")
        r2 = pr.assign_roles(feats(v, f, part, {0: "body", 1: "body"}, lab=np.zeros((len(f), 3))), self.rules, "диван", {"legs"})
        self.assertEqual(r2[1]["role"], "body")                             # тот же цвет — повода сомневаться нет

    def test_repeat_group_gets_one_role(self):
        body = box(0, 0.55, 0, 1.0, 0.9, 0.6, n=24)                         # главная часть над полом (низ на 0.1)
        a = box(-0.35, 0.05, 0, 0.3, 0.1, 0.4, n=10)                        # два одинаковых нижних модуля; один стоит на полу…
        b = box(0.35, 0.13, 0, 0.3, 0.1, 0.4, n=10)                         # …второй приподнят на 0.08 (пол «чуть хуже»)
        v, f, part = assemble([body, a, b])
        kinds = {0: "body", 1: "body", 2: "body"}
        ft = feats(v, f, part, kinds)
        self.assertEqual(ft[1]["symmetry_group"], 2)                        # признаки видят повтор
        self.assertNotEqual(ft[1]["supports_body"], ft[2]["supports_body"])   # а опорой по полу они расходятся
        r = pr.assign_roles(ft, self.rules, "диван", {"legs"})
        self.assertEqual(r[1]["role"], r[2]["role"])                        # одинаковые части — одна роль
        self.assertEqual(r[1]["unknown_reason"], "group_disagree")

    def test_group_ignores_unreliable_members(self):
        v, f, part = table()
        kinds = {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}
        ft = feats(v, f, part, kinds)
        ft[4]["agree"], ft[4]["seen"] = 0.1, 0.5                            # одна ножка нечитаема кадрами — группу из-за неё не рушим
        r = pr.assign_roles(ft, self.rules, "столик", {"legs"})
        self.assertEqual(r[4]["unknown_reason"], "unreliable")
        for p in (1, 2, 3):
            self.assertEqual(r[p]["role"], "legs")

    def test_merged_legs_with_stretchers_are_legs(self):
        top = box(0, 1.0, 0, 1.0, 0.06, 1.0, n=40)
        legs = [box(x, 0.485, z, 0.05, 0.97, 0.05, n=4) for x in (-0.45, 0.45) for z in (-0.45, 0.45)]
        bar = box(0, 0.5, -0.45, 0.9, 0.04, 0.04, n=6)                      # царга между ножками: одна часть «ножки+царга»
        v, f, part = assemble([top, legs[0], legs[1], legs[2], legs[3], bar])
        part[part >= 2] = np.where(part[part >= 2] == 5, 1, part[part >= 2])
        r = pr.assign_roles(feats(v, f, part, {0: "body", 1: "mid", 2: "thin", 3: "thin", 4: "thin"}), self.rules, "столик", {"legs"})
        self.assertEqual(r[1]["role"], "legs")

    def test_chandelier_without_channels(self):
        v, f, part = assemble([box(0, 0.7, 0, 0.6, 0.3, 0.6, n=8), box(0, 0.3, 0, 0.5, 0.4, 0.5, n=8)])
        r = pr.assign_roles(feats(v, f, part, {0: "body", 1: "body"}), self.rules, "люстра", {"shade"})
        for p in (0, 1):
            self.assertEqual(r[p]["role"], "unknown")
            self.assertEqual(r[p]["unknown_reason"], "no_channel")

    def _chest(self):
        body = box(0, 0.6, 0, 1.0, 0.8, 0.5, n=12)
        handle = box(0, 0.6, 0.27, 0.14, 0.05, 0.03, n=3)
        legs = [box(x, 0.1, z, 0.04, 0.2, 0.04, n=3) for x in (-0.45, 0.45) for z in (-0.2, 0.2)]
        return assemble([body, handle] + legs)

    def test_handle_needs_front(self):
        v, f, part = self._chest()
        kinds = {0: "body", 1: "body", 2: "thin", 3: "thin", 4: "thin", 5: "thin"}
        r = pr.assign_roles(feats(v, f, part, kinds), self.rules, "комод", {"legs", "handles"})
        self.assertEqual(r[1]["role"], "unknown")                           # камеры нет: ручку от «просто малой части» не отличить
        self.assertEqual(r[1]["unknown_reason"], "no_front")
        for p in (2, 3, 4, 5):
            self.assertEqual(r[p]["role"], "legs")

    def test_handle_not_without_channel(self):
        v, f, part = self._chest()
        kinds = {0: "body", 1: "body", 2: "thin", 3: "thin", 4: "thin", 5: "thin"}
        r = pr.assign_roles(feats(v, f, part, kinds, cam_az=0.0), self.rules, "комод", {"legs"})
        self.assertNotEqual(r[1]["role"], "handles")                        # в каталоге нет материала ручек — роль не вводим

    def test_tiny_and_untrusted_abstain(self):
        v, f, part = table()
        kinds = {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}
        ft = feats(v, f, part, kinds)
        ft[1]["agree"], ft[1]["seen"] = 0.5, 0.9
        r = pr.assign_roles(ft, self.rules, "столик", {"legs"})
        self.assertEqual(r[1]["unknown_reason"], "unreliable")              # роль не увереннее разбиения
        self.assertEqual(r[2]["role"], "legs")


class RulesFile(unittest.TestCase):
    def test_no_product_ids_and_known_types(self):
        import json
        import re
        txt = open(pr.RULES, encoding="utf-8").read()
        self.assertIsNone(re.search(r"\d{15,}", txt))
        classes = json.load(open(pr.CLASSES, encoding="utf-8"))
        rules = pr.load_rules()
        self.assertEqual(set(rules["groups"]) - {"any"}, set(classes["groups"]))
        for g in rules["groups"].values():
            for role in g["roles"]:
                self.assertIn(role, rules["roles"])
        self.assertIsNone(rules["roles"]["glass_mirror"]["material_channel"])
        for g in rules["groups"].values():
            self.assertNotIn("glass_mirror", g["roles"])                    # стекло/металл по положению не выводится

    def test_group_by_type(self):
        self.assertEqual(pr.group_of("комод"), "case")
        self.assertEqual(pr.group_of("диван"), "seating")
        self.assertEqual(pr.group_of("журнальный стол"), "table")             # по общему слову «стол»
        self.assertEqual(pr.group_of("торшер"), "lamp")
        self.assertEqual(pr.group_of(None), "any")
        self.assertEqual(pr.group_of("что-то новое"), "any")

    def test_colour_not_a_condition(self):
        txt = open(pr.RULES, encoding="utf-8").read()
        self.assertEqual(txt.count('"f": "delta_e_main"'), 0)


if __name__ == "__main__":
    unittest.main()

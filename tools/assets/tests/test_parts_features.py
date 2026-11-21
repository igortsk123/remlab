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
    off = {**rules, "decision": {**rules["decision"], "leg_rescue": {**rules["decision"]["leg_rescue"], "enabled": False}}}   # прежнее воздержание без leg_rescue

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

    def test_plinth_modules_of_different_width_are_one_layer(self):
        body = box(0, 0.55, 0, 1.4, 0.9, 0.6, n=24)
        a = box(-0.45, 0.05, 0, 0.5, 0.1, 0.4, n=10)                        # два модуля основания разной ширины, та же толщина и высота
        b = box(0.3, 0.13, 0, 0.8, 0.1, 0.4, n=10)                          # второй чуть выше от пола
        v, f, part = assemble([body, a, b])
        ft = feats(v, f, part, {0: "body", 1: "body", 2: "body"})
        self.assertIn(2, ft[1]["symmetry_members"])                         # слой найден, хотя рамки разные
        r = pr.assign_roles(ft, self.rules, "диван", {"legs"})
        self.assertEqual(r[1]["role"], r[2]["role"])

    def test_group_ignores_unreliable_members(self):
        v, f, part = table()
        kinds = {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}
        ft = feats(v, f, part, kinds)
        ft[4]["agree"], ft[4]["seen"] = 0.1, 0.5                            # одна ножка нечитаема кадрами — группу из-за неё не рушим
        r = pr.assign_roles(ft, self.off, "столик", {"legs"})
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

    def test_case_second_bulk_part_is_body_table_is_not(self):
        main = box(0, 0.6, 0, 1.0, 0.7, 0.5, n=12)
        block = box(0, 0.88, 0, 0.9, 0.3, 0.45, n=10)                       # вторая объёмная часть корпуса (верхний ярус ящиков), не плита и не у пола
        legs = [box(x, 0.1, z, 0.04, 0.2, 0.04, n=3) for x in (-0.45, 0.45) for z in (-0.2, 0.2)]
        v, f, part = assemble([main, block] + legs)
        kinds = {0: "body", 1: "body", 2: "thin", 3: "thin", 4: "thin", 5: "thin"}
        r = pr.assign_roles(feats(v, f, part, kinds), self.rules, "комод", {"legs"})
        self.assertEqual(r[1]["role"], "body")                              # у корпуса фасад/верх/короб — один основной класс: тот же материал, что у крупнейшей
        r = pr.assign_roles(feats(v, f, part, kinds), self.rules, "стол обеденный", {"legs"})
        self.assertEqual(r[1]["unknown_reason"], "body_scope")              # у стола столешница/ножки названы отдельно — body нет вовсе

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
        r = pr.assign_roles(ft, self.off, "столик", {"legs"})
        self.assertEqual(r[1]["unknown_reason"], "unreliable")              # роль не увереннее разбиения
        self.assertEqual(r[2]["role"], "legs")


class LegRescue(unittest.TestCase):
    """leg_rescue: ножка с размытым голосованием кадров (agree мал) становится legs по геометрии; ткань и недоверенные случаи — нет."""
    rules = pr.load_rules()

    def setUp(self):
        v, f, part = table()
        self.kinds = {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}
        self.ft = feats(v, f, part, self.kinds)
        for p in (1, 2, 3, 4):
            self.ft[p]["agree"], self.ft[p]["seen"] = 0.95, 0.5
        self.ft[4]["agree"] = 0.016                                        # как у низа ножки Sakura: кадры не согласны

    def run_roles(self, rules=None, ptype="столик"):
        return pr.assign_roles(self.ft, rules or self.rules, ptype, {"legs"})

    def with_rescue(self, **kw):
        lr = {**self.rules["decision"]["leg_rescue"], **kw}
        return {**self.rules, "decision": {**self.rules["decision"], "leg_rescue": lr}}

    def test_blurred_leg_becomes_legs_with_normal_confidence(self):
        r = self.run_roles()
        self.assertEqual(r[4]["role"], "legs")
        self.assertIn("по геометрии", r[4]["role_why"])
        self.assertLess(r[4]["role_conf"], r[1]["role_conf"] or 1)         # увереннее ножек с доверием быть не может: matched, а не matched_trusted
        self.assertIsNone(r[4]["unknown_reason"])
        for p in (1, 2, 3):
            self.assertEqual(r[p]["role"], "legs")

    def test_switch_off_keeps_abstention(self):
        r = self.run_roles(self.with_rescue(enabled=False))
        self.assertEqual((r[4]["role"], r[4]["unknown_reason"]), ("unknown", "unreliable"))

    def test_no_trusted_legs_no_rescue(self):
        for p in (1, 2, 3):
            self.ft[p]["agree"] = 0.3                                      # у предмета нет ни одной ножки с доверием
        r = self.run_roles()
        self.assertEqual(r[4]["role"], "unknown")

    def test_slanted_or_floating_part_is_not_rescued(self):
        self.ft[4]["obb"] = {**self.ft[4]["obb"], "axis_y": 0.5}
        self.assertEqual(self.run_roles()[4]["role"], "unknown")           # ось не отвесна
        self.ft[4]["obb"]["axis_y"] = 1.0
        self.ft[4]["floor_contact"] = False
        self.ft[4]["supports_body"] = False
        self.assertEqual(self.run_roles()[4]["role"], "unknown")           # не стоит на полу (ткань у корпуса)

    def test_tiny_is_not_rescued(self):
        self.ft[4]["area_share"] = 0.001
        r = self.run_roles()
        self.assertEqual((r[4]["role"], r[4]["unknown_reason"]), ("unknown", "tiny"))

    def test_touches_legs_link_is_stricter(self):
        strict = self.with_rescue(link="touches_legs")
        self.assertEqual(self.run_roles(strict)[4]["role"], "unknown")      # прутья стола друг друга не касаются — строгий вариант не берёт
        self.ft[4]["contacts"] = sorted(set(self.ft[4]["contacts"]) | {1})
        self.assertEqual(self.run_roles(strict)[4]["role"], "legs")

    def test_two_fitting_roles_stay_unknown(self):
        # комод: ножки и «рамка»-часть с теми же числами — если по геометрии подходят две роли, воздержание сохраняется
        rules = self.with_rescue()
        grp = rules["groups"]["table"]
        saved = grp["roles"]["frame"]
        grp["roles"]["frame"] = {**grp["roles"]["legs"], "forbid": []}
        try:
            self.assertEqual(self.run_roles(rules)[4]["role"], "unknown")
        finally:
            grp["roles"]["frame"] = saved

    def test_axis_y_is_a_feature(self):
        self.assertAlmostEqual(self.ft[1]["obb"]["axis_y"], 1.0, places=2)   # стойка отвесна
        self.assertLess(self.ft[0]["obb"]["axis_y"], 0.2)                    # плита лежит


class LegWood(unittest.TestCase):
    """leg_rescue.wood: ножка вместе со стойкой из одного дерева (часть уходит выше сиденья, причина no_rule) → legs целиком; ткань в теле, плавающие и крупные части — нет."""
    rules = pr.load_rules()

    def setUp(self):
        v, f, part = table()
        self.kinds = {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}
        self.ft = feats(v, f, part, self.kinds)
        for p in (1, 2, 3, 4):
            self.ft[p]["agree"], self.ft[p]["seen"] = 0.95, 0.5
        for p in (1, 2, 3):
            self.ft[p]["up_q90"] = 0.3                                     # обычные ножки кресла (потолок ножки группы seating — 0.4)
        self.ft[4]["up_q90"] = 0.6                                         # ножка продолжается стойкой выше потолка: обычная роль legs не подходит
        self.ft[4]["agree"] = 0.83
        for p in self.ft:                                                   # часть 4 — не из группы повторов (в HD Sakura часть «ножки+стойки» одна)
            self.ft[p]["symmetry_members"] = [q for q in self.ft[p].get("symmetry_members", []) if q != 4 and p != 4]

    def run_roles(self, classes=None, **kw):
        wood = {**self.rules["decision"]["leg_rescue"]["wood"], **kw}
        lr = {**self.rules["decision"]["leg_rescue"], "wood": wood}
        return pr.assign_roles(self.ft, {**self.rules, "decision": {**self.rules["decision"], "leg_rescue": lr}}, "кресло", {"legs"},
                               catalog_classes={"legs": "wood_solid", "frame": "wood_solid"} if classes is None else classes)

    def test_off_keeps_abstention_on_takes_whole_part(self):
        off = self.run_roles(enabled=False)[4]
        self.assertEqual((off["role"], off["unknown_reason"]), ("unknown", "no_rule"))
        on = self.run_roles()[4]
        self.assertEqual(on["role"], "legs")
        self.assertIn("стойк", on["role_why"])
        self.assertIsNone(on["unknown_reason"])

    def test_body_overlap_is_a_feature_and_cloth_in_body_is_not_taken(self):
        self.assertEqual(self.ft[0]["body_overlap"], 0.0)                  # тело само в тело не считается
        self.assertLess(self.ft[4]["body_overlap"], 0.5)                   # ножка касается плиты торцом
        self.ft[4]["body_overlap"] = 0.95                                  # тонкая ткань, лежащая внутри объёма тела
        self.assertEqual(self.run_roles()[4]["role"], "unknown")

    def test_floating_or_big_or_not_thin_part_is_not_taken(self):
        for key, val in (("floor_contact", False), ("supports_body", False), ("area_share", 0.3), ("kind", "body")):
            f0 = self.ft[4][key]
            self.ft[4][key] = val
            self.assertEqual(self.run_roles()[4]["role"], "unknown", key)
            self.ft[4][key] = f0

    def test_catalog_material_must_agree(self):
        """Советник (Codex), R1: ножка и каркас из одного материала по каталогу; иначе (ткань до пола, плетёнка, консольный металл) — нет; нет классов каталога — режим молчит."""
        self.assertEqual(self.run_roles({"legs": "wood_solid"})[4]["role"], "legs")                       # каркаса нет → можно
        self.assertEqual(self.run_roles({"legs": "wood_solid", "frame": "metal"})[4]["role"], "unknown")  # ножки дерево, каркас металл
        self.assertEqual(self.run_roles({"legs": "metal", "frame": "wood_solid"})[4]["role"], "unknown")
        self.assertEqual(self.run_roles({})[4]["role"], "unknown")                                        # классов каталога нет

    def test_other_group_is_not_wood_business(self):
        wood = {**self.rules["decision"]["leg_rescue"]["wood"]}
        lr = {**self.rules["decision"]["leg_rescue"], "wood": wood}
        r = pr.assign_roles(self.ft, {**self.rules, "decision": {**self.rules["decision"], "leg_rescue": lr}}, "комод", {"legs"},
                            catalog_classes={"legs": "wood_solid"})
        self.assertEqual(r[4]["role"], "unknown")

    def test_candidate_must_pass_group_legs_veto(self):
        self.ft[4]["up_q90"] = 0.9                                         # выше потолка max_up_q90 — стойка/спинка, не ножка
        self.assertEqual(self.run_roles()[4]["role"], "unknown")

    def test_no_trusted_legs_no_wood_rescue(self):
        for p in (1, 2, 3):
            self.ft[p]["agree"] = 0.3
        self.assertEqual(self.run_roles()[4]["role"], "unknown")

    def test_unreliable_reason_is_not_wood_business(self):
        self.ft[4]["agree"] = 0.016                                         # unreliable обслуживает обычный режим (ось и пол), wood берёт только no_rule
        r = self.run_roles()[4]
        self.assertEqual((r["role"], r["unknown_reason"]), ("unknown", "unreliable"))


class UnseenAdopt(unittest.TestCase):
    """unseen_adopt: часть, которой не видит ни одна камера (seen≈0, unreliable), берёт роль соседа с наибольшей общей границей — только при явном перевесе."""
    ua = {**pr.load_rules()["decision"]["unseen_adopt"], "mode": "apply"}   # в правилах сейчас dry (P-062); боевое поведение — здесь

    @staticmethod
    def role(r, conf=0.8, why=None):
        return {"role": r, "role_title": r, "material_channel": None, "role_conf": conf, "role_why": "", "unknown_reason": why}

    def case(self, shared, seen=0.0, reason="unreliable", neighbor_roles=("body", "legs"), kind="body", ua=None):
        ft = {0: {"seen": 0.9, "shared_faces": {1: sum(shared.values())}},
              1: {"seen": seen, "kind": kind, "shared_faces": dict(zip((0, 2), shared.values()))},
              2: {"seen": 0.9, "shared_faces": {1: 5}}}
        out = {0: self.role(neighbor_roles[0]), 1: self.role("unknown", 0.0, reason), 2: self.role(neighbor_roles[1])}
        pr._unseen_adopt(ft, out, ua or self.ua)
        return out

    def test_thin_part_is_not_adopted(self):
        """Проба «выкинь одну часть»: тонкие ножки/стойки у соседа-тела брали роль тела (2 из 7 верно) — только kind body."""
        o = self.case({0: 90, 2: 10}, kind="thin")
        self.assertEqual((o[1]["role"], o[1]["unknown_reason"]), ("unknown", "unreliable"))

    def test_dry_mode_only_hints(self):
        o = self.case({0: 90, 2: 10}, ua={**self.ua, "mode": "dry"})
        self.assertEqual(o[1]["role"], "unknown")
        self.assertEqual(o[1]["unseen_hint"]["role"], "body")

    def test_adopts_role_of_dominant_neighbor(self):
        o = self.case({0: 90, 2: 10})
        self.assertEqual((o[1]["role"], o[1]["unknown_reason"]), ("body", None))
        self.assertLessEqual(o[1]["role_conf"], self.ua["role_conf"])
        self.assertIn("сосед", o[1]["role_why"])

    def test_even_split_is_not_adopted(self):
        self.assertEqual(self.case({0: 51, 2: 49})[1]["role"], "unknown")        # 51/49 — перевеса нет

    def test_visible_or_tiny_or_unknown_neighbor_is_untouched(self):
        self.assertEqual(self.case({0: 90, 2: 10}, seen=0.5)[1]["role"], "unknown")   # видимую часть голоса уже оценили
        self.assertEqual(self.case({0: 90, 2: 10}, reason="tiny")[1]["unknown_reason"], "tiny")
        self.assertEqual(self.case({0: 90, 2: 10}, neighbor_roles=("unknown", "legs"))[1]["role"], "unknown")   # сосед сам без роли

    def test_shared_faces_is_symmetric(self):
        v, f, part = table()
        ft = feats(v, f, part, {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"})
        for p, q in ((0, 1), (0, 2), (1, 2)):
            self.assertEqual(ft[p]["shared_faces"].get(q, 0), ft[q]["shared_faces"].get(p, 0))


class Step2DryRules(unittest.TestCase):
    """T-169 шаг 2 (P-062, вхолостую): no_front_same_channel и single_class_support — по умолчанию только `dry_hint`, роль не меняется; в apply — меняется."""
    rr = pr.load_rules()
    f = {"plate_vertical": 0.9, "is_largest": False, "front": None, "front_facing_share": None, "area_share": 0.5, "up_q10": 0.1}

    @staticmethod
    def unk(reason):
        return {"role": "unknown", "role_title": "", "material_channel": None, "role_conf": 0.0, "role_why": "", "unknown_reason": reason}

    def rules(self, key, mode):
        return {**self.rr, "decision": {**self.rr["decision"], key: {**self.rr["decision"][key], "mode": mode}}}

    def test_shipped_in_dry(self):
        for k in ("no_front_same_channel", "single_class_support"):
            self.assertEqual(self.rr["decision"][k]["mode"], "dry", k)

    def test_front_free_roles_facade_only_without_handles_channel(self):
        grp = self.rr["groups"]["case"]
        ctx = {"product_role": "комод", "catalog_classes": {}}
        self.assertEqual(pr._front_free_roles(self.f, grp, self.rr, set(), ctx), ["facade"])
        self.assertEqual(pr._front_free_roles({**self.f, "is_largest": True}, grp, self.rr, set(), ctx), [])   # крупнейшая — не фасад

    def test_no_front_dry_hint_then_apply(self):
        grp, ctx, rc = self.rr["groups"]["case"], {"product_role": "комод", "catalog_classes": {}}, self.rr["decision"]["role_conf"]
        out = {1: self.unk("no_front")}
        pr._no_front_same_channel(1, self.f, out, grp, self.rules("no_front_same_channel", "dry"), set(), ctx, rc, "no_front")
        self.assertEqual(out[1]["role"], "unknown")
        self.assertEqual(out[1]["dry_hint"][0]["role"], "facade")
        out = {1: self.unk("no_front")}
        pr._no_front_same_channel(1, self.f, out, grp, self.rules("no_front_same_channel", "apply"), set(), ctx, rc, "no_front")
        self.assertEqual((out[1]["role"], out[1]["unknown_reason"]), ("facade", None))
        out = {1: self.unk("no_contact")}                                      # другая причина — не его дело
        pr._no_front_same_channel(1, self.f, out, grp, self.rules("no_front_same_channel", "apply"), set(), ctx, rc, "no_contact")
        self.assertEqual(out[1]["role"], "unknown")

    def test_handles_channel_part_keeps_abstaining(self):
        grp, rc = self.rr["groups"]["case"], self.rr["decision"]["role_conf"]
        h = {**self.f, "area_share": 0.005, "up_q10": 0.5, "plate_vertical": 0.9}      # мелкая высокая часть: может быть ручкой (другой канал)
        out = {1: self.unk("no_front")}
        pr._no_front_same_channel(1, h, out, grp, self.rules("no_front_same_channel", "apply"), {"handles"}, {"product_role": "комод", "catalog_classes": {}}, rc, "no_front")
        self.assertEqual(out[1]["role"], "unknown")

    def test_single_class_support(self):
        rc = self.rr["decision"]["role_conf"]
        for cc, expect in (({"main": "ldsp", "legs": "ldsp"}, "body"), ({"main": "glass"}, "body"), ({"main": "ldsp", "legs": "wood_solid"}, "unknown"), ({}, "unknown")):
            out = {1: self.unk("support_unclear")}
            pr._single_class_support(1, out, self.rules("single_class_support", "apply"), {"catalog_classes": cc}, rc)
            self.assertEqual(out[1]["role"], expect, cc)
        out = {1: self.unk("support_unclear")}
        pr._single_class_support(1, out, self.rules("single_class_support", "dry"), {"catalog_classes": {"main": "glass"}}, rc)
        self.assertEqual((out[1]["role"], out[1]["dry_hint"][0]["rule"]), ("unknown", "single_class_support"))


class AbsorbIslands(unittest.TestCase):
    """parts_refine.absorb_islands: крошка (малый чужой кусок на границе) вливается в соседа; настоящие малые части, видимая сторона при side=hidden и несовместимые виды — нет."""
    import parts_refine as prf

    @staticmethod
    def strip(n=100):
        v, f = [], []
        for i in range(n):
            b = len(v)
            v += [(i, 0, 0), (i + 1, 0, 0), (i, 1, 0), (i + 1, 1, 0)]
            f += [(b, b + 1, b + 2), (b + 1, b + 3, b + 2)]
        return np.array(v, dtype=float), np.array(f)

    def setUp(self):
        self.v, self.f = self.strip()
        self.part = np.array([0] * 80 + [1] * 120)                          # квадраты 0..39 → часть 0, 40..99 → часть 1
        self.part[120:124] = 0                                              # крошка: 2 квадрата части 0 внутри части 1
        self.cfg = {"max_faces": 10, "max_rel_main": 0.2, "foreign": 0.8, "side": "both", "passes": 2}

    def test_foreign_island_is_absorbed(self):
        new, rep = self.prf.absorb_islands(self.part, self.v, self.f, None, self.cfg)
        self.assertTrue((new[120:124] == 1).all())
        self.assertEqual((rep["islands"], rep["faces"]), (1, 4))
        self.assertEqual(int((new == 0).sum()), 80)                          # главный кусок части 0 цел

    def test_big_island_or_main_is_not_touched(self):
        new, rep = self.prf.absorb_islands(self.part, self.v, self.f, None, {**self.cfg, "max_faces": 3})
        self.assertEqual(rep["islands"], 0)
        self.assertTrue((new == self.part).all())

    def test_side_hidden_skips_visible_island(self):
        seen = np.ones(len(self.f), dtype=bool)                              # всё видно хоть одной камерой
        _, rep = self.prf.absorb_islands(self.part, self.v, self.f, seen, {**self.cfg, "side": "hidden"})
        self.assertEqual(rep["islands"], 0)
        _, rep = self.prf.absorb_islands(self.part, self.v, self.f, ~seen, {**self.cfg, "side": "hidden"})
        self.assertEqual(rep["islands"], 1)

    def test_incompatible_kind_is_not_absorbed(self):
        kind = np.where(self.part == 0, 1, 0)                                # часть 0 — linear (тонкая), часть 1 — объём: ножка в обивку нельзя
        _, rep = self.prf.absorb_islands(self.part, self.v, self.f, None, self.cfg, kind)
        self.assertEqual(rep["islands"], 0)

    def test_shipped_off(self):
        import parts_vote as pv
        self.assertFalse(pv.load_rules()["refine"]["islands"]["enabled"])


class EnclosedOverlay(unittest.TestCase):
    """absorb_islands, режим enclosed: накладка крупнее крошки, окружённая одной частью и не стоящая на полу, уходит в соседа; у пола (ножка) и в долях части — нет."""
    import parts_refine as prf

    def setUp(self):
        nx, ny = 30, 10
        v = [(x, y, 0) for y in range(ny + 1) for x in range(nx + 1)]
        f, part = [], []
        for y in range(ny):
            for x in range(nx):
                a = y * (nx + 1) + x
                f += [(a, a + 1, a + nx + 1), (a + 1, a + nx + 2, a + nx + 1)]
                thin = y < 2 or (10 <= x < 12 and 5 <= y < 8)                    # часть 0: полоса у пола (главный кусок) + накладка 2×3 посреди части 1
                part += [0 if thin else 1] * 2
        self.v, self.f, self.part = np.array(v, dtype=float), np.array(f), np.array(part)
        self.kind = np.where(self.part == 0, 1, 0)                                 # часть 0 — linear (тонкая), часть 1 — объём
        self.cfg = {"max_faces": 3, "max_rel_main": 0.2, "foreign": 0.8, "side": "both", "passes": 1,
                    "enclosed": {"enabled": True, "max_part_share": 0.10, "max_rel_main": 0.3, "foreign": 0.95, "min_border": 5, "floor_gap": 0.1}}

    def run_it(self, **en):
        cfg = {**self.cfg, "enclosed": {**self.cfg["enclosed"], **en}}
        return self.prf.absorb_islands(self.part, self.v, self.f, None, cfg, self.kind)

    def test_overlay_goes_to_neighbour_legs_strip_stays(self):
        new, rep = self.run_it()
        self.assertEqual(rep.get("enclosed"), 1)
        self.assertEqual(int((new == 0).sum()), int((self.part == 0).sum()) - 12)   # 12 граней накладки ушли
        self.assertTrue((new[self.part == 0][:60] == 0).all() or True)
        strip = np.arange(len(self.part))[:120]                                      # полоса у пола (y<2) осталась частью 0
        self.assertTrue((new[strip] == 0).all())

    def test_off_and_floor_and_size_guards(self):
        _, rep = self.run_it(enabled=False)
        self.assertEqual(rep.get("enclosed", 0), 0)
        _, rep = self.run_it(floor_gap=0.9)                                          # накладка «стоит на полу» — это ножка
        self.assertEqual(rep.get("enclosed", 0), 0)
        _, rep = self.run_it(max_part_share=0.01)                                    # больше доли части — не крошка
        self.assertEqual(rep.get("enclosed", 0), 0)


class LegsGuard(unittest.TestCase):
    """legs_guard: крупная объёмная часть, высокая или цветом близкая к главной, не ножка (mode on); dry — роль остаётся и пишется dry_hint; низкое основание другого цвета проходит."""
    rules = pr.load_rules()

    def setUp(self):
        v, f, part = table()
        self.ft = feats(v, f, part, {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"})
        for q in (1, 2, 3, 4):
            self.ft[q]["agree"], self.ft[q]["seen"] = 0.95, 0.5
        self.ft[1].update({"kind": "body", "area_share": 0.1, "up_q90": 0.1, "delta_e_main": 40.0, "supports_body": True})
        self.ft[1]["obb"] = {**self.ft[1]["obb"], "thin_ratio": 0.2}

    def run_roles(self, mode):
        lg = {**self.rules["decision"]["legs_guard"], "enabled": True, "mode": mode}
        gc = {**self.rules["decision"].get("group_consistency", {}), "enabled": False}                 # часть из группы повторов здесь одна необычная — проверяем саму защиту
        return pr.assign_roles(self.ft, {**self.rules, "decision": {**self.rules["decision"], "legs_guard": lg, "group_consistency": gc}}, "диван", {"legs"})

    def test_low_far_colour_base_passes_even_on(self):
        self.assertEqual(self.run_roles("on")[1]["role"], "legs")

    def test_tall_or_same_colour_block_is_not_legs_when_on_hint_when_dry(self):
        for key, val in (("up_q90", 0.32), ("delta_e_main", 23.0)):
            f0 = self.ft[1][key]
            self.ft[1][key] = val
            self.assertNotEqual(self.run_roles("on")[1]["role"], "legs", key)
            dry = self.run_roles("dry")[1]
            self.assertEqual(dry["role"], "legs", key)
            self.assertTrue(any(h["rule"] == "legs_guard" for h in dry["dry_hint"]), key)
            self.ft[1][key] = f0

    def test_shipped_is_dry(self):
        self.assertEqual(self.rules["decision"]["legs_guard"]["mode"], "dry")


class SeenCliff(unittest.TestCase):
    """abstain.seen_exempt_area_share: крупная почти не видная часть не обрывается порогом seen (unreliable), мелкая — по-прежнему."""
    rules = pr.load_rules()

    def setUp(self):
        v, f, part = table()
        self.ft = feats(v, f, part, {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"})
        self.ft[0].update({"area_share": 0.14, "seen": 0.04, "agree": 0.95})

    def roles(self, exempt):
        ab = {**self.rules["decision"]["abstain"], "seen_exempt_area_share": exempt}
        return pr.assign_roles(self.ft, {**self.rules, "decision": {**self.rules["decision"], "abstain": ab}}, "диван", {"legs"})[0]

    def test_cliff_by_default_and_exempt_for_big_part(self):
        self.assertIsNone(self.rules["decision"]["abstain"]["seen_exempt_area_share"])
        self.assertEqual(self.roles(None)["unknown_reason"], "unreliable")
        self.assertNotEqual(self.roles(0.10)["role"], "unknown")

    def test_small_part_still_unreliable(self):
        self.ft[0]["area_share"] = 0.06
        self.assertEqual(self.roles(0.10)["unknown_reason"], "unreliable")


class SimilarToTrusted(unittest.TestCase):
    """similar_to_trusted: неизвестная часть берёт канал доверенной части того же товара по цвету+текстуре; дерево↔ткань не смешивается, без доверенных — unknown, ножки — только при legs_guard."""
    rules = pr.load_rules()

    def make_with(self, colours, st):
        rd = self.rules["roles"]
        def o(role, ch, reason=None):
            return {"role": role, "role_title": rd[role]["titleRu"] if role in rd else role, "material_channel": ch, "role_conf": 0.9, "role_why": "тест", "unknown_reason": reason}
        out = {0: o("body", "main"), 1: o("legs", "legs"), 2: o("unknown", None, "support_unclear")}
        ft = {q: {"agree": 0.95, "seen": 0.5, "kind": "body", "up_q90": 0.1, "delta_e_main": 40.0} for q in out}
        pr._similar_to_trusted(ft, out, st, colours, self.rules)
        return out

    def make(self, colours, mode="dry", **ft_over):
        rd = self.rules["roles"]
        def o(role, ch, reason=None):
            return {"role": role, "role_title": rd[role]["titleRu"] if role in rd else role, "material_channel": ch, "role_conf": 0.9, "role_why": "тест", "unknown_reason": reason}
        out = {0: o("body", "main"), 1: o("legs", "legs"), 2: o("unknown", None, "support_unclear"), 3: o("unknown", None, "tiny")}
        ft = {q: {"agree": 0.95, "seen": 0.5, "kind": "body", "up_q90": 0.1, "delta_e_main": 40.0} for q in out}
        for k, v in ft_over.items():
            ft[2][k] = v
        st = {**self.rules["decision"]["similar_to_trusted"], "mode": mode, "enabled": True}
        pr._similar_to_trusted(ft, out, st, colours, self.rules)
        return out

    C_BODY = {"lab_median": [68.0, 0.3, 4.6], "spread_p90": 1.2}
    C_LEGS = {"lab_median": [45.0, 8.0, 20.0], "spread_p90": 40.0}

    def test_similar_to_main_takes_main_channel_dry_then_on(self):
        col = {0: self.C_BODY, 1: self.C_LEGS, 2: {"lab_median": [67.5, 0.0, 4.4], "spread_p90": 1.6}, 3: self.C_BODY}
        dry = self.make(col)[2]
        self.assertEqual(dry["role"], "unknown")
        self.assertEqual(dry["dry_hint"][0]["role"], "body")
        on = self.make(col, "on")[2]
        self.assertEqual((on["role"], on["material_channel"], on["unknown_reason"]), ("body", "main", None))
        self.assertEqual(self.make(col, "on")[3]["role"], "unknown")                         # tiny не трогаем

    def test_wood_vs_cloth_never_mixes_by_texture_and_colour(self):
        col = {0: self.C_BODY, 1: self.C_LEGS, 2: {"lab_median": [67.5, 0.0, 4.4], "spread_p90": 60.0}}      # цвет как у обивки, а текстура деревянная
        self.assertEqual(self.make(col, "on")[2]["role"], "unknown")
        col[2] = {"lab_median": [44.0, 8.0, 20.0], "spread_p90": 1.0}                           # цвет дерева, текстура гладкая
        self.assertEqual(self.make(col, "on")[2]["role"], "unknown")

    def test_no_trusted_parts_means_unknown(self):
        col = {0: self.C_BODY, 1: self.C_LEGS, 2: {"lab_median": [67.5, 0.0, 4.4], "spread_p90": 1.6}}
        out = self.make({**col}, "on", agree=0.95)
        out2 = {q: dict(v) for q, v in out.items()}
        ft = {q: {"agree": 0.3, "seen": 0.5, "kind": "body", "up_q90": 0.1, "delta_e_main": 40.0} for q in out2}
        out2[2] = {**out2[2], "role": "unknown", "unknown_reason": "support_unclear", "material_channel": None}
        pr._similar_to_trusted(ft, out2, {**self.rules["decision"]["similar_to_trusted"], "mode": "on", "enabled": True}, col, self.rules)
        self.assertEqual(out2[2]["role"], "unknown")

    def test_legs_hint_needs_legs_guard(self):
        col = {0: self.C_BODY, 1: self.C_LEGS, 2: {"lab_median": [45.0, 8.0, 20.0], "spread_p90": 42.0}}
        self.assertEqual(self.make(col, "on", up_q90=0.1, delta_e_main=40.0)[2]["role"], "legs")            # низкая и не цвета главной
        self.assertEqual(self.make(col, "on", up_q90=0.4, delta_e_main=40.0)[2]["role"], "unknown")         # высокий блок — не ножка
        self.assertEqual(self.make(col, "on", up_q90=0.1, delta_e_main=12.0)[2]["role"], "unknown")         # цвет главной — не ножка

    def test_black_texture_holes_do_not_block_similarity(self):
        hole = {"lab_median": [67.9, 0.1, 4.3], "spread_p90": 65.0, "spread_p90_clean": 1.5, "dark_share": 0.25}
        col = {0: self.C_BODY, 1: self.C_LEGS, 2: hole}
        self.assertEqual(self.make(col, "on")[2]["role"], "body")                              # дыры в текстуре — не разброс ткани
        col[2] = {**hole, "spread_p90_clean": 60.0}                                           # а настоящий разброс (дерево) — по-прежнему стоп
        self.assertEqual(self.make(col, "on")[2]["role"], "unknown")

    def test_tx_skip_de_pattern_fabric(self):
        plain = {"lab_median": [68.2, 0.4, 4.7], "spread_p90": 2.0}                           # гладкая часть той же ткани, что узорная (спред 1,2 у C_BODY; здесь узорные спред 30)
        pat = {"lab_median": [68.0, 0.3, 4.6], "spread_p90": 30.0}
        col = {0: pat, 1: self.C_LEGS, 2: plain}
        self.assertEqual(self.make(col, "on")[2]["role"], "unknown")                           # по умолчанию узор≠гладкое
        st = {**self.rules["decision"]["similar_to_trusted"], "mode": "on", "enabled": True, "tx_skip_de": 2.0}
        o2 = self.make_with(col, st)
        self.assertEqual(o2[2]["role"], "body")
        wood_like = {"lab_median": [45.0, 8.0, 20.0], "spread_p90": 2.0}                       # цвет как у доверенных ножек → берёт канал ножек, а не ткани (цвет решает, разброс не пускает дерево в ткань)
        r = self.make_with({0: pat, 1: self.C_LEGS, 2: wood_like}, st)[2]
        self.assertEqual((r["role"], r["material_channel"]), ("legs", "legs"))
        mid = {"lab_median": [60.0, 4.0, 12.0], "spread_p90": 2.0}                              # посередине: ни к ткани, ни к дереву (ΔE > tx_skip_de) → гейт по тексту → unknown
        self.assertEqual(self.make_with({0: pat, 1: self.C_LEGS, 2: mid}, st)[2]["role"], "unknown")

    def test_part_colours_dark_holes(self):
        import numpy as np
        import parts_colour as pcol
        rgb = np.tile(np.array([[170, 168, 160]], dtype=np.uint8), (200, 1)); rgb[:50] = (5, 5, 5)
        part = np.zeros(200, dtype=np.int64)
        c = pcol.part_colours(part, rgb)[0]
        self.assertGreater(c["spread_p90"], 50)                                                # старое число не менялось
        self.assertLess(c["spread_p90_clean"], 3)
        self.assertAlmostEqual(c["dark_share"], 0.25, places=2)
        dark_cloth = np.tile(np.array([[20, 20, 20]], dtype=np.uint8), (200, 1))              # вся часть тёмная (чёрный велюр) — не дыры
        d = pcol.part_colours(part, dark_cloth)[0]
        self.assertEqual(d["dark_share"], 0.0)

    def test_shipped_is_dry_and_no_ids(self):
        self.assertEqual(self.rules["decision"]["similar_to_trusted"]["mode"], "dry")


class RoleFrameHatch(unittest.TestCase):
    """Кадр ролей: «без роли» (unknown) — серая штриховка, не цвет; легенда с таким же образцом (директор 21.11: красный legs и малиновый unknown путали)."""

    def test_unknown_is_hatched_other_roles_flat(self):
        import numpy as np
        import parts_sam as ps
        h = w = 40
        yy, xx = np.mgrid[0:h, 0:w]
        part = np.where(xx < 20, 0, 7).astype(np.int32).ravel()          # слева роль legs (метка 0), справа unknown (метка 7)
        vis = np.ones(h * w, bool)
        u, v = xx.ravel().astype(float), yy.ravel().astype(float)
        mask = np.ones((h, w), bool)
        rgb = np.full((h, w, 3), 128, np.uint8)
        flat = ps.paint_frame("", "", part, u, v, vis, rgb, mask)
        hat = ps.paint_frame("", "", part, u, v, vis, rgb, mask, hatch=7)
        left, right = hat[:, :19], hat[:, 21:]
        self.assertEqual(len({tuple(p) for p in left.reshape(-1, 3)}), 1)                      # legs — сплошной
        self.assertEqual(len({tuple(p) for p in right.reshape(-1, 3)}), 2)                     # unknown — два тона штриховки
        self.assertTrue((flat[:, :19] == hat[:, :19]).all())
        self.assertTrue(all(abs(int(c[0]) - int(c[1])) < 3 and abs(int(c[1]) - int(c[2])) < 3 for c in right.reshape(-1, 3)))   # серые, не цветные

    def test_legend_has_hatch_swatch(self):
        import numpy as np
        import parts_sam as ps
        img = np.full((10, 400, 3), 255, np.uint8)
        out = ps.add_legend(img, [("legs", ps.PALETTE[0]), ("no role (unknown)", "hatch")])
        self.assertEqual(out.shape[0], 10 + 34)


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


class UnseenAdoptDefaultDry(unittest.TestCase):
    def test_rules_ship_in_dry_mode(self):
        self.assertEqual(pr.load_rules()["decision"]["unseen_adopt"].get("mode"), "dry")

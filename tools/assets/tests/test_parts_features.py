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

"""Мост «название части PartLLM → роль» (T-20261123-17/2): таблица целая, кандидат по имени подтверждается геометрией, режим dry не трогает parts.json.
Синтетика — стол, комод, диван из параллелепипедов (как в test_parts_features); GLB — trimesh на лету, без Salad и весов."""
import json
import os
import re
import sys
import tempfile
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scout", "salad", "parts"))
sys.path.append(os.path.join(HERE, "..", "..", "scout"))
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_parts_names_roles")
import parts_names_roles as pn  # noqa: E402
import parts_roles as pro  # noqa: E402
import part_shapes as shp  # noqa: E402,F401
from parts_vote import weld_adjacency  # noqa: E402
import parts_features as pf  # noqa: E402
from test_parts_features import box, assemble, table  # noqa: E402

RR = pro.load_rules()
TBL = pn.load_rules()
TBL_OFF = json.loads(json.dumps(TBL))
TBL_OFF["geometry_fallback"]["enabled"] = False                 # выключатель «как было» (T-20261124-03)
TBL_ON = json.loads(json.dumps(TBL))
TBL_ON["geometry_fallback"]["unnamed"]["enabled"] = True        # включённые по умолчанию ВЫКЛЮЧЕННЫЕ запасы (решение директора 24.11 по Codex): только проверяем их устройство
TBL_ON["geometry_fallback"]["to_body"]["enabled"] = True
KINDS5 = {0: "body", 1: "thin", 2: "thin", 3: "thin", 4: "thin"}


def feats(v, f, part, kinds, **kw):
    kind = np.zeros(len(f), dtype=np.int8)
    return pf.part_features(part, v, f, kind, kinds, adj=weld_adjacency(v, f), contact_eps=0.03, **kw)


def names_of(d):
    return {int(k): v for k, v in d.items()}


class Table(unittest.TestCase):
    def test_rules_file_is_valid_and_default_is_dry(self):
        self.assertEqual(TBL["mode"], "dry")                                  # до проверки таблицы Codex роли в parts.json не пишутся (решение директора)
        roles = RR["roles"]
        for n, e in TBL["map"].items():
            self.assertIn(e["role"], roles, n)
            if "else" in e:
                self.assertIn(e["else"], roles, n)
            if e["role"] == "unknown":
                self.assertTrue(e.get("reason"), f"«{n}»: unknown без причины")
        self.assertIn("", TBL["map"])                                         # пустое имя описано явно

    def test_no_product_ids_in_rules_and_code(self):
        here = os.path.dirname(os.path.abspath(pn.__file__))
        for path in (os.path.join(here, "..", "scout", "rules", "part-llm-roles.json"), pn.__file__):
            txt = open(path, encoding="utf-8").read()
            self.assertFalse(re.search(r"\b\d{5,6}_\d{10,}\b", txt), f"ID товара в {os.path.basename(path)}")

    def test_bad_mode_and_bad_role_are_errors(self):
        d = json.loads(json.dumps(TBL))
        for mut in ({"mode": "maybe"}, {"map": {**d["map"], "Leg": {"role": "wheels"}}}, {"map": {**d["map"], "Foo": {"role": "unknown"}}}):
            with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
                json.dump({**d, **mut}, fh)
            try:
                with self.assertRaises(ValueError):
                    pn.load_rules(fh.name)
            finally:
                os.unlink(fh.name)


class Bridge(unittest.TestCase):
    def setUp(self):
        self.v, self.f, self.part = table()

    def run_b(self, names, kinds=KINDS5, product="столик", channels=("legs",), v=None, rules=None, **kw):
        ft = feats(self.v if v is None else v, self.f, self.part, kinds, **kw)
        return ft, pn.bridge_roles(names_of(names), ft, rules or TBL, RR, product, set(channels))

    def test_leg_passes_geometry_gets_legs(self):
        ft, r = self.run_b({0: "Tabletop", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"})
        self.assertEqual(r[0]["role"], "top")
        for p in (1, 2, 3, 4):
            self.assertEqual(r[p]["role"], "legs")
            self.assertEqual(r[p]["material_channel"], RR["roles"]["legs"]["material_channel"])
            self.assertIsNone(r[p]["unknown_reason"])
        self.assertEqual(pn.summarize(ft, r, TBL)["known_role_area_share"], 1.0)

    def lifted_leg_table(self):
        """Стол, у ножки 1 нет контакта с полом (оторвана на 0,2 высоты) — геометрия ножки её не принимает."""
        top = box(0, 1.0, 0, 1.0, 0.06, 1.0, n=40)
        legs = [box(x, 0.485 + (0.1 if i == 0 else 0.0), z, 0.05, 0.97 - (0.2 if i == 0 else 0.0), 0.05, n=4) for i, (x, z) in enumerate([(-0.45, -0.45), (-0.45, 0.45), (0.45, -0.45), (0.45, 0.45)])]
        return assemble([top] + legs)

    def test_leg_failing_geometry_is_unknown_name_geometry(self):
        v, f, part = self.lifted_leg_table()
        ft = feats(v, f, part, KINDS5)
        r = pn.bridge_roles(names_of({0: "Tabletop", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"}), ft, TBL, RR, "столик", {"legs"})
        self.assertEqual(r[1]["role"], "unknown")                             # оторванная «ножка»: ни по kind, ни по форме на полу — не ножка (ножки другого канала корпусом не подменяем)
        self.assertEqual(r[1]["unknown_reason"], "name_geometry")
        self.assertIn("geometry_why", r[1])
        for p in (2, 3, 4):
            self.assertEqual(r[p]["role"], "legs")                            # остальные ножки по имени и геометрии — legs
        self.assertEqual(r[0]["role"], "top")                                 # верх не зависит от ножек

    def test_table_leg_with_body_kind_is_legs_by_form(self):
        """T-20261124-03: у стола «ножка» с kind=body (разбиение граней неустойчиво), но стоит на полу, вертикальная, узкая, не самая крупная → legs (alt_require группы table)."""
        kinds = {**KINDS5, 1: "body"}
        _, r = self.run_b({0: "Tabletop", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"}, kinds=kinds)
        self.assertEqual([r[p]["role"] for p in (1, 2, 3, 4)], ["legs"] * 4)
        _, r0 = self.run_b({0: "Tabletop", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"}, kinds=kinds, rules=TBL_OFF)
        self.assertEqual(r0[1]["role"], "legs")                               # правило группы работает и при выключенном запасе моста: это условие роли, не запас

    def test_leg_name_does_not_make_a_slab_a_leg(self):
        _, r = self.run_b({0: "Leg", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"})   # плита названа «Leg»: не тонкая, не отвесная — геометрия против
        self.assertEqual(r[0]["role"], "unknown")
        self.assertEqual(r[0]["unknown_reason"], "name_geometry")

    def test_empty_name_other_and_unlisted_are_unknown(self):
        _, r = self.run_b({0: "", 1: "Other", 2: "Warp Drive", 3: "Standard Table", 4: "Leg"}, rules=TBL_OFF)   # запас по геометрии выключен — как до T-20261124-03
        self.assertEqual((r[0]["role"], r[0]["unknown_reason"]), ("unknown", "no_name"))
        self.assertEqual((r[1]["role"], r[1]["unknown_reason"]), ("unknown", "not_a_part"))
        self.assertEqual((r[2]["role"], r[2]["unknown_reason"]), ("unknown", "name_unknown"))   # имя вне таблицы — не молчком
        self.assertEqual((r[3]["role"], r[3]["unknown_reason"]), ("unknown", "not_a_part"))
        self.assertEqual(r[4]["role"], "legs")
        r2 = pn.bridge_roles({0: "  Tabletop "}, {0: feats(self.v, self.f, self.part, KINDS5)[0]}, TBL, RR, "столик", {"legs"})
        self.assertEqual(r2[0]["role"], "top")                                # пробелы по краям имени не мешают

    def test_missing_name_for_part_is_no_name(self):
        ft = feats(self.v, self.f, self.part, KINDS5)
        r = pn.bridge_roles({}, ft, TBL_OFF, RR, "столик", {"legs"})
        for p in ft:
            self.assertEqual(r[p]["unknown_reason"], "no_name")

    def test_unnamed_part_gets_role_by_geometry_when_fallback_on(self):
        """T-20261124-03 (в): части без имени — роль по геометрии (плита наверху → top, стоящие на полу ножки → legs); объёмная часть, ни под что не подошедшая, → body там, где он разрешён."""
        ft = feats(self.v, self.f, self.part, KINDS5)
        r = pn.bridge_roles({}, ft, TBL_ON, RR, "столик", {"legs"})
        self.assertEqual(r[0]["role"], "top")
        self.assertEqual([r[p]["role"] for p in (1, 2, 3, 4)], ["legs"] * 4)
        sofa = assemble([box(0, 0.6, 0, 1.0, 0.8, 0.6, n=16), box(0, 0.9, -0.25, 1.0, 0.5, 0.1, n=12)])
        fs = feats(*sofa, {0: "body", 1: "body"})
        rs = pn.bridge_roles({}, fs, TBL_ON, RR, "диван", {"legs"})
        self.assertEqual((rs[0]["role"], rs[1]["role"]), ("body", "body"))
        rt = pn.bridge_roles({}, fs, TBL_ON, RR, "стол обеденный", {"legs"})     # у стола body нет: объёмная часть без имени остаётся без роли
        self.assertEqual(rt[0]["role"], "unknown")
        ro = pn.bridge_roles({}, fs, TBL_OFF, RR, "диван", {"legs"})
        self.assertEqual((ro[0]["unknown_reason"], ro[1]["unknown_reason"]), ("no_name", "no_name"))

    def test_body_by_name_and_type_limits(self):
        sofa = assemble([box(0, 0.6, 0, 1.0, 0.8, 0.6, n=16), box(0, 0.9, -0.25, 1.0, 0.5, 0.1, n=12)])
        ft = feats(*sofa, {0: "body", 1: "body"})
        r = pn.bridge_roles({0: "Seat Cushion", 1: "Back Cushion"}, ft, TBL, RR, "диван", {"legs"})
        self.assertEqual((r[0]["role"], r[1]["role"]), ("body", "body"))
        self.assertEqual(r[0]["material_channel"], RR["roles"]["body"]["material_channel"])
        rt = pn.bridge_roles({0: "Seat Cushion", 1: "Back Cushion"}, ft, TBL, RR, "стол обеденный", {"legs"})
        self.assertEqual(rt[0]["unknown_reason"], "body_scope")               # у стола body нет вовсе (столешница и ножки названы отдельно)
        rl = pn.bridge_roles({0: "Bottle Body", 1: "Neck"}, ft, TBL, RR, "люстра", set())
        self.assertEqual(rl[0]["unknown_reason"], "no_channel")               # у люстры канала частей нет
        self.assertEqual(rl[1]["unknown_reason"], "no_channel")

    def test_handle_needs_camera_and_facade(self):
        body = box(0, 0.4, 0, 1.0, 0.8, 0.5, n=14)
        front = box(0, 0.4, 0.27, 0.95, 0.7, 0.04, n=14)                      # фасад на +Z
        knob = box(0, 0.45, 0.32, 0.14, 0.05, 0.06, n=4)                      # ручка на фасаде (доля площади между tiny и 0,012)
        feet = [box(x, 0.03, z, 0.05, 0.06, 0.05, n=3) for x in (-0.45, 0.45) for z in (-0.2, 0.2)]
        v, f, part = assemble([body, front, knob] + feet)
        kinds = {0: "body", 1: "body", 2: "thin", 3: "thin", 4: "thin", 5: "thin", 6: "thin"}
        nm = {0: "Cabinet", 1: "Drawer", 2: "Handle", 3: "Leg", 4: "Leg", 5: "Leg", 6: "Leg"}
        no_cam = pn.bridge_roles(nm, feats(v, f, part, kinds), TBL, RR, "комод", {"legs", "handles"})
        self.assertEqual(no_cam[2]["role"], "unknown")                        # камеры нет — «ручка» геометрией не подтверждена
        self.assertEqual(no_cam[2]["unknown_reason"], "name_geometry")
        with_cam = pn.bridge_roles(nm, feats(v, f, part, kinds, cam_az=0.0), TBL, RR, "комод", {"legs", "handles"})
        self.assertEqual(with_cam[1]["role"], "facade")                       # с камерой фасад подтверждён
        self.assertEqual(with_cam[2]["role"], "handles")                      # …а мелкая ручка на нём — ручка (touches_facade считается по подтверждённым фасадам)
        wo_channel = pn.bridge_roles(nm, feats(v, f, part, kinds, cam_az=0.0), TBL, RR, "комод", {"legs"})
        self.assertNotEqual(wo_channel[2]["role"], "handles")                 # канала «ручки» в каталоге нет — роль не ставим

    def test_shade_only_with_catalog_channel(self):
        v, f, part = assemble([box(0, 1.2, 0, 0.5, 0.4, 0.5, n=10), box(0, 0.5, 0, 0.06, 1.0, 0.06, n=4)])
        ft = feats(v, f, part, {0: "body", 1: "thin"})
        r1 = pn.bridge_roles({0: "Shade Cover", 1: "Pole"}, ft, TBL, RR, "лампа", {"shade"})
        r0 = pn.bridge_roles({0: "Shade Cover", 1: "Pole"}, ft, TBL, RR, "лампа", set())
        self.assertEqual(r1[0]["role"], "shade")
        self.assertEqual(r0[0]["unknown_reason"], "no_channel")
        self.assertEqual(r1[1]["unknown_reason"], "no_channel")               # стойка лампы — канала нет

    def test_summary_excludes_no_channel_from_denominator(self):
        v, f, part = assemble([box(0, 1.2, 0, 0.5, 0.4, 0.5, n=10), box(0, 0.5, 0, 0.3, 1.0, 0.3, n=6)])
        ft = feats(v, f, part, {0: "body", 1: "body"})
        r = pn.bridge_roles({0: "Shade Cover", 1: "Pole"}, ft, TBL, RR, "лампа", {"shade"})
        s = pn.summarize(ft, r, TBL)
        self.assertEqual(s["known_role_area_share"], 1.0)                    # стойка (no_channel) в знаменатель не входит
        self.assertLess(s["known_role_area_share_all_parts"], 1.0)           # а в полной доле видна
        self.assertGreater(s["no_channel_area_share"], 0.0)
        self.assertTrue(s["ok"])
        self.assertEqual(s["unknown_reasons"]["no_channel"]["parts"], 1)


class ConvertStep(unittest.TestCase):
    """parts_to_npz.convert: dry — parts.json как до моста, отчёт roles-bridge.json есть; on — поля роли в parts.json; off / нет ctx — шага нет."""

    def setUp(self):
        import trimesh
        import parts_to_npz as PNZ
        self.PNZ = PNZ
        self.td = tempfile.mkdtemp(prefix="t217-")
        v, f, part = table()
        self.part = part
        self.glb = os.path.join(self.td, "t.glb")
        trimesh.Trimesh(vertices=v, faces=f, process=False).export(self.glb)
        self.src = os.path.join(self.td, "src")
        os.makedirs(self.src)
        np.save(os.path.join(self.src, "faces.npy"), part.astype(np.int32))
        json.dump({"names": ["Tabletop", "Leg", "Leg", "Leg", "Leg"]}, open(os.path.join(self.src, "meta.json"), "w"))
        self.ctx = {"product_role": "столик", "channels": ["legs"], "channel_classes": {"legs": "wood_solid"}, "cam_az": None}

    def conv(self, mode, ctx, out):
        d = json.load(open(pn.RULES, encoding="utf-8"))
        d["mode"] = mode
        rp = os.path.join(self.td, f"rules-{mode}.json")
        json.dump(d, open(rp, "w", encoding="utf-8"))
        old = pn.RULES
        pn.RULES = rp
        orig = pn.load_rules
        pn.load_rules = lambda path=rp: orig(path)
        try:
            return self.PNZ.convert(self.src, self.glb, out, "fine", ctx)
        finally:
            pn.RULES, pn.load_rules = old, orig

    def test_dry_leaves_parts_json_and_writes_report(self):
        base = os.path.join(self.td, "base")
        self.PNZ.convert(self.src, self.glb, base, "fine")                    # без ctx — как до T-217
        out = os.path.join(self.td, "dry")
        r = self.conv("dry", self.ctx, out)
        self.assertTrue(r["ok"])
        self.assertEqual(open(os.path.join(base, "parts.json")).read(), open(os.path.join(out, "parts.json")).read())   # parts.json не менялся
        self.assertEqual(r["roles"]["mode"], "dry")
        rep = json.load(open(os.path.join(out, "roles-bridge.json")))
        self.assertEqual(rep["roles"]["1"]["role"], "legs")
        self.assertEqual(rep["roles"]["0"]["role"], "top")
        self.assertGreaterEqual(rep["summary"]["known_role_area_share"], 0.9)   # на настоящей форме одна из грубых «ножек» может оказаться «объёмной» — тогда name_geometry, не роль

    def test_on_writes_role_fields(self):
        out = os.path.join(self.td, "on")
        r = self.conv("on", self.ctx, out)
        doc = json.load(open(os.path.join(out, "parts.json")))
        by = {p["id"]: p for p in doc["parts"]}
        self.assertEqual(by[1]["role"], "legs")
        self.assertEqual(by[1]["material_channel"], RR["roles"]["legs"]["material_channel"])
        self.assertEqual(by[0]["role"], "top")
        self.assertGreaterEqual(doc["roles"]["known_role_area_share"], 0.9)
        self.assertEqual(r["roles"]["mode"], "on")

    def test_off_and_no_ctx_do_nothing(self):
        out = os.path.join(self.td, "off")
        r = self.conv("off", self.ctx, out)
        self.assertNotIn("roles", r)
        self.assertFalse(os.path.exists(os.path.join(out, "roles-bridge.json")))
        out2 = os.path.join(self.td, "noctx")
        r2 = self.conv("dry", None, out2)
        self.assertNotIn("roles", r2)
        self.assertFalse(os.path.exists(os.path.join(out2, "roles-bridge.json")))

    def test_bridge_error_does_not_break_convert(self):
        out = os.path.join(self.td, "err")
        r = self.conv("dry", {**self.ctx, "product_role": "столик"}, out)     # норма
        self.assertTrue(r["ok"])
        np.save(os.path.join(self.src, "faces.npy"), self.part.astype(np.int32))
        bad = pn.run_glb(self.glb, self.part[:-1], ["Tabletop"], "столик", {"legs"})   # грани не совпали — ошибка в отчёте, не исключение
        self.assertIn("error", bad)


class BridgeFront(unittest.TestCase):
    """T-34/5: «перёд» для моста — единый свидетель front_axis (камера 04 с поправкой «развёрнут на 180°»), а не сырая камера; не решён — az=None (фасад/ручка воздерживаются), без ctx['front'] — как раньше."""

    def setUp(self):
        import trimesh
        import parts_to_npz as PNZ
        import front_axis as FA
        self.PNZ, self.FA = PNZ, FA
        self.td = tempfile.mkdtemp(prefix="t345-")
        V, F, UV = FA._box4()
        sc = trimesh.Trimesh(vertices=V, faces=F, process=False, visual=trimesh.visual.TextureVisuals(uv=UV))
        self.glb = os.path.join(self.td, "box.glb")
        sc.export(self.glb)
        self.vis = os.path.join(self.td, "06-visible")
        os.makedirs(self.vis)
        from PIL import Image
        kn = np.zeros((100, 400), np.uint8)
        kn[:, 200:300] = 255                                              # известна грань −Z: камера на +Z смотрит на ЗАД
        Image.fromarray(kn).save(os.path.join(self.vis, "known.png"))
        self.check06 = os.path.join(self.vis, "check.json")
        json.dump({"extra": {"camera": {"az": 0.0}}}, open(self.check06, "w"))

    def test_flipped_camera_needs_second_witness(self):
        ctx = {"cam_az": 0.0, "front": {"glb": self.glb, "check06": self.check06}}
        az, rep = self.PNZ.bridge_front(ctx)
        self.assertEqual(az, 0.0)                                          # только доли известного — одного свидетеля мало (R-FRONT-PHOTO-WITNESS): перёд = камера
        json.dump({"extra": {"camera": {"az": 0.0}, "front_check": {"edge_agree": 0.3}}}, open(self.check06, "w"))
        az2, rep2 = self.PNZ.bridge_front(ctx)
        self.assertEqual(az2, 180.0)                                       # + кромки позы 04 хуже edge_ref (второй свидетель) → развёрнуто: az+180
        self.assertIn(rep2["source"], ("camera04_flipped", "known_share"))     # квадратный в плане макет — «перёд» по долям известного, θ тот же

    def test_no_front_ctx_keeps_raw_camera(self):
        az, rep = self.PNZ.bridge_front({"cam_az": 37.0})
        self.assertEqual((az, rep["source"]), (37.0, "camera04_raw"))
        self.assertEqual(self.PNZ.bridge_front({})[0], None)

    def test_unresolved_front_gives_no_az(self):
        az, rep = self.PNZ.bridge_front({"cam_az": 0.0, "front": {"glb": os.path.join(self.td, "нет.glb"), "check06": self.check06}})
        self.assertIsNone(az)                                              # входов нет → не гадаем по сырой камере
        self.assertTrue(any(str(f).startswith("front_unknown") for f in rep["flags"]))

    def test_convert_writes_front_into_report_only(self):
        import trimesh
        v, f, part = table()
        glb = os.path.join(self.td, "t.glb")
        trimesh.Trimesh(vertices=v, faces=f, process=False).export(glb)
        src = os.path.join(self.td, "src")
        os.makedirs(src)
        np.save(os.path.join(src, "faces.npy"), part.astype(np.int32))
        json.dump({"names": ["Tabletop", "Leg", "Leg", "Leg", "Leg"]}, open(os.path.join(src, "meta.json"), "w"))
        out = os.path.join(self.td, "o")
        ctx = {"product_role": "столик", "channels": ["legs"], "channel_classes": {}, "front": {"glb": os.path.join(self.td, "нет.glb"), "check06": self.check06}}
        r = self.PNZ.convert(src, glb, out, "fine", ctx)
        self.assertTrue(r["ok"])
        rep = json.load(open(os.path.join(out, "roles-bridge.json")))
        self.assertIn("front", rep)                                        # отчёт моста: чем решён перёд
        self.assertNotIn("role", json.load(open(os.path.join(out, "parts.json")))["parts"][0])   # dry: parts.json без ролей


class GeometryFallback(unittest.TestCase):
    """T-20261124-03: геометрический запас моста — крупная часть не остаётся «без роли» (строки журнала #199, #206, #207). Типы, а не товары: синтетика комод/стол из параллелепипедов."""

    def chest(self):
        """Комод: корпус (самая крупная часть), фасадная плита, «ножка», оторванная от пола."""
        v, f, part = assemble([box(0, 0.5, 0, 1.0, 0.8, 0.5, n=16), box(0, 0.5, 0.27, 0.9, 0.5, 0.04, n=8), box(0.4, 0.3, 0.0, 0.05, 0.15, 0.05, n=4)])
        return v, f, part, feats(v, f, part, {0: "body", 1: "body", 2: "thin"})

    def test_facade_by_name_failing_geometry_becomes_body_same_channel(self):
        _, _, _, ft = self.chest()
        names = {0: "Drawer", 1: "Door Panel", 2: "Leg"}
        r = pn.bridge_roles(names, ft, TBL_ON, RR, "комод", {"legs"})
        self.assertEqual(r[0]["role"], "body")                                # самая крупная часть с именем «Drawer»: фасад слит с корпусом (forbid is_largest) → корпус
        self.assertEqual(r[0]["material_channel"], RR["roles"]["body"]["material_channel"])
        self.assertIn("геометрия не подтвердила", r[0]["role_why"])
        self.assertEqual(r[2]["role"], "unknown")                             # «Leg» без касания пола: канал ножек, корпусом не подменяем
        self.assertEqual(r[2]["unknown_reason"], "name_geometry")
        ro = pn.bridge_roles(names, ft, TBL_OFF, RR, "комод", {"legs"})
        self.assertEqual((ro[0]["role"], ro[0]["unknown_reason"]), ("unknown", "name_geometry"))   # выключатель: как до правки

    def test_to_body_not_where_body_is_not_allowed(self):
        _, _, _, ft = self.chest()
        r = pn.bridge_roles({0: "Drawer", 1: "Door Panel", 2: "Leg"}, ft, TBL_ON, RR, "стол обеденный", {"legs"})
        self.assertNotEqual(r[0]["role"], "body")                             # у стола body нет: фасад столу не ставим
        r2 = pn.bridge_roles({0: "Drawer", 1: "Door Panel", 2: "Leg"}, ft, TBL_ON, RR, "люстра", set())
        self.assertNotIn("body", {r2[p]["role"] for p in r2})                 # у типа без канала частей — тоже

    def test_generic_names_of_a_table_get_top_and_legs_by_form(self):
        v, f, part = table()
        ft = feats(v, f, part, KINDS5)
        names = {0: "Horizontal Panel", 1: "Base", 2: "Base", 3: "Base", 4: "Base"}
        r = pn.bridge_roles(names, ft, TBL, RR, "стол обеденный", {"legs"})
        self.assertEqual(r[0]["role"], "top")
        self.assertEqual([r[p]["role"] for p in (1, 2, 3, 4)], ["legs"] * 4)
        self.assertEqual(pn.summarize(ft, r, TBL)["known_role_area_share"], 1.0)
        r0 = pn.bridge_roles(names, ft, TBL_OFF, RR, "стол обеденный", {"legs"})
        self.assertEqual({r0[p]["unknown_reason"] for p in r0}, {"body_scope"})   # как было: столу «Base»/«Horizontal Panel» роли не давали

    def test_generic_name_follows_the_form_not_the_name(self):
        top = box(0, 1.0, 0, 1.0, 0.06, 1.0, n=40)                            # одна из четырёх опор оторвана от пола: ножкой по форме не станет — тонкая вставка под плитой = каркас (frame)
        legs = [box(x, 0.485 + (0.1 if i == 0 else 0.0), z, 0.05, 0.97 - (0.2 if i == 0 else 0.0), 0.05, n=4) for i, (x, z) in enumerate([(-0.45, -0.45), (-0.45, 0.45), (0.45, -0.45), (0.45, 0.45)])]
        v, f, part = assemble([top] + legs)
        ft = feats(v, f, part, KINDS5)
        r = pn.bridge_roles({0: "Horizontal Panel", 1: "Base", 2: "Base", 3: "Base", 4: "Base"}, ft, TBL, RR, "стол обеденный", {"legs"})
        self.assertEqual(r[0]["role"], "top")
        self.assertEqual(r[1]["role"], "frame")
        self.assertEqual([r[p]["role"] for p in (2, 3, 4)], ["legs"] * 3)
        big = assemble([box(0, 0.5, 0, 1.0, 0.8, 0.5, n=16)])                  # объёмная часть «Base» у стола: ни столешница, ни ножки, ни каркас — body_scope, корпус столу не ставим
        r2 = pn.bridge_roles({0: "Base"}, feats(*big, {0: "body"}), TBL, RR, "стол обеденный", {"legs"})
        self.assertEqual((r2[0]["role"], r2[0]["unknown_reason"]), ("unknown", "body_scope"))

    def apron_table(self, apron_top=0.95, apron_h=0.08):
        """Стол с царгой: плита наверху (0), четыре ножки на полу (1–4) и царга — тонкая плита под столешницей (5), не на полу и не самая крупная."""
        top = box(0, 1.0, 0, 1.0, 0.06, 1.0, n=40)
        legs = [box(x, 0.485, z, 0.05, 0.97, 0.05, n=4) for x in (-0.45, 0.45) for z in (-0.45, 0.45)]
        apron = box(0, apron_top - apron_h / 2 - 0.03, 0, 0.8, apron_h, 0.8, n=12)
        return assemble([top] + legs + [apron])

    def test_table_apron_named_frame_gets_frame_by_position(self):
        """T-20261124-03/2: «Table Frame» — царга под столешницей (kind=body, не на полу, не самая крупная, висит в верхней половине) → frame; ножки и столешница не задеты."""
        v, f, part = self.apron_table()
        kinds = {**KINDS5, 5: "body"}
        ft = feats(v, f, part, kinds)
        names = {0: "Surface Panel", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg", 5: "Table Frame"}
        r = pn.bridge_roles(names, ft, TBL, RR, "стол обеденный", {"legs"})
        self.assertEqual(r[5]["role"], "frame")
        self.assertEqual(r[5]["material_channel"], "legs")                     # у стола frame красится каналом ножек («материал каркаса в каталоге входит в legs»), а не глобальным каналом frame
        self.assertNotEqual(r[5]["material_channel"], RR["roles"]["frame"]["material_channel"])
        self.assertEqual(r[0]["role"], "top")
        self.assertEqual([r[p]["role"] for p in (1, 2, 3, 4)], ["legs"] * 4)
        self.assertEqual(pn.summarize(ft, r, TBL)["known_role_area_share"], 1.0)

    def test_frame_by_position_rejects_floor_part_and_top_slab(self):
        v, f, part = self.apron_table()
        ft = feats(v, f, part, {**KINDS5, 5: "body"})
        # «Table Frame» на самой плите верха (нижний квантиль ≥ 0,98) и «Table Frame» на ножке (на полу) — frame не получают
        r_top = pn.bridge_roles({0: "Table Frame", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg", 5: "Table Frame"}, ft, TBL, RR, "стол обеденный", {"legs"})
        self.assertNotEqual(r_top[0]["role"], "frame")
        r_leg = pn.bridge_roles({0: "Tabletop", 1: "Table Frame", 2: "Leg", 3: "Leg", 4: "Leg", 5: "Table Frame"}, ft, TBL, RR, "стол обеденный", {"legs"})
        self.assertNotEqual(r_leg[1]["role"], "frame")                        # ножка стоит на полу — каркасом не станет (legs по форме у неё не выбирается именем)
        self.assertEqual(r_leg[5]["role"], "frame")

    def test_frame_rule_is_a_rule_of_table_group_only(self):
        """Правило положения — условие роли группы table: у корпусного (комод) имя «Frame» по этим условиям каркасом не станет."""
        v, f, part = self.apron_table()
        ft = feats(v, f, part, {**KINDS5, 5: "body"})
        r = pn.bridge_roles({0: "Frame", 1: "Frame", 2: "Frame", 3: "Frame", 4: "Frame", 5: "Frame"}, ft, TBL, RR, "комод", {"legs", "frame"})
        self.assertNotEqual(r[5]["role"], "frame")

    def test_disabled_block_equals_missing_block(self):
        v, f, part = table()
        ft = feats(v, f, part, KINDS5)
        no_block = json.loads(json.dumps(TBL))
        del no_block["geometry_fallback"]
        names = {0: "Horizontal Panel", 1: "Base", 2: "Leg", 3: "", 4: "Other"}
        a = pn.bridge_roles(names, ft, TBL_OFF, RR, "стол обеденный", {"legs"})
        b = pn.bridge_roles(names, ft, no_block, RR, "стол обеденный", {"legs"})
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_bad_roles_order_is_an_error(self):
        d = json.loads(json.dumps(TBL))
        d["geometry_fallback"]["unnamed"]["roles_order"] = ["top", "wheels"]
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
            json.dump(d, fh)
        try:
            with self.assertRaises(ValueError):
                pn.load_rules(fh.name)
        finally:
            os.unlink(fh.name)


class GeometryEnemies(unittest.TestCase):
    """Тесты-«враги» (Codex 24.11, ~/remlab-logs/t2403-1124/codex-roles-answer.md): безымянный фасад, стекло, фурнитура, боковина стола не получают чужую роль; запасные пути (to_body, unnamed) выключены по умолчанию."""

    def chest(self):
        """Корпус (самая крупная часть), фасадная плита, безымянная часть-«стекло» спереди, мелкая «фурнитура»."""
        v, f, part = assemble([box(0, 0.5, 0, 1.0, 0.8, 0.5, n=16), box(0, 0.5, 0.27, 0.9, 0.5, 0.04, n=8), box(0, 0.7, 0.30, 0.4, 0.3, 0.01, n=6), box(0.3, 0.3, 0.30, 0.06, 0.03, 0.03, n=3)])
        return feats(v, f, part, {0: "body", 1: "body", 2: "body", 3: "thin"})

    def test_risky_fallbacks_are_off_by_default(self):
        gf = TBL["geometry_fallback"]
        self.assertTrue(gf["enabled"])                                         # общий выключатель и generic_in_no_body_types действуют
        self.assertFalse(gf["to_body"]["enabled"])                             # «имя отвергнуто геометрией → body» — только отдельным решением
        self.assertFalse(gf["unnamed"]["enabled"])                             # «безымянная ≥2 % → роль/body» — тоже

    def test_unnamed_front_glass_hardware_stay_unknown_by_default(self):
        ft = self.chest()
        r = pn.bridge_roles({}, ft, TBL, RR, "комод", {"legs", "handles"})
        self.assertEqual({r[p]["role"] for p in r}, {"unknown"})              # безымянные фасад, «стекло», фурнитура — ни body, ни facade, ни handles
        self.assertEqual({r[p]["unknown_reason"] for p in r if r[p]["unknown_reason"] != "tiny"}, {"no_name"})

    def test_rejected_name_stays_unknown_by_default(self):
        ft = self.chest()
        r = pn.bridge_roles({0: "Drawer", 1: "Door Panel", 2: "Glass Door", 3: "Handle"}, ft, TBL, RR, "комод", {"legs", "handles"})
        self.assertEqual((r[0]["role"], r[0]["unknown_reason"]), ("unknown", "name_geometry"))   # самая крупная «Drawer»: слитый фасад не маскируем под body
        self.assertEqual(r[2]["unknown_reason"], "name_unknown")             # «стекло» — имени нет в таблице
        self.assertNotIn(r[3]["role"], ("body", "facade"))

    def test_to_body_never_swallows_other_channels_even_when_on(self):
        ft = self.chest()
        r = pn.bridge_roles({0: "Drawer", 1: "Door Panel", 2: "Glass Door", 3: "Handle"}, ft, TBL_ON, RR, "комод", {"legs", "handles"})
        self.assertNotEqual(r[3]["role"], "body")                              # ручки — другой канал (handles): корпусом не подменяются
        self.assertEqual(r[2]["unknown_reason"], "name_unknown")

    def side_panel_table(self):
        """Стол, у которого боковина — вертикальная плита до пола (часть 1), и обычная ножка (2)."""
        top = box(0, 1.0, 0, 1.0, 0.06, 1.0, n=40)
        panel = box(-0.45, 0.485, 0, 0.03, 0.97, 0.8, n=12)
        leg = box(0.45, 0.485, 0.45, 0.05, 0.97, 0.05, n=4)
        return assemble([top, panel, leg])

    def test_table_side_panel_is_not_a_leg(self):
        v, f, part = self.side_panel_table()
        ft = feats(v, f, part, {0: "body", 1: "body", 2: "thin"})
        for nm in ("Leg", "Base", "Support Structure"):
            r = pn.bridge_roles({0: "Tabletop", 1: nm, 2: "Leg"}, ft, TBL, RR, "стол обеденный", {"legs"})
            self.assertNotEqual(r[1]["role"], "legs", nm)                    # узкая боковина-плита (obb.slab) ножкой не станет ни по имени, ни по общему имени
            self.assertEqual(r[2]["role"], "legs")                            # настоящая ножка рядом — legs

    def test_table_legs_alt_rule_requires_non_slab(self):
        alts = RR["groups"]["table"]["roles"]["legs"]["alt_require"]
        self.assertTrue(any(c["f"] == "obb.slab" and c["v"] is False for grp in alts for c in grp))

    def test_role_channel_is_group_specific(self):
        self.assertEqual(pro.role_channel(RR, RR["groups"]["table"], "frame"), "legs")
        self.assertEqual(pro.role_channel(RR, RR["groups"]["case"], "frame"), RR["roles"]["frame"]["material_channel"])
        self.assertEqual(pro.role_channel(RR, None, "frame"), RR["roles"]["frame"]["material_channel"])
        self.assertEqual(pro.role_channel(RR, RR["groups"]["table"], "legs"), RR["roles"]["legs"]["material_channel"])

    def test_assign_roles_uses_table_frame_channel(self):
        v, f, part = GeometryFallback().apron_table()
        ft = feats(v, f, part, {**KINDS5, 5: "body"})
        out = pro.assign_roles(ft, RR, "стол обеденный", {"legs"})
        for p, o in out.items():
            if o["role"] == "frame":
                self.assertEqual(o["material_channel"], "legs")


class NameRelax(unittest.TestCase):
    """T-20261124-64: «Leg» стула — коническая наклонная ножка (up_q90 0,43–0,47, «касается тела» не всегда) → legs по ослабленной геометрии; не-ножки и другие группы не страдают."""

    def setUp(self):
        v, f, part = table()
        self.ft = feats(v, f, part, KINDS5)
        self.RR_ = RR
        self.on = json.loads(json.dumps(TBL))
        self.on["name_relax"]["enabled"] = True                                 # в rules выключено по умолчанию (решение директора 25.11): тесты включают явно

    def chair(self, over, product="стул", names=None, rules=None):
        ft = {p: dict(f) for p, f in self.ft.items()}
        ft[1] = {**ft[1], "kind": "thin", "floor_contact": True, "supports_body": False, "up_q90": 0.46, "obb": {**ft[1]["obb"], "thin_ratio": 0.15}, "area_share": 0.03, **over}
        return ft, pn.bridge_roles(names_of(names or {0: "Seat", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"}), ft, rules or self.on, RR, product, {"legs"})

    def test_conical_chair_leg_gets_legs_relaxed(self):
        _, r = self.chair({})
        self.assertEqual(r[1]["role"], "legs")
        self.assertTrue(r[1].get("relaxed"))
        self.assertGreaterEqual(r[1]["role_conf"], RR["decision"]["role_conf"]["matched"])
        self.assertIsNone(r[1]["unknown_reason"])

    def test_strict_pass_is_not_marked_relaxed(self):
        _, r = self.chair({"up_q90": 0.2, "supports_body": True})
        self.assertEqual(r[1]["role"], "legs")
        self.assertNotIn("relaxed", r[1])

    def test_not_on_floor_or_not_thin_or_too_tilted_stays_unknown(self):
        for over in ({"floor_contact": False}, {"kind": "body", "obb": {"thin_ratio": 0.8}}, {"up_q90": 0.7}, {"area_share": 0.3}):
            _, r = self.chair(over)
            self.assertEqual(r[1]["role"], "unknown", over)
            self.assertEqual(r[1]["unknown_reason"], "name_geometry", over)

    def test_only_listed_groups_and_switch_off_is_as_before(self):
        _, r_case = self.chair({}, product="комод")
        self.assertEqual(r_case[1]["role"], "unknown")                          # группа case в name_relax не перечислена
        off = json.loads(json.dumps(self.on))
        off["name_relax"]["enabled"] = False
        _, r_off = self.chair({}, rules=off)
        self.assertEqual(r_off[1]["role"], "unknown")                           # выключатель = как было
        self.assertEqual(r_off[1]["unknown_reason"], "name_geometry")

    def test_default_rules_have_relax_disabled(self):
        self.assertIs(TBL["name_relax"]["enabled"], False)                      # боевой 03 без замера по покраске роли стульев не меняет
        _, r = self.chair({}, rules=TBL)
        self.assertEqual(r[1]["role"], "unknown")

    def test_other_names_untouched(self):
        _, r2 = self.chair({}, names={0: "Seat", 1: "Backrest", 2: "Leg", 3: "Leg", 4: "Leg"})
        self.assertEqual(r2[1]["role"], "body")                                 # имя не «Leg» — решение прежнее, ослабление к нему не применяется
        self.assertNotIn("relaxed", r2[1])

    def test_bad_relax_rules_are_errors(self):
        bad = json.loads(json.dumps(TBL))
        bad["name_relax"]["nonexistent_role"] = {"groups": ["seating"]}
        path = os.path.join(tempfile.mkdtemp(), "bad.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(bad, fh)
        with self.assertRaises(ValueError):
            pn.load_rules(path)


class NoRuleOtherChannel(unittest.TestCase):
    """T-20261124-64: имя назвало роль чужого канала, у группы правила роли нет (рама лампы) → unknown:no_channel, а не name_geometry; роли основного канала и группы с правилом — как прежде."""

    def setUp(self):
        v, f, part = table()
        self.ft = feats(v, f, part, KINDS5)

    def run_b(self, names, product, channels, rules=None):
        return pn.bridge_roles(names_of(names), self.ft, rules or TBL, RR, product, set(channels))

    def test_lamp_other_frame_is_no_channel(self):
        r = self.run_b({0: "Other Frame", 1: "Bulb", 2: "Bulb", 3: "Bulb", 4: "Bulb"}, "лампа", {"shade"})
        self.assertEqual(r[0]["role"], "unknown")
        self.assertEqual(r[0]["unknown_reason"], "no_channel")
        self.assertEqual(r[0]["geometry_why"], "no_rule")                         # причина — в отчёте: у группы нет правила роли
        self.assertEqual(pn.summarize(self.ft, r, TBL)["known_role_area_share"], 0.0)   # знаменатель без no_channel пуст: роль не появилась, мерка не «выросла» на площади

    def test_switch_off_is_as_before(self):
        off = json.loads(json.dumps(TBL))
        off["no_rule_other_channel"]["enabled"] = False
        r = self.run_b({0: "Other Frame", 1: "Bulb", 2: "Bulb", 3: "Bulb", 4: "Bulb"}, "лампа", {"shade"}, rules=off)
        self.assertEqual(r[0]["unknown_reason"], "name_geometry")

    def test_main_channel_roles_are_not_touched(self):
        r = self.run_b({0: "Top Panel", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"}, "диван", {"legs"})   # у seating нет правила top, но top — основной канал: геометрию «не подтвердили» как прежде
        self.assertEqual(r[0]["unknown_reason"], "name_geometry")

    def test_group_with_rule_is_not_touched(self):
        r = self.run_b({0: "Frame", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"}, "стол обеденный", {"legs"})   # у table правило frame есть: решает геометрия
        self.assertNotEqual(r[0].get("geometry_why"), "no_rule")
        if r[0]["role"] == "unknown":
            self.assertNotEqual(r[0]["unknown_reason"], "no_channel")

    def test_case_frame_has_no_channel_too(self):
        r = self.run_b({0: "Frame", 1: "Handle", 2: "Handle", 3: "Handle", 4: "Handle"}, "комод", {"legs", "handles"})   # корпусной мебели «каркас» каталог не называет — то же правило
        self.assertEqual(r[0]["unknown_reason"], "no_channel")

    def test_rule_is_on_by_default(self):
        self.assertIs(TBL["no_rule_other_channel"]["enabled"], True)


if __name__ == "__main__":
    unittest.main()

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

    def run_b(self, names, kinds=KINDS5, product="столик", channels=("legs",), v=None, **kw):
        ft = feats(self.v if v is None else v, self.f, self.part, kinds, **kw)
        return ft, pn.bridge_roles(names_of(names), ft, TBL, RR, product, set(channels))

    def test_leg_passes_geometry_gets_legs(self):
        ft, r = self.run_b({0: "Tabletop", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"})
        self.assertEqual(r[0]["role"], "top")
        for p in (1, 2, 3, 4):
            self.assertEqual(r[p]["role"], "legs")
            self.assertEqual(r[p]["material_channel"], RR["roles"]["legs"]["material_channel"])
            self.assertIsNone(r[p]["unknown_reason"])
        self.assertEqual(pn.summarize(ft, r, TBL)["known_role_area_share"], 1.0)

    def test_leg_failing_geometry_is_unknown_name_geometry(self):
        kinds = {**KINDS5, 1: "body"}                                         # одна «ножка» по форме объёмная (не тонкая и не средняя): геометрия роли legs её не принимает
        _, r = self.run_b({0: "Tabletop", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"}, kinds=kinds)
        self.assertEqual(r[1]["role"], "unknown")
        self.assertEqual(r[1]["unknown_reason"], "name_geometry")
        self.assertIn("geometry_why", r[1])
        for p in (2, 3, 4):
            self.assertEqual(r[p]["role"], "legs")                            # остальные ножки по имени и геометрии — legs
        self.assertEqual(r[0]["role"], "top")                                 # верх не зависит от ножек

    def test_leg_name_does_not_make_a_slab_a_leg(self):
        _, r = self.run_b({0: "Leg", 1: "Leg", 2: "Leg", 3: "Leg", 4: "Leg"})   # плита названа «Leg»: не тонкая, не отвесная — геометрия против
        self.assertEqual(r[0]["role"], "unknown")
        self.assertEqual(r[0]["unknown_reason"], "name_geometry")

    def test_empty_name_other_and_unlisted_are_unknown(self):
        _, r = self.run_b({0: "", 1: "Other", 2: "Warp Drive", 3: "Standard Table", 4: "Leg"})
        self.assertEqual((r[0]["role"], r[0]["unknown_reason"]), ("unknown", "no_name"))
        self.assertEqual((r[1]["role"], r[1]["unknown_reason"]), ("unknown", "not_a_part"))
        self.assertEqual((r[2]["role"], r[2]["unknown_reason"]), ("unknown", "name_unknown"))   # имя вне таблицы — не молчком
        self.assertEqual((r[3]["role"], r[3]["unknown_reason"]), ("unknown", "not_a_part"))
        self.assertEqual(r[4]["role"], "legs")
        r2 = pn.bridge_roles({0: "  Tabletop "}, {0: feats(self.v, self.f, self.part, KINDS5)[0]}, TBL, RR, "столик", {"legs"})
        self.assertEqual(r2[0]["role"], "top")                                # пробелы по краям имени не мешают

    def test_missing_name_for_part_is_no_name(self):
        ft = feats(self.v, self.f, self.part, KINDS5)
        r = pn.bridge_roles({}, ft, TBL, RR, "столик", {"legs"})
        for p in ft:
            self.assertEqual(r[p]["unknown_reason"], "no_name")

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


if __name__ == "__main__":
    unittest.main()

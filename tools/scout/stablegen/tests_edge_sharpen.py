"""Тесты выпрямления кромок (T-20261121-175): синтетические формы, без файлов и без ID товаров. Запуск: python3 tools/scout/stablegen/tests_edge_sharpen.py"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import remlab_tmp  # noqa: E402
remlab_tmp.use("tests_edge_sharpen")
import edge_sharpen as E  # noqa: E402


def grid_box(n=60, ripple=0.0015, seed=1):
    """Коробка 1×0.6×0.8 из сетки n×n на грань, швы совпадают точно (склейка), потом каждая вершина получает шум `ripple` (доля 1) по всем осям — рябь плоскостей и волна кромок."""
    rng = np.random.default_rng(seed)
    dims = np.array([1.0, 0.6, 0.8])
    V, F, base = [], [], 0
    for axis in range(3):
        for sign in (-1, 1):
            a, b = [i for i in range(3) if i != axis]
            u, v = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n), indexing="ij")
            P = np.zeros((n * n, 3))
            P[:, a] = u.ravel() * dims[a]
            P[:, b] = v.ravel() * dims[b]
            P[:, axis] = dims[axis] if sign > 0 else 0.0
            idx = np.arange(n * n).reshape(n, n)
            t1 = np.stack([idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel()], 1)
            t2 = np.stack([idx[:-1, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()], 1)
            Ft = np.concatenate([t1, t2])
            nrm = np.cross(P[Ft[:, 1]] - P[Ft[:, 0]], P[Ft[:, 2]] - P[Ft[:, 0]]).mean(0)
            if nrm[axis] * sign < 0:
                Ft = Ft[:, ::-1]
            V.append(P)
            F.append(Ft + base)
            base += n * n
    V, F = E.weld(np.concatenate(V), np.concatenate(F), 1e-9)
    V = V + rng.normal(0, ripple, V.shape)
    return V, F


def rules(**kw):
    r = E.load_rules()
    r.update(kw)
    return r


class T(unittest.TestCase):
    def test_rules_ok(self):
        self.assertEqual(E.check(), 0)

    def test_box_flattened(self):
        V, F = grid_box()
        R = rules(tol_plane=0.004)
        planes, ctx = E.find_planes(V, F, R)
        self.assertGreaterEqual(len(planes), 6)
        before = E.measure(V, F, planes, R)
        V2, kind, rep = E.sharpen(V, F, planes, R, ctx)
        after = E.measure(V2, F, planes, R)
        self.assertEqual(rep["flipped_after"], 0)
        self.assertLess(after["ripple_std_pct"], before["ripple_std_pct"] / 2)
        self.assertLessEqual(rep["shift_max_pct"], R["max_shift"] * 100 + 1e-9)
        self.assertEqual(len(V2), len(V))                                 # топология та же

    def test_non_flat_refused(self):
        rng = np.random.default_rng(3)
        # сфера: плоских кусков нет
        n = 80
        u, v = np.meshgrid(np.linspace(0, np.pi, n), np.linspace(0, 2 * np.pi, n), indexing="ij")
        P = np.stack([np.sin(u) * np.cos(v), np.sin(u) * np.sin(v), np.cos(u)], -1).reshape(-1, 3) * 0.5
        idx = np.arange(n * n).reshape(n, n)
        F = np.concatenate([np.stack([idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel()], 1), np.stack([idx[:-1, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()], 1)])
        V, F = E.weld(P, F, 1e-9)
        V2, kind, planes, ctx, rep = E.analyze(V, F, rules(), role="комод")
        self.assertIsNone(V2)
        self.assertIn("не корпусная", rep["refused"])

    def test_role_gate(self):
        V, F = grid_box(n=40)
        self.assertFalse(E.role_allowed("диван", rules()))
        V2, kind, planes, ctx, rep = E.analyze(V, F, rules(), role="диван")
        self.assertIsNone(V2)
        self.assertTrue(E.role_allowed("Комод", rules()))

    def test_milling_survives(self):
        # ниша 4 мм на фасаде (глубже допуска 0,3 % диагонали ≈ 3 мм при диагонали ~1,4) остаётся: зазор параллельных плоскостей ±
        V, F = grid_box(n=90, ripple=0.0005)
        diag = float(np.linalg.norm(np.ptp(V, axis=0)))
        depth = 0.012                                                       # ≈ 0,9 % диагонали — заведомо глубже допуска
        m = (np.abs(V[:, 2] - 0.8) < 1e-3) & (np.abs(V[:, 0] - 0.5) < 0.12) & (np.abs(V[:, 1] - 0.3) < 0.12)
        V = V.copy()
        V[m, 2] -= depth
        R = rules(tol_plane=0.003)
        planes, ctx = E.find_planes(V, F, R)
        V2, kind, rep = E.sharpen(V, F, planes, R, ctx)
        got = float(np.median(V2[m, 2]))
        self.assertLess(abs((0.8 - got) - depth), depth * 0.1)               # глубина ниши ±10 %


    # ───── режим «задняя панель» (T-20261123-41) ─────
    def _relief_back(self, amp=0.02, ripple=0.0005, n=70):
        """Коробка с рельефом на ЗАДУ (z≈0; камера смотрит с +z): две «рамки» шириной 0,2 выдавлены наружу (в −z) — как продублированные двери."""
        V, F = grid_box(n=n, ripple=ripple)
        back = (V[:, 2] < 0.05) & (V[:, 0] > 0.05) & (V[:, 0] < 0.95) & (V[:, 1] > 0.05) & (V[:, 1] < 0.55)
        stripe = back & (((V[:, 0] > 0.15) & (V[:, 0] < 0.35)) | ((V[:, 0] > 0.6) & (V[:, 0] < 0.8)))
        V = V.copy()
        V[stripe, 2] -= amp
        return V, F, back

    def test_back_relief_flattened(self):
        V, F, back = self._relief_back()
        R = rules()
        V2, moved, rep = E.back_panel(V, F, np.array([0.0, 0.0, 1.0]), R)
        self.assertTrue(rep["apply"], rep)
        self.assertGreater(float(V[back, 2].std()), 0.005)                      # рельеф был
        self.assertLess(float(V2[back, 2].std()), float(V[back, 2].std()) / 5)  # стал плоскостью
        self.assertEqual(float(np.abs(V2[V[:, 2] > 0.3] - V[V[:, 2] > 0.3]).max()), 0.0)     # лицо и верх тела не тронуты
        self.assertEqual(rep["flipped_after"], 0)
        self.assertLessEqual(rep["shift_max_pct"], R["back_panel"]["depth"] * 100 + 1e-9)

    def test_back_flat_or_domed_refused(self):
        V, F = grid_box(n=70, ripple=0.0005)                                   # зад уже плоский — рельефа нет
        _, _, rep = E.back_panel(V, F, np.array([0.0, 0.0, 1.0]), rules())
        self.assertFalse(rep["apply"])
        self.assertIn("рельефа нет", rep["reason"])
        V2 = V.copy()                                                           # зад — купол: плоскости нет, не корпусной
        m = V2[:, 2] < 0.05
        V2[m, 2] -= 0.3 * np.sin(np.pi * np.clip(V2[m, 0], 0, 1)) * np.sin(np.pi * np.clip(V2[m, 1] / 0.6, 0, 1))
        _, _, rep2 = E.back_panel(V2, F, np.array([0.0, 0.0, 1.0]), rules())
        self.assertFalse(rep2["apply"])
        self.assertIn("нет плоскости", rep2["reason"])

    def test_back_direction_and_roles(self):
        V, F, back = self._relief_back()
        _, _, rep = E.back_panel(V, F, np.array([0.0, 0.0, -1.0]), rules())     # камера с другой стороны — «зад» это z=0.8: он плоский
        self.assertFalse(rep["apply"])
        reg = BackPanelStage._reg({"комод": {"hidden_pattern": "body", "mode": "active"}, "диван": {"hidden_pattern": "same_fabric", "mode": "active"}})
        self.assertTrue(E.back_panel_gate("комод", reg, rules())["allowed"])                  # допуск — политика типа паспорта, своего списка ролей у режима нет
        self.assertFalse(E.back_panel_gate("диван", reg, rules())["allowed"])
        self.assertFalse(E.back_panel_gate("", reg, rules())["allowed"])
        self.assertNotIn("roles", rules()["back_panel"])
        c = E.camera_dir(0.0, 0.0)
        self.assertTrue(np.allclose(c, [0, 0, 1]) and np.allclose(E.camera_dir(90.0, 0.0), [1, 0, 0], atol=1e-9))

    @staticmethod
    def _write_glb(path, V, F):
        import json as _json
        import struct
        Vf = V.astype(np.float32)
        nrm = np.zeros_like(Vf)
        nrm[:, 2] = 1.0
        idx = F.astype(np.uint32).ravel()
        pos_b, nrm_b, idx_b = Vf.tobytes(), nrm.tobytes(), idx.tobytes()
        binc = pos_b + nrm_b + idx_b
        js = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1}, "indices": 2}]}],
              "accessors": [{"bufferView": 0, "componentType": 5126, "count": len(Vf), "type": "VEC3", "min": Vf.min(0).tolist(), "max": Vf.max(0).tolist()},
                            {"bufferView": 1, "componentType": 5126, "count": len(Vf), "type": "VEC3"}, {"bufferView": 2, "componentType": 5125, "count": len(idx), "type": "SCALAR"}],
              "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos_b)}, {"buffer": 0, "byteOffset": len(pos_b), "byteLength": len(nrm_b)},
                              {"buffer": 0, "byteOffset": len(pos_b) + len(nrm_b), "byteLength": len(idx_b)}], "buffers": [{"byteLength": len(binc)}]}
        jb = _json.dumps(js).encode()
        jb += b" " * (-len(jb) % 4)
        data = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(jb) + 8 + len(binc)) + struct.pack("<I4s", len(jb), b"JSON") + jb + struct.pack("<I4s", len(binc), b"BIN\x00") + binc
        with open(path, "wb") as fh:
            fh.write(data)

    def test_back_glb_roundtrip(self):
        import json as _json
        import struct
        import tempfile
        V, F, back = self._relief_back(n=40)
        Vf = V.astype(np.float32)
        idx = F.astype(np.uint32).ravel()
        with tempfile.TemporaryDirectory() as t:
            a, b = os.path.join(t, "a.glb"), os.path.join(t, "b.glb")
            self._write_glb(a, V, F)
            rep = E.back_panel_glb(a, b, 0.0, 0.0, rules())                     # азимут 0 → камера на +z
            self.assertTrue(rep["written"], rep)
            with open(b, "rb") as fh:
                out = fh.read()
            jl = struct.unpack_from("<I", out, 12)[0]
            js2 = _json.loads(out[20:20 + jl])
            bo = 20 + jl + 8
            pos2 = np.frombuffer(out, np.float32, len(Vf) * 3, bo + js2["bufferViews"][0]["byteOffset"]).reshape(-1, 3)
            idx2 = np.frombuffer(out, np.uint32, len(idx), bo + js2["bufferViews"][2]["byteOffset"])
            self.assertTrue(np.array_equal(idx, idx2))                          # топология та же
            self.assertLess(float(pos2[back, 2].std()), float(Vf[back, 2].std()) / 5)
            self.assertEqual(float(np.abs(pos2[Vf[:, 2] > 0.3] - Vf[Vf[:, 2] > 0.3]).max()), 0.0)
            self.assertAlmostEqual(js2["accessors"][0]["min"][2], float(pos2[:, 2].min()), places=5)    # границы позиций обновлены


    def test_back_protect_mask(self):
        V, F, back = self._relief_back()
        prot = np.zeros(len(V), bool)
        prot[np.flatnonzero(back)[::3]] = True                                  # часть вершин зада объявлена «фото» — не трогать никогда
        V2, moved, rep = E.back_panel(V, F, np.array([0.0, 0.0, 1.0]), rules(), protect=prot)
        self.assertTrue(rep["apply"], rep)
        self.assertEqual(rep["photo_touched"], 0)
        self.assertTrue(np.array_equal(V2[prot], V[prot]))
        self.assertGreater(rep["protected_in_near"], 0)

    def test_pose_edge_and_photo_guards(self):
        import tempfile
        import trimesh
        from PIL import Image
        self.assertAlmostEqual(E.pose_edge_min(), 0.5)                          # тот же порог, что у этапа камеры (camera-check.json)
        # заглушка этапа 6: коробка с несклеенными вершинами; грани +z — на пикселе prov=1, остальные — 0
        b = trimesh.creation.box((1.0, 0.6, 0.8))
        Vb = b.vertices[b.faces].reshape(-1, 3)
        Fb = np.arange(len(Vb)).reshape(-1, 3)
        uv = np.where((b.face_normals[:, 2] > 0.9)[:, None], np.array([0.1, 0.9]), np.array([0.9, 0.1]))
        uv = np.repeat(uv, 3, axis=0)
        m = trimesh.Trimesh(Vb, Fb, process=False)
        m.visual = trimesh.visual.TextureVisuals(uv=uv)
        prov = np.zeros((4, 4), np.uint8)
        prov[0, 0] = 1
        with tempfile.TemporaryDirectory() as t:
            vp, pp = os.path.join(t, "v.glb"), os.path.join(t, "prov.png")
            m.export(vp)
            Image.fromarray(prov).save(pp)
            pv, pn, pf = E.photo_faces(vp, pp, [1, 2, 3])
            self.assertEqual(pf, 2)
            self.assertGreater(float(pn[2]), 0.99)
            self.assertGreaterEqual(len(pv), 4)
            self.assertEqual(E.photo_faces(vp, pp, [7])[2], 0)
            # GLB туда-обратно: низкое согласие кромок камеры → отказ; фото-сторона не совпала с камерой → отказ
            Vr, Fr, back = self._relief_back(n=40)
            g = os.path.join(t, "a.glb")
            self._write_glb(g, Vr, Fr)
            rep = E.back_panel_glb(g, os.path.join(t, "o.glb"), 0.0, 0.0, rules(), pose_edge=0.2)
            self.assertFalse(rep["apply"] or rep["written"])
            self.assertIn("камере не верим", rep["reason"])
            rep = E.back_panel_glb(g, os.path.join(t, "o.glb"), 180.0, 0.0, rules(), pose_edge=0.9, photo=(vp, pp))
            self.assertFalse(rep["apply"] or rep["written"])
            self.assertIn("не совпадает с камерой", rep["reason"])
            self.assertLess(rep["photo_n_cam"], 0)

    def test_deterministic(self):
        V, F = grid_box(n=40)
        a = E.sharpen(V, F, E.find_planes(V, F, rules())[0], rules())[0]
        b = E.sharpen(V, F, E.find_planes(V, F, rules())[0], rules())[0]
        self.assertTrue(np.array_equal(a, b))


class BackPanelStage(unittest.TestCase):
    """Шаг `back_panel_stage` (T-43/❓2): разрешение по типу паспорта (body+active), след, откаты. Реестр — копия с подменой политики на заглушках; ID товаров нет."""

    @staticmethod
    def _reg(role_pol: dict):
        import copy
        import mesh_type_passports as MTP
        reg = copy.deepcopy(MTP.load())
        for role, pol in role_pol.items():
            t = MTP.normalize(role, reg)
            reg["types"][t]["paint"] = dict(pol)
        return reg

    def test_gate_body_continue_unknown(self):
        import back_panel_stage as BS
        reg = self._reg({"комод": {"hidden_pattern": "body", "mode": "active"}, "ваза": {"hidden_pattern": "continue", "mode": "active"},
                         "шкаф": {"hidden_pattern": "body", "mode": "observe"}})
        self.assertTrue(BS.gate("комод", reg)["allowed"])
        g = BS.gate("ваза", reg)
        self.assertFalse(g["allowed"])
        self.assertIn("continue", g["reason"])
        g = BS.gate("шкаф", reg)
        self.assertFalse(g["allowed"])
        self.assertIn("observe", g["reason"])
        g = BS.gate("неведомая вещь", reg)                                      # нет типа → unknown: воздержание с кодом причины
        self.assertFalse(g["allowed"])
        self.assertIn("unknown", g["reason"])
        self.assertFalse(BS.gate("", reg)["allowed"])
        self.assertFalse(BS.gate(None, reg)["allowed"])

    def _stage(self, t, check_extra, role, reg, glb_fn, with_prov=True, **kw):
        import json as _json
        import back_panel_stage as BS
        sku_dir = os.path.join(t, "s1")
        d = os.path.join(sku_dir, "06-visible")
        os.makedirs(d)
        V, F, _ = T._relief_back(None, n=40)
        T._write_glb(os.path.join(d, "visible.glb"), V, F)
        if with_prov:
            from PIL import Image
            Image.fromarray(np.zeros((4, 4), np.uint8)).save(os.path.join(d, "prov.png"))
        with open(os.path.join(d, "check.json"), "w", encoding="utf-8") as f:
            _json.dump({"extra": check_extra}, f)
        return BS.run_stage(t, "s1", role, reg=reg, glb_fn=glb_fn, **kw), d

    def test_stage_policy_refusal_leaves_files(self):
        import tempfile
        reg = self._reg({"комод": {"hidden_pattern": "body", "mode": "active"}, "ваза": {"hidden_pattern": "continue", "mode": "active"}})
        calls = []
        with tempfile.TemporaryDirectory() as t:
            doc, d = self._stage(t, {"camera": {"az": 0.0, "el": 0.0}, "front_check": {"edge_agree": 0.9}}, "ваза", reg, lambda *a, **k: calls.append(1) or {})
            self.assertFalse(doc["applied"])
            self.assertEqual(calls, [])                                         # расчёт даже не запускался
            self.assertIn("тип не допускает", doc["reason"])
            self.assertTrue(os.path.exists(os.path.join(d, "back_panel.json")))
            self.assertFalse(os.path.exists(os.path.join(d, "visible.pre-backpanel.glb")))

    def test_stage_body_applies_and_keeps_original(self):
        import hashlib
        import tempfile
        reg = self._reg({"комод": {"hidden_pattern": "body", "mode": "active"}})
        with tempfile.TemporaryDirectory() as t:
            doc, d = self._stage(t, {"camera": {"az": 0.0, "el": 0.0}, "front_check": {"edge_agree": 0.9}}, "комод", reg, None, with_prov=False)   # без prov.png: защита фото-стороны покрыта test_pose_edge_and_photo_guards
            self.assertTrue(doc["applied"], doc)
            self.assertEqual(doc["policy"]["hidden_pattern"], "body")
            keep, vis = os.path.join(d, "visible.pre-backpanel.glb"), os.path.join(d, "visible.glb")
            self.assertTrue(os.path.exists(keep))
            self.assertNotEqual(hashlib.md5(open(keep, "rb").read()).hexdigest(), hashlib.md5(open(vis, "rb").read()).hexdigest())
            first = hashlib.md5(open(vis, "rb").read()).hexdigest()
            doc2 = __import__("back_panel_stage").run_stage(t, "s1", "комод", reg=reg)      # повторный запуск идёт от исходного: тот же результат, не «выравнивание выровненного»
            self.assertTrue(doc2["applied"])
            self.assertEqual(hashlib.md5(open(vis, "rb").read()).hexdigest(), first)

    def test_stage_camera_trust_and_missing_inputs(self):
        import tempfile
        reg = self._reg({"комод": {"hidden_pattern": "body", "mode": "active"}})
        with tempfile.TemporaryDirectory() as t:
            doc, d = self._stage(t, {"camera": {"az": 0.0, "el": 0.0}}, "комод", reg, None)       # согласие кромок неизвестно → зад не трогаем
            self.assertFalse(doc["applied"])
            self.assertIn("согласие кромок", doc["reason"])
            self.assertFalse(os.path.exists(os.path.join(d, "visible.pre-backpanel.glb")))
        with tempfile.TemporaryDirectory() as t:
            doc, d = self._stage(t, {"camera": {"az": 0.0, "el": 0.0}, "front_check": {"edge_agree": 0.1}}, "комод", reg, None)   # камере не верим (порог — camera-check.json)
            self.assertFalse(doc["applied"])
            self.assertIn("камере не верим", doc["reason"])
        with tempfile.TemporaryDirectory() as t:
            doc, d = self._stage(t, {}, "комод", reg, None)
            self.assertFalse(doc["applied"])
            self.assertIn("камеры", doc["reason"])

    def test_rules_entry_in_check_json(self):
        import json as _json
        import tempfile
        import mesh_type_passports as MTP
        reg = self._reg({"комод": {"hidden_pattern": "body", "mode": "active"}, "ваза": {"hidden_pattern": "continue", "mode": "active"}})
        ex = {"camera": {"az": 0.0, "el": 0.0}, "front_check": {"edge_agree": 0.9}, "rules": [{"rule_id": "R-OTHER", "type": "комод", "applied": True}]}
        with tempfile.TemporaryDirectory() as t:
            doc, d = self._stage(t, ex, "комод", reg, None, with_prov=False)
            e = [x for x in _json.load(open(os.path.join(d, "check.json"), encoding="utf-8"))["extra"]["rules"] if x["rule_id"] == "R-BACKPANEL-06"]
            self.assertEqual(len(e), 1)
            self.assertTrue(e[0]["applied"] is True and e[0]["type"] == "комод" and e[0]["digest"] == MTP.paint_policy("комод", reg)["digest"], e)      # digest — из политики паспорта (тот же, что у 07 и оценки)
            self.assertEqual(len(_json.load(open(os.path.join(d, "check.json"), encoding="utf-8"))["extra"]["rules"]), 2)     # чужие записи целы
            __import__("back_panel_stage").run_stage(t, "s1", "ваза", reg=reg)                      # повтор с другой ролью заменяет запись, а не копит рядом (у товара один тип)
            rules_ = _json.load(open(os.path.join(d, "check.json"), encoding="utf-8"))["extra"]["rules"]
            mine = [x for x in rules_ if x["rule_id"] == "R-BACKPANEL-06"]
            self.assertEqual(len(mine), 1)
            self.assertIn("continue", mine[0]["abstain"])
            self.assertNotIn("applied", mine[0])
            self.assertEqual(len(rules_), 2)                                                       # чужая запись цела
        with tempfile.TemporaryDirectory() as t:                                                    # неизвестный тип: запись воздержания no_type (пустого охвата не бывает), type=null
            doc, d = self._stage(t, ex, "неведомая вещь", reg, None, with_prov=False)
            mine = [x for x in _json.load(open(os.path.join(d, "check.json"), encoding="utf-8"))["extra"]["rules"] if x["rule_id"] == "R-BACKPANEL-06"]
            self.assertEqual(len(mine), 1)
            self.assertIsNone(mine[0]["type"])
            self.assertIn("no_type", mine[0]["abstain"])
            self.assertTrue(os.path.exists(os.path.join(d, "back_panel.json")))
        with tempfile.TemporaryDirectory() as t:                                                    # запись делает единая функция rule_record.entry (тот же формат у всех этапов)
            import rule_record as RR
            doc, d = self._stage(t, ex, "комод", reg, None, with_prov=False)
            mine = [x for x in _json.load(open(os.path.join(d, "check.json"), encoding="utf-8"))["extra"]["rules"] if x["rule_id"] == "R-BACKPANEL-06"]
            self.assertEqual(mine, [RR.entry("R-BACKPANEL-06", "комод", True, reg=reg)])

    def test_stale_backup_not_used_after_new_06(self):
        import hashlib
        import tempfile
        import back_panel_stage as BS
        reg = self._reg({"комод": {"hidden_pattern": "body", "mode": "active"}})
        ex = {"camera": {"az": 0.0, "el": 0.0}, "front_check": {"edge_agree": 0.9}}
        with tempfile.TemporaryDirectory() as t:
            doc, d = self._stage(t, ex, "комод", reg, None, with_prov=False)
            self.assertTrue(doc["applied"])
            vis, keep = os.path.join(d, "visible.glb"), os.path.join(d, "visible.pre-backpanel.glb")
            V, F, _ = T._relief_back(None, n=40, amp=0.03)                                           # «06 прошёл заново»: другой visible.glb поверх нашего выхода
            T._write_glb(vis, V, F)
            new_in = hashlib.md5(open(vis, "rb").read()).hexdigest()
            doc2 = BS.run_stage(t, "s1", "комод", reg=reg)
            self.assertTrue(doc2["applied"], doc2)
            self.assertEqual(hashlib.md5(open(keep, "rb").read()).hexdigest(), new_in)               # копия — НОВЫЙ исходник, а не старая
        with tempfile.TemporaryDirectory() as t:                                                     # Salad: исходник не храним
            doc3, d = self._stage(t, ex, "комод", reg, None, with_prov=False, keep_original=False)
            self.assertTrue(doc3["applied"], doc3)
            self.assertFalse(os.path.exists(os.path.join(d, "visible.pre-backpanel.glb")))

    def test_no_ids_in_code_and_rules_wired(self):
        import json as _json
        import re
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "back_panel_stage.py"), encoding="utf-8").read()
        self.assertFalse(re.search(r"\b\d{5,}_\d{3,}\b", src))
        self.assertEqual(rules()["back_panel"]["paint_gate"], {"hidden_pattern": "body", "mode": "active"})
        ra = _json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rules", "paint-run-all.json"), encoding="utf-8"))
        self.assertTrue(any("back_panel_stage.py" in " ".join(s["argv"]) for s in ra["stages"]["06"]["steps"]))


if __name__ == "__main__":
    unittest.main()

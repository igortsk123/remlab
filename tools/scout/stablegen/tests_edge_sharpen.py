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
        self.assertTrue(E.back_panel_role_allowed("Комод", rules()))
        self.assertFalse(E.back_panel_role_allowed("диван", rules()))
        self.assertFalse(E.back_panel_role_allowed("", rules()))
        c = E.camera_dir(0.0, 0.0)
        self.assertTrue(np.allclose(c, [0, 0, 1]) and np.allclose(E.camera_dir(90.0, 0.0), [1, 0, 0], atol=1e-9))

    def test_back_glb_roundtrip(self):
        import json as _json
        import struct
        import tempfile
        V, F, back = self._relief_back(n=40)
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
        with tempfile.TemporaryDirectory() as t:
            a, b = os.path.join(t, "a.glb"), os.path.join(t, "b.glb")
            with open(a, "wb") as fh:
                fh.write(data)
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

    def test_deterministic(self):
        V, F = grid_box(n=40)
        a = E.sharpen(V, F, E.find_planes(V, F, rules())[0], rules())[0]
        b = E.sharpen(V, F, E.find_planes(V, F, rules())[0], rules())[0]
        self.assertTrue(np.array_equal(a, b))


if __name__ == "__main__":
    unittest.main()

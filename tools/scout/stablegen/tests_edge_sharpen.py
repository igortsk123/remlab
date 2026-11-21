"""Тесты выпрямления кромок (T-20261121-175): синтетические формы, без файлов и без ID товаров. Запуск: python3 tools/scout/stablegen/tests_edge_sharpen.py"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
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

    def test_deterministic(self):
        V, F = grid_box(n=40)
        a = E.sharpen(V, F, E.find_planes(V, F, rules())[0], rules())[0]
        b = E.sharpen(V, F, E.find_planes(V, F, rules())[0], rules())[0]
        self.assertTrue(np.array_equal(a, b))


if __name__ == "__main__":
    unittest.main()

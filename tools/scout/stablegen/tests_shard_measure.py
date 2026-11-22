"""Тесты мерки осколков (T-20261121-175/3д): синтетика, без файлов. Запуск: python3 tools/scout/stablegen/tests_shard_measure.py (нужен numpy)."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import shard_measure as S  # noqa: E402


def plate(n=60):
    g = np.linspace(0, 1, n)
    X, Y = np.meshgrid(g, g, indexing="ij")
    V = np.stack([X.ravel(), Y.ravel(), np.zeros(n * n)], 1)
    idx = np.arange(n * n).reshape(n, n)
    F = np.concatenate([np.stack([idx[:-1, :-1].ravel(), idx[1:, :-1].ravel(), idx[1:, 1:].ravel()], 1),
                        np.stack([idx[:-1, :-1].ravel(), idx[1:, 1:].ravel(), idx[:-1, 1:].ravel()], 1)])
    return V, F


class T(unittest.TestCase):
    def test_flat_plate_is_zero(self):
        V, F = plate()
        m = S.local_shards(V, F)
        self.assertEqual((m["dev60_faces"], m["dev90_faces"]), (0, 0))
        self.assertEqual(m["faces"], len(F))

    def test_flipped_faces_counted(self):
        V, F = plate()
        F2 = F.copy()
        bad = np.arange(0, len(F), 37)                                 # редкие перевёрнутые грани (не соседи друг другу)
        F2[bad] = F2[bad][:, [0, 2, 1]]
        m = S.local_shards(V, F2)
        self.assertGreaterEqual(m["dev90_faces"], int(0.95 * len(bad)))
        self.assertLessEqual(m["dev90_faces"], len(bad) + 5)

    def test_spikes_are_steep_not_flipped(self):
        V, F = plate()
        V2 = V.copy()
        pick = np.arange(0, len(V), 53)
        V2[pick, 2] += 0.05                                            # щепки: одиночные вершины выдвинуты — окружающие грани наклонены круто, но не вывернуты
        m = S.local_shards(V2, F)
        self.assertGreater(m["dev60_faces"], 20)
        self.assertEqual(m["dev90_faces"], 0)

    def test_split_vertices_still_neighbours(self):
        """Вершины размножены по граням (как у glTF с швами) — соседство всё равно находится по положению: перевёрнутая грань видна."""
        V, F = plate()
        F2 = F.copy()
        bad = np.arange(0, len(F), 37)
        F2[bad] = F2[bad][:, [0, 2, 1]]
        Vs, Fs = V[F2.ravel()], np.arange(len(F2) * 3).reshape(-1, 3)
        m = S.local_shards(Vs, Fs)
        self.assertGreaterEqual(m["dev90_faces"], int(0.95 * len(bad)))

    def test_smooth_bump_is_zero(self):
        V, F = plate()
        V2 = V.copy()
        V2[:, 2] = 0.02 * np.sin(V[:, 0] * 6) * np.cos(V[:, 1] * 6)    # плавная рябь — не осколки
        m = S.local_shards(V2, F)
        self.assertEqual(m["dev60_faces"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=1)

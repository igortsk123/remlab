"""Ш4 (T-181) — чистая часть three_layers.py: карта фото→грани, распространение по форме, зоны, края."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import three_layers as tl  # noqa: E402


def strip_adj(n):
    from scipy import sparse
    a = sparse.lil_matrix((n, n))
    for i in range(n - 1):
        a[i, i + 1] = a[i + 1, i] = 1
    return a.tocsr()


class FaceRegion(unittest.TestCase):
    def test_majority_conflict_and_invisible(self):
        ids = -np.ones((4, 4), np.int32)
        lab = -np.ones((4, 4), np.int32)
        ids[0, :4], lab[0, :4] = 0, [1, 1, 1, 1]                      # грань 0 — целиком область 1
        ids[1, :4], lab[1, :4] = 1, [1, 2, 2, 3]                      # грань 1: 2 из 4 — доля 0.5 < 0.6 → спор
        reg, tot, c = tl.face_region_from_photo(ids, lab, 3)
        self.assertEqual(list(reg), [1, -1, -2])                      # грань 2 не видна на фото
        self.assertEqual(c["faces_conflict"], 1)


class Propagate(unittest.TestCase):
    def test_flat_spreads_crease_blocks_conflict_marks(self):
        n = np.tile([0.0, 0.0, 1.0], (6, 1))
        n[3:] = [0.0, 1.0, 0.0]                                        # излом 90° между гранями 2 и 3
        reg = np.array([5, -2, -2, -2, -2, -2])
        lab, c = tl.propagate(reg, strip_adj(6), n)
        self.assertEqual(list(lab[:3]), [5, 5, 5])
        self.assertTrue((lab[3:] == -3).all())                          # за изломом метка не прошла
        reg2 = np.array([1, -2, 2, -2, -2, -2])
        lab2, _ = tl.propagate(reg2, strip_adj(6), np.tile([0.0, 0.0, 1.0], (6, 1)))
        self.assertEqual(lab2[1], -1)                                   # две разные метки претендуют → спор


class Zones(unittest.TestCase):
    def test_front_rear_top_under_interior(self):
        nrm = np.array([[0, 0, 1], [0, 0, -1], [0, 1, 0], [0, -1, 0], [1, 0, 0]], float)
        photo = np.array([0, -2, -2, -2, -2])                           # фото видит только грань 0 → камера смотрит вдоль +z
        z = tl.surface_zones(nrm, photo, np.ones(5), np.array([1, 1, 1, 1, 0], bool))
        self.assertEqual([tl.ZONES[i] for i in z], ["front", "rear", "top", "underside", "interior"])


class Edges(unittest.TestCase):
    def test_boundary_on_photo_edge(self):
        grey = np.zeros((40, 40), np.float32)
        grey[:, 20:] = 200
        obj = np.ones((40, 40), bool)
        on = np.where(np.arange(40)[None, :] < 20, 0, 1) * np.ones((40, 1), int)
        off = np.where(np.arange(40)[None, :] < 8, 0, 1) * np.ones((40, 1), int)
        self.assertGreater(tl.edge_agreement(on, grey, obj)["on_photo_edge"], 0.9)
        self.assertLess(tl.edge_agreement(off, grey, obj)["on_photo_edge"], 0.1)



def grid(nx, ny, x0=0.0, flip=False):
    """Плоская сетка nx×ny клеток в плоскости z=0 (нормали +z; flip — обход обратный → нормали −z)."""
    v, f = [], []
    for j in range(ny + 1):
        for i in range(nx + 1):
            v.append([x0 + i, j, 0.0])
    for j in range(ny):
        for i in range(nx):
            a, b, c, d = j * (nx + 1) + i, j * (nx + 1) + i + 1, (j + 1) * (nx + 1) + i, (j + 1) * (nx + 1) + i + 1
            f += [[a, b, d], [a, d, c]]
    f = np.array(f)
    if flip:
        f = f[:, ::-1]
    return np.array(v), f


def face_normals(v, f):
    t = v[f]
    n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    return n / np.maximum(1e-12, np.linalg.norm(n, axis=1, keepdims=True))


class OrientNormals(unittest.TestCase):
    def test_flipped_island_is_turned_to_camera_and_hidden_island_follows_neighbour(self):
        from scipy import sparse
        va, fa = grid(3, 3)
        vb, fb = grid(3, 3, x0=10.0, flip=True)                        # остров с перевёрнутым обходом, виден на фото
        vc, fc = grid(3, 3, x0=20.0, flip=True)                        # скрытый остров, тоже перевёрнут
        v = np.vstack([va, vb, vc])
        f = np.vstack([fa, fb + len(va), fc + len(va) + len(vb)])
        n = face_normals(v, f)
        seen = np.zeros(len(f), bool)
        seen[: len(fa) + len(fb)] = True
        adj = sparse.lil_matrix((len(f), len(f)))
        adj[len(fa) + len(fb) - 1, len(fa) + len(fb)] = adj[len(fa) + len(fb), len(fa) + len(fb) - 1] = 1  # сварной шов: видимый остров B ↔ скрытый C
        out, c = tl.orient_normals(v, f, n, adj.tocsr(), seen, np.array([0.0, 0.0, 1.0]))
        self.assertTrue((out[:, 2] > 0.9).all())
        self.assertEqual(c["islands"], 3)
        self.assertEqual(c["visible_facing_camera_after"], 1.0)
        self.assertLess(c["visible_facing_camera_before"], 1.0)


class DeepFaces(unittest.TestCase):
    def test_pixels_far_behind_surroundings_are_hole_faces(self):
        ids = np.zeros((40, 40), np.int32)
        depth = np.full((40, 40), 3.0, np.float32)
        ids[18:22, 18:22], depth[18:22, 18:22] = 1, 3.4                  # дыра: грань 1 видна сквозь оболочку на 0.4 глубже
        deep = tl.deep_faces(ids, depth, 2)
        self.assertEqual(list(deep), [False, True])


class SliverVote(unittest.TestCase):
    def test_tiny_face_takes_zone_of_neighbours_big_face_keeps_own(self):
        ids = np.zeros((80, 80), np.int32)
        ids[39:41, 39:41] = 1                                          # мелкая грань внутри плиты 0
        ids[:, 55:] = 2                                                # крупная грань 2 с иной зоной
        zone = np.array([0, 3, 1], np.int8)
        out, n = tl.sliver_vote(zone, ids, 3)
        self.assertEqual(list(out), [0, 0, 1])
        self.assertEqual(n, 1)


class PatchZones(unittest.TestCase):
    def test_noise_island_on_flat_plate_is_absorbed_and_hidden_part_is_interior(self):
        v, f = grid(20, 20)
        n = face_normals(v, f)
        n[100:103] = [0.0, 1.0, 0.0]                                    # три грани «смотрят вверх» посреди фасада
        from scipy import sparse
        import trimesh
        fa = trimesh.Trimesh(v, f, process=False).face_adjacency
        adj = sparse.coo_matrix((np.ones(len(fa)), (fa[:, 0], fa[:, 1])), shape=(len(f), len(f)))
        adj = (adj + adj.T).tocsr()
        areas = np.ones(len(f)) * 0.5
        seen = np.ones(len(f), bool)
        zone = tl.patch_zones(n, areas, adj, seen, np.array([0.0, 0.0, 1.0]), v[f].mean(axis=1))
        self.assertEqual(len(set(zone.tolist())), 1)                    # одна зона (front), крапин нет
        self.assertEqual(tl.ZONES[int(zone[0])], "front")


if __name__ == "__main__":
    unittest.main()

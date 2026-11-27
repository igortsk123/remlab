#!/usr/bin/env python3
"""Этап 03 «части меша» целиком — `parts_sam.run` на синтетическом столе (T-20261127-163/4): fail-closed, parts.npz только у прошедшего этапа, сверка порядка граней Blender ↔ меш.
SAM2 и Blender подменены (маски по высоте кадра; «облёт» собран из самого меша), всё остальное — настоящее: голосование, доводка, цвет, геометрия, роли, проверка, check.json.
Нужны numpy, scipy, pillow, trimesh. Запуск: python3 tools/assets/tests/test_parts_sam_run.py"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "..", "scout"))
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_parts_sam_run")
import material_parts as mp  # noqa: E402
import paint_check as pcheck  # noqa: E402
import parts_colour as pcol  # noqa: E402
import parts_refine as pr  # noqa: E402
import parts_roles as pro  # noqa: E402
import parts_sam as psam  # noqa: E402
import parts_vote as pv  # noqa: E402

SIZE = 128
SKU = "synthetic-table"


def build_mesh(dup_after: int | None = None, reverse: bool = True):
    """Стол: столешница + четыре ножки (боксы), цветная текстура (светлая и тёмная половины), UV — проекция на XZ. dup_after — вставить двойник грани после грани с этим номером."""
    import trimesh
    from PIL import Image

    parts = [trimesh.creation.box(extents=(1.0, 0.08, 0.6), transform=trimesh.transformations.translation_matrix((0, 0.76, 0)))]
    for sx in (-0.42, 0.42):
        for sz in (-0.22, 0.22):
            parts.append(trimesh.creation.box(extents=(0.07, 0.72, 0.07), transform=trimesh.transformations.translation_matrix((sx, 0.36, sz))))
    m = trimesh.util.concatenate(parts)
    v, f = np.asarray(m.vertices, dtype=np.float32), np.asarray(m.faces, dtype=np.int64)
    if dup_after is not None:
        f = f.tolist()
        f.insert(dup_after + 1, list(reversed(f[dup_after])) if reverse else list(f[dup_after]))
        f = np.array(f, dtype=np.int64)
    uv = np.stack([(v[:, 0] + 0.6) / 1.2, (v[:, 2] + 0.4) / 0.8], axis=1)
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    img[:, :32] = (200, 170, 120)
    img[:, 32:] = (60, 40, 30)
    mesh = trimesh.Trimesh(vertices=v, faces=f, process=False, validate=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv, material=trimesh.visual.material.PBRMaterial(baseColorTexture=Image.fromarray(img)))
    return mesh


def blender_like_fingerprints(mesh):
    """Что запишет облёт Blender: отпечатки граней без дублей, в повёрнутых осях (Y-вверх → Z-вверх)."""
    fm = pv.duplicate_face_map(mesh.faces)
    f = np.asarray(mesh.faces)[fm["keep"]] if fm["n_dup"] else np.asarray(mesh.faces)
    rot = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], dtype=np.float64)
    return pv.face_fingerprint(np.asarray(mesh.vertices, dtype=np.float64) @ rot.T, f), len(f)


class Harness:
    """Папка прогона + «облёт» + подмены SAM/Blender; run() — зовёт parts_sam.run и отдаёт (код, check.json, папка этапа)."""

    def __init__(self, mesh, **orbit_over):
        self.tmp = tempfile.mkdtemp(prefix="t163-4-")
        self.mesh = mesh
        self.run_dir = os.path.join(self.tmp, "run")
        self.orbit = os.path.join(self.tmp, "orbit")
        os.makedirs(self.orbit)
        fp, nb = blender_like_fingerprints(mesh)
        np.savez_compressed(os.path.join(self.orbit, "faces_fp.npz"), fp=fp)
        info = {"faces": nb, "mesh_objects": 1, "faces_fp": "faces_fp.npz", "views": [{"name": "00"}, {"name": "01"}]}
        info.update(orbit_over)
        json.dump(info, open(os.path.join(self.orbit, "orbit.json"), "w"))
        self.sdir = os.path.join(self.run_dir, SKU, "03-parts")

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def view(self):
        """Кадр спереди: центры граней → пиксели (x вправо, y вверх), всё видно; предмет — все пиксели под гранями."""
        V = np.asarray(self.mesh.vertices, dtype=np.float64)
        fm = pv.duplicate_face_map(self.mesh.faces)
        F = np.asarray(self.mesh.faces)[fm["keep"]] if fm["n_dup"] else np.asarray(self.mesh.faces)      # у Blender граней без дублей
        c = V[F].mean(axis=1)
        u = (SIZE / 2 + (c[:, 0] / 1.3) * SIZE / 2).astype(np.float32)
        v = (SIZE - 8 - (c[:, 1] / 0.9) * (SIZE - 16)).astype(np.float32)
        rgb = np.full((SIZE, SIZE, 3), 128, dtype=np.uint8)
        mask = np.zeros((SIZE, SIZE), dtype=bool)
        mask[int(v.min()) - 1:int(v.max()) + 2, int(u.min()) - 1:int(u.max()) + 2] = True
        return rgb, mask, u, v, np.ones(len(F), dtype=bool), np.ones(len(F), dtype=np.float32)

    def run(self, patches=(), one_mask=False):
        view = self.view()
        rgb, mask, u, v, vis, cos = view
        y_edge = int(SIZE - 8 - (0.72 / 0.9) * (SIZE - 16))
        top = mask.copy()
        top[y_edge:, :] = False
        legs = mask.copy()
        legs[:y_edge, :] = False
        masks = [top] if one_mask else [top, legs]
        args = argparse.Namespace(glb="synthetic.glb", orbit=self.orbit, run=self.run_dir, sku=SKU, limit=0, product_role=None, channels="", channel_classes="", cam_az=None)
        stack = [mock.patch.object(mp, "load_mesh", lambda p: self.mesh.copy()),
                 mock.patch.object(psam, "load_sam", lambda name: (None, None)),
                 mock.patch.object(psam, "sam_masks", lambda model, proc, rgb_, obj, rules: masks),
                 mock.patch.object(psam, "load_view", lambda orbit, name: view)] + list(patches)
        for p in stack:
            p.start()
        try:
            code = psam.run(args)
        finally:
            for p in reversed(stack):
                p.stop()
        chk = json.load(open(os.path.join(self.sdir, "check.json"), encoding="utf-8"))
        return code, chk

    def has(self, *rel):
        return os.path.exists(os.path.join(self.sdir, *rel))


def boom(*a, **k):
    raise RuntimeError("синтетическая поломка блока")


class PartsSamRun(unittest.TestCase):
    def setUp(self):
        self.h = None

    def tearDown(self):
        if self.h:
            self.h.close()

    def go(self, mesh=None, **kw):
        self.h = Harness(mesh if mesh is not None else build_mesh(), **kw.pop("orbit", {}))
        return self.h.run(**kw)

    # ---- основа: синтетика проходит, иначе остальные тесты ничего не доказывают
    def test_baseline_passes_and_writes_npz_json(self):
        code, chk = self.go()
        self.assertTrue(chk["passed"], chk["reason"])
        self.assertEqual(chk["extra"]["degraded"], [])
        self.assertTrue(self.h.has("parts.npz") and self.h.has("parts.json"))
        self.assertFalse(self.h.has("refused"))
        self.assertEqual(chk["outputs"], ["parts.npz", "parts.json"])
        self.assertEqual(len(np.load(os.path.join(self.h.sdir, "parts.npz"))["part"]), len(self.h.mesh.faces))

    # ---- (1) fail-closed: исключение блока = отказ с причиной
    def check_blocked(self, block, patch):
        code, chk = self.go(patches=[patch])
        self.assertFalse(chk["passed"], f"{block}: этап прошёл при сбое блока")
        self.assertEqual([d["block"] for d in chk["extra"]["degraded"]].count(block), 1, chk["extra"]["degraded"])
        self.assertIn(block, chk["reason"])
        self.assertIn("синтетическая поломка", chk["reason"])
        self.assertFalse(self.h.has("parts.npz") or self.h.has("parts.json"))
        self.assertTrue(os.path.exists(os.path.join(self.h.sdir, "refused", "parts.npz")))      # диагностика сохранена, но читатели её не видят
        self.assertEqual(chk["outputs"], [])
        st = pcheck.classify_stage("03-parts", chk, pcheck.load_rules() if hasattr(pcheck, "load_rules") else json.load(open(os.path.join(HERE, "..", "..", "scout", "rules", "paint-check.json"), encoding="utf-8")))
        self.assertEqual(st["status"], "refused")                                              # не «soft»: 07 не получит --parts-npz

    def test_refine_error_refuses(self):
        self.check_blocked("refine", mock.patch.object(pr, "refine", boom))

    def test_colours_error_refuses(self):
        self.check_blocked("colours", mock.patch.object(pcol, "part_colours", boom))

    def test_roles_error_refuses(self):
        self.check_blocked("roles", mock.patch.object(pro, "assign_roles", boom))

    def test_geometry_technical_error_refuses(self):
        self.check_blocked("geometry", mock.patch.object(mp, "analyze", boom))

    def test_lab_face_error_refuses(self):
        self.check_blocked("lab_face", mock.patch.object(pcol, "rgb_to_lab", boom))

    def test_geometry_unsure_is_legitimate(self):
        legs_none = lambda mesh, rec: np.zeros(len(mesh.faces), dtype=bool)
        code, chk = self.go(patches=[mock.patch.object(mp, "analyze", lambda mesh, rules: {"status": "unsure"}), mock.patch.object(mp, "legs_face_mask", legs_none)])
        self.assertTrue(chk["passed"], chk["reason"])
        self.assertEqual(chk["extra"]["degraded"], [])
        self.assertEqual(chk["extra"]["geometry"]["status"], "unsure")

    # ---- (2) parts.npz/json — только у прошедшего этапа, и устаревшее не переживает отказ
    def test_quality_refusal_leaves_no_npz_in_stage_dir(self):
        code, chk = self.go(one_mask=True)                                                      # одна область = одна часть < min_parts
        self.assertFalse(chk["passed"])
        self.assertFalse(self.h.has("parts.npz") or self.h.has("parts.json"))
        self.assertTrue(os.path.exists(os.path.join(self.h.sdir, "refused", "parts.json")))
        self.assertEqual(chk["outputs"], [])

    def test_stale_files_of_previous_run_are_removed_on_refusal(self):
        self.h = Harness(build_mesh())
        os.makedirs(self.h.sdir)
        for n in ("parts.npz", "parts.json"):
            open(os.path.join(self.h.sdir, n), "w").write("stale")
        code, chk = self.h.run(one_mask=True)
        self.assertFalse(chk["passed"])
        self.assertFalse(self.h.has("parts.npz") or self.h.has("parts.json"))

    def test_stale_files_removed_even_on_early_refusal_by_face_count(self):
        self.h = Harness(build_mesh(), faces=12345)
        os.makedirs(self.h.sdir)
        open(os.path.join(self.h.sdir, "parts.npz"), "w").write("stale")
        code, chk = self.h.run()
        self.assertEqual(code, 1)
        self.assertFalse(chk["passed"])
        self.assertFalse(self.h.has("parts.npz"))

    # ---- (3) сверка порядка граней и схемы дублей
    def test_reversed_pair_is_mapped_and_passes(self):
        mesh = build_mesh(dup_after=5)
        code, chk = self.go(mesh=mesh)
        self.assertTrue(chk["passed"], chk["reason"])
        z = np.load(os.path.join(self.h.sdir, "parts.npz"))
        self.assertEqual(len(z["part"]), len(mesh.faces))                                       # по граням МЕША, с дублем
        self.assertEqual(z["part"][5], z["part"][6])                                            # метка дубля = метке пары
        self.assertEqual(chk["extra"]["face_map"]["duplicate_faces"], 1)
        self.assertTrue(chk["extra"]["face_fingerprint"]["ok"])

    def test_fingerprint_mismatch_refuses_even_if_count_matches(self):
        h = Harness(build_mesh())
        fp = np.load(os.path.join(h.orbit, "faces_fp.npz"))["fp"].copy()
        fp[[3, 40]] = fp[[40, 3]]                                                               # Blender «перемешал» две грани: число то же
        np.savez_compressed(os.path.join(h.orbit, "faces_fp.npz"), fp=fp)
        self.h = h
        code, chk = h.run()
        self.assertEqual(code, 1)
        self.assertFalse(chk["passed"])
        self.assertIn("порядок граней Blender ≠ меша", chk["reason"])
        self.assertEqual(chk["extra"]["face_fingerprint"]["n_bad"], 2)
        self.assertFalse(h.has("parts.npz"))

    def test_missing_fingerprints_refuse(self):
        h = Harness(build_mesh())
        os.remove(os.path.join(h.orbit, "faces_fp.npz"))
        self.h = h
        code, chk = h.run()
        self.assertEqual(code, 1)
        self.assertFalse(chk["passed"])
        self.assertIn("нет отпечатков", chk["reason"])

    def test_multi_object_glb_refuses(self):
        code, chk = self.go(orbit={"mesh_objects": 2})
        self.assertEqual(code, 1)
        self.assertFalse(chk["passed"])
        self.assertIn("mesh-объектов", chk["reason"])
        self.assertFalse(self.h.has("parts.npz"))

    def test_same_winding_pair_refuses_with_reason(self):
        code, chk = self.go(mesh=build_mesh(dup_after=5, reverse=False))
        self.assertEqual(code, 1)
        self.assertFalse(chk["passed"])
        self.assertIn("вне схемы", chk["reason"])
        self.assertEqual(chk["extra"]["face_map"]["bad_groups"], 1)

    def test_group_of_three_refuses_with_reason(self):
        mesh = build_mesh(dup_after=5)
        f = np.asarray(mesh.faces).tolist()
        f.insert(7, list(f[5]))                                                                 # третья грань на тех же вершинах
        mesh.faces = np.array(f, dtype=np.int64)
        self.h = Harness(mesh)
        code, chk = self.h.run()
        self.assertEqual(code, 1)
        self.assertFalse(chk["passed"])
        self.assertIn("вне схемы", chk["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

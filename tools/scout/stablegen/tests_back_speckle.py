#!/usr/bin/env python3
"""Тесты мерки крапинок (tools/scout/back_speckle.py; T-20261123-43/3): синтетические листы, без файлов товаров и ID. Запуск: python3 tools/scout/stablegen/tests_back_speckle.py (numpy, scipy, Pillow)"""
import json
import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import remlab_tmp  # noqa: E402
remlab_tmp.use("tests_back_speckle")
import back_speckle as BS  # noqa: E402

SP, SH = BS.load_rules()
S, HP = int(SH["size"]), int(SH["header_px"])


def sheet(path, back_noise=0.0, seed=1, with_object=True):
    """Лист: белый, на виде «зад» — тёмно-красный прямоугольник; доля `back_noise` пикселей внутри — светлые точки (как крапинки)."""
    rng = np.random.default_rng(seed)
    im = np.full((S + HP, S * (len(SH["views"]) + 1), 3), 255, np.uint8)
    col = [i for i, v in enumerate(SH["views"]) if v["dtheta"] == SP["view_dtheta"]][0] + 1
    if with_object:
        cell = im[HP:, col * S:(col + 1) * S]
        cell[int(S * .25):int(S * .8), int(S * .1):int(S * .9)] = (160, 30, 10)
        h, w = cell.shape[:2]
        m = rng.random((h, w)) < back_noise
        inside = np.zeros((h, w), bool)
        inside[int(S * .25):int(S * .8), int(S * .1):int(S * .9)] = True
        cell[m & inside] = (230, 120, 90)
    Image.fromarray(im).save(path)
    return path


class T(unittest.TestCase):
    def test_rules_present_and_no_hardcode(self):
        for k in ("view_dtheta", "median_px", "dev_levels", "core_shrink", "white_sum", "share_max", "ratio_max"):
            self.assertIn(k, SP)
        with open(os.path.join(os.path.dirname(BS.__file__), "back_speckle.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotIn("0.002", src)

    def test_clean_back_passes_and_noisy_back_fails(self):
        with tempfile.TemporaryDirectory() as t:
            clean = BS.measure(sheet(os.path.join(t, "a.png"), 0.0), SP, SH)
            self.assertTrue(clean["ok"], clean)
            self.assertEqual(clean["share"], 0.0)
            noisy = BS.measure(sheet(os.path.join(t, "b.png"), 0.02), SP, SH)          # ≈2 % светлых точек — как у 0,65 % после медианы они дают долю выше порога
            self.assertFalse(noisy["ok"], noisy)
            self.assertGreater(noisy["share"], SP["share_max"])
            self.assertIn("порога", noisy["reason"])

    def test_edge_of_silhouette_not_counted(self):
        with tempfile.TemporaryDirectory() as t:
            m = BS.measure(sheet(os.path.join(t, "c.png"), 0.0), SP, SH)               # край предмета резкий (красный→белый): рамка сжата, край не считается выбросом
            self.assertEqual(m["share"], 0.0)

    def test_no_object_and_small_sheet_are_reported(self):
        with tempfile.TemporaryDirectory() as t:
            m = BS.measure(sheet(os.path.join(t, "d.png"), with_object=False), SP, SH)
            self.assertFalse(m["ok"])
            self.assertIn("предмета нет", m["reason"])
            Image.fromarray(np.full((50, 50, 3), 255, np.uint8)).save(os.path.join(t, "e.png"))
            with self.assertRaises(ValueError):
                BS.measure(os.path.join(t, "e.png"), SP, SH)

    def test_pair_compare_tolerates_textured_original(self):
        with tempfile.TemporaryDirectory() as t:
            clean, light, heavy = (sheet(os.path.join(t, n), x, seed=3) for n, x in (("p.png", 0.0), ("q.png", 0.002), ("r.png", 0.05)))
            self.assertTrue(BS.compare(clean, clean, SP, SH)["ok"])
            self.assertFalse(BS.compare(clean, heavy, SP, SH)["ok"])                   # чистый оригинал → крапинки после = брак
            noisy_before = BS.measure(heavy, SP, SH)["share"]
            self.assertGreater(noisy_before, SP["share_max"])                          # оригинал сам шумный: сам по себе выше порога…
            self.assertTrue(BS.compare(heavy, heavy, SP, SH)["ok"])                    # …но «не хуже себя» проходит
            self.assertFalse(BS.compare(light, heavy, SP, SH)["ok"])
            self.assertFalse(BS.compare(clean, sheet(os.path.join(t, "n.png"), with_object=False), SP, SH)["ok"])               # на «после» предмета нет — не «чисто»

    def test_cli_exit_code(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as t:
            ok_p, bad_p = sheet(os.path.join(t, "f.png"), 0.0), sheet(os.path.join(t, "g.png"), 0.03)
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.assertEqual(BS.main([ok_p]), 0)
                self.assertEqual(BS.main([ok_p, bad_p]), 1)
                self.assertEqual(BS.main([os.path.join(t, "нет.png")]), 1)
            lines = [json.loads(x) for x in buf.getvalue().splitlines()]
            self.assertTrue(lines[0]["ok"] and not lines[-1]["ok"])
            buf2 = io.StringIO()
            with redirect_stdout(buf2):
                self.assertEqual(BS.main(["--before", ok_p, ok_p]), 0)
                self.assertEqual(BS.main(["--before", ok_p, bad_p]), 1)
                self.assertEqual(BS.main(["--before", ok_p]), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)

"""Тесты правил «верх и кромки» этапа 6 (T-20261124-05): тон у границы острова, тонкая щель целиком, верх по моде, мерка скачка. Синтетика, секунды, бесплатно."""
import os
import sys
import unittest

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE), os.path.dirname(os.path.dirname(HERE))]
import tex_visible as TV  # noqa: E402

T = 160
ORANGE = np.array([225.0, 90.0, 40.0])
DARK = np.array([110.0, 35.0, 15.0])
LIGHT = np.array([235.0, 120.0, 70.0])


def flat(color=ORANGE):
    t = np.zeros((T, T, 3))
    t[:] = color
    return t


class LineGaps(unittest.TestCase):
    def setUp(self):
        self.occ = np.ones((T, T), bool)
        self.known = np.ones((T, T), bool)

    def test_continuous_line_unchanged(self):
        tex = flat()
        tex[:, 80] = DARK                                  # сплошная вертикальная щель между дверцами
        gaps, _col, info = TV.line_gaps(tex, self.occ, self.known)
        self.assertEqual(int(gaps.sum()), 0, info)
        self.assertEqual(info['line_ragged_share'], 0.0)

    def test_dashed_line_closed_along_line(self):
        tex = flat()
        for x in range(10, 150):                           # горизонтальная щель, разрывы по 3 текселя
            if (x // 4) % 2 == 0 or x % 7 == 0:
                tex[80, x] = DARK
        n_before = int((np.abs(tex - DARK).sum(2) < 1).sum())
        gaps, col, info = TV.line_gaps(tex, self.occ, self.known)
        self.assertGreater(int(gaps.sum()), 0, info)
        self.assertTrue(np.all(np.abs(col[gaps] - DARK) < 1), 'разрыв закрыт цветом линии')
        self.assertTrue(np.all(np.nonzero(gaps)[0] == 80), 'закрыто только вдоль линии, не поперёк')
        self.assertGreater(info['line_ragged_share'], 0.1)
        self.assertGreater(n_before, 0)

    def test_two_parallel_slits_not_merged(self):
        tex = flat()
        tex[70, 10:150] = DARK
        tex[76, 10:150] = DARK                             # две сплошные щели в 6 текселях друг от друга
        gaps, _col, info = TV.line_gaps(tex, self.occ, self.known)
        self.assertEqual(int(gaps.sum()), 0, info)

    def test_wide_shadow_not_a_line(self):
        tex = flat()
        tex[60:80, 60:100] = DARK                          # широкая тень — не щель
        gaps, _col, info = TV.line_gaps(tex, self.occ, self.known)
        self.assertEqual(int(gaps.sum()), 0, info)
        self.assertEqual(info['line_thin_px'], 0)

    def test_pattern_many_thin_lines_skipped(self):
        tex = flat()
        for r in range(4, 156, 8):                         # частая сетка тонких тёмных линий с разрывами — рисунок ткани
            tex[r, 4:156] = DARK
            tex[r, 40:44] = ORANGE
            tex[r, 100:104] = ORANGE
        gaps, _col, info = TV.line_gaps(tex, self.occ, self.known)
        self.assertEqual(int(gaps.sum()), 0, info)
        self.assertIn('line_skip', info)

    def test_unknown_texels_are_not_lines(self):
        tex = flat()
        tex[80, :] = DARK
        known = self.known.copy()
        known[:, :] = False                                # ничего не взято с фото — мерка не работает
        gaps, _col, info = TV.line_gaps(tex, self.occ, known)
        self.assertEqual(int(gaps.sum()), 0)


class IslandTone(unittest.TestCase):
    def setUp(self):
        self.occ = np.ones((T, T), bool)
        self.native = flat(ORANGE)
        self.tex = self.native.copy()
        self.known = np.zeros((T, T), bool)
        self.known[40:120, 40:120] = True                  # остров, взятый с фото
        self.tex[self.known] = LIGHT                       # фото светлее родного цвета (ΔL≈+8…10)

    def test_ring_shifts_toward_photo_and_decays(self):
        new, info = TV.island_tone(self.tex, self.native, self.occ, self.known, self.known)
        lab0, lab1 = TV._lab_img(self.tex), TV._lab_img(new)
        near, mid, far = lab1[80, 38, 0], lab1[80, 34, 0], lab1[80, 10, 0]
        base = lab0[80, 10, 0]
        self.assertGreater(near, base + 3.0, 'у границы тон подтянут к фото')
        self.assertGreater(near, mid)
        self.assertAlmostEqual(far, base, delta=0.5)       # дальше полосы — как было
        self.assertTrue(np.array_equal(new[self.known], self.tex[self.known]), 'известное не тронуто')
        self.assertGreater(info['edge_tone_texels'], 0)

    def test_jump_metric_drops(self):
        before = TV.island_jump(self.tex, self.occ, self.known, self.known)
        new, _ = TV.island_tone(self.tex, self.native, self.occ, self.known, self.known)
        after = TV.island_jump(new, self.occ, self.known, self.known)
        self.assertTrue(before['bad'])
        self.assertLess(abs(after['dL']), abs(before['dL']) * 0.6)
        self.assertLess(after['dE'], before['dE'] * 0.6)

    def test_no_known_no_change(self):
        none = np.zeros((T, T), bool)
        new, info = TV.island_tone(self.native, self.native, self.occ, none, none)
        self.assertTrue(np.array_equal(new, self.native))
        self.assertIsNone(TV.island_jump(self.native, self.occ, none, none)['dL'])

    def test_known_synth_not_repainted(self):
        synth = np.zeros((T, T), bool)
        synth[40:120, 120:140] = True                      # соседний кусок с тоном Ш3б — «известный», но не с фото
        new, _ = TV.island_tone(self.tex, self.native, self.occ, self.known, self.known | synth)
        self.assertTrue(np.array_equal(new[synth], self.tex[synth]))


class TopMode(unittest.TestCase):
    def _mesh(self, n_top, n_side):
        V, F = [], []
        for i in range(n_top):                             # горизонтальные грани (нормаль по y)
            b = len(V)
            V += [(i, 0, 0), (i + 1, 0, 0), (i, 0, 1)]
            F.append((b, b + 2, b + 1))
        for i in range(n_side):                            # вертикальные
            b = len(V)
            V += [(i, 0, 5), (i + 1, 0, 5), (i, 1, 5)]
            F.append((b, b + 1, b + 2))
        return np.array(V, float), np.array(F, np.int64)

    def test_top_pulled_to_median_side_untouched(self):
        V, F = self._mesh(40, 10)
        rng = np.random.default_rng(1)
        delta = rng.normal(0, 6, (50, 3))
        delta[:40] += np.array([4.0, 1.0, 1.0])
        painted = np.ones(50, bool)
        out, info = TV.top_mode(delta, painted, V, F, {'top_ny': 0.7, 'k': 0.7, 'min_faces': 20})
        self.assertLess(out[:40].std(0)[0], delta[:40].std(0)[0] * 0.5)
        self.assertAlmostEqual(float(np.median(out[:40, 0])), float(np.median(delta[:40, 0])), delta=0.5)   # низкочастотный тон сохранён
        self.assertTrue(np.array_equal(out[40:], delta[40:]))
        self.assertEqual(info['top_faces'], 40)

    def test_few_top_faces_untouched(self):
        V, F = self._mesh(5, 10)
        delta = np.random.default_rng(2).normal(0, 6, (15, 3))
        out, info = TV.top_mode(delta, np.ones(15, bool), V, F, {'top_ny': 0.7, 'k': 0.7, 'min_faces': 20})
        self.assertTrue(np.array_equal(out, delta))
        self.assertIn('top_skip', info)


class Switch(unittest.TestCase):
    def test_off_by_default_in_rules(self):
        if 'TEX_VISIBLE_ISLAND' not in os.environ:
            self.assertFalse(TV.ISL_ON, 'island_edge.enabled=false до решения директора (пробный режим)')
        for k in ('edge_tone', 'line_close', 'top_mode', 'jump'):
            self.assertIn(k, TV.ISL, k)


if __name__ == '__main__':
    unittest.main(verbosity=1)

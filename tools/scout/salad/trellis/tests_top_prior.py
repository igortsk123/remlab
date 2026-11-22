#!/usr/bin/env python3
"""Тесты правила верха столешницы (top_prior.decide / library_bin): чистая логика без GLB. Запуск: python3 tests_top_prior.py"""
import copy
import os
import sys
import unittest
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import top_prior as TP  # noqa: E402

RULES = TP.load_rules()
WOOD = [60.0, 10.0, 28.0]


def v(lab, n=1000, **kw):
    return dict({'lab': lab, 'n': n}, **kw)


class Decide(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(RULES['enabled'])
        self.assertEqual(RULES['mode'], 'dry')

    def test_class_other_routes_to_stage08_without_tone(self):
        r = TP.decide({'edge': v(WOOD), 'card': {'group': 'other', 'class': 'glass'}}, RULES)
        self.assertEqual((r['source'], r['route'], r['tone_lab']), ('unknown', 'stage08', None))

    def test_edge_and_plane_agree_is_continuation_high(self):
        r = TP.decide({'edge': v(WOOD), 'plane': v([61.0, 10.5, 27.0])}, RULES)
        self.assertEqual((r['source'], r['type'], r['confidence']), ('same_part_inference', 'continuation', 'high'))
        self.assertEqual(r['tone_lab'], WOOD)                      # главный голос — кромка

    def test_plane_only_is_low_confidence_not_refusal(self):
        r = TP.decide({'plane': v(WOOD)}, RULES)
        self.assertEqual((r['source'], r['confidence']), ('same_part_inference', 'low'))

    def test_edge_differs_from_plane_keeps_edge_with_hint(self):
        r = TP.decide({'edge': v([85.0, 0.0, 2.0]), 'plane': v([30.0, 5.0, 10.0])}, RULES)
        self.assertTrue(r['other_material_hint'])
        self.assertEqual((r['source'], r['type'], r['tone_lab']), ('same_part_inference', 'other_material_hint', [85.0, 0.0, 2.0]))

    def test_edge_plane_disagree_unknown_switch(self):
        rules = copy.deepcopy(RULES)
        rules['decision']['edge_plane_disagree'] = 'unknown'
        r = TP.decide({'edge': v([85.0, 0.0, 2.0]), 'plane': v([30.0, 5.0, 10.0])}, rules)
        self.assertEqual((r['source'], r['agree'], r['tone_lab']), ('unknown', False, None))

    def test_trellis_disagreement_gives_unknown(self):
        r = TP.decide({'edge': v(WOOD), 'trellis': v([85.0, 0.0, 2.0], bg_share=0.1)}, RULES)
        self.assertEqual((r['source'], r['agree'], r['tone_lab']), ('unknown', False, None))

    def test_trellis_background_texels_are_not_a_voice(self):
        r = TP.decide({'plane': v(WOOD), 'trellis': v([95.0, 0.0, 1.0], bg_share=0.9)}, RULES)
        self.assertTrue(r['trellis_unknown'])
        self.assertEqual((r['source'], r['tone_lab']), ('same_part_inference', WOOD))   # фон ТRELLIS не спорит с плоскостью
        self.assertFalse([c for c in r['candidates'] if c['voice'] == 'trellis'][0]['used'])

    def test_flat_trellis_alone_is_low_fallback_tone(self):
        r = TP.decide({'trellis': v([42.0, 24.0, 40.0], bg_share=0.0, flat_std=0.3)}, RULES)
        self.assertEqual((r['source'], r['confidence'], r['tone_lab']), ('trellis_prior', 'low', [42.0, 24.0, 40.0]))

    def test_flat_trellis_fill_is_not_a_voice(self):
        r = TP.decide({'edge': v(WOOD), 'plane': v(WOOD), 'trellis': v([42.0, 24.0, 40.0], bg_share=0.0, flat_std=0.3)}, RULES)
        self.assertTrue(r['trellis_unknown'])
        self.assertEqual((r['source'], r['confidence']), ('same_part_inference', 'high'))
        self.assertIn('плоская', [c for c in r['candidates'] if c['voice'] == 'trellis'][0]['why'])

    def test_textured_trellis_that_disagrees_still_vetoes(self):
        r = TP.decide({'edge': v(WOOD), 'trellis': v([85.0, 0.0, 2.0], bg_share=0.0, flat_std=9.0)}, RULES)
        self.assertEqual(r['source'], 'unknown')

    def test_trellis_only_is_low(self):
        r = TP.decide({'trellis': v(WOOD, bg_share=0.1, flat_std=8.0)}, RULES)
        self.assertEqual((r['source'], r['confidence']), ('trellis_prior', 'low'))

    def test_too_few_texels_means_unknown(self):
        r = TP.decide({'edge': v(WOOD, n=5), 'plane': v(WOOD, n=10)}, RULES)
        self.assertEqual((r['source'], r['tone_lab']), ('unknown', None))

    def test_sources_are_from_the_closed_list(self):
        for voices in ({'edge': v(WOOD)}, {'plane': v(WOOD)}, {}, {'trellis': v(WOOD, bg_share=0.0)}):
            self.assertIn(TP.decide(voices, RULES)['source'], TP.SOURCES)


class CardClass(unittest.TestCase):
    def test_composite_with_wood_words_gets_wood_pattern(self):
        c = TP.card_class({'role': 'стол обеденный', 'Материал столешницы': 'древесно-полимерный композит (поливуд)', 'name': 'Стол Древесный натуральный'}, RULES)
        self.assertEqual(c['group'], 'library')

    def test_plain_plastic_without_wood_words_is_decor(self):
        c = TP.card_class({'role': 'стол обеденный', 'Материал столешницы': 'Пластик', 'name': 'Стол белый'}, RULES)
        self.assertEqual(c['group'], 'decor')

    def test_glass_and_metal_go_to_stage08(self):
        for m in ('Стекло', 'Металл'):
            self.assertEqual(TP.card_class({'role': 'стол обеденный', 'Материал столешницы': m, 'name': 'Стол'}, RULES)['group'], 'other', m)

    def test_no_card_no_class(self):
        self.assertIsNone(TP.card_class(None, RULES)['group'])


class RealKnown(unittest.TestCase):
    def test_missing_known_png_gives_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(TP._real_known(d, 1), (None, None))

    def test_reads_known_png(self):
        import tempfile
        from PIL import Image
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, '06-visible'))
            m = np.zeros((4, 4), np.uint8); m[1, 2] = 255
            Image.fromarray(m).save(os.path.join(d, '06-visible', 'known.png'))
            k, src = TP._real_known(d, 1)
            self.assertEqual(src, 'stage06_known_png')
            self.assertTrue(k[0][1, 2] and not k[0][0, 0])


class CardDims(unittest.TestCase):
    def test_thickness_and_length_from_card(self):
        d = TP.card_dims({'Толщина столешницы': '1 см', 'name': 'Стол 160x90 Древесный'})
        self.assertEqual((d['thickness_cm'], d['length_cm'], d['width_cm']), (1.0, 160.0, 90.0))

    def test_millimetres_and_missing(self):
        self.assertEqual(TP.card_dims({'Толщина столешницы': '25 мм'})['thickness_cm'], 2.5)
        self.assertEqual(TP.card_dims(None), {'thickness_cm': None, 'length_cm': None, 'width_cm': None})


class PhotoBand(unittest.TestCase):
    def _img(self, noise: float, path: str) -> None:
        from PIL import Image
        rng = np.random.default_rng(0)
        a = np.full((200, 300, 4), 255, np.uint8)
        a[20:180, 20:280, :3] = 150
        a[20:40, 20:280, :3] = np.clip(150 + rng.normal(0, noise, (20, 260, 1)), 0, 255).astype(np.uint8)
        a[:, :, 3] = 0
        a[20:180, 20:280, 3] = 255
        Image.fromarray(a, 'RGBA').save(path)

    def test_smooth_band_below_noisy_band_and_missing_is_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self._img(0.0, os.path.join(d, 'a.png'))
            self._img(8.0, os.path.join(d, 'b.png'))
            s0, s1 = TP.photo_band_std(os.path.join(d, 'a.png'), RULES), TP.photo_band_std(os.path.join(d, 'b.png'), RULES)
            self.assertLess(s0, 0.2)
            self.assertGreater(s1, 1.0)
        self.assertIsNone(TP.photo_band_std(None, RULES))
        self.assertIsNone(TP.photo_band_std('/нет/такого.png', RULES))


class PhotoGroove(unittest.TestCase):
    def _img(self, seam_dL, path):
        from PIL import Image
        a = np.zeros((200, 300, 4), np.uint8)
        a[20:180, 20:280, :3] = 150
        a[20:180, 20:280, 3] = 255
        if seam_dL:
            for y in (27, 28):
                a[y, 20:280, :3] = 150 - seam_dL * 2.2
        Image.fromarray(a, 'RGBA').save(path)

    def test_seam_depth_from_photo_and_missing_is_none(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            self._img(0, os.path.join(d, 'a.png'))
            self._img(6, os.path.join(d, 'b.png'))
            s0, s1 = TP.photo_groove_dL(os.path.join(d, 'a.png'), RULES), TP.photo_groove_dL(os.path.join(d, 'b.png'), RULES)
            self.assertEqual(s0, RULES['pattern']['groove']['min_dL'])
            self.assertGreater(s1, s0 + 1.0)
            self.assertLessEqual(s1, RULES['pattern']['groove']['max_dL'])
        self.assertIsNone(TP.photo_groove_dL(None, RULES))


class PatternClass(unittest.TestCase):
    def test_polywood_is_planks_on_straight(self):
        r = TP.card_pattern({'m': 'древесно-полимерный композит (поливуд)'}, RULES)
        self.assertEqual((r['layout'], r['bin_classes'], r['word']), ('planks', ['straight'], 'поливуд'))

    def test_veneer_solid_ldsp_and_default(self):
        self.assertEqual(TP.card_pattern({'m': 'Шпон дуба'}, RULES)['layout'], 'none')
        self.assertEqual(TP.card_pattern({'m': 'массив бука'}, RULES)['bin_classes'], ['straight', 'swirl'])
        self.assertEqual(TP.card_pattern({'m': 'ЛДСП'}, RULES)['bin_classes'][0], 'flat')
        d = TP.card_pattern({'m': 'серый'}, RULES)
        self.assertEqual((d['bin_classes'], d['layout'], d['word']), (['straight'], 'none', None))

    def test_word_start_only(self):
        self.assertEqual(TP.card_pattern({'m': 'пластик'}, RULES)['word'], None)              # «тик» внутри слова не считается

    def test_bin_filtered_by_pattern_class(self):
        lib = {'items': {'S': {'lab': [60.0, 8.0, 24.0], 'family': 'wood', 'pattern_class': 'swirl'},
                         'T': {'lab': [70.0, 8.0, 24.0], 'family': 'wood', 'pattern_class': 'straight'},
                         'B': {'lab': [60.0, 8.0, 24.0], 'family': 'wood', 'pattern_class': 'blocks'}}}
        self.assertEqual(TP.library_bin([60.0, 8.0, 24.0], 'library', lib, {**RULES, 'library_max_de00': None}, 'wood_solid', ['straight'])['bin'], 'T')
        self.assertEqual(TP.library_bin([60.0, 8.0, 24.0], 'library', lib, {**RULES, 'library_max_de00': None}, 'wood_solid', ['straight', 'swirl'])['bin'], 'S')
        self.assertIsNone(TP.library_bin([60.0, 8.0, 24.0], 'library', lib, {**RULES, 'library_max_de00': None}, 'wood_solid', ['flat'])['bin'])


class UnknownKeep(unittest.TestCase):
    def test_no_tone_keeps_top(self):
        rules = TP.load_rules()
        base = [np.full((8, 8, 3), 40, np.uint8)]
        an = {'report': {'tone_lab': None, 'library': {'bin': None}}, 'geoms': [{}], 'top_all': [np.ones(1, bool)], 'size': None, 'ctr': None, 'voices': {}}
        out = TP.hypothesis_textures(an, rules, base, 100.0, None)
        self.assertTrue((out[0] == base[0]).all())
        self.assertIn('не тронут', an['report']['applied'])


class LibraryMaxDe(unittest.TestCase):
    def test_far_bin_becomes_flat(self):
        rules = TP.load_rules()
        lib = {'items': {'W1': {'family': 'wood', 'lab': [55.0, 15.0, 27.0], 'pattern_class': 'straight'}}}
        far = TP.library_bin([90.0, 0.0, 1.0], 'library', lib, rules, None, None)
        self.assertEqual(far['bin'], 'flat')
        near = TP.library_bin([54.0, 15.0, 26.0], 'library', lib, rules, None, None)
        self.assertEqual(near['bin'], 'W1')


class RetintNative(unittest.TestCase):
    class _Tx:
        def __init__(self, n):
            self.Q = np.zeros((n, 3))
            self.ti = np.arange(n)

    def _an(self, n, tone, tr_lab):
        return {'report': {'tone_lab': tone, 'library': {'bin': 'flat'}, 'candidates': [{'voice': 'trellis', 'used': True, 'lab': tr_lab}]},
                'top_all': [{'tx': self._Tx(n), 'top': np.ones(n, bool), 'kn': np.zeros(n, bool), 'gi': 0}], 'size': 1.0}

    def test_keeps_native_pattern_shifts_tone(self):
        import tex_coverage as TC
        rules = TP.load_rules()
        base = np.zeros((8, 8, 3), np.uint8)
        base[:, :4] = 80
        base[:, 4:] = 120
        lab0 = TC.rgb2lab(base.reshape(-1, 3))
        an = self._an(64, [float(lab0[:, 0].mean()) + 5.0, 0.0, 0.0], [float(lab0[:, 0].mean()), 0.0, 0.0])
        out = TP.hypothesis_textures(an, rules, [base], 100.0, None)
        lab1 = TC.rgb2lab(out[0].reshape(-1, 3))
        self.assertAlmostEqual(float(lab1[:, 0].mean() - lab0[:, 0].mean()), 5.0, delta=0.8)
        self.assertAlmostEqual(float(lab1[:, 0].std()), float(lab0[:, 0].std()), delta=0.8)   # рисунок (разброс) сохранён
        self.assertIn('сдвиг тона', an['report']['applied'])

    def test_off_when_trellis_not_used(self):
        rules = TP.load_rules()
        base = np.full((8, 8, 3), 100, np.uint8)
        an = self._an(64, [60.0, 0.0, 0.0], [60.0, 0.0, 0.0])
        an['report']['candidates'][0]['used'] = False
        out = TP.hypothesis_textures(an, rules, [base], 100.0, None)
        self.assertNotIn('applied', an['report'])
        self.assertEqual(out[0].shape, base.shape)


class Library(unittest.TestCase):
    lib = {'items': {'A': {'lab': [30.0, 10.0, 15.0], 'grain_axis': 'u', 'tile_cm': [40, 40]}, 'B': {'lab': [70.0, 8.0, 25.0], 'grain_axis': 'v', 'tile_cm': [80, 80]}}}

    def test_nearest_bin_by_tone(self):
        self.assertEqual(TP.library_bin([68.0, 9.0, 24.0], 'library', self.lib, RULES)['bin'], 'B')
        self.assertEqual(TP.library_bin([32.0, 9.0, 14.0], 'library', self.lib, RULES)['bin'], 'A')

    def test_chipboard_bin_not_for_solid_wood(self):
        lib = {'items': {'W': {'lab': [50.0, 8.0, 20.0], 'family': 'wood'}, 'C': {'lab': [70.0, 8.0, 25.0], 'family': 'chipboard'}}}
        self.assertEqual(TP.library_bin([71.0, 8.0, 25.0], 'library', lib, {**RULES, 'library_max_de00': None}, 'wood_solid')['bin'], 'W')
        self.assertEqual(TP.library_bin([71.0, 8.0, 25.0], 'library', lib, RULES, 'ldsp')['bin'], 'C')

    def test_decor_has_no_pattern_and_no_tone_no_bin(self):
        self.assertEqual(TP.library_bin([68.0, 9.0, 24.0], 'decor', self.lib, RULES)['bin'], 'flat')
        self.assertIsNone(TP.library_bin(None, 'library', self.lib, RULES)['bin'])

    def test_rules_have_no_product_ids(self):
        import json
        txt = json.dumps(RULES)
        self.assertNotRegex(txt, r'\d{5,}_\d{6,}')


if __name__ == '__main__':
    unittest.main(verbosity=1)

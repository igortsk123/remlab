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


class RimCut(unittest.TestCase):
    """Полоса edge режется до скачка цвета: фасад под светлой плитой в голос не попадает (правило типа «комод с контрастным верхом», Ш3в)."""
    G = RULES['geometry']

    def mk(self, rim_n=600, face_n=3000, rim_lab=(70.0, 4.5, 23.0), face_lab=(34.0, 0.0, 1.3), seed=1):
        rng = np.random.RandomState(seed)
        depth = np.concatenate([rng.uniform(0, 0.008, rim_n), rng.uniform(0.012, 0.03, face_n)])
        q = 0.2 - depth
        lab = np.vstack([np.tile(rim_lab, (rim_n, 1)), np.tile(face_lab, (face_n, 1))]) + rng.normal(0, 0.5, (rim_n + face_n, 3))
        return q, lab, np.ones(len(q), bool)

    def test_dark_facade_below_light_top_is_cut(self):
        q, lab, sel = self.mk()
        out, depth = TP.rim_cut(q, lab, sel, 0.2, self.G)
        self.assertIsNotNone(depth)
        self.assertLessEqual(depth, 0.012 + 1e-9)
        self.assertEqual(int(out.sum()), 600)                           # осталась только светлая кромка
        self.assertGreater(float(np.median(lab[out][:, 0])), 65.0)

    def test_uniform_wood_is_untouched(self):
        q, lab, sel = self.mk(rim_lab=(60.0, 10.0, 28.0), face_lab=(60.5, 10.2, 27.5))
        out, depth = TP.rim_cut(q, lab, sel, 0.2, self.G)
        self.assertIsNone(depth)
        self.assertEqual(int(out.sum()), len(q))

    def test_grain_noise_does_not_cut(self):
        rng = np.random.RandomState(3)
        q = 0.2 - rng.uniform(0, 0.03, 4000)
        lab = np.array([60.0, 10.0, 28.0]) + rng.normal(0, 3.0, (4000, 3))      # текстура дерева: разброс, но тот же тон
        out, depth = TP.rim_cut(q, lab, np.ones(4000, bool), 0.2, self.G)
        self.assertIsNone(depth)

    def test_split_cuts_plane_too(self):
        q, lab, sel = self.mk()
        edge = sel & (0.2 - q < 0.012)                                   # узкая полоса у верха
        plane = sel & (0.2 - q >= 0.004)                                 # полоса пониже, захватила и фасад
        e2, p2, depth = TP.rim_split(q, lab, edge, plane, 0.2, self.G)
        self.assertIsNotNone(depth)
        self.assertGreater(float(np.median(lab[e2][:, 0])), 65.0)
        self.assertGreater(float(np.median(lab[p2][:, 0])), 65.0)        # без среза plane выходил тёмным (фасад)
        self.assertLess(float(np.median(lab[plane][:, 0])), 60.0)

    def test_split_uniform_wood_untouched(self):
        q, lab, sel = self.mk(rim_lab=(60.0, 10.0, 28.0), face_lab=(60.5, 10.2, 27.5))
        edge, plane = sel & (0.2 - q < 0.01), sel & (0.2 - q >= 0.005)
        e2, p2, depth = TP.rim_split(q, lab, edge, plane, 0.2, self.G)
        self.assertIsNone(depth)
        self.assertEqual((int(e2.sum()), int(p2.sum())), (int(edge.sum()), int(plane.sum())))

    def test_split_off_when_rule_off(self):
        q, lab, sel = self.mk()
        cfg = dict(self.G, rim_de00=0)
        e2, p2, depth = TP.rim_split(q, lab, sel, sel, 0.2, cfg)
        self.assertIsNone(depth)
        self.assertEqual(int(e2.sum()), len(q))

    def test_too_few_texels_untouched(self):
        q, lab, sel = self.mk(rim_n=50, face_n=100)
        out, depth = TP.rim_cut(q, lab, sel, 0.2, self.G)
        self.assertIsNone(depth)

    def test_disabled_by_rule(self):
        q, lab, sel = self.mk()
        out, depth = TP.rim_cut(q, lab, sel, 0.2, dict(self.G, rim_de00=0))
        self.assertIsNone(depth)
        self.assertEqual(int(out.sum()), len(q))

    def test_sparse_layer_is_skipped_not_cut(self):
        q, lab, sel = self.mk(face_n=0)
        extra = np.array([[34.0, 0.0, 1.3]] * 5)                          # пять случайных тёмных текселей ниже — не фасад
        q2 = np.concatenate([q, np.full(5, 0.2 - 0.02)])
        lab2 = np.vstack([lab, extra])
        out, depth = TP.rim_cut(q2, lab2, np.ones(len(q2), bool), 0.2, self.G)
        self.assertIsNone(depth)

    def test_rule_has_no_ids(self):
        import inspect
        src = inspect.getsource(TP.rim_cut)
        self.assertNotRegex(src, r'\d{9,}')


class Seamless(unittest.TestCase):
    """Правило 22.11: узор верха кладётся без видимых стыков плитки — скачок L на стыке / рядом ≤ 1,3 (настоящие узоры библиотеки pat512, обе оси)."""
    LIMIT = 1.3

    def _pats(self):
        import json
        from PIL import Image
        import tex_coverage as TC
        root = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
        d = os.path.join(root, RULES['library_pat'])
        out = {}
        for k in sorted(json.load(open(os.path.join(root, RULES['library']), encoding='utf-8'))['items']):
            im = np.asarray(Image.open(os.path.join(d, k + '.jpg')).convert('RGB').resize((512, 512)), np.uint8)
            L = TC.rgb2lab(im.reshape(-1, 3)).reshape(512, 512, 3)
            out[k] = L - L.reshape(-1, 3).mean(0)
        return out

    def test_real_patterns_have_no_seam_jump(self):
        ov = RULES['pattern']['seam_overlap']
        self.assertTrue(0.08 <= ov[0] <= ov[1] <= 0.16)                       # перекрытие 8–16 % плитки (правило директора 22.11)
        self.assertEqual(RULES['pattern']['seam_max_jump'], self.LIMIT)
        pats = self._pats()
        self.assertGreaterEqual(len(pats), 28)
        before = {k: TP.seam_jump(p) for k, p in pats.items()}
        after = {k: TP.seam_jump(TP.seamless_pattern(p, ov)) for k, p in pats.items()}
        bad = {k: round(v, 2) for k, v in after.items() if v > self.LIMIT}
        self.assertEqual(bad, {}, f'стык виден: {bad} (до правки максимум {max(before.values()):.2f})')
        self.assertGreater(max(before.values()), self.LIMIT)                  # мерка ловит прежний шов: без неё тест ничего не доказывал бы

    def test_seam_is_continuous_and_not_a_mirror(self):
        rng = np.random.default_rng(1)
        p = rng.normal(size=(100, 100, 3))
        q = TP.seamless_pattern(p, [0.12, 0.12])
        self.assertEqual(q.shape, (88, 88, 3))                                   # перекрытие 12 из 100: плитка короче на 12 по каждой оси
        self.assertTrue(np.allclose(q[12:, 12:], p[12:88, 12:88]))                # середина плитки — без изменений
        q2 = TP.seamless_pattern(p, [0.08, 0.16])
        self.assertTrue(80 <= q2.shape[0] <= 92)
        self.assertLessEqual(TP.seam_jump(q2), TP.seam_jump(q) + 1e-9)             # из диапазона берётся лучшее (не хуже одного значения)
        self.assertTrue(np.array_equal(TP.seamless_pattern(p, [0.08, 0.16]), q2))  # детерминированно
        self.assertFalse(np.allclose(q[:, 0], q[:, -1][::-1]))                    # не зеркало
        self.assertLess(abs(float(q.std()) / float(p.std()) - 1.0), 0.15)         # контраст не просел и не вырос заметно
        self.assertTrue(np.array_equal(TP.seamless_pattern(p, 0.0), p))           # правило выключено — узор как был
        self.assertTrue(np.array_equal(TP.seamless_pattern(p, [0.5, 0.5]), p))     # перекрытие больше трети — не применяется


class Gutter(unittest.TestCase):
    """Желоб вокруг перекрашенного верха (линия на шве островков UV): непокрытые текселы рядом с перекрашенными дублируют их цвет, остальные — нет."""

    def test_gutter_follows_painted_only(self):
        t = 16
        img = np.zeros((t, t, 4), np.uint8)
        img[..., 3] = 255
        occ = np.zeros((t, t), bool)
        occ[4:8, 2:14] = True                     # островок A (перекрашен)
        occ[10:14, 2:14] = True                   # островок B (не трогали)
        img[occ, :3] = (200, 100, 50)
        painted = np.zeros((t, t), bool)
        painted[4:8, 2:14] = True
        img[painted, :3] = (10, 220, 30)
        n = TP.gutter_into(img, np.flatnonzero(occ.reshape(-1)), np.flatnonzero(painted.reshape(-1)), 2)
        self.assertGreater(n, 0)
        self.assertTrue((img[8, 5, :3] == (10, 220, 30)).all())                  # строка сразу под A — цвет A
        self.assertTrue((img[3, 5, :3] == (10, 220, 30)).all())                  # и над A
        self.assertTrue((img[9, 5, :3] == (0, 0, 0)).all() or (img[9, 5, :3] == (10, 220, 30)).all())  # третий пиксель до B: у B нет перекрашенного соседа
        self.assertTrue((img[10:14, 2:14, :3] == (200, 100, 50)).all())            # B не тронут
        self.assertEqual(TP.gutter_into(img.copy(), np.flatnonzero(occ.reshape(-1)), np.array([], int), 2), 0)


class TestChooseTopTone(unittest.TestCase):
    """T-28/1: тон верха без фото — кандидат 06-synth против Ш3в; светлое не темнеет."""
    S = {'enabled': True, 'min_texels': 500, 'max_dL': 10.0, 'light_min_L': 90.0, 'light_max_darker': 4.0}

    def test_close_takes_synth(self):
        r = TP.choose_top_tone([70.0, 1.0, 5.0], [76.0, 0.0, 6.0], self.S)
        self.assertEqual(r['use'], 'synth')

    def test_white_stays_white(self):                                            # стол 18286: synth L100, Ш3в L88 (по кромке в тени) — белая столешница не серая
        r = TP.choose_top_tone([100.0, 0.0, 0.0], [88.1, 0.0, 0.0], self.S)
        self.assertEqual(r['use'], 'synth')
        self.assertGreaterEqual(r['lab'][0], 99.0)

    def test_dark_synth_far_takes_top(self):                                     # synth темнее Ш3в на 30: расхождение, не светлый случай — Ш3в
        r = TP.choose_top_tone([40.0, 0.0, 0.0], [70.0, 3.0, 20.0], self.S)
        self.assertEqual(r['use'], 'top')

    def test_light_synth_but_top_not_darker(self):                               # synth светлее Ш3в не-светлого: 92 против 78 → светлое не темнеет → synth; а Ш3в светлее synth — Ш3в
        self.assertEqual(TP.choose_top_tone([92.0, 0, 0], [78.0, 0, 0], self.S)['use'], 'synth')
        self.assertEqual(TP.choose_top_tone([60.0, 0, 0], [95.0, 0, 0], self.S)['use'], 'top')

    def test_disabled_or_missing(self):
        self.assertEqual(TP.choose_top_tone([100.0, 0, 0], [88.0, 0, 0], dict(self.S, enabled=False))['use'], 'top')
        self.assertEqual(TP.choose_top_tone(None, [88.0, 0, 0], self.S)['use'], 'top')


if __name__ == '__main__':
    unittest.main(verbosity=1)

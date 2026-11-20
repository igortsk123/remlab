"""Тесты чистых частей пробы StableGen (T-20261119-90/5): драйвер Salad, воркер, мост. Запуск: PYTHONPATH=<папка с aiohttp> python3 -m unittest tests_sg -v (из этой папки)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sg_relay  # noqa: E402
import sg_salad as S  # noqa: E402
import worker_sg as W  # noqa: E402

KEY = '112923_13224664101879413845'


class Runs(unittest.TestCase):
    def test_parse_ok(self):
        self.assertEqual(S.parse_runs(f'{KEY}:q2509q5,{KEY}:q2511q5'), [(KEY, 'q2509q5'), (KEY, 'q2511q5')])

    def test_parse_unknown_variant_fails_before_money(self):
        with self.assertRaises(ValueError):
            S.parse_runs(f'{KEY}:q3km')
        with self.assertRaises(ValueError):
            S.parse_runs('')

    def test_weights_shared_and_ordered(self):
        spec = S.weights_for([(KEY, 'q2509q5'), (KEY, 'q2511q5'), ('x', 'q2509q5')])
        self.assertEqual(spec, 'te,vae,q2509_q5,lora2509,q2511_q5,lora2511')            # без повторов, общие первыми

    def test_every_variant_weight_exists_in_worker_catalog(self):
        cat = S.load_weights_catalog()
        self.assertEqual(cat, W.WEIGHTS)                                                  # драйвер читает тот же каталог, что и воркер
        for var, v in S.VARIANTS.items():
            for w in v['weights']:
                self.assertIn(w, cat, f'{var}: нет весов {w}')
            names = [(cat[w][3] or os.path.basename(cat[w][1])) for w in v['weights']]
            self.assertIn(v['unet'], names, f'{var}: имя GGUF в списке сервера ≠ имя файла воркера')
            if v['lora']:
                self.assertIn(v['lora'], names, f'{var}: имя LoRA в списке сервера ≠ имя файла воркера')


class Money(unittest.TestCase):
    def test_cost(self):
        self.assertEqual(S.cost_usd(0, 0.44), 0.0)                                       # до running не платим и запас не копим
        self.assertAlmostEqual(S.cost_usd(3600, 0.44, reserve_s=0), 0.44)
        self.assertAlmostEqual(S.cost_usd(1800, 0.44, reserve_s=60), (1860 / 3600) * 0.44)

    def test_cap_reached_in_hours(self):
        # потолок $4 при $0,44/ч — это ≈ 9 часов; предел жизни ноды (150 мин) срабатывает раньше
        hours = 4.0 / 0.44
        self.assertGreater(hours * 60, 150)


class Cfg(unittest.TestCase):
    def test_cfg_for_2511_swaps_lora_and_unet(self):
        c = S.build_cfg(KEY, 'q2511q5', '/o', '127.0.0.1:18190', 8, 2048, 42, 2400)
        self.assertEqual(c['preset'], 'QWEN PRECISE')
        self.assertEqual(c['model_unet'], 'Qwen-Image-Edit-2511-Q5_K_M.gguf')
        self.assertIn('2511', c['lora_name'])
        self.assertEqual(c['cameras'], {'mode': 'orbit_ring', 'num': 8})
        self.assertTrue(c['style_image'].endswith(f'{KEY}.rgba.png'))
        self.assertTrue(c['glb'].endswith(f'{KEY}-hd.glb'))

    def test_body_has_no_secrets_in_print_and_command_is_exec(self):
        body = S.build_body('trial-sg-x', 'img:tag', 'high', 'te,vae', 8, 32768, {'basic': {'username': 'u', 'password': 'p'}})
        self.assertEqual(body['container']['command'][:2], ['python3', '-u'])
        self.assertIn('TRIAL_WORKER_Z', body['container']['environment_variables'])
        self.assertEqual(body['container']['resources']['gpu_classes'], [S.CARD['class_id']])      # только 4090


class Worker(unittest.TestCase):
    def test_plan_and_rename(self):
        plan = W.weights_plan('q2511_q5')
        self.assertEqual(plan[0][3], 'Qwen-Image-Edit-2511-Q5_K_M.gguf')
        self.assertEqual(plan[0][2], 'unet')

    def test_unknown_weight_fails_fast(self):
        with self.assertRaises(ValueError):
            W.weights_plan('te,nope')

    def test_none_is_empty(self):
        self.assertEqual(W.weights_plan('none'), [])

    def test_default_set_matches_catalog(self):
        for k in W.DEFAULT_SET.split(','):
            self.assertIn(k, W.WEIGHTS)


class Relay(unittest.TestCase):
    def test_key_injected_and_foreign_dropped(self):
        h = sg_relay.clean_headers({'Host': 'x', 'Salad-Api-Key': 'old', 'Content-Type': 'application/json', 'Upgrade': 'websocket'}, 'K')
        self.assertEqual(h, {'Content-Type': 'application/json', 'User-Agent': 'remlab-mesh/1.0', 'Salad-Api-Key': 'K'})

    def test_no_key_no_header(self):
        self.assertNotIn('Salad-Api-Key', sg_relay.clean_headers({'Salad-Api-Key': 'old'}, None))

    def test_foreign_user_agent_replaced(self):          # прокси RunPod отвечает 403 на python-requests/aiohttp
        self.assertEqual(sg_relay.clean_headers({'User-Agent': 'python-requests/2.32'}, None)['User-Agent'], 'remlab-mesh/1.0')


class Experiments(unittest.TestCase):
    def test_no_lora_variant_config(self):
        c = S.build_cfg('K', 'q2509nl', '/o', 's', 8, 2048, 42, 60)
        self.assertTrue(c['no_lora'])
        self.assertIsNone(c['lora_name'])
        self.assertEqual(c['scene_props'], {'steps': 24, 'cfg': 4.0})
        self.assertNotIn('lora2509', S.weights_for([('K', 'q2509nl')]).split(','))

    def test_edge_variant_levers(self):
        c = S.build_cfg('K', 'q2509edge', '/o', 's', 8, 2048, 42, 60)
        self.assertFalse(c['bake_denoise'])
        self.assertEqual(c['scene_props']['weight_exponent_after_generation'], 15.0)
        self.assertTrue(c['scene_props']['weight_exponent_generation_only'])
        self.assertNotIn('bake_denoise', S.build_cfg('K', 'q2509q5', '/o', 's', 8, 2048, 42, 60))

    def test_r2b1_newcut_keys(self):
        c = S.build_cfg('112923_13224664101879413845@r2b1+newcut', 'q2509q5', '/o', 's', 8, 2048, 42, 60)
        self.assertTrue(c['glb'].endswith('R2b1.s140k-uv.glb'))
        self.assertIn('newcut-2149', c['style_image'])
        self.assertIn('hd_inputs', S.build_cfg('114667_11634594969038554503@r2b1', 'q2509q5', '/o', 's', 8, 2048, 42, 60)['style_image'])

    def test_megapixels_variant(self):
        self.assertEqual(S.build_cfg('K', 'q2509mp', '/o', 's', 8, 2048, 42, 60)['megapixels'], 1.76)
        self.assertNotIn('megapixels', S.build_cfg('K', 'q2509q5', '/o', 's', 8, 2048, 42, 60))

    def test_shape_suffix_picks_comfy_shape(self):
        c = S.build_cfg('112923_1322@c1024', 'q2509q5', '/o', 's', 8, 2048, 42, 60)
        self.assertTrue(c['glb'].endswith('out-comfy/112923_1322-c1024.glb'))
        self.assertTrue(c['style_image'].endswith('112923_1322.rgba.png'))
        self.assertEqual(S.parse_runs('112923_1322@c1024:q2509q5'), [('112923_1322@c1024', 'q2509q5')])


class Views(unittest.TestCase):
    """T-90/7 ⑪: тексты видов по классу роли и зоне от «переда», словарь материалов, порядок камер, шаблоны CUSTOM (Codex 20.11)."""

    def test_zones_boundaries_and_sign(self):
        import sg_views as V
        f = (0.0, -1.0, 0.0)
        z = lambda x, y: V.zone_of(V.azimuth_deg((x, y, 0.5), f))
        self.assertEqual(z(0.0, -2.0), 'front')
        self.assertEqual(z(1.0, -2.0), 'quarter')                    # ≈26,6°
        self.assertEqual(z(2.0, -1.0), 'quarter')                    # ≈63,4°
        self.assertEqual(z(2.0, 0.0), 'side')
        self.assertEqual(z(1.0, 2.0), 'rear_quarter')                # ≈153,4°
        self.assertEqual(z(0.0, 2.0), 'rear')
        self.assertEqual(V.zone_of(22.4), 'front')
        self.assertEqual(V.zone_of(22.5), 'quarter')
        self.assertEqual(V.zone_of(-67.5), 'side')
        self.assertEqual(V.zone_of(112.5), 'rear_quarter')
        self.assertEqual(V.zone_of(157.5), 'rear')
        self.assertGreater(V.azimuth_deg((1.7, -0.7, 0.5), f), 0)       # камера на +X при переде −Y — левая сторона предмета
        self.assertLess(V.azimuth_deg((-1.7, -0.7, 0.5), f), 0)

    def test_custom_front_vector(self):
        import sg_views as V
        t, m = V.view_text('комод', (2.0, 0.0, 0.5), (1.0, 0.0, 0.0), is_seed=True)
        self.assertEqual(m['zone'], 'front')
        self.assertTrue(t.startswith('Front view. Match'))
        t, m = V.view_text('комод', (0.0, -2.0, 0.5), (1.0, 0.0, 0.0))
        self.assertEqual(m['zone'], 'side')

    def test_class_texts_are_affirmative_and_have_no_front_motif(self):
        import sg_views as V
        for role in ('комод', 'диван', 'стул', 'люстра', 'бра', 'ковёр', 'абажур'):
            for cam in ((1.7, -0.7, 0.9), (0.0, 2.0, 0.9), (-1.7, 0.7, 0.9)):
                t, _ = V.view_text(role, cam, (0.0, -1.0, 0.0))
                self.assertNotRegex(t.lower(), r'\bno\b|\bnot\b|\bwithout\b|\bdon\'t\b')
                self.assertNotIn('style reference', t.lower().replace('match the', ''))   # тексты не-зерна не ссылаются на фото; «Match … to the product reference» — только у зерна

    def test_seed_only_gets_photo_wording(self):
        import sg_views as V
        seed, _ = V.view_text('диван', (0.0, -2.0, 0.9), (0.0, -1.0, 0.0), is_seed=True)
        other, _ = V.view_text('диван', (0.0, -2.0, 0.9), (0.0, -1.0, 0.0), is_seed=False)
        self.assertIn('style reference', seed)
        self.assertNotIn('style reference', other)
        self.assertIn('painted front', other)

    def test_unknown_role_is_cautious_and_flagged(self):
        import sg_views as V
        t, m = V.view_text('абажур', (0.0, 2.0, 0.9), (0.0, -1.0, 0.0))
        self.assertFalse(m['known'])
        self.assertEqual(m['class'], 'generic')
        self.assertIn('corresponding adjacent painted component', t)
        self.assertNotIn('panel', t)                                  # неизвестная роль никогда не получает «глухую панель»
        self.assertEqual(V.role_class('Диван'), ('upholstered', True))
        self.assertEqual(V.role_class('Chest_of_Drawers'), ('casework', True))
        self.assertEqual(V.role_class('прикроватная-тумба'), ('casework', True))

    def test_top_only_when_really_high(self):
        import sg_views as V
        t, _ = V.view_text('комод', (1.0, -1.0, 1.0), (0.0, -1.0, 0.0))     # ≈35° — обычный вид с приподнятого кольца
        self.assertNotIn('High view', t)
        t, _ = V.view_text('комод', (0.1, -0.1, 2.0), (0.0, -1.0, 0.0))
        self.assertTrue(t.startswith('High view'))

    def test_material_vocabulary_and_prompt(self):
        import sg_views as V
        self.assertEqual(V.material_from_texts(['Ткань', 'Диван Король Велюр Роял']), 'velour')
        self.assertEqual(V.material_from_texts(['', 'ЛДСП 16 мм', '']), 'ldsp')
        self.assertEqual(V.material_from_texts(['рогожка']), 'rogozhka')
        self.assertEqual(V.material_from_texts(['экокожа']), 'leather')
        self.assertIsNone(V.material_from_texts(['Ткань', 'Диван Модерн']))
        p, fl = V.build_prompt('диван', 'velour', 'a fabric sofa')
        self.assertEqual(fl, [])
        self.assertIn('crushed velvet', p)
        self.assertIn('marbled mottled pile', p)
        p, fl = V.build_prompt('диван', None, 'a fabric sofa')
        self.assertEqual((p, fl), ('a fabric sofa', ['unknown_material']))
        p, fl = V.build_prompt('абажур', 'velour', 'x')
        self.assertEqual((p, fl), ('x', ['unknown_role_noun']))

    def test_seed_choice_and_order(self):
        import sg_views as V
        # симметричный предмет (перёд ≈ зад по силуэту): берём камеру, ближайшую к −Y, и помечаем «неуверенно»
        sc = {'C0': .5556, 'C1': .5503, 'C2': .8435, 'C3': .833, 'C4': .5571, 'C5': .5515, 'C6': .8174, 'C7': .8113}
        dirs = {'C2': (0.71, 1.62), 'C3': (-0.62, 1.64), 'C4': (-1.74, .69), 'C5': (-1.75, -.6), 'C6': (-.7, -1.61), 'C7': (.62, -1.64), 'C0': (1.75, -.7), 'C1': (1.75, .6)}
        self.assertEqual(V.choose_seed(sc, dirs), ('C7', False))
        # несимметричный (лучший заметно впереди остальных с другой стороны) — берём лучший по IoU, «уверенно»
        sc2 = dict(sc, C2=.95)
        self.assertEqual(V.choose_seed(sc2, dirs), ('C2', True))
        self.assertEqual(V.choose_seed({'a': .7}, {}), ('a', True))
        self.assertEqual(V.camera_order(['Camera_10', 'Camera_2', 'Camera_1'], 'Camera_2'), ['Camera_2', 'Camera_10', 'Camera_1'])
        self.assertEqual(V.camera_order(['Camera_0', 'Camera_1', 'Camera_2', 'Camera_3'], 'Camera_2'), ['Camera_2', 'Camera_3', 'Camera_0', 'Camera_1'])

    def test_no_product_ids_in_views(self):
        import re
        src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sg_views.py'), encoding='utf-8').read()
        self.assertIsNone(re.search(r'\d{5,}[_:]\d{5,}', src))                  # правило конвейера: ID товаров в коде запрещены

    def test_only_initial_only_prop_and_no_custom_templates(self):
        import sg_views as V
        self.assertEqual(V.CUSTOM_PROMPT_PROPS, {'qwen_external_style_initial_only': True})   # свои шаблоны с ролями картинок провалились на поде 20.11 — штатные остаются
        c = S.build_cfg('112923_13224664101879413845@r2b1+newcut', 'q2509vp', '/o', 's', 8, 2048, 42, 60)
        self.assertTrue(c['view_prompts'])
        self.assertNotIn('qwen_prompt_template', c['scene_props'])
        self.assertNotIn('view_prompts', S.build_cfg('112923_13224664101879413845@r2b1+newcut', 'q2509q5', '/o', 's', 8, 2048, 42, 60))

    def test_diagnostic_variants_toggle_one_factor(self):
        k = '112923_13224664101879413845@r2b1+newcut'
        t1, t3, t4 = (S.build_cfg(k, v, '/o', 's', 2, 2048, 42, 60) for v in ('q2509t1', 'q2509t3', 'q2509t4'))
        self.assertEqual(t1['vp_off'], ['text'])
        self.assertTrue(t1['view_prompts'])
        self.assertNotIn('vp_off', t3)
        self.assertEqual(t3['prompt'], 'a wooden chest of drawers')           # prompt_keep: прежний короткий промпт, подсказки видов остаются
        self.assertNotIn('view_prompts', t4)
        self.assertEqual(t4['scene_props'], {'qwen_external_style_initial_only': True})


class RunpodDriverStops(unittest.TestCase):
    """Драйвер пода: «контейнер не встал» (RUNNING, uptime 0, /health нет) — удаляем через container-min, не ждём потолка (директор 20.11, под cef3upb6ek9udf)."""

    class FakeApi:
        def __init__(self):
            self.calls = []
            self.deleted = False

        def call(self, method, path, body=None, timeout=60):
            self.calls.append((method, path))
            if method == 'POST' and path == '/v2/pods':
                return 201, {'id': 'podX', 'cost': 0.89, 'status': 'RUNNING'}
            if method == 'GET' and path == '/v2/pods/podX':
                return (404, {}) if self.deleted else (200, {'status': 'RUNNING', 'uptimeSeconds': 0, 'runtime': None})
            if method == 'POST' and path.endswith('/action'):
                self.deleted = True
                return 204, {}
            return 200, {}

    def _args(self, out, **kw):
        import argparse
        a = argparse.Namespace(runs=f'{KEY}:q2509q5', gpu=None, cloud='SECURE', image='img', disk=80, min_ram=32, cameras=8, texture=2048, seed=42, cap=0.5, max_price=1.0,
                               max_min=150, no_machine_min=20, health_min=12, container_min=6, job_timeout=40, suffix='t', out=out, relay_python='x', relay_deps='x',
                               salad_logs=[], reuse_pod=None, reuse_age_s=0, apply=True, gate=None, gate_min=15)
        for k, v in kw.items():
            setattr(a, k, v)
        return a

    def test_container_not_started_is_deleted_after_container_min(self):
        import tempfile
        from unittest import mock
        import sg_runpod as R
        clock = [1000.0]
        api = self.FakeApi()
        with tempfile.TemporaryDirectory() as d, mock.patch.object(S, 'hf_head', return_value=200), mock.patch.object(R, 'public_get', return_value=(404, {})), \
                mock.patch.object(S, 'load_weights_catalog', return_value={}), mock.patch.object(S, 'weight_urls', return_value=[]):
            def sleep(n):
                clock[0] += 60
            rc = R.run(self._args(d), api, sleep=sleep, clock=lambda: clock[0])
            import json
            summ = json.load(open(os.path.join(d, 'summary-trial-sg-rp-t.json'), encoding='utf-8'))
        self.assertEqual(summ['stopped_by'], 'no_container')
        self.assertTrue(summ['terminated'])
        self.assertLess(summ['alive_s'], 12 * 60)            # раньше 12-минутного health-min
        self.assertEqual(rc, 1)


if __name__ == '__main__':
    unittest.main()

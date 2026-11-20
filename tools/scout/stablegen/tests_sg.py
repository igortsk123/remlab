"""Тесты чистых частей пробы StableGen (T-20261119-90/5): драйвер Salad, воркер, мост. Запуск: PYTHONPATH=<папка с aiohttp> python3 -m unittest tests_sg -v (из этой папки)."""
import math
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


class RelayRetry(unittest.TestCase):
    """T-153/1: мост сам повторяет краткие сбои связи (поддельный ComfyUI за шлюзом); отказ — только после повторов."""

    GATE_403 = '<html><ul aria-label="Salad Connection Error"><h1>Error 403 Detected</h1></ul></html>'

    def run_relay(self, script, method='GET', path='/queue'):
        import asyncio
        import sg_transient
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        calls = []

        async def upstream(req):
            code, body = script[min(len(calls), len(script) - 1)]
            calls.append(code)
            return web.Response(status=code, text=body)

        up = web.Application()
        up.add_routes([web.route('*', '/{tail:.*}', upstream)])
        rules = sg_transient.load_rules()

        async def go():
            async with TestServer(up) as srv:
                app = sg_relay.make_app(f'http://127.0.0.1:{srv.port}', None, rules, sleep=lambda s: asyncio.sleep(0))
                async with TestClient(TestServer(app)) as cl:
                    r = await cl.request(method, path, data=b'x' if method == 'POST' else None)
                    st = await (await cl.get('/_relay/stats')).json()
                    return r.status, st
        status, stats = asyncio.run(go())
        return status, stats, calls

    def test_403_gateway_page_is_retried_then_succeeds(self):
        status, stats, calls = self.run_relay([(403, self.GATE_403), (403, self.GATE_403), (200, '{}')])
        self.assertEqual((status, calls, stats['retries'], stats['gave_up']), (200, [403, 403, 200], 2, 0))
        self.assertEqual(stats['reasons'], {'403 Salad Connection Error': 2})

    def test_gives_up_after_three_retries(self):
        status, stats, calls = self.run_relay([(403, self.GATE_403)])
        self.assertEqual((status, len(calls), stats['retries'], stats['gave_up']), (403, 4, 3, 1))

    def test_real_403_and_real_errors_are_not_retried(self):
        status, _s, calls = self.run_relay([(403, '{"error":"bad key"}')])
        self.assertEqual((status, calls), (403, [403]))
        status, _s, calls = self.run_relay([(500, 'workflow failed')])
        self.assertEqual((status, calls), (500, [500]))

    def test_502_retried_for_get_but_not_post(self):
        status, stats, calls = self.run_relay([(502, ''), (200, '{}')])
        self.assertEqual((status, calls, stats['retries']), (200, [502, 200], 1))
        status, _s, calls = self.run_relay([(502, ''), (200, '{}')], method='POST', path='/prompt')       # POST мог дойти до ComfyUI — не дублируем
        self.assertEqual((status, calls), (502, [502]))

    def test_post_with_gateway_403_page_is_retried(self):                 # страница шлюза = запрос не дошёл до ComfyUI
        status, _s, calls = self.run_relay([(403, self.GATE_403), (200, '{}')], method='POST', path='/upload/image')
        self.assertEqual((status, calls), (200, [403, 200]))

    def test_rules_are_data_and_sane(self):
        import sg_transient
        r = sg_transient.load_rules()
        self.assertEqual((r['retries'], r['pauses_s']), (3, [2, 5, 10]))
        self.assertTrue(sg_transient.text_has_server_marker(r, "ComfyUI isn't reachable at 127.0.0.1:18193"))
        self.assertEqual(sg_transient.pause_s(r, 9), 10.0)


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
        self.assertEqual(V.role_class('тумба прикроватная'), ('casework', True))                 # порядок слов роли не важен (Codex 20.11)
        self.assertEqual(V.role_noun('тумба прикроватная'), 'bedside cabinet')
        for r, n in (('торшер', 'floor lamp'), ('лампа', 'table lamp'), ('ваза', 'vase'), ('кашпо', 'planter'), ('люстра', 'chandelier')):
            self.assertEqual(V.role_noun(r), n, r)                                                # роли «continuous» больше не дают «piece of furniture»
        self.assertIsNone(V.role_noun('неизвестное'))

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
        p, fl = V.build_prompt('диван', 'velour', 'blue')
        self.assertEqual(fl, [])
        self.assertTrue(p.startswith('a blue sofa, crushed velvet'))
        self.assertIn('marbled mottled pile', p)
        p, fl = V.build_prompt('диван', None, 'beige')                                        # нет материала — честно без него, флаг
        self.assertEqual((p, fl), ('a beige sofa', ['unknown_material']))
        p, fl = V.build_prompt('абажур', 'velour', None)                                      # нет роли и цвета — «piece of furniture», флаги
        self.assertTrue(p.startswith('a piece of furniture, crushed velvet'))
        self.assertEqual(fl, ['unknown_role_noun', 'unknown_colour'])
        self.assertEqual(V.build_prompt('кресло', 'wood_solid', 'oak')[0][:9], 'an oak ar')   # артикль
        self.assertEqual(V.colour_from_texts(['Комод divan.ru Модерн 93x88 Графитовый']), 'graphite')
        self.assertEqual(V.colour_from_texts(['Кресло Glasar Сакура 62х49х97 см', '']), None)
        self.assertEqual(V.colour_from_texts(['Шкаф Монблан Косы Мятный', 'Зеленый Бежевый']), 'mint')
        self.assertEqual(V.colour_from_texts(['Диван модульный divan.ru Брера 4 Букле Бежевый']), 'beige')   # «Букле» — материал, не «бук»
        self.assertIsNone(V.colour_from_texts(['Серия Вега Сервант']))                                         # «серия», «сервант» — не «серый»
        self.assertEqual(V.colour_from_texts(['Комод Дуб золотистый']), 'oak')

    def test_seed_choice_and_order(self):
        import sg_views as V
        # T-90/10: зерно только в передней полусфере (лицо формы на −Y); IoU выбирает угол внутри неё
        sc = {'C0': .5556, 'C1': .5503, 'C2': .8435, 'C3': .833, 'C4': .5571, 'C5': .5515, 'C6': .8174, 'C7': .8113}
        dirs = {'C2': (0.71, 1.62), 'C3': (-0.62, 1.64), 'C4': (-1.74, .69), 'C5': (-1.75, -.6), 'C6': (-.7, -1.61), 'C7': (.62, -1.64), 'C0': (1.75, -.7), 'C1': (1.75, .6)}
        self.assertEqual(V.choose_seed(sc, dirs), ('C6', False))          # лучший по IoU C2 — сзади; из передних камер IoU выбирает C6 (.8174 > C7 .8113), «неуверенно»
        sc2 = dict(sc, C7=.95)
        self.assertEqual(V.choose_seed(sc2, dirs), ('C7', True))          # лучший и так спереди
        sc3 = dict(sc, C3=.99)                                            # кресло: IoU «уверенно» сзади, а лицо формы на −Y → зерно спереди
        self.assertEqual(V.choose_seed(sc3, dirs)[0], 'C6')
        self.assertFalse(V.choose_seed(sc3, dirs)[1])
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
        self.assertEqual(t3['prompt'], t1['prompt'])                          # подсказка — из каталога у всех вариантов, словаря по ID нет
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

    def test_relay_must_reach_the_pod_not_a_stranger(self):
        import tempfile
        from unittest import mock
        import sg_runpod as R
        clock = [1000.0]
        api = self.FakeApi()
        seen = []

        def pg(url, timeout=20):
            seen.append(url)
            if 'proxy.runpod.net' in url:
                return 200, {'warm': True, 'weights_gb': 1}          # под готов
            return 200, {'ok': 1}                                      # по порту моста отвечает ЧУЖОЙ сервер без поля warm (как fake_comfy на занятом порту)
        fake_relay = mock.Mock()
        fake_relay.poll.return_value = None
        with tempfile.TemporaryDirectory() as d, mock.patch.object(S, 'hf_head', return_value=200), mock.patch.object(R, 'public_get', side_effect=pg), \
                mock.patch.object(S, 'load_weights_catalog', return_value={}), mock.patch.object(S, 'weight_urls', return_value=[]):
            def sleep(n):
                clock[0] += 5
            import json
            rc = R.run(self._args(d), api, sleep=sleep, clock=lambda: clock[0], popen=lambda *a, **k: fake_relay)
            summ = json.load(open(os.path.join(d, 'summary-trial-sg-rp-t.json'), encoding='utf-8'))
        self.assertEqual(summ['stopped_by'], 'relay_not_pod')
        self.assertTrue(summ['terminated'])
        self.assertEqual(summ['runs'], [])                             # ни одного прогона на чужом сервере
        self.assertEqual(rc, 1)

    def test_t5_short_side_text_by_angle_only(self):
        import sg_views as V
        front = (0.0, -1.0, 0.0)
        def txt(az, role='комод'):
            r = math.radians(az)
            return V.short_side_text(role, (math.sin(r), -math.cos(r), 0.3), front)[0]
        for az in (0, 30, -45, 59):
            self.assertEqual(txt(az), '')
        self.assertEqual(txt(90), 'the plain left side of the same chest of drawers')
        self.assertEqual(txt(-90), 'the plain right side of the same chest of drawers')
        self.assertEqual(txt(135), 'the plain back of the same chest of drawers')
        self.assertEqual(txt(180), 'the plain back of the same chest of drawers')
        self.assertEqual(txt(-135), 'the plain back of the same chest of drawers')
        self.assertEqual(txt(90, 'неизвестная роль'), 'the plain left side of the same piece of furniture')

    def test_t5b_back_suffix_only_on_back(self):
        import sg_views as V
        self.assertEqual(S.VARIANTS['q2509t5b']['back_suffix'], ', same colour and material as its side panels')
        r = math.radians(180)
        self.assertTrue(V.short_side_text('комод', (math.sin(r), -math.cos(r), 0.3), (0, -1, 0), ', X')[0].endswith('chest of drawers, X'))
        r = math.radians(90)
        self.assertEqual(V.short_side_text('комод', (math.sin(r), -math.cos(r), 0.3), (0, -1, 0), ', X')[0], 'the plain left side of the same chest of drawers')

    def test_t5c_alternating_order_by_angles_and_photo_only_to_seed(self):
        import sg_views as V
        az = {'Camera_7': 0.0, 'Camera_0': 47.5, 'Camera_1': 88.4, 'Camera_2': 135.7, 'Camera_3': 180.0, 'Camera_4': -132.4, 'Camera_5': -91.8, 'Camera_6': -44.3}     # углы из лога T5 (20.11)
        dirs = {n: (math.sin(math.radians(a)), -math.cos(math.radians(a))) for n, a in az.items()}
        self.assertEqual(V.alternating_order(dirs, (0.0, -1.0, 0.0), 'Camera_7'), ['Camera_7', 'Camera_0', 'Camera_6', 'Camera_1', 'Camera_5', 'Camera_2', 'Camera_4', 'Camera_3'])
        rot = {n: (math.sin(math.radians(a + 20)), -math.cos(math.radians(a + 20))) for n, a in az.items()}        # перёд в другом месте кольца — порядок тот же, по углам, не по именам
        front = (math.sin(math.radians(20)), -math.cos(math.radians(20)), 0.0)
        self.assertEqual(V.alternating_order(rot, front, 'Camera_7')[-1], 'Camera_3')
        v = S.VARIANTS['q2509t5c']
        self.assertEqual(v['order_mode'], 'alternating')
        self.assertEqual(v['scene_props'], {'qwen_external_style_initial_only': True})
        self.assertEqual(v['vp_off'], [])
        self.assertEqual(v['back_suffix'], S.VARIANTS['q2509t5b']['back_suffix'])

    def test_t5def_back_by_angle_and_variants(self):
        import sg_views as V
        az = {'Camera_7': 0.0, 'Camera_0': 47.5, 'Camera_1': 88.4, 'Camera_2': 135.7, 'Camera_3': 180.0, 'Camera_4': -132.4, 'Camera_5': -91.8, 'Camera_6': -44.3}
        dirs = {n: (math.sin(math.radians(a)), -math.cos(math.radians(a))) for n, a in az.items()}
        front = (0.0, -1.0, 0.0)
        self.assertEqual(V.back_cameras(dirs, front), ['Camera_3'])                       # 135° — ещё не «строго сзади»
        order = V.alternating_order(dirs, front, 'Camera_7')
        self.assertEqual(V.side_sample_camera(dirs, front, order), 'Camera_1')              # |88,4−90|=1,6 < |91,8−90|=1,8: ближайший к 90°
        rot = {n: (math.sin(math.radians(a + 33)), -math.cos(math.radians(a + 33))) for n, a in az.items()}
        f2 = (math.sin(math.radians(33)), -math.cos(math.radians(33)), 0.0)
        self.assertEqual(V.back_cameras(rot, f2), ['Camera_3'])                              # по углам, не по именам
        for k, m in (('q2509t5d', 'drop'), ('q2509t5e', 'side_sample'), ('q2509t5f', 'no_photo')):
            v = S.VARIANTS[k]
            self.assertEqual(v['back_mode'], m)
            self.assertEqual(v['order_mode'], 'alternating')
            self.assertEqual(v['vp_off'], [])
            self.assertNotIn('qwen_external_style_initial_only', v.get('scene_props') or {})   # фото остальным видам — как в T5b
            self.assertEqual(v['back_suffix'], S.VARIANTS['q2509t5b']['back_suffix'])

    def test_t5g_back_limit_is_variant_parameter_boundary(self):
        import sg_views as V
        def dirs_at(angles):
            return {f'C{i}': (math.sin(math.radians(a)), -math.cos(math.radians(a))) for i, a in enumerate(angles)}
        front = (0.0, -1.0, 0.0)
        d = dirs_at([0, 90, 99.5, 100.5, 135, -135, 150.5, 180])
        names = lambda lim: sorted(V.back_cameras(d, front, lim))
        self.assertEqual(names(100.0), ['C3', 'C4', 'C5', 'C6', 'C7'])      # 99,5 — ещё с фото, 100,5 — уже без; ±135 и 180 — без
        self.assertEqual(names(135.0 - 0.01), ['C4', 'C5', 'C6', 'C7'])       # граница 135: в пределах допуска ±135 включены
        self.assertEqual(names(150.0), ['C6', 'C7'])                         # прежний порог T5d/e/f
        v = S.VARIANTS['q2509t5g']
        self.assertEqual((v['back_mode'], v['back_limit']), ('no_photo', 100.0))
        cfg = S.build_cfg('112923_13224664101879413845@r2b1+newcut', 'q2509t5g', '/o', 's', 2, 2048, 42, 60)
        self.assertEqual(cfg['back_limit'], 100.0)                           # порог доходит до конфига драйвера, в коде драйвера — только значение по умолчанию

    def test_strip_colour_for_photo_views(self):
        import sg_views as V
        self.assertEqual(V.strip_colour('a graphite chest of drawers, matte laminated chipboard finish'), 'a chest of drawers, matte laminated chipboard finish')
        self.assertEqual(V.strip_colour('a beige armchair, coarse woven linen-like upholstery, matte'), 'an armchair, coarse woven linen-like upholstery, matte')
        self.assertEqual(V.strip_colour('an armchair'), 'an armchair')                                        # цвета нет — как есть
        self.assertEqual(V.strip_colour('a light blue sofa, velvet'), 'a sofa, velvet')                        # цвет из двух слов
        self.assertEqual(V.strip_colour('a wardrobe, white doors'), 'a wardrobe, white doors')                # цвет вне первой фразы не трогаем

    def test_shape_and_cut_dirs_by_suffix(self):
        c = S.build_cfg('112923_321183910010607839@n1024+cut-vyb10', 'q2509t5g', '/o', 's', 8, 2048, 42, 60)
        self.assertTrue(c['glb'].endswith('t90-1120/shape-uv/112923_321183910010607839-n1024.glb'))
        self.assertTrue(c['style_image'].endswith('t104-1120/vyb10-1216/112923_321183910010607839.rgba.png'))
        c = S.build_cfg('112923_321183910010607839@n1024b+cut-vyb30', 'q2509t5g', '/o', 's', 8, 2048, 42, 60)
        self.assertTrue(c['glb'].endswith('t90-1120/shape-uv/112923_321183910010607839-n1024.glb'))
        self.assertTrue(c['style_image'].endswith('t104-1120/vyb30-1242/112923_321183910010607839.rgba.png'))

    @staticmethod
    def _glb(path, attrs):
        import json
        import struct
        j = json.dumps({'asset': {'version': '2.0'}, 'meshes': [{'primitives': [{'attributes': attrs}]}]}).encode()
        j += b' ' * (-len(j) % 4)
        open(path, 'wb').write(b'glTF' + struct.pack('<III', 2, 20 + len(j), len(j)) + b'JSON' + j)

    def test_shape_without_uv_is_refused_before_pod(self):
        """T-90/11: формы Salad без UV запекались 55 мин и не кончались — build_cfg отказывает ДО старта пода; с UV и несуществующий файл — проходят."""
        import tempfile
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            self._glb(os.path.join(d, 'pA-tt.glb'), {'POSITION': 0})
            self._glb(os.path.join(d, 'pB-tt.glb'), {'POSITION': 0, 'TEXCOORD_0': 1})
            self.assertFalse(S.glb_has_uv(os.path.join(d, 'pA-tt.glb')))
            self.assertTrue(S.glb_has_uv(os.path.join(d, 'pB-tt.glb')))
            self.assertIsNone(S.glb_has_uv(os.path.join(d, 'нет.glb')))
            with mock.patch.dict(S.SHAPE_DIRS, {'tt': d}):
                with self.assertRaises(ValueError):
                    S.build_cfg('pA@tt', 'q2509t5g', '/o', 's', 8, 2048, 42, 60)
                S.build_cfg('pB@tt', 'q2509t5g', '/o', 's', 8, 2048, 42, 60)

    def test_bake_watchdog_kills_hung_bake_and_marks_it(self):
        """T-90/11: запекание дольше 3× ожидаемого — убиваем, товар «запекание зависло», под берёт следующий."""
        import json
        import tempfile
        from unittest import mock
        import sg_runpod as R
        clock = [1000.0]
        api = self.FakeApi()
        procs = []

        def pg(url, timeout=20):
            return (200, {'backend': 'comfy-0.46.0+gguf', 'gpu': 'NVIDIA RTX A6000'}) if url.endswith('/info') else (200, {'warm': True, 'weights_gb': 1})

        def popen(cmd, **kw):
            m = mock.Mock()
            if 'sg_relay.py' in ' '.join(map(str, cmd)):
                m.poll.return_value = None
                return m
            cfg = json.load(open(cmd[-1], encoding='utf-8'))
            os.makedirs(cfg['out'], exist_ok=True)
            n = len(procs)
            t0 = clock[0]
            open(os.path.join(cfg['out'], 'status.json'), 'w').write(json.dumps({'stage': 'bake', 'steps': [[1.0, 'generate'], [5.0, 'bake']]}))
            m.poll.return_value = None                                 # запекание первого товара висит; второй кончается сам
            if n >= 1:
                m.poll.side_effect = lambda: (open(os.path.join(cfg['out'], 'painted.glb'), 'wb').write(b'g') and 0) if clock[0] - t0 >= 100 else None
            procs.append(m)
            return m
        with tempfile.TemporaryDirectory() as d, mock.patch.object(S, 'hf_head', return_value=200), mock.patch.object(R, 'public_get', side_effect=pg), \
                mock.patch.object(S, 'load_weights_catalog', return_value={}), mock.patch.object(S, 'weight_urls', return_value=[]), \
                mock.patch.object(S, 'build_cfg', side_effect=lambda key, var, out, *r, **k: {'out': out}), mock.patch.object(S, 'parse_runs', return_value=[('k1', 'q2509t5i'), ('k2', 'q2509t5i')]), \
                mock.patch.object(S, 'weights_for', return_value={}):
            args = self._args(d)
            args.out = d

            def sleep(n):
                clock[0] += 20
            R.run(args, api, sleep=sleep, clock=lambda: clock[0], popen=popen)
            summ = json.load(open(os.path.join(d, 'summary-trial-sg-rp-t.json'), encoding='utf-8'))
        procs[0].terminate.assert_called()
        hung = [r for r in summ['runs'] if r.get('note') == 'запекание зависло']
        self.assertEqual(len(hung), 1)
        self.assertFalse(hung[0]['ok'])
        self.assertEqual(len(procs), 2)                                  # оба товара стартовали: второй не ждал зависшего первого

    def test_t5_variant_keeps_photo_on_every_view(self):
        v = S.VARIANTS['q2509t5']
        self.assertTrue(v['short_side'] and v['view_prompts'])
        self.assertEqual(v.get('scene_props'), S.VARIANTS['q2509q5'].get('scene_props'))
        self.assertNotIn('qwen_external_style_initial_only', v.get('scene_props') or {})
        self.assertEqual(v['vp_off'], ['order'])

    def test_run_records_who_answered_and_marks_unanswered_as_failure(self):
        import json
        import tempfile
        from unittest import mock
        import sg_runpod as R
        for info, expect_ok in (({'backend': 'comfy-0.46.0+gguf', 'gpu': 'NVIDIA GeForce RTX 4090'}, True), ({}, False)):
            clock = [1000.0]
            api = self.FakeApi()

            def pg(url, timeout=20, info=info):
                if url.endswith('/info'):
                    return (200, info) if info else (404, {})
                return 200, {'warm': True, 'weights_gb': 1}

            def popen(cmd, **kw):
                m = mock.Mock()
                m.poll.return_value = None if 'sg_relay.py' in ' '.join(map(str, cmd)) else 0      # мост жив, задание Blender завершилось
                if str(cmd[0]).endswith('heavy-slot.sh'):
                    cfg = json.load(open(cmd[-1], encoding='utf-8'))
                    os.makedirs(cfg['out'], exist_ok=True)
                    open(os.path.join(cfg['out'], 'painted.glb'), 'wb').write(b'glb')
                    self.assertTrue(cfg['require_worker'])
                return m
            with tempfile.TemporaryDirectory() as d, mock.patch.object(S, 'hf_head', return_value=200), mock.patch.object(R, 'public_get', side_effect=pg), \
                    mock.patch.object(S, 'load_weights_catalog', return_value={}), mock.patch.object(S, 'weight_urls', return_value=[]):
                def sleep(n):
                    clock[0] += 20
                R.run(self._args(d), api, sleep=sleep, clock=lambda: clock[0], popen=popen)
                summ = json.load(open(os.path.join(d, 'summary-trial-sg-rp-t.json'), encoding='utf-8'))
            self.assertEqual(len(summ['runs']), 1)
            self.assertEqual(summ['runs'][0]['ok'], expect_ok)
            self.assertEqual(bool(summ['runs'][0]['answered_by']['gpu']), expect_ok)

    def test_next_product_starts_while_previous_is_baking(self):
        """T-90/11: пока товар N запекается локально (stage=bake), под свободен — генерация товара N+1 стартует, а не ждёт."""
        import json
        import tempfile
        from unittest import mock
        import sg_runpod as R
        clock = [1000.0]
        api = self.FakeApi()
        started, polls = [], {}

        def pg(url, timeout=20):
            return (200, {'backend': 'comfy-0.46.0+gguf', 'gpu': 'NVIDIA RTX A6000'}) if url.endswith('/info') else (200, {'warm': True, 'weights_gb': 1})

        def popen(cmd, **kw):
            m = mock.Mock()
            if 'sg_relay.py' in ' '.join(map(str, cmd)):
                m.poll.return_value = None
                return m
            cfg = json.load(open(cmd[-1], encoding='utf-8'))
            os.makedirs(cfg['out'], exist_ok=True)
            started.append((clock[0], cfg['out']))
            open(os.path.join(cfg['out'], 'status.json'), 'w').write(json.dumps({'stage': 'bake'}))      # генерация на поде уже закончена
            n = len(started)

            def poll():                                              # запекание длится 300 с по часам теста
                if clock[0] - started[n - 1][0] >= 300:
                    open(os.path.join(cfg['out'], 'painted.glb'), 'wb').write(b'glb')
                    return 0
                return None
            m.poll.side_effect = poll
            return m
        args = self._args(tempfile.mkdtemp())
        args.runs = 'k1:q2509t5i,k2:q2509t5i'
        with tempfile.TemporaryDirectory() as d, mock.patch.object(S, 'hf_head', return_value=200), mock.patch.object(R, 'public_get', side_effect=pg), \
                mock.patch.object(S, 'load_weights_catalog', return_value={}), mock.patch.object(S, 'weight_urls', return_value=[]), \
                mock.patch.object(S, 'build_cfg', side_effect=lambda key, var, out, *r, **k: {'out': out}), mock.patch.object(S, 'parse_runs', return_value=[('k1', 'q2509t5i'), ('k2', 'q2509t5i')]), \
                mock.patch.object(S, 'weights_for', return_value={}):
            args.out = d

            def sleep(n):
                clock[0] += 20
            R.run(args, api, sleep=sleep, clock=lambda: clock[0], popen=popen)
            summ = json.load(open(os.path.join(d, 'summary-trial-sg-rp-t.json'), encoding='utf-8'))
        self.assertEqual(len(started), 2)
        self.assertLess(started[1][0] - started[0][0], 300)          # второй запущен, пока первый ещё запекался
        self.assertEqual([r['ok'] for r in summ['runs']], [True, True])

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


class QueueTests(unittest.TestCase):
    """Общая очередь прогонов (sg_queue.RunQueue) — одни правила для RunPod и Salad (T-90/12)."""

    class P:
        def __init__(self): self.rc, self.killed = None, False
        def poll(self): return self.rc
        def terminate(self): self.killed, self.rc = True, -15

    free = 100.0

    def make(self, runs, tmp, results):
        import sg_queue as Q
        procs = {}

        def start(key, var, t):
            d = os.path.join(tmp, key)
            os.makedirs(os.path.join(d, 'blender'), exist_ok=True)
            p = procs[key] = self.P()
            return {'key': key, 'variant': var, 'label': var, 'dir': d, 'proc': p, 'started': t, 'last_say': t}

        def finish(it, rc, t):
            return results.get(it['key'], rc == 0), {}
        said = []
        q = Q.RunQueue(runs, {}, free_gb=lambda: self.free, start=start, finish=finish, say=lambda *x: said.append(' '.join(map(str, x))), progress=lambda s, c, cap: s, job_timeout_s=3000)
        return q, procs, said

    def status(self, tmp, key, stage, steps=()):
        import json
        json.dump({'stage': stage, 'steps': list(steps)}, open(os.path.join(tmp, key, 'blender', 'status.json'), 'w'))

    def test_probe_failure_stops_group(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            q, procs, _ = self.make([('a', 'v'), ('b', 'v')], tmp, {})
            self.assertIsNone(q.step(0))
            procs['a'].rc = 1
            self.assertEqual(q.step(1), 'probe_failed')

    def test_second_failure_after_success_does_not_stop_but_two_in_a_row_do(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            q, procs, _ = self.make([(k, 'v') for k in 'abcd'], tmp, {'b': False, 'c': False})
            for k, expect in (('a', None), ('b', None), ('c', 'failures')):
                q.step(0)
                procs[k].rc = 0
                self.assertEqual(q.step(1), expect, k)

    def test_retries_are_recorded_in_run_and_journal(self):
        import json
        import tempfile
        import unittest.mock as um
        import sg_transient
        with tempfile.TemporaryDirectory() as tmp:
            q, procs, said = self.make([('a', 'v')], tmp, {})
            q.relay_port = 1
            q.step(0)
            json.dump({'stage': 'export', 'steps': [], 'server_retries': 1}, open(os.path.join(tmp, 'a', 'blender', 'status.json'), 'w'))
            procs['a'].rc = 0
            with um.patch.object(sg_transient, 'relay_stats', return_value={'retries': 2}):
                q.step(1)
            self.assertEqual(q.summary['runs'][0]['retries'], {'relay': 2, 'drive': 1})
            self.assertEqual(q.summary['retries_total'], 3)
            self.assertTrue(any('повторы связи' in x for x in said))

    def test_low_disk_stops_group_and_slim_keeps_result(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            q, procs, said = self.make([('a', 'v'), ('b', 'v')], tmp, {})
            q.step(0)
            b = os.path.join(tmp, 'a', 'blender')
            os.makedirs(os.path.join(b, 'sg-output', 'S', 't', 'inpaint'))
            os.makedirs(os.path.join(b, 'sg-output', 'S', 't', 'generated'))
            for f in ('session.blend', 'painted.glb', 'sg-output/S/t/inpaint/x.png', 'sg-output/S/t/generated/v.png'):
                open(os.path.join(b, f), 'wb').write(b'x' * 10)
            procs['a'].rc = 0
            q.step(1)
            self.assertFalse(os.path.exists(os.path.join(b, 'session.blend')))
            self.assertFalse(os.path.exists(os.path.join(b, 'sg-output', 'S', 't', 'inpaint')))
            self.assertTrue(os.path.exists(os.path.join(b, 'painted.glb')) and os.path.exists(os.path.join(b, 'sg-output', 'S', 't', 'generated', 'v.png')))
            self.free = 1.0
            self.assertEqual(q.step(2), 'disk')
            self.assertTrue(any('диск' in x for x in said))
            self.free = 100.0

    def test_next_starts_when_previous_bakes_and_hung_bake_is_killed(self):
        import tempfile
        import sg_queue as Q
        with tempfile.TemporaryDirectory() as tmp:
            q, procs, said = self.make([('a', 'v'), ('b', 'v')], tmp, {})
            q.step(0)
            self.status(tmp, 'a', 'bake', [(10.0, 'bake')])
            q.step(20)                                              # a ушёл в запекание → нода свободна
            q.step(21)                                              # → стартует b
            self.assertIn('b', procs)
            self.assertEqual([x['key'] for x in q.baking], ['a'])
            q.step(20 + Q.BAKE_EXPECT_S * Q.BAKE_WATCH_FACTOR + 5)
            self.assertTrue(procs['a'].killed)
            self.assertTrue(any('запекание зависло' in x for x in said))
            self.assertEqual(q.summary['runs'][0]['note'], 'запекание зависло')


if __name__ == '__main__':
    unittest.main()

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
        self.assertEqual(h, {'Content-Type': 'application/json', 'Salad-Api-Key': 'K'})

    def test_no_key_no_header(self):
        self.assertNotIn('Salad-Api-Key', sg_relay.clean_headers({'Salad-Api-Key': 'old'}, None))


if __name__ == '__main__':
    unittest.main()

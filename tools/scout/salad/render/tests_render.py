#!/usr/bin/env python3
"""Тесты воркера и драйвера Salad «кадры форм» (T-184/1, очередь 3). Без сети, Salad и видеокарты: настоящий HTTP-сервер воркера на localhost; вместо Blender — поддельный исполняемый
файл (пишет кадры с теми же именами, что render_stand). Запуск: python tools/scout/salad/render/tests_render.py (stdlib + numpy/Pillow для сверки; без них тесты сверки пропускаются)."""
from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'pose'))
import kit_worker as KW  # noqa: E402
import render_trial as RT  # noqa: E402
import stage_render_code as SRC  # noqa: E402
import worker_render as WR  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
GLB = b'glTF' + b'1' * 200
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64

FAKE_BLENDER = r'''#!/usr/bin/env python3
import os, sys, time
a = sys.argv[1:]
if '--version' in a:
    print('Blender 4.5.9 (fake)'); sys.exit(0)
g = lambda k: a[a.index(k) + 1]
glb = open(g('--glb'), 'rb').read()
out = g('--out')
if b'FAILME' in glb:
    print('Error: упал нарочно'); sys.exit(1)
if b'NOGPU' in glb and g('--device') == 'GPU':
    print('GPU: нет CUDA-устройства'); sys.exit(3)
if b'SLOW' in glb:
    time.sleep(2.0)
os.makedirs(out, exist_ok=True)
n = 0
print('GPU: fake CUDA' if g('--device') == 'GPU' else 'CPU')
for v in [x.split(':')[0] for x in g('--views').split(',')]:
    for lt in g('--lights').split(','):
        n += 1
        if b'PARTIAL' in glb and n == 3:
            continue
        open(os.path.join(out, f"{n:02d}_{v}_clay" + ('_graze' if lt == 'graze' else '') + '.png'), 'wb').write(b'\x89PNG\r\n\x1a\n' + b'0' * 64)
'''


def fake_blender(root: str) -> str:
    p = os.path.join(root, 'fake_blender')
    open(p, 'w').write(FAKE_BLENDER)
    os.chmod(p, os.stat(p).st_mode | stat.S_IXUSR)
    return p


def wait_for(pool, ids, timeout=30.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if all(pool.jobs[i]['status'] in ('done', 'failed') for i in ids):
            return True
        time.sleep(0.1)
    return False


def make_cfg(tmp: str, **kw) -> dict:
    c = {'code': REPO, 'work': os.path.join(tmp, 'work'), 'blender': fake_blender(tmp), 'device': 'GPU', 'procs': 2, 'threads': 1, 'timeout': 30.0}
    c.update(kw)
    return c


PARAMS = {'views': ['az000', 'az090'], 'lights': ['key', 'graze'], 'samples': 4, 'w': 0, 'h': 0, 'shade': 'orig'}


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tests_render_')
        self.c = make_cfg(self.tmp)
        self.fr = WR.load_forms_render(self.c)
        self.state = KW.State()
        self.pool = WR.Pool(self.state, self.c, self.fr)

    def test_job_done_zip_has_all_frames(self):
        self.pool.submit('a1', GLB, PARAMS)
        self.assertTrue(wait_for(self.pool, ['a1']))
        j = self.pool.jobs['a1']
        self.assertEqual(j['status'], 'done', j.get('error'))
        data = open(j['zip'], 'rb').read()
        self.assertEqual(j['sha256'], hashlib.sha256(data).hexdigest())
        names = zipfile.ZipFile(j['zip']).namelist()
        for n in self.fr.frame_names(PARAMS['views'], PARAMS['lights']):
            self.assertIn(n, names)
        self.assertIn('render.log', names)
        self.assertEqual(j['metrics']['frames'], 4)
        self.assertIn('fake CUDA', j['metrics']['gpu'])                 # устройство GPU дошло до render_stand

    def test_device_flag_follows_config(self):
        pool = WR.Pool(self.state, make_cfg(self.tmp, device='CPU'), self.fr)
        pool.submit('cpu1', GLB, PARAMS)
        self.assertTrue(wait_for(pool, ['cpu1']))
        self.assertEqual(pool.jobs['cpu1']['metrics']['gpu'], '')

    def test_same_job_id_is_one_work(self):
        a = self.pool.submit('dup', GLB, PARAMS)
        b = self.pool.submit('dup', GLB, PARAMS)
        self.assertIs(a, b)
        self.assertTrue(wait_for(self.pool, ['dup']))
        self.assertEqual(self.pool.counts()['total'], 1)

    def test_failed_job_has_reason_and_counts(self):
        self.pool.submit('bad', GLB + b'FAILME', PARAMS)
        self.pool.submit('ok', GLB, PARAMS)
        self.assertTrue(wait_for(self.pool, ['bad', 'ok']))
        self.assertEqual(self.pool.jobs['bad']['status'], 'failed')
        self.assertIn('blender rc=1', self.pool.jobs['bad']['error'])
        self.assertIn('упал нарочно', self.pool.jobs['bad']['error'])
        self.assertEqual(self.pool.jobs['ok']['status'], 'done')
        n = self.pool.counts()
        self.assertEqual((n['done'], n['failed']), (1, 1))
        self.assertFalse(self.state.busy)
        self.assertIsNone(self.state.job)

    def test_no_cuda_is_failure_not_silent_cpu(self):
        self.pool.submit('ng', GLB + b'NOGPU', PARAMS)
        self.assertTrue(wait_for(self.pool, ['ng']))
        self.assertEqual(self.pool.jobs['ng']['status'], 'failed')
        self.assertIn('rc=3', self.pool.jobs['ng']['error'])

    def test_missing_frame_fails_with_names(self):
        self.pool.submit('pt', GLB + b'PARTIAL', PARAMS)
        self.assertTrue(wait_for(self.pool, ['pt']))
        self.assertEqual(self.pool.jobs['pt']['status'], 'failed')
        self.assertIn('кадров меньше', self.pool.jobs['pt']['error'])

    def test_concurrency_limit(self):
        c = make_cfg(self.tmp, procs=1)
        pool = WR.Pool(self.state, c, self.fr)
        ids = [f'c{i}' for i in range(3)]
        for i in ids:
            pool.submit(i, GLB + b'SLOW', PARAMS)
        peak = 0
        t0 = time.time()
        while time.time() - t0 < 40 and not all(pool.jobs[i]['status'] in ('done', 'failed') for i in ids):
            peak = max(peak, pool.counts()['running'])
            time.sleep(0.05)
        self.assertEqual(peak, 1)
        self.assertTrue(all(pool.jobs[i]['status'] == 'done' for i in ids))

    def test_timeout_kills_own_process(self):
        pool = WR.Pool(self.state, make_cfg(self.tmp, timeout=0.5), self.fr)
        pool.submit('slow', GLB + b'SLOW', PARAMS)
        self.assertTrue(wait_for(pool, ['slow']))
        self.assertEqual(pool.jobs['slow']['status'], 'failed')
        self.assertIn('снят', pool.jobs['slow']['error'])

    def test_step_shows_progress(self):
        self.pool.submit('s1', GLB + b'SLOW', PARAMS)
        time.sleep(0.6)
        jv = self.state.job_view()
        self.assertEqual(jv['id'], 'render-batch')
        self.assertIn('рисую', jv['step'])
        self.assertTrue(wait_for(self.pool, ['s1']))

    def test_custom_size_goes_to_blender(self):
        seen = {}

        class P:
            def __init__(s, cmd, **kw):
                seen['cmd'] = cmd
                s.rc = 0

            def poll(s):
                return 0

        pool = WR.Pool(self.state, self.c, self.fr, popen=P)
        pool.submit('w1', GLB, dict(PARAMS, w=640, h=480))
        wait_for(pool, ['w1'], 5)
        cmd = seen['cmd']
        self.assertEqual((cmd[cmd.index('--w') + 1], cmd[cmd.index('--h') + 1], cmd[cmd.index('--device') + 1]), ('640', '480', 'GPU'))


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='tests_render_http_')
        c = make_cfg(cls.tmp)
        cls.fr = WR.load_forms_render(c)
        cls.state = KW.State()
        cls.pool = WR.Pool(cls.state, c, cls.fr)
        cls.wd = KW.Watchdog(600, 600)
        stop = threading.Event()
        h = WR.make_handler(cls.state, cls.pool, cls.wd, stop, {'blender': 'Blender fake', 'cuda': ['fake']})
        cls.srv = KW.make_server(0, h, host='127.0.0.1')
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.gw = RT.Gateway(f'http://127.0.0.1:{cls.srv.server_address[1]}', '')

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def body(self, jid='h1', glb=GLB, **kw):
        import base64
        import zlib
        b = {'job_id': jid, 'glb_z': base64.b64encode(zlib.compress(glb)).decode(), 'views': ['az000'], 'lights': ['key'], 'samples': 4}
        b.update(kw)
        return b

    def test_not_ready_503_then_ready(self):
        self.state.phase = 'loading'
        c, _ = self.gw.call('POST', '/jobs', self.body('n0'))
        self.assertEqual(c, 503)
        self.state.phase = 'ready'
        c, _ = self.gw.call('POST', '/jobs', self.body('n0'))
        self.assertEqual(c, 202)
        self.assertTrue(wait_for(self.pool, ['n0']))

    def test_bad_inputs(self):
        self.state.phase = 'ready'
        post = lambda b: self.gw.call('POST', '/jobs', b)[0]
        self.assertEqual(post(self.body('../evil')), 400)
        self.assertEqual(post(self.body('b1', glb=b'not a glb')), 400)
        self.assertEqual(post(self.body('b2', views=['нет'])), 400)
        self.assertEqual(post(self.body('b3', views=['az000', 'az000'])), 400)
        self.assertEqual(post(self.body('b4', lights=['sun'])), 400)
        self.assertEqual(post(self.body('b5', samples=0)), 400)
        self.assertEqual(post(self.body('b6', w=640)), 400)                     # w и h — только вместе
        self.assertEqual(post({'job_id': 'b7'}), 400)
        self.assertEqual(self.gw.call('GET', '/jobs/net')[0], 404)

    def test_result_409_until_done_and_health(self):
        self.state.phase = 'ready'
        self.gw.call('POST', '/jobs', self.body('r1', glb=GLB + b'SLOW'))
        c, _ = self.gw.call('GET', '/jobs/r1/result', raw=True)
        self.assertEqual(c, 409)
        c, h = self.gw.call('GET', '/health')
        self.assertEqual(c, 200)
        self.assertEqual(h['cuda'], ['fake'])
        self.assertIn('pool', h)
        self.assertTrue(wait_for(self.pool, ['r1']))
        c, data = self.gw.call('GET', '/jobs/r1/result', raw=True)
        self.assertEqual((c, hashlib.sha256(data).hexdigest()), (200, self.pool.jobs['r1']['sha256']))

    def test_driver_pack_roundtrip(self):
        """submit_pack/poll_pack драйвера на настоящем воркере: кадры забраны, sha сверен, сидячему — лишний вид, отказ — счётом с причиной."""
        self.state.phase = 'ready'
        d = tempfile.mkdtemp(prefix='tests_render_drv_')
        for sku, extra in (('p1', b''), ('p2', b''), ('p3', b'FAILME')):
            open(os.path.join(d, f'{sku}-hd.glb'), 'wb').write(GLB + extra)

        class A:
            glb_dir = d
            glb_name = '{sku}-hd.glb'
            out = os.path.join(d, 'out')
            samples, shade = 4, 'orig'
        os.makedirs(A.out)
        cur, info = RT.submit_pack(self.gw, A, ['p1', 'p2', 'p3'], {'p2'}, 1.0)
        self.assertIsNotNone(cur, info)
        self.assertEqual(len(cur['expect']['p1']), 10)                       # 5 видов × 2 света
        self.assertEqual(len(cur['expect']['p2']), 12)                       # сидячий: + низкий боковой
        st, res = 'running', {}
        t0 = time.time()
        while st == 'running' and time.time() - t0 < 30:
            st, res = RT.poll_pack(self.gw, A, cur, time.time())
            time.sleep(0.2)
        self.assertEqual(st, 'failed')                                       # p3 нарочно упал
        self.assertEqual((res['ok'], res['total']), (2, 3))
        self.assertIn('p3', res['metrics']['failed'])
        self.assertEqual(len([f for f in os.listdir(os.path.join(A.out, 'p2')) if f.endswith('.png')]), 12)
        self.assertTrue(os.path.isfile(os.path.join(A.out, 'items.json')))

    def test_driver_not_accepted_reports_sku(self):
        self.state.phase = 'broken'
        d = tempfile.mkdtemp(prefix='tests_render_drv2_')
        open(os.path.join(d, 'q1-hd.glb'), 'wb').write(GLB)

        class A:
            glb_dir = d
            glb_name = '{sku}-hd.glb'
            samples, shade = 4, 'orig'
        cur, info = RT.submit_pack(self.gw, A, ['q1'], set(), 1.0)
        self.state.phase = 'ready'
        self.assertIsNone(cur)
        self.assertEqual((info['http'], info['sku']), (503, 'q1'))


class PureTests(unittest.TestCase):
    def test_job_id_changes_with_input_and_params(self):
        class A:
            samples, shade = 16, 'orig'
        a, b = A(), A()
        b.samples = 32
        v, lt = ('az000',), ('key',)
        self.assertNotEqual(RT.job_id('s', a, GLB, v, lt), RT.job_id('s', a, GLB + b'x', v, lt))
        self.assertNotEqual(RT.job_id('s', a, GLB, v, lt), RT.job_id('s', b, GLB, v, lt))
        self.assertNotEqual(RT.job_id('s', a, GLB, v, lt), RT.job_id('s', a, GLB, v + ('az090',), lt))
        self.assertEqual(RT.job_id('s', a, GLB, v, lt), RT.job_id('s', a, GLB, v, lt))

    def test_file_list_exists_and_staged(self):
        for f in SRC.read_list():
            self.assertTrue(os.path.isfile(os.path.join(REPO, f)), f'нет файла из списка: {f}')
        d = os.path.join(tempfile.mkdtemp(prefix='tests_render_stage_'), 'code')
        import stage_pose_code as SPC
        done = SPC.stage(REPO, d, SRC.read_list())
        self.assertEqual(len(done), len(SRC.read_list()))
        with self.assertRaises(FileNotFoundError):
            SPC.stage(REPO, os.path.join(d, 'x'), ['tools/scout/нет-такого.py'])

    def test_worker_shows_progress_for_driver_guard(self):
        import kit_driver as KD
        self.assertEqual(KD.worker_progress_refusal(RT.WORKER), '')

    def test_body_has_no_secrets_and_gpu(self):
        body = RT.build_body('trial-forms-t', 'x/y@sha256:' + 'a' * 64, 'low', 'cls', {}, 3600, 900, 2, 4, worker_z='Z')
        text = json.dumps(body)
        self.assertNotIn('SALAD_API_KEY', text)
        self.assertIn('RENDER_PROCS', text)
        self.assertIn('KIT_WORKER_Z', text)
        import kit_driver as KD
        prof = KD.resource_profile(RT.WORK_TYPE)
        self.assertEqual(body['container']['resources'], {**KD.profile_resources(prof, ''), 'gpu_classes': ['cls']})   # ресурсы — только профиль, в build_body своих нет

    def test_render_stand_has_device_switch(self):
        """render_stand умеет --device и не падает молча на процессор: нет CUDA → sys.exit(3)."""
        src = open(os.path.join(REPO, 'tools/scout/stablegen/render_stand.py'), encoding='utf-8').read()
        self.assertIn("'--device'", src)
        self.assertIn('sys.exit(3)', src)
        self.assertIn("sc.cycles.device = 'CPU'", src)                       # по умолчанию всё как раньше

    def test_rules_have_start_thresholds(self):
        r = RT.load_rules()
        self.assertGreaterEqual(r['compare']['iou_min'], 0.99)
        for k in ('procs', 'samples'):
            self.assertIn(k, r)

    def test_compare_catches_silhouette_and_black(self):
        try:
            import numpy as np
            from PIL import Image
        except ImportError:
            self.skipTest('нет numpy/Pillow')
        import compare_render as CR
        rules = CR.load_rules()
        tmp = tempfile.mkdtemp(prefix='tests_render_cmp_')

        def put(root, name, shift=0, black=False, noise=0):
            os.makedirs(os.path.join(root, 's'), exist_ok=True)
            img = np.full((90, 120, 3), 240, np.uint8)
            if not black:
                img[20:70, 30 + shift:90 + shift] = 120
            else:
                img[:] = 0
            if noise:
                img = np.clip(img.astype(int) + np.random.RandomState(1).randint(-noise, noise + 1, img.shape), 0, 255).astype(np.uint8)
            Image.fromarray(img).save(os.path.join(root, 's', name))
        ref = os.path.join(tmp, 'ref')
        put(ref, '01_az000_clay.png')
        same = os.path.join(tmp, 'same')
        put(same, '01_az000_clay.png', noise=2)                              # шум Cycles — не важен
        self.assertTrue(CR.compare(same, ref, ['s'], rules)['s']['ok'])
        moved = os.path.join(tmp, 'moved')
        put(moved, '01_az000_clay.png', shift=8)
        self.assertFalse(CR.compare(moved, ref, ['s'], rules)['s']['ok'])
        blk = os.path.join(tmp, 'blk')
        put(blk, '01_az000_clay.png', black=True)
        res = CR.compare(blk, ref, ['s'], rules)['s']
        self.assertFalse(res['ok'])
        self.assertTrue(any('чёрный' in p or 'пустой' in p for p in res['problems']))
        miss = os.path.join(tmp, 'miss')
        os.makedirs(os.path.join(miss, 's'))
        self.assertFalse(CR.compare(miss, ref, ['s'], rules)['s']['ok'])      # нет кадров — не совпало


if __name__ == '__main__':
    unittest.main(verbosity=1)

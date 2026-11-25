#!/usr/bin/env python3
"""Тесты воркера и драйвера Salad «камера по фото» (T-184/1, очередь 2). Без сети и без Salad: настоящий HTTP-сервер воркера на localhost, вместо цепочки pose_fit — маленькие поддельные
скрипты (пишут те же файлы результата). Запуск: python tools/scout/salad/pose/tests_pose.py (нужны только stdlib и numpy-free код воркера)."""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
import compare_pose as CP  # noqa: E402
import kit_worker as KW  # noqa: E402
import pose_trial as PT  # noqa: E402
import stage_pose_code as SPC  # noqa: E402
import worker_pose as WP  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
PNG = b'\x89PNG\r\n\x1a\n' + b'0' * 64
GLB = b'glTF' + b'1' * 200

FAKE_FIT = '''
import json, os, sys, time
a = sys.argv[1:]
glb = open(a[a.index('--glb') + 1], 'rb').read()
out = a[a.index('--out-run') + 1]
if b'FAILME' in glb:
    print('прогон упал нарочно'); sys.exit(1)
if b'SLOW' in glb:
    time.sleep(2.0)
os.makedirs(os.path.join(out, 'stages', 'render_view0'), exist_ok=True)
json.dump({'camera': {'az': 10.0, 'el': 5.0, 'd': 3.0}, 'iou_frame': 0.9}, open(os.path.join(out, 'pose.json'), 'w'))
open(os.path.join(out, 'stages', 'render_view0', 'mask.png'), 'wb').write(b'm' * 100)
print('pose_fit готово')
'''
FAKE_CHECK = '''
import json, os, sys
a = sys.argv[1:]
out = a[a.index('--run') + 1]
os.makedirs(os.path.join(out, '04-camera'), exist_ok=True)
json.dump({'passed': True, 'reason': 'камера легла', 'metrics': {}, 'metric': {'ok': True}}, open(os.path.join(out, '04-camera', 'check.json'), 'w'))
print('check готово')
'''


def fake_code(root: str) -> str:
    d = os.path.join(root, 'code')
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'pose_fit.py'), 'w').write(FAKE_FIT)
    open(os.path.join(d, 'camera_check.py'), 'w').write(FAKE_CHECK)
    return d


def wait_for(pool, ids, timeout=30.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if all(pool.jobs[i]['status'] in ('done', 'failed') for i in ids):
            return True
        time.sleep(0.1)
    return False


class PoolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='tests_pose_')
        self.c = {'code': fake_code(self.tmp), 'work': os.path.join(self.tmp, 'work'), 'procs': 2, 'omp': '1', 'fit_timeout': 30.0, 'check_timeout': 30.0}
        self.state = WP.PoseState()
        self.pool = WP.Pool(self.state, self.c)

    def test_job_done_zip_and_metrics(self):
        self.pool.submit('a1', GLB, PNG, {})
        self.assertTrue(wait_for(self.pool, ['a1']))
        j = self.pool.jobs['a1']
        self.assertEqual(j['status'], 'done', j.get('error'))
        data = open(j['zip'], 'rb').read()
        self.assertEqual(j['sha256'], hashlib.sha256(data).hexdigest())
        names = zipfile.ZipFile(j['zip']).namelist()
        for need in PT.NEED:
            self.assertIn(need, names)
        self.assertIn('fit.log', names)
        self.assertEqual(j['metrics']['passed'], True)
        self.assertEqual(j['metrics']['camera']['az'], 10.0)
        self.assertGreater(j['wall_s'], 0)

    def test_same_job_id_is_one_work(self):
        a = self.pool.submit('dup', GLB, PNG, {})
        b = self.pool.submit('dup', GLB, PNG, {})
        self.assertIs(a, b)
        self.assertTrue(wait_for(self.pool, ['dup']))
        self.assertEqual(self.pool.counts()['total'], 1)

    def test_failed_job_has_reason_and_counts(self):
        self.pool.submit('bad', GLB + b'FAILME', PNG, {})
        self.pool.submit('ok', GLB, PNG, {})
        self.assertTrue(wait_for(self.pool, ['bad', 'ok']))
        self.assertEqual(self.pool.jobs['bad']['status'], 'failed')
        self.assertIn('pose_fit rc=1', self.pool.jobs['bad']['error'])
        self.assertIn('упал нарочно', self.pool.jobs['bad']['error'])
        self.assertEqual(self.pool.jobs['ok']['status'], 'done')
        n = self.pool.counts()
        self.assertEqual((n['done'], n['failed']), (1, 1))
        self.assertFalse(self.state.busy)
        self.assertIsNone(self.state.job)               # ход закрыт, когда всё закончилось

    def test_concurrency_limit(self):
        self.c['procs'] = 1
        pool = WP.Pool(self.state, self.c)
        ids = [f'c{i}' for i in range(3)]
        for i in ids:
            pool.submit(i, GLB + b'SLOW', PNG, {})
        peak = 0
        t0 = time.time()
        while time.time() - t0 < 30 and not all(pool.jobs[i]['status'] in ('done', 'failed') for i in ids):
            peak = max(peak, pool.counts()['running'])
            time.sleep(0.05)
        self.assertEqual(peak, 1)
        self.assertTrue(all(pool.jobs[i]['status'] == 'done' for i in ids))

    def test_timeout_kills_own_process(self):
        self.c['fit_timeout'] = 0.5
        pool = WP.Pool(self.state, self.c)
        pool.submit('slow', GLB + b'SLOW', PNG, {})
        self.assertTrue(wait_for(pool, ['slow']))
        self.assertEqual(pool.jobs['slow']['status'], 'failed')
        self.assertIn('снят', pool.jobs['slow']['error'])

    def test_step_shows_progress(self):
        self.pool.submit('s1', GLB + b'SLOW', PNG, {})
        time.sleep(0.5)
        jv = self.state.job_view()
        self.assertEqual(jv['id'], 'pose-batch')
        self.assertIn('считаю', jv['step'])
        self.assertTrue(wait_for(self.pool, ['s1']))

    def test_state_reports_cpu_not_gpu(self):
        import subprocess
        p = subprocess.Popen([sys.executable, '-c', 'import time\nt=time.time()\nwhile time.time()-t<3: pass'])
        self.state.begin_job('x')
        self.state.pids[p.pid] = WP.proc_cpu_s(p.pid) or 0.0
        time.sleep(1.2)
        jv = self.state.job_view()
        p.wait()
        self.assertGreaterEqual(jv['gpu_util'], 50.0)    # занятый процесс — «считает»
        self.assertEqual(jv['procs_live'], 1)


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix='tests_pose_http_')
        c = {'code': fake_code(cls.tmp), 'work': os.path.join(cls.tmp, 'work'), 'procs': 2, 'omp': '1', 'fit_timeout': 30.0, 'check_timeout': 30.0}
        cls.state = WP.PoseState()
        cls.pool = WP.Pool(cls.state, c)
        cls.wd = KW.Watchdog(600, 600)
        stop = threading.Event()
        h = WP.make_handler(cls.state, cls.pool, cls.wd, stop, {'cpu_model': 'x', 'cpus': 2, 'libs': {'python': 'x'}})
        cls.srv = KW.make_server(0, h, host='127.0.0.1')
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.gw = PT.Gateway(f'http://127.0.0.1:{cls.srv.server_address[1]}', '')

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def body(self, jid='h1', glb=GLB, photo=PNG):
        import base64
        import zlib
        return {'job_id': jid, 'glb_z': base64.b64encode(zlib.compress(glb)).decode(), 'photo_b64': base64.b64encode(photo).decode()}

    def test_not_ready_503_then_ready(self):
        self.state.phase = 'loading'
        c, r = self.gw.call('POST', '/jobs', self.body('n0'))
        self.assertEqual(c, 503)
        self.state.phase = 'ready'
        c, _ = self.gw.call('POST', '/jobs', self.body('n0'))
        self.assertEqual(c, 202)
        self.assertTrue(wait_for(self.pool, ['n0']))

    def test_bad_inputs(self):
        self.state.phase = 'ready'
        self.assertEqual(self.gw.call('POST', '/jobs', self.body('../evil'))[0], 400)
        self.assertEqual(self.gw.call('POST', '/jobs', self.body('b1', glb=b'not a glb'))[0], 400)
        self.assertEqual(self.gw.call('POST', '/jobs', self.body('b2', photo=b'not png'))[0], 400)
        self.assertEqual(self.gw.call('POST', '/jobs', {'job_id': 'b3'})[0], 400)
        self.assertEqual(self.gw.call('GET', '/jobs/net')[0], 404)

    def test_result_409_until_done_and_health(self):
        self.state.phase = 'ready'
        self.gw.call('POST', '/jobs', self.body('r1', glb=GLB + b'SLOW'))
        c, _ = self.gw.call('GET', '/jobs/r1/result', raw=True)
        self.assertEqual(c, 409)
        c, h = self.gw.call('GET', '/health')
        self.assertEqual(c, 200)
        self.assertEqual(h['cpu_model'], 'x')
        self.assertIn('pool', h)
        self.assertTrue(wait_for(self.pool, ['r1']))
        c, data = self.gw.call('GET', '/jobs/r1/result', raw=True)
        self.assertEqual((c, hashlib.sha256(data).hexdigest()), (200, self.pool.jobs['r1']['sha256']))

    def test_driver_pack_roundtrip(self):
        """submit_pack/poll_pack драйвера на настоящем воркере: результаты забраны, sha сверен, отказ — счётом с причиной."""
        self.state.phase = 'ready'
        d = tempfile.mkdtemp(prefix='tests_pose_drv_')
        for sku, extra in (('p1', b''), ('p2', b''), ('p3', b'FAILME')):
            open(os.path.join(d, f'{sku}-hd.glb'), 'wb').write(GLB + extra)
            open(os.path.join(d, f'{sku}.hd.rgba.png'), 'wb').write(PNG)

        class A:
            glb_dir = photo_dir = d
            glb_name, photo_name = '{sku}-hd.glb', '{sku}.hd.rgba.png'
            out = os.path.join(d, 'out')
            px = n_fit = topk = None
        os.makedirs(A.out)
        cur, info = PT.submit_pack(self.gw, A, ['p1', 'p2', 'p3'], 1.0)
        self.assertIsNotNone(cur, info)
        st, res = 'running', {}
        t0 = time.time()
        while st == 'running' and time.time() - t0 < 30:
            st, res = PT.poll_pack(self.gw, A, cur, time.time())
            time.sleep(0.2)
        self.assertEqual(st, 'failed')                     # p3 нарочно упал
        self.assertEqual((res['ok'], res['total']), (2, 3))
        self.assertIn('p3', res['metrics']['failed'])
        self.assertTrue(os.path.isfile(os.path.join(A.out, 'p1', 'pose.json')))
        self.assertTrue(os.path.isfile(os.path.join(A.out, 'p2', '04-camera', 'check.json')))
        self.assertTrue(os.path.isfile(os.path.join(A.out, 'items.json')))

    def test_driver_not_accepted_reports_sku(self):
        self.state.phase = 'broken'
        d = tempfile.mkdtemp(prefix='tests_pose_drv2_')
        open(os.path.join(d, 'q1-hd.glb'), 'wb').write(GLB)
        open(os.path.join(d, 'q1.hd.rgba.png'), 'wb').write(PNG)

        class A:
            glb_dir = photo_dir = d
            glb_name, photo_name = '{sku}-hd.glb', '{sku}.hd.rgba.png'
            px = n_fit = topk = None
        cur, info = PT.submit_pack(self.gw, A, ['q1'], 1.0)
        self.state.phase = 'ready'
        self.assertIsNone(cur)
        self.assertEqual((info['http'], info['sku']), (503, 'q1'))


class PureTests(unittest.TestCase):
    def test_fit_flags_whitelist(self):
        """T-20261124-18: флаги подгонки в подпроцесс — только из белого списка и значений 0/1/probe; мусор → {} (камера как без флагов)."""
        self.assertEqual(WP.fit_flags('POSE_JUNCTION=1, POSE_VERT_AXIS=1,POSE_ANGLE_FIT=probe'), {'POSE_JUNCTION': '1', 'POSE_VERT_AXIS': '1', 'POSE_ANGLE_FIT': 'probe'})
        self.assertEqual(WP.fit_flags('PATH=/x,POSE_JUNCTION=2,POSE_CODE=/etc,LD_PRELOAD=1'), {})
        self.assertEqual(WP.fit_flags(''), {})
        body = PT.build_body('trial-pose-t', 'x/y@sha256:' + 'a' * 64, 'low', 'cls', {}, 3600, 900, 6, 1, worker_z='Z', flags='POSE_JUNCTION=1')
        self.assertEqual(body['container']['environment_variables']['POSE_FIT_FLAGS'], 'POSE_JUNCTION=1')
        body0 = PT.build_body('trial-pose-t', 'x/y@sha256:' + 'a' * 64, 'low', 'cls', {}, 3600, 900, 6, 1, worker_z='Z')
        self.assertNotIn('POSE_FIT_FLAGS', body0['container']['environment_variables'])

    def test_safe_extract_blocks_traversal(self):
        import io
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('../evil.txt', 'x')
        with self.assertRaises(ValueError):
            PT.safe_extract(buf.getvalue(), tempfile.mkdtemp(prefix='tests_pose_zip_'))

    def test_job_id_changes_with_input_and_params(self):
        class A:
            px = n_fit = topk = None
        a, b = A(), A()
        b.px = 1024
        self.assertNotEqual(PT.job_id('s', a, GLB, PNG), PT.job_id('s', a, GLB + b'x', PNG))
        self.assertNotEqual(PT.job_id('s', a, GLB, PNG), PT.job_id('s', b, GLB, PNG))
        self.assertEqual(PT.job_id('s', a, GLB, PNG), PT.job_id('s', a, GLB, PNG))

    def test_compare_rules(self):
        r = CP.load_rules()
        ref = {'az': 359.9, 'el': 6.0, 'd': 5.6, 'iou': 0.95, 'passed': True, 'failed': [], 'reason': ''}
        ours = dict(ref, az=0.1, el=6.2, d=5.62, iou=0.953)
        self.assertTrue(CP.compare(ref, ours, r)['match'])
        self.assertFalse(CP.compare(ref, dict(ours, passed=False), r)['match'])                      # вердикт — точно
        self.assertFalse(CP.compare(ref, dict(ours, failed=['miss']), r)['match'])
        self.assertFalse(CP.compare(ref, dict(ours, az=1.0), r)['match'])
        self.assertFalse(CP.compare(ref, dict(ours, d=6.5), r)['match'])
        self.assertFalse(CP.compare(ref, dict(ours, iou=0.96), r)['match'])

    def test_file_list_covers_import_closure(self):
        """Список файлов образа не отстаёт от кода: все наши модули, которые импортирует цепочка (в т.ч. лениво), — в pose_files.txt, и все файлы списка существуют."""
        listed = set(SPC.read_list())
        for f in listed:
            self.assertTrue(os.path.isfile(os.path.join(REPO, f)), f'нет файла из списка: {f}')
        roots = [os.path.join(REPO, 'tools/scout/salad/trellis'), os.path.join(REPO, 'tools/scout'), os.path.join(REPO, 'tools/scout/salad')]

        def find(n):
            for r in roots:
                p = os.path.join(r, n + '.py')
                if os.path.isfile(p):
                    return p
            return None
        seen, todo = {}, ['pose_fit', 'camera_check', 'stages_cpu']
        while todo:
            n = todo.pop()
            p = find(n)
            if not p or n in seen:
                continue
            seen[n] = os.path.relpath(p, REPO)
            with open(p, encoding='utf-8') as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                names = [a.name.split('.')[0] for a in node.names] if isinstance(node, ast.Import) else ([node.module.split('.')[0]] if isinstance(node, ast.ImportFrom) and node.module and not node.level else [])
                todo += [x for x in names if find(x)]
        self.assertEqual(sorted(set(seen.values()) - listed), [], 'модули цепочки не в pose_files.txt (образ без них упадёт)')

    def test_stage_copies_and_refuses_missing(self):
        d = os.path.join(tempfile.mkdtemp(prefix='tests_pose_stage_'), 'code')
        done = SPC.stage(REPO, d)
        self.assertEqual(len(done), len(SPC.read_list()))
        self.assertTrue(os.path.isfile(os.path.join(d, 'tools/scout/rules/camera-check.json')))
        with self.assertRaises(FileNotFoundError):
            SPC.stage(REPO, os.path.join(d, 'x'), ['tools/scout/нет-такого.py'])
        with self.assertRaises(FileExistsError):
            SPC.stage(REPO, d)

    def test_rules_json_of_closure_are_listed(self):
        """Правила, на которые ссылаются модули списка (строковый литерал `<имя>.json`, такой файл лежит в tools/scout/rules), — тоже в pose_files.txt: образ собирается по списку (сборка 24.11 упала на tex-coverage.json)."""
        listed = set(SPC.read_list())
        have = set(os.listdir(os.path.join(REPO, 'tools/scout/rules')))
        need = {}
        for f in listed:
            if not f.endswith('.py'):
                continue
            with open(os.path.join(REPO, f), encoding='utf-8') as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    for m in re.findall(r'[A-Za-z0-9_-]+\.json', node.value):
                        if m in have:
                            need.setdefault('tools/scout/rules/' + m, f)
        self.assertEqual(sorted((r, src) for r, src in need.items() if r not in listed), [], 'правила, читаемые модулями образа, не в pose_files.txt')

    def test_image_import_line_works_from_staged_dir(self):
        """Та же строка проверки комплектности, что в Dockerfile.pose (RUN python -I -c …), прогнана из каталога, собранного по pose_files.txt (вместо /opt/scout-root — временная папка)."""
        try:
            import numpy, cv2, scipy, PIL, trimesh  # noqa: F401,E401
        except ImportError as e:
            self.skipTest(f'нет библиотек образа в этом окружении: {e}')
        import subprocess
        text = open(os.path.join(HERE, 'Dockerfile.pose'), encoding='utf-8').read()
        m = re.search(r'RUN python -I -c "(.*?)"\n', text, re.S)
        self.assertIsNotNone(m, 'в Dockerfile.pose нет строки проверки комплектности')
        d = os.path.join(tempfile.mkdtemp(prefix='tests_pose_img_'), 'code')
        SPC.stage(REPO, d)
        code = m.group(1).replace('\\\n', '').replace('/opt/scout-root', d)
        r = subprocess.run([sys.executable, '-I', '-c', code], cwd=tempfile.gettempdir(), capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 0, 'строка проверки образа упала на каталоге по pose_files.txt:\n' + r.stderr[-1500:])

    def test_worker_shows_progress_for_driver_guard(self):
        import kit_driver as KD
        self.assertEqual(KD.worker_progress_refusal(PT.WORKER), '')

    def test_body_has_no_secrets_and_digest_required(self):
        body = PT.build_body('trial-pose-t', 'x/y@sha256:' + 'a' * 64, 'low', 'cls', {}, 3600, 900, 6, 1, worker_z='Z')
        text = json.dumps(body)
        self.assertNotIn('SALAD_API_KEY', text)
        self.assertIn('POSE_PROCS', text)
        self.assertIn('KIT_WORKER_Z', text)
        import kit_driver as KD
        prof = KD.resource_profile(PT.WORK_TYPE)
        self.assertEqual(body['container']['resources'], {**KD.profile_resources(prof, ''), 'gpu_classes': ['cls']})   # ресурсы — только профиль, в build_body своих нет


class SubmitPostTests(unittest.TestCase):
    """Отправка пакета идёт через общий `kit_driver.post_job` (урок T-178/2: шлюз Salad молчит на холодной ноде): «нет ответа» ≠ отказ, один повтор по идемпотентному job_id."""

    def _args(self):
        import types
        d = tempfile.mkdtemp(prefix='tests_pose_post_')
        for n, data in (('s1.glb', GLB), ('s1.png', b'\x89PNG')):
            with open(os.path.join(d, n), 'wb') as f:
                f.write(data)
        return types.SimpleNamespace(glb_dir=d, glb_name='{sku}.glb', photo_dir=d, photo_name='{sku}.png', px=1024, n_fit=8, topk=3)

    def _gw(self, post_codes, worker_sees):
        calls = []

        class GW:
            def call(self, method, path, body=None, timeout=60, raw=False):
                calls.append((method, path, timeout))
                if method == 'POST':
                    return post_codes.pop(0), {}
                return (200 if worker_sees else 404), {}
        return GW(), calls

    def test_no_answer_then_worker_did_not_see_then_retry_accepts(self):
        gw, calls = self._gw([-1, 202], worker_sees=False)
        cur, info = PT.submit_pack(gw, self._args(), ['s1'], 100.0)
        self.assertIsNotNone(cur, info)
        self.assertEqual([c[0] for c in calls].count('POST'), 2)
        self.assertGreaterEqual(calls[0][2], 90)                      # таймаут по размеру тела, не зашитые 30–60 с

    def test_no_answer_but_worker_saw_job_is_accepted_without_second_post(self):
        gw, calls = self._gw([-1], worker_sees=True)
        cur, info = PT.submit_pack(gw, self._args(), ['s1'], 100.0)
        self.assertIsNotNone(cur, info)
        self.assertEqual([c[0] for c in calls].count('POST'), 1)

    def test_busy_429_is_returned_as_http_for_the_driver_to_wait(self):
        gw, _ = self._gw([429], worker_sees=False)
        cur, info = PT.submit_pack(gw, self._args(), ['s1'], 100.0)
        self.assertIsNone(cur)
        self.assertEqual(info['http'], 429)


class TierRuleTests(unittest.TestCase):
    """Правило владельца 22.11 (TG 1456/1457): low; нет машин → medium; batch и high — никогда."""

    def test_low_no_machine_goes_medium_only(self):
        self.assertEqual(PT.fallback_tier('low', 'no_machine'), 'medium')
        for tier, why in (('low', 'done'), ('low', 'money'), ('low', ''), ('medium', 'no_machine'), ('medium', 'done')):
            self.assertIsNone(PT.fallback_tier(tier, why), (tier, why))

    def test_default_is_low_and_batch_high_refused(self):
        import subprocess
        src = open(PT.__file__, encoding='utf-8').read()
        self.assertIn("default='low', choices=['low', 'medium']", src)
        r = subprocess.run([sys.executable, '-I', PT.__file__, '--tier', 'batch', '--skus', 'x', '--image', 'y'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        r = subprocess.run([sys.executable, '-I', PT.__file__, '--tier', 'high', '--skus', 'x', '--image', 'y'], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)

    def test_stopped_by_reads_summary(self):
        import types
        d = tempfile.mkdtemp(prefix='tests_pose_sum_')
        a = types.SimpleNamespace(out=d, suffix='z1')
        self.assertEqual(PT.stopped_by(a), '')
        with open(os.path.join(d, 'summary-trial-pose-z1.json'), 'w') as f:
            json.dump({'stopped_by': 'no_machine'}, f)
        self.assertEqual(PT.stopped_by(a), 'no_machine')


if __name__ == '__main__':
    unittest.main(verbosity=1)

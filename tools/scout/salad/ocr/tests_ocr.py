#!/usr/bin/env python3
"""Тесты «кэш слов OCR на Salad» (T-176/ocr-salad). Без сети, Salad и rapidocr: настоящий HTTP-сервер воркера на localhost, вместо OCR — поддельный `words_on_sheet`.
Запуск: python tools/scout/salad/ocr/tests_ocr.py (stdlib). Сторожа: (1) код образа = снимок 20261126-2234 побайтно; (2) слияние не теряет строки при параллельной записи; (3) воркер и драйвер."""
from __future__ import annotations

import base64
import hashlib
import http.client
import json
import multiprocessing as mp
import os
import sys
import tempfile
import threading
import time
import types
import unittest
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', 'pose'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'render_gpu'))
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402
import merge_words as MW  # noqa: E402
import ocr_words_run as RUN  # noqa: E402
import stage_ocr_code as SOC  # noqa: E402
import worker_ocr as WO  # noqa: E402

REPO = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
SNAPSHOT = os.path.expanduser('~/remlab-logs/etazhi-walls/voronka/versii/20261126-2234')
FROZEN = os.path.join(HERE, 'frozen')


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ---------------------------------------------------------------- 1. код образа = снимок
class TestFrozen(unittest.TestCase):
    def test_files_match_recorded_sums(self):
        """frozen/* совпадает с frozen/SHA256SUMS (= SHA256SUMS снимка) побайтно."""
        sums = SOC.read_sums()
        self.assertEqual(sorted(sums), ['words_on_sheet.py', 'words_rules.json'])
        for name, h in sums.items():
            self.assertEqual(sha(open(os.path.join(FROZEN, name), 'rb').read()), h, name)

    def test_image_file_list_is_snapshot(self):
        """Список файлов образа = ровно два файла снимка + requirements; ни лишнего, ни пропавшего."""
        got = SOC.read_list()
        self.assertEqual(sorted(os.path.basename(f) for f in got), ['requirements-ocr.txt', 'words_on_sheet.py', 'words_rules.json'])
        self.assertEqual(SOC.frozen_problems(REPO, got, SOC.read_sums()), [])

    @unittest.skipUnless(os.path.isdir(SNAPSHOT), 'снимок 20261126-2234 лежит только на DEV-VM')
    def test_equals_live_snapshot(self):
        """Где снимок есть (DEV-VM): файлы побайтно равны живому снимку и его SHA256SUMS."""
        sums = {ln.split()[1]: ln.split()[0] for ln in open(os.path.join(SNAPSHOT, 'SHA256SUMS'), encoding='utf-8') if len(ln.split()) == 2}
        for name in ('words_on_sheet.py', 'words_rules.json'):
            self.assertEqual(open(os.path.join(FROZEN, name), 'rb').read(), open(os.path.join(SNAPSHOT, name), 'rb').read(), name)
            self.assertEqual(sums[name], SOC.read_sums()[name], name)

    def test_dockerfile_pins(self):
        """Dockerfile: основа по digest, те же хеши снимка, версии rapidocr/onnxruntime; requirements — точные версии."""
        d = open(os.path.join(HERE, 'Dockerfile.ocr'), encoding='utf-8').read()
        self.assertRegex(d, r'ARG BASE=python@sha256:[0-9a-f]{64}')
        for h in SOC.read_sums().values():
            self.assertIn(h, d)
        req = open(os.path.join(HERE, 'requirements-ocr.txt'), encoding='utf-8').read().split()
        self.assertIn('rapidocr==3.10.0', req)
        self.assertIn('onnxruntime==1.31.1', req)
        self.assertTrue(all('==' in r for r in req), 'каждая строка requirements — точная версия')
        self.assertIn("'rapidocr':'3.10.0','onnxruntime':'1.31.1'", d.replace(' ', ''))

    def test_stage_copies_and_refuses_tampered(self):
        with tempfile.TemporaryDirectory() as t:
            SOC.stage(REPO, os.path.join(t, 'ctx'))
            self.assertEqual(sorted(os.listdir(os.path.join(t, 'ctx'))), ['Dockerfile.ocr', 'code', 'requirements-ocr.txt'])
            self.assertEqual(sorted(os.listdir(os.path.join(t, 'ctx', 'code'))), ['words_on_sheet.py', 'words_rules.json'])
            # −контроль: правленый файл → отказ, контекст не собирается
            fake = os.path.join(t, 'repo', SOC.REPO_DIR)
            os.makedirs(os.path.join(fake, 'frozen'))
            for src, dst in ((HERE, fake), (FROZEN, os.path.join(fake, 'frozen'))):
                for f in os.listdir(src):
                    if os.path.isfile(os.path.join(src, f)):
                        with open(os.path.join(src, f), 'rb') as fi, open(os.path.join(dst, f), 'wb') as fo:
                            fo.write(fi.read())
            open(os.path.join(fake, 'frozen', 'words_rules.json'), 'a').write(' ')
            with self.assertRaisesRegex(ValueError, 'не совпал со снимком'):
                SOC.stage(os.path.join(t, 'repo'), os.path.join(t, 'ctx2'))

    def test_helpers_match_frozen_module(self):
        """sheet_sha и rules_ver драйвера = функции замороженного words_on_sheet (ключ кэша тот же)."""
        sys.path.insert(0, FROZEN)
        try:
            import words_on_sheet as W
            with tempfile.TemporaryDirectory() as t:
                p = os.path.join(t, 'x.jpeg')
                open(p, 'wb').write(os.urandom(3 * 2 ** 20 + 17))
                self.assertEqual(RUN.sheet_sha(p), W.sheet_sha(p))
            self.assertEqual(RUN.rules_ver(), W.rules_ver())
        finally:
            sys.path.remove(FROZEN)
            sys.modules.pop('words_on_sheet', None)


# ---------------------------------------------------------------- 2. слияние
def _writer(args):
    target, k, n, lock = args
    ents = {sha(f'{k}-{i}'.encode()): {'words': bool(i % 2), 'found': [], 'conf': 0.5, 'n_lines': i, 'sheet': f'p{k}'} for i in range(n)}
    MW.merge(target, ents, 'R1', lock=lock, _between=lambda: time.sleep(0.02))


class TestMerge(unittest.TestCase):
    def ent(self, n=1, **kw):
        return {**{'words': True, 'found': ['кухня'], 'conf': 0.9, 'n_lines': n, 'sheet': 's'}, **kw}

    def test_add_keep_stale(self):
        with tempfile.TemporaryDirectory() as t:
            f = os.path.join(t, 'words_flags.json')
            self.assertEqual(MW.merge(f, {'a': self.ent(1), 'b': self.ent(2)}, 'R1')['added'], 2)
            r = MW.merge(f, {'a': self.ent(99), 'c': self.ent(3)}, 'R1')                      # a уже посчитан этими правилами — НЕ перезаписывается
            self.assertEqual((r['added'], r['kept'], r['total']), (1, 1, 3))
            d = json.load(open(f, encoding='utf-8'))
            self.assertEqual(d['a']['n_lines'], 1)
            self.assertEqual(d['a']['rules'], 'R1')
            f2 = os.path.join(t, 'old.json')
            json.dump({'a': {**self.ent(1), 'rules': 'OLD'}}, open(f2, 'w'))
            r = MW.merge(f2, {'a': self.ent(5)}, 'R1')                                          # другая версия правил = промах для читателя → заменяем
            self.assertEqual((r['added'], r['replaced_stale']), (0, 1))
            self.assertEqual(json.load(open(f2))['a']['n_lines'], 5)

    def test_no_temp_left_and_format_like_words_cached(self):
        with tempfile.TemporaryDirectory() as t:
            f = os.path.join(t, 'w.json')
            MW.merge(f, {'a': self.ent()}, 'R1')
            self.assertEqual(sorted(x for x in os.listdir(t) if not x.endswith('.lock')), ['w.json'])
            self.assertEqual(set(json.load(open(f))['a']), {'words', 'found', 'conf', 'n_lines', 'rules', 'sheet'})
            self.assertIn('кухня', open(f, encoding='utf-8').read())                           # ensure_ascii=False — как у words_on_sheet

    def test_broken_json_is_not_wiped(self):
        with tempfile.TemporaryDirectory() as t:
            f = os.path.join(t, 'w.json')
            open(f, 'w').write('{"a": ')
            with self.assertRaises(ValueError):
                MW.merge(f, {'b': self.ent()}, 'R1')
            self.assertEqual(open(f).read(), '{"a": ')                                         # файл не тронут

    def test_bad_entry_refused(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(ValueError, 'нет полей'):
                MW.merge(os.path.join(t, 'w.json'), {'a': {'words': True}}, 'R1')

    def test_parallel_merges_lose_nothing(self):
        """8 процессов × 25 строк одновременно (между чтением и записью пауза): с замком — все 200 на месте."""
        with tempfile.TemporaryDirectory() as t:
            f = os.path.join(t, 'w.json')
            with mp.Pool(8) as p:
                p.map(_writer, [(f, k, 25, True) for k in range(8)])
            self.assertEqual(len(json.load(open(f))), 200)

    def test_negative_control_without_lock_loses_rows(self):
        """−контроль: без замка тот же прогон ТЕРЯЕТ строки — значит тест выше способен поймать потерю."""
        with tempfile.TemporaryDirectory() as t:
            f = os.path.join(t, 'w.json')
            with mp.Pool(8) as p:
                p.map(_writer, [(f, k, 25, False) for k in range(8)])
            self.assertLess(len(json.load(open(f))), 200)

    def test_cli_refuses_other_rules(self):
        with tempfile.TemporaryDirectory() as t:
            r = os.path.join(t, 'r.json')
            json.dump({'rules': 'OTHER', 'results': {'a': self.ent()}}, open(r, 'w'))
            sys.argv = ['merge_words.py', '--target', os.path.join(t, 'w.json'), '--rules', 'R1', r]
            self.assertEqual(MW.main(), 2)
            self.assertFalse(os.path.exists(os.path.join(t, 'w.json')))


# ---------------------------------------------------------------- 3. драйвер (чистые функции)
class TestDriver(unittest.TestCase):
    def mk(self, root, sid, content, ext='jpeg'):
        d = os.path.join(root, sid)
        os.makedirs(d, exist_ok=True)
        open(os.path.join(d, f'plan.{ext}'), 'wb').write(content)

    def test_parts_cover_all_disjoint(self):
        items = list(range(23))
        parts = [RUN.take_part(items, f'{k}/6') for k in range(1, 7)]
        self.assertEqual(sorted(x for p in parts for x in p), items)
        self.assertEqual(sum(len(p) for p in parts), 23)
        with self.assertRaises(ValueError):
            RUN.take_part(items, '7/6')

    def test_chunks(self):
        self.assertEqual([len(c) for c in RUN.chunks(list(range(13)), 6)], [6, 6, 1])

    def test_plan_skips_cached_same_rules_only(self):
        with tempfile.TemporaryDirectory() as t:
            d1, d2 = os.path.join(t, 'a'), os.path.join(t, 'b')
            self.mk(d1, 's1', b'one')
            self.mk(d2, 's2', b'two', 'png')
            self.mk(d1, 's3', b'three')
            cache = {sha(b'one'): {'rules': 'R1'}, sha(b'three'): {'rules': 'OLD'}}
            p = RUN.plan_todo(['s1', 's2', 's3', 's4'], [d1, d2], cache, 'R1')
            self.assertEqual(p['cached'], ['s1'])
            self.assertEqual([x['id'] for x in p['todo']], ['s2', 's3'])                       # s3: кэш под другими правилами = промах
            self.assertEqual(p['no_file'], ['s4'])
            self.assertEqual(p['todo'][0]['ext'], 'png')

    def test_probe_pick_even_and_needs_enough(self):
        with tempfile.TemporaryDirectory() as t:
            cache = {}
            ids = []
            for i in range(30):
                sid = f'p{i:02d}'
                self.mk(t, sid, f'file{i}'.encode())
                cache[sha(f'file{i}'.encode())] = {'rules': 'R1', 'sheet': sid, 'words': bool(i % 2), 'found': [], 'conf': 0.0, 'n_lines': i}
                ids.append(sid)
            self.mk(t, 'changed', b'new bytes')                                                # лист есть, а в кэше — под другим sha: в пробу не годится
            cache['dead'] = {'rules': 'R1', 'sheet': 'changed'}
            pick, expect = RUN.probe_pick(cache, ids + ['changed'], [t], 'R1', 10)
            self.assertEqual(len(pick), 10)
            self.assertEqual(len({p['sha'] for p in pick}), 10)
            self.assertTrue({p['sha'] for p in pick} <= set(expect))
            self.assertIn(True, {e['words'] for e in expect.values()})
            self.assertIn(False, {e['words'] for e in expect.values()})
            with self.assertRaisesRegex(ValueError, 'нужно 40'):
                RUN.probe_pick(cache, ids, [t], 'R1', 40)

    def test_compare_exact_and_tolerance(self):
        e = {'k1': {'sheet': 'a', 'words': True, 'found': ['кухня'], 'conf': 0.900, 'n_lines': 7}}
        ok = {'k1': {'words': True, 'found': ['кухня'], 'conf': 0.905, 'n_lines': 7, 'ocr_s': 3}}
        self.assertTrue(RUN.compare(e, ok)[0]['ok'])
        for k, v in (('conf', 0.92), ('n_lines', 8), ('found', ['спальня']), ('words', False)):
            bad = {'k1': {**ok['k1'], k: v}}
            r = RUN.compare(e, bad)[0]
            self.assertFalse(r['ok'], k)                                                       # −контроль: любое расхождение краснит
            self.assertIn(k, r['why'])
        self.assertFalse(RUN.compare(e, {})[0]['ok'])
        self.assertIn('совпало 0 из 1', RUN.table_md(RUN.compare(e, {})))

    def test_body_low_only_and_no_secrets(self):
        body = RUN.build_body('ocr-words-x', 'ghcr.io/o/i@sha256:' + '0' * 64, 'low', 'cls', {'k': 'v'}, 3000, 600)
        self.assertEqual(body['priority'], 'low')
        self.assertEqual(body['replicas'], 1)
        self.assertNotIn('KIT_WORKER_Z', body['container']['environment_variables'])
        with self.assertRaises(KD.ProfileRefused):
            RUN.build_body('ocr-words-x', 'img@sha256:' + '0' * 64, 'medium', 'cls', {}, 3000, 600)

    def test_worker_reports_progress_and_bundles(self):
        self.assertEqual(KD.worker_progress_refusal(RUN.WORKER), '')
        cmd, z = RUN.worker_command()
        self.assertEqual(cmd[:2], ['python', '-u'])
        self.assertLess(len(cmd[-1]), 1000)
        self.assertGreater(len(z), 1000)


# ---------------------------------------------------------------- 4. воркер на настоящем HTTP
class FakeW:
    """Подставной words_on_sheet: слова по содержимому файла; «BOOM» — отказ листа."""
    @staticmethod
    def rules_ver():
        return 'R1'

    @staticmethod
    def words_on_sheet(path):
        with open(path, 'rb') as f:
            b = f.read()
        if b.startswith(b'BOOM'):
            raise RuntimeError('сломанный лист')
        return {'words': b'kitchen' in b, 'found': ['кухня'] if b'kitchen' in b else [], 'conf': 0.9, 'n_lines': len(b)}


class TestWorker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state = KW.State()
        cls.state.phase = 'ready'
        wd = KW.Watchdog(3600, 3600)
        cls.pool = WO.Pool(cls.state, {'code': '', 'work': cls.tmp.name, 'procs': 1}, FakeW)
        h = WO.make_handler(cls.state, cls.pool, wd, threading.Event(), {'rapidocr': 'x'})
        cls.srv = KW.make_server(0, h, host='127.0.0.1')
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def call(self, method, path, body=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        c.request(method, path, json.dumps(body).encode() if body is not None else None)
        r = c.getresponse()
        data = r.read()
        c.close()
        return r.status, data

    @staticmethod
    def sheet(sid, raw, ext='jpeg', sha_override=None):
        return {'id': sid, 'sha': sha_override or sha(raw), 'ext': ext, 'z': base64.b64encode(zlib.compress(raw)).decode()}

    def wait(self, jid):
        for _ in range(100):
            c, d = self.call('GET', f'/jobs/{jid}')
            v = json.loads(d)
            if v['status'] in ('done', 'failed'):
                return v
            time.sleep(0.05)
        self.fail('задание не закончилось')

    def test_job_roundtrip_and_idempotent(self):
        a, b = b'plan kitchen 1', b'plan empty 2'
        c, d = self.call('POST', '/jobs', {'job_id': 'j1', 'sheets': [self.sheet('A', a), self.sheet('B', b, 'png')]})
        self.assertEqual(c, 202, d)
        v = self.wait('j1')
        self.assertEqual(v['status'], 'done', v)
        c, d = self.call('GET', '/jobs/j1/result')
        self.assertEqual(c, 200)
        self.assertEqual(sha(d), v['sha256'])
        r = json.loads(d)
        self.assertEqual(r['rules'], 'R1')
        self.assertEqual(r['errors'], {})
        self.assertEqual(r['results'][sha(a)]['words'], True)
        self.assertEqual(r['results'][sha(a)]['sheet'], 'A')
        self.assertEqual(r['results'][sha(b)]['n_lines'], len(b))
        self.assertIn('ocr_s', r['results'][sha(a)])
        c, d = self.call('POST', '/jobs', {'job_id': 'j1', 'sheets': [self.sheet('A', a)]})       # повтор того же job_id — не дубль
        self.assertEqual((c, json.loads(d).get('repeat')), (202, True))
        self.assertEqual(self.pool.counts()['total'], len([1 for k in self.pool.jobs]))

    def test_sha_mismatch_and_bad_input_refused(self):
        c, d = self.call('POST', '/jobs', {'job_id': 'j2', 'sheets': [self.sheet('A', b'zzz', sha_override='0' * 64)]})
        self.assertEqual(c, 400)
        self.assertIn('sha256 не сошёлся', json.loads(d)['error'])
        self.assertEqual(self.call('POST', '/jobs', {'job_id': 'j3', 'sheets': [self.sheet('A', b'zzz', 'gif')]})[0], 400)
        self.assertEqual(self.call('POST', '/jobs', {'job_id': 'bad id', 'sheets': []})[0], 400)
        self.assertEqual(self.call('POST', '/jobs', {'job_id': 'j4', 'sheets': []})[0], 400)
        self.assertEqual(self.call('POST', '/jobs', {'job_id': 'j5', 'sheets': [self.sheet('A', b'x'), self.sheet('B', b'x')]})[0], 400)    # один файл дважды

    def test_failed_sheet_counts_with_reason(self):
        good, bad = b'kitchen ok', b'BOOM sheet'
        c, _ = self.call('POST', '/jobs', {'job_id': 'j6', 'sheets': [self.sheet('G', good), self.sheet('X', bad)]})
        self.assertEqual(c, 202)
        v = self.wait('j6')
        self.assertEqual(v['status'], 'failed')
        self.assertIn('сломанный лист', v['error'])
        r = json.loads(self.call('GET', '/jobs/j6/result')[1])
        self.assertIn(sha(good), r['results'])                                                  # готовый лист не теряем
        self.assertIn('X: RuntimeError', r['errors'][sha(bad)])

    def test_not_ready_node_refuses(self):
        self.state.phase = 'loading'
        try:
            self.assertEqual(self.call('POST', '/jobs', {'job_id': 'j7', 'sheets': [self.sheet('A', b'x')]})[0], 503)
        finally:
            self.state.phase = 'ready'

    def test_health_has_progress(self):
        c, d = self.call('GET', '/health')
        self.assertEqual(c, 200)
        self.assertEqual(json.loads(d)['version'], WO.VERSION)


if __name__ == '__main__':
    unittest.main(verbosity=1)

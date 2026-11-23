"""Тесты круга «на 5» (loop5.py, T-20261123-29/1): без сети и платного — разбор входов, команды нод, деление, страница. Запуск: python3 tools/assets/tests/test_loop5.py (нужен Pillow)."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import loop5 as L  # noqa: E402
sys.path.append(os.path.join(HERE, "..", "..", "scout"))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_loop5")

SK = ['112923_1', '112923_2', '112923_3', '112923_4', '112923_5']


def make_base(tmp, with_fill=True):
    root = os.path.join(tmp, 'base')
    for i, s in enumerate(SK):
        d = os.path.join(root, f'sh{i % 2}', s)
        for n in ('06-visible/visible.glb', '06-visible/check.json', '06-visible/known.png', '07-fill/filled.glb', '07-fill/frame-photo.png', '08-material/material.glb'):
            if n.startswith('07') and not with_fill:
                continue
            p = os.path.join(d, n)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            open(p, 'wb').write(b'x')
    shards = os.path.join(tmp, 'shards')
    os.makedirs(shards)
    json.dump({s: {'glb': f'/g/{s}.glb', 'photo': f'/p/{s}.png', 'pose_run': f'/pose/{s}', 'args': ['--card-json', '@in/card.json'], 'extra_in': {'card.json': '/c.json'}} for s in SK[:3]},
              open(os.path.join(shards, 'sh0.json'), 'w'))
    json.dump({s: {'glb': f'/g/{s}.glb', 'photo': f'/p/{s}.png', 'pose_run': f'/pose/{s}'} for s in SK[3:]}, open(os.path.join(shards, 'sh1.json'), 'w'))
    r = L.load_rules()
    r.update({'golden': SK, 'base_root': root, 'shard_inputs_glob': os.path.join(shards, 'sh*.json'), 'out_root': os.path.join(tmp, 'out')})
    return r, root


class T(unittest.TestCase):
    def test_rules_ok(self):
        r = L.load_rules()
        self.assertEqual(r['node']['variant'], 'big')                          # A/B 23.11: big в 4 раза быстрее на 07 (T-34)
        self.assertEqual(len(r['golden']), 5)
        self.assertLessEqual(r['machines'], 6)                                 # потолок директора: до 6 нод (общий потолок 10 на всех)
        self.assertTrue(all(k in r['stages'] for k in ('06', '07', '08')))
        self.assertIn('@sha256:', r['image'])                                  # образ — по дайджесту, не по тегу (ADR-0137)

    def test_split(self):
        self.assertEqual(L.split(SK, 2), [SK[0::2], SK[1::2]])
        self.assertEqual(L.split(SK[:1], 2), [SK[:1]])
        self.assertEqual(len(L.split(SK, 9)), 5)

    def test_resolve_sha(self):
        sha = L.resolve_sha('HEAD')
        self.assertEqual(len(sha), 40)
        with self.assertRaises(SystemExit):
            L.resolve_sha('no-such-ref-xyz')

    def test_base_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = make_base(tmp)
            b = L.base_dirs(r, SK)
            self.assertEqual(L.need_files('07', b), [])
            self.assertEqual(L.need_files('08', b), [])
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = make_base(tmp, with_fill=False)
            b = L.base_dirs(r, SK)
            self.assertEqual(L.need_files('07', b), [])
            self.assertEqual(len(L.need_files("08", b)), 5)                    # нет filled.glb — 08 не стартует
        with self.assertRaises(SystemExit):
            L.base_dirs({'base_root': '/nonexistent'}, SK)

    def test_inputs_vis_only_for_07(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = make_base(tmp)
            b = L.base_dirs(r, SK)
            i7 = L.shard_inputs(r, SK[:2], '07', b)
            self.assertTrue(i7[SK[0]]['vis'].endswith(f'{SK[0]}/06-visible'))
            i6 = L.shard_inputs(r, SK[:2], '06', b)
            self.assertNotIn('vis', i6[SK[0]])
            self.assertEqual(i6[SK[0]]['pose_run'], f'/pose/{SK[0]}')
            with self.assertRaises(SystemExit):
                L.shard_inputs(r, ['112923_nope'], '06', b)

    def test_keep_photo_copies_into_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = make_base(tmp)
            b = L.base_dirs(r, SK)
            src = os.path.join(tmp, 'src-photo.png')                    # «исходник во /tmp»
            with open(src, 'wb') as f:
                f.write(b'PNGDATA')
            for f in glob.glob(L.ex(r['shard_inputs_glob'])):           # подставляем реальный файл как фото товара
                d = json.load(open(f, encoding='utf-8'))
                for v in d.values():
                    v['photo'] = src
                json.dump(d, open(f, 'w', encoding='utf-8'))
            keep = os.path.join(tmp, 'run', 'photos')
            inp = L.shard_inputs(r, SK[:2], '06', b, keep)
            self.assertEqual(inp[SK[0]]['photo'], os.path.join(keep, SK[0] + '.png'))
            self.assertEqual(open(inp[SK[0]]['photo'], 'rb').read(), b'PNGDATA')
            os.remove(src)                                              # исходник пропал (как /tmp) — второй заход берёт копию
            inp2 = L.shard_inputs(r, SK[:2], '06', b, keep)
            self.assertEqual(inp2[SK[1]]['photo'], os.path.join(keep, SK[1] + '.png'))
            self.assertEqual(L.photos(r, keep)[SK[0]], os.path.join(keep, SK[0] + '.png'))
            with self.assertRaises(SystemExit):                          # ни исходника, ни копии
                L.shard_inputs(r, SK[2:3], '06', b, keep)

    def test_stage_cmd(self):
        r = L.load_rules()
        c = L.stage_cmd(r, 'a' * 40, '07', 1, SK[:2], '/run', '1300', None, '/run/in.json', True)
        j = ' '.join(c)
        self.assertIn('--stages 07,seam,08', j)
        self.assertIn('--inputs /run/in.json', j)
        self.assertIn(f'--code-ref {"a" * 40}', j)
        self.assertIn('--apply', c)
        self.assertIn('--prio 2', j)
        self.assertEqual(c[0].endswith('heavy-slot.sh'), True)
        self.assertNotIn('--apply', L.stage_cmd(r, 'a' * 40, '07', 0, SK[:2], '/run', '1300', None, '/run/in.json', False))
        c8 = L.stage_cmd(r, 'b' * 40, '08', 0, SK[:2], '/run', '1300', '/run/base', None, True)
        j8 = ' '.join(c8)
        self.assertIn('--stages 08', j8)
        self.assertIn('--fill-root /run/base --vis-root /run/base', j8)
        self.assertIn(f'--skus {SK[0]},{SK[1]}', j8)
        self.assertNotIn('--inputs', j8)
        self.assertIn('--stages 06,07,seam,08', ' '.join(L.stage_cmd(r, 'a' * 40, '06', 0, SK, '/run', '1300', None, '/run/in.json', True)))

    def test_compose(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            rows = []
            for s in SK[:2]:
                b, a = os.path.join(tmp, f'{s}-b.png'), os.path.join(tmp, f'{s}-a.png')
                Image.new('RGB', (700, 60), 'gray').save(b)
                Image.new('RGB', (700, 60), 'white').save(a)
                rows.append({'sku': s, 'status': 'пересчитан', 'before_png': b, 'after_png': a})
            rows.append({'sku': SK[2], 'status': 'ОТКАЗ', 'before_png': '/no', 'after_png': '/no2'})
            p = L.compose(L.load_rules(), tmp, 'c' * 40, '07', rows)
            self.assertTrue(os.path.isfile(p))
            doc = open(p, encoding='utf-8').read()
            self.assertIn(f'{SK[0]}.png', doc)
            self.assertIn('нет листа', doc)                                    # отказ виден на странице, не молча
            self.assertTrue(os.path.isfile(os.path.join(tmp, 'page', f'{SK[0]}.png')))

    def test_retry_names_and_collect(self):
        self.assertEqual(L.tag_of(1), 'sh1')
        self.assertEqual(L.tag_of(1, 2), 'sh1r2')
        r0 = {'image': 'x@sha256:0b7c855d4f98', 'warm': {'enabled': False}}
        self.assertEqual(L.suffix_of(r0, '1300', 0), 'l51300s0')
        self.assertEqual(L.suffix_of(r0, '1300', 0, 1), 'l51300s0r1')              # у повтора своя группа Salad (без тёплой ноды)
        rw = {'image': 'x@sha256:0b7c855d4f98', 'warm': {'enabled': True}}
        self.assertEqual(L.suffix_of(rw, '1300', 1, 0), 'w1-0b7c85')
        self.assertEqual(L.suffix_of(rw, '9999', 1, 2), 'w1-0b7c85')               # тёплая: имя постоянное — от прогона и повтора не зависит
        self.assertNotEqual(L.suffix_of({**rw, 'image': 'x@sha256:ffffff000000'}, '1300', 1), 'w1-0b7c85')   # другой образ — другая нода
        with tempfile.TemporaryDirectory() as tmp:
            for tag, sku, size in (('sh0', SK[0], 5), ('sh0', SK[1], 0), ('sh0r1', SK[1], 5)):   # пустой material.glb (диск был полон) — не результат
                p = os.path.join(tmp, 'out', tag, sku, '08-material', 'material.glb')
                os.makedirs(os.path.dirname(p))
                open(p, 'wb').write(b'x' * size)
            res, money = L.collect(tmp, SK[:3])
            self.assertEqual(sorted(res), sorted(SK[:2]))
            self.assertIn('sh0r1', res[SK[1]])
            self.assertTrue(money['stop_verified'])

    def test_queue_cmd_nodes_and_variant(self):
        r = L.load_rules()
        self.assertTrue(L.queue_on(r))
        self.assertEqual(L.node_count(r, 5), min(5, r['machines']))
        self.assertEqual(L.node_count(r, 2), 2)                                # нод не больше товаров
        r_off = {**r, 'queue': {**r['queue'], 'enabled': False}}
        self.assertEqual(L.node_count(r_off, 5), len(L.split(SK, r['machines'])))
        c = L.stage_cmd(r, 'a' * 40, '07', 2, SK, '/run', '1300', None, '/run/in.json', True, 0, queue='/run/queue-r0')
        j = ' '.join(c)
        self.assertIn('--queue /run/queue-r0', j)
        self.assertIn(f'--nodes {L.node_count(r, 5)}', j)
        self.assertIn('--out /run/out/q', j)                                   # общий out для всех нод очереди
        self.assertIn('--requeue-max', j)
        self.assertIn('--out /run/out/sh2', ' '.join(L.stage_cmd(r, 'a' * 40, '07', 2, SK, '/run', '1300', None, '/run/in.json', True)))   # без очереди — прежний out на ноду
        r = {**r, 'node': {'variant': '', 'procs': 0, 'fill_procs': 0, 'threads': 0}}                # база — нода low
        self.assertNotIn('--variant', ' '.join(L.stage_cmd(r, 'a' * 40, '07', 0, SK, '/run', '1300', None, '/run/in.json', True)))
        rb = {**r, 'node': {'variant': 'big', 'procs': 4, 'fill_procs': 3, 'threads': 2}}
        jb = ' '.join(L.stage_cmd(rb, 'a' * 40, '07', 0, SK, '/run', '1300', None, '/run/in.json', True))
        self.assertIn('--variant big', jb)
        self.assertIn('--fill-procs 3', jb)
        self.assertIn('--threads 2', jb)
        self.assertNotEqual(L.suffix_of(rb, '1300', 0), L.suffix_of(r, '1300', 0))     # другой размер — другое имя тёплой ноды

    def test_warm_cmd_and_rules(self):
        r = L.load_rules()
        self.assertTrue(r['warm']['enabled'])
        self.assertGreaterEqual(r['warm']['life_min'], r['warm']['min_left_min'] + r['warm']['idle_min'])   # жизни хватает хотя бы на простой и запас
        c = L.stage_cmd(r, 'a' * 40, '07', 1, SK[:2], '/run', '1300', None, '/run/in.json', True)
        j = ' '.join(c)
        self.assertIn(f'--suffix {L.suffix_of(r, "1300", 1)}', j)
        self.assertIn(f'--keep-warm {r["warm"]["idle_min"]}', j)
        self.assertIn('--warm-min-left-min', j)
        r2 = {**r, 'warm': {**r['warm'], 'enabled': False}}
        self.assertNotIn('--keep-warm', ' '.join(L.stage_cmd(r2, 'a' * 40, '07', 1, SK[:2], '/run', '1300', None, '/run/in.json', True)))

    def test_collect_kept_warm(self):
        with tempfile.TemporaryDirectory() as tmp:
            for tag, kept in (('sh0', True), ('sh1', False)):
                d = os.path.join(tmp, 'out', tag)
                os.makedirs(d)
                json.dump({'cost_usd_est': 0.004, 'running_s': 100, 'stop_verified': not kept, 'kept_warm': {'idle_min': 20} if kept else None, 'adopted_warm': kept}, open(os.path.join(d, 'summary-trial-stage-x.json'), 'w'))
            _, money = L.collect(tmp, SK)
            self.assertEqual((money['kept_warm'], money['adopted_warm'], money['stop_verified']), (1, 1, True))     # тёплая нода — не «остановка не подтверждена»

    def test_sheet_items_and_batch_cmd(self):
        items = L.sheet_items([('/g/a/material.glb', '/p/a.png', '/o/sheets/112923_1.png', '/v/a/check.json'), ('/g/b/material.glb', '/p/b.png', '/o/sheets/112923_2.png')])
        self.assertEqual(items[0], {'id': '112923_1', 'glb': '/g/a/material.glb', 'photo': '/p/a.png', 'check06': '/v/a/check.json'})
        self.assertNotIn('check06', items[1])                                    # нет камеры — поля нет (sides_sheet сам отметит «нет az»)
        r = L.load_rules()
        self.assertEqual(r['sheets']['mode'], 'batch')
        c = L.batch_cmd(r, '/o/items.json', '/o/sheets')
        j = ' '.join(c)
        self.assertTrue(c[0].endswith('heavy-slot.sh'))
        self.assertIn('sides_sheet.py batch --items /o/items.json --out /o/sheets', j)
        self.assertIn(f'--cores {r["heavy_slot"]["cores_sheets_batch"]}', j)

    def test_run_sheets_one_dir_and_skip_done(self):
        r = L.load_rules()
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(L.run_sheets(r, [], os.path.join(tmp, 'l.log')), 0)
            done = os.path.join(tmp, 'a', '1.png')
            os.makedirs(os.path.dirname(done))
            with open(done, 'wb') as f:
                f.write(b'x')
            self.assertEqual(L.run_sheets(r, [('/g', '/p', done)], os.path.join(tmp, 'l.log')), 0)      # готовый непустой — не пересчитывается
            with self.assertRaises(ValueError):
                L.run_sheets(r, [('/g', '/p', os.path.join(tmp, 'a', '2.png')), ('/g', '/p', os.path.join(tmp, 'b', '3.png'))], os.path.join(tmp, 'l.log'))

    def test_cli_dry_checks_before_money(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = make_base(tmp, with_fill=False)
            rp = os.path.join(tmp, 'rules.json')
            json.dump(r, open(rp, 'w'))
            with self.assertRaises(SystemExit) as e:
                L.main(['--code-ref', 'HEAD', '--from', '08', '--dry', '--rules', rp])
            self.assertIn('нет входов', str(e.exception))                      # до создания платной группы


    def test_sheet_photo_no_frame_photo_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            ph = os.path.join(tmp, 'a.png')
            open(ph, 'wb').write(b'x')
            L.check_sheet_photos({'112923_1': ph}, ['112923_1'])                           # есть настоящее фото — молчит
            with self.assertRaises(SystemExit) as e:
                L.check_sheet_photos({'112923_1': ph, '112923_2': ''}, ['112923_1', '112923_2'])
            self.assertIn('112923_2', str(e.exception))
            self.assertIn('frame-photo', str(e.exception))                              # причина названа
            with self.assertRaises(SystemExit):
                L.check_sheet_photos({'112923_1': os.path.join(tmp, 'нет.png')}, ['112923_1'])   # путь есть, файла нет
        src = open(os.path.join(HERE, '..', 'loop5.py'), encoding='utf-8').read()
        self.assertNotIn("'frame-photo.png')", src)                                     # запасного пути в коде нет

if __name__ == '__main__':
    unittest.main()

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
        self.assertEqual(L.suffix_of(rw, '1300', 1, 0), 'w1-0b7c85-1300')
        self.assertEqual(L.suffix_of(rw, '1300', 1, 2), 'w1-0b7c85-1300')          # тёплая: у своего прогона имя постоянное — от повтора не зависит
        # T-20261124-58 п.5: два прогона с одним образом — РАЗНЫЕ группы (раньше обе хватали одну, «занята другим прогоном»)
        self.assertNotEqual(L.suffix_of(rw, '1300', 1), L.suffix_of(rw, '9999', 1))
        self.assertEqual({L.suffix_of(rw, 'A', i) for i in range(4)} & {L.suffix_of(rw, 'B', i) for i in range(4)}, set())
        # явная передача: следующий прогон берёт ноды прогона 1300 по --warm-from
        self.assertEqual(L.suffix_of({**rw, 'warm': {'enabled': True, 'name_owner': '1300'}}, '9999', 1), 'w1-0b7c85-1300')
        self.assertNotEqual(L.suffix_of({**rw, 'image': 'x@sha256:ffffff000000'}, '1300', 1), 'w1-0b7c85-1300')   # другой образ — другая нода
        with tempfile.TemporaryDirectory() as tmp:
            for tag, sku, size in (('sh0', SK[0], 5), ('sh0', SK[1], 0), ('sh0r1', SK[1], 5)):   # пустой material.glb (диск был полон) — не результат
                p = os.path.join(tmp, 'out', tag, sku, '08-material', 'material.glb')
                os.makedirs(os.path.dirname(p))
                open(p, 'wb').write(b'x' * size)
            res, money = L.collect(tmp, SK[:3])
            self.assertEqual(sorted(res), sorted(SK[:2]))
            self.assertIn('sh0r1', res[SK[1]])
            self.assertTrue(money['stop_verified'])

    def test_product_types_and_by_type(self):
        r = L.load_rules()
        cat = [{'sid': '112923_1', 'role': 'кровать'}, {'sid': '112923_2', 'role': 'диван'}, {'sid': '112923_3', 'role': 'нет-такой-роли-в-реестре'}]
        t = L.product_types(r, ['112923_1', '112923_2', '112923_3', '112923_4'], catalog=cat)
        self.assertEqual(t['112923_1']['type'], 'кровать')                         # тип — из паспортов типов (rules/mesh-type-passports.json)
        self.assertTrue(t['112923_1']['family'])
        self.assertIsNone(t['112923_3']['type'])                                   # роль есть, паспорта нет — честно None
        self.assertEqual(t['112923_3']['role'], 'нет-такой-роли-в-реестре')
        self.assertEqual(t['112923_4'], {'role': None, 'type': None, 'family': None, 'provisional': None})   # товара нет в каталоге
        bt = L.by_type(t, {'112923_1': {'ok': True}, '112923_2': {'ok': False}})
        self.assertEqual(bt['кровать'], {'skus': ['112923_1'], 'n': 1, 'passed': 1, 'failed': []})
        self.assertEqual(bt['без паспорта']['n'], 2)
        self.assertEqual(L.by_type(t, None)['кровать']['passed'], 0)               # листов не оценивали — прошедших нет, отказов нет
        bu = L.by_type(t, {'112923_1': {'ok': None}, '112923_2': {'ok': True}})   # T-20261124-22: ok None = «не измерено» — не прошёл и не провалил
        self.assertEqual((bu['кровать']['passed'], bu['кровать']['failed'], bu['кровать']['unmeasured']), (0, [], ['112923_1']))
        # сбой каталога не роняет круг
        self.assertEqual(L.product_types({**r, 'catalog': '/нет/такого.json'}, ['x'])['x']['type'], None)

    def test_all_skus_from_shards(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i, ks in enumerate((['112923_9', '112923_1'], ['112923_5'])):
                json.dump({k: {} for k in ks}, open(os.path.join(tmp, f'sh{i}.json'), 'w'))
            r = {**L.load_rules(), 'shard_inputs_glob': os.path.join(tmp, 'sh*.json')}
            self.assertEqual(L.all_skus(r), ['112923_1', '112923_5', '112923_9'])      # все товары пакета, по порядку, без дублей

    def test_salad_ceiling_live_count(self):
        r = {**L.load_rules(), 'machines': 6, 'salad_ceiling': 10}
        run = lambda name, st, n=None: {'name': name, 'current_state': {'status': st, 'instance_status_counts': {'running_count': n or 0}}}   # noqa: E731
        live = lambda *rows: (lambda: list(rows))                                              # noqa: E731
        self.assertEqual(L.salad_live(live(run('a', 'stopped'), run('b', 'failed'), run('c', 'running', 1), run('d', 'deploying'), run('e', 'stopped', 2))), {'c': 1, 'd': 1, 'e': 2})
        # 4 чужих живых → из 6 запрошенных можно 6 (10−4)
        can, other, mine = L.cap_machines(r, 6, '1', live(*[run(f'x{i}', 'running', 1) for i in range(4)]))
        self.assertEqual((can, other, mine), (6, 4, []))
        # 7 чужих → 3
        self.assertEqual(L.cap_machines(r, 6, '1', live(*[run(f'x{i}', 'running', 1) for i in range(7)]))[0], 3)
        # свои тёплые (те же имена) В СЧЁТЕ (T-20261124-58: раньше вычитались как «не чужие», три прогона вышли за 10): 1 своя + 5 чужих = 6 живых → 4 ноды
        mine_name = L.GROUP_PREFIX + L.suffix_of(r, '1', 0)
        can, total, mine = L.cap_machines(r, 6, '1', live(run(mine_name, 'running', 1), *[run(f'x{i}', 'running', 1) for i in range(5)]))
        self.assertEqual((can, total, mine), (4, 6, [mine_name]))
        # 10 и больше чужих → 0 (отказ)
        self.assertEqual(L.cap_machines(r, 6, '1', live(*[run(f'x{i}', 'running', 2) for i in range(6)]))[0], 0)

    def test_retry_sizes_nodes_anew_through_the_gate(self):
        """T-20261125-58/4: повтор упавших считает ноды заново (живой счёт Salad + оставшиеся товары), а не берёт урезанное при старте machines; потолок смотрит до создания групп."""
        run = lambda name, st, n=None: {'name': name, 'current_state': {'status': st, 'instance_status_counts': {'running_count': n or 0}}}   # noqa: E731
        live = lambda *rows: (lambda: list(rows))                                              # noqa: E731
        others = lambda k: [run(f'x{i}', 'running', 1) for i in range(k)]                      # noqa: E731
        r = {**L.load_rules(), 'machines': 6, 'salad_ceiling': 10, 'warm': {'enabled': False}, 'queue': {'enabled': True}}
        said = []
        # заход 0: 8 чужих → из 6 нод можно 2 (rules.machines урезан до 2, но machines_cfg = 6 запомнен ДО урезания)
        self.assertEqual(L.cap_machines(r, 6, '1', live(*others(8)))[0], 2)
        r['machines'] = 2
        todo = [f'112923_{i}' for i in range(10)]
        # к повтору место освободилось (3 чужих): хотим min(10 товаров, 6) = 6, можно 10−3 = 7 → 6 нод, а не прежние 2
        ok = L.prepare_retry(r, 6, todo, '1', live(*others(3)), said.append)
        self.assertTrue(ok)
        self.assertEqual(r['machines'], 6)
        self.assertIn('нод 6 из 6', said[-1])
        # чужие снова заняли место: 8 живых → 2 ноды (повтор не выходит за потолок)
        r['machines'] = 6
        self.assertTrue(L.prepare_retry(r, 6, todo, '1', live(*others(8)), said.append))
        self.assertEqual(r['machines'], 2)
        # повторять осталось 1 товар → одна нода, лишних не поднимаем
        r['machines'] = 6
        self.assertTrue(L.prepare_retry(r, 6, todo[:1], '1', live(*others(3)), said.append))
        self.assertEqual(r['machines'], 1)
        # --machines 3 на запуске — это и потолок повтора (machines_cfg = 3)
        r['machines'] = 3
        self.assertTrue(L.prepare_retry(r, 3, todo, '1', live(*others(0)), said.append))
        self.assertEqual(r['machines'], 3)
        # потолок исчерпан: повтор НЕ стартует, rules не трогаем, причина в лог
        r['machines'] = 2
        n = len(said)
        self.assertFalse(L.prepare_retry(r, 6, todo, '1', live(*others(10)), said.append))
        self.assertEqual(r['machines'], 2)
        self.assertEqual(len(said), n + 1)
        self.assertIn('потолок 10', said[-1])
        self.assertIn('исчерпан', said[-1])
        # не-тёплый повтор: прежние группы заходa 0 (даже не погашенные) занимают место — их считает живой счёт
        prev = L.GROUP_PREFIX + L.suffix_of(r, '1', 0)
        self.assertFalse(L.prepare_retry(r, 6, todo, '1', live(run(prev, 'running', 1), *others(9)), said.append))
        # счёт Salad не прочитан → не стартуем, молчаливого запуска нет
        def boom():
            raise RuntimeError('нет сети')
        r['machines'] = 2
        self.assertFalse(L.prepare_retry(r, 6, todo, '1', boom, said.append))
        self.assertIn('не прочитан', said[-1])
        self.assertEqual(r['machines'], 2)
        # тёплые ноды: имя постоянное, повтор берёт свои же — их место возвращается (10 живых = 4 чужих + 6 своих тёплых → повтор на 6 нод можно)
        rw = {**r, 'machines': 6, 'warm': {'enabled': True}}
        mine = [run(L.GROUP_PREFIX + L.suffix_of(rw, '1', i), 'running', 1) for i in range(6)]
        self.assertTrue(L.prepare_retry(rw, 6, todo, '1', live(*mine, *others(4)), said.append))
        self.assertEqual(rw['machines'], 6)
        # …но сверх своих не растём: 2 свои тёплые + 8 чужих = 10 → повтор на 6 хочет, можно только 2 (свои)
        rw['machines'] = 6
        self.assertTrue(L.prepare_retry(rw, 6, todo, '1', live(*mine[:2], *others(8)), said.append))
        self.assertEqual(rw['machines'], 2)
        # ноды считаются от machines_cfg и в режиме без очереди (товары делятся заранее): 4 товара → 4 группы, а не 6
        rn = {**r, 'machines': 2, 'queue': {'enabled': False}}
        self.assertTrue(L.prepare_retry(rn, 6, todo[:4], '1', live(*others(0)), said.append))
        self.assertEqual(rn['machines'], 4)

    def test_cli_refuses_when_ceiling_exhausted_and_when_count_unreadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            r, _ = make_base(tmp, with_fill=True)
            rp = os.path.join(tmp, 'rules.json')
            json.dump({**r, 'salad_ceiling': 2}, open(rp, 'w'))
            orig, orig_sw = L._salad_items, L.sweep_warm
            swept = []
            L.sweep_warm = lambda: swept.append(1) or True                                   # настоящий sweep ходит в Salad — в тесте заглушка
            try:
                L._salad_items = lambda: [{'name': f'x{i}', 'current_state': {'status': 'running', 'instance_status_counts': {'running_count': 1}}} for i in range(3)]
                with self.assertRaises(SystemExit) as e:
                    L.main(['--code-ref', 'HEAD', '--from', '08', '--dry', '--rules', rp])
                self.assertIn('потолок 2', str(e.exception))
                self.assertIn('исчерпан', str(e.exception))

                def boom():
                    raise RuntimeError('нет сети')
                L._salad_items = boom
                with self.assertRaises(SystemExit) as e2:
                    L.main(['--code-ref', 'HEAD', '--from', '08', '--rules', rp])                  # боевой: счёт не прочитан — не стартуем
                self.assertIn('не смог прочитать живой счёт', str(e2.exception))
                self.assertEqual(len(swept), 1)                                           # боевой старт сперва гасит просроченные тёплые; разбор (--dry) — нет
            finally:
                L._salad_items, L.sweep_warm = orig, orig_sw

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
        self.assertIn('--variant low', ' '.join(L.stage_cmd(r, 'a' * 40, '07', 0, SK, '/run', '1300', None, '/run/in.json', True)))     # low — явно (T-20261124-09: у stage_trial без флага пакет идёт на big)
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
        self.assertIn('--warm-owner 1300', j)                                   # метка владельца ноды = run-id: чужой стоп/освобождение видит, чья нода
        r2 = {**r, 'warm': {**r['warm'], 'enabled': False}}
        self.assertNotIn('--keep-warm', ' '.join(L.stage_cmd(r2, 'a' * 40, '07', 1, SK[:2], '/run', '1300', None, '/run/in.json', True)))
        self.assertNotIn('--warm-owner', ' '.join(L.stage_cmd(r2, 'a' * 40, '07', 1, SK[:2], '/run', '1300', None, '/run/in.json', True)))

    def test_release_on_done(self):
        # T-34/16: по окончании Salad-части свои тёплые ноды гасятся (простой ≈8 мин у круга 2), если не просили оставить и не выключено правилом
        r = L.load_rules()
        self.assertTrue(L.release_on_done(r))
        self.assertFalse(L.release_on_done(r, keep=True))                         # --keep-warm-nodes: следующий прогон подхватит
        self.assertFalse(L.release_on_done({**r, 'warm': {**r['warm'], 'release_on_done': False}}))
        self.assertFalse(L.release_on_done({**r, 'warm': {**r['warm'], 'enabled': False}}))   # без тёплых нод гасить нечего (группы гасятся по-старому)

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
        self.assertIn('sides_sheet.py batch --clay --items /o/items.json --out /o/sheets', j)
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

    def test_eval_after_runs_by_itself_and_table_worst_first(self):
        import numpy as np
        from PIL import Image
        sys.path.insert(0, HERE)
        import sides_eval as SE
        SR = SE.load_sheet_rules()
        S, HP = int(SR['size']), int(SR['header_px'])
        yy, xx = np.mgrid[0:S, 0:S]
        m = (np.abs(xx - S / 2) < 95) & (np.abs(yy - S / 2) < 105)

        def sheet(bad_back):
            cells = []
            for i in range(7):
                c = np.full((S, S, 3), 245 if i == 0 else 255, np.uint8)
                col = np.empty((S, S, 3))
                col[:] = (170, 140, 100)
                if bad_back and i == 4:                                  # «зад» — половина другого тона (заплатка)
                    col[:, S // 2:, :] += (-60, 25, 40)
                c[m] = np.clip(col, 0, 255).astype(np.uint8)[m]
                cells.append(c)
            out = np.full((S + HP, S * 7, 3), 255, np.uint8)
            out[HP:] = np.concatenate(cells, axis=1)
            return out
        with tempfile.TemporaryDirectory() as tmp:
            sh = os.path.join(tmp, 'sheets')
            os.makedirs(sh)
            Image.fromarray(sheet(False)).save(os.path.join(sh, 'a_good.png'))
            Image.fromarray(sheet(True)).save(os.path.join(sh, 'b_bad.png'))
            jobs = [('/g/a.glb', '/p/a.png', os.path.join(sh, 'a_good.png'), '', 12.0), ('/g/b.glb', '/p/b.png', os.path.join(sh, 'b_bad.png'), '', 190.0),
                    ('/g/c.glb', '/p/c.png', os.path.join(sh, 'c_missing.png'), '')]
            fronts = {'a_good': {'theta': 12.0, 'source': 'camera04', 'flags': []}, 'b_bad': {'theta': 190.0, 'source': 'camera04_flipped', 'flags': ['front_camera_opposite']}}
            rl = L.load_rules()
            rl['eval'] = {'inproc': True}
            ev, page = L.eval_after(rl, tmp, jobs, fronts)
            self.assertEqual(ev['summary']['items'], 2)                                    # лист-призрак (нет файла) в оценку не идёт
            self.assertEqual(ev['summary']['passed_all'], 1)
            self.assertEqual(ev['summary']['worst_first'][0], 'b_bad')
            self.assertTrue(any(f['view'] == 'зад' and f['feature'] == 'patches' for f in ev['per_sku']['b_bad']['fails']))
            self.assertLess(page.index('b_bad'), page.index('a_good'))                     # worst-first в таблице
            self.assertIn('(50.0 %)', page)
            self.assertIn('camera04_flipped', page)                                        # источник «перёда» виден
            self.assertTrue(os.path.isfile(os.path.join(tmp, 'eval', 'eval.json')))
            self.assertEqual(L.eval_after(rl, tmp, [('/g', '/p', os.path.join(tmp, 'нет.png'), '')], {})[0], None)   # нет листов — не падает

    def test_front_resolved_and_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = L.front_of(L.load_rules(), os.path.join(tmp, 'нет.glb'), os.path.join(tmp, 'нет.json'), '', '')
            self.assertIsNone(r['theta'])                                                  # нет входов: не падает, лист по камере 04
            self.assertIn('front_unknown:no_inputs', r['flags'])
        it = L.sheet_items([('/g/a.glb', '/p/a.png', '/o/s/x.png', '/v/check.json', 190.0), ('/g/b.glb', '/p/b.png', '/o/s/y.png', '/v/check.json')])
        self.assertEqual(it[0]['az'], 190.0)
        self.assertNotIn('az', it[1])
        r = L.load_rules()
        self.assertIn('--clay', L.batch_cmd(r, '/o/i.json', '/o/s'))
        r['sheets']['clay'] = False
        self.assertNotIn('--clay', L.batch_cmd(r, '/o/i.json', '/o/s'))


    def test_eval_parallel_and_cache_same_result(self):
        import numpy as np
        from PIL import Image
        sys.path.insert(0, HERE)
        import sides_eval as SE
        SR = SE.load_sheet_rules()
        S, HP = int(SR['size']), int(SR['header_px'])
        yy, xx = np.mgrid[0:S, 0:S]
        m = (np.abs(xx - S / 2) < 95) & (np.abs(yy - S / 2) < 105)
        rng = np.random.default_rng(3)

        def sheet(k):
            cells = []
            for i in range(7):
                c = np.full((S, S, 3), 245 if i == 0 else 255, np.uint8)
                col = np.empty((S, S, 3))
                col[:] = (170 - 9 * k, 140, 100 + 7 * k)
                col = col + rng.normal(0, 2 + k, col.shape)
                if k % 2 and i == 4:
                    col[:, S // 2:, :] += (-60, 25, 40)
                c[m] = np.clip(col, 0, 255).astype(np.uint8)[m]
                cells.append(c)
            out = np.full((S + HP, S * 7, 3), 255, np.uint8)
            out[HP:] = np.concatenate(cells, axis=1)
            return out
        with tempfile.TemporaryDirectory() as tmp:
            sh = os.path.join(tmp, 'sheets')
            os.makedirs(sh)
            for k in range(5):
                Image.fromarray(sheet(k)).save(os.path.join(sh, f'p{k}.png'))
            a = SE.batch(sh, os.path.join(tmp, 'a'))
            cache = os.path.join(tmp, 'cache')
            b = SE.batch(sh, os.path.join(tmp, 'b'), workers=3, cache_dir=cache)            # пул процессов + кэш пишется
            self.assertEqual(len(os.listdir(cache)), 5)
            c = SE.batch(sh, os.path.join(tmp, 'c'), workers=3, cache_dir=cache)            # всё из кэша
            for x in 'abc':
                self.assertTrue(os.path.isfile(os.path.join(tmp, x, 'eval.json')))
            ref = open(os.path.join(tmp, 'a', 'eval.json'), 'rb').read()
            self.assertEqual(ref, open(os.path.join(tmp, 'b', 'eval.json'), 'rb').read())   # пул даёт тот же файл байт в байт
            self.assertEqual(ref, open(os.path.join(tmp, 'c', 'eval.json'), 'rb').read())   # кэш — тот же файл байт в байт
            self.assertEqual(a['summary'], c['summary'])
            Image.fromarray(sheet(9)).save(os.path.join(sh, 'p0.png'))                       # лист изменился — ключ другой, пересчёт
            d = SE.batch(sh, os.path.join(tmp, 'd'), workers=2, cache_dir=cache)
            self.assertEqual(len(os.listdir(cache)), 6)
            self.assertNotEqual(a['eval']['p0'], d['eval']['p0'])

    def test_photo_upscale_cap_and_front_cache(self):
        sys.path.insert(0, HERE)
        import numpy as np
        import sides_eval as SE
        rgb = np.full((420, 420, 3), 240, np.uint8)
        mk = np.zeros((420, 420), bool)
        mk[100:110, 100:121] = True                                                         # тонкая вещь: маска фото 210 px
        big, _ = SE.rescale_to_area(rgb, mk, 55000.0)
        self.assertGreater(big.shape[0], 3000)                                              # без потолка — раздувание, как раньше
        capped, _ = SE.rescale_to_area(rgb, mk, 55000.0, 4.0)
        self.assertEqual(capped.shape[:2], (1680, 1680))                                    # потолок 4× линейно
        memo = {}
        x1 = SE.rescale_to_area(rgb, mk, 5000.0, None, memo)
        x2 = SE.rescale_to_area(rgb, mk, 5000.0, None, memo)
        self.assertIs(x1[0], x2[0])                                                         # тот же размер — один resize
        with tempfile.TemporaryDirectory() as tmp:
            r = L.load_rules()
            r['eval'] = {'front_cache': os.path.join(tmp, 'fc')}
            L.front_of(r, os.path.join(tmp, 'нет.glb'), os.path.join(tmp, 'нет.json'), '', '')
            self.assertFalse(os.path.isdir(os.path.join(tmp, 'fc')) and os.listdir(os.path.join(tmp, 'fc')))   # сбой чтения не кэшируется


    def test_thin_photo_is_uncertain_not_fail(self):
        import numpy as np
        from PIL import Image
        sys.path.insert(0, HERE)
        import sides_eval as SE
        SR = SE.load_sheet_rules()
        S, HP = int(SR['size']), int(SR['header_px'])
        yy, xx = np.mgrid[0:S, 0:S]
        m = (np.abs(xx - S / 2) < 95) & (np.abs(yy - S / 2) < 105)
        thin = (np.abs(xx - S / 2) < 40) & (np.abs(yy - S / 2) < 2)                       # фото: тонкая полоска — после съедания края почти ничего

        def sheet(photo_mask):
            cells = []
            for i in range(7):
                c = np.full((S, S, 3), 245 if i == 0 else 255, np.uint8)
                c[(photo_mask if i == 0 else m)] = (170, 140, 100)
                cells.append(c)
            out = np.full((S + HP, S * 7, 3), 255, np.uint8)
            out[HP:] = np.concatenate(cells, axis=1)
            return out
        with tempfile.TemporaryDirectory() as tmp:
            sh = os.path.join(tmp, 'sheets')
            os.makedirs(sh)
            Image.fromarray(sheet(m)).save(os.path.join(sh, 'good.png'))
            Image.fromarray(sheet(thin)).save(os.path.join(sh, 'thin.png'))
            r = SE.batch(sh, os.path.join(tmp, 'o'))
            s = r['summary']
            self.assertEqual(r['eval']['thin']['uncertain'][:10], 'маска фото')
            self.assertIsNone(r['eval']['thin']['ok'])                                      # не провал и не проход
            self.assertEqual((s['items'], s['measured'], s['passed_all'], s['passed_all_pct'], s['uncertain']), (2, 1, 1, 50.0, ['thin']))   # T-20261124-22: «не измерено» в знаменателе (раньше 100 % — прятало)
            self.assertEqual((s['failed'], s['with_unmeasured'], s['unmeasured_ids']), (0, 1, ['thin']))                          # три числа: прошли всё 1 · не измерено 1 · не прошли 0
            self.assertEqual(s['worst_first'], ['good', 'thin'])
            page = L.eval_html(L.run_eval({**L.load_rules(), 'eval': {'inproc': True}}, sh, os.path.join(tmp, 'o2'), [{'id': 'good'}, {'id': 'thin'}]))
            self.assertIn('не измерено', page)
            self.assertIn('1 из 2 (50.0 %)', page)                                                  # T-20261124-22: знаменатель — все товары
            self.assertIn('есть «не измерено» — 1 · не прошли — 0', page)                            # три числа в заголовке страницы


    def test_type_policy_from_passport_into_eval(self):
        import copy
        import numpy as np
        from PIL import Image
        sys.path.insert(0, HERE)
        sys.path.insert(0, os.path.join(HERE, '..', '..', 'scout'))
        import mesh_type_passports as MTP
        import sides_eval as SE
        reg = copy.deepcopy(MTP.load())
        reg['types']['комод']['paint'] = {**reg['types']['комод'].get('paint', {}), 'hidden_pattern': 'body'}
        self.assertEqual(MTP.paint_policy('комод', reg)['hidden_pattern'], 'body')
        types = {'112923_1': {'role': 'комод', 'type': 'комод'}, '112923_2': {'role': None, 'type': None}, '112923_3': {'role': 'стул', 'type': 'стул'}}
        orig = MTP.load
        MTP.load = lambda *a, **k: reg
        try:
            pol = L.type_policies(L.load_rules(), list(types), types)
        finally:
            MTP.load = orig
        self.assertEqual(pol['112923_1']['hidden_pattern'], 'body')                          # политика из паспорта (paint_policy р.6)
        self.assertEqual(pol['112923_1']['passport_digest'], MTP.digest_of(reg['types']['комод']))
        self.assertEqual(pol['112923_2'], {'hidden_pattern': 'unknown', 'passport_digest': None, 'policy_reason': 'no_type', 'type_hidden_pattern': 'unknown', 'role': None})   # нет типа — «не оценено», не «обычная мебель»
        self.assertIn(pol['112923_3']['hidden_pattern'], ('continue', 'body', 'same_fabric', 'plain', 'not_applicable'))            # у всех типов политика явная (А1)
        self.assertIsNotNone(pol['112923_3']['passport_digest'])
        reg2 = copy.deepcopy(reg)
        reg2['types']['стул']['paint'] = {**reg2['types']['стул'].get('paint', {}), 'hidden_pattern': 'plain', 'mode': 'observe'}
        MTP.load = lambda *a, **k: reg2
        try:
            pol2 = L.type_policies(L.load_rules(), ['112923_3'], types)
        finally:
            MTP.load = orig
        self.assertEqual((pol2['112923_3']['hidden_pattern'], pol2['112923_3']['policy_reason']), ('unknown', 'mode_observe'))   # observe → «не оценено», не ok
        SR = SE.load_sheet_rules()
        S, HP = int(SR['size']), int(SR['header_px'])
        yy, xx = np.mgrid[0:S, 0:S]
        m = (np.abs(xx - S / 2) < 95) & (np.abs(yy - S / 2) < 105)
        stripes = np.where((xx % 6) == 0, 140, 190)

        def sheet(back_flat):
            cells = []
            for i in range(7):
                c = np.full((S, S, 3), 245 if i == 0 else 255, np.uint8)
                pat = (i == 0) or (i in (1, 2)) or (i != 4 or not back_flat)
                c[m] = np.stack([stripes if pat else np.full((S, S), 190)] * 3, axis=-1).astype(np.uint8)[m]
                cells.append(c)
            out = np.full((S + HP, S * 7, 3), 255, np.uint8)
            out[HP:] = np.concatenate(cells, axis=1)
            return out
        with tempfile.TemporaryDirectory() as tmp:
            sh = os.path.join(tmp, 'sheets')
            os.makedirs(sh)
            Image.fromarray(sheet(True)).save(os.path.join(sh, '112923_1.png'))             # комод: узор на фасаде, ровный зад — НЕ брак при body
            rl = L.load_rules()
            rl['eval'] = {'inproc': True}
            jobs = [('/g/a.glb', '/p/a.png', os.path.join(sh, '112923_1.png'), '', 12.0)]
            MTP.load = lambda *a, **k: reg
            try:
                ev, page = L.eval_after(rl, tmp, jobs, {}, {'112923_1': types['112923_1']})
            finally:
                MTP.load = orig
            v = ev['per_sku']['112923_1']
            self.assertEqual(v['hidden_pattern'], 'body')
            self.assertEqual(v['passport_digest'], MTP.digest_of(reg['types']['комод']))
            self.assertTrue(v['views']['зад']['pattern']['ok'] is not False)                 # ровный зад при узорном фото — для body не брак
            with open(os.path.join(tmp, 'eval', 'eval.json'), encoding='utf-8') as f:
                self.assertEqual(json.load(f)['112923_1']['passport_digest'], v['passport_digest'])   # digest в eval.json


    def test_stop_timeout_does_not_crash_run(self):
        """Стоп/освобождение/sweep, повисшие дольше потолка (failed-группа w3b, р.2 23.11), → False и ❗ в журнал, а не TimeoutExpired: итоговая страница круга строится."""
        orig = L.subprocess.run
        seen = {}

        def hang(cmd, **kw):
            seen['timeout'] = kw.get('timeout')
            raise subprocess.TimeoutExpired(cmd, kw.get('timeout'))
        L.subprocess.run = hang
        try:
            r = {'run_prefix': 'x', 'stop_timeout_s': 45}
            self.assertFalse(L.stop_group(r, 'rid', 3, 0))
            self.assertEqual(seen['timeout'], 45)                                   # потолок — из правил, не 300 с
            self.assertFalse(L.release_warm('rid', 20))
            self.assertEqual(seen['timeout'], 20)
            self.assertFalse(L.sweep_warm(15))
            self.assertEqual(seen['timeout'], 15)

            def nostart(cmd, **kw):
                raise OSError('нет интерпретатора')
            L.subprocess.run = nostart
            self.assertFalse(L.stop_group(r, 'rid', 0, 0))                          # не запустилось — тоже не падаем
        finally:
            L.subprocess.run = orig

    def test_stop_timeout_default_and_floor(self):
        self.assertEqual(L.stop_timeout({}), 120)
        self.assertEqual(L.stop_timeout({'stop_timeout_s': 1}), 10)                 # нижний предел: не 0 с
        self.assertEqual(L.stop_timeout({'stop_timeout_s': 'x'}), 120)
        self.assertEqual(L.stop_timeout({'release_timeout_s': 200}, 'release_timeout_s', 300), 200)


if __name__ == '__main__':
    unittest.main()

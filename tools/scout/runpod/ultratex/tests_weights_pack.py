#!/usr/bin/env python3
"""Тесты weights_pack.py БЕЗ сети и видеокарты: свой HTTP-сервер с Range и переадресацией (как HF → CDN), тензоры разных типов.
  python tools/scout/runpod/ultratex/tests_weights_pack.py        (нужны torch и safetensors; нет — раздел пропускается)"""
from __future__ import annotations
import os as _rt_os  # noqa: E402
import sys as _rt_sys  # noqa: E402
_rt_sys.path.append(_rt_os.path.join(_rt_os.path.dirname(_rt_os.path.abspath(__file__)), '../..'))
import remlab_tmp  # noqa: E402,I001  — временное теста на диске и с уборкой при выходе (T-20261107-13)
remlab_tmp.use('tests_weights_pack')

import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
FAILS = []


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


try:
    import torch
    from safetensors.torch import save_file
except ImportError:
    print('torch/safetensors не установлены — тесты пропущены')
    sys.exit(0)

import weights_pack as WP                                       # noqa: E402

SEEN = []                                                       # (путь, есть ли Authorization)
DATA = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        SEEN.append((self.path, 'Authorization' in self.headers))
        if self.path.startswith('/resolve/'):
            if self.headers.get('Authorization') != 'Bearer SECRET-TOKEN':
                self.send_response(401)
                self.end_headers()
                return
            self.send_response(302)
            self.send_header('Location', f'http://localhost:{self.server.server_port}/cdn/{self.path.split("/")[-1]}')
            self.end_headers()
            return
        blob = DATA[self.path.split('/')[-1]]
        rng = self.headers.get('Range', '')
        a, b = (int(x) for x in rng.split('=')[1].split('-')) if rng else (0, len(blob) - 1)
        self.send_response(206)
        self.send_header('Content-Length', str(b - a + 1))
        self.end_headers()
        self.wfile.write(blob[a:b + 1])


srv = ThreadingHTTPServer(('127.0.0.1', 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f'http://127.0.0.1:{srv.server_port}/resolve/m.safetensors'

with tempfile.TemporaryDirectory() as td:
    g = torch.Generator().manual_seed(1)
    sd = {'a.w': torch.randn(300, 100, generator=g).to(torch.bfloat16), 'b.w': torch.randn(50, 70, generator=g), 'c.big': torch.randn(500, 200, generator=g).to(torch.bfloat16),
          'd.i': torch.arange(1000, dtype=torch.int64), 'e.s': torch.randn(7, generator=g).to(torch.float16), 'f.w': torch.randn(200, 100, generator=g).to(torch.bfloat16)}
    src_file = os.path.join(td, 'm.safetensors')
    save_file(sd, src_file)
    DATA['m.safetensors'] = open(src_file, 'rb').read()
    os.environ['T_TOK'] = 'SECRET-TOKEN'
    src = WP.HttpRange(URL, 'SECRET-TOKEN')
    header, ds = WP.read_header(src)
    ok(set(header) == set(sd), 'заголовок исходника читается Range-запросом')
    ok(any(p.startswith('/resolve/') and a for p, a in SEEN) and all(not a for p, a in SEEN if p.startswith('/cdn/')), 'токен ушёл только на первый хост; на CDN после переадресации — без токена')

    groups = WP.plan_groups(header, 100_000)                     # 100 КБ: c.big (200 КБ) — свой кусок
    sizes = [sum(header[n]['data_offsets'][1] - header[n]['data_offsets'][0] for n in gr) for gr in groups]
    ok(len(groups) >= 3 and sorted(n for gr in groups for n in gr) == sorted(sd), f'разбиение: {len(groups)} групп, каждый тензор ровно в одной')
    ok(all(s <= 100_000 or len(gr) == 1 for s, gr in zip(sizes, groups)), 'куски ≤ потолка (тензор больше потолка — один в куске)')
    ok(groups == WP.plan_groups(header, 100_000), 'разбиение детерминировано')
    out = os.path.join(td, 'shards')
    for k in range(len(groups)):
        row = WP.shard_step(src, out, k, 100_000)
        ok(row['tensors'] == len(groups[k]) and row['bytes'] > 0, f'кусок {k}: собран ({row["tensors"]} тензоров, {row["bytes"]} Б)')
    info = WP.verify_dir(out)
    ok(info['shards'] == len(groups) and info['tensors'] == len(sd), f'verify: {info}')
    ok(WP.is_sharded_dir(out) and not WP.is_sharded_dir(src_file), 'каталог кусков распознаётся, обычный файл — нет')
    got = WP.load_sharded(out)
    ok(set(got) == set(sd) and all(got[k].dtype == sd[k].dtype and torch.equal(got[k], sd[k]) for k in sd), 'load_sharded: все тензоры побитно равны исходным (bf16/fp32/fp16/int64)')
    alltxt = b''.join(open(os.path.join(out, f), 'rb').read() for f in os.listdir(out))
    ok(b'SECRET-TOKEN' not in alltxt, 'токена нет ни в кусках, ни в манифесте')

    # порча
    victim = os.path.join(out, 'shard-00.safetensors')
    raw = bytearray(open(victim, 'rb').read())
    raw[-1] ^= 1
    open(victim, 'wb').write(bytes(raw))
    try:
        WP.verify_dir(out)
        ok(False, 'порча байта должна ловиться')
    except ValueError as e:
        ok('sha256' in str(e), 'порча одного байта куска → verify падает (sha256)')
    raw[-1] ^= 1
    open(victim, 'wb').write(bytes(raw))
    ok(WP.verify_dir(out)['tensors'] == len(sd), 'починили байт — verify снова зелёный')
    # недостающий кусок
    man = json.load(open(os.path.join(out, 'manifest.json')))
    del man['shards'][str(len(groups) - 1)]
    json.dump(man, open(os.path.join(td, 'bad-manifest.json'), 'w'))
    bad = os.path.join(td, 'bad')
    os.makedirs(bad)
    for f in os.listdir(out):
        open(os.path.join(bad, f), 'wb').write(open(os.path.join(out, f), 'rb').read())
    json.dump(man, open(os.path.join(bad, 'manifest.json'), 'w'))
    try:
        WP.verify_dir(bad)
        ok(False, 'недостающий кусок должен ловиться')
    except ValueError as e:
        ok('ждали' in str(e), 'нет одного куска в манифесте → verify падает')
    # путь командной строки, как в Dockerfile: --token-file, --k, --expect-shards
    tf = os.path.join(td, 'tok')
    open(tf, 'w').write('SECRET-TOKEN\n')
    cli = os.path.join(td, 'cli')
    for k in range(len(groups)):
        rc = WP.main(['shard', '--url', URL, '--token-file', tf, '--out', cli, '--k', str(k), '--max-gb', str(100_000 / 2 ** 30)])
        ok(rc == 0, f'CLI shard --k {k} (токен из файла)')
    ok(WP.main(['verify', '--out', cli, '--expect-shards', str(len(groups))]) == 0, 'CLI verify --expect-shards верное число — ок')
    try:
        WP.main(['verify', '--out', cli, '--expect-shards', str(len(groups) + 1)])
        ok(False, 'неверное число кусков должно падать')
    except SystemExit as e:
        ok('ждали' in str(e), 'CLI verify: число кусков ≠ ожидаемому → сборка падает')
    try:
        WP.main(['plan', '--url', URL, '--token-file', tf, '--max-gb', str(100_000 / 2 ** 30), '--expect-shards', '99'])
        ok(False, 'plan с неверным ожиданием должен падать')
    except SystemExit as e:
        ok('Dockerfile' in str(e), 'CLI plan: число кусков ≠ RUN-шагам Dockerfile → ранний отказ до долгой сборки')
    # без токена
    try:
        WP.read_header(WP.HttpRange(URL, ''))
        ok(False, 'без токена должно падать')
    except Exception as e:                                       # noqa: BLE001
        ok('401' in str(e), 'без токена HF → 401 (не молчаливый пустой файл)')
    # индекс вне диапазона
    try:
        WP.shard_step(src, os.path.join(td, 'x'), 99, 100_000)
        ok(False, 'индекс вне диапазона должен падать')
    except IndexError:
        ok(True, 'индекс куска вне диапазона → IndexError')
    # не safetensors
    DATA['junk.safetensors'] = b'\xff' * 64
    try:
        WP.read_header(WP.HttpRange(URL.replace('m.safetensors', 'junk.safetensors'), 'SECRET-TOKEN'))
        ok(False, 'не safetensors должно падать')
    except ValueError:
        ok(True, 'не safetensors → ValueError')

srv.shutdown()
print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПРОВАЛОВ: {len(FAILS)}')
sys.exit(1 if FAILS else 0)

#!/usr/bin/env python3
"""ЛОКАЛЬНЫЙ МОСТ для аддона StableGen (T-20261119-90/5): аддон ходит на сервер ComfyUI только по `http://` и `ws://` (`stablegen/workflows.py`: `f"http://{server_address}/…"`,
`ws://…/ws`), а шлюз Salad отдаёт только HTTPS с ключом `Salad-Api-Key`. Мост слушает 127.0.0.1:<порт>, пересылает HTTP и WebSocket на `--target` (https://… или http://…)
и подставляет ключ из переменной окружения `--key-env` (в аргументы и журнал ключ не попадает). Аддон при этом не правится.

    PYTHONPATH=<deps с aiohttp> python3 sg_relay.py --listen 8190 --target https://<dns группы> --key-env SALAD_API_KEY
"""
import argparse
import asyncio
import os
import sys

import aiohttp
from aiohttp import WSMsgType, web

HOP = {'host', 'connection', 'keep-alive', 'transfer-encoding', 'upgrade', 'content-length', 'content-encoding', 'sec-websocket-key', 'sec-websocket-version',
       'sec-websocket-extensions', 'sec-websocket-protocol'}


def clean_headers(h, key: str | None) -> dict:
    out = {k: v for k, v in h.items() if k.lower() not in HOP and k.lower() not in ('salad-api-key', 'user-agent')}
    out['User-Agent'] = 'remlab-mesh/1.0'          # прокси RunPod (Cloudflare) режет чужой User-Agent (python-requests/aiohttp) ответом 403
    if key:
        out['Salad-Api-Key'] = key
    return out


def make_app(target: str, key: str | None) -> web.Application:
    target = target.rstrip('/')
    ws_target = ('wss://' + target[8:]) if target.startswith('https://') else ('ws://' + target[7:])

    async def h_ws(req):
        ws_c = web.WebSocketResponse(max_msg_size=0)
        await ws_c.prepare(req)
        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(f'{ws_target}/ws?{req.query_string}', headers=clean_headers({}, key), max_msg_size=0, heartbeat=30) as ws_s:
                async def up():
                    async for m in ws_c:
                        if m.type == WSMsgType.TEXT:
                            await ws_s.send_str(m.data)
                        elif m.type == WSMsgType.BINARY:
                            await ws_s.send_bytes(m.data)
                        else:
                            break

                async def down():
                    async for m in ws_s:
                        if m.type == WSMsgType.TEXT:
                            await ws_c.send_str(m.data)
                        elif m.type == WSMsgType.BINARY:
                            await ws_c.send_bytes(m.data)
                        else:
                            break

                _, pending = await asyncio.wait([asyncio.ensure_future(up()), asyncio.ensure_future(down())], return_when=asyncio.FIRST_COMPLETED)
                for p in pending:
                    p.cancel()
        return ws_c

    async def h_proxy(req):
        body = await req.read()
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.request(req.method, target + req.path_qs, data=body or None, headers=clean_headers(req.headers, key),
                                        timeout=aiohttp.ClientTimeout(total=1800)) as r:
                    data = await r.read()
                    return web.Response(body=data, status=r.status, headers={k: v for k, v in r.headers.items() if k.lower() not in HOP})
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:          # сеть до шлюза пропала: аддон увидит 502 и сам решит, повторять ли
            return web.json_response({'error': f'мост: {type(e).__name__}: {e}'}, status=502)

    app = web.Application(client_max_size=512 * 2 ** 20)
    app.add_routes([web.get('/ws', h_ws), web.route('*', '/{tail:.*}', h_proxy)])
    return app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--listen', type=int, default=8190)
    ap.add_argument('--target', required=True)
    ap.add_argument('--key-env', default=None, help='имя переменной окружения с ключом Salad; без неё заголовок не ставится (локальная проверка)')
    a = ap.parse_args()
    key = os.environ.get(a.key_env) if a.key_env else None
    if a.key_env and not key:
        print(f'нет переменной {a.key_env}', file=sys.stderr)
        return 2
    web.run_app(make_app(a.target, key), host='127.0.0.1', port=a.listen, print=lambda *_: print(f'мост 127.0.0.1:{a.listen} → {a.target}', flush=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())

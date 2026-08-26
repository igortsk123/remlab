#!/usr/bin/env python3
"""СЕРВИС ЧЕРНОВОГО РЕНДЕРА — то, что нельзя отдать браузеру (26.08).

Ключ fal живёт только на сервере, поэтому страница присылает СВОЮ расстановку, а сервис считает
сцену, собирает коллаж с фотографиями товаров и делает один вызов модели.

  POST /draft  {"room":{...},"items":[{role,x,y,rot,w,d,h,img}]}  → {"url": "...", "sec": 15.2}
  POST /warm   {}                                                 → {"sec": 12.4}
  GET  /health                                                    → ok

Запуск: DRAFT_PORT=8099 ~/venvs/scout/bin/python draft_service.py
"""
import hashlib
import html
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

import draft_render as DR  # noqa: E402

MAX_BODY = 2 << 20
# Каталог подборок монтируется из `/opt/remlab/test/share` — Caddy уже отдаёт его как /test/share/*
SHARE_DIR = os.environ.get('SHARE_DIR', os.path.join(HERE, 'share'))
PUBLIC_BASE = os.environ.get('PUBLIC_BASE', 'https://remont-lab.online')
TG_BOT = os.environ.get('SHARE_TG_BOT', '')        # имя бота без @; пусто — канал не подключён
MAX_BOT = os.environ.get('SHARE_MAX_BOT', '')
esc = html.escape
SHARE_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{{TITLE}} — подборка</title>
<style>
:root{color-scheme:light}
body{margin:0;background:#fff;color:#1A1F1C;font:17px/1.5 system-ui,-apple-system,Segoe UI,Roboto}
.wrap{max-width:1100px;margin:0 auto;padding:18px 16px 48px}
h1{font-size:clamp(24px,4.4vw,32px);margin:6px 0 4px}
.sub{color:#5C655E;font-size:16px;margin-bottom:16px}
.grid{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(300px,1fr))}
figure{margin:0}
img{width:100%;border-radius:12px;display:block;background:#F2F0EB}
figcaption{font-size:14px;color:#5C655E;margin-top:6px}
.foot{margin-top:28px;font-size:14px;color:#8A8F89}
</style></head><body><div class="wrap">
<h1>{{TITLE}}</h1>
<div class="sub">Ваша подборка · фотографий: {{COUNT}}. Ссылку можно сохранить или переслать себе.</div>
<div class="grid">{{CARDS}}</div>
<div class="foot">Сделано в планировщике remont-lab.online. Фотографии сгенерированы по вашей
расстановке; товары — из каталогов магазинов-партнёров.</div>
</div></body></html>"""
_LOCK = threading.Semaphore(2)          # два одновременных рендера: больше не нужно, ключ общий
_LAST_WARM = [0.0]
# ПРЕДОХРАНИТЕЛЬ РАСХОДА (26.08): эндпоинт публичный, а каждый рендер — деньги на fal. Больше
# HOURLY_CAP рендеров в час сервис не делает и честно об этом отвечает.
HOURLY_CAP = int(os.environ.get('DRAFT_HOURLY_CAP', 60))
_HITS: list = []


class H(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def _send(self, code: int, obj: dict) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Headers', 'content-type')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):                                    # noqa: N802
        self._send(204, {})

    @property
    def route(self) -> str:
        # Caddy отдаёт полный путь (`/api/draft`), локально зовут `/draft` — принимаем оба
        p = self.path.split('?')[0]
        return p[4:] if p.startswith('/api/') else p

    def do_GET(self):                                        # noqa: N802
        if self.route.startswith(('/health', 'draft/health')) or self.route in ('/draft/health',):
            return self._send(200, {'ok': True})
        self._send(404, {'error': 'нет такого пути'})

    def do_POST(self):                                       # noqa: N802
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            return self._send(413, {'error': 'слишком большой запрос'})
        raw = self.rfile.read(n) if n else b'{}'
        try:
            payload = json.loads(raw or b'{}')
        except Exception:
            return self._send(400, {'error': 'не JSON'})
        if self.route.startswith('/warm'):
            # ПРОГРЕВ ЗОВЁТСЯ, КОГДА ЧЕЛОВЕК НАЧАЛ ДВИГАТЬ МЕБЕЛЬ (владелец 26.08): у модели
            # холодный старт, и без прогрева первый рендер ждал бы минуту. Чаще раза в 4 минуты
            # греть незачем — платим за вызовы.
            if time.time() - _LAST_WARM[0] < 240:
                return self._send(200, {'sec': 0, 'skipped': 'уже прогрето'})
            _LAST_WARM[0] = time.time()
            threading.Thread(target=DR.warm, daemon=True).start()
            return self._send(200, {'sec': 0, 'started': True})
        if self.route.startswith('/share'):
            return self._share(payload)
        if not self.route.startswith(('/draft', '/render')):
            return self._send(404, {'error': 'нет такого пути'})
        if not (payload.get('room') and payload.get('items')):
            return self._send(400, {'error': 'нужны room и items'})
        now = time.time()
        _HITS[:] = [t for t in _HITS if now - t < 3600]
        if len(_HITS) >= HOURLY_CAP:
            return self._send(429, {'error': 'на сегодня лимит черновых рендеров исчерпан'})
        _HITS.append(now)
        if not _LOCK.acquire(blocking=False):
            return self._send(429, {'error': 'сейчас считается другой рендер, попробуйте через минуту'})
        try:
            t = time.time()
            quality = 'realistic' if payload.get('quality') == 'realistic' else 'draft'
            res = DR.render(layout=payload, quality=quality,
                            save_prefix=os.path.join(DR.OUT, 'draft-web'))
            self._send(200, {'shots': res['shots'], 'url': res['url'], 'model': res['model'],
                             'quality': quality, 'sec': round(time.time() - t, 1),
                             'diag': res['diag']})
        except Exception as e:                       # noqa: BLE001 — наружу отдаём короткую причину
            self._send(502, {'error': f'рендер не удался: {str(e)[:200]}'})
        finally:
            _LOCK.release()

    def _share(self, payload: dict) -> None:
        """ПОДБОРКА ФОТОГРАФИЙ (26.08, владелец: «можно отправить себе»). Сохраняем страницу с
        выбранными кадрами и отдаём короткую ссылку — её можно открыть на телефоне или переслать.
        Мессенджеры подключаются токеном бота: бот не может написать первым, поэтому это deep-link
        со `start=<id>` (тот же приём, что у лид-бота, ADR-0028)."""
        shots = [s for s in (payload.get('shots') or []) if isinstance(s, dict) and s.get('url')][:24]
        if not shots:
            return self._send(400, {'error': 'нечего отправлять — список кадров пуст'})
        sid = hashlib.sha1((json.dumps(shots, ensure_ascii=False, sort_keys=True)
                            + str(time.time())).encode()).hexdigest()[:10]
        d = os.path.join(SHARE_DIR, sid)
        try:
            os.makedirs(d, exist_ok=True)
            cards = '\n'.join(
                f'<figure><img src="{esc(s["url"])}" alt="{esc(s.get("label") or "")}" loading="lazy">'
                f'<figcaption>{esc(s.get("label") or "")}</figcaption></figure>' for s in shots)
            open(os.path.join(d, 'index.html'), 'w', encoding='utf-8').write(
                SHARE_PAGE.replace('{{TITLE}}', esc(payload.get('title') or 'Ваша комната'))
                          .replace('{{CARDS}}', cards)
                          .replace('{{COUNT}}', str(len(shots))))
        except Exception as e:                       # noqa: BLE001
            return self._send(500, {'error': f'не удалось сохранить подборку: {str(e)[:120]}'})
        url = f'{PUBLIC_BASE}/test/share/{sid}/'
        tg = f'https://t.me/{TG_BOT}?start=share_{sid}' if TG_BOT else None
        mx = f'https://max.ru/{MAX_BOT}?start=share_{sid}' if MAX_BOT else None
        self._send(200, {'id': sid, 'url': url, 'telegram': tg, 'max': mx, 'count': len(shots)})

    def log_message(self, fmt, *a):                  # noqa: A003 — тише в логе
        sys.stderr.write('%s %s\n' % (self.address_string(), fmt % a))


if __name__ == '__main__':
    port = int(os.environ.get('DRAFT_PORT', 8099))
    print(f'черновой рендер слушает :{port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', port), H).serve_forever()

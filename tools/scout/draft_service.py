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
SMS_GATE = os.environ.get('SHARE_SMS_GATE', '')   # шлюз СМС; пусто — канал не подключён
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
.grid{display:grid;gap:26px;grid-template-columns:1fr}
@media(min-width:900px){.grid{grid-template-columns:1fr 1fr}}
.sum{display:flex;justify-content:space-between;font-weight:700;margin:10px 0 6px;font-size:16px}
.ps-grid{display:grid;gap:10px;grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}
.p{border:1px solid #E4E6E2;border-radius:10px;padding:8px;text-decoration:none;color:inherit;
 display:block;background:#fff}
.p:hover{border-color:#3B76A2}
.p img,.p .noimg{width:100%;aspect-ratio:4/3;object-fit:contain;background:#F7F5F1;border-radius:7px}
.p .noimg{display:flex;align-items:center;justify-content:center;color:#A6ABA4;font-size:12px}
.p .pn{font-size:13.5px;line-height:1.3;margin-top:6px;max-height:36px;overflow:hidden}
.p .pp{font-size:15px;font-weight:700;margin-top:3px}
.p .ps{font-size:12px;color:#5C655E}
figure{margin:0}
img{width:100%;border-radius:12px;display:block;background:#F2F0EB}
figcaption{font-size:14px;color:#5C655E;margin-top:6px}
.foot{margin-top:28px;font-size:14px;color:#8A8F89}
</style></head><body><div class="wrap">
<h1>{{TITLE}}</h1>
<div class="sub">Ваша коллекция · фотографий: {{COUNT}}. Под каждым кадром — товары с ценами и
ссылками в магазин.</div>
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
            if os.environ.get('SCENE3D', '1') != '1':
                threading.Thread(target=DR.warm, daemon=True).start()
            return self._send(200, {'sec': 0, 'started': True})
        if self.route.startswith('/share'):
            return self._share(payload)
        if not self.route.startswith(('/draft', '/render')):
            return self._send(404, {'error': 'нет такого пути'})
        if not (payload.get('room') and payload.get('items')):
            return self._send(400, {'error': 'нужны room и items'})
        # ВРЕМЕННЫЙ КОСТЫЛЬ ДЛЯ ДЕМО (владелец 31.08): полный кадр рендерит DEV-машина
        # через ssh-туннель; конфиг кладётся файлом в share (env контейнера не пересоздать).
        # DEV молчит/упала → фолбэк на локальный (декимированный) рендер, кнопка живёт
        prx = os.environ.get('RENDER_PROXY') or ''
        if not prx:
            try:
                cf = os.path.join(os.path.dirname(DR.FRAMES_DIR), 'render-proxy.conf')
                prx = open(cf, encoding='utf-8').read().strip() if os.path.exists(cf) else ''
            except Exception:  # noqa: BLE001
                prx = ''
        if prx and not payload.get('no_proxy'):
            try:
                import urllib.request as _u
                req = _u.Request(prx, data=raw, method='POST',
                                 headers={'Content-Type': 'application/json'})
                # РЕЖИМ РЕМОНТА ЖДЁТ ДОЛЬШЕ (01.09): сборка листа плюс генерация в 2048 —
                # это минуты. Прежние 120 с роняли запрос в ФОЛБЭК на локальный рендер
                # прода, то есть человек получал кадр СТАРОГО пути и не знал об этом.
                _to = 600 if payload.get('quality') == 'realistic' else 120
                with _u.urlopen(req, timeout=_to) as r:
                    out = json.loads(r.read())
                for nm, b64 in (out.pop('frames', None) or {}).items():
                    # кадры пришли в теле — кладём в раздаваемую папку, ссылки уже прод-URL
                    import base64 as _b64
                    if '/' in nm or '..' in nm:
                        continue
                    os.makedirs(DR.FRAMES_DIR, exist_ok=True)
                    open(os.path.join(DR.FRAMES_DIR, nm), 'wb').write(_b64.b64decode(b64))
                out['backend'] = 'dev'
                return self._send(200, out)
            except Exception as e:  # noqa: BLE001
                print(f'DEV-бэкенд молчит ({str(e)[:80]}) — рендерю локально', flush=True)
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
            if os.environ.get('FRAME_INLINE') == '1':
                # DEV-бэкенд: кадры уезжают в теле ответа (2 scp-рукопожатия стоили ~5с)
                import base64 as _b64
                fr = {}
                for sh in res.get('shots') or []:
                    nm = (sh.get('url') or '').rsplit('/', 1)[-1]
                    fp = os.path.join(DR.FRAMES_DIR, nm)
                    if nm and os.path.exists(fp):
                        fr[nm] = _b64.b64encode(open(fp, 'rb').read()).decode()
                if fr:
                    res['frames'] = fr
            self._send(200, {'shots': res['shots'], 'url': res['url'], 'model': res['model'],
                             'sources': res.get('sources'), 'timing': res.get('timing'),
                             'quality': quality, 'sec': round(time.time() - t, 1),
                             'frames': res.get('frames'), 'diag': res['diag']})
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
            # КОЛЛЕКЦИЯ = ФОТО + ТОВАРЫ СО ССЫЛКАМИ (владелец 26.08: «человек должен получать
            # коллекции»): под каждым кадром — что на нём стоит, почём и где купить.
            def prod(p):
                pic = (f'<img src="{esc(p.get("img") or "")}" alt="" loading="lazy">'
                       if p.get('img') else '<div class="noimg">фото нет</div>')
                price = f'{int(p.get("price") or 0):,}'.replace(',', ' ') + ' \u20bd'
                inner = (pic + f'<div class="pn">{esc(p.get("name") or "")}</div>'
                         f'<div class="pp">{price}</div>'
                         f'<div class="ps">{esc(p.get("role") or "")}'
                         + (f' \u00b7 {esc(p.get("shop"))}' if p.get('shop') else '') + '</div>')
                return (f'<a class="p" href="{esc(p["url"])}" target="_blank" rel="noopener">{inner}</a>'
                        if p.get('url') else f'<div class="p">{inner}</div>')

            def block(sh):
                items = [p for p in (sh.get('items') or []) if isinstance(p, dict) and p.get('name')]
                total = sum(int(p.get('price') or 0) for p in items)
                head = (f'<div class="sum"><span>Товары на фото \u00b7 {len(items)}</span>'
                        f'<span>{f"{total:,}".replace(",", " ")} \u20bd</span></div>' if items else '')
                grid = ('<div class="ps-grid">' + ''.join(prod(p) for p in items) + '</div>') if items else ''
                return (f'<figure><img src="{esc(sh["url"])}" alt="{esc(sh.get("label") or "")}" '
                        f'loading="lazy"><figcaption>{esc(sh.get("label") or "")}</figcaption>'
                        f'{head}{grid}</figure>')
            cards = '\n'.join(block(sh) for sh in shots)
            open(os.path.join(d, 'index.html'), 'w', encoding='utf-8').write(
                SHARE_PAGE.replace('{{TITLE}}', esc(payload.get('title') or 'Ваша комната'))
                          .replace('{{CARDS}}', cards)
                          .replace('{{COUNT}}', str(len(shots))))
        except Exception as e:                       # noqa: BLE001
            return self._send(500, {'error': f'не удалось сохранить подборку: {str(e)[:120]}'})
        url = f'{PUBLIC_BASE}/test/share/{sid}/'
        # КОНТАКТ ВМЕСТО ССЫЛКИ (владелец 26.08): ссылку на подборку наружу не отдаём — человек
        # оставляет Telegram, MAX или телефон, и доставка идёт туда. Пока каналы не подключены
        # (нет токенов ботов и SMS-шлюза), запрос честно помечается как ожидающий отправки.
        chan = str(payload.get('channel') or '').lower()
        contact = str(payload.get('contact') or '').strip()[:120]
        ready = {'telegram': bool(TG_BOT), 'max': bool(MAX_BOT), 'sms': bool(SMS_GATE)}.get(chan, False)
        if contact:
            try:
                os.makedirs(os.path.join(SHARE_DIR, '_queue'), exist_ok=True)
                open(os.path.join(SHARE_DIR, '_queue', f'{sid}.json'), 'w', encoding='utf-8').write(
                    json.dumps({'id': sid, 'url': url, 'channel': chan, 'contact': contact,
                                'count': len(shots), 'ts': int(time.time()),
                                'delivered': False}, ensure_ascii=False))
            except Exception:
                pass
        self._send(200, {'id': sid, 'count': len(shots), 'channel': chan,
                         'pending': not ready})

    def log_message(self, fmt, *a):                  # noqa: A003 — тише в логе
        sys.stderr.write('%s %s\n' % (self.address_string(), fmt % a))


if __name__ == '__main__':
    port = int(os.environ.get('DRAFT_PORT', 8099))
    print(f'черновой рендер слушает :{port}', flush=True)
    ThreadingHTTPServer((os.environ.get('DRAFT_HOST', '0.0.0.0'), port), H).serve_forever()

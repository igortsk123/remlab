#!/usr/bin/env python3
"""Сторож урока 724: воркер Salad обязан слушать `::` (IPv6; шлюз и пробы Salad ходят по IPv6). Без сети и GPU. Запуск: python3 tools/scout/salad/tests_dualstack.py [--check]

1. общий `dualstack.py` реально отвечает по ::1 и 127.0.0.1;
2. КАЖДЫЙ воркер (`tools/scout/**/worker*.py`, `*_worker.py`), который поднимает HTTP-сервер, — либо несёт дословную копию блока `# dualstack:begin…end` и вызывает `make_server(`,
   либо слушает `::` своим сокетом (как `worker_sg.py`), либо записан в `dualstack-allow.txt` с причиной; иначе тест падает — новый воркер на 0.0.0.0 не пройдёт;
3. сам сторож проверен на примерах (плохой воркер ловится, хороший пропускается)."""
import os
import re
import socket
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import dualstack as DS  # noqa: E402

FAILS = []
BEGIN, END = '# dualstack:begin', '# dualstack:end'
SERVES = re.compile(r'ThreadingHTTPServer\(|[^A-Za-z]HTTPServer\(|uvicorn\.run\(|make_server\(')


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


def block(text: str):
    """Текст между метками (включая метки) или None."""
    a, b = text.find(BEGIN), text.find(END)
    if a < 0 or b < a:
        return None
    return text[a:b + len(END)]


def problems(text: str, canonical: str) -> list[str]:
    """Что не так в воркере. Пусто — годится или HTTP не поднимает."""
    if not SERVES.search(text):
        return []
    own = block(text)
    if own is not None:
        out = []
        if own.strip() != canonical.strip():
            out.append('блок dualstack отличается от dualstack.py (скопировать дословно)')
        rest = text.replace(own, '')
        if not re.search(r'make_server\(', rest):
            out.append('блок есть, но сервер поднимается не через make_server(')
        if re.search(r"HTTPServer\(\s*\(\s*['\"](0\.0\.0\.0)?['\"]", rest):
            out.append('сервер вне блока привязан к 0.0.0.0')
        return out
    if 'AF_INET6' in text and re.search(r"bind\(\s*\(\s*['\"]::['\"]", text):
        return []                                               # свой сокет на `::` (worker_sg.py)
    return ['слушает только 0.0.0.0 (или не через `::`): шлюз и пробы Salad ходят по IPv6 — нужен блок dualstack (урок 724)']


def workers() -> list[str]:
    out = []
    for dp, dn, fn in os.walk(SCOUT):
        dn[:] = [d for d in dn if d not in ('node_modules', '__pycache__', '.git')]
        for f in fn:
            if f.endswith('.py') and (f.startswith('worker') or f.endswith('_worker.py')) and not f.startswith(('test', 'tests')):
                out.append(os.path.join(dp, f))
    return sorted(out)


def allowed() -> dict:
    p = os.path.join(HERE, 'dualstack-allow.txt')
    res = {}
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#'):
                path, _, why = line.partition('#')
                res[path.strip()] = why.strip()
    return res


canonical = block(open(os.path.join(HERE, 'dualstack.py'), encoding='utf-8').read())
ok(canonical is not None, 'в dualstack.py есть блок между метками')

# 1. общий модуль отвечает по обоим стекам
class _Ping(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):                                          # noqa: N802
        self.send_response(200)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'ok')


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status
    except Exception:                                          # noqa: BLE001
        return None


if socket.has_ipv6:
    try:
        srv = DS.make_server(0, _Ping)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        ok(_get(f'http://[::1]:{port}/') == 200, 'общий сервер отвечает по IPv6 (::1)')
        ok(_get(f'http://127.0.0.1:{port}/') == 200, 'и по IPv4 (127.0.0.1)')
        srv.shutdown()
        srv.server_close()
    except OSError as exc:
        ok(True, f'IPv6 на этой машине недоступен ({exc}) — прогон по сокету пропущен')
else:
    ok(True, 'IPv6 в Python нет — прогон по сокету пропущен')

# 3. сам сторож
BAD = "from http.server import ThreadingHTTPServer\nsrv = ThreadingHTTPServer(('0.0.0.0', PORT), H)\n"
GOOD = 'import socket\n' + canonical + '\nsrv = make_server(PORT, H)\n'
GOOD_OWN = "sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)\nsock.bind(('::', PORT))\nuvicorn.run(app, fd=sock.fileno())\n"
ok(problems(BAD, canonical), 'сторож: сервер на 0.0.0.0 — ловится')
ok(not problems(GOOD, canonical), 'сторож: блок dualstack + make_server — проходит')
ok(not problems(GOOD_OWN, canonical), 'сторож: свой сокет на `::` — проходит')
ok(problems(GOOD.replace('IPV6_V6ONLY, 0', 'IPV6_V6ONLY, 1'), canonical), 'сторож: искажённая копия блока — ловится')
ok(problems(GOOD + "\nother = ThreadingHTTPServer(('0.0.0.0', 9), H)\n", canonical), 'сторож: второй сервер на 0.0.0.0 рядом с блоком — ловится')
ok(not problems('print(1)\n', canonical), 'сторож: файл без HTTP — не трогаем')

# 2. все воркеры репозитория
allow = allowed()
seen = 0
for path in workers():
    rel = os.path.relpath(path, os.path.join(SCOUT, '..', '..')).replace(os.sep, '/')
    text = open(path, encoding='utf-8').read()
    if not SERVES.search(text):
        continue
    seen += 1
    if rel in allow:
        ok(True, f'{rel}: в списке исключений — {allow[rel] or "причина не указана"}')
        continue
    pr = problems(text, canonical)
    ok(not pr, f'{rel}: слушает `::`' if not pr else f'{rel}: {"; ".join(pr)}')
ok(seen > 0, f'найдено воркеров с HTTP-сервером: {seen}')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПРОВАЛОВ: {len(FAILS)}')
sys.exit(1 if FAILS else 0)

#!/usr/bin/env python3
"""Раздача файлов приёмника (`GET /files`, `GET /ls`) — безопасность и поведение (T-20261117-24/2). БЕЗ сети и Salad: сервер на 127.0.0.1.

Закрепляет:
  1) без токена — 401 на обе ручки; с неверным — 401;
  2) отдаётся ТОЛЬКО префикс из списка (`renderjobs`); меши и любой другой префикс — 404, и по /files, и по /ls;
  3) `..`, `%2e%2e`, `%2E%2E`, абсолютный путь, обратная косая, NUL, скрытые имена (`.staging`), `.part` — 404, наружу ничего не уходит;
  4) симлинк (на файл и на каталог) наружу — 404 и не виден в /ls;
  5) /ls — только имена/размер/время, глубже задания нельзя; чужого префикса нет;
  6) файл отдаётся целиком и потоком (размер и содержимое сходятся; из .staging и из постоянного каталога);
  7) потолок PUT: пакет renderjobs > SERVE_MAX_MB → 413, обычный меш > MAX_FILE_MB → 413, меш в пределах — 200.

Запуск: ~/venvs/scout/bin/python tests_sink_serve.py   (CI: python tools/scout/salad/tests_sink_serve.py)
"""
import json
import os
import sys
import tempfile
import threading
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_sink_serve')

ROOT = tempfile.mkdtemp(prefix='sink-serve-')
os.environ['MESH_ROOT'] = ROOT
os.environ['MESH_SINK_TOKEN'] = 'tok-test'
os.environ['MESH_SERVE_PREFIXES'] = 'renderjobs'
os.environ['MESH_SERVE_MAX_MB'] = '2'
os.environ['MESH_MAX_FILE_MB'] = '1'
os.environ['MESH_MIN_FREE_GB'] = '0'
import receiver as R  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

FAILS: list = []


def check(cond: bool, what: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + what)
    if not cond:
        FAILS.append(what)


def w(rel: str, data: bytes = b'x') -> str:
    p = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, 'wb').write(data)
    return p


srv = ThreadingHTTPServer(('127.0.0.1', 0), R.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def call(method: str, path: str, token='tok-test', data=None):
    """path — как есть в строке запроса (без перекодирования). → (код, тело bytes)."""
    import http.client
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
    h = {'Authorization': f'Bearer {token}'} if token else {}
    if data is not None:
        h['Content-Length'] = str(len(data))
    c.request(method, path, body=data, headers=h)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def main() -> int:
    big = os.urandom(3 * 2 ** 20 // 2)          # 1.5 МБ — «пакет»
    w('renderjobs/job1/bundle.tgz', big)
    w('renderjobs/job1/.staging/job.json', b'{"a":1}')
    w('renderjobs/job1/.staging/half.part', b'zz')
    w('renderjobs/job2/result.json', b'{"ok":true}')
    w('meshes-secret/abc/model.glb', b'SECRET-MESH')
    w('lv-set10/x/manifest.json', b'SECRET2')
    outside = tempfile.mkdtemp(prefix='sink-out-')
    open(os.path.join(outside, 'passwd'), 'w').write('SECRET-OUT')
    os.symlink(os.path.join(outside, 'passwd'), os.path.join(ROOT, 'renderjobs/job1/link.txt'))
    os.symlink(outside, os.path.join(ROOT, 'renderjobs/linkdir'))
    os.symlink(outside, os.path.join(ROOT, 'renderjobs/job2/.staging')) if not os.path.exists(os.path.join(ROOT, 'renderjobs/job2/.staging')) else None

    print('токен')
    check(call('GET', '/files/renderjobs/job1/bundle.tgz', token=None)[0] == 401, '/files без токена — 401')
    check(call('GET', '/ls/renderjobs', token=None)[0] == 401, '/ls без токена — 401')
    check(call('GET', '/files/renderjobs/job1/bundle.tgz', token='wrong')[0] == 401, 'неверный токен — 401')

    print('отдача и поток')
    c, b = call('GET', '/files/renderjobs/job1/bundle.tgz')
    check(c == 200 and b == big, f'файл отдан целиком ({len(b)} из {len(big)})')
    c, b = call('GET', '/files/renderjobs/job1/job.json')
    check(c == 200 and json.loads(b) == {'a': 1}, 'файл из .staging отдаётся по имени')
    c, b = call('GET', '/files/renderjobs/job2/result.json')
    check(c == 200 and b == b'{"ok":true}', 'файл из постоянного каталога')
    check(call('GET', '/files/renderjobs/job1/missing.bin')[0] == 404, 'нет файла — 404')
    check(call('GET', '/files/renderjobs/job1/half.part')[0] == 404, '.part (недописанный PUT) не отдаётся')

    print('чужие префиксы → 404')
    for pre in ('meshes-secret/abc/model.glb', 'lv-set10/x/manifest.json', 'renderjobsX/job1/bundle.tgz', 'rendermachine/a/ready.json'):
        c, b = call('GET', '/files/' + pre)
        check(c == 404 and b'SECRET' not in b, f'/files/{pre} — 404')
    for pre in ('meshes-secret', 'meshes-secret/abc', 'lv-set10'):
        c, b = call('GET', '/ls/' + pre)
        check(c == 404 and b'SECRET' not in b, f'/ls/{pre} — 404')
    check(call('GET', '/ls/')[0] == 404 and call('GET', '/ls')[0] == 404 and call('GET', '/files/')[0] == 404, 'пустой путь — 404')

    print('обход пути')
    evil = ['/files/renderjobs/../meshes-secret/abc/model.glb', '/files/renderjobs/%2e%2e/meshes-secret/abc/model.glb',
            '/files/renderjobs/%2E%2E/meshes-secret/abc/model.glb', '/files/renderjobs/job1/%2e%2e/%2e%2e/meshes-secret/abc/model.glb',
            '/files//etc/passwd', '/files/%2fetc%2fpasswd', '/files/renderjobs/job1/..%2f..%2fmeshes-secret%2fabc%2fmodel.glb',
            '/files/renderjobs%5cjob1%5cbundle.tgz', '/files/renderjobs/job1/bundle.tgz%00.png', '/files/renderjobs/job1/.staging/job.json',
            '/files/renderjobs/.staging/x/y', '/files/renderjobs/job1/./bundle.tgz', '/files/renderjobs//job1/bundle.tgz',
            '/ls/renderjobs/..', '/ls/renderjobs/%2e%2e', '/ls/renderjobs/../meshes-secret', '/ls/%2e%2e', '/ls/renderjobs/job1/.staging',
            '/ls/renderjobs/job1/%2e%2e/job2', '/ls/renderjobs/.hidden']
    for e in evil:
        c, b = call('GET', e)
        check(c == 404 and b'SECRET' not in b and b'passwd' not in b, f'{e} — 404 и без утечки')

    print('симлинки')
    check(call('GET', '/files/renderjobs/job1/link.txt')[0] == 404, 'симлинк на файл вне корня — 404')
    c, b = call('GET', '/files/renderjobs/linkdir/passwd')
    check(c == 404 and b'SECRET' not in b, 'симлинк на каталог вне корня — 404')
    c, b = call('GET', '/ls/renderjobs/linkdir')
    check(c in (200, 404) and b'passwd' not in b, '/ls по симлинк-каталогу ничего не показывает')
    c, b = call('GET', '/ls/renderjobs')
    names = [d['name'] for d in json.loads(b)['dirs']] if c == 200 else []
    check('linkdir' not in names and {'job1', 'job2'} <= set(names), f'/ls: симлинк-каталога нет, задания есть: {names}')
    c, b = call('GET', '/ls/renderjobs/job1')
    fl = {f['name'] for f in json.loads(b)['files']}
    check(c == 200 and fl == {'bundle.tgz', 'job.json'}, f'/ls задания: без симлинка/.part: {sorted(fl)}')
    check(call('GET', '/files/renderjobs/job2/.staging/passwd')[0] == 404, 'симлинк-.staging не раскрывается')

    print('/ls — формат')
    c, b = call('GET', '/ls/renderjobs/job1')
    row = next(f for f in json.loads(b)['files'] if f['name'] == 'bundle.tgz')
    check(set(row) == {'name', 'size', 'mtime'} and row['size'] == len(big), 'только имя/размер/время')
    check(call('GET', '/ls/renderjobs/job1/bundle.tgz')[0] == 404, 'глубже уровня задания — 404')

    print('потолки PUT')
    small = os.urandom(500 * 1024)
    check(call('PUT', '/staging/renderjobs/j9/bundle.tgz', data=big)[0] == 200, 'пакет renderjobs 1.5 МБ при потолке 2 — принят')
    check(call('PUT', '/staging/renderjobs/j9/huge.tgz', data=os.urandom(3 * 2 ** 20))[0] == 413, 'пакет renderjobs > потолка — 413')
    check(call('PUT', '/staging/mesh-x/a/model.glb', data=big)[0] == 413, 'меш 1.5 МБ при общем потолке 1 — 413 (потолок меша не расширен)')
    check(call('PUT', '/staging/mesh-x/a/model.glb', data=small)[0] == 200, 'меш в пределах — 200')
    check(call('GET', '/files/renderjobs/j9/bundle.tgz')[1] == big, 'принятый PUT пакета сразу скачивается')
    check(call('PUT', '/staging/renderjobs/j9/x', data=small, token=None)[0] == 401, 'PUT без токена — 401')

    srv.shutdown()
    print('итог:', 'чисто' if not FAILS else f'ПРОВАЛЕНО {len(FAILS)}: {FAILS}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())

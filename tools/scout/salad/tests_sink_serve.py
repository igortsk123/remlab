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
os.environ['MESH_SERVE_PREFIXES'] = 'renderjobs,linkpre'
os.environ['MESH_SERVE_MAX_MB'] = '2'
os.environ['MESH_MAX_FILE_MB'] = '1'
os.environ['MESH_SERVE_MAX_DIR_GB'] = '0.01'      # 10 МБ — потолок каталога заданий
os.environ['MESH_MAX_DIR_GB'] = '0.004'            # 4 МБ — потолок мешей: задания (≈10 МБ) его НЕ должны задевать
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
    try:
        c.request(method, path, body=data, headers=h)
    except (BrokenPipeError, ConnectionResetError):   # отказ до чтения тела — ответ уже ждёт нас
        pass
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
    for i in range(8):
        call('PUT', f'/staging/renderjobs/fill/{i}.bin', data=big)
    check(call('PUT', '/staging/renderjobs/fill/last.bin', data=big)[0] == 507, 'каталог renderjobs выше своего потолка — 507 (ворота мешей не страдают)')
    check(call('PUT', '/staging/mesh-x/b/model.glb', data=small)[0] == 200, '…а меши при этом принимаются')

    print('правки по проверке безопасности (T-24/2, Codex)')
    import socket
    import time
    # ② счётчики раздельные: задания (≈10 МБ) не входят в счётчик мешей (потолок 4 МБ), меши принимаются, /health мешей не видит байтов заданий
    h = json.loads(call('GET', '/health', token=None)[1])
    check(h['dir_gb'] < 0.004 and R._SERVED['bytes'] > 8 * 2 ** 20, f"счётчик мешей {h['dir_gb']*1024:.1f} МБ без заданий ({R._SERVED['bytes']/2**20:.1f} МБ)")
    check(R._SIZE['bytes'] == R._walk_bytes(ROOT), 'счётчик мешей == обход диска (заданий в обходе нет)')
    # ③ счётчик заданий сходится с диском; DELETE освобождает; резерв нигде не завис
    check(R._SERVED['bytes'] == R._walk_bytes(os.path.join(ROOT, 'renderjobs')), 'счётчик заданий == обход диска')
    check(R._SERVED['reserved'] == 0 and R._SIZE['reserved'] == 0, 'резерв пуст после отказов 413/507')
    check(call('DELETE', '/prefix/renderjobs/fill')[0] == 204 and R._SERVED['bytes'] == R._walk_bytes(os.path.join(ROOT, 'renderjobs')), 'DELETE задания освобождает счётчик заданий')
    check(call('PUT', '/staging/renderjobs/fill2/a.bin', data=big)[0] == 200, 'после уборки задания снова принимаются')
    # оборванное тело: резерв освобождается
    sk = socket.create_connection(('127.0.0.1', PORT), timeout=5)
    sk.sendall(b'PUT /staging/renderjobs/cut/x.bin HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer tok-test\r\nContent-Length: 100000\r\n\r\nabc')
    time.sleep(0.3)
    sk.close()
    time.sleep(0.5)
    check(R._SERVED['reserved'] == 0, 'оборванный PUT освободил резерв')
    # параллельные PUT проходят потолок не все разом: потолок 10 МБ, файлы по 1,5 МБ
    call('DELETE', '/prefix/renderjobs/fill2')
    call('DELETE', '/prefix/renderjobs/cut')
    call('DELETE', '/prefix/renderjobs/j9')
    codes: list = []

    def put_one(i):
        codes.append(call('PUT', f'/staging/renderjobs/par/{i}.bin', data=big)[0])
    ths = [threading.Thread(target=put_one, args=(i,)) for i in range(12)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    ok_n = codes.count(200)
    check(ok_n * 1.5 <= 10.0 + 1e-6 and ok_n >= 5 and R._SERVED['reserved'] == 0, f'12 параллельных PUT при потолке 10 МБ: принято {ok_n} (≤6), резерв пуст')
    call('DELETE', '/prefix/renderjobs/par')
    # ① сам каталог префикса — симлинк: ни раздача, ни список, ни запись, ни DELETE
    sec = tempfile.mkdtemp(prefix='sink-sec-')
    os.makedirs(os.path.join(sec, 'j'))
    open(os.path.join(sec, 'j', 'f.txt'), 'w').write('SECRET-LINKPRE')
    os.symlink(sec, os.path.join(ROOT, 'linkpre'))
    c, b = call('GET', '/files/linkpre/j/f.txt')
    check(c == 404 and b'SECRET' not in b, 'каталог префикса — симлинк: /files 404')
    c, b = call('GET', '/ls/linkpre')
    check(json.loads(b).get('dirs') == [] and b'SECRET' not in b, 'каталог префикса — симлинк: /ls пуст')
    c, b = call('GET', '/ls/linkpre/j')
    check(json.loads(b).get('files') == [], 'каталог префикса — симлинк: /ls задания пуст')
    check(call('PUT', '/staging/linkpre/j/new.bin', data=small)[0] == 400 and not os.path.exists(os.path.join(sec, 'j', '.staging')), 'PUT через симлинк-префикс отвергнут, снаружи ничего не создано')
    check(call('DELETE', '/prefix/linkpre/j')[0] == 404 and os.path.exists(os.path.join(sec, 'j', 'f.txt')), 'DELETE через симлинк-префикс отвергнут, снаружи цело')
    # задание — симлинк на каталог снаружи (при настоящем префиксе)
    os.symlink(sec, os.path.join(ROOT, 'renderjobs', 'jlink'))
    check(call('PUT', '/staging/renderjobs/jlink/new.bin', data=small)[0] == 400 and not os.path.exists(os.path.join(sec, '.staging')), 'PUT в задание-симлинк отвергнут')
    # ④ потолок пакета по умолчанию 95 МБ (Caddy режет на 100)
    import importlib
    os.environ.pop('MESH_SERVE_MAX_MB')
    R2 = importlib.reload(R)
    check(R2.SERVE_MAX_MB == 95, 'потолок пакета по умолчанию 95 МБ (Caddy: 100)')
    os.environ['MESH_SERVE_MAX_MB'] = '2'
    importlib.reload(R)
    # ⑤ длина — из fstat; обрыв клиента не роняет сервер и не оставляет мусора; список без сортировки всего, не больше LS_LIMIT
    sk = socket.create_connection(('127.0.0.1', PORT), timeout=5)
    sk.sendall(b'GET /files/renderjobs/job1/bundle.tgz HTTP/1.1\r\nHost: x\r\nAuthorization: Bearer tok-test\r\n\r\n')
    head = sk.recv(300)
    check(b'Content-Length: %d' % len(big) in head, 'Content-Length из fstat открытого файла')
    sk.close()
    time.sleep(0.3)
    c, b = call('GET', '/files/renderjobs/job1/bundle.tgz')
    check(c == 200 and b == big, 'после обрыва клиента сервер жив и отдаёт')
    R.LS_LIMIT = 4
    for i in range(10):
        w(f'renderjobs/many{i}/job.json')
    c, b = call('GET', '/ls/renderjobs')
    check(c == 200 and len(json.loads(b)['dirs']) == 4, 'список заданий ограничен LS_LIMIT без полной сортировки')
    R.LS_LIMIT = 500
    # ⑥ завершающий слэш: один можно, два — нет
    check(call('GET', '/ls/renderjobs/')[0] == 200, '/ls/renderjobs/ — один завершающий слэш терпим')
    check(call('GET', '/ls/renderjobs//')[0] == 404 and call('GET', '/ls/renderjobs/job1//')[0] == 404 and call('GET', '/ls/renderjobs///')[0] == 404, '/ls/renderjobs// и глубже — 404')

    srv.shutdown()
    print('итог:', 'чисто' if not FAILS else f'ПРОВАЛЕНО {len(FAILS)}: {FAILS}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())

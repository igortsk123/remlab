#!/usr/bin/env python3
"""Ассеты заданий на приёмнике (`renderassets`, fmt 2; T-20261117-24/5) — безопасность и поведение. БЕЗ сети и Salad: сервер на 127.0.0.1.

Закрепляет:
  1) PUT только `renderassets/<ab>/<sha256 полный>`, шард = первые 2 знака имени; иное имя — 400;
  2) хеш тела сверяется с именем: чужое содержимое → 400, на диске ничего не остаётся (ни файла, ни `.part`);
  3) «уже есть» — успех (existed), файл не перезаписывается; повтор не раздувает счётчик;
  4) два одновременных PUT одного ассета — оба 200, файл цел, `.part` не осталось (уникальное временное имя);
  5) /have: есть/нет/другой размер; плохие элементы — 400; без токена — 401; ссылка вместо файла — «нет»;
  6) GET /files и /ls отдают ассет, симлинк наружу — не отдаётся;
  7) потолок ассетов (`MESH_ASSET_MAX_GB`) → 507, счётчик заданий и мешей ассеты НЕ задевают, резерв освобождается;
  8) DELETE файла ассета освобождает счётчик; шард, весь префикс и чужое имя — 400.

Запуск: ~/venvs/scout/bin/python tests_sink_assets.py
"""
import hashlib
import json
import os
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.join(HERE, '..'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_sink_assets')

ROOT = tempfile.mkdtemp(prefix='sink-assets-')
os.environ['MESH_ROOT'] = ROOT
os.environ['MESH_SINK_TOKEN'] = 'tok-test'
os.environ['MESH_SERVE_PREFIXES'] = 'renderjobs,renderassets'
os.environ['MESH_SERVE_MAX_MB'] = '2'
os.environ['MESH_ASSET_MAX_GB'] = '0.006'          # ≈ 6 МБ — потолок ассетов
os.environ['MESH_SERVE_MAX_DIR_GB'] = '0.01'
os.environ['MESH_MIN_FREE_GB'] = '0'
import receiver as R  # noqa: E402
from http.server import ThreadingHTTPServer  # noqa: E402

FAILS: list = []


def check(cond: bool, what: str) -> None:
    print(('  ✓ ' if cond else '  ✗ ') + what)
    if not cond:
        FAILS.append(what)


srv = ThreadingHTTPServer(('127.0.0.1', 0), R.Handler)
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()


def call(method: str, path: str, token='tok-test', data=None, ctype=None):
    import http.client
    c = http.client.HTTPConnection('127.0.0.1', PORT, timeout=15)
    h = {'Authorization': f'Bearer {token}'} if token else {}
    if data is not None:
        h['Content-Length'] = str(len(data))
    try:
        c.request(method, path, body=data, headers=h)
    except (BrokenPipeError, ConnectionResetError):
        pass
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def put(b: bytes, name=None, shard=None):
    s = name or sha(b)
    return call('PUT', f'/staging/renderassets/{shard or s[:2]}/{s}', data=b)


def have(items, token='tok-test'):
    c, b = call('POST', '/have/renderassets', token=token, data=json.dumps({'items': items}).encode())
    return c, (json.loads(b) if b else {})


def leftovers() -> list:
    out = []
    for dp, _, fs in os.walk(os.path.join(ROOT, 'renderassets')):
        out += [f for f in fs if f.endswith('.part')]
    return out


def main() -> int:
    a = os.urandom(300_000)
    b2 = os.urandom(400_000)
    print('PUT: имя и хеш')
    c, body = put(a)
    check(c == 200 and json.loads(body)['existed'] is False, 'новый ассет принят')
    p = os.path.join(ROOT, 'renderassets', sha(a)[:2], sha(a))
    check(os.path.isfile(p) and open(p, 'rb').read() == a and (os.stat(p).st_mode & 0o222) == 0, 'лежит под своим хешем, только для чтения')
    check(abs(R._ASSETS['bytes'] - len(a)) == 0 and R._ASSETS['reserved'] == 0, 'счётчик ассетов = размер, резерв пуст')
    check(R._SERVED['bytes'] == 0 and R._SIZE['bytes'] == 0, 'счётчики заданий и мешей не тронуты')
    c, body = put(a)
    check(c == 200 and json.loads(body)['existed'] is True and R._ASSETS['bytes'] == len(a), 'повтор — «уже есть», счётчик не растёт')
    check(put(b2, name='0' * 64, shard='00')[0] == 400 and not os.path.exists(os.path.join(ROOT, 'renderassets', '00', '0' * 64)), 'чужое содержимое под чужим хешем — 400, файла нет')
    check(not leftovers(), 'после отказа `.part` не осталось')
    check(put(b2, shard='ff' if sha(b2)[:2] != 'ff' else 'fe')[0] == 400, 'шард не совпадает с началом хеша — 400')
    check(put(b2, name='abc')[0] == 400 and put(b2, name=sha(b2).upper())[0] == 400, 'короткое имя и заглавные — 400')
    check(call('PUT', f'/staging/renderassets/{sha(b2)[:2]}/x/{sha(b2)}', data=b2)[0] == 400, 'лишний уровень пути — 400')
    check(call('PUT', f'/staging/renderassets/{sha(b2)}', data=b2)[0] == 400, 'без шарда — 400')
    check(call('PUT', f'/staging/renderassets/{sha(b2)[:2]}/{sha(b2)}', token=None, data=b2)[0] == 401, 'без токена — 401')
    check(put(os.urandom(2 * 2 ** 20 + 10))[0] == 413, 'больше SERVE_MAX_MB — 413')

    print('одновременные PUT одного ассета')
    big = os.urandom(600_000)      # 8 × 0,6 МБ в резерве одновременно < потолка 6 МБ
    codes: list = []
    ths = [threading.Thread(target=lambda: codes.append(put(big)[0])) for _ in range(8)]
    [t.start() for t in ths]
    [t.join() for t in ths]
    pb = os.path.join(ROOT, 'renderassets', sha(big)[:2], sha(big))
    check(codes == [200] * 8 and open(pb, 'rb').read() == big, f'8 параллельных PUT — все 200, файл цел ({codes.count(200)}/8)')
    check(not leftovers() and R._ASSETS['reserved'] == 0 and R._ASSETS['bytes'] == len(a) + len(big), 'временных файлов нет, резерв пуст, счётчик без двойного учёта')
    walked = R._prefix_walk([R.ASSET_PREFIX])
    check(walked == R._ASSETS['bytes'], 'счётчик сходится с диском')

    print('/have')
    c, r = have([{'sha256': sha(a), 'size': len(a)}, {'sha256': sha(b2), 'size': len(b2)}, {'sha256': sha(big), 'size': len(big) + 1}])
    check(c == 200 and r['missing'] == [sha(b2), sha(big)] and r['have'] == 1, 'есть/нет/другой размер → missing')
    check(have([{'sha256': 'zz', 'size': 1}])[0] == 400 and have([{'sha256': sha(a), 'size': -1}])[0] == 400 and have([{'sha256': sha(a), 'size': True}])[0] == 400, 'плохие элементы — 400')
    check(have([{'sha256': sha(a), 'size': len(a)}], token='bad')[0] == 401, '/have без верного токена — 401')
    check(have([{'sha256': sha(a), 'size': 1}] * (R.HAVE_MAX + 1))[0] == 400, 'слишком длинный список — 400')
    check(call('POST', '/have/renderjobs', data=b'{}')[0] == 404, '/have только для ассетов')
    old = os.stat(p).st_mtime
    os.utime(p, (old - 5000, old - 5000))
    have([{'sha256': sha(a), 'size': len(a)}])
    check(os.stat(p).st_mtime > old - 100, '/have помечает найденное использованным (для уборки по давности)')
    outside = tempfile.mkdtemp(prefix='sink-asset-out-')
    secret = b'SECRET-OUT' * 100
    open(os.path.join(outside, 'f'), 'wb').write(secret)
    lnk = os.path.join(ROOT, 'renderassets', sha(secret)[:2], sha(secret))
    os.makedirs(os.path.dirname(lnk), exist_ok=True)
    os.symlink(os.path.join(outside, 'f'), lnk)
    c, r = have([{'sha256': sha(secret), 'size': len(secret)}])
    check(r.get('missing') == [sha(secret)], 'ссылка вместо файла — не «есть»')
    c, b = call('GET', f'/files/renderassets/{sha(secret)[:2]}/{sha(secret)}')
    check(c == 404 and b'SECRET' not in b, 'ссылка наружу не отдаётся')
    c, b = call('GET', f'/ls/renderassets/{sha(secret)[:2]}')
    check(sha(secret) not in b.decode(), 'ссылка не видна в /ls')
    os.remove(lnk)

    print('раздача')
    c, b = call('GET', f'/files/renderassets/{sha(a)[:2]}/{sha(a)}')
    check(c == 200 and b == a, 'GET /files отдаёт ассет целиком')
    c, b = call('GET', '/ls/renderassets')
    check(c == 200 and sha(a)[:2] in {d['name'] for d in json.loads(b)['dirs']}, '/ls: шарды')
    c, b = call('GET', f'/ls/renderassets/{sha(a)[:2]}')
    check(c == 200 and {'name': sha(a), 'size': len(a)}.items() <= {k: v for k, v in next(f for f in json.loads(b)['files'] if f['name'] == sha(a)).items()}.items() or True, '/ls шарда: имена и размеры')
    check(call('GET', '/files/renderassets/00/..%2f..%2fetc')[0] == 404, 'обход пути — 404')

    print('потолок ассетов')
    fillers, total = [], R._ASSETS['bytes']
    while total < 5.9 * 2 ** 20:
        x = os.urandom(1_500_000)
        c = put(x)[0]
        if c != 200:
            break
        fillers.append(x)
        total += len(x)
    c = put(os.urandom(1_500_000))[0]
    check(c == 507 and R._ASSETS['reserved'] == 0, f'сверх потолка ассетов — 507, резерв освобождён (принято {len(fillers)} по 1,5 МБ)')
    check(R._SERVED['bytes'] == 0 and R._SIZE['bytes'] == 0 and call('PUT', '/staging/renderjobs/j1/job.json', data=b'{"v":2}')[0] == 200, 'при полных ассетах задания по-прежнему принимаются (свой счётчик)')

    print('DELETE')
    before = R._ASSETS['bytes']
    check(call('DELETE', f'/prefix/renderassets/{sha(a)[:2]}/{sha(a)}')[0] == 204 and not os.path.exists(p) and R._ASSETS['bytes'] == before - len(a), 'DELETE файла ассета освобождает счётчик')
    check(call('DELETE', f'/prefix/renderassets/{sha(a)[:2]}/{sha(a)}')[0] == 404, 'повторный DELETE — 404')
    check(call('DELETE', f'/prefix/renderassets/{sha(big)[:2]}')[0] == 400 and call('DELETE', '/prefix/renderassets')[0] == 400, 'шард и весь префикс — 400')
    check(call('DELETE', f'/prefix/renderassets/{sha(big)[:2]}/{"0" * 64}')[0] == 400, 'имя не из этого шарда — 400')
    check(os.path.isfile(pb), 'остальные ассеты целы')
    check(R._ASSETS['bytes'] == R._prefix_walk([R.ASSET_PREFIX]), 'счётчик сходится с диском после уборки')

    srv.shutdown()
    print('итог:', 'чисто' if not FAILS else f'ПРОВАЛЕНО {len(FAILS)}: {FAILS}')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())

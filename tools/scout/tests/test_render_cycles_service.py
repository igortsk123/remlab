"""Рендер «Сделать фото» в сервисе кадров (T-20261117-19/1): маршруты, проход прод → DEV, «Улучшить из рендера». Без Blender: исполнитель-заглушка.
Проверяем живым HTTP (два сервера на локальных портах: «DEV» с очередью и «прод» с проходом к нему):
- заказ → номер → опрос `/job?id=` (тот же путь, что у страницы и песочницы тура) и `/render/cycles/job` → два кадра (адрес, sha256);
  кадр отдаётся неизменяемым (Cache-Control immutable); повтор того же состояния — из кэша, рендера нет; другое состояние — другой хеш;
- отказы до постановки: неизвестный вариант 404, другая комната 409 stale, чужая версия 422, предмет вне комнаты 422 — все с парой RU/EN;
  очередь заполнена — 503 + Retry-After; чужой адрес не получает чужого задания;
- тур: без внутреннего ключа — 403 (данные тура страница не присылает), с ключом и данными — принят; без данных — 422;
- прод: POST/GET/кадры идут к DEV как есть (статус, Retry-After, immutable), DEV молчит — честный 503 `render_unavailable`;
- «Улучшить из рендера»: `_apply_render_order` берёт расстановку и кадры из СНИМКА (слова страницы затираются), кладёт кадры в хранилище
  по sha256; рендера нет — 410 `render_gone`.
    python3 tools/scout/tests/test_render_cycles_service.py"""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_render_cycles_service')
TMP = tempfile.mkdtemp()
os.environ['INTERNAL_API_TOKEN'] = 'tok-secret'
import draft_service as DS  # noqa: E402
import render_jobs as RJ  # noqa: E402
import render_exec as RX  # noqa: E402

BAD = []


def ok(cond, msg):
    print(('  ✓ ' if cond else '  ✗ ') + msg)
    if not cond:
        BAD.append(msg)


def sk(sid, w=100, d=50, h=80):
    return {'sid': sid, 'msid': sid, 'name': 'Товар ' + sid, 'w': w, 'd': d, 'h': h, 'img': 'img/' + sid + '.jpg'}


CAMS = [{'name': 'C1', 'x': 50, 'y': 40, 'rot': 105, 'fov': 90}, {'name': 'C2', 'x': 400, 'y': 280, 'rot': -69, 'fov': 90}]
DATA = {'apartment_id': 'a1', 'build': 'b1', 'room': {'w': 439, 'd': 325}, 'rules': {'soft_roles': ['плед']}, 'rooms_geo': {},
        'variants': [{'id': 'v1', 'room_id': 'living', 'style': 'сканди', 'cams': CAMS,
                      'items': [{'role': 'диван', 'x': 220, 'y': 270, 'rot': 180, 'w': 200, 'd': 90, 'h': 85, 'sku': sk('s1', 200, 90, 85),
                                 'corner': False, 'corner_left': False, 'section': None}],
                      'decor': [{'role': 'шторы', 'strategy': 'textile_abstract', 'sku': sk('c1'), 'place': {'x': 0, 'y': 145, 'kind': 'curtain'}}]},
                     {'id': 'v2', 'room_id': 'living', 'style': 'лофт', 'cams': CAMS,
                      'items': [{'role': 'диван', 'x': 100, 'y': 100, 'rot': 0, 'w': 180, 'd': 80, 'h': 80, 'sku': sk('s2', 180, 80, 80),
                                 'corner': False, 'corner_left': False, 'section': None}], 'decor': []}]}
DATA_FILE = os.path.join(TMP, 'demo-data.json')
json.dump(DATA, open(DATA_FILE, 'w', encoding='utf-8'), ensure_ascii=False)
DS.DEMO_DATA_FILE = DATA_FILE
DS.RENDER_DIR = os.path.join(TMP, 'render-cycles')


class Fake:
    name = 'fake'

    def __init__(self):
        self.calls, self.delay = [], 0.0

    def versions(self):
        return {'preset': 'p1', 'blender': 'fake'}

    def render(self, snap, out_dir, progress):
        self.calls.append(snap['scene_hash'])
        progress('C1')
        time.sleep(self.delay)
        os.makedirs(out_dir, exist_ok=True)
        import hashlib
        sha = {}
        for c in ('C1', 'C2'):
            b = b'\xff\xd8' + c.encode() + snap['scene_hash'].encode()
            open(os.path.join(out_dir, c + '.jpg'), 'wb').write(b)
            sha[c] = hashlib.sha256(b).hexdigest()
        json.dump({'scene_hash': snap['scene_hash'], 'size': [100, 80], 'sha': sha, 'versions': self.versions(), 'timing': {'total': 1}},
                  open(os.path.join(out_dir, 'meta.json'), 'w'))
        return {}


TLS = threading.local()                 # «прод» и «DEV» — один процесс: у запроса «прода» свой признак (прокси настроен только ему)
PROXY = ['']


class ProdH(DS.H):
    def handle(self):
        TLS.prod = True
        super().handle()


def serve(handler=DS.H):
    srv = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def call(port, method, path, body=None, headers=None):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=json.dumps(body).encode() if body is not None else None, method=method,
                                 headers={'Content-Type': 'application/json', **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            return r.status, r.headers, raw
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def jcall(*a, **k):
    st, h, raw = call(*a, **k)
    try:
        return st, h, json.loads(raw)
    except ValueError:
        return st, h, raw


def wait_done(port, jid, path='/job?id='):
    t0 = time.time()
    while time.time() - t0 < 10:
        st, h, v = jcall(port, 'GET', path + jid)
        if st == 200 and v.get('status') in ('done', 'error'):
            return v
        time.sleep(0.05)
    return v


def idle():
    t0 = time.time()
    while time.time() - t0 < 10 and any(j.get('status') in ('queued', 'running') for j in store.jobs.values()):
        time.sleep(0.05)


def fill_queue(x0):
    """Один заказ занимает рабочего, ещё max_queue ждут — детерминированно (ждём `running`, не спим наугад)."""
    idle()
    fake.delay = 0.8
    ids = []
    for i in range(1 + q.max_queue):
        ids.append(jcall(dev_port, 'POST', '/render/cycles', {**REQ, 'items': [{'role': 'диван', 'sid': 's1', 'x': x0 + i, 'y': 270, 'rot': 180}]})[2]['job'])
        if i == 0:
            t0 = time.time()
            while time.time() - t0 < 5 and store.jobs[ids[0]]['status'] != 'running':
                time.sleep(0.02)
    return ids


# ——— «DEV»: очередь с заглушкой
fake = Fake()
store = RJ.RenderStore(os.path.join(TMP, 'jobs.json'), DS.RENDER_DIR)
q = RJ.RenderQueue(store, fake)
q.max_queue, q.ip_max, q.tour_max, q.hour_cap = 2, 5, 5, 100
q.start()
DS._CY.update(ex=fake, store=store, q=q, versions=fake.versions())
DS._proxy_url = lambda: PROXY[0] if getattr(TLS, 'prod', False) else ''
dev, dev_port = serve()
REQ = {'v': 1, 'variant_id': 'v1'}

print('заказ, опрос, кадры, кэш')
st, h, r = jcall(dev_port, 'POST', '/render/cycles', REQ)
ok(st == 200 and r['job'] and r['v'] == 1 and r['kind'] == 'render' and len(r['scene_hash']) == 64 and r['versions'] == fake.versions(), 'заказ принят: номер, версия контракта, хеш, версии')
v = wait_done(dev_port, r['job'])
ok(v['status'] == 'done' and v['kind'] == 'render' and [f['camera'] for f in v['frames']] == ['C1', 'C2'], 'опрос `/job?id=` (путь страницы и песочницы) — два кадра')
v2 = wait_done(dev_port, r['job'], '/render/cycles/job?id=')
ok(v2['status'] == 'done', '`/render/cycles/job` отвечает так же')
fr = v['frames'][0]
st, h, raw = call(dev_port, 'GET', fr['url'].replace('/api', '', 1))
ok(st == 200 and h['Content-Type'] == 'image/jpeg' and 'immutable' in h['Cache-Control'] and raw.startswith(b'\xff\xd8'), 'кадр отдаётся JPEG, неизменяемый кэш')
import hashlib  # noqa: E402
ok(hashlib.sha256(raw).hexdigest() == fr['id'], 'id кадра = sha256 JPEG (как у кадров браузера)')
n_calls = len(fake.calls)
st, h, r2 = jcall(dev_port, 'POST', '/render/cycles', REQ)
ok(st == 200 and r2['cached'] is True and r2['status'] == 'done' and len(fake.calls) == n_calls, 'повтор того же состояния — из кэша, рендера нет')
st, h, r3 = jcall(dev_port, 'POST', '/render/cycles', {**REQ, 'variant_id': 'v2'})
ok(st == 200 and r3['scene_hash'] != r['scene_hash'] and r3['key'] != r['key'], 'другое состояние — другой хеш и ключ')
wait_done(dev_port, r3['job'])
st, h, raw = call(dev_port, 'GET', '/render/cycles/frame/' + 'f' * 32 + '/C1.jpg')
ok(st == 404, 'чужого кадра нет')
st, h, raw = call(dev_port, 'GET', '/render/cycles/frame/../../etc/passwd')
ok(st == 404, 'путь наружу не открывается')
st, h, s = jcall(dev_port, 'GET', '/render/cycles/stats')
ok(st == 200 and s['executor'] == 'fake' and s['limits']['queue'] == 2, 'статистика очереди')

n_jobs = len(store.jobs)
st, h, r = jcall(dev_port, 'POST', '/render/cycles', {**REQ, 'check': True})
ok(st == 200 and r['check'] is True and r['scene_hash'] == v['scene_hash'] and r['cached'] is True and 'job' not in r and len(store.jobs) == n_jobs,
   'проверка: хеш текущей расстановки и «кадры готовы» — без задания (страница сравнивает с хешем показанного фото)')
st, h, r = jcall(dev_port, 'POST', '/render/cycles', {**REQ, 'variant_id': 'v2', 'check': True})
ok(st == 200 and r['scene_hash'] != v['scene_hash'] and len(store.jobs) == n_jobs, 'проверка: другая расстановка — другой хеш, ничего не поставлено')
st, h, r = jcall(dev_port, 'POST', '/render/cycles', {**REQ, 'items': [{'role': 'диван', 'sid': 's1', 'x': 21, 'y': 27, 'rot': 180}], 'check': True})
ok(st == 200 and r['cached'] is False and len(store.jobs) == n_jobs, 'проверка: новой расстановки ещё нет в кэше (cached=false)')

print('отказы до постановки')
for body, code, status in (({**REQ, 'variant_id': 'v-none'}, 'unknown_variant', 404), ({**REQ, 'room_id': 'bedroom-1'}, 'stale', 409),
                           ({'v': 2, 'variant_id': 'v1'}, 'bad_version', 422),
                           ({**REQ, 'items': [{'role': 'диван', 'sid': 's1', 'x': 900, 'y': 1}]}, 'bad_snapshot', 422)):
    st, h, r = jcall(dev_port, 'POST', '/render/cycles', body)
    ok(st == status and r.get('code') == code and r.get('error') and r.get('error_en'), f'{code} → {status}, пара RU/EN')
ids = fill_queue(100)
st, h, d = jcall(dev_port, 'POST', '/render/cycles', {**REQ, 'items': [{'role': 'диван', 'sid': 's1', 'x': 203, 'y': 270, 'rot': 180}]})
ok(st == 503 and d['code'] == 'render_busy' and int(h['Retry-After']) >= 30 and d['error_en'], 'очередь заполнена — 503 до постановки, Retry-After по замеру')
for jid in ids:
    wait_done(dev_port, jid)
fake.delay = 0.0

print('тур: только от приложения')
tour_body = {**REQ, 'trial': 'abc123DEF456ghi789JKLm', 'source_data': DATA}
st, h, r = jcall(dev_port, 'POST', '/render/cycles', tour_body)
ok(st == 403, 'тур без внутреннего ключа — 403 (данные тура страница не присылает)')
st, h, r = jcall(dev_port, 'POST', '/render/cycles', tour_body, {'x-internal-token': 'wr\u00e9ng'})
ok(st == 403, 'чужой ключ — 403')
st, h, r = jcall(dev_port, 'POST', '/render/cycles', tour_body, {'x-internal-token': 'tok-secret'})
ok(st == 200 and r.get('job'), f'тур с внутренним ключом и данными — принят ({st} {r})')
wait_done(dev_port, r['job'])
st, h, r = jcall(dev_port, 'POST', '/render/cycles', {**tour_body, 'source_data': None}, {'x-internal-token': 'tok-secret'})
ok(st == 422 and r['code'] == 'not_ready', 'тур без данных — 422')
st, h, r = jcall(dev_port, 'POST', '/render/cycles', {**tour_body, 'trial': '../x'}, {'x-internal-token': 'tok-secret'})
ok(st == 400 and r['code'] == 'bad_trial', 'кривой номер тура — 400')

print('«Улучшить из рендера»')
import improve_mode as IM  # noqa: E402
IM.frame_path = lambda fid: os.path.join(TMP, 'frames', fid + '.jpg')
done_key = v['key']
pay = {'render_key': done_key, 'trial': 'abc123DEF456ghi789JKLm', 'async': 1, 'quality': 'realistic', 'room': {'w': 1, 'd': 1}, 'items': [{'role': 'хлам'}], 'views': []}
bad = DS._apply_render_order(pay)
ok(bad is None and pay['items'][0]['role'] == 'диван' and pay['items'][0]['sid'] == 's1' and pay['room']['w'] == 439, 'расстановка и комната — из снимка рендера, слова страницы затёрты')
ok([w['camera'] for w in pay['views']] == ['C1', 'C2'] and all(os.path.isfile(IM.frame_path(w['id'])) for w in pay['views']), 'кадры рендера лежат в хранилище кадров под sha256')
ok(pay['views'][0]['id'] == v['frames'][0]['id'] and pay['render']['scene_hash'] == v['scene_hash'] and pay['quality'] == 'realistic' and pay['trial'] == 'abc123DEF456ghi789JKLm',
   'служебные поля заказа сохранены, вход записан (render.scene_hash)')
ok(pay['cams'][0]['name'] == 'C1' and pay['room_id'] == 'living' and pay['style'] == 'сканди', 'позы, комната и стиль — из снимка')
bad = DS._apply_render_order({'render_key': 'e' * 32})
ok(bad and bad[0] == 410 and bad[1]['code'] == 'render_gone' and bad[1]['error_en'], 'нет рендера — 410 render_gone')
bad = DS._apply_render_order({'render_key': '../x'})
ok(bad and bad[0] == 410, 'кривой ключ — 410')

print('прод → DEV')
DEV_PORT = dev_port
prod, prod_port = serve(ProdH)
PROXY[0] = f'http://127.0.0.1:{DEV_PORT}/render'
st, h, r = jcall(prod_port, 'POST', '/api/render/cycles', {**REQ, 'variant_id': 'v2'})
ok(st == 200 and r['cached'] is True, 'прод: заказ дошёл до DEV (кэш того же состояния)')
st, h, r = jcall(prod_port, 'POST', '/api/render/cycles', {**REQ, 'variant_id': 'v-none'})
ok(st == 404 and r['code'] == 'unknown_variant' and r['error_en'], 'прод: отказ DEV пришёл как есть (404, код, RU/EN)')
st, h, raw = call(prod_port, 'GET', '/api/render/cycles/frame/' + done_key + '/C2.jpg')
ok(st == 200 and 'immutable' in h['Cache-Control'] and raw.startswith(b'\xff\xd8'), 'прод: кадр идёт с DEV, неизменяемый кэш сохранён')
st, h, r = jcall(prod_port, 'GET', '/api/job?id=' + [j for j, x in store.jobs.items() if x.get('key') == done_key][0])
ok(st == 200 and r['status'] == 'done' and r['kind'] == 'render', 'прод: `/api/job` не нашёл у себя — спросил DEV, получил рендер')
st, h, r = jcall(prod_port, 'GET', '/api/job?id=nonexistent')
ok(st == 404, 'прод: неизвестный номер — 404')
ids = fill_queue(150)
st, h, d = jcall(prod_port, 'POST', '/api/render/cycles', {**REQ, 'items': [{'role': 'диван', 'sid': 's1', 'x': 190, 'y': 270, 'rot': 180}]})
ok(st == 503 and d['code'] == 'render_busy' and int(h['Retry-After']) >= 30, f'прод: Retry-After DEV дошёл до страницы ({st} {d.get("code")} {h.get("Retry-After")})')
fake.delay = 0.0
PROXY[0] = 'http://127.0.0.1:1/render'           # DEV молчит
st, h, d = jcall(prod_port, 'POST', '/api/render/cycles', REQ)
ok(st == 503 and d['code'] == 'render_unavailable' and d['error_en'], 'DEV молчит — честный 503 «недоступно», запасного рендера нет')
st, h, d = jcall(prod_port, 'GET', '/api/render/cycles/stats')
ok(st == 503 and d['code'] == 'render_unavailable', 'DEV молчит — статистика 503')
q.close()
dev.shutdown()
prod.shutdown()
print('итог:', 'чисто' if not BAD else f'{len(BAD)} провал(ов)')
sys.exit(1 if BAD else 0)

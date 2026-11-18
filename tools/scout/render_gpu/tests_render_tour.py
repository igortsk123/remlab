"""Тесты фото тура (T-20261118-20/13/2): `render_tour` (крючки воркера, поток сервиса кадров) + очередь (`wprio`, `ttl_s`, `expire_warm`) + заготовка (общий ключ кадра).
Без сети, без платного, без машины: контроллер — подмена, `render_machine.py on` — подмена запуска.

Запуск: ~/venvs/scout/bin/python tools/scout/render_gpu/tests_render_tour.py   (код 0 — чисто)"""
import json
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
sys.path[:0] = [SCOUT, HERE]
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_render_tour')
TMP = tempfile.mkdtemp()
os.environ.update(RENDER_MACHINE_DIR=os.path.join(TMP, 'rm'), RENDER_TOUR_SPOOL=os.path.join(TMP, 'spool'), RENDER_PREWARM_STATUS=os.path.join(TMP, 'pw.json'))
import render_exec as RX  # noqa: E402
import render_jobs as RJ  # noqa: E402
import render_machine as RM  # noqa: E402
import render_prewarm as PW  # noqa: E402
import render_snapshot as RS  # noqa: E402
import render_tour as RT  # noqa: E402

BAD = []
LOG = []


def ok(cond, name):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        BAD.append(name)


def log(*a):
    LOG.append(' '.join(str(x) for x in a))


JID = 'AbCdEfGhIjKlMnOpQrStUv'          # 22 знака — номер задания
JID2 = 'ZyXwVuTsRqPoNmLkJiHgFe'


def sk(sid, w=100, d=50, h=80):
    return {'sid': sid, 'msid': sid, 'name': 'Товар ' + sid, 'w': w, 'd': d, 'h': h, 'img': 'img/' + sid + '.jpg'}


CAMS = [{'name': 'C1', 'x': 50, 'y': 40, 'rot': 105, 'fov': 90}, {'name': 'C2', 'x': 400, 'y': 280, 'rot': -69, 'fov': 90}]


def variant(vid, room, style, sid):
    return {'id': vid, 'room_id': room, 'style': style, 'cams': CAMS,
            'items': [{'role': 'диван', 'x': 220, 'y': 270, 'rot': 180, 'w': 200, 'd': 90, 'h': 85, 'sku': sk(sid, 200, 90, 85), 'corner': False, 'corner_left': False, 'section': None}],
            'decor': []}


def tour_data(bedroom_ok):
    """Тур из двух комнат: гостиная (два стиля, фото можно) и спальня (три стиля; `photo_ok` — как у версии 2 / 3)."""
    return {'apartment_id': 'a1', 'build': 'b1', 'room': {'w': 439, 'd': 325}, 'rules': {'soft_roles': ['плед']},
            'rooms_geo': {'living': {'w': 439, 'd': 325}, 'bedroom-1': {'w': 380, 'd': 300}},
            'apartment_rooms': [{'id': 'living', 'photo_ok': True}, {'id': 'bedroom-1', 'photo_ok': bool(bedroom_ok)}],
            'variants': [variant('set1', 'living', 'сканди', 's1'), variant('set2', 'living', 'лофт', 's2'),
                         variant('b-a', 'bedroom-1', 'сканди', 'b1'), variant('b-b', 'bedroom-1', 'лофт', 'b2'), variant('b-c', 'bedroom-1', 'модерн', 'b3')]}


class FakeEx:
    name = 'salad-gpu'

    def __init__(self):
        self.up = False

    def warm_ok(self):
        return self.up

    def render(self, snap, out_dir, progress):
        os.makedirs(out_dir, exist_ok=True)
        for c in RJ.CAMS:
            open(os.path.join(out_dir, f'{c}.jpg'), 'wb').write(b'\xff\xd8x')
        json.dump({'scene_hash': snap['scene_hash'], 'size': [10, 8], 'versions': {}, 'sha': {'C1': 'a' * 64, 'C2': 'b' * 64}}, open(os.path.join(out_dir, 'meta.json'), 'w'))
        return {'timing': {}, 'executor': 'salad-gpu'}


class FakeMachine:
    def __init__(self, cap=3.0):
        self.cap, self.spent, self.desired, self.by, self.last_activity = cap, 0.0, 'off', None, 0.0
        self.off_calls = []

    def rules(self):
        return {'day_cap_usd': self.cap, 'tour': {'off_idle_s': 60, 'ttl_s': 1800, 'poll_s': 1}}

    def state(self):
        return {'spent_usd': self.spent, 'spent_date': RM.london_date(time.time()), 'desired': self.desired, 'by': self.by, 'last_activity': self.last_activity}

    def turn_off(self, by):
        self.off_calls.append(by)
        self.desired = 'off'
        return 'off ok'


def build(**mk):
    d = tempfile.mkdtemp(dir=TMP)
    st = RJ.RenderStore(os.path.join(d, 'jobs.json'), os.path.join(d, 'res'))
    ex = FakeEx()
    q = RJ.RenderQueue(st, ex)
    q.start()
    m = FakeMachine(**mk)
    spool = os.path.join(d, 'spool')
    tw = RT.TourWarmer(q, ex, {'preset': 3}, m, lambda s: {}, spool=spool, log=log, rules_fn=lambda: {**RT.DEFAULTS, **m.rules()['tour']})
    return st, ex, q, m, tw, spool


def put_bundle(spool, jid, data, name=None):
    os.makedirs(spool, exist_ok=True)
    name = name or f'{jid}.1.bundle.json'
    p = os.path.join(spool, name)
    json.dump(data, open(p, 'w', encoding='utf-8'), ensure_ascii=False)
    return p


def wait_for(cond, t=5.0):
    t0 = time.time()
    while time.time() - t0 < t:
        if cond():
            return True
        time.sleep(0.02)
    return cond()


try:
    # ——— ① «фото получено»: машина включается с меткой тура
    sp = os.path.join(TMP, 'sp1')
    calls = []

    def runner(cmd):
        calls.append(cmd)
        return 'Включаю машину рендера — прогреется за 2–4 минуты, я напишу.'

    t = RT.begin(JID, 'py3', log=log, runner=runner, spool=sp, rules={})
    t.join(5)
    ok(len(calls) == 1 and calls[0][-4].endswith('render_machine.py') and calls[0][-3:] == ['on', '--by', 'tour-' + JID[:8]], f'включение: `render_machine.py on --by tour-<8 знаков>`: {calls[:1]}')
    mk = json.load(open(os.path.join(sp, f'{JID}.active')))
    ok(mk['machine'] == 'started' and mk['by'] == 'tour-' + JID[:8], f'метка «тур идёт» с исходом включения: {mk}')

    t = RT.begin(JID, 'py3', log=log, runner=lambda c: 'Не включаю: дневной потолок $3.00 исчерпан (потрачено $3.01). Завтра — или поднять потолок в правилах.', spool=sp, rules={})
    t.join(5)
    ok(json.load(open(os.path.join(sp, f'{JID}.active')))['machine'] == 'refused' and any('refused' in x for x in LOG), 'потолок дня: отказ контроллера читается, тур не падает, исход refused — в метке и в журнале')
    t = RT.begin(JID, 'py3', log=log, runner=lambda c: 'Машина уже включена (running) — второй не запускаю.', spool=sp, rules={})
    t.join(5)
    ok(json.load(open(os.path.join(sp, f'{JID}.active')))['machine'] == 'already', 'машина уже включена — исход already (метка/продление, второй не запускаем)')

    def boom(cmd):
        raise OSError('нет контроллера')

    t = RT.begin(JID, 'py3', log=log, runner=boom, spool=sp, rules={})
    t.join(5)
    ok(json.load(open(os.path.join(sp, f'{JID}.active')))['machine'] == 'error', 'сбой запуска контроллера — исход error, исключения наружу нет')
    n0 = len(calls)
    ok(RT.begin(JID, 'py3', log=log, runner=runner, spool=os.path.join(TMP, 'sp2'), rules={'tour': {'enabled': 0}}) is None and len(calls) == n0 and not os.path.exists(os.path.join(TMP, 'sp2')),
       'enabled: 0 — крючок выключен: ни метки, ни запуска')
    ok(RT.begin('bad id', 'py3', log=log, runner=runner, spool=sp, rules={}) is None, 'странный номер задания — крючок молчит')
    RT.begin(JID2, 'py3', log=log, runner=runner, spool=sp, rules={'tour': {'on_claim': 0}})
    ok(os.path.exists(os.path.join(sp, f'{JID2}.active')) and len(calls) == n0, 'on_claim: 0 — метка есть, машину не включаем')

    # ——— ②/③ принятая версия → файл запроса; конец → метка снята
    ok(RT.publish(JID, b'{"a":1}', 'v2-living', log=log, spool=sp, rules={}) and os.path.exists(os.path.join(sp, f'{JID}.req.json')), 'версия принята — запрос и данные лежат в папке обмена')
    ok(not RT.publish(JID, b'{}', 'v2', log=log, spool=sp, rules={'tour': {'warm': 0}}), 'warm: 0 — рендеры тура не ставим')
    RT.finish(JID, sp)
    ok(not os.path.exists(os.path.join(sp, f'{JID}.active')), 'воркер закончил — метка снята')

    # ——— сервис: версия 2 (гостиная) → рендеры гостиной; версия 3 → спальня
    st, ex, q, m, tw, spool = build()
    p = put_bundle(spool, JID, tour_data(False))
    r = tw.ingest(JID, p, 1800, 80)
    ok(r['variants'] == 2 and r['queued'] == 2 and r['state'] == 'ok', f'v2: фото можно только гостиной — два стиля в очереди: {r}')
    jobs = [j for j in st.jobs.values() if j.get('warm')]
    ok(len(jobs) == 2 and all(j['wprio'] == 1 and j['tour'] == f'tour:{JID}' and j['expires'] > time.time() + 1700 for j in jobs), 'заготовки: класс тура, метка тура, срок жизни 30 мин')
    p = put_bundle(spool, JID, tour_data(True), f'{JID}.2.bundle.json')
    r = tw.ingest(JID, p, 1800, 80)
    ok(r['variants'] == 5 and r['queued'] == 3 and r['have'] == 2, f'v3: добавились три стиля спальни, гостиная — без дублей: {r}')
    r = tw.ingest(JID, p, 1800, 80)
    ok(r['queued'] == 0 and r['have'] == 5, 'тот же запрос второй раз — дублей нет')
    ex.up = True
    ok(wait_for(lambda: q.warm_counts() == {'queued': 0, 'running': 0}, 8) and sum(1 for j in st.jobs.values() if j.get('status') == 'done') == 5, 'машина прогрета — все пять посчитаны')
    r = tw.ingest(JID, p, 1800, 80)
    ok(r['have'] == 5 and r['queued'] == 0, 'уже в кэше — не ставим')
    key = RX.frame_key_of(RS.canonicalize(tour_data(True), {'v': RS.SNAPSHOT_VERSION, 'variant_id': 'set1'}, 'trial'), {'preset': 3})
    ok(st.cached(key) is not None, 'кадры лежат под ключом `frame_key_of` — тем же, что спросит страница')
    q.close()

    # R6 (T-20261118-22/3): порядок постановки — по кругам комнат; набор кадров и число — те же; отказ одной комнаты остальных не валит
    def multi(bad=None):
        rooms = [('living', 2), ('bedroom-1', 3), ('bedroom-2', 3), ('bedroom-3', 2)]
        d = {'apartment_id': 'a1', 'build': 'b1', 'room': {'w': 439, 'd': 325}, 'rules': {'soft_roles': ['плед']},
             'rooms_geo': {r: {'w': 380, 'd': 300} for r, _ in rooms}, 'apartment_rooms': [{'id': r, 'photo_ok': True} for r, _ in rooms], 'variants': []}
        for r, n in rooms:
            for i in range(n):
                v = variant(f'{r}-{i}', r, f's{i}', f'{r}{i}')
                if bad == v['id']:
                    v['items'][0]['sku'] = {'sid': 'x', 'msid': 'x', 'name': 'без размеров'}      # снимок не принят: нет размеров
                    v['items'][0].pop('w'), v['items'][0].pop('d')
                d['variants'].append(v)
        return d

    def order_of(st, q, snaps):
        ids = {RX.frame_key_of(s, {'preset': 3}): lb.rsplit('/', 1)[-1] for lb, s in snaps}
        return [ids[st.jobs[j]['key']] for j in q._order()]
    st, ex, q, m, tw, spool = build()
    data = multi()
    flat = RT.eligible_snaps(data, f'tour:{JID}', log)
    r = tw.ingest(JID, put_bundle(spool, JID, data), 1800, 80)
    got = order_of(st, q, flat)
    ok(r['queued'] == 10 and r['variants'] == 10, f'R6: поставлено столько же кадров, сколько вариантов (10): {r}')
    ok(got == ['living-0', 'bedroom-1-0', 'bedroom-2-0', 'bedroom-3-0', 'living-1', 'bedroom-1-1', 'bedroom-2-1', 'bedroom-3-1', 'bedroom-1-2', 'bedroom-2-2'], f'R6: первый кадр каждой комнаты — первыми, потом вторые и так далее: {got}')
    ok(sorted(got) == sorted(lb.rsplit('/', 1)[-1] for lb, _ in flat), 'R6: набор кадров тот же, что при порядке «комната за комнатой» (деньги не растут)')
    ok([lb for lb, _ in RT.by_rounds(flat)][:2] == [flat[0][0], flat[2][0]] and RT.by_rounds([]) == [], 'by_rounds: комнаты в порядке данных; пусто — пусто')
    q.close()
    st, ex, q, m, tw, spool = build()
    data = multi(bad='bedroom-2-0')
    r = tw.ingest(JID, put_bundle(spool, JID, data), 1800, 80)
    left = {RX.frame_key_of(s, {'preset': 3}): lb.rsplit('/', 1)[-1] for lb, s in RT.eligible_snaps(data, f'tour:{JID}', log)}
    got = [left[st.jobs[j]['key']] for j in q._order()]
    ok(r['queued'] == 9 and 'bedroom-2-0' not in got and got[:3] == ['living-0', 'bedroom-1-0', 'bedroom-2-1'] and 'bedroom-3-0' in got,
       f'R6: у одного варианта снимок не принят — остальные комнаты и кадры стоят, у комнаты следующий вариант идёт первым: {got}')
    q.close()

    # потолок дня — не ставим, машина выключена
    st, ex, q, m, tw, spool = build()
    m.spent = 3.2
    r = tw.ingest(JID, put_bundle(spool, JID, tour_data(True)), 1800, 80)
    ok(r['state'] == 'cap' and r['queued'] == 0 and not [j for j in st.jobs.values() if j.get('warm')] and any('потолок' in x for x in LOG), 'потолок дня исчерпан — заготовки не ставим, строка в журнале')
    m.desired = 'on'
    r = tw.ingest(JID, put_bundle(spool, JID, tour_data(True)), 1800, 80)
    ok(r['state'] == 'ok' and r['queued'] == 5, 'машина включена (даже при исчерпанном потолке: её уже платят) — ставим')
    q.close()

    # срок жизни: не дождалась машины — снимается с журналом
    st, ex, q, m, tw, spool = build()
    tw.ingest(JID, put_bundle(spool, JID, tour_data(True)), 0.05, 80)
    time.sleep(0.12)
    n = q.expire_warm()
    ok(n == 5 and q.warm_counts() == {'queued': 0, 'running': 0}, f'срок 30 мин (здесь 0,05 с) вышел — {n} заготовок сняты')
    st.jobs  # noqa: B018
    q.close()

    # порядок: заготовка тура — раньше заготовки витрины, заказ человека — раньше всех
    st, ex, q, m, tw, spool = build()
    a = q.submit({'scene_hash': 'demo1', 'variant': {}}, 'kdemo1', tour='demo:1', warm=True)
    tw.ingest(JID, put_bundle(spool, JID, tour_data(False)), 1800, 80)
    h = q.submit({'scene_hash': 'human1', 'variant': {}}, 'khuman1', ip='9.9.9.9')
    order = q._order()
    ok(order[0] == h['job'] and order[-1] == a['job'] and len(order) == 4, f'очередь: человек, затем тур (2), затем витрина: {[st.jobs[x].get("tour") for x in order]}')
    q.close()

    # ——— запросы воркера файлами: проход потока
    st, ex, q, m, tw, spool = build()
    ex.up = True
    RT.publish(JID, json.dumps(tour_data(False)).encode(), 'v2-living', log=log, spool=spool, rules={})
    out = tw.once()
    ok(out['ingested'] and out['ingested'][0]['queued'] == 2 and not tw.pending() and not [n for n in os.listdir(spool) if n.endswith('.bundle.json')], f'проход: запрос забран и поставлен, файлы убраны: {os.listdir(spool)}')
    RT.publish(JID, json.dumps(tour_data(True)).encode(), 'v3-bedrooms', log=log, spool=spool, rules={})
    out = tw.once()
    ok(out['ingested'][0]['variants'] == 5, 'следующая версия — следующий запрос')
    # запрос с чужим путём — не читаем
    json.dump({'jid': JID, 'bundle': '../../etc/passwd', 'ts': 1}, open(os.path.join(spool, f'{JID}.req.json'), 'w'))
    ok(tw.take(f'{JID}.req.json') is None and any('неверным' in x for x in LOG), 'запрос с путём вне папки обмена — отказ со строкой')
    q.close()

    # ——— ③ выключение машины, включённой туром
    def fresh(by, active=False, queued=False, human=False, recent=False):
        st, ex, q, m, tw, spool = build()
        m.desired, m.by, m.last_activity = 'on', by, time.time() - (5 if recent else 600)
        if active:
            RT._mark(JID, spool)
        if queued:
            q.submit({'scene_hash': 'x', 'variant': {}}, 'kx', tour='tour:x', warm=True)
        if human:
            st.jobs['hh'] = {'status': 'running', 'ts': time.time(), 'key': 'kk'}
        return st, q, m, tw

    st, q, m, tw = fresh('tour-AbCdEfGh')
    ok(tw.maybe_off({'off_idle_s': 60, 'active_stale_s': 2400}) and m.off_calls == ['tour-warm'], 'машину включил тур, дела нет, людей нет — выключена сразу')
    q.close()
    for name, kw, by in (('метка «тур идёт» (воркер ещё считает следующую версию)', {'active': True}, 'tour-AbCdEfGh'), ('в очереди есть заготовка', {'queued': True}, 'tour-AbCdEfGh'),
                         ('людям нужна (заказ в работе)', {'human': True}, 'tour-AbCdEfGh'), ('последнее дело только что (окно простоя)', {'recent': True}, 'tour-AbCdEfGh'),
                         ('включила заготовка витрины — не наша', {}, 'prewarm'), ('включил заказ человека — не наша', {}, 'order')):
        st, q, m, tw = fresh(by, **kw)
        ok(tw.maybe_off({'off_idle_s': 60, 'active_stale_s': 2400}) == '' and not m.off_calls, f'не выключаем: {name}')
        q.close()
    st, q, m, tw = fresh('tour-AbCdEfGh', active=True)
    os.utime(os.path.join(tw.spool, f'{JID}.active'), (time.time() - 5000, time.time() - 5000))
    ok(tw.maybe_off({'off_idle_s': 60, 'active_stale_s': 2400}) and m.off_calls, 'метка старше срока (воркер упал) — не держит машину включённой')
    q.close()
    st, q, m, tw = fresh('tour-AbCdEfGh')
    ok(tw.maybe_off({'off_idle_s': 0}) == '' and not m.off_calls, 'off_idle_s: 0 — не выключать')
    q.close()

    # ——— запасной путь: последняя версия задания в папках воркера
    root = os.path.join(TMP, 'trialroot')
    for jid, files in ((JID, ('a0-100000/bundle-1-v1-walls.json', 'a0-100000/bundle-2-v2-living.json', 'a0-100000/bundle-3-v3-bedrooms.json')), (JID2, ('a0-090000/bundle-1-v1-walls.json',))):
        for f in files:
            os.makedirs(os.path.join(root, jid, os.path.dirname(f)), exist_ok=True)
            json.dump(tour_data(True), open(os.path.join(root, jid, f), 'w'))
    os.makedirs(os.path.join(root, 'cards'), exist_ok=True)
    got = RT.recent_job_bundles(root, 3600, 5)
    ok(len(got) == 2 and all(lb.startswith('tour:') for lb, _ in got) and any(p.endswith('bundle-3-v3-bedrooms.json') for _, p in got), f'запасной путь: по заданию — версия с наибольшим номером: {[os.path.basename(p) for _, p in got]}')
    ok(RT.recent_job_bundles(root, 0.0001, 5) == [] and RT.recent_job_bundles(os.path.join(TMP, 'нет'), 3600, 5) == [], 'старые и нет папки — пусто')
    sn = RT.eligible_snaps(tour_data(False), 'tour:x', log)
    ok([lb for lb, _ in sn] == ['tour:x/set1', 'tour:x/set2'], 'снимки — только комнат, где фото можно')

    # ——— заготовка витрины: ключ — общий путь `frame_key_of` (не `cache_key` руками)
    st, ex, q, m, tw, spool = build()
    sn = RT.eligible_snaps(tour_data(True), 'tour:x', log)
    pw = PW.Prewarmer(q, ex, {'preset': 3}, m, lambda s: {}, scenes_fn=lambda pw: sn, log=log)
    miss = pw.missing(sn, {'fail_max': 2})
    ok(len(miss) == 5 and all(k == RX.frame_key_of(s, {'preset': 3}) for _, s, k in miss), 'заготовка витрины берёт ключ через `frame_key_of`')
    bad = [(lb, dict(s, frame_inputs={'missing': ['x']})) for lb, s in sn[:1]]
    ok(PW.Prewarmer(q, ex, {'space': 'room-frame/v2', 'preset': 3}, m, lambda s: {}, scenes_fn=lambda pw: bad, log=log).missing(bad, {'fail_max': 2}) == [], 'ключ v2: сцене не хватает файла — комната пропускается, проход не падает')
    q.close()
finally:
    pass

print('\n' + ('ВСЁ ЧИСТО' if not BAD else f'ПРОВАЛЕНО: {len(BAD)}'))
for b in BAD:
    print(' -', b)
sys.exit(1 if BAD else 0)

"""Тесты контроллера машины рендера (T-20261117-24/1): чистый plan() + команды on/off/status на подмене Salad. Без сети.
Запуск: python3 tools/scout/render_gpu/tests_render_machine.py   (код 0 — чисто)"""
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ['RENDER_MACHINE_DIR'] = tempfile.mkdtemp(prefix='rm-test-')
os.environ['RENDER_MACHINE_DRY'] = '1'
import render_machine as RM  # noqa: E402

BAD = []


def ok(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        BAD.append(name)


R = dict(RM.DEFAULT_RULES, image='ghcr.io/x/y@sha256:aaa')
T0 = 1_800_000_000.0
PRICE = 0.17


def st(**kw):
    s = RM.new_state()
    s.update(kw)
    return s


def obs(status, ready=None, price=PRICE):
    return {'status': status, 'running': 1 if status == 'running' else 0, 'ready': ready, 'price': price, 'exists': status is not None}


def ready_at(ts, flag=True):
    return {'ts': ts, 'ready': flag, 'device': 'CUDA'}


def on_state(now, **kw):
    d = dict(desired='on', gen=1, on_at=now - 300, last_activity=now - 300, accrued_ts=now - 60, spent_date=RM.london_date(now))
    d.update(kw)
    return st(**d)


def keys(acts):
    return [a[0] if a[0] != 'notify' else 'notify:' + a[1] for a in acts if a[0] != 'say']      # строки журнала ('say') в проверках действий не считаем


# ── желаемое «выключено» ──
s, a = RM.plan(st(), obs('stopped'), R, T0)
ok('выключено и остановлена — ничего', a == [])
s, a = RM.plan(st(), obs('running'), R, T0)
ok('выключено, а группа жива (мимо контроллера) — гасим', keys(a) == ['stop'])

# ── включается, ещё не готова ──
s, a = RM.plan(on_state(T0), obs('deploying'), R, T0)
ok('deploying без ready — ждём, сообщений нет', a == [])
s, a = RM.plan(on_state(T0), obs('pending'), R, T0)
ok('pending (группа создаётся) — ждём, не стартуем', a == [])

# ── прогрелась: одно сообщение за запуск ──
s1, a = RM.plan(on_state(T0), obs('running', ready_at(T0 - 10)), R, T0)
ok('running + свежий ready → «прогрелась» одно', keys(a) == ['notify:warm'] and s1['warm_gen'] == 1)
s2, a = RM.plan(s1, obs('running', ready_at(T0 + 50)), R, T0 + 60)
ok('следующая отметка — повторного «прогрелась» нет', a == [])
s3, a = RM.plan(on_state(T0), obs('running', ready_at(T0 - 500)), R, T0)
ok('ready.json старый (>120 с) — не прогрелась', a == [] and s3['warm_gen'] == 0)
s3, a = RM.plan(on_state(T0), obs('running', ready_at(T0 - 10, False)), R, T0)
ok('ready:false (GPU не поднялся) — не прогрелась', a == [] and s3['warm_gen'] == 0)
s3, a = RM.plan(on_state(T0), obs('running', ready_at(T0 - 400)), R, T0)
ok('ready.json от ПРОШЛОГО запуска (старше on_at) — не прогрелась', a == [] and s3['warm_gen'] == 0)

# ── деградация: одно сообщение на эпизод, потом стоп ──
w = dict(s1)
sd, a = RM.plan(w, obs('running', ready_at(T0 - 500)), R, T0 + 100)
ok('была готова, отметка пропала — «деградация» одно', keys(a) == ['notify:degraded'] and sd['degraded_since'])
sd2, a = RM.plan(sd, obs('running', ready_at(T0 - 500)), R, T0 + 200)
ok('дальше — без повтора (нет спама)', a == [])
sd3, a = RM.plan(sd2, obs('running', ready_at(T0 - 500)), R, T0 + 100 + R['degraded_stop_min'] * 60 + 1)
ok('не ожила за degraded_stop_min — стоп + одно сообщение', keys(a) == ['stop', 'notify:recovered_stop'] and sd3['desired'] == 'off')
sr, a = RM.plan(sd, obs('running', ready_at(T0 + 150)), R, T0 + 160)
ok('ожила — деградация снята без сообщения', a == [] and sr['degraded_since'] == 0)

# ── автостоп по простою ──
idle = dict(s1, last_activity=T0 - 25 * 60, on_at=T0 - 25 * 60)
si, a = RM.plan(idle, obs('running', ready_at(T0 + 50)), R, T0 + 60)
ok('простой > 20 мин — стоп и сообщение', keys(a) == ['stop', 'notify:stop_idle'] and si['desired'] == 'off')
busy = dict(s1, last_activity=T0 + 30)
_, a = RM.plan(busy, obs('running', ready_at(T0 + 50)), R, T0 + 60)
ok('работа была недавно (pulse) — не гасим', a == [])
_, a = RM.plan(on_state(T0, last_activity=T0 - 30 * 60, on_at=T0 - 30 * 60), obs('deploying'), R, T0)
ok('простой считаем только у прогретой — прогревающуюся гасит лимит прогрева, не простой',
   'notify:stop_idle' not in keys(a) and 'notify:stop_warmup' in keys(a))

# автостоп — от ПОСЛЕДНЕГО события: и заказ (pulse при постановке), и готовая пара (pulse в конце) сдвигают отсчёт
IDLE = R['idle_stop_min'] * 60
ev = dict(s1, last_activity=T0, on_at=T0 - 3600)
_, a = RM.plan(ev, obs('running', ready_at(T0 + IDLE - 10)), R, T0 + IDLE - 5)
ok('19:55 после последнего события — ещё не гасим', a == [])
_, a = RM.plan(ev, obs('running', ready_at(T0 + IDLE + 10)), R, T0 + IDLE + 5)
ok('20:05 после последнего события — гасим (автостоп)', 'stop' in keys(a))
# заказ в очередь в 15-й минуте простоя (pulse) — отсчёт заново
order = dict(ev, last_activity=T0 + 15 * 60)
_, a = RM.plan(order, obs('running', ready_at(T0 + IDLE + 10)), R, T0 + IDLE + 5)
ok('заказ на 15-й минуте простоя сдвинул отсчёт: на 20-й минуте от прошлого события не гасим', a == [])
_, a = RM.plan(order, obs('running', ready_at(T0 + 15 * 60 + IDLE + 10)), R, T0 + 15 * 60 + IDLE + 5)
ok('…а через 20 мин от заказа — гасим', 'stop' in keys(a))
# пока задание в очереди/в работе — не гасим никогда (busy_until, пока исполнитель ждёт пару), только потолки
long_job = dict(ev, last_activity=T0, busy_until=T0 + 3 * IDLE)
_, a = RM.plan(long_job, obs('running', ready_at(T0 + 2 * IDLE + 10)), R, T0 + 2 * IDLE)
ok('задание в работе (busy_until впереди) — простой не гасит даже через 40 мин', a == [])
_, a = RM.plan(dict(long_job, spent_usd=2.0, spent_date=RM.london_date(T0 + 2 * IDLE), accrued_ts=T0 + 2 * IDLE - 5), obs('running', ready_at(T0 + 2 * IDLE + 10)), R, T0 + 2 * IDLE)
ok('…но дневной потолок гасит и занятую', keys(a) == ['stop', 'notify:stop_cap'])
_, a = RM.plan(dict(long_job, running_since=T0 - 241 * 60), obs('running', ready_at(T0 + 2 * IDLE + 10)), R, T0 + 2 * IDLE)
ok('…и предел 4 ч гасит занятую', keys(a) == ['stop', 'notify:stop_maxrun'])
_, a = RM.plan(dict(ev, busy_until=T0 + 100), obs('running', ready_at(T0 + IDLE + 10)), R, T0 + IDLE + 5)
ok('метка занятости истекла (исполнитель умер) — простой снова считается и гасит', 'stop' in keys(a))
# pulse(): заказ ставит и «занято», конец пары снимает его и обновляет последнее событие
with RM.Box() as b0:
    b0.state.update(desired='on', gen=1)
    b0.save()
RM.pulse(busy_s=90, now=T0)
with RM.Box() as b0:
    ok('pulse --busy: последнее событие и busy_until', b0.state['last_activity'] == T0 and b0.state['busy_until'] == T0 + 90)
RM.pulse(now=T0 + 40)
with RM.Box() as b0:
    ok('pulse (конец пары): busy снят, отсчёт простоя с этого момента', b0.state['last_activity'] == T0 + 40 and b0.state['busy_until'] == 0)
    b0.state.update(desired='off')
    b0.save()

# ── прогрев ──
sw, a = RM.plan(on_state(T0, on_at=T0 - 16 * 60), obs('running', None), R, T0)
ok('не прогрелась за 15 мин — стоп + сообщение', keys(a) == ['stop', 'notify:stop_warmup'])

# ── максимум непрерывной работы ──
sm = dict(s1, running_since=T0 - 241 * 60, last_activity=T0 + 50)
sm2, a = RM.plan(sm, obs('running', ready_at(T0 + 50)), R, T0 + 60)
ok('4 ч подряд — стоп', keys(a) == ['stop', 'notify:stop_maxrun'])

# ── дневной потолок ──
sc = dict(s1, spent_usd=2.0, spent_date=RM.london_date(T0 + 60), accrued_ts=T0)
sc2, a = RM.plan(sc, obs('running', ready_at(T0 + 50)), R, T0 + 60)
ok('потолок $2 — стоп + сообщение', keys(a) == ['stop', 'notify:stop_cap'])
sa = st(desired='on', gen=1, on_at=T0 - 100, accrued_ts=T0 - 60, spent_date=RM.london_date(T0), spent_usd=1.0)
sa2, _ = RM.plan(sa, obs('running', ready_at(T0)), R, T0)
ok('расход копится по цене класса: 60 с × $0,17/ч', abs(sa2['spent_usd'] - (1.0 + 60 / 3600 * PRICE)) < 1e-4)
sa3, _ = RM.plan(dict(sa, accrued_ts=T0 - 3600), obs('running', ready_at(T0)), R, T0)
ok('пропуск между отметками не раздувает счёт (не больше 10 мин за шаг)', abs(sa3['spent_usd'] - (1.0 + 600 / 3600 * PRICE)) < 1e-4)
sn, _ = RM.plan(dict(sa, spent_date='2020-01-01', spent_usd=1.9), obs('stopped'), R, T0)
ok('новые сутки по Лондону — счёт с нуля', sn['spent_date'] == RM.london_date(T0) and sn['spent_usd'] == 0.0)
sx, _ = RM.plan(dict(sa), obs('stopped'), R, T0)
ok('остановленная не копит расход', sx['spent_usd'] == 1.0 and sx['accrued_ts'] == 0)

# ── потеря машины ──
base = dict(on_state(T0), running_since=T0 - 200, warm_gen=1, last_activity=T0)
sl, a = RM.plan(base, obs('stopped'), R, T0)
ok('пропала — сообщение «пропала» и перезапуск', keys(a) == ['notify:lost', 'start'] and sl['restarts'] == 1)
sl2, a = RM.plan(dict(sl, restarts=2, last_start_try=T0 - 100), obs('stopped'), R, T0)
ok('после restart_max попыток — отказ, стоп, одно сообщение', keys(a) == ['stop', 'notify:gave_up'] and sl2['desired'] == 'off')
sj, a = RM.plan(on_state(T0, last_start_try=T0 - 100), obs('stopped'), R, T0)
ok('создана, но не стартовала (running ни разу) — просто /start, без «пропала»', keys(a) == ['start'] and sj['restarts'] == 0)
sj2, a = RM.plan(dict(sj, last_start_try=T0 - 5), obs('stopped'), R, T0)
ok('повтор /start не чаще start_retry_s', a == [])
_, a = RM.plan(on_state(T0, last_start_try=T0 - 100), obs(None), R, T0)
ok('группы ещё нет — create/start от исполнителя', keys(a) == ['start'])


# ── T-24/10: «прогрелась» — после горячего списка; проба узла: медленный узел ──
def ready_hot(ts, done, note='PROBE_SEC 0.6; PROBE_OK CUDA', extra=None):
    d = {'ts': ts, 'ready': True, 'device': 'CUDA', 'note': note}
    if done is not None:
        d['hot'] = {'done': done}
    if extra:
        d.update(extra)
    return d


sh1, a = RM.plan(on_state(T0), obs('running', ready_hot(T0 - 10, False)), R, T0)
ok('подогрев не пройден — «прогрелась» не объявлена, заказы на запасном пути (warm_gen 0, ready_since записан)', keys(a) == [] and sh1['warm_gen'] == 0 and sh1['ready_since'] == T0)
sh2, a = RM.plan(sh1, obs('running', ready_hot(T0 + 20, True)), R, T0 + 30)
ok('подогрев пройден — «прогрелась»', keys(a) == ['notify:warm'] and sh2['warm_gen'] == 1)
sh3, a = RM.plan(sh1, obs('running', ready_hot(T0 + R['hot_wait_max_min'] * 60, False)), R, T0 + R['hot_wait_max_min'] * 60 + 5)
ok('подогрев не кончился за hot_wait_max_min — «прогрелась» всё равно (заказы не ждут вечно)', keys(a) == ['notify:warm'] and sh3['warm_gen'] == 1)
sh4, a = RM.plan(on_state(T0), obs('running', ready_hot(T0 - 10, None)), R, T0)
ok('в ready.json нет поля hot (образ без T-24/10) — как раньше, сразу «прогрелась»', keys(a) == ['notify:warm'] and sh4['warm_gen'] == 1)
sh5, a = RM.plan(on_state(T0, on_at=T0 - R['warmup_max_min'] * 60 - 30), obs('running', ready_hot(T0 - 10, False)), R, T0)
ok('машина готова, ждёт подогрев, а с включения >warmup_max_min — не гасим по «прогрев не вышел»', 'stop' not in keys(a))
_, a = RM.plan(on_state(T0, on_at=T0 - R['warmup_max_min'] * 60 - 30), obs('running', None), R, T0)
ok('машина не готова за warmup_max_min — гасим как раньше', 'stop' in keys(a))
ss, a = RM.plan(on_state(T0), obs('running', ready_hot(T0 - 10, True, note='PROBE_SEC 1.9; PROBE_OK CUDA')), R, T0)
ok('проба 1,9 с (порог 1,2) — узел медленный: в состоянии и в журнале', ss['slow'] is True and ss['probe_sec'] == 1.9 and any(x[0] == 'say' and 'МЕДЛЕННЫЙ' in x[1] for x in a))
sf, a = RM.plan(on_state(T0), obs('running', ready_hot(T0 - 10, True, note='PROBE_SEC 0.6; PROBE_OK CUDA')), R, T0)
ok('проба 0,6 с — норма, строка журнала «норма»', sf['slow'] is False and sf['probe_sec'] == 0.6 and any(x[0] == 'say' and 'норма' in x[1] for x in a))
sn, a = RM.plan(on_state(T0), obs('running', ready_hot(T0 - 10, True, note='без пробы')), R, T0)
ok('в note нет PROBE_SEC — не медленный и не падаем', sn['slow'] is False and sn['probe_sec'] is None)
rc_ = ready_hot(T0 - 10, True)
sj, _ = RM.plan(on_state(T0), obs('running', {**rc_, 'caps': {'frames': ['png', 'jpg']}}), R, T0)
ok('T-24/11: ready.json caps.frames → state.frames (исполнитель шлёт jpg только такой машине)', sj['frames'] == ['png', 'jpg'])
sj0, _ = RM.plan(on_state(T0), obs('running', rc_), R, T0)
ok('T-24/11: нет поля caps (образ до T-24/11) — frames = [png]', sj0['frames'] == ['png'])
ok('T-24/11: caps_frames: мусор и неизвестные форматы отбрасываются, пустое = [png]', RM.caps_frames({'caps': {'frames': ['gif', 'jpg']}}) == ['jpg'] and RM.caps_frames({'caps': {'frames': 'jpg'}}) == ['png']
   and RM.caps_frames({'caps': 5}) == ['png'] and RM.caps_frames({'caps': {'frames': []}}) == ['png'])
ok('probe_sec_of / hot_pending: разбор', RM.probe_sec_of({'note': 'PROBE_SEC 12.5; X'}) == 12.5 and RM.probe_sec_of({}) is None and RM.hot_pending({'hot': {'done': False}}) and not RM.hot_pending({}) and not RM.hot_pending({'hot': {'done': True}}))

# ── сообщение о стопе — одно на запуск ──
s_, a = RM.plan(dict(sc, stop_notified_gen=1), obs('running', ready_at(T0 + 50)), R, T0 + 60)
ok('о стопе по запуску уже писали — второго нет', 'notify:stop_cap' not in keys(a) and 'stop' in keys(a))

# ── надписи: у каждой пара RU/EN, форматируются ──
fill = dict(st='running', cap=2.0, spent=0.5, g='render-x1', why='x', age=5, left=3, min=15, n=1, max=2, p=1.9, thr=1.2, old='render-x0', new='render-x1')
ok('все надписи — пара RU/EN и форматируются', all(len(v) == 2 and RM.tr(k, 'ru', **fill) and RM.tr(k, 'en', **fill) for k, v in RM.T.items()))
ok('RU-надписи не пустые и без английского вместо русского', all(any('а' <= c.lower() <= 'я' for c in RM.tr(k, 'ru', **fill)) for k in RM.T))

# ── исполнитель: у каждого действия notify надпись форматируется (урок live-проверки: spent/cap дважды) ──
_sent = []
RM.alert = lambda rules, text: _sent.append(text) or True
_noop = types.SimpleNamespace(stop=lambda: 202, group=lambda: (None, 'stopped', {}))
for key in ('stop_idle', 'stop_cap', 'stop_maxrun', 'stop_warmup', 'recovered_stop', 'gave_up', 'lost', 'warm', 'degraded'):
    _kw = {'stop_idle': {'min': 20, 'spent': 0.4}, 'stop_cap': {'cap': 2.0, 'spent': 2.1}, 'stop_maxrun': {'min': 240}, 'stop_warmup': {'min': 15},
           'recovered_stop': {'min': 10}, 'gave_up': {'max': 2}, 'lost': {'st': 'stopped', 'n': 1, 'max': 2}, 'warm': {'min': 3},
           'degraded': {'why': 'x', 'min': 10}}[key]
    try:
        RM.execute(_noop, R, [('notify', key, _kw)], 'ru', 0.5)
    except Exception as e:  # noqa: BLE001
        ok(f'execute notify {key}', False)
        print('   ', type(e).__name__, e)
ok('execute: все надписи уведомлений уходят без ошибок', len(_sent) == 9)

# ── команды на подмене Salad ──


class FakeSalad:
    calls = []
    status = None            # None — группы нет
    image = None

    def __init__(self, rules):
        self.r = rules

    def group(self):
        if FakeSalad.status is None:
            return None, None, {}
        return {'container': {'image': FakeSalad.image}}, FakeSalad.status, {'running_count': 1 if FakeSalad.status == 'running' else 0}

    def running_count(self, cnt):
        return int(cnt.get('running_count', 0))

    def create(self, image):
        FakeSalad.calls.append('create')
        FakeSalad.status, FakeSalad.image = 'stopped', image

    def start(self):
        FakeSalad.calls.append('start')
        FakeSalad.status = 'deploying'
        return 202

    def stop(self):
        FakeSalad.calls.append('stop')
        FakeSalad.status = 'stopped'
        return 202


RM.Salad = FakeSalad
RM.read_ready = lambda rules: None
RM.beat_server = lambda rules, now: True
args = types.SimpleNamespace(busy=0.0, by='test', lang='ru', json=False)

out1 = RM.cmd_on(args, R)
ok('on: группы нет → создаёт и стартует', FakeSalad.calls[:1] == ['create'] and 'Включаю' in out1)
FakeSalad.status = 'deploying'
out2 = RM.cmd_on(args, R)
ok('повторный on — второй группы нет, повторного create/start нет', FakeSalad.calls.count('create') == 1 and 'уже включена' in out2)
n_start = FakeSalad.calls.count('start')
FakeSalad.status = 'running'
out3 = RM.cmd_on(args, R)
ok('on при running — ничего не перезапускает', FakeSalad.calls.count('start') == n_start and 'уже включена' in out3)
out4 = RM.cmd_status(args, R)
ok('status при running без ready — «включается»', 'включается' in out4)
RM.read_ready = lambda rules: ready_at(RM.time.time() + 1)
s_now = RM.Box().__enter__()
s_now.state['warm_gen'] = s_now.state['gen']
s_now.save()
s_now.__exit__()
out5 = RM.cmd_status(args, R)
ok('status прогрелась — строка про готовность и автостоп', 'прогрелась' in out5 and 'автостопа' in out5)
RM.read_ready = lambda rules: None
out6 = RM.cmd_off(args, R)
ok('off: гасит и подтверждает', FakeSalad.calls[-1] == 'stop' and 'выключена' in out6)
out7 = RM.cmd_off(args, R)
ok('повторный off — «уже выключена», без второго /stop', FakeSalad.calls.count('stop') == 1 and 'уже выключена' in out7)
tl_ = open(os.path.join(RM.STATE_DIR, 'tick.log'), encoding='utf-8').read()
ok('журнал tick.log: кто и где включил/выключил (T-20261118-20/5) — on/off by=, where=, родитель',
   tl_.count(' off by=') == 2 and tl_.count(' on by=') >= 3 and 'where=cmd_off' in tl_ and 'where=cmd_on' in tl_ and 'parent=[' in tl_ and f'by={args.by} ' in tl_)
out8 = RM.cmd_status(types.SimpleNamespace(by='t', lang='en', json=False), R)
ok('status по-английски', out8.startswith('Render machine is off'))
FakeSalad.status = 'running'      # желаемое «выключено», а группа на Salad ещё живёт (запущена мимо контроллера / остановка идёт)
out8b = RM.cmd_status(args, R)
ok('status при desired=off и работающей группе — не «не отвечает N мин», а «выключена по команде, ближайший tick погасит»', 'не отвечает' not in out8b and 'tick' in out8b and 'running' in out8b)
FakeSalad.status = 'stopped'
ok('status при desired=off и остановленной группе — «выключена»', 'выключена' in RM.cmd_status(args, R))
FakeSalad.image = 'ghcr.io/other@sha256:bbb'
FakeSalad.status = 'stopped'
out9 = RM.cmd_on(args, R)
ok('образ существующей группы не тот — отказ, не перезапуск и не пересоздание', 'другим образом' in out9 and 'start' not in FakeSalad.calls[-1:])
with RM.Box() as b:
    b.state.update(spent_date=RM.london_date(RM.time.time()), spent_usd=2.5, desired='off')
    b.save()
ok('on при исчерпанном потолке — отказ', 'потолок' in RM.cmd_on(args, R))
ok('pulse отвечает ok', RM.cmd_pulse(args, R) == 'ok')
# status: подогрев и медленный узел
FakeSalad.status = 'running'
RM.read_ready = lambda rules: ready_hot(RM.time.time() + 1, False)
with RM.Box() as b:
    b.state.update(desired='on', gen=9, on_at=RM.time.time() - 600, warm_gen=0, slow=True, probe_sec=1.9)
    b.save()
out_h = RM.cmd_status(args, R)
ok('status: готова, но подогрев идёт — строка про ассеты витрины и запасной CPU; медленный узел — предупреждение', 'подтягивает ассеты' in out_h and 'Узел медленный' in out_h and '1.9' in out_h)
with RM.Box() as b:
    b.state.update(warm_gen=9)
    b.save()
RM.read_ready = lambda rules: ready_hot(RM.time.time() + 1, True)
out_r = RM.cmd_status(args, R)
ok('status: прогрелась на медленном узле — предупреждение тоже', 'прогрелась' in out_r and 'Узел медленный' in out_r)
import json as _j
ok('status --json: probe_sec и slow', _j.loads(RM.cmd_status(types.SimpleNamespace(by='t', lang='ru', json=True), R)).get('slow') is True)

# ── СМЕНА ГРУППЫ В ПРАВИЛАХ (T-20261118-09/6): прежняя группа гасится, потом ведётся новая ──
class MultiSalad:
    groups = {}              # имя → статус
    log = []

    def __init__(self, rules):
        self.r = rules

    def group(self):
        n = self.r['group']
        st_ = MultiSalad.groups.get(n)
        if st_ is None:
            return None, None, {}
        return {'container': {'image': self.r['image']}}, st_, {'running_count': 1 if st_ == 'running' else 0}

    def running_count(self, cnt):
        return int(cnt.get('running_count', 0))

    def create(self, image):
        MultiSalad.log.append(('create', self.r['group']))
        MultiSalad.groups[self.r['group']] = 'stopped'

    def start(self):
        MultiSalad.log.append(('start', self.r['group']))
        MultiSalad.groups[self.r['group']] = 'deploying'
        return 202

    def stop(self):
        MultiSalad.log.append(('stop', self.r['group']))
        MultiSalad.groups[self.r['group']] = 'stopped'
        return 202


RM.Salad = MultiSalad
RM.time.sleep = lambda x: None
RM.read_ready = lambda rules: None
R7 = dict(R, group='render-4090m7')
R11 = dict(R, group='render-4090m11')
_real_time, _real_sleep = RM.time.time, RM.time.sleep
with RM.Box() as b:
    b.state = RM.new_state()
    b.state.update(desired='on', gen=4, on_at=T0 - 3000, group='render-4090m7', running_since=T0 - 2900, warm_gen=4, restarts=1)
    b.save()
MultiSalad.groups = {'render-4090m7': 'running', 'render-4090m11': 'stopped'}
MultiSalad.log = []
RM.time.time = lambda: T0
out_t = RM.cmd_tick(args, R11)
ok('смена группы: m7 running + правило m11 → СНАЧАЛА stop m7', MultiSalad.log[:1] == [('stop', 'render-4090m7')] and MultiSalad.groups['render-4090m7'] == 'stopped')
with RM.Box() as b:
    sw = dict(b.state)
ok('…состояние ведёт m11, новый запуск: gen+1, on_at сейчас, прогрев с нуля, restarts 0', sw['group'] == 'render-4090m11' and sw['gen'] == 5 and sw['on_at'] == T0 and sw['warm_gen'] == 0 and sw['restarts'] == 0 and sw['desired'] == 'on')
RM.time.time = lambda: T0 + 60
RM.cmd_tick(args, R11)
ok('…потом (через ≥20 с) start m11, m7 больше не трогали', ('start', 'render-4090m11') in MultiSalad.log and MultiSalad.log.index(('stop', 'render-4090m7')) < MultiSalad.log.index(('start', 'render-4090m11'))
   and MultiSalad.log.count(('stop', 'render-4090m7')) == 1)
# тот же тик без смены — ничего лишнего
n_log = len(MultiSalad.log)
MultiSalad.groups['render-4090m11'] = 'running'
RM.time.time = lambda: T0 + 120
RM.cmd_tick(args, R11)
ok('без смены правил — прежняя группа не трогается', not [x for x in MultiSalad.log[n_log:] if x[0] == 'stop'])
# прежняя уже остановлена — просто переходим без стопа
with RM.Box() as b:
    b.state.update(group='render-4090m7', desired='off')
    b.save()
MultiSalad.groups = {'render-4090m7': 'stopped', 'render-4090m11': 'stopped'}
MultiSalad.log = []
RM.cmd_tick(args, R11)
with RM.Box() as b:
    ok('прежняя уже остановлена — стопа нет, группа записана; выключенное остаётся выключенным', MultiSalad.log == [] and b.state['group'] == 'render-4090m11' and b.state['desired'] == 'off')
# состояние без группы (старое) — берём текущую, ничего не гасим
with RM.Box() as b:
    b.state['group'] = ''
    b.save()
MultiSalad.groups = {'render-4090m7': 'running', 'render-4090m11': 'stopped'}
MultiSalad.log = []
RM.cmd_tick(args, R11)
with RM.Box() as b:
    ok('старое состояние без группы — берём текущую из правил, чужое не гасим (не знаем)', MultiSalad.log == [] and b.state['group'] == 'render-4090m11')
# остановка не подтверждается — новую не ведём, повтор
class StuckSalad(MultiSalad):
    def stop(self):
        MultiSalad.log.append(('stop', self.r['group']))
        return 202


RM.Salad = StuckSalad
with RM.Box() as b:
    b.state.update(group='render-4090m7', desired='on', gen=7, on_at=T0 - 100)
    b.save()
MultiSalad.groups = {'render-4090m7': 'running', 'render-4090m11': 'stopped'}
MultiSalad.log = []
RM.time.time = lambda: T0 + 1000
_clock = [T0 + 1000]
RM.time.time = lambda: (_clock.__setitem__(0, _clock[0] + 100) or _clock[0])      # время идёт: стоп-проверка не бесконечна
out_s = RM.cmd_tick(args, R11)
with RM.Box() as b:
    ok('остановка прежней не подтвердилась — новую не включаем, группа в состоянии прежняя, повтор на следующей отметке',
       'повтор' in out_s and b.state['group'] == 'render-4090m7' and ('start', 'render-4090m11') not in MultiSalad.log)
RM.Salad = MultiSalad
# on при смене: гасит прежнюю, затем стартует новую
with RM.Box() as b:
    b.state.update(group='render-4090m7', desired='on', gen=9)
    b.save()
MultiSalad.groups = {'render-4090m7': 'running', 'render-4090m11': 'stopped'}
MultiSalad.log = []
RM.time.time = lambda: T0 + 5000
o_on = RM.cmd_on(args, R11)
ok('on при смене группы: stop m7 → start m11', MultiSalad.log[:2] == [('stop', 'render-4090m7'), ('start', 'render-4090m11')] and 'Включаю' in o_on)
# off гасит и прежнюю
with RM.Box() as b:
    b.state.update(group='render-4090m7')
    b.save()
MultiSalad.groups = {'render-4090m7': 'running', 'render-4090m11': 'deploying'}
MultiSalad.log = []
RM.cmd_off(args, R11)
ok('off при смене группы: гасит и прежнюю, и текущую', ('stop', 'render-4090m7') in MultiSalad.log and ('stop', 'render-4090m11') in MultiSalad.log)

# РАСХОД ПО ТЕМ, КТО ВКЛЮЧИЛ (T-20261118-20/12): `spent_by`, чтобы заготовка видела свои траты, а не общие
ok('by_class: prewarm/order/tour — как есть; tg-… и bot — бот; рабочие, cli, пусто — probe',
   [RM.by_class(x) for x in ('prewarm', 'order', 'tour', 'tour-1', 'tg-common', 'rabochiy-1', 'cli', '', None)] == ['prewarm', 'order', 'tour', 'tour', 'bot', 'probe', 'probe', 'probe', 'probe'])
sa = RM.new_state()
sa.update(by='prewarm', accrued_ts=1000.0, spent_date=RM.london_date(1000.0))
RM._acc(sa, 1000.0 + 360, True, 0.273)
ok('_acc: прирост идёт и в общий, и в spent_by[prewarm]', abs(sa['spent_usd'] - 0.0273) < 1e-4 and abs(sa['spent_by']['prewarm'] - 0.0273) < 1e-4 and list(sa['spent_by']) == ['prewarm'])
sa['by'] = 'order'
RM._acc(sa, 1000.0 + 720, True, 0.273)
ok('_acc: сменилась метка — прирост другого класса отдельно, сумма = общему', set(sa['spent_by']) == {'prewarm', 'order'} and abs(sum(sa['spent_by'].values()) - sa['spent_usd']) < 1e-4)
RM._acc(sa, 1000.0 + 730, False, 0.273)
ok('_acc: машина не платная — ничего не прибавилось', abs(sum(sa['spent_by'].values()) - sa['spent_usd']) < 1e-4 and sa['accrued_ts'] == 0)
so = RM.new_state()
del so['spent_by']                                    # состояние от прежней версии контроллера (поля нет)
so.update(by='probe', accrued_ts=2000.0, spent_date=RM.london_date(2000.0), spent_usd=1.0)
RM._acc(so, 2000.0 + 60, True, 0.273)
ok('_acc: у старого состояния без spent_by поле создаётся, общий счёт не теряется', so['spent_by'] == {'probe': so['spent_by']['probe']} and so['spent_usd'] > 1.0)
sn = RM.new_state()
sn.update(by='prewarm', accrued_ts=3000.0, spent_date='2000-01-01', spent_usd=1.5, spent_by={'prewarm': 0.5})
RM._acc(sn, 3000.0, True, 0.273)
ok('_acc: новые сутки по Лондону — и общий, и spent_by с нуля', sn['spent_usd'] == 0.0 and sn['spent_by'] == {})
# метка в путях включения: заготовка включила, нужна заказу/туру — расход дальше на них; фон не перехватывает чужое
RM.Salad = MultiSalad
with RM.Box() as b:
    b.state.update(group='render-4090m11', desired='on', by='prewarm', gen=3, on_at=T0, spent_date=RM.london_date(T0), spent_usd=0.0, spent_by={})
    b.save()
MultiSalad.groups = {'render-4090m11': 'running'}
RM.time.time = lambda: T0 + 30
RM.cmd_on(types.SimpleNamespace(busy=0.0, by='order', lang='ru', json=False), R11)
with RM.Box() as b:
    ok('on при уже включённой заготовкой: метка переходит к заказу', b.state['by'] == 'order' and b.state['desired'] == 'on')
RM.cmd_on(types.SimpleNamespace(busy=0.0, by='prewarm', lang='ru', json=False), R11)
with RM.Box() as b:
    ok('заготовка не забирает метку у заказа', b.state['by'] == 'order')
RM.cmd_on(types.SimpleNamespace(busy=0.0, by='tour', lang='ru', json=False), R11)
with RM.Box() as b:
    ok('чужая метка (не заготовка) не перехватывается тем, кто пришёл позже', b.state['by'] == 'order')
with RM.Box() as b:
    b.state.update(desired='off', by='prewarm')
    b.save()
MultiSalad.groups = {'render-4090m11': 'stopped'}
RM.cmd_on(types.SimpleNamespace(busy=0.0, by='tour', lang='ru', json=False), R11)
with RM.Box() as b:
    ok('свежий запуск: метка = того, кто включил (tour)', b.state['by'] == 'tour' and b.state['desired'] == 'on')
# --by везде: все места, зовущие `render_machine.py on|off`, передают метку (иначе расход уйдёт в probe/cli)
import re as _re
_scout = os.path.abspath(os.path.join(HERE, '..'))
_bad = []
for _f in ('render_exec.py', 'render_prewarm.py', 'render_jobs.py', 'draft_service.py'):
    _src = open(os.path.join(_scout, _f), encoding='utf-8').read()
    for _m in _re.finditer(r"'render_machine\.py'\)?,\s*'(on|off)'[^\n]*", _src):
        if "'--by'" not in _m.group(0):
            _bad.append(f'{_f}: {_m.group(0)[:60]}')
ok('все вызовы render_machine.py on/off в коде сервиса несут --by', _bad == [])
_calls = []
for _f in ('render_exec.py', 'render_prewarm.py', 'render_jobs.py'):
    _src = open(os.path.join(_scout, _f), encoding='utf-8').read()
    _calls += [(_f, _m.group(1)) for _m in _re.finditer(r"\.turn_on\(([^)]*)\)", _src)] + [(_f, _m.group(1)) for _m in _re.finditer(r"\.wake\(([^)]*)\)", _src)]
ok('turn_on/wake зовут с меткой («prewarm», «order», by) — без пустых вызовов', _calls and all(a.strip() for _, a in _calls))

RM.time.time, RM.time.sleep = _real_time, _real_sleep
print('итог:', 'чисто' if not BAD else f'ПРОВАЛЕНО {len(BAD)}: {BAD}')
sys.exit(1 if BAD else 0)

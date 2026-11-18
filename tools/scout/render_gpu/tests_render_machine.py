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
    return [a[0] if a[0] != 'notify' else 'notify:' + a[1] for a in acts]


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

# ── сообщение о стопе — одно на запуск ──
s_, a = RM.plan(dict(sc, stop_notified_gen=1), obs('running', ready_at(T0 + 50)), R, T0 + 60)
ok('о стопе по запуску уже писали — второго нет', 'notify:stop_cap' not in keys(a) and 'stop' in keys(a))

# ── надписи: у каждой пара RU/EN, форматируются ──
fill = dict(st='running', cap=2.0, spent=0.5, g='render-x1', why='x', age=5, left=3, min=15, n=1, max=2)
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
print('итог:', 'чисто' if not BAD else f'ПРОВАЛЕНО {len(BAD)}: {BAD}')
sys.exit(1 if BAD else 0)

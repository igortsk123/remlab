#!/usr/bin/env python3
"""Ворота предела живых машин Salad (`salad_ceiling.py`) и их подключение к `kit_driver` (T-20261124-58). БЕЗ сети, Salad и ключа: список групп и ответы подставные.

Проверяет: (а) 9 живых + создать 1 → можно; (б) 10 живых → отказ со строкой «живо N, предел 10»; (в) два параллельных создания при 9 живых → одно прошло, другое отказ (замок + резерв);
(г) API недоступен (503, обрыв, мусор) → отказ, а не «свободно»; свои тёплые группы В СЧЁТЕ; старт уже зарезервированной группы проходит; погашенная группа освобождает место;
резерв истекает по сроку; предел берётся из rules/loop5.json (одно правило); `kit_driver.api_retry` при отказе НЕ шлёт create, `create_and_start` возвращает причину salad_ceiling,
`stop_and_verify` снимает резерв; в тестовом процессе без явной папки ворота выключены (чужие тесты со своими подставными API не ломаются).
Запуск: python3 tools/scout/salad/tests_salad_ceiling.py
"""
import json
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.append(os.path.abspath(os.path.join(HERE, '..')))
import remlab_tmp  # noqa: E402  временное теста — на диске, папка убирается при выходе (test_tmp_hygiene)
remlab_tmp.use('tests_salad_ceiling')
import tempfile  # noqa: E402
import kit_driver as KD  # noqa: E402
import salad_ceiling as SC  # noqa: E402

FAILS = []


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


def grp(name, n=1, status='running'):
    return {'name': name, 'current_state': {'status': status, 'instance_status_counts': {'running_count': n}}}


class ListMG:
    """Подставной API групп: GET '' → список, GET '/имя' → группа, POST '' → создание (записывается), прочее → 202."""

    def __init__(self, items=None, list_code=200, list_exc=None, replicas=1):
        self.items, self.list_code, self.list_exc, self.replicas = list(items or []), list_code, list_exc, replicas
        self.calls = []

    def api(self, path, method='GET', body=None):
        self.calls.append((method, path))
        if method == 'GET' and path == '':
            if self.list_exc:
                raise self.list_exc
            return self.list_code, ({'items': self.items} if self.list_code == 200 else {'detail': 'Service Unavailable'})
        if method == 'GET':
            for x in self.items:
                if '/' + x['name'] == path:
                    return 200, {'replicas': self.replicas, **x}
            return 404, {}
        if method == 'POST' and path == '':
            self.items.append(grp((body or {}).get('name', '?'), 0, 'stopped'))      # создана и ждёт образ: stopped, 0 машин
            return 201, {}
        return 202, {}


def nine():
    return [grp(f'x{i}') for i in range(9)]


tmp = tempfile.mkdtemp(prefix='ceil-')
_n = [0]


def fresh():
    """Своя папка замка/резерва на каждый случай — случаи друг на друга не влияют."""
    _n[0] += 1
    d = os.path.join(tmp, f'c{_n[0]}')
    os.makedirs(d)
    return d


# ---- единое правило
rules = SC.load_rules()
ok(SC.ceiling(rules) == 10 and rules['salad_ceiling'] == 10, 'предел — salad_ceiling из rules/loop5.json (10), не число в коде')

# ---- (а) 9 живых + 1 → можно
d = fresh()
res, why = SC.admit(ListMG(nine()), 'new1', 1, d=d)
ok(res and 'будет 10 из 10' in why, f'(а) 9 живых + создать 1 → можно ({why})')

# ---- (б) 10 живых → отказ
d = fresh()
res, why = SC.admit(ListMG(nine() + [grp('x9')]), 'new1', 1, d=d)
ok((not res) and 'живо 10' in why and 'предел 10' in why and 'жди или останови свои' in why, f'(б) 10 живых → отказ со строкой ({why})')
ok(not os.path.exists(os.path.join(d, 'salad-ceiling-reserved.json')), '(б) отказ ничего не резервирует')
res, why = SC.admit(ListMG(nine()), 'new2', 2, d=fresh())
ok(not res, '(б) 9 живых + группа на 2 машины → отказ (считаем машины, не группы)')

# ---- (в) два параллельных создания при 9 живых
d = fresh()
out = []
gate = threading.Barrier(2)


def worker(name):
    mg = ListMG(nine())                               # у каждого свой «снимок»: оба видят 9 живых и «свободно»
    gate.wait()
    out.append((name, SC.admit(mg, name, 1, d=d)[0]))


ts = [threading.Thread(target=worker, args=(n,)) for n in ('pA', 'pB')]
[t.start() for t in ts]
[t.join() for t in ts]
ok(sorted(r for _, r in out) == [False, True], f'(в) параллельно при 9 живых: одно прошло, другое отказ — замок и резерв ({out})')
# много потоков сразу
d = fresh()
out = []
gate = threading.Barrier(8)
ts = [threading.Thread(target=worker, args=(f'p{i}',)) for i in range(8)]
[t.start() for t in ts]
[t.join() for t in ts]
ok(sum(1 for _, r in out if r) == 1, f'(в) 8 процессов в одно окно при 9 живых → ровно один ({sum(1 for _, r in out if r)})')
d = fresh()
out = []
gate = threading.Barrier(8)


def worker_empty(name):
    gate.wait()
    out.append((name, SC.admit(ListMG([]), name, 1, d=d)[0]))


ts = [threading.Thread(target=worker_empty, args=(f'e{i}',)) for i in range(12)]
gate = threading.Barrier(12)
[t.start() for t in ts]
[t.join() for t in ts]
ok(sum(1 for _, r in out if r) == 10, f'(в) 12 запросов по 1 машине при 0 живых → ровно 10 прошли, 2 отказ ({sum(1 for _, r in out if r)})')

# ---- (г) API недоступен → отказ, а не «свободно»
for label, mg in (('503', ListMG(list_code=503)), ('обрыв сети', ListMG(list_exc=OSError('connection reset'))), ('таймаут', ListMG(list_exc=TimeoutError('t')))):
    res, why = SC.admit(mg, 'new1', 1, d=fresh())
    ok((not res) and 'не прочитан' in why, f'(г) список групп: {label} → отказ ({why[:70]})')


class JunkMG(ListMG):
    def api(self, path, method='GET', body=None):
        return 200, {'detail': 'no items'} if path == '' else (404, {})


res, why = SC.admit(JunkMG(), 'new1', 1, d=fresh())
ok(not res, '(г) ответ 200 без списка → отказ')

# ---- свои тёплые в счёте; повторный старт той же группы
d = fresh()
mg = ListMG([grp('trial-stage-t1w')] + [grp(f'x{i}') for i in range(8)])      # 8 чужих + 1 своя тёплая = 9
res, why = SC.admit(mg, 'trial-stage-t2', 1, d=d)
ok(res, 'своя тёплая в счёте: 9 живых (в т.ч. своя) + 1 → 10, можно')
res, why = SC.admit(mg, 'trial-stage-t3', 1, d=d)
ok((not res) and 'предел 10' in why, f'своя тёплая в счёте: ещё одна группа сверх предела → отказ ({why[:60]})')
res, why = SC.admit(mg, 'trial-stage-t2', None, d=d)
ok(res, 'старт группы, уже зарезервированной на create (need из резерва), проходит — не считается дважды')
mg2 = ListMG([grp('trial-stage-t2', 1, 'pending')] + [grp(f'x{i}') for i in range(8)], replicas=1)
res, why = SC.admit(mg2, 'trial-stage-t2', None, d=fresh())
ok(res, 'старт тёплой группы без резерва: need из GET группы, её собственная машина не считается дважды')
mg3 = ListMG([grp('wg')] + [grp(f'x{i}') for i in range(9)], replicas=1)
ok(SC.admit(mg3, 'wg', None, d=fresh())[0], 'старт группы, уже среди 10 живых (её машина в счёте): не отказ, считаем только недостающее')
res, why = SC.admit(ListMG(nine() + [grp('s', 0, 'stopped')], replicas=3), 's', None, d=fresh())
ok(not res, 'старт остановленной группы на 3 реплики при 9 живых → отказ (need из GET)')

# ---- release и срок
d = fresh()
mg = ListMG(nine())
ok(SC.admit(mg, 'g1', 1, d=d)[0] and not SC.admit(mg, 'g2', 1, d=d)[0], 'резерв держит место под группу, которой Salad ещё не показывает')
ok(SC.release('g1', d=d) is True and SC.admit(mg, 'g2', 1, d=d)[0], 'release: погашенная группа освобождает место')
ok(SC.release('нет-такой', d=d) is False, 'release чужого/несуществующего имени — тихо False')
d = fresh()
t = [1000.0]
ok(SC.admit(ListMG(nine()), 'g1', 1, d=d, clock=lambda: t[0])[0], 'срок резерва: g1 занята')
t[0] += float(rules['salad_reserve_ttl_s']) + 1
ok(SC.admit(ListMG(nine()), 'g2', 1, d=d, clock=lambda: t[0])[0], 'срок резерва: через salad_reserve_ttl_s резерв забыт (группу не погасили)')

# ---- тестовый процесс без явной папки: ворота выключены (чужие тесты с подставным API не ломаются)
os.environ.pop('SALAD_CEILING_DIR', None)
res, why = SC.admit(ListMG(list_code=503), 'g', 1)
ok(res and 'выключены' in why, 'тестовый процесс без явной папки: ворота выключены (иначе тесты kit_driver с подставным API упали бы)')

# ---- kit_driver: подключение
os.environ['SALAD_CEILING_DIR'] = fresh()
lines = []
say = lambda *a: lines.append(' '.join(str(x) for x in a))  # noqa: E731
mg = ListMG(nine() + [grp('x9')])
code, resp, n = KD.api_retry(mg, '', 'POST', {'name': 'g', 'replicas': 1}, 'g', say, lambda s: None)
ok(code == KD.CEILING_REFUSED and resp.get('ceiling_refused') and ('POST', '') not in mg.calls, 'api_retry: при 10 живых create НЕ отправляется, код отказа ворот')
ok(any('предел 10' in s for s in lines), 'api_retry: причина отказа — в журнале («Salad: живо 10, предел 10 …»)')
mg = ListMG(nine())
code, resp, n = KD.api_retry(mg, '', 'POST', {'name': 'g', 'replicas': 1}, 'g', say, lambda s: None)
ok(code == 201 and ('POST', '') in mg.calls, 'api_retry: при 9 живых create уходит')
mg2 = ListMG(nine())
code, resp, n = KD.api_retry(mg2, '', 'POST', {'name': 'h', 'replicas': 1}, 'h', say, lambda s: None)
ok(code == KD.CEILING_REFUSED and ('POST', '') not in mg2.calls, 'api_retry: второй create в то же окно (g ещё не виден в списке) → отказ по резерву')
mg3 = ListMG(nine())
code, resp, n = KD.api_retry(mg3, '/g/start', 'POST', None, 'g', say, lambda s: None)
ok(code == 202 and ('POST', '/g/start') in mg3.calls, 'api_retry: /start зарезервированной группы проходит')
mg4 = ListMG(nine() + [grp('x9')])
code, resp, n = KD.api_retry(mg4, '/zz/start', 'POST', None, 'zz', say, lambda s: None)
ok(code == KD.CEILING_REFUSED and ('POST', '/zz/start') not in mg4.calls, 'api_retry: /start чужой группы при полном пределе → отказ, машины не поднимаются')


class Clock:
    """Время тестов: sleep двигает часы, настоящих пауз нет."""

    def __init__(self):
        self.t = 0.0

    def sleep(self, s):
        self.t += s

    def __call__(self):
        return self.t


class BR:
    def __init__(self):
        self.stopped = []

    def group_state(self, name):
        return 200, 'stopped', 0

    def stop_and_verify(self, name):
        self.stopped.append(name)
        return True


os.environ['SALAD_CEILING_DIR'] = fresh()
mg = ListMG(nine() + [grp('x9')])
okc, t0, why = KD.create_and_start(mg, BR(), 'trial-q', {'name': 'trial-q', 'replicas': 1}, say, Clock().sleep, Clock(), 60)
ok((not okc) and why.startswith('salad_ceiling:') and ('POST', '') not in mg.calls, f'create_and_start: отказ ворот → причина salad_ceiling, группа не создана ({why[:60]})')
mg = ListMG(nine())
br = BR()
clk = Clock()
okc, t0, why = KD.create_and_start(mg, br, 'trial-q2', {'name': 'trial-q2', 'replicas': 1}, say, clk.sleep, clk, 60)
folder = SC.ceiling_dir()
reserved = json.load(open(os.path.join(folder, 'salad-ceiling-reserved.json'), encoding='utf-8'))
ok(okc and 'trial-q2' in reserved, 'create_and_start: место под группу зарезервировано до гашения')
ok(KD.stop_and_verify(br, 'trial-q2') is True and 'trial-q2' not in json.load(open(os.path.join(folder, 'salad-ceiling-reserved.json'), encoding='utf-8')), 'stop_and_verify: «0 нод» → резерв снят')

# ---- все создатели групп идут через ворота (сторож репозитория)
import subprocess  # noqa: E402
root = os.path.abspath(os.path.join(HERE, '..', '..', '..'))
creators = subprocess.run(['git', 'grep', '-l', '-E', r"api(_retry)?\(.*'', *'POST'|api_retry\(", '--', 'tools/scout'], cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.split()
creators = [c for c in creators if '/tests_' not in c and '/test_' not in c and not c.endswith('kit_driver.py')]
gated = {c for c in creators if 'salad_ceiling' in open(os.path.join(root, c), encoding='utf-8').read() or 'KD.api_retry' in open(os.path.join(root, c), encoding='utf-8').read()}
ok(set(creators) <= gated, f'каждый скрипт, создающий группы Salad, идёт через ворота (salad_ceiling или KD.api_retry); мимо: {sorted(set(creators) - gated)}')

# ================= T-20261124-58/2: ворота и на /start УЖЕ созданной (остановленной) группы =================
def stopped(name, replicas=1):
    return {'name': name, 'replicas': replicas, 'current_state': {'status': 'stopped', 'instance_status_counts': {}}}


# единый счёт: остановленная/упавшая/останавливающаяся группа без машин — 0 (раньше tools/ops/salad_live.py показывал её «живых 1»)
ok(SC.live_by_group([stopped('s'), grp('f', 0, 'failed'), grp('st', 0, 'stopping')]) == {}, 'live_by_group: stopped/failed/stopping без машин → 0')
sys.path.append(os.path.abspath(os.path.join(HERE, '..', '..', 'ops')))
import salad_live as SLV  # noqa: E402
rows = SLV.live_groups({'items': [stopped('s'), grp('f', 0, 'failed'), grp('st', 0, 'stopping'), grp('r', 2), grp('p', 0, 'pending')]})
ok(sorted((r['name'], r['live']) for r in rows) == [('p', 1), ('r', 2)], f'salad_live.live_groups считает ТЕМ ЖЕ live_by_group: stopped → не строка ({[(r["name"], r["live"]) for r in rows]})')
src = open(os.path.join(HERE, '..', '..', 'ops', 'salad_live.py'), encoding='utf-8').read()
ok('SC.live_by_group' in src and "'allocating_count'" not in src, 'salad_live.py не держит своего счёта (зовёт salad_ceiling.live_by_group)')

# /start остановленной группы: 10 живых → отказ, 9 → ок (число машин — из GET группы)
os.environ['SALAD_CEILING_DIR'] = fresh()
ok(not SC.admit(ListMG(nine() + [grp('x9')] + [stopped('sg')]), 'sg', None)[0], '/start остановленной группы при 10 живых → отказ')
os.environ['SALAD_CEILING_DIR'] = fresh()
ok(SC.admit(ListMG(nine() + [stopped('sg')]), 'sg', None)[0], '/start остановленной группы при 9 живых → ок')
os.environ['SALAD_CEILING_DIR'] = fresh()
ok(not SC.admit(ListMG(nine() + [stopped('sg3', 3)]), 'sg3', None)[0], '/start остановленной группы на 3 реплики при 9 живых → отказ')
# резерв после /start держится только «грейс»: остановили мимо драйвера — место не висит час
d = fresh()
t = [5000.0]
mgs = ListMG(nine() + [stopped('sg')])
ok(SC.admit(mgs, 'sg', None, d=d, clock=lambda: t[0])[0] and not SC.admit(ListMG(nine() + [stopped('sg')]), 'zz', 1, d=d, clock=lambda: t[0])[0], 'после /start группа держит место (резерв), пока Salad её не показал')
t[0] += SC.START_GRACE_S + 5
ok(SC.admit(ListMG(nine() + [stopped('sg')]), 'zz', 1, d=d, clock=lambda: t[0])[0], 'через грейс резерв стартовавшей группы забыт (остановлена мимо драйвера — место свободно)')


class FakeNet(ListMG):
    """Подмена `DefaultMG`: список групп и GET группы — из ListMG; POST /start записывается."""
    sent = []

    def __init__(self):
        super().__init__(FakeNet.items0, replicas=FakeNet.replicas0)


def with_net(items, replicas=1):
    FakeNet.items0, FakeNet.replicas0, FakeNet.sent = list(items), replicas, []
    SC.DefaultMG = FakeNet
    os.environ['SALAD_CEILING_DIR'] = fresh()


# путь 1–2: batch_show.ensure_group_started (первый старт и повторный start) — живой код с подставным urllib
import urllib.request  # noqa: E402
import batch_show as BS  # noqa: E402


class _Resp:
    def read(self):
        return b''


LAST_BS = ['']


def run_batch_show(items):
    with_net(items)
    os.environ.setdefault('SALAD_API_KEY', 'KEY-FAKE')                 # настоящего ключа тесту не нужно: сеть подменена
    sent = []
    real = (urllib.request.urlopen, BS.halt_reason, BS.group_states, BS.SG.groups_from_env, BS.SG.allowed_now, BS.holder_do)
    urllib.request.urlopen = lambda req, timeout=None: (sent.append(getattr(req, 'full_url', req)), _Resp())[1]
    BS.halt_reason, BS.group_states, BS.holder_do = (lambda: ''), (lambda: {'sg': 'stopped'}), (lambda *a, **k: None)
    BS.SG.groups_from_env, BS.SG.allowed_now = (lambda: ['sg']), (lambda g: True)
    try:
        import contextlib
        import io
        buf_bs = io.StringIO()
        with contextlib.redirect_stdout(buf_bs):
            res = BS.ensure_group_started()
        LAST_BS[:] = [buf_bs.getvalue()]
    finally:
        urllib.request.urlopen, BS.halt_reason, BS.group_states, BS.SG.groups_from_env, BS.SG.allowed_now, BS.holder_do = real
    return res, [s for s in sent if str(s).endswith('/start')]


res, sent = run_batch_show(nine() + [grp('x9')] + [stopped('sg')])
ok(sent == [], 'batch_show.ensure_group_started: при 10 живых /start НЕ уходит')
res, sent = run_batch_show(nine() + [stopped('sg')])
ok(len(sent) == 1, f'batch_show.ensure_group_started: при 9 живых /start уходит ({LAST_BS[0][-200:]!r})')

# путь 3: grey_probe, путь 4: cutout_redo — порядок в коде: ворота раньше POST /start (сам main тяжёлый: GPU, очередь, фото)
for rel, gate, start in (('grey_probe.py', 'SC.admit_start(a.group)', "'/containers/{a.group}/start'"), ('../cutout_redo.py', 'SC.admit(MG, a.group, None)', "f'/{a.group}/start'")):
    text = open(os.path.join(HERE, rel), encoding='utf-8').read()
    ok(gate in text and start in text and text.index(gate) < text.index(start), f'{rel}: ворота стоят ДО POST /start')
    ok('if not okc:' in text[text.index(gate):text.index(start)], f'{rel}: отказ ворот прекращает старт')

# путь 5: batch_window.sh — CLI ворот (код выхода 0/1) и порядок в скрипте
with_net(nine() + [grp('x9')] + [stopped('sg')])
import contextlib  # noqa: E402
import io  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc_full = SC.main(['--admit', 'sg'])
ok(rc_full == 1 and 'предел 10' in buf.getvalue(), 'salad_ceiling.py --admit при 10 живых → код 1 и причина на stdout (batch_window.sh пропускает группу)')
with_net(nine() + [stopped('sg')])
with contextlib.redirect_stdout(io.StringIO()):
    rc_ok = SC.main(['--admit', 'sg'])
ok(rc_ok == 0, 'salad_ceiling.py --admit при 9 живых → код 0')
sh = open(os.path.join(HERE, 'batch_window.sh'), encoding='utf-8').read()
ok('salad_ceiling.py" --admit' in sh and sh.index('salad_ceiling.py" --admit') < sh.index('$BASE/$g/start') and sh.index('"${GATE_CMD[@]}"') < sh.index('$BASE/$g/start'), 'batch_window.sh: ворота (--admit) стоят ДО curl …/start')

# сторож: каждый скрипт с POST …/start идёт через ворота (salad_ceiling / api_retry), кроме самих ворот и тестов
starters = subprocess.run(['git', 'grep', '-l', '-E', r"[}\w$]/start['\"`]|/start\" *\|\||\$g/start", '--', 'tools'], cwd=root, capture_output=True, text=True, stdin=subprocess.DEVNULL).stdout.split()
starters = [c for c in starters if '/tests_' not in c and '/test_' not in c and not c.endswith(('kit_driver.py', 'salad_ceiling.py'))]
bare = [c for c in starters if not any(k in open(os.path.join(root, c), encoding='utf-8').read() for k in ('salad_ceiling', 'SC.admit', 'api_retry'))]
ok(not bare, f'каждый скрипт с POST …/start идёт через ворота; мимо: {bare}')

print('\nFAILS:', FAILS or 'нет')
sys.exit(1 if FAILS else 0)

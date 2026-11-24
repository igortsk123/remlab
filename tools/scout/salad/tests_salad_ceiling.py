#!/usr/bin/env python3
"""Ворота предела живых машин Salad (`salad_ceiling.py`) и их подключение к `kit_driver` (T-20261124-58). БЕЗ сети, Salad и ключа: список групп и ответы подставные.

Проверяет: (а) 9 живых + создать 1 → можно; (б) 10 живых → отказ со строкой «живо N, предел 10»; (в) два параллельных создания при 9 живых → одно прошло, другое отказ (замок + резерв);
(г) API недоступен (503, обрыв, мусор) → отказ, а не «свободно»; свои тёплые группы В СЧЁТЕ; старт уже зарезервированной группы проходит; погашенная группа освобождает место;
резерв истекает по сроку; предел берётся из rules/loop5.json (одно правило); `kit_driver.api_retry` при отказе НЕ шлёт create, `create_and_start` возвращает причину salad_ceiling,
`stop_and_verify` снимает резерв; в тестовом процессе без явной папки ворота выключены (чужие тесты со своими подставными API не ломаются).
Запуск: python3 tools/scout/salad/tests_salad_ceiling.py
"""
import contextlib
import io
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

# ================= T-20261124-58/3: пересоздание групп и погашенные серии — через те же ворота =================
import argparse  # noqa: E402
import time  # noqa: E402

# 1. метка стопа серии: кто видит, кто нет
d = fresh()
SC.series_stop('kA', d=d, reason='тест', now=1000.0)
ok(SC.series_stopped('kA', since=500.0, d=d) != '', 'метка: драйвер, запущенный ДО метки, видит стоп серии')
ok(SC.series_stopped('kA', since=2000.0, d=d) == '', 'метка: новая серия с тем же ключом (старт позже метки) стоп не видит — метку удалять не нужно')
ok(SC.series_stopped('kB', since=0.0, d=d) == '', 'метка чужой серии не мешает')
ok(SC.series_clear('kA', d=d) and SC.series_stopped('kA', since=0.0, d=d) == '', 'series_clear: ручная уборка метки')
ok(SC.series_stopped('', since=0.0, d=d) == '', 'серия не задана — метки не читаются')

# 2. ворота admit: серия остановлена → отказ ДО чтения списка (ни одного обращения к Salad), другая серия и «без серии» проходят
d = fresh()
SC.series_stop('kA', d=d, reason='повтор погашен')
mgs = ListMG(nine())
okc, why = SC.admit(mgs, 'g1', 1, d=d, series='kA')
ok((not okc) and 'серия kA остановлена' in why and 'повтор погашен' in why and mgs.calls == [], f'admit: серия остановлена → отказ, Salad не опрашивается ({why[:80]})')
ok(SC.admit(ListMG(nine()), 'g1', 1, d=d, series='kZ')[0], 'admit: другая серия — можно')
ok(SC.admit(ListMG(nine()), 'g1', 1, d=d)[0], 'admit: серия не задана — метка не читается')

# 3. штатная команда стопа серии (CLI) пишет метку; --series-status её видит
d = fresh()
os.environ['SALAD_CEILING_DIR'] = d
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    rc_stop = SC.main(['--stop-series', 'k-cli', '--reason', 'руками'])
    rc_st = SC.main(['--series-status', 'k-cli'])
    rc_none = SC.main(['--series-status', 'k-none'])
ok(rc_stop == 0 and rc_st == 0 and rc_none == 1 and os.path.isfile(os.path.join(d, 'series-stop', 'k-cli.json')), f'CLI: --stop-series пишет метку, --series-status: есть 0 / нет 1 ({rc_stop},{rc_st},{rc_none})')

# 4. драйвер: серия объявлена → api_retry и create_and_start при метке не шлют ни create, ни /start
os.environ['SALAD_CEILING_DIR'] = fresh()
mod = KD._sc()
KD.series_bind('kD')
ok(KD.series_stop_reason() == '', 'драйвер: метки нет — стопа нет')
mod.series_stop('kD', reason='стоп серии')
ok('kD' in KD.series_stop_reason(), 'драйвер: метка записана после старта процесса — серия остановлена')
mg_s = ListMG([])
code, resp, n = KD.api_retry(mg_s, '', 'POST', {'name': 'w2b-0b7c85m', 'replicas': 1}, 'w2b-0b7c85m', say, lambda x: None)
ok(code == KD.CEILING_REFUSED and ('POST', '') not in mg_s.calls and 'серия kD' in str(resp.get('detail')), 'api_retry: пересоздание «…m» при метке серии → отказ, create не шлётся')
okc, t0, why = KD.create_and_start(mg_s, BR(), 'w2b-0b7c85m', {'name': 'w2b-0b7c85m', 'replicas': 1}, say, Clock().sleep, Clock(), 60)
ok((not okc) and why.startswith('salad_ceiling:') and ('POST', '') not in mg_s.calls, f'create_and_start: при метке серии группа не создаётся ({why[:70]})')
mg_s2 = ListMG([stopped('w2b-0b7c85')])
code, resp, n = KD.api_retry(mg_s2, '/w2b-0b7c85/start', 'POST', None, 'w2b-0b7c85', say, lambda x: None)
ok(code == KD.CEILING_REFUSED and ('POST', '/w2b-0b7c85/start') not in mg_s2.calls, 'api_retry: /start при метке серии → отказ')

# 5. повтор на запасной тариф (run_probe) — при метке серии не делается; без метки — идёт и снова через ворота
calls_once = []
real_once, real_prof, real_tr = KD._run_probe_once, KD.resource_profile, KD.tier_refusal
KD._run_probe_once = lambda a_, MG_, BR_, spec_, result=None, **kw: (calls_once.append(a_.suffix), result.update({'summary': {'stopped_by': 'no_machine'}}), 1)[2]
KD.resource_profile = lambda wt, path=None: {'tier': 'low', 'tier_fallback': 'medium'}
KD.tier_refusal = lambda prof_, tier_: None
try:
    a_ = argparse.Namespace(apply=True, tier='low', suffix='s1')
    with contextlib.redirect_stdout(io.StringIO()) as out_m:
        rc_m = KD.run_probe(a_, None, None, argparse.Namespace(work_type='x'))
    ok(rc_m == 1 and calls_once == ['s1'] and a_.suffix == 's1' and 'повтор' in out_m.getvalue(), f'run_probe: серия остановлена → повтор «…m» не создаётся (вызовы {calls_once})')
    mod.bind_series('')
    calls_once.clear()
    a_ = argparse.Namespace(apply=True, tier='low', suffix='s1')
    with contextlib.redirect_stdout(io.StringIO()) as out_m:
        KD.run_probe(a_, None, None, argparse.Namespace(work_type='x'))
    ok(calls_once == ['s1', 's1m'], f'run_probe: серии нет — повтор идёт (проверка, что стоп-тест не пустой): {calls_once}')
finally:
    KD._run_probe_once, KD.resource_profile, KD.tier_refusal = real_once, real_prof, real_tr
    mod.bind_series('')

# 6. пересоздание «…m» при 10 живых → отказ (предел — те же ворота), при 9 — можно
os.environ['SALAD_CEILING_DIR'] = fresh()
mg10 = ListMG(nine() + [grp('x9')])
okc, t0, why = KD.create_and_start(mg10, BR(), 'w4b-0b7c85m', {'name': 'w4b-0b7c85m', 'replicas': 1}, say, Clock().sleep, Clock(), 60)
ok((not okc) and 'salad_ceiling' in why and 'предел 10' in why and ('POST', '') not in mg10.calls, f'пересоздание «…m» при 10 живых → отказ без create ({why[:80]})')
mg9 = ListMG(nine())
okc, t0, why = KD.create_and_start(mg9, BR(), 'w4b-0b7c85m', {'name': 'w4b-0b7c85m', 'replicas': 1}, say, Clock().sleep, Clock(), 60)
ok(okc and ('POST', '') in mg9.calls, 'пересоздание «…m» при 9 живых → можно')

# 7. recreate_group: цикл попыток создания проверяет метку серии перед каждой попыткой
rg = open(os.path.join(HERE, 'recreate_group.py'), encoding='utf-8').read()
loop_at = rg.index('for attempt in range(1, 41):')
ok('SC.series_stopped()' in rg[loop_at:loop_at + 300] and rg.index('SC.series_stopped()', loop_at) < rg.index("MG.api('', 'POST', body)", loop_at), 'recreate_group: метка серии читается перед КАЖДОЙ попыткой создания')

# 8. версия воркера: от образа и кода воркера; тёплая нода чужой версии не берётся
dg_a, dg_b = 'i@sha256:' + 'a' * 64, 'i@sha256:' + 'b' * 64
with tempfile.TemporaryDirectory() as td:
    wf = os.path.join(td, 'worker.py')
    open(wf, 'w').write('v1')
    v1 = KD.worker_version(dg_a, wf)
    ok(len(v1) == 6 and v1 == KD.worker_version(dg_a, wf), 'worker_version: 6 hex, стабильна')
    open(wf, 'w').write('v2')
    ok(KD.worker_version(dg_a, wf) != v1, 'worker_version: код воркера изменился → версия другая')
ok(KD.worker_version(dg_b, '') != KD.worker_version(dg_a, ''), 'worker_version: образ другой → версия другая')
good = {'image': dg_a, 'worker_ver': 'aaaaaa', 'expires_at': 10_000.0}
ok(KD.warm_decide('running', good, dg_a, 0.0, 600.0, ver='aaaaaa')[0] == 'adopt', 'warm_decide: версия та же → подхват')
act, why = KD.warm_decide('running', good, dg_a, 0.0, 600.0, ver='bbbbbb')
ok(act == 'refuse' and 'версия воркера' in why, f'warm_decide: живая нода другой версии → не берём ({why[:60]})')
act, why = KD.warm_decide('running', {'image': dg_a, 'expires_at': 10_000.0}, dg_a, 0.0, 600.0, ver='aaaaaa')
ok(act == 'refuse' and 'не записана' in why, 'warm_decide: у живой ноды версия не записана → не берём')
ok(KD.warm_decide('running', {'image': dg_a, 'expires_at': 10_000.0}, dg_a, 0.0, 600.0)[0] == 'adopt', 'warm_decide: без ver (старые вызовы) — как раньше')
ok(KD.warm_decide('stopped', {'worker_ver': 'aaaaaa'}, dg_a, 0.0, 600.0, ver='bbbbbb')[0] == 'refuse', 'warm_decide: остановленная группа записанной другой версии → не стартуем')
act, why = KD.warm_decide('stopped', {}, dg_a, 0.0, 600.0, ver='aaaaaa', group_image=dg_b)
ok(act == 'refuse' and 'другой образ' in why, 'warm_decide: у остановленной группы образ в Salad другой (нет записи) → не стартуем')
ok(KD.warm_decide('stopped', {}, dg_a, 0.0, 600.0, ver='aaaaaa', group_image=dg_a)[0] == 'restart', 'warm_decide: образ группы тот же → старт заново')
ok(KD.warm_decide(None, {}, dg_a, 0.0, 600.0, ver='aaaaaa')[0] == 'create', 'warm_decide: группы нет → создание (через ворота)')

print('\nFAILS:', FAILS or 'нет')
sys.exit(1 if FAILS else 0)

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
                    return 200, {**x, 'replicas': self.replicas}
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

print('\nFAILS:', FAILS or 'нет')
sys.exit(1 if FAILS else 0)

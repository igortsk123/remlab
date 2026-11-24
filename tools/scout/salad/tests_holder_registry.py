#!/usr/bin/env python3
"""Реестр держателей групп Salad и `tools/ops/salad_live.py` (T-20261124-42/1, урок 929). БЕЗ сети, Salad и ключа.

Проверяет: запись/пульс/стирание; «жив / МЁРТВ / pid переиспользован / чужая машина»; тёплая метка (живая и истёкшая); строки и итог salad_live
(формат «ЖИВО машин всего (оценка): N … · ❗ без держателя: K»); код выхода; ошибка записи НЕ роняет драйвер (kit_driver.create_and_start идёт дальше);
ключ Salad не попадает в вывод; запись/стирание реально происходят в kit_driver.create_and_start / stop_and_verify.
Запуск: python3 tools/scout/salad/tests_holder_registry.py
"""
import contextlib
import io
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'ops')))
import holder_registry as HR  # noqa: E402
import salad_live as SL  # noqa: E402

FAILS = []
FAKE_KEY = 'KEY-MUST-NOT-LEAK-0123456789'


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


HOST = 'this-host'
NOW = 1_000_000.0


def alive_map(m):
    return lambda pid: m.get(pid)


def listing(*groups):
    """groups: (имя, статус, running_count)."""
    return {'items': [{'name': n, 'replicas': 1, 'current_state': {'status': st, 'instance_status_counts': {'running_count': r, 'creating_count': 0, 'allocating_count': 0}}}
                      for n, st, r in groups]}


def rec(group, pid, host=HOST, pid_start='111', task='T-1', hb=NOW - 180, started=NOW - 3600, **kw):
    return {'group': group, 'host': host, 'pid': pid, 'pid_start': pid_start, 'task': task, 'started_at': started, 'heartbeat_at': hb, **kw}


# --- 1. запись, пульс, стирание
with tempfile.TemporaryDirectory() as d:
    ok(HR.pid_start(os.getpid()) is not None and HR.pid_start(2 ** 30) is None, 'pid_start: свой процесс читается, несуществующий — None')
    ok(HR.write('trial-a', 'T-42', d=d, now=NOW), 'write → True')
    r = HR.read('trial-a', d)
    ok(r and r['pid'] == os.getpid() and r['task'] == 'T-42' and r['pid_start'] == HR.pid_start(os.getpid()) and r['started_at'] == NOW and r['heartbeat_at'] == NOW, 'запись: pid, pid_start, задача, время старта и пульса')
    ok(HR.beat('trial-a', now=NOW + 60, d=d) and HR.read('trial-a', d)['heartbeat_at'] == NOW + 60 and HR.read('trial-a', d)['started_at'] == NOW, 'beat: обновляет только heartbeat_at')
    ok(not HR.beat('trial-a', now=NOW + 99, d=d, pid=os.getpid() + 1) and HR.read('trial-a', d)['heartbeat_at'] == NOW + 60, 'beat чужого pid — ничего не пишет')
    ok(not HR.beat('нет-такой', d=d), 'beat без записи — False, файл не создан')
    HR.write('trial-b', d=d, now=NOW)
    ok(HR.beat_all(now=NOW + 120, d=d) == 2, 'beat_all: все группы своего процесса')
    ok(sorted(HR.read_all(d)) == ['trial-a', 'trial-b'], 'read_all: обе записи')
    open(os.path.join(d, 'битая.json'), 'w').write('{не json')
    ok(sorted(HR.read_all(d)) == ['trial-a', 'trial-b'], 'read_all: битый файл пропущен')
    ok(HR.clear('trial-a', d) and HR.read('trial-a', d) is None and HR.clear('trial-a', d), 'clear: стёрла; повторный clear без записи — тоже True')
    HR.write('trial-c', d=d, now=NOW)
    ok(HR.mark_warm('trial-c', NOW + 900, now=NOW + 5, d=d) and HR.read('trial-c', d)['warm_until'] == NOW + 900, 'mark_warm: метка «тёплая до»')
    ok(HR.beat('trial-c', now=NOW + 10, d=d) and 'warm_until' not in HR.read('trial-c', d), 'пульс живого держателя снимает тёплую метку (группа снова в работе)')
    # адопт: живого держателя нет → пишем; свой живой → не перетираем
    HR.write('mesh-low-1', 'старый', d=d, now=NOW)
    r0 = HR.read('mesh-low-1', d)
    ok(HR.adopt('mesh-low-1', 'batch_show', now=NOW + 5, d=d) and HR.read('mesh-low-1', d)['started_at'] == r0['started_at'], 'adopt: живой держатель уже есть — запись не перетирается')
    path = os.path.join(d, 'mesh-low-2.json')
    json.dump(rec('mesh-low-2', 2 ** 30, host=HR.socket.gethostname()), open(path, 'w'))
    HR.adopt('mesh-low-2', 'batch_show', now=NOW, d=d)
    ok(HR.read('mesh-low-2', d)['pid'] == os.getpid() and HR.read('mesh-low-2', d)['task'] == 'batch_show', 'adopt: держатель умер — подхватываем')

# --- 2. состояния держателя
r = rec('g', 100)
ok(HR.holder_state(r, HOST, alive_map({100: '111'})) == 'alive', 'жив: pid есть, pid_start совпал')
ok(HR.holder_state(r, HOST, alive_map({})) == 'dead', 'МЁРТВ: процесса нет')
ok(HR.holder_state(r, HOST, alive_map({100: '999'})) == 'dead', 'МЁРТВ: pid достался другому процессу (pid_start разный)')
ok(HR.holder_state(r, 'other-host', alive_map({100: '111'})) == 'foreign', 'чужая машина: проверить нельзя')

# --- 3. строки salad_live
rows = SL.live_groups(listing(('trial-ok', 'running', 1), ('trial-dead', 'running', 1), ('mesh-low-1', 'running', 2), ('mesh-warm', 'running', 1), ('trial-old', 'stopped', 0),
                              ('trial-fail', 'failed', 0), ('mesh-pend', 'pending', 0), ('trial-far', 'running', 1), ('trial-wx', 'running', 1)))
ok([r['name'] for r in rows] == ['trial-ok', 'trial-dead', 'mesh-low-1', 'mesh-warm', 'mesh-pend', 'trial-far', 'trial-wx'], 'живые: stopped и failed без нод не считаются, pending считается')
registry = {
    'trial-ok': rec('trial-ok', 100, task='T-91', hb=NOW - 180),
    'trial-dead': rec('trial-dead', 200, task='T-77', hb=NOW - 47 * 60),
    'mesh-warm': rec('mesh-warm', 300, warm_until=NOW + 600),
    'trial-wx': rec('trial-wx', 300, warm_until=NOW - 300),
    'trial-far': rec('trial-far', 400, host='common'),
    'trial-old': rec('trial-old', 500),
}
lines, bad = SL.report(rows, registry, NOW, HOST, alive_map({100: '111'}))
text = '\n'.join(lines)
ok(bad == 4, f'❗ ровно 4: МЁРТВ, нет записи (mesh-low-1, mesh-pend), истёкшая тёплая метка — получено {bad}')
ok(any(l.startswith('   trial-ok') and 'держатель pid 100 / T-91 · жив · молчит 3 мин' in l for l in lines), 'живой: «держатель pid / задача · жив · молчит 3 мин»')
ok(any(l.startswith('❗ trial-dead') and 'МЁРТВ · молчит 47 мин' in l for l in lines), 'мёртвый: ❗ и «молчит 47 мин»')
ok(any(l.startswith('❗ mesh-low-1') and 'НЕТ ЗАПИСИ' in l for l in lines), 'нет записи: ❗')
ok(any(l.startswith('   mesh-warm') and 'тёплая нода, осталось 10 мин' in l for l in lines), 'тёплая нода: не ❗, осталось 10 мин')
ok(any(l.startswith('❗ trial-wx') and 'ИСТЕКЛА 5 мин' in l for l in lines), 'истёкшая тёплая метка: ❗')
ok(any(l.startswith('   trial-far') and 'чужая машина (common)' in l for l in lines), 'чужая машина: не ❗, но видно')
ok('записи без живой группы' in text and 'trial-old' in text, 'запись остановленной группы — отдельной строкой «мусор»')
ok(lines[-1] == 'ЖИВО машин всего (оценка): 8 · из них проба (trial-*): 4 · ❗ без держателя: 4', 'итоговая строка: ' + lines[-1])
lines0, bad0 = SL.report([], {}, NOW, HOST)
ok(bad0 == 0 and lines0 == ['ЖИВО машин всего (оценка): 0 · из них проба (trial-*): 0 · ❗ без держателя: 0'], 'пусто: итог с нулями, ❗ нет')

# --- 4. main: код выхода, ключ не печатается
with tempfile.TemporaryDirectory() as d:
    gf = os.path.join(d, 'groups.json')
    json.dump(listing(('trial-x', 'running', 1)), open(gf, 'w'))
    reg = os.path.join(d, 'reg')
    os.environ['SALAD_API_KEY'] = FAKE_KEY
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = SL.main(['--groups-file', gf, '--registry', reg])
    ok(rc == 1 and '❗ trial-x' in out.getvalue() and 'НЕТ ЗАПИСИ' in out.getvalue(), 'main: группа без записи → код 1')
    ok(FAKE_KEY not in out.getvalue() + err.getvalue(), 'ключ Salad не попал в вывод')
    HR.write('trial-x', 'T-42', d=reg, now=__import__('time').time())
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = SL.main(['--groups-file', gf, '--registry', reg])
    ok(rc == 0 and 'жив' in out.getvalue() and 'без держателя: 0' in out.getvalue(), 'main: держатель — этот процесс, жив → код 0')
    # список не получен
    del os.environ['SALAD_API_KEY']
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = SL.main([])
    ok(rc == 2 and 'SALAD_API_KEY' in err.getvalue(), 'main: нет ключа → код 2 с подсказкой, как загрузить')
    os.environ['SALAD_API_KEY'] = FAKE_KEY
    real = SL.fetch_groups
    SL.fetch_groups = lambda key, timeout=30: (_ for _ in ()).throw(OSError('sock: ' + key))      # исключение, в тексте которого — ключ
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = SL.main([])
    SL.fetch_groups = real
    ok(rc == 2 and FAKE_KEY not in err.getvalue(), 'main: сбой GET → код 2, текст исключения (а в нём мог быть ключ) не печатается')

# --- 5. ошибка записи НЕ роняет драйвер
with tempfile.TemporaryDirectory() as d:
    blocked = os.path.join(d, 'файл-вместо-папки')
    open(blocked, 'w').write('x')
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        w = HR.write('trial-e', d=os.path.join(blocked, 'sub'), now=NOW)
        b = HR.beat('trial-e', d=os.path.join(blocked, 'sub'))
        c = HR.clear('trial-e', d=os.path.join(blocked, 'sub'))
    ok(w is False and 'реестр держателей' in buf.getvalue() and b is False, 'write в недоступную папку: False и строка в журнал, исключения нет')

# --- 6. wiring в kit_driver: запись при /start, стирание после «0 нод», сбой реестра не мешает
sys.path.append(os.path.abspath(os.path.join(HERE, '..')))
import kit_driver as KD  # noqa: E402


class FakeMG:
    def __init__(self):
        self.calls = []

    def api(self, path, method='GET', body=None):
        self.calls.append((method, path))
        if method == 'POST' and path == '':
            return 201, {}
        if method == 'POST' and path.endswith('/start'):
            return 202, {}
        return 200, {'current_state': {'status': 'stopped'}}


class FakeBR:
    stops = 0

    def group_state(self, name):
        return 200, 'stopped', {}

    def stop_and_verify(self, name):
        self.stops += 1
        return True


class Clk:
    t = 5000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


with tempfile.TemporaryDirectory() as d:
    os.environ['SALAD_HOLDERS_DIR'] = d
    clk, br = Clk(), FakeBR()
    good, t_start, why = KD.create_and_start(FakeMG(), br, 'trial-w', {}, lambda *a: None, clk.sleep, clk, wait_s=300)
    r = HR.read('trial-w', d)
    ok(good and r and r['pid'] == os.getpid() and r['group'] == 'trial-w', 'create_and_start: после /start держатель записан (pid этого процесса)')
    ok(KD.stop_and_verify(br, 'trial-w') and HR.read('trial-w', d) is None, 'stop_and_verify: «0 нод» подтверждено → запись стёрта')
    # остановка НЕ подтверждена → запись остаётся (группа может быть жива)
    HR.write('trial-w2', d=d, now=NOW)
    br2 = FakeBR()
    br2.stop_and_verify = lambda name: False
    ok(not KD.stop_and_verify(br2, 'trial-w2') and HR.read('trial-w2', d) is not None, 'остановка не подтверждена → запись остаётся (будет видно в обходе)')
    # сбой реестра (папка — файл) драйвер не роняет
    blocked = os.path.join(d, 'файл')
    open(blocked, 'w').write('x')
    os.environ['SALAD_HOLDERS_DIR'] = os.path.join(blocked, 'sub')
    clk = Clk()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        good, t_start, why = KD.create_and_start(FakeMG(), FakeBR(), 'trial-w3', {}, lambda *a: None, clk.sleep, clk, wait_s=300)
        stopped = KD.stop_and_verify(FakeBR(), 'trial-w3')
    ok(good and why == '' and stopped, 'сбой записи реестра: create_and_start и stop_and_verify отработали как обычно')
    ok('реестр держателей' in buf.getvalue(), '… а причина — строкой в журнал')
    del os.environ['SALAD_HOLDERS_DIR']
    # тест-процесс без явной папки в настоящий реестр не пишет
    ok(HR.write('trial-zzz') is False and HR.read('trial-zzz') is None, 'процесс tests_*.py без явной папки в боевой реестр не пишет')

print()
print(f'ПРОВАЛЕНО: {len(FAILS)}' if FAILS else 'ВСЁ ЗЕЛЁНОЕ')
sys.exit(1 if FAILS else 0)

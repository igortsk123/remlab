#!/usr/bin/env python3
"""Тесты НАБОРА SALAD (kit_driver.py, kit_worker.py) БЕЗ сети, денег и GPU + СТОРОЖ ВСЕГО РЕПОЗИТОРИЯ (T-20261121-178/2).
Запуск: python3 tools/scout/salad/tests_kit.py

Сторож: (1) каждый воркер с HTTP-сервером (`tools/scout/**/worker*.py`, `*_worker.py`) идёт через `kit_worker` (сервер на `::`) или слушает `::` своим сокетом; (2) каждый драйвер платных проб
(зовёт `BR.stop_and_verify(`) импортирует `kit_driver`. Исключения — только в `kit-allow.txt`, строка `worker|driver <путь>  # причина`. Новая проба или воркер мимо набора роняют тест (уроки 724, 748, 754, 755…)."""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, HERE)
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402

FAILS: list[str] = []


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


# ================================================================ ДРАЙВЕР
# --- образ: digest и размер
D = 'sha256:' + 'a' * 64
ok(KD.check_image('ghcr.io/o/n:tag')[0] is False and 'digest' in KD.check_image('ghcr.io/o/n:tag')[1], 'образ по тегу — отказ (ADR-0137)')
ok(KD.check_image('')[0] is False, 'пустой образ — отказ')
GIB = 2 ** 30


def getter_for(layers_gib, index=False, arch='amd64'):
    def get(path, headers):
        if index and '/manifests/' + D in path:
            return {'manifests': [{'platform': {'os': 'linux', 'architecture': 'arm64'}, 'digest': 'sha256:b' * 1}, {'platform': {'os': 'linux', 'architecture': arch}, 'digest': 'sha256:' + 'c' * 64}]}
        return {'config': {'size': 1000}, 'layers': [{'size': int(g * GIB)} for g in layers_gib]}
    return get


r = KD.check_image(f'ghcr.io/o/n@{D}', None, getter=getter_for([2.0, 4.8]))
ok(r[0] and abs(r[2] - 6.8) < 0.01, f'образ 6,8 ГиБ по digest годится ({r[1]})')
r = KD.check_image(f'ghcr.io/o/n@{D}', None, getter=getter_for([20, 12]))
ok(r[0] and r[2] == 32.0, 'образ 32 ГиБ — годится (предел 35, как у Salad и в ADR-0137)')
r = KD.check_image(f'ghcr.io/o/n@{D}', None, getter=getter_for([20, 16]))
ok(not r[0] and '35' in r[1] and r[2] == 36.0, 'образ 36 ГиБ — отказ с причиной (больше 35)')
r = KD.check_image(f'ghcr.io/o/n@{D}', None, getter=getter_for([1, 2], index=True))
ok(r[0] and r[2] == 3.0, 'мультиархитектурный индекс: берём linux/amd64')
r = KD.check_image(f'ghcr.io/o/n@{D}', None, getter=getter_for([1, 2], index=True, arch='s390x'))
ok(not r[0] and 'amd64' in r[1], 'в индексе нет amd64 — отказ')


def boom(path, headers):
    raise OSError('нет сети')


r = KD.check_image(f'ghcr.io/o/n@{D}', None, getter=boom)
ok(not r[0] and 'не прочитан' in r[1], 'манифест не прочитан — НЕ запускаем (платное без проверки размера нельзя)')
ok(KD.split_image(f'ghcr.io/igortsk123/mesh-x@{D}') == ('ghcr.io', 'igortsk123/mesh-x', D), 'разбор имени образа: реестр, репозиторий, digest')

# --- heavy-slot --prio 2
with tempfile.TemporaryDirectory() as proc:
    def holder(pid, args):
        os.makedirs(os.path.join(proc, str(pid)), exist_ok=True)
        open(os.path.join(proc, str(pid), 'cmdline'), 'wb').write(b'\0'.join(a.encode() for a in args) + b'\0')

    holder(111, ['python3', 'heavy_slot.py', 't', '--prio', '2', '--cores', '1', '--', 'x'])
    holder(222, ['python3', 'heavy_slot.py', 't', '--prio', '1', '--', 'x'])
    holder(333, ['python3', 'heavy_slot.py', 't', '--cores', '1', '--', 'x'])
    holder(444, ['python3', 'heavy_slot.py', 't', '--prio=2', '--', 'x'])

    def slot(env):
        try:
            KD.require_slot(2, env, proc)
            return None
        except KD.SlotRefused as exc:
            return str(exc)

    ok(slot({'HEAVY_SLOT_HELD': '111'}) is None, 'слот: под heavy-slot --prio 2 — можно')
    ok(slot({'HEAVY_SLOT_HELD': '444'}) is None, 'слот: --prio=2 — можно')
    ok('приоритетом' in (slot({'HEAVY_SLOT_HELD': '222'}) or ''), 'слот: --prio 1 — отказ')
    ok('приоритетом' in (slot({'HEAVY_SLOT_HELD': '333'}) or ''), 'слот: без --prio — отказ')
    ok('HEAVY_SLOT_HELD' in (slot({}) or ''), 'слот: вне heavy-slot — отказ')
    ok('no-slot' in (slot({'HEAVY_SLOT_HELD': '111', 'HEAVY_SLOT_NOSLOT': '9'}) or ''), 'слот: --no-slot (мимо очереди) — отказ')
    ok('не найден' in (slot({'HEAVY_SLOT_HELD': '999'}) or ''), 'слот: держатель не найден (чужое окружение) — отказ')


# --- общие фейки Salad
class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeMG:
    API = 'https://x/projects/p/containers'

    def __init__(self, script=None, listed_after=0):
        self.script, self.calls, self.created, self.listed_after = list(script or []), [], False, listed_after

    def api(self, path, method='GET', body=None):
        self.calls.append((method, path))
        if self.script and self.script[0][0] == (method, path):
            return self.script.pop(0)[1]
        if method == 'POST' and path == '':
            self.created = True
            return 201, {}
        if method == 'GET' and path.startswith('/'):
            return (200, {'current_state': {'status': 'stopped'}}) if self.created else (404, {})
        return 202, {}


class FakeBR:
    def __init__(self):
        self.stopped = 0

    def group_state(self, name):
        return 200, 'stopped', 1

    def stop_and_verify(self, name):
        self.stopped += 1
        return True


# --- api_retry
clk = Clock()
mg = FakeMG([(('POST', ''), (504, {})), (('POST', ''), (201, {}))])
code, _, n = KD.api_retry(mg, '', 'POST', {'a': 1}, 'g', lambda *a: None, clk.sleep)
ok(code == 201 and n == 1, 'api_retry: 504 → повтор → 201')
mg = FakeMG([(('POST', ''), (504, {}))])
mg.created = True                                              # группа уже есть, хотя ответ 504
code, _, n = KD.api_retry(mg, '', 'POST', {'a': 1}, 'g', lambda *a: None, clk.sleep)
ok(code == 201 and n == 1 and mg.calls.count(('POST', '')) == 1, 'api_retry: 504, но группа уже создана — не создаём второй раз')
mg = FakeMG([(('POST', '/g/start'), (503, {}))] * 9)
code, _, n = KD.api_retry(mg, '/g/start', 'POST', None, 'g', lambda *a: None, clk.sleep, {'retries': 3, 'status_codes': [503], 'pauses_s': [1]})
ok(code == 503 and n == 3, 'api_retry: сбой не уходит — после лимита отдаём код')

# --- create_and_start
clk, mg, br = Clock(), FakeMG([(('POST', '/g/start'), (400, {}))] * 3 + [(('POST', '/g/start'), (202, {}))]), FakeBR()
good, t_start, why = KD.create_and_start(mg, br, 'g', {}, lambda *a: None, clk.sleep, clk, wait_s=2400)
ok(good and mg.calls.count(('POST', '/g/start')) == 4, 'старт: HTTP 400 на большой образ — ждём и повторяем, потом 202 (e022e305)')
clk, mg, br = Clock(), FakeMG([(('POST', '/g/start'), (400, {}))] * 999), FakeBR()
good, t_start, why = KD.create_and_start(mg, br, 'g', {}, lambda *a: None, clk.sleep, clk, wait_s=300)
ok(not good and why == 'start_http_400', 'старт: 400 дольше потолка ожидания — отказ start_http_400')
clk, mg, br = Clock(), FakeMG([(('POST', ''), (500, {'e': 1}))]), FakeBR()
good, t_start, why = KD.create_and_start(mg, br, 'g', {}, lambda *a: None, clk.sleep, clk, wait_s=300)
ok(not good and why == 'create_http_500' and ('POST', '/g/start') not in mg.calls, 'создание: 500 — группа не создана, /start не зовём (урок 755)')


class NeverStopped(FakeBR):
    def group_state(self, name):
        return 200, 'pending', 1


clk, mg, br = Clock(), FakeMG(), NeverStopped()
good, t_start, why = KD.create_and_start(mg, br, 'g', {}, lambda *a: None, clk.sleep, clk, wait_s=120)
ok(not good and why == 'create_wait_timeout', 'образ не готовится дольше потолка — отказ, /start не зовём')

# --- Watch: чистые решения
w = KD.Watch(t_start=0, price=0.6, probe_cap=1.0, cap=4.0, max_min=120, running_min=30, start_min=20, health_min=8, ready_min=30, stall_min=5)
ins_run = [{'state': 'running', 'started': False}]
ok(w.money_time(100, []) == (None, ''), 'Watch: нода ещё не выдана — ждём')
ok(w.money_time(31 * 60, [])[0] == 'no_machine', 'Watch: 30 мин без ноды — no_machine')
w = KD.Watch(0, 0.6, 1.0, 4.0)
w.money_time(60, ins_run)
ok(w.run_since == 60 and w.events[0][0] == 'to_first_running_s', 'Watch: running отмечен')
ok(w.health(60 + 21 * 60, ins_run, 503, {})[0] == 'no_start', 'Watch: 20 мин running, контейнер не запущен — no_start')
w.money_time(200, [{'state': 'running', 'started': True}])
ok(w.started_since == 200, 'Watch: started отмечен')
ok(w.health(200 + 9 * 60, ins_run, 503, {})[0] == 'no_health', 'Watch: 8 мин после started без /health — no_health')
w2 = KD.Watch(0, 0.6, 1.0, 4.0)
w2.money_time(10, ins_run)
ok(w2.money_time(10 + int(1.0 / 0.6 * 3600), ins_run)[0] == 'probe_cap', 'Watch: потолок пробы $1 — probe_cap')
w2.first_done = True
ok(w2.money_time(10 + int(1.0 / 0.6 * 3600), ins_run)[0] is None and w2.cap_now() == 4.0, 'Watch: после первого успеха действует общий потолок')
w3 = KD.Watch(0, 0.6, 9, 9, stall_min=5, stall_gb=0.05)
w3.money_time(0, [{'state': 'running', 'started': True}])
res = None
for i in range(40):
    res = w3.health(i * 10.0, ins_run, 200, {'phase': 'weights', 'root_gb': 1.0})
    if res[0]:
        break
ok(res[0] == 'download_stalled', 'Watch: докачка не растёт 5 мин — download_stalled')
w4 = KD.Watch(0, 0.6, 9, 9)
ok(w4.health(5, ins_run, 200, {'phase': 'broken', 'error': 'no kernel image'})[0] == 'warm_failed', 'Watch: воркер сломан — warm_failed')
ok(w4.health(6, ins_run, 200, {'phase': 'ready'})[1] == 'ready' and w4.ready_at == 6, 'Watch: ready отмечен')
w5 = KD.Watch(0, 0.6, 9, 9, ready_min=30)
w5.money_time(0, ins_run)
w5.health(1, ins_run, 200, {'phase': 'loading'})
ok(w5.health(31 * 60, ins_run, 200, {'phase': 'loading'})[0] == 'not_ready', 'Watch: 30 мин без готовности — not_ready')

# --- докачка весов
ok(KD.weights_slow([(0, 0), (600, 0.3)], 300, 0.5) == 0.3 / 10 * 1 or KD.weights_slow([(0, 0), (600, 0.3)], 300, 0.5) is not None, 'докачка: медленная — возвращает скорость')
ok(KD.weights_slow([(0, 0), (600, 20.0)], 300, 0.5) is None, 'докачка: быстрая — None')
ok(KD.weights_stalled([(i * 10.0, 3.0) for i in range(40)], 300, 0.05) and not KD.weights_stalled([(i * 10.0, i * 0.5) for i in range(40)], 300, 0.05), 'докачка: stalled = рост меньше порога')

# --- учёт денег
with tempfile.TemporaryDirectory() as tmp:
    p = os.path.join(tmp, 'sub', 'ledger.jsonl')
    ok(KD.ledger_append({'group': 'a', 'cost_usd_est': 0.2}, p) is None and KD.ledger_append({'group': 'b', 'cost_usd_est': 0.3}, p) is None, 'учёт: две строки записаны')
    ok(len(open(p).read().splitlines()) == 2 and abs(KD.ledger_total('', p) - 0.5) < 1e-9, 'учёт: сумма расходов')
    ok(KD.ledger_total('2999-01-01', p) == 0.0, 'учёт: окно по дате')
    ok(KD.ledger_window(86400, p) == (2, 0.5) and KD.ledger_line(86400, p) == 'пробы Salad за сутки: 2 шт ≈ $0.50', 'учёт: сводка за сутки для общего отчёта')
    ok(KD.ledger_window(86400, p, now=time.time() + 3 * 86400) == (0, 0.0) and KD.ledger_window(1, os.path.join(tmp, 'нет.jsonl')) == (0, 0.0), 'учёт: старше окна и нет файла — ноль')
    os.environ['SALAD_PROBE_LEDGER'] = '/proc/nope/x.jsonl'
    ok('учёт не записан' in (KD.ledger_append({'a': 1}) or ''), 'учёт: ошибка записи видна, а не глотается')
    del os.environ['SALAD_PROBE_LEDGER']

# --- тело группы
rd, st = KD.probes(8000)
ok(st['failure_threshold'] <= 20 and rd['http']['path'] == '/health', 'пробы: /health, failure_threshold ≤ 20 (иначе HTTP 400)')
body = KD.group_body('g', 'img@sha256:x', 'high', 'cls', 8000, {'HF_TOKEN': 'S1', 'KIT_WORKER_Z': 'zzzz'}, {'cpu': 8}, {'basic': {'password': 'S2'}}, ['python'])
ok(body['container']['resources']['gpu_classes'] == ['cls'] and body['autostart_policy'] is False and body['restart_policy'] == 'never' and body['replicas'] == 1, 'группа: 1 нода, без автостарта и перезапуска')
import contextlib  # noqa: E402
import io  # noqa: E402
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    KD.safe_print(body)
ok('S1' not in buf.getvalue() and 'S2' not in buf.getvalue() and 'zzzz' not in buf.getvalue(), 'печать тела: секреты и код воркера скрыты')

# ================================================================ ВОРКЕР
class Ping(KW.KitHandler):
    def handle_get(self, path):
        if path == '/x':
            self.send_json(200, {'x': 1})
            return True
        return False


def http(url, method='GET'):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=5) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, {}
    except Exception:                                          # noqa: BLE001
        return None, {}


state, stop = KW.State(), threading.Event()
wd = KW.Watchdog(1e9, 1e9)
with tempfile.TemporaryDirectory() as root:
    open(os.path.join(root, 'w.bin'), 'wb').write(b'0' * 2 ** 20)
    H = Ping.bind(state, wd, stop, 'v-test', root_dir=root, health_extra=lambda: {'extra': 7}, engine='E')
    ok(H.engine == 'E', 'bind: дополнительные атрибуты класса')
    srv = KW.make_server(0, H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if socket.has_ipv6:
        c6, h6 = http(f'http://[::1]:{port}/health')
        ok(c6 == 200 and h6['phase'] == 'weights' and h6['version'] == 'v-test' and h6['extra'] == 7, 'воркер отвечает по IPv6 (::1): /health с фазой, версией, расширением')
    c4, h4 = http(f'http://127.0.0.1:{port}/health')
    ok(c4 == 200 and h4['root_gb'] is not None and 'cuda' in h4 and h4['root_gb'] > 0, 'и по IPv4; в /health root_gb (ход докачки) и cuda')
    ok(http(f'http://127.0.0.1:{port}/x') == (200, {'x': 1}) and http(f'http://127.0.0.1:{port}/nope')[0] == 404, 'пути модели через handle_get, чужие — 404')
    ok(http(f'http://127.0.0.1:{port}/shutdown', 'POST')[0] == 200 and stop.is_set(), '/shutdown выставляет остановку')
    srv.shutdown()
    srv.server_close()
ok(KW.make_server(0, Ping, host='0.0.0.0').address_family == socket.AF_INET, 'явный 0.0.0.0 остаётся IPv4 (только для тестов)')


# --- ход задания в /health
sj = KW.State()
ok(sj.job_view() is None, 'ход задания: заданий нет — job = None')
sj.begin_job('j1')
sj.step('te')
sj.step('te')                                                  # тот же шаг повторно — не плодит записей
sj.step('dit')
v = sj.job_view()
ok(v['id'] == 'j1' and v['step'] == 'dit' and [d[0] for d in v['done']] == ['старт', 'te'] and v['elapsed_s'] >= 0, f'ход задания: шаг и пройденные шаги ({v})')
sj.end_job()
ok(sj.job_view() is None, 'ход задания: после конца — None')
with tempfile.TemporaryDirectory() as root2:
    sj2 = KW.State()
    sj2.begin_job('j2')
    sj2.step('vae')
    srv2 = KW.make_server(0, Ping.bind(sj2, KW.Watchdog(1e9, 1e9), threading.Event(), 'v', root_dir=root2))
    threading.Thread(target=srv2.serve_forever, daemon=True).start()
    c, h = http(f'http://127.0.0.1:{srv2.server_address[1]}/health')
    ok(c == 200 and h['job']['step'] == 'vae' and h['job']['id'] == 'j2', '/health отдаёт ход задания (шаг, время)')
    srv2.shutdown()
    srv2.server_close()


# --- прогрев
class Denied(RuntimeError):
    code = 'WEIGHTS_DENIED'


s1 = KW.State()
KW.run_warm(s1, KW.Watchdog(1e9, 1e9), [('weights', lambda: None), ('loading', lambda: None)], selftest=False)
ok(s1.phase == 'ready' and not s1.error, 'прогрев: шаги прошли → ready')
phases = []
s2 = KW.State()
KW.run_warm(s2, KW.Watchdog(1e9, 1e9), [('weights', lambda: phases.append(s2.phase)), ('loading', lambda: phases.append(s2.phase))], selftest=False)
ok(phases == ['weights', 'loading'], 'прогрев: фазы идут по порядку (в /health виден ход)')


def deny():
    raise Denied('403 FLUX.2')


s3 = KW.State()
KW.run_warm(s3, KW.Watchdog(1e9, 1e9), [('weights', deny)], selftest=False)
ok(s3.phase == 'broken' and s3.error.startswith('WEIGHTS_DENIED: '), 'прогрев: исключение с кодом → broken и «КОД: текст» в error')
s4 = KW.State()
KW.run_warm(s4, KW.Watchdog(1e9, 1e9), [('loading', lambda: 1 / 0)], selftest=False)
ok(s4.phase == 'broken' and 'ZeroDivisionError' in s4.error, 'прогрев: любое исключение → broken с типом ошибки')
ok(KW.fatal_cuda(RuntimeError('CUDA error: an illegal memory access')) and KW.fatal_cuda(RuntimeError('no kernel image is available')) and not KW.fatal_cuda(ValueError('plain')),
   'fatal_cuda: ядра/память CUDA — фатально, прочее нет')
KW.gpu_selftest()
ok(True, 'gpu_selftest без torch/CUDA — пропуск без ошибки')

# --- автостоп
t = [0.0]
w = KW.Watchdog(100, 30, now=lambda: t[0])
t[0] = 50
ok(w.verdict(False, False) is None, 'автостоп: не готов — простой не считаем')
ok(w.verdict(True, False) is not None and 'простой' in w.verdict(True, False), 'автостоп: простой после готовности')
ok(w.verdict(True, True) is None, 'автостоп: занят — не гасим')
t[0] = 101
ok('предел жизни' in (w.verdict(True, True) or ''), 'автостоп: предел жизни — всегда')

# --- serve: полный круг на свободном порту
s5, stop5 = KW.State(), threading.Event()
sock = socket.socket()
sock.bind(('', 0))
free = sock.getsockname()[1]
sock.close()
wd5 = KW.Watchdog(max_lifetime_s=3, idle_s=1)
box = {}
th = threading.Thread(target=lambda: box.setdefault('rc', KW.serve(Ping.bind(s5, wd5, stop5, 'v'), s5, wd5, stop5, [('weights', lambda: time.sleep(0.2))], port=free, poll_s=0.1)), daemon=True)
th.start()
time.sleep(0.6)
c, h = http(f'http://127.0.0.1:{free}/health')
ok(c == 200 and h['phase'] in ('weights', 'ready'), f'serve: сервер отвечает во время прогрева ({h.get("phase")})')
th.join(8)
ok(box.get('rc') == 0 and not th.is_alive(), 'serve: автостоп по простою — процесс завершается сам')

# --- доставка кода в env: модуль набора + модель; запускается как на Salad
with tempfile.TemporaryDirectory() as tmp:
    main_py = os.path.join(tmp, 'm.py')
    open(main_py, 'w', encoding='utf-8').write("import kit_worker as KW\nprint('MAIN', __name__, KW.make_server.__name__, KW.__name__)\n")
    cmd, z = KW.bundle(main_py)
    ok(cmd[:3] == ['python', '-u', '-c'] and len(cmd[3]) < 1000, f'bundle: команда python -u -c, элемент {len(cmd[3])} знаков (< 1000, лимит Salad)')
    out = subprocess.run([sys.executable] + cmd[1:], env={**os.environ, 'KIT_WORKER_Z': z}, cwd=tmp, capture_output=True, text=True, timeout=30)
    ok(out.stdout.strip() == 'MAIN __main__ make_server kit_worker', f'bundle: код едет в env и выполняется ({out.stdout.strip()!r} {out.stderr[-120:]})')

# ================================================================ СТОРОЖ РЕПОЗИТОРИЯ
SERVES = re.compile(r'ThreadingHTTPServer\(|[^A-Za-z]HTTPServer\(|uvicorn\.run\(|KW\.serve\(|make_server\(')
KIT_IMPORT = re.compile(r'^\s*(import kit_worker|from kit_worker import)', re.M)
DRIVER_CALL = re.compile(r'\bBR\.stop_and_verify\(')
DRIVER_IMPORT = re.compile(r'^\s*(import kit_driver|from kit_driver import)', re.M)


def worker_problems(text: str) -> list[str]:
    if not SERVES.search(text):
        return []
    if re.search(r'class\s+_DualStackServer\b', text) and 'IPV6_V6ONLY' in text and 'def make_server' in text:
        return []                                               # сам kit_worker
    if KIT_IMPORT.search(text) or re.search(r"import kit_worker as \w+", text):
        if re.search(r"HTTPServer\(\s*\(\s*['\"](0\.0\.0\.0)?['\"]", text):
            return ['набор подключён, но сервер всё равно привязан к 0.0.0.0']
        return []
    if 'AF_INET6' in text and re.search(r"bind\(\s*\(\s*['\"]::['\"]", text):
        return []                                               # свой сокет на `::` (worker_sg.py)
    return ['воркер не через kit_worker и не на `::`: шлюз и пробы Salad ходят по IPv6 (урок 724/754)']


def driver_problems(text: str) -> list[str]:
    if not DRIVER_CALL.search(text):
        return []
    return [] if DRIVER_IMPORT.search(text) else ['драйвер платных проб не импортирует kit_driver (деньги, сторожа, учёт, слот — только из набора)']


def files(pred) -> list[str]:
    out = []
    for dp, dn, fn in os.walk(SCOUT):
        dn[:] = [d for d in dn if d not in ('node_modules', '__pycache__', '.git')]
        for f in fn:
            if f.endswith('.py') and pred(f):
                out.append(os.path.join(dp, f))
    return sorted(out)


def allow() -> dict:
    res = {}
    p = os.path.join(HERE, 'kit-allow.txt')
    if os.path.exists(p):
        for line in open(p, encoding='utf-8'):
            line = line.strip()
            if line and not line.startswith('#'):
                head, _, why = line.partition('#')
                kind, _, path = head.strip().partition(' ')
                res[(kind, path.strip())] = why.strip()
    return res


# сам сторож — на примерах
ok(worker_problems("srv = ThreadingHTTPServer(('0.0.0.0', P), H)"), 'сторож воркеров: 0.0.0.0 ловится')
ok(not worker_problems("import kit_worker as KW\nsrv = KW.make_server(P, H)"), 'сторож воркеров: через kit_worker проходит')
ok(worker_problems("import kit_worker as KW\nsrv = ThreadingHTTPServer(('0.0.0.0', P), H)"), 'сторож воркеров: набор есть, но 0.0.0.0 рядом — ловится')
ok(not worker_problems("sock = socket.socket(socket.AF_INET6)\nsock.bind(('::', P))\nuvicorn.run(app, fd=1)"), 'сторож воркеров: свой сокет на `::` проходит')
ok(not worker_problems('print(1)'), 'сторож воркеров: файл без сервера не трогаем')
ok(driver_problems('import bench_run as BR\nBR.stop_and_verify(n)'), 'сторож драйверов: проба без kit_driver — ловится')
ok(not driver_problems('import kit_driver as KD\nimport bench_run as BR\nBR.stop_and_verify(n)'), 'сторож драйверов: с kit_driver проходит')
ok(not driver_problems('x = 1'), 'сторож драйверов: не драйвер — не трогаем')

al = allow()
n_w = n_d = 0
rel = lambda p: os.path.relpath(p, os.path.join(SCOUT, '..', '..')).replace(os.sep, '/')  # noqa: E731
for path in files(lambda f: (f.startswith('worker') or f.endswith('_worker.py')) and not f.startswith(('test', 'tests'))):
    text = open(path, encoding='utf-8').read()
    if not SERVES.search(text):
        continue
    n_w += 1
    if ('worker', rel(path)) in al:
        ok(True, f'{rel(path)}: в списке исключений — {al[("worker", rel(path))]}')
        continue
    pr = worker_problems(text)
    ok(not pr, f'воркер {rel(path)}: через набор/`::`' if not pr else f'воркер {rel(path)}: {"; ".join(pr)}')
for path in files(lambda f: not f.startswith(('test', 'tests', 'kit_')) and f != 'bench_run.py'):
    text = open(path, encoding='utf-8').read()
    if not DRIVER_CALL.search(text):
        continue
    n_d += 1
    if ('driver', rel(path)) in al:
        ok(True, f'{rel(path)}: в списке исключений — {al[("driver", rel(path))]}')
        continue
    pr = driver_problems(text)
    ok(not pr, f'драйвер {rel(path)}: через kit_driver' if not pr else f'драйвер {rel(path)}: {"; ".join(pr)}')
ok(n_w > 0, f'найдено воркеров с HTTP-сервером: {n_w}')
ok(n_d > 0, f'найдено драйверов платных проб: {n_d}')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПРОВАЛОВ: {len(FAILS)}')
sys.exit(1 if FAILS else 0)

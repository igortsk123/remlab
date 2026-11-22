#!/usr/bin/env python3
"""Тесты НАБОРА SALAD (kit_driver.py, kit_worker.py) БЕЗ сети, денег и GPU + СТОРОЖ ВСЕГО РЕПОЗИТОРИЯ (T-20261121-178/2).
Запуск: python3 tools/scout/salad/tests_kit.py

Сторож: (1) каждый воркер с HTTP-сервером (`tools/scout/**/worker*.py`, `*_worker.py`) идёт через `kit_worker` (сервер на `::`) или слушает `::` своим сокетом; (2) каждый драйвер платных проб
(зовёт `BR.stop_and_verify(`) импортирует `kit_driver`. Исключения — только в `kit-allow.txt`, строка `worker|driver <путь>  # причина`. Новая проба или воркер мимо набора роняют тест (уроки 724, 748, 754, 755…)."""
from __future__ import annotations

import ast
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
sys.path.append(SCOUT)
import remlab_tmp  # noqa: E402  временное теста — на диске, папка убирается при выходе (T-20261107-13)
remlab_tmp.use('tests_kit')
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
ok(st['period_seconds'] == 10, 'стартовая проба: период 10 с (рецепт Hunyuan/TRELLIS.2 fast, урок 802), не 60')

# --- сверка архитектуры CUDA образа с картой до группы (урок 742)
ok(KD.card_arch('RTX 5090 (32 GB)') == '12.0' and KD.card_arch('RTX 4090 (24 GB)') == '8.9' and KD.card_arch('RTX 3090 (24 GB)') == '8.6' and KD.card_arch('Quadro Q') is None, 'карта → архитектура: 5090=12.0, 4090=8.9, 3090=8.6, незнакомая — None')
ok(KD.arch_refusal('RTX 5090 (32 GB)', ('12.0',)) == '' and KD.arch_refusal('RTX 5090 (32 GB)', ()) == '' and KD.arch_refusal('Quadro Q', ('8.9',)) == '', 'сверка: подходит / модель не заявила / карта незнакомая — без отказа')
ok('no kernel image' in KD.arch_refusal('RTX 5090 (32 GB)', ('8.9',)) and 'no kernel image' in KD.arch_refusal('RTX 3090 (24 GB)', ('8.9', '12.0')), 'сверка: образ под 8.9 на 5090/3090 — отказ ДО создания группы (урок 742)')
body = KD.group_body('g', 'img@sha256:x', 'low', 'cls', 8000, {'HF_TOKEN': 'S1', 'KIT_WORKER_Z': 'zzzz'}, {'basic': {'password': 'S2'}}, ['python'], work_type='ultratex')
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
    ok(http(f'http://127.0.0.1:{port}/shutdown', 'POST')[0] == 200 and stop.wait(3), '/shutdown выставляет остановку')      # ответ уходит ДО stop.set() (процесс не должен умереть, не отдав 200) — ждём флаг, а не читаем сразу (плавающий тест под нагрузкой, 21.11)
    srv.shutdown()
    srv.server_close()
ok(KW.make_server(0, Ping, host='0.0.0.0').address_family == socket.AF_INET, 'явный 0.0.0.0 остаётся IPv4 (только для тестов)')


# --- ход задания в /health
class OutOfMemoryError(RuntimeError):                          # как torch.OutOfMemoryError: распознаём по имени класса, torch не нужен
    pass


ok(KW.fatal_cuda(RuntimeError('CUDA out of memory. Tried to allocate 2.00 GiB')) and KW.fatal_cuda(OutOfMemoryError('x')) and KW.fatal_cuda(RuntimeError('!handles_.at(i) INTERNAL ASSERT FAILED at CUDACachingAllocator.cpp:432')),
   'fatal_cuda (урок 744): CUDA OOM и INTERNAL ASSERT аллокатора — фатально (аллокатор испорчен), воркер broken и драйвер гасит ноду')
ok(not KW.fatal_cuda(ValueError('что-то другое')) and not KW.fatal_cuda(RuntimeError('out of memory in the cache of regex')), 'fatal_cuda: посторонняя ошибка и «out of memory» без CUDA — не фатально')
sj = KW.State()
ok(sj.job_view() is None, 'ход задания: заданий нет — job = None')
sj.begin_job('j1')
sj.step('te')
sj.step('te')                                                  # тот же шаг повторно — не плодит записей
sj.step('dit')
v = sj.job_view()
ok(v['id'] == 'j1' and v['step'] == 'dit' and [d[0] for d in v['done']] == ['старт', 'te'] and v['elapsed_s'] >= 0, f'ход задания: шаг и пройденные шаги ({v})')
ok('cores_now' in v, 'ход задания: поле cores_now есть (ядра CPU процесса, None до первого интервала)')
sj._cpu = (time.time() - 10.0, sum(os.times()[:2]) - 5.0)       # 10 с назад процесс имел на 5 с CPU меньше → ≈0,5 ядра + то, что реально жгли с тех пор
v2 = sj.job_view()
ok(isinstance(v2['cores_now'], float) and 0.4 <= v2['cores_now'] <= 8.0, f'ход задания: cores_now = CPU-секунды процесса / секунды интервала ({v2["cores_now"]})')
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

# ================================================================ ЖИВОЙ ХОД ЗАДАНИЯ (урок b1 21.11, P3-SAM: 15 мин молчания)
_st = KW.State()
_st.begin_job('j1')
_st.step('prep', 'первая строка')
_st.note('  строка лога модели  ')
_jv = _st.job_view()
ok(_jv['step'] == 'prep' and _jv['line'] == 'строка лога модели' and 'gpu_util' in _jv and 'gpu_mem_mb' in _jv and _jv['step_s'] >= 0 and _jv['done'][0][0] == 'старт',
   'ход задания: шаг, секунды шага, последняя строка, GPU % и память в job_view')
_st.step('prep', 'вторая')
ok(_st.job_view()['line'] == 'вторая' and len(_st.job_view()['done']) == 1, 'строка обновляется без смены шага; шаг не дублируется')
_st.note('x' * 500)
ok(len(_st.job_view()['line']) == 160, 'строка лога обрезается до 160 знаков (health не раздуваем)')
_st.end_job()
ok(_st.job_view() is None, 'нет задания — нет хода')
_st.step('мимо')
ok(_st.job is None, 'step/note вне задания молча игнорируются')

class _R:
    stdout = '87, 23456\n'
ok(KW.gpu_util_mem(lambda *a, **k: _R()) == (87.0, 23456.0), 'gpu_util_mem разбирает nvidia-smi')
ok(KW.gpu_util_mem(lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError())) == (None, None), 'нет nvidia-smi — (None, None), не падаем')

_jv = {'id': 'j', 'step': 's1', 'gpu_util': 0.0, 'line': 'тишина'}
_sl = KD.JobStall(4)
ok(_sl.step(0, _jv) is None and _sl.step(239, _jv) is None and 'зависло' in (_sl.step(241, _jv) or '') and 'тишина' in (_sl.step(300, _jv) or ''),
   'JobStall: шаг тот же и GPU 0 % > 4 мин — стоп, в причине последняя строка')
_sl = KD.JobStall(4)
_sl.step(0, _jv)
_sl.step(200, {**_jv, 'gpu_util': 60.0})
ok(_sl.step(300, _jv) is None and _sl.step(530, _jv) is None and _sl.step(541, _jv) is not None, 'JobStall: всплеск GPU сбрасывает счёт; 4 мин считаются заново и подряд')
_sl = KD.JobStall(4)
_sl.step(0, _jv)
ok(_sl.step(400, {**_jv, 'step': 's2'}) is None and _sl.step(600, {**_jv, 'step': 's2'}) is None and _sl.step(650, {**_jv, 'step': 's2'}) is not None, 'JobStall: смена шага — счёт заново')
_sl = KD.JobStall(4)
ok(all(_sl.step(t, {**_jv, 'gpu_util': None}) is None for t in (0, 500, 5000)), 'JobStall: GPU неизвестен — не гасим (None ≠ 0 %)')
ok(KD.JobStall(0).step(10 ** 6, _jv) is None and KD.JobStall(4).step(10 ** 6, None) is None, 'JobStall: порог 0 — выключен; задания нет — молчим')
ok(not KD.progress_problems('state.begin_job(j)\nengine.on_step = state.step') and len(KD.progress_problems('print(1)')) == 2, 'progress_problems: begin_job + step обязательны')
ok(len(KD.progress_problems('state.begin_job(j)')) == 1, 'progress_problems: begin_job без шагов — ловится')

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
    if 'AF_INET6' in text and 'IPV6_V6ONLY' in text and re.search(r"Server\(\s*\(\s*['\"]::['\"]", text):
        return []                                               # свой класс сервера с address_family=AF_INET6, V6ONLY=0 и привязкой к `::` (worker_trellis.py: DualStackServer)
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


def spec_problems(text: str) -> list[str]:
    """Проба, собирающая `KD.Spec(`, обязана указать `worker_file=` (код воркера → проверка хода задания до группы); пропуск — только `allow_no_worker_check` в тестах."""
    if not re.search(r'\bKD\.Spec\(|kit_driver\.Spec\(', text):
        return []
    return [] if 'worker_file' in text else ['KD.Spec без worker_file: ход задания до платного запуска не проверить (урок b1)']


ok(worker_problems("class DualStackServer(ThreadingHTTPServer):\n    address_family = socket.AF_INET6\n    def server_bind(self):\n        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)\ndef make_server(p):\n    return DualStackServer(('::', p), H)\n") == []
   and worker_problems("srv = ThreadingHTTPServer(('0.0.0.0', 8000), H)\n") and worker_problems("def make_server(p):\n    return S(('::', p), H)\n"),
   'сторож воркера: свой сервер с AF_INET6 + IPV6_V6ONLY + привязкой к `::` проходит; 0.0.0.0 и `::` без AF_INET6/V6ONLY — нет')
ok(spec_problems('return KD.Spec(prefix="x", worker_file=WF)') == [] and spec_problems('return KD.Spec(prefix="x")') and spec_problems('x = 1') == [], 'сторож Spec: worker_file обязателен')
for path in files(lambda f: not f.startswith(('test', 'tests', 'kit_')) and f != 'bench_run.py'):
    text = open(path, encoding='utf-8').read()
    pr = spec_problems(text)
    if pr:
        ok(False, f'проба {rel(path)}: {"; ".join(pr)}')


# T-178/2: общий вход «отправить задание» — таймаут по размеру тела; POST без ответа (-1) не отказ, а вопрос воркеру
class _GW:
    def __init__(self, post_codes, saw):
        self.post_codes, self.saw, self.calls = list(post_codes), saw, []

    def call(self, method, path, body=None, timeout=60, raw=False):
        self.calls.append((method, path, timeout))
        if method == 'POST':
            return self.post_codes.pop(0), {}
        return (200 if self.saw else 404), {}


g_ = _GW([202], False)
c_, r_, i_ = KD.post_job(g_, '/generate', {'job_id': 'j', 'image_b64': 'x' * (2 * 2 ** 20)}, '/job/j', say_fn=lambda *a: None)
ok(c_ == 202 and i_ is None and len(g_.calls) == 1 and 150 <= g_.calls[0][2] <= 160, 'post_job: ответ есть → отдаём как есть, таймаут POST растёт с телом (2 МБ → ≈150 с), без лишних запросов')
g_ = _GW([-1], True)
c_, r_, i_ = KD.post_job(g_, '/generate', {'job_id': 'j', 'image_b64': 'x'}, '/job/j', say_fn=lambda *a: None)
ok(c_ == 202 and i_['worker_saw_job'] is True and [x[0] for x in g_.calls] == ['POST', 'GET'], 'post_job: POST без ответа, воркер задание видит → принято (202), повтор не нужен')
g_ = _GW([-1], False)
c_, r_, i_ = KD.post_job(g_, '/generate', {'job_id': 'j', 'image_b64': 'x'}, '/job/j', say_fn=lambda *a: None)
ok(c_ == -1 and i_['worker_saw_job'] is False and i_['timeout_s'] == 90, 'post_job: воркер задание не видит → -1 остаётся (повтор решает драйвер), в сведениях таймаут')
g_ = _GW([503], False)
c_, r_, i_ = KD.post_job(g_, '/generate', {'job_id': 'j', 'image_b64': 'x'}, '/job/j', say_fn=lambda *a: None)
ok(c_ == 503 and i_ and i_['code'] == 503 and i_['worker_saw_job'] is False and [x[0] for x in g_.calls] == ['POST', 'GET'], 'post_job: 503 (HTML шлюза) → как нет ответа: спросили воркера, не видит — код 503 остаётся в сведениях, повтор решает драйвер')
g_ = _GW([503], True)
c_, r_, i_ = KD.post_job(g_, '/generate', {'job_id': 'j', 'image_b64': 'x'}, '/job/j', say_fn=lambda *a: None)
ok(c_ == 202 and i_['worker_saw_job'] is True, 'post_job: 503, но воркер задание видит → принято')
g_ = _GW([400], False)
c_, r_, i_ = KD.post_job(g_, '/generate', {'job_id': 'j', 'image_b64': 'x'}, '/job/j', say_fn=lambda *a: None)
ok(c_ == 400 and i_ is None and len(g_.calls) == 1, 'post_job: 400 и прочие ответы воркера — как есть, без повтора')
g_ = _GW([500], False)
c_, r_, i_ = KD.post_job(g_, '/generate', {'job_id': 'j', 'image_b64': 'x'}, '/job/j', say_fn=lambda *a: None, rules={'retry_http': [500]})
ok(c_ == 500 and i_ and i_['worker_saw_job'] is False, 'post_job: список кодов берётся из rules (retry_http), не из кода')
ok('retry_http' in KD.gateway_post_rules() and 503 in KD.gateway_post_rules()['retry_http'], 'rules/salad-groups.json: gateway_post.retry_http задан')
_pr = KD.salad_rules('pull_guard')
ok(_pr and KD.PULL_AFTER_S == _pr['after_s'] and KD.PULL_WINDOW_S == _pr['window_s'] and KD.PULL_MAX_CULLS == _pr['max_culls'] and KD.PULL_SLOW_FACTOR == _pr['slow_factor'],
   'сторож докачки: числа берутся из rules/salad-groups.json → pull_guard, не из кода')
_obs = [(float(t), 0.01 + t / 60.0 * 0.001) for t in range(0, 900, 60)]               # T-178 22.11: 1 % → 2 % за 15 мин (≈0,1 %/мин)
ok(KD.pull_verdict(_obs, max_total_min=KD.max_total_for_image(22.46)) is not None, 'pull_verdict: образ 22,5 ГиБ, темп 0,1 %/мин на 15-й минуте → медленно (пересадка)')
_good = [(float(t), 0.05 * t / 60.0) for t in range(0, 900, 60)]                       # нормальная нода: 5 %/мин (22 ГиБ за ≈20 мин, допуск 55)
ok(KD.pull_verdict(_good, max_total_min=KD.max_total_for_image(22.46)) is None, 'pull_verdict: нормальный темп (5 %/мин, прогноз ≈20 мин при допуске 55) — не трогаем')
class _Rl:
    n = 0
_rl, _sl = [], []
_pg = KD.PullGuard('g', take_slot=lambda: (_sl.append(1) or 1), realloc=lambda g, i, w: (_rl.append((g, i)) or True), say_fn=lambda *a: None)
_pg.configure(22.46)
_moved = [_pg.step(float(t), [{'id': 'inst-1', 'state': 'downloading', 'pulling_progress': 0.01 + t / 60.0 * 0.001}]) for t in range(0, 900, 60)]
ok(any(_moved) and _rl == [('g', 'inst-1')] and _pg.culls == 1, 'PullGuard: темп 0,1 %/мин → пересадка этого экземпляра (без новой группы), ровно одна')
ok(KD.post_timeout_s(0) == 90 and KD.post_timeout_s(500 * 2 ** 20) == 300 and KD.post_timeout_s(10 ** 9, 45) == 45
   and KD.post_timeout_s(2 ** 20, rules={'base_s': 10, 'per_mb_s': 5, 'max_s': 100}) == 15, 'post_timeout_s: формула, потолок max_s, override и правила из rules')

# ---------------------------------------------------------------- T-186/1: профиль ресурсов Salad по типу работы + сторож «мимо профиля»
PROFS = KD.load_profiles()
ok(len(PROFS) >= 5 and {'trellis_shape', 'ultratex', 'forms_render', 'pose_camera', 'parts_segment'} <= set(PROFS), f'профили на месте: {sorted(PROFS)}')
for wt, pr in PROFS.items():
    bad = KD.profile_problems(pr)
    ok(not bad, f'профиль «{wt}»: поля, тариф low/medium, basis честный' + (f' — {bad}' if bad else ''))
    ok(pr['tier'] == 'low' and pr['tier_fallback'] == 'medium', f'профиль «{wt}»: low, нет машин — medium (владелец TG 1456/1457)')
    ok(KD.basis_text(pr) == 'по оценке' or 'замер' in KD.basis_text(pr), f'профиль «{wt}»: откуда числа — {KD.basis_text(pr)}')
_good = dict(PROFS['ultratex'])
ok(KD.profile_problems({k: v for k, v in _good.items() if k != 'basis'}), 'профиль без basis — негоден')
ok(KD.profile_problems(dict(_good, basis='measured')), 'basis=measured без measured.date/log — негоден')
ok(not KD.profile_problems(dict(_good, basis='measured', measured={'date': '2026-11-22', 'log': 't178-forms-1122'})), 'basis=measured с датой и логом — годен')
ok(KD.profile_problems(dict(_good, basis='estimate', basis_note='')), 'basis=estimate без пояснения, что не мерили — негоден')
ok(KD.profile_problems(dict(_good, tier='batch')) and KD.profile_problems(dict(_good, tier_fallback='high')), 'в профиле batch/high запрещены')
ok(KD.tier_refusal(_good, 'batch') and KD.tier_refusal(_good, 'high') and not KD.tier_refusal(_good, 'low') and not KD.tier_refusal(_good, 'medium'), 'тариф: low/medium можно, batch/high нельзя')
ok(KD.card_refusal(_good, 'RTX 3050 Laptop (4 GB)') and not KD.card_refusal(_good, _good['card']), 'карта вне профиля — отказ')
_r = KD.profile_resources(PROFS['ultratex'])
ok(_r == {'cpu': 8, 'memory': 49152, 'storage_amount': 80 * 2 ** 30, 'shm_size': 2048}, f'ultratex: 8 vCPU / 48 ГБ / 80 ГиБ диска ({_r})')
ok(KD.profile_resources(PROFS['ultratex'], 'diag')['storage_amount'] == 20 * 2 ** 30, 'ultratex diag: диск 20 ГиБ из варианта профиля')
for _bad_call, _frag in ((lambda: KD.group_body('g', 'i', 'low', 'c', 8000, {}, {}, work_type=''), 'не указан тип'), (lambda: KD.group_body('g', 'i', 'low', 'c', 8000, {}, {}, work_type='x-нет'), 'нет профиля'),
                         (lambda: KD.group_body('g', 'i', 'low', 'c', 8000, {}, {}, work_type='ultratex', resources={'cpu': 1}), 'мимо профиля'),
                         (lambda: KD.group_body('g', 'i', 'batch', 'c', 8000, {}, {}, work_type='ultratex'), 'запрещён'),
                         (lambda: KD.group_body('g', 'i', 'low', 'c', 8000, {}, {}, work_type='ultratex', card='RTX 3050 Laptop (4 GB)'), 'вне профиля')):
    try:
        _bad_call()
        _got = ''
    except KD.ProfileRefused as _e:
        _got = str(_e)
    ok(_frag in _got, f'group_body реальным профилем: «{_frag}» → отказ')

SALAD_API = re.compile(r'\bgpu_classes\b|\bstorage_amount\b|container-groups')


def profile_bypass(text: str) -> list[str]:
    """Вызов `group_body(` без `work_type=` или со своими `resources=` — мимо профиля ресурсов."""
    out = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', None)
            if name == 'group_body':
                kws = {k.arg for k in n.keywords}
                if 'work_type' not in kws:
                    out.append(f'строка {n.lineno}: group_body без work_type — группа мимо профиля ресурсов')
                if 'resources' in kws:
                    out.append(f'строка {n.lineno}: group_body со своими resources — числа только из rules/salad-resources.json')
    return out


def api_bypass(text: str) -> list[str]:
    """Файл сам собирает ресурсы/классы групп Salad (gpu_classes, storage_amount, container-groups) мимо `kit_driver.group_body(work_type=…)`."""
    return ['сам собирает ресурсы/классы группы Salad (gpu_classes/storage_amount/container-groups) мимо профиля — зови KD.group_body(work_type=…) или внеси в kit-allow.txt с причиной'] if SALAD_API.search(text) else []


ok(profile_bypass('KD.group_body(n, i, t, c, 8000, e, a, work_type="x")') == [] and profile_bypass('KD.group_body(n, i, t, c, 8000, e, a)') and profile_bypass('group_body(n, i, t, c, 8000, e, a, work_type="x", resources={})'),
   'сторож профиля: group_body без work_type и со своими resources ловится')
ok(api_bypass("r = {'gpu_classes': [c]}") and api_bypass("requests.post(U + '/container-groups', json=b)") and not api_bypass('x = 1'), 'сторож профиля: самодельное тело группы / POST container-groups ловится')
_al = allow()
_n_gb = _n_api = 0
for path in files(lambda f: not f.startswith(('test', 'tests')) and f != 'kit_driver.py'):
    text = open(path, encoding='utf-8').read()
    pr = profile_bypass(text)
    if 'group_body' in text:
        _n_gb += 1
        ok(not pr, f'{rel(path)}: group_body только с work_type' if not pr else f'{rel(path)}: {"; ".join(pr)}')
    pr = api_bypass(text)
    if pr:
        if ('salad-api', rel(path)) in _al:
            ok(True, f'{rel(path)}: в списке исключений — {_al[("salad-api", rel(path))]}')
        else:
            ok(False, f'{rel(path)}: {"; ".join(pr)}')
        _n_api += 1
ok(_n_gb >= 2, f'драйверов с group_body найдено: {_n_gb}')

# воркер: пики и скорости диска в /health (профиль уточняется после каждого прогона)
_dt = KW.disk_speed_test(tempfile.mkdtemp(), 8)
ok(_dt.get('write_mb_s', 0) > 0 and _dt.get('read_mb_s', 0) > 0, f'замер диска на старте: запись/чтение МБ/с ({_dt})')
_st = KW.State()
_rv = _st.resources_view(1.0, '')
ok({'peak_rss_gb', 'peak_vram_gb', 'disk_free_gb', 'disk_mb_s', 'weights_gb_min'} <= set(_rv) and (_rv['peak_rss_gb'] or 0) > 0 and (_rv['disk_free_gb'] or 0) > 0,
   f'/health отдаёт peak_rss_gb, peak_vram_gb, disk_free_gb, disk_mb_s, weights_gb_min ({_rv})')
_st.disk_test = {'write_mb_s': 123.4, 'read_mb_s': 200.0}
_st.peak_gpu_mb = 20480.0
_st._w_hist = [(time.time() - 60, 1.0)]
_st.phase = 'weights'
_rv2 = _st.resources_view(7.0, '')
ok(_rv2['disk_mb_s'] == 123.4 and _rv2['peak_vram_gb'] == 20.0 and _rv2['weights_gb_min'] is not None and _rv2['weights_gb_min'] > 0, f'пик VRAM из nvidia-smi, скорость диска и докачки видны ({_rv2})')

# resource_profile.py --suggest: расхождения профиль ↔ замер (профиль правит человек, скрипт только печатает)
import resource_profile as RP  # noqa: E402
_sum = {'work_type': 'ultratex', 'last_health': {'body': {'peak_rss_gb': 44.0, 'peak_vram_gb': 25.2, 'disk_free_gb': 40.0, 'disk_mb_s': 310.0, 'disk_read_mb_s': 900.0, 'weights_gb_min': 0.95}},
        'jobs': {'k': {'status': 'done', 'wall_s': 341}}, 'disk_culls': 1, 'disk_slow_rates': [0.95]}
_sg = RP.suggest(_sum)
ok(any('RAM' in x and 'не влезает' in x for x in _sg), 'suggest: пик RAM 44 ГБ с запасом не влезает в 48 → поднять memory_mb')
ok(any('НИЖЕ нормы' in x for x in _sg) and any('пересаживал 1' in x for x in _sg) and any('среднее 341' in x for x in _sg), 'suggest: медленная докачка, пересадка и время задания видны')
ok(any('по оценке' in x for x in _sg), 'suggest: напоминает, что основание профиля — «по оценке»')
ok(any('не пришёл' in x for x in RP.suggest({'work_type': 'ultratex', 'last_health': {'body': {}}})), 'suggest: нет замера — так и говорит')
_sl = RP.suggest({'work_type': 'trellis_shape', 'last_health': {'body': {'peak_rss_gb': 30.2, 'peak_vram_gb': 11.6}}, 'jobs': [{'status': 'done', 'seconds': 200.0}, {'status': 'failed', 'seconds': 300.0}, {'status': 'done', 'seconds': 100.0}]})
ok(any('среднее 150' in x and 'n=2' in x for x in _sl), 'suggest: итог trellis_trial (jobs — список, время в seconds) тоже читается')

print('\nИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if not FAILS else f'ПРОВАЛОВ: {len(FAILS)}')
sys.exit(1 if FAILS else 0)

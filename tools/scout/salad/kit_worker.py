#!/usr/bin/env python3
"""НАБОР SALAD — СКЕЛЕТ ВОРКЕРА (T-20261121-178/2). Что у каждого воркера пробы одно и то же, лежит здесь; модель пишет только загрузку весов (`steps`), обработчики путей и свою работу.

ЧТО ДАЁТ (урок → функция):
  • 724/754 сервер на `::` (IPv6+IPv4): шлюз и пробы Salad ходят по IPv6 .............. `make_server`
  • 724 `/health` отвечает ДО докачки весов: фаза, папка весов (`root_gb`), карта, ошибка ... `KitHandler`, `State`, `dir_gb`, `cuda_info`
  • фоновая загрузка (фаза weights → loading → ready), ошибка → `broken` ................ `run_warm`
  • 742/745 образ без ядер под карту («no kernel image») → `broken` сразу ................. `gpu_selftest`
  • 744 фатальная ошибка CUDA → воркер больше не берёт задания ............................ `fatal_cuda`
  • автостоп `MAX_LIFETIME_S` / `IDLE_S` на самой ноде (страховка, если драйвер умер) ... `Watchdog`, `serve`
  • код воркера едет в env группы (образ не пересобирается) ................................ `bundle` (сам скелет — модулем `kit_worker`, модель — `__main__`)
Образец использования — `tools/scout/runpod/ultratex/worker_ultratex.py`. Сторож — `tests_kit.py` (воркер без набора или без `::` роняет тест).
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# ---------------------------------------------------------------- сервер на :: (урок 724)
class _DualStackServer(ThreadingHTTPServer):
    """Слушает `::` и принимает И IPv6, И IPv4: шлюз и пробы Salad ходят по IPv6 — сервер только на 0.0.0.0 им не отвечает («running, started=false, 503», урок 724)."""
    address_family = socket.AF_INET6

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass
        super().server_bind()


def make_server(port: int, handler, host: str | None = None) -> ThreadingHTTPServer:
    """Двойной стек (`::`), если в системе есть IPv6; иначе обычный 0.0.0.0. `host` — только для тестов."""
    if host is not None:
        return (_DualStackServer if ':' in host else ThreadingHTTPServer)((host, port), handler)
    if socket.has_ipv6:
        try:
            return _DualStackServer(('::', port), handler)
        except OSError:                                        # IPv6 в контейнере выключен — откат на IPv4
            pass
    return ThreadingHTTPServer(('0.0.0.0', port), handler)


# ---------------------------------------------------------------- состояние и /health
def dir_gb(path: str) -> float:
    """Сколько ГБ уже лежит в папке весов (с недокачанными кусками): ход докачки для сторожа драйвера. Нет папки — 0."""
    total = 0
    for dp, _dn, fn in os.walk(path):
        for f in fn:
            try:
                total += os.path.getsize(os.path.join(dp, f))
            except OSError:
                pass
    return round(total / 2 ** 30, 3)


def cuda_info() -> dict:
    """Карта и свободная память — для журнала драйвера; без torch/CUDA не падаем, и торч ради журнала не грузим."""
    try:
        torch = sys.modules.get('torch')
        if torch is None:
            return {'torch_loaded': False}
        if getattr(getattr(torch, '__spec__', None), '_initializing', False):      # torch прямо сейчас импортируется в потоке прогрева — не трогаем
            return {'torch_loaded': 'loading'}
        if not torch.cuda.is_available():
            return {'available': False}
        free, total = torch.cuda.mem_get_info()
        return {'available': True, 'name': torch.cuda.get_device_name(0), 'free_gb': round(free / 2 ** 30, 1), 'total_gb': round(total / 2 ** 30, 1)}
    except Exception as exc:                                   # noqa: BLE001
        return {'error': f'{type(exc).__name__}: {str(exc)[:80]}'}


def is_cuda_oom(exc: BaseException) -> bool:
    """Нехватка памяти карты: `torch.OutOfMemoryError` (по имени класса — без импорта torch) или «CUDA out of memory» в тексте."""
    low = str(exc).lower()
    return type(exc).__name__ == 'OutOfMemoryError' or ('out of memory' in low and 'cuda' in low)


def gpu_util_mem(run=None) -> tuple:
    """Загрузка GPU, % и занятая видеопамять, МБ — по nvidia-smi (то, что видит карта, не torch). Нет nvidia-smi/ответа — (None, None). `run` подставляется в тестах."""
    try:
        r = (run or subprocess.run)(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5)
        u, m = [x.strip() for x in r.stdout.strip().splitlines()[0].split(',')]
        return float(u), float(m)
    except Exception:  # noqa: BLE001
        return None, None


def disk_speed_test(path: str, mb: int = 256) -> dict:
    """Скорость диска ноды: запись `mb` МБ с fsync и чтение обратно (кэш страниц сброшен, где можно). {'write_mb_s', 'read_mb_s'} или {'error'}. Идёт ОДИН раз на старте воркера (T-186/1)."""
    p = os.path.join(path or '.', '.kit_disk_test')
    try:
        os.makedirs(path or '.', exist_ok=True)
        chunk = os.urandom(1 << 20)
        t0 = time.time()
        with open(p, 'wb') as f:
            for _ in range(mb):
                f.write(chunk)
            f.flush()
            os.fsync(f.fileno())
        tw = max(time.time() - t0, 1e-6)
        try:
            fd = os.open(p, os.O_RDONLY)
            os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            os.close(fd)
        except (AttributeError, OSError):
            pass
        t0 = time.time()
        with open(p, 'rb') as f:
            while f.read(1 << 20):
                pass
        tr = max(time.time() - t0, 1e-6)
        return {'write_mb_s': round(mb / tw, 1), 'read_mb_s': round(mb / tr, 1)}
    except OSError as exc:
        return {'error': f'{type(exc).__name__}: {str(exc)[:80]}'}
    finally:
        try:
            os.remove(p)
        except OSError:
            pass


def peak_rss_gb() -> float | None:
    """Пик ОЗУ процесса и его завершённых потомков, ГБ (ru_maxrss: на Linux — КБ). Нет модуля `resource` — None."""
    try:
        import resource
        kb = max(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss)
        return round(kb / 2 ** 20, 2)
    except (ImportError, OSError, ValueError):
        return None


def peak_vram_gb(extra_mb: float | None = None) -> float | None:
    """Пик видеопамяти, ГБ: max(`torch.cuda.max_memory_allocated` если torch уже загружен, пик занятого по nvidia-smi из `State.peak_gpu_mb`). Нет ни того ни другого — None."""
    vals = []
    try:
        torch = sys.modules.get('torch')
        if torch is not None and not getattr(getattr(torch, '__spec__', None), '_initializing', False) and torch.cuda.is_available():
            vals.append(torch.cuda.max_memory_allocated(0) / 2 ** 30)
    except Exception:  # noqa: BLE001
        pass
    if extra_mb:
        vals.append(extra_mb / 1024)
    return round(max(vals), 2) if vals else None


class State:
    def __init__(self):
        self.phase = 'weights'
        self.weights: dict = {}
        self.error = ''
        self.jobs: dict[str, dict] = {}
        self.busy = False
        self.lock = threading.Lock()
        self.t_start = time.time()
        self._cpu = (time.time(), sum(os.times()[:2]))            # прошлый замер CPU процесса — для `cores_now` в job_view
        self.peak_gpu_mb: float | None = None                     # пик занятой видеопамяти по nvidia-smi за жизнь воркера (job_view)
        self.disk_test: dict | None = None                        # замер диска на старте (`disk_speed_test`) — профиль ресурсов уточняется по нему (T-186/1)
        self._w_hist: list = []                                   # (время, ГБ папки весов) для `weights_gb_min`
        self.job: dict | None = None                              # ход ТЕКУЩЕГО задания: виден в /health (урок p4 21.11: 16 мин «busy» без видимого шага — не отличить медленное от зависшего)

    def begin_job(self, job_id: str) -> None:
        now = time.time()
        self.job = {'id': job_id, 't0': now, 'step': 'старт', 'step_t': now, 'done': [], 'line': None}

    def step(self, name: str, line: str | None = None) -> None:
        """Модель сообщает, на каком шаге она сейчас; прошлый шаг уходит в `done` с длительностью. `line` — последняя строка лога модели (для /health)."""
        j = self.job
        if j is None:
            return
        if line is not None:
            j['line'] = str(line).strip()[:160]
        if j['step'] == name:
            return
        now = time.time()
        j['done'].append([j['step'], round(now - j['step_t'], 1)])
        j['step'], j['step_t'] = name, now

    def note(self, line: str) -> None:
        """Последняя строка лога модели без смены шага (вывод субпроцесса, прогресс сэмплера)."""
        if self.job is not None and str(line).strip():
            self.job['line'] = str(line).strip()[:160]

    def end_job(self) -> None:
        self.job = None

    def resources_view(self, root_gb: float | None, root_dir: str = '') -> dict:
        """Пики и скорости для профиля ресурсов (T-186/1): `peak_rss_gb`, `peak_vram_gb`, `disk_free_gb`, `disk_mb_s` (замер на старте), `weights_gb_min` (рост папки весов за фазу weights)."""
        now = time.time()
        if self.phase == 'weights' and root_gb is not None:
            if not self._w_hist or root_gb != self._w_hist[-1][1]:
                self._w_hist.append((now, float(root_gb)))
        rate = None
        if len(self._w_hist) >= 2 and self._w_hist[-1][0] > self._w_hist[0][0]:
            (t0, g0), (t1, g1) = self._w_hist[0], self._w_hist[-1]
            rate = round((g1 - g0) / ((t1 - t0) / 60), 2)
        try:
            free = round(shutil.disk_usage(root_dir if root_dir and os.path.isdir(root_dir) else '/').free / 2 ** 30, 1)
        except OSError:
            free = None
        dt = self.disk_test or {}
        return {'peak_rss_gb': peak_rss_gb(), 'peak_vram_gb': peak_vram_gb(self.peak_gpu_mb), 'disk_free_gb': free,
                'disk_mb_s': dt.get('write_mb_s'), 'disk_read_mb_s': dt.get('read_mb_s'), 'weights_gb_min': rate}

    def job_view(self) -> dict | None:
        j = self.job
        if j is None:
            return None
        now = time.time()
        util, mem = gpu_util_mem()
        if mem is not None:
            self.peak_gpu_mb = max(self.peak_gpu_mb or 0.0, mem)
        t_prev, cpu_prev = self._cpu
        cpu = sum(os.times()[:2])
        cores = round((cpu - cpu_prev) / max(now - t_prev, 1e-6), 2) if now - t_prev >= 1.0 else None      # ядер CPU, занятых процессом (user+sys всех потоков) с прошлого просмотра
        if cores is not None:
            self._cpu = (now, cpu)
        return {'id': j['id'], 'elapsed_s': round(now - j['t0']), 'step': j['step'], 'step_s': round(now - j['step_t']), 'done': list(j['done'])[-12:],
                'line': j.get('line'), 'gpu_util': util, 'gpu_mem_mb': mem, 'cores_now': cores}          # урок b1 21.11 (P3-SAM): 15 мин молчания — шаг, секунды шага, GPU %, последняя строка лога


class Watchdog:
    """Решает, пора ли процессу выйти. Время и «занят» подаёт вызывающий (проверяется тестом без сна)."""

    def __init__(self, max_lifetime_s: float, idle_s: float, now=time.time):
        self.now, self.max_lifetime_s, self.idle_s = now, max_lifetime_s, idle_s
        self.t0 = now()
        self.last_activity = self.t0

    def touch(self):
        self.last_activity = self.now()

    def verdict(self, ready: bool, busy: bool) -> str | None:
        t = self.now()
        if t - self.t0 >= self.max_lifetime_s:
            return f'предел жизни {self.max_lifetime_s:.0f} с'
        if ready and not busy and t - self.last_activity >= self.idle_s:
            return f'простой {self.idle_s:.0f} с без заданий'
        return None


def fatal_cuda(exc: BaseException) -> bool:
    """Фатальная ошибка CUDA: процесс после неё живёт испорченным (урок 744) — новых заданий не берём. Сюда же нехватка памяти карты (CUDA OOM портит аллокатор: следующее задание падает INTERNAL ASSERT handles_, d1 UltraTex 21.11) и сам этот assert. Воркер ставит phase=broken, драйвер гасит ноду."""
    s = str(exc)
    return 'CUDA error' in s or 'illegal memory access' in s or 'no kernel image' in s or 'device-side assert' in s or 'INTERNAL ASSERT' in s or is_cuda_oom(exc)


def gpu_selftest() -> None:
    """Первый шаг прогрева: одна операция на карте. Образ без ядер под эту карту (sm_120 при torch<2.7, уроки 742/745) падает здесь, а не после часа докачки.
    Нет torch или CUDA (тест на CPU) — молча пропускаем."""
    try:
        import torch
    except ImportError:
        return
    if not torch.cuda.is_available():
        return
    x = torch.randn(64, 64, device='cuda')
    float((x @ x).sum().item())


class KitHandler(BaseHTTPRequestHandler):
    """Базовый обработчик: `/health` и `/shutdown` — здесь; пути модели — в `handle_get`/`handle_post` (вернуть True, если путь обработан).
    Класс-наследник получает `state`, `wd`, `stop`, `version`, `health_extra` через `KitHandler.bind(...)`."""
    state: State = None
    wd: Watchdog = None
    stop: threading.Event = None
    version = ''
    health_extra = staticmethod(lambda: {})
    root_dir = ''

    @classmethod
    def bind(cls, state: State, wd: Watchdog, stop: threading.Event, version: str, root_dir: str = '', health_extra=None, **attrs):
        """Привязка к состоянию; `attrs` — прочие атрибуты класса (например `engine=…`)."""
        return type(cls.__name__ + 'Bound', (cls,), {'state': state, 'wd': wd, 'stop': stop, 'version': version, 'root_dir': root_dir,
                                                      'health_extra': staticmethod(health_extra or (lambda: {})), **attrs})

    def log_message(self, fmt, *a):                            # тихо: журнал — в логгер воркера
        pass

    def send_json(self, code: int, obj) -> None:
        raw = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def send_bytes(self, code: int, data: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def read_json(self, max_bytes: int) -> dict | None:
        """Тело запроса как JSON; больше лимита или не JSON — сам отвечает 413/400 и возвращает None."""
        n = int(self.headers.get('Content-Length') or 0)
        if n > max_bytes:
            self.send_json(413, {'error': 'тело больше лимита'})
            return None
        try:
            return json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            self.send_json(400, {'error': 'не JSON'})
            return None

    def health_body(self) -> dict:
        s = self.state
        rg = dir_gb(self.root_dir) if self.root_dir else None
        return {'phase': s.phase, 'weights': s.weights, 'error': s.error, 'version': self.version, 'root_gb': rg,
                'cuda': cuda_info(), 'uptime_s': round(time.time() - s.t_start), 'busy': s.busy, 'job': s.job_view(), **s.resources_view(rg, self.root_dir), **self.health_extra()}

    def handle_get(self, path: str) -> bool:
        return False

    def handle_post(self, path: str) -> bool:
        return False

    def do_GET(self):                                          # noqa: N802
        if self.path != "/health":                              # /health дёргает readiness-проба самой платформы (каждые секунды) и опрос драйвера — это не работа: иначе сторож простоя не срабатывает никогда (T-34: тёплые ноды жили до предела жизни)
            self.wd.touch()
        if self.path == '/health':
            return self.send_json(200, self.health_body())
        if not self.handle_get(self.path):
            self.send_json(404, {'error': 'нет такого пути'})

    def do_POST(self):                                         # noqa: N802
        self.wd.touch()
        if self.path == '/shutdown':
            self.send_json(200, {'ok': True})
            self.stop.set()
            return
        if not self.handle_post(self.path):
            self.send_json(404, {'error': 'нет такого пути'})


def run_warm(state: State, wd: Watchdog, steps: list, log=None, selftest: bool = True) -> None:
    """Прогрев в фоне: `steps` = [(фаза, функция)] по порядку (обычно: ('weights', докачка), ('loading', загрузка в память)). Любое исключение → фаза `broken` и текст в `error`
    (драйвер видит его в /health и гасит ноду). Успех → `ready`."""
    try:
        if selftest:
            state.phase = 'weights'
            gpu_selftest()
        for phase, fn in steps:
            state.phase = phase
            fn()
        state.phase = 'ready'
        wd.touch()
    except Exception as exc:                                   # noqa: BLE001
        code = getattr(exc, 'code', None)                       # у исключения модели может быть свой код (WEIGHTS_DENIED: нет допуска к закрытым весам)
        state.phase, state.error = 'broken', (f'{code}: {exc}' if code else f'{type(exc).__name__}: {exc}')
        if log:
            log.error('прогрев упал: %s', traceback.format_exc())


def serve(handler_cls, state: State, wd: Watchdog, stop: threading.Event, steps: list, port: int | None = None, log=None, poll_s: float = 5.0) -> int:
    """Поднять сервер (`::`), запустить прогрев в фоне и ждать автостопа/`/shutdown`. Возвращает код выхода процесса."""
    port = port or int(os.environ.get('PORT', '8000'))
    srv = make_server(port, handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    root = getattr(handler_cls, 'root_dir', '') or ''
    test_dir = os.environ.get('KIT_DISK_TEST_DIR') or (os.path.dirname(root.rstrip('/')) if root else '') or '/tmp'      # НЕ в папке весов: файл замера сбил бы счёт докачки
    threading.Thread(target=lambda: setattr(state, 'disk_test', disk_speed_test(test_dir)), daemon=True).start()           # T-186/1: скорость диска ноды — в /health, профиль уточняется
    threading.Thread(target=run_warm, args=(state, wd, steps, log), daemon=True).start()
    while not stop.is_set():
        why = wd.verdict(state.phase == 'ready', state.busy)
        if why:
            if log:
                log.warning('АВТОСТОП: %s', why)
            break
        stop.wait(poll_s)
    if log:
        log.warning('выход процесса (под остановится сам)')
    srv.shutdown()
    return 0


# ---------------------------------------------------------------- доставка кода воркера в env группы (образ не пересобирается)
BOOT = ("import base64,json,os,sys,types,zlib;"
        "S=json.loads(zlib.decompress(base64.b64decode(os.environ['KIT_WORKER_Z'])));"
        "[(lambda m:(sys.modules.__setitem__(n,m),exec(compile(s,'/app/'+n+'.py','exec'),m.__dict__)))(types.ModuleType(n)) for n,s in S['mods'].items()];"
        "exec(compile(S['main'],'/app/worker.py','exec'),{'__name__':'__main__','__file__':'/app/worker.py'})")


def bundle(main_path: str, mods: dict[str, str] | None = None) -> tuple[list[str], str]:
    """Код воркера → (command, сжатый код для env `KIT_WORKER_Z`). `mods` = {имя модуля: путь} — модули набора (по умолчанию `kit_worker`), `main_path` — файл модели (`__main__`).
    На ноде модули регистрируются в sys.modules, поэтому `import kit_worker` в воркере работает и локально, и на Salad. Лимит Salad на элемент `command` — 1000 знаков (BOOT ≈ 450)."""
    here = os.path.dirname(os.path.abspath(__file__))
    mods = mods or {'kit_worker': os.path.join(here, 'kit_worker.py')}
    payload = {'mods': {n: open(p, encoding='utf-8').read() for n, p in mods.items()}, 'main': open(main_path, encoding='utf-8').read()}
    z = base64.b64encode(zlib.compress(json.dumps(payload).encode(), 9)).decode()
    return ['python', '-u', '-c', BOOT], z

#!/usr/bin/env python3
"""ВОРКЕР SALAD «КАМЕРА ПО ФОТО» (T-184/1, очередь 2): форма TRELLIS.2 (`<sku>-hd.glb`) + фото (RGBA PNG) → поза камеры `pose_fit` + вердикт `camera_check` (этап 04).
Работа — ЧИСТЫЙ CPU (numpy/cv2/scipy/Pillow/trimesh), видеокарта и torch не нужны: берём самый дешёвый класс Salad. Считает НАШ боевой код без правок — ровно те же команды, что у нашего
прогона (`pose_fit.py --glb --photo --out-run`, затем `camera_check.py --run --photo`), каждая в своём процессе; код цепочки лежит в образе (`Dockerfile.pose`, список — `pose_files.txt`),
сам воркер едет в env группы (`kit_worker.bundle`) — правка воркера образ не пересобирает.

HTTP (порт $PORT, 8000; сервер на `::` — kit_worker.make_server):
  GET  /health                 → {"phase": weights|loading|ready|broken, ...}; прогрев — секунды (веса не нужны), в `health` версии библиотек, модель CPU, число ядер
  POST /jobs                   {"job_id","glb_z"(zlib→base64 GLB),"photo_b64"(RGBA PNG),"yaw","px","n_fit","topk","role"(необязательно: роль каталога для метки типа 04)} → 202 (повтор того же job_id не дублирует работу)
  GET  /jobs/<id>              → {"status": queued|running|done|failed, "step", "metrics", "error", "sha256", "bytes"}
  GET  /jobs/<id>/result       → zip папки прогона (pose.json, stage_loss.json, pose_overlay.png, stages/…, 04-camera/…, логи); только при done
  POST /shutdown               → процесс завершается
Заданий идёт одновременно не больше POSE_PROCS (по ядру на процесс); остальные ждут в очереди ноды. Ход — в /health.job (`State.begin_job`/`step`): «считаю N, в очереди M, готово K из T».
АВТОСТОП: MAX_LIFETIME_S / IDLE_S (kit_worker.Watchdog); драйвер всё равно гасит группу сам и проверяет «0 нод».
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    import kit_worker as KW                                    # на Salad модуль набора зарегистрирован в sys.modules (KW.bundle)
except ImportError:                                            # локально (тесты, разбор): набор лежит рядом, в tools/scout/salad
    sys.path.insert(0, os.path.join(HERE, '..'))
    import kit_worker as KW

log = logging.getLogger('pose-worker')

VERSION = 'pose-worker-1'
MAX_BODY = 120 * 2 ** 20
JOB_RE = re.compile(r'^[A-Za-z0-9._\-]{1,150}$')
CLK = os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100


FIT_FLAG_NAMES = ('POSE_VERT_AXIS', 'POSE_JUNCTION', 'POSE_ANGLE_FIT', 'POSE_FLIP_ALWAYS')      # флаги подгонки (все выкл. по умолчанию), которые можно передать в подпроцесс (T-20261124-18); других имён не пускаем


def fit_flags(raw: str) -> dict:
    """`POSE_FIT_FLAGS="POSE_JUNCTION=1,POSE_VERT_AXIS=1"` → {имя: значение} только из FIT_FLAG_NAMES и значений 0/1/probe; пусто/мусор — {} (камера как без флагов)."""
    out = {}
    for part in (raw or '').split(','):
        k, _, v = part.strip().partition('=')
        if k in FIT_FLAG_NAMES and v in ('0', '1', 'probe'):
            out[k] = v
    return out


def cfg() -> dict:
    """Настройки из окружения группы (драйвер кладёт их в env; секретов тут нет)."""
    return {'code': os.environ.get('POSE_CODE', '/opt/scout/tools/scout/salad/trellis'),
            'work': os.environ.get('POSE_WORK', '/tmp/pose'),
            'procs': max(1, int(os.environ.get('POSE_PROCS', '6'))),
            'omp': os.environ.get('POSE_OMP', '1'),
            'flags': fit_flags(os.environ.get('POSE_FIT_FLAGS', '')),
            'fit_timeout': float(os.environ.get('POSE_FIT_TIMEOUT_S', '3600')),
            'check_timeout': float(os.environ.get('POSE_CHECK_TIMEOUT_S', '900'))}


def cpu_model() -> str:
    try:
        for ln in open('/proc/cpuinfo', encoding='utf-8', errors='replace'):
            if ln.lower().startswith('model name'):
                return ln.split(':', 1)[1].strip()[:80]
    except OSError:
        pass
    return ''


def proc_cpu_s(pid: int) -> float | None:
    """CPU-секунды процесса (user+sys) по /proc/<pid>/stat; нет процесса — None. Для хода задания и учёта «ядро-секунд на товар»."""
    try:
        rest = open(f'/proc/{pid}/stat', encoding='utf-8').read().rsplit(')', 1)[1].split()
        return (int(rest[11]) + int(rest[12])) / CLK
    except (OSError, IndexError, ValueError):
        return None


# ---------------------------------------------------------------- состояние: ход считает по CPU процессов-детей (nvidia-smi тут нет смысла)
class PoseState(KW.State):
    """`job_view` у набора берёт GPU % из nvidia-smi; у CPU-задания там пусто и сторож «завис» не мог бы отличить работу от простоя. Подменяем: `gpu_util` = загрузка ядер живыми
    процессами расчёта, % от числа этих процессов (≈100 — считают, <5 — стоят), `cores_now` = занятых ядер."""

    def __init__(self):
        super().__init__()
        self.pids: dict[int, float] = {}                       # pid → CPU-секунды на прошлом просмотре
        self._t_view = time.time()

    def job_view(self):
        j = super().job_view()
        if j is None:
            return None
        now = time.time()
        dt = max(now - self._t_view, 1e-6)
        used, n = 0.0, 0
        for pid, prev in list(self.pids.items()):
            cur = proc_cpu_s(pid)
            if cur is None:
                self.pids.pop(pid, None)
                continue
            n += 1
            used += max(cur - prev, 0.0)
            self.pids[pid] = cur
        self._t_view = now
        j['cores_now'] = round(used / dt, 2) if n else None
        j['gpu_util'] = round(min(100.0, 100.0 * used / dt / n), 1) if n and dt >= 1.0 else None      # CPU-загрузка живых процессов расчёта (имя поля — как у набора, чтобы драйвер не менять)
        j['gpu_mem_mb'] = None
        j['procs_live'] = n
        return j


# ---------------------------------------------------------------- пул заданий
def tail(path: str, n: int = 400) -> str:
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode('utf-8', 'replace').strip()
    except OSError:
        return ''


def pack_zip(out_dir: str, extra: dict[str, str]) -> bytes:
    """Все файлы папки прогона + логи → zip (сжатие — только текстовым и npz-пропуску не нужно); пути в архиве относительные."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for dp, _dn, fn in os.walk(out_dir):
            for f in sorted(fn):
                p = os.path.join(dp, f)
                z.write(p, os.path.relpath(p, out_dir))
        for name, p in extra.items():
            if os.path.isfile(p):
                z.write(p, name)
    return buf.getvalue()


def summarize(out_dir: str) -> dict:
    """Короткая сводка прогона для /jobs/<id>: поза и вердикт камеры (полные файлы — в zip)."""
    m: dict = {}
    try:
        pose = json.load(open(os.path.join(out_dir, 'pose.json'), encoding='utf-8'))
        m['camera'] = {k: round(float(pose['camera'][k]), 5) for k in ('az', 'el', 'd')}
        m['iou_frame'] = pose.get('iou_frame')
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        chk = json.load(open(os.path.join(out_dir, '04-camera', 'check.json'), encoding='utf-8'))
        m['passed'] = chk.get('passed')
        m['reason'] = str(chk.get('reason') or '')[:200]
    except (OSError, ValueError):
        pass
    return m


class Pool:
    """Очередь заданий ноды: до `procs` одновременно, остальные ждут. Один job_id — одна работа (повтор POST возвращает то же задание)."""

    def __init__(self, state: PoseState, c: dict, popen=subprocess.Popen, sleep=time.sleep):
        self.state, self.c, self.popen, self.sleep = state, c, popen, sleep
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.sem = threading.Semaphore(c['procs'])
        self.opened = False

    # --- учёт для /health
    def counts(self) -> dict:
        with self.lock:
            v = [j['status'] for j in self.jobs.values()]
        return {'total': len(v), 'queued': v.count('queued'), 'running': v.count('running'), 'done': v.count('done'), 'failed': v.count('failed')}

    def _refresh(self) -> None:
        n = self.counts()
        busy = n['queued'] + n['running'] > 0
        self.state.busy = busy
        if busy and not self.opened:
            self.state.begin_job('pose-batch')
            self.opened = True
        if self.opened:
            self.state.step(f"считаю {n['running']}, в очереди {n['queued']}, готово {n['done']}, отказов {n['failed']} из {n['total']}")
        if not busy and self.opened:
            self.state.end_job()
            self.opened = False

    def view(self, jid: str) -> dict | None:
        j = self.jobs.get(jid)
        if j is None:
            return None
        return {k: j.get(k) for k in ('job_id', 'status', 'step', 'metrics', 'error', 'sha256', 'bytes', 'files', 'wall_s', 'fit_s', 'check_s', 'cpu_s', 'queue_s')}

    # --- приём
    def submit(self, jid: str, glb: bytes, photo: bytes, params: dict) -> dict:
        with self.lock:
            if jid in self.jobs:
                return self.jobs[jid]
            d = os.path.join(self.c['work'], jid)
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, 'in.glb'), 'wb').write(glb)
            open(os.path.join(d, 'in.png'), 'wb').write(photo)
            j = {'job_id': jid, 'status': 'queued', 'step': 'очередь', 'dir': d, 'params': params, 't_in': time.time(), 'error': None, 'metrics': None}
            self.jobs[jid] = j
        threading.Thread(target=self._run, args=(j,), daemon=True).start()
        self._refresh()
        return j

    # --- расчёт
    def _cmd(self, script: str, args: list[str]) -> list[str]:
        return [sys.executable, '-I', os.path.join(self.c['code'], script)] + args

    def _exec(self, j: dict, name: str, cmd: list[str], timeout: float) -> tuple[int, float]:
        """Одна команда в своём процессе; вывод — в файл; по таймауту — kill СВОЕГО процесса. → (код, сек)."""
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'OMP_NUM_THREADS': self.c['omp'], 'OPENBLAS_NUM_THREADS': self.c['omp'], 'MKL_NUM_THREADS': self.c['omp'],
               'NUMEXPR_NUM_THREADS': self.c['omp'], 'HOME': os.environ.get('HOME', '/tmp'), **self.c.get('flags', {})}
        logp = os.path.join(j['dir'], f'{name}.log')
        t0 = time.time()
        with open(logp, 'wb') as lf:
            p = self.popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=j['dir'], env=env)
            pid = getattr(p, 'pid', 0)
            if pid:
                self.state.pids[pid] = proc_cpu_s(pid) or 0.0
            last = 0.0
            rc = None
            while rc is None:
                rc = p.poll()
                if rc is not None:
                    break
                c = proc_cpu_s(pid) if pid else None
                if c is not None:
                    last = c
                if time.time() - t0 > timeout:
                    p.kill()
                    p.wait()
                    rc = -9
                    j['error'] = f'{name}: дольше {timeout:.0f} с — снят'
                    break
                self.sleep(1.0)
                self.state.note(f"{j['job_id'][:40]} {name}: {tail(logp, 160).splitlines()[-1] if tail(logp, 160) else ''}")
        self.state.pids.pop(pid, None)
        j['cpu_s'] = round(j.get('cpu_s', 0.0) + last, 1)
        return rc, round(time.time() - t0, 1)

    def _run(self, j: dict) -> None:
        self.sem.acquire()
        try:
            j['status'], j['step'], j['t_run'] = 'running', 'pose_fit', time.time()
            j['queue_s'] = round(j['t_run'] - j['t_in'], 1)
            self._refresh()
            d, p = j['dir'], j['params']
            out = os.path.join(d, 'out')
            args = ['--glb', os.path.join(d, 'in.glb'), '--photo', os.path.join(d, 'in.png'), '--out-run', out]
            for k, flag in (('yaw', '--yaw'), ('px', '--px'), ('n_fit', '--n-fit'), ('topk', '--topk')):
                if p.get(k) is not None:
                    args += [flag, str(p[k])]
            _role = p.get('role')
            if isinstance(_role, str) and _role.strip() and len(_role) <= 60 and _role.isprintable():       # T-20261125-88: тип с перёдом (pose-rank.json: flip_always); без роли — как раньше
                args += ['--role', _role.strip()]
            rc, j['fit_s'] = self._exec(j, 'fit', self._cmd('pose_fit.py', args), self.c['fit_timeout'])
            if rc != 0:
                j['error'] = j['error'] or f"pose_fit rc={rc}: {tail(os.path.join(d, 'fit.log'), 300)}"
                raise RuntimeError(j['error'])
            j['step'] = 'camera_check'
            rc, j['check_s'] = self._exec(j, 'check', self._cmd('camera_check.py', check_args(out, os.path.join(d, 'in.png'), p)), self.c['check_timeout'])
            if rc != 0:
                j['error'] = j['error'] or f"camera_check rc={rc}: {tail(os.path.join(d, 'check.log'), 300)}"
                raise RuntimeError(j['error'])
            for need in ('pose.json', os.path.join('04-camera', 'check.json')):
                if not os.path.isfile(os.path.join(out, need)):
                    raise RuntimeError(f'нет файла результата {need}')
            data = pack_zip(out, {'fit.log': os.path.join(d, 'fit.log'), 'check.log': os.path.join(d, 'check.log')})
            zp = os.path.join(d, 'result.zip')
            open(zp, 'wb').write(data)
            j.update(zip=zp, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), files=len(zipfile.ZipFile(io.BytesIO(data)).namelist()), metrics=summarize(out),
                     wall_s=round(time.time() - j['t_in'], 1), status='done', step='готово')
        except Exception as exc:                               # noqa: BLE001 — причина всегда в error (молчаливых except нет)
            j['status'], j['step'] = 'failed', 'отказ'
            j['error'] = j['error'] or f'{type(exc).__name__}: {exc}'
            j['wall_s'] = round(time.time() - j['t_in'], 1)
            log.error('задание %s: %s', j['job_id'], traceback.format_exc())
        finally:
            self.sem.release()
            self._refresh()


# ---------------------------------------------------------------- HTTP
class PoseHandler(KW.KitHandler):
    pool: Pool = None

    def handle_get(self, path: str) -> bool:
        if path == '/jobs':
            self.send_json(200, {'jobs': [self.pool.view(k) for k in list(self.pool.jobs)], **self.pool.counts()})
            return True
        m = re.match(r'^/jobs/([A-Za-z0-9._\-]+)(/result)?$', path)
        if not m:
            return False
        v = self.pool.view(m.group(1))
        if v is None:
            self.send_json(404, {'error': 'нет такого задания'})
        elif not m.group(2):
            self.send_json(200, v)
        elif v['status'] != 'done':
            self.send_json(409, {'error': f"результата нет: статус {v['status']}"})
        else:
            self.send_bytes(200, open(self.pool.jobs[m.group(1)]['zip'], 'rb').read(), 'application/zip')
        return True

    def handle_post(self, path: str) -> bool:
        if path != '/jobs':
            return False
        if self.state.phase != 'ready':
            self.send_json(503, {'error': f'нода не готова: фаза {self.state.phase}', 'detail': self.state.error})
            return True
        b = self.read_json(MAX_BODY)
        if b is None:
            return True
        jid = str(b.get('job_id') or '')
        if not JOB_RE.match(jid):
            self.send_json(400, {'error': 'job_id: буквы, цифры, . _ -, до 150 знаков'})
            return True
        if jid in self.pool.jobs:
            self.send_json(202, {'job_id': jid, 'status': self.pool.jobs[jid]['status'], 'repeat': True})
            return True
        try:
            glb = zlib.decompress(base64.b64decode(b['glb_z']))
            photo = base64.b64decode(b['photo_b64'])
        except (KeyError, ValueError, zlib.error):
            self.send_json(400, {'error': 'нужны glb_z (zlib→base64 GLB) и photo_b64 (PNG)'})
            return True
        if not glb[:4] == b'glTF' or not photo[:8] == b'\x89PNG\r\n\x1a\n':
            self.send_json(400, {'error': 'вход не GLB/PNG'})
            return True
        params = {k: b.get(k) for k in ('yaw', 'px', 'n_fit', 'topk', 'role')}
        j = self.pool.submit(jid, glb, photo, params)
        self.send_json(202, {'job_id': jid, 'status': j['status']})
        return True


def check_args(out: str, photo: str, p: dict) -> list[str]:
    """Аргументы camera_check.py. `--role` (T-20261124-57: метка типа white_plate, только запись; без неё и при enabled=false метка не пишется) — если роль пришла в задании: короткая строка без управляющих символов."""
    args = ['--run', out, '--photo', photo]
    role = p.get('role')
    if isinstance(role, str) and role.strip() and len(role) <= 60 and role.isprintable():
        args += ['--role', role.strip()]
    return args


def selfcheck(c: dict) -> dict:
    """Прогрев: цепочка импортируется, нужные библиотеки на месте (образ собран верно). Ошибка → /health broken, драйвер гасит ноду, деньги не жжём."""
    code = ('import sys,json;sys.path[:0]=[%r,%r,%r];import numpy,cv2,scipy,PIL,trimesh,pose_fit,camera_check,stages_cpu,worker_trellis,tex_coverage,photo_front;'
            'print(json.dumps({"python":sys.version.split()[0],"numpy":numpy.__version__,"cv2":cv2.__version__,"scipy":scipy.__version__,"pillow":PIL.__version__,"trimesh":trimesh.__version__}))'
            % (c['code'], os.path.normpath(os.path.join(c['code'], '..', '..')), os.path.normpath(os.path.join(c['code'], '..'))))
    r = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise RuntimeError(f'образ не годится: цепочка pose_fit не импортируется: {(r.stderr or r.stdout)[-400:]}')
    return json.loads(r.stdout.strip().splitlines()[-1])


def make_handler(state: PoseState, pool: Pool, wd, stop, info: dict):
    return PoseHandler.bind(state, wd, stop, VERSION, health_extra=lambda: {'libs': info.get('libs'), 'cpu_model': info.get('cpu_model'), 'cpus': info.get('cpus'), 'pool': pool.counts(),
                                                                          'procs': pool.c['procs'], 'omp': pool.c['omp']}, pool=pool)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    c = cfg()
    os.makedirs(c['work'], exist_ok=True)
    state = PoseState()
    wd = KW.Watchdog(float(os.environ.get('MAX_LIFETIME_S', '7200')), float(os.environ.get('IDLE_S', '900')))
    stop = threading.Event()
    pool = Pool(state, c)
    try:
        cpus = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        cpus = os.cpu_count()
    info = {'cpu_model': cpu_model(), 'cpus': cpus}

    def warm():
        info['libs'] = selfcheck(c)
        state.weights = {'note': 'веса не нужны', 'code': c['code']}

    log.info('воркер %s: процессов %s, OMP %s, код %s, CPU %s ×%s', VERSION, c['procs'], c['omp'], c['code'], info['cpu_model'], cpus)
    return KW.serve(make_handler(state, pool, wd, stop, info), state, wd, stop, [('loading', warm)], log=log)


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""ВОРКЕР SALAD «ЭТАПЫ 06/07 КОНВЕЙЕРА ПОКРАСКИ» (T-189/1): перенос фото на форму (`tex_visible.py`) и заливка невидимого (`tex_fill.py`) на процессоре ноды (профиль `cpu_stage`).
Считает НАШ боевой код без правок логики — тот же файл, что у локального счёта (в образе, `Dockerfile.stage`, список — `stage_files.txt`); воркер едет в env группы (`kit_worker.bundle`).
Видеокарта не нужна (у Salad нет класса без неё — берём самую дешёвую, профиль `cpu_stage`).

HTTP (порт $PORT, 8000; сервер на `::` — kit_worker.make_server):
  GET  /health                 → {"phase", ..., "pool", "procs", "fill_procs", "peak_stage_gb": {"06": …, "07": …}}  — пик памяти этапа (ГБ), по нему правится строка профиля
  POST /jobs                   {"job_id","stage":"06"|"07","sku","input_z"(zlib→base64 zip входа),"body_only"} → 202 (повтор того же job_id не дублирует)
        вход 06: zip с `model.glb`, `photo.png`, `pose_run/…` (папка камеры этапа 4: stage_loss.json, stages/render_view0/*, 04-camera/check.json)
        вход 07: zip с `06-visible/…` (выход этапа 6: visible.glb, known*.png, check.json) и необязательным `parts.npz`
  GET  /jobs/<id>              → {"status": queued|running|done|failed, "step", "metrics", "error", "sha256", "bytes", "files", "wall_s", "queue_s", "run_s", "peak_gb"}
  GET  /jobs/<id>/result       → zip выхода этапа (`06-visible/…` или `07-fill/…`); только при done
  POST /shutdown               → процесс завершается
Одновременно идёт не больше STAGE_PROCS заданий (по умолчанию 4), из них этапа 07 — не больше STAGE_FILL_PROCS (по умолчанию 2: пик памяти 07 до 9 ГБ при 8 ГБ ноды, замер heavy-slot 22.11).
«Этап не прошёл» (код 1 у 06: камера/покрытие не годятся) — НЕ отказ воркера: выход и check.json есть, status=done, metrics.passed=false. Отказ (failed) — только сбой запуска/нет выхода/таймаут.
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

log = logging.getLogger('stage-worker')

VERSION = 'stage-worker-1'
MAX_BODY = 160 * 2 ** 20
MAX_UNPACK = 600 * 2 ** 20
JOB_RE = re.compile(r'^[A-Za-z0-9._\-]{1,150}$')
STAGES = ('06', '07')
# вход этапа 6: что обязано лежать в zip (то же, что проверяет tex_visible.load_stage); без этого — отказ до запуска, а не «упало внутри»
NEED_06 = ('model.glb', 'photo.png', 'pose_run/stage_loss.json', 'pose_run/stages/render_view0/ids.npz', 'pose_run/stages/render_view0/uv.npz',
           'pose_run/stages/render_view0/depth.npz', 'pose_run/stages/render_view0/aoi_cos16.png', 'pose_run/stages/render_view0/mask.png')
NEED_07 = ('06-visible/visible.glb', '06-visible/check.json')
# запуск этапа в обёртке: пик памяти ПОТОМКА (ru_maxrss, КБ) пишется в файл — число в /health, по нему поправят строку профиля
RUNNER = ("import resource,subprocess,sys;r=subprocess.run(sys.argv[2:]);"
          "open(sys.argv[1],'w').write(str(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss));sys.exit(r.returncode)")


def cfg() -> dict:
    """Настройки из окружения группы (драйвер кладёт их в env; секретов тут нет)."""
    return {'code': os.environ.get('STAGE_CODE', '/opt/scout-root'),
            'work': os.environ.get('STAGE_WORK', '/tmp/stage'),
            'python': os.environ.get('STAGE_PYTHON', sys.executable),
            'procs': max(1, int(os.environ.get('STAGE_PROCS', '4'))),
            'fill_procs': max(1, int(os.environ.get('STAGE_FILL_PROCS', '2'))),
            'threads': max(1, int(os.environ.get('STAGE_THREADS', '1'))),
            'timeout': float(os.environ.get('STAGE_TIMEOUT_S', '900'))}


def script_path(c: dict, stage: str) -> str:
    return os.path.join(c['code'], 'tools', 'scout', 'salad', 'trellis', 'tex_visible.py' if stage == '06' else 'tex_fill.py')


def safe_extract(data: bytes, dest: str, limit: int = MAX_UNPACK) -> list[str]:
    """Распаковка zip только внутрь `dest`: без абсолютных путей, `..`, ссылок и «бомб» (сумма распакованного ≤ limit). Возвращает список имён файлов."""
    z = zipfile.ZipFile(io.BytesIO(data))
    total, names = 0, []
    root = os.path.realpath(dest)
    for i in z.infolist():
        n = i.filename
        if n.endswith('/'):
            continue
        if n.startswith('/') or '..' in n.split('/') or '\\' in n or ((i.external_attr >> 16) & 0o170000) == 0o120000:
            raise ValueError(f'небезопасное имя в архиве: {n[:80]}')
        total += i.file_size
        if total > limit:
            raise ValueError(f'архив распаковывается в {total / 2 ** 20:.0f} МБ — больше лимита {limit / 2 ** 20:.0f} МБ')
        p = os.path.realpath(os.path.join(dest, n))
        if not p.startswith(root + os.sep):
            raise ValueError(f'имя вне папки: {n[:80]}')
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with z.open(i) as src, open(p, 'wb') as out:
            out.write(src.read())
        names.append(n)
    return names


def pack_zip(src_dir: str) -> bytes:
    """Выход этапа → zip (пути относительно папки выхода); .pyc и кэши не берём."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for dp, dn, fn in os.walk(src_dir):
            dn[:] = [d for d in dn if d != '__pycache__']
            for f in sorted(fn):
                p = os.path.join(dp, f)
                z.write(p, os.path.relpath(p, src_dir))
    return buf.getvalue()


def tail(path: str, n: int = 400) -> str:
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode('utf-8', 'replace').strip()
    except OSError:
        return ''


def stage_command(c: dict, stage: str, jdir: str, sku: str, body_only: bool, has_parts: bool, peak_file: str) -> tuple[list[str], str, str]:
    """(команда, папка выхода этапа, имя папки этапа). Команды — те же, что у локального счёта (`tex_visible.py` CLI, `tex_fill.py run_stage`)."""
    py, script = c['python'], script_path(c, stage)
    base = [py, '-c', RUNNER, peak_file, py, '-I', script]
    out = os.path.join(jdir, 'out')
    if stage == '06':
        cmd = base + (['--body-only'] if body_only else []) + [os.path.join(jdir, 'in', 'model.glb'), os.path.join(jdir, 'in', 'photo.png'), os.path.join(jdir, 'in', 'pose_run'), out, sku]
        return cmd, out, '06-visible'
    cmd = base + ['run_stage', out, sku, '--visible', os.path.join(jdir, 'in', '06-visible')]
    cmd += ['--parts-npz', os.path.join(jdir, 'in', 'parts.npz')] if has_parts else ['--no-parts-npz']
    return cmd, out, '07-fill'


def find_stage_dir(out: str, name: str) -> str | None:
    """`<out>/<sku-безопасное-имя>/<этап>` — единственная такая папка."""
    try:
        for d in sorted(os.listdir(out)):
            p = os.path.join(out, d, name)
            if os.path.isdir(p) and os.listdir(p):
                return p
    except OSError:
        pass
    return None


class Pool:
    """Очередь заданий ноды: до `procs` одновременно, из них этапа 07 — до `fill_procs`. Один job_id — одна работа (повтор POST возвращает то же задание)."""

    def __init__(self, state, c: dict, popen=subprocess.Popen, sleep=time.sleep):
        self.state, self.c, self.popen, self.sleep = state, c, popen, sleep
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.sem = threading.Semaphore(c['procs'])
        self.sem_fill = threading.Semaphore(c['fill_procs'])
        self.opened = False
        self.peak: dict[str, float] = {}

    def counts(self) -> dict:
        with self.lock:
            v = [j['status'] for j in self.jobs.values()]
        return {'total': len(v), 'queued': v.count('queued'), 'running': v.count('running'), 'done': v.count('done'), 'failed': v.count('failed')}

    def _refresh(self) -> None:
        n = self.counts()
        busy = n['queued'] + n['running'] > 0
        self.state.busy = busy
        if busy and not self.opened:
            self.state.begin_job('stage-batch')
            self.opened = True
        if self.opened:
            self.state.step(f"считаю {n['running']}, в очереди {n['queued']}, готово {n['done']}, отказов {n['failed']} из {n['total']}; пик памяти {self.peak}")
        if not busy and self.opened:
            self.state.end_job()
            self.opened = False

    def view(self, jid: str) -> dict | None:
        j = self.jobs.get(jid)
        if j is None:
            return None
        return {k: j.get(k) for k in ('job_id', 'status', 'step', 'metrics', 'error', 'sha256', 'bytes', 'files', 'wall_s', 'queue_s', 'run_s', 'peak_gb', 'stage', 'sku')}

    def submit(self, jid: str, stage: str, sku: str, files: dict[str, bytes] | bytes, body_only: bool) -> dict:
        with self.lock:
            if jid in self.jobs:
                return self.jobs[jid]
            d = os.path.join(self.c['work'], jid)
            os.makedirs(os.path.join(d, 'in'), exist_ok=True)
            names = safe_extract(files, os.path.join(d, 'in')) if isinstance(files, (bytes, bytearray)) else []
            j = {'job_id': jid, 'stage': stage, 'sku': sku, 'status': 'queued', 'step': 'очередь', 'dir': d, 'body_only': body_only, 'inputs': names, 't_in': time.time(),
                 'error': None, 'metrics': None}
            self.jobs[jid] = j
        threading.Thread(target=self._run, args=(j,), daemon=True).start()
        self._refresh()
        return j

    def _exec(self, j: dict, cmd: list[str]) -> int:
        """Этап в своём процессе; вывод — в файл; по таймауту — kill СВОЕГО процесса."""
        logp = os.path.join(j['dir'], 'stage.log')
        t0 = time.time()
        env = dict(os.environ, OMP_NUM_THREADS=str(self.c['threads']), OPENBLAS_NUM_THREADS=str(self.c['threads']), MKL_NUM_THREADS=str(self.c['threads']))
        with open(logp, 'wb') as lf:
            p = self.popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=j['dir'], env=env)
            while True:
                rc = p.poll()
                if rc is not None:
                    return rc
                if time.time() - t0 > self.c['timeout']:
                    p.kill()
                    p.wait()
                    j['error'] = f"этап {j['stage']}: дольше {self.c['timeout']:g} с — снят"
                    return -9
                self.sleep(2.0)
                j['step'] = f"этап {j['stage']}: {int(time.time() - t0)} с"
                self.state.note(f"{j['job_id'][:40]} {j['step']}: {(tail(logp, 160).splitlines() or [''])[-1][:140]}")

    def _run(self, j: dict) -> None:
        stage = j['stage']
        if stage == '07':
            self.sem_fill.acquire()                           # сначала «место для 07», потом общий слот: иначе 07 в ожидании держал бы слот
        self.sem.acquire()
        try:
            j['status'], j['t_run'] = 'running', time.time()
            j['queue_s'] = round(j['t_run'] - j['t_in'], 1)
            j['step'] = f'этап {stage}: старт'
            self._refresh()
            peak_file = os.path.join(j['dir'], 'peak_kb.txt')
            cmd, out, sname = stage_command(self.c, stage, j['dir'], j['sku'], j['body_only'], os.path.isfile(os.path.join(j['dir'], 'in', 'parts.npz')), peak_file)
            rc = self._exec(j, cmd)
            j['run_s'] = round(time.time() - j['t_run'], 1)
            try:
                j['peak_gb'] = round(int(open(peak_file).read().strip()) / 2 ** 20, 3)
                self.peak[stage] = max(self.peak.get(stage, 0.0), j['peak_gb'])
            except (OSError, ValueError):
                j['peak_gb'] = None
            sdir = find_stage_dir(out, sname)
            chk = os.path.join(sdir, 'check.json') if sdir else ''
            ok_rc = (0, 1) if stage == '06' else (0,)           # 06: код 1 = «этап не прошёл» (выход есть); 07: только 0
            if rc not in ok_rc or not sdir or not os.path.isfile(chk):
                j['error'] = j['error'] or f"этап {stage} rc={rc}{'' if sdir else ', нет папки выхода'}: {tail(os.path.join(j['dir'], 'stage.log'), 400)}"
                raise RuntimeError(j['error'])
            check = json.load(open(chk, encoding='utf-8'))
            data = pack_zip(sdir)
            zp = os.path.join(j['dir'], 'result.zip')
            open(zp, 'wb').write(data)
            j.update(zip=zp, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), files=len(zipfile.ZipFile(io.BytesIO(data)).namelist()),
                     metrics={'passed': check.get('passed'), 'refused': check.get('refused'), 'reason': str(check.get('reason') or '')[:200], 'metric': check.get('metric'), 'rc': rc,
                              'seconds': check.get('seconds')},
                     wall_s=round(time.time() - j['t_in'], 1), status='done', step='готово')
        except Exception as exc:                               # noqa: BLE001 — причина всегда в error (молчаливых except нет)
            j['status'], j['step'] = 'failed', 'отказ'
            j['error'] = j['error'] or f'{type(exc).__name__}: {exc}'
            j['wall_s'] = round(time.time() - j['t_in'], 1)
            log.error('задание %s: %s', j['job_id'], traceback.format_exc())
        finally:
            self.sem.release()
            if stage == '07':
                self.sem_fill.release()
            self._refresh()


def missing_inputs(stage: str, names: list[str]) -> list[str]:
    need = NEED_06 if stage == '06' else NEED_07
    return [n for n in need if n not in names]


class StageHandler(KW.KitHandler):
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
        jid, stage, sku = str(b.get('job_id') or ''), str(b.get('stage') or ''), str(b.get('sku') or '')
        if not JOB_RE.match(jid):
            self.send_json(400, {'error': 'job_id: буквы, цифры, . _ -, до 150 знаков'})
            return True
        if stage not in STAGES or not sku or len(sku) > 150:
            self.send_json(400, {'error': f'stage — одно из {list(STAGES)}, sku — непустой, до 150 знаков'})
            return True
        if jid in self.pool.jobs:
            self.send_json(202, {'job_id': jid, 'status': self.pool.jobs[jid]['status'], 'repeat': True})
            return True
        try:
            data = zlib.decompress(base64.b64decode(b['input_z']))
            tmp = io.BytesIO(data)
            names = [n for n in zipfile.ZipFile(tmp).namelist() if not n.endswith('/')]
        except (KeyError, ValueError, zlib.error, zipfile.BadZipFile):
            self.send_json(400, {'error': 'нужен input_z (zlib→base64 zip входа)'})
            return True
        miss = missing_inputs(stage, names)
        if miss:
            self.send_json(400, {'error': f'во входе этапа {stage} нет файлов: {miss}'})
            return True
        try:
            j = self.pool.submit(jid, stage, sku, data, bool(b.get('body_only')))
        except ValueError as exc:
            self.send_json(400, {'error': str(exc)})
            return True
        self.send_json(202, {'job_id': jid, 'status': j['status']})
        return True


def selfcheck(c: dict) -> dict:
    """Прогрев: библиотеки этапов на месте и код в образе (иначе нода не годится — деньги не жжём)."""
    import importlib
    info: dict = {'python': sys.version.split()[0]}
    for mod in ('numpy', 'scipy', 'trimesh', 'PIL', 'cv2'):
        try:
            info[mod] = getattr(importlib.import_module(mod), '__version__', 'ok')
        except ImportError as exc:
            raise RuntimeError(f'образ не годится: нет библиотеки {mod}: {exc}') from exc
    for st in STAGES:
        if not os.path.isfile(script_path(c, st)):
            raise RuntimeError(f'образ не годится: нет кода этапа {st}: {script_path(c, st)}')
    return info


def make_handler(state, pool: Pool, wd, stop, info: dict):
    return StageHandler.bind(state, wd, stop, VERSION, health_extra=lambda: {'libs': info, 'pool': pool.counts(), 'procs': pool.c['procs'], 'fill_procs': pool.c['fill_procs'],
                                                                             'peak_stage_gb': dict(pool.peak)}, pool=pool)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    c = cfg()
    os.makedirs(c['work'], exist_ok=True)
    state = KW.State()
    wd = KW.Watchdog(float(os.environ.get('MAX_LIFETIME_S', '7200')), float(os.environ.get('IDLE_S', '900')))
    stop = threading.Event()
    pool = Pool(state, c)
    info: dict = {}

    def warm():
        info.update(selfcheck(c))
        state.weights = {'note': 'веса не нужны', 'code': c['code']}

    log.info('воркер %s: процессов %s (07 — %s), код %s', VERSION, c['procs'], c['fill_procs'], c['code'])
    return KW.serve(make_handler(state, pool, wd, stop, info), state, wd, stop, [('loading', warm)], log=log)


if __name__ == '__main__':
    sys.exit(main())

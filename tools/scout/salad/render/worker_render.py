#!/usr/bin/env python3
"""ВОРКЕР SALAD «КАДРЫ ФОРМ» (T-184/1, очередь 3): форма TRELLIS.2 (`<sku>-hd.glb`) → кадры приёмки (виды × свет, глина) на видеокарте ноды — Blender 4.5.9 Cycles CUDA.
Считает НАШ боевой код без правок логики: команду Blender строит `tools/ops/forms_render.render_cmd` (виды и свет — таблицы `VIEW_DEFS`/`ACCEPT_LIGHTS` оттуда же), кадры рисует
`tools/scout/stablegen/render_stand.py` (новое только `--device GPU`: нет CUDA — код 3, на процессор молча не падаем). Код лежит в образе (`Dockerfile.render`, список — `render_files.txt`),
сам воркер едет в env группы (`kit_worker.bundle`) — правка воркера образ не пересобирает.

HTTP (порт $PORT, 8000; сервер на `::` — kit_worker.make_server):
  GET  /health                 → {"phase": weights|loading|ready|broken, ...}; прогрев — секунды: Blender запускается, CUDA-устройство видно (иначе broken — деньги не жжём)
  POST /jobs                   {"job_id","glb_z"(zlib→base64 GLB),"views":["az000",…],"lights":["key","graze"],"samples","w","h","shade"} → 202 (повтор того же job_id не дублирует)
  GET  /jobs/<id>              → {"status": queued|running|done|failed, "step", "metrics", "error", "sha256", "bytes"}
  GET  /jobs/<id>/result       → zip кадров (NN_<вид>_clay[_graze].png, bbox.json, render.log); только при done
  POST /shutdown               → процесс завершается
Одновременно идёт не больше RENDER_PROCS заданий (по умолчанию 2: видеокарте хватает, а разбор формы идёт на процессоре). Ход — в /health.job: «кадр K из N» (число готовых PNG), GPU % — из nvidia-smi набора.
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
import types
import zipfile
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    import kit_worker as KW                                    # на Salad модуль набора зарегистрирован в sys.modules (KW.bundle)
except ImportError:                                            # локально (тесты, разбор): набор лежит рядом, в tools/scout/salad
    sys.path.insert(0, os.path.join(HERE, '..'))
    import kit_worker as KW

log = logging.getLogger('render-worker')

VERSION = 'render-worker-1'
MAX_BODY = 120 * 2 ** 20
JOB_RE = re.compile(r'^[A-Za-z0-9._\-]{1,150}$')


def cfg() -> dict:
    """Настройки из окружения группы (драйвер кладёт их в env; секретов тут нет)."""
    return {'code': os.environ.get('RENDER_CODE', '/opt/scout-root'),
            'work': os.environ.get('RENDER_WORK', '/tmp/render'),
            'blender': os.environ.get('BLENDER_BIN', '/opt/blender/blender'),
            'device': os.environ.get('RENDER_DEVICE', 'GPU'),
            'procs': max(1, int(os.environ.get('RENDER_PROCS', '2'))),
            'threads': max(1, int(os.environ.get('RENDER_THREADS', '4'))),
            'timeout': float(os.environ.get('RENDER_TIMEOUT_S', '1500'))}


def load_forms_render(c: dict):
    """`forms_render` из кода образа: он импортирует `paint_run_report` только ради поиска GLB (воркеру не нужен, тянет пол-репозитория) — на время импорта подставляем пустышку.
    Константы пути Blender и render_stand переопределяем под образ."""
    ops = os.path.join(c['code'], 'tools', 'ops')
    if ops not in sys.path:
        sys.path.insert(0, ops)
    saved = sys.modules.get('paint_run_report')
    sys.modules['paint_run_report'] = types.ModuleType('paint_run_report')
    sys.modules.pop('forms_render', None)
    try:
        import forms_render as FR
    finally:
        if saved is None:
            sys.modules.pop('paint_run_report', None)
        else:
            sys.modules['paint_run_report'] = saved
    FR.BLENDER = c['blender']
    FR.RENDER_STAND = os.path.join(c['code'], 'tools', 'scout', 'stablegen', 'render_stand.py')
    return FR


def tail(path: str, n: int = 400) -> str:
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode('utf-8', 'replace').strip()
    except OSError:
        return ''


def count_png(d: str) -> int:
    try:
        return sum(1 for f in os.listdir(d) if f.endswith('.png'))
    except OSError:
        return 0


def pack_zip(out_dir: str, extra: dict[str, str]) -> bytes:
    """Кадры и сопутствующие файлы → zip (PNG уже сжаты — кладём без повторного сжатия); пути в архиве относительные."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for dp, _dn, fn in os.walk(out_dir):
            for f in sorted(fn):
                p = os.path.join(dp, f)
                z.write(p, os.path.relpath(p, out_dir))
        for name, p in extra.items():
            if os.path.isfile(p):
                z.write(p, name)
    return buf.getvalue()


class Pool:
    """Очередь заданий ноды: до `procs` одновременно, остальные ждут. Один job_id — одна работа (повтор POST возвращает то же задание)."""

    def __init__(self, state, c: dict, fr, popen=subprocess.Popen, sleep=time.sleep):
        self.state, self.c, self.fr, self.popen, self.sleep = state, c, fr, popen, sleep
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self.sem = threading.Semaphore(c['procs'])
        self.opened = False

    def counts(self) -> dict:
        with self.lock:
            v = [j['status'] for j in self.jobs.values()]
        return {'total': len(v), 'queued': v.count('queued'), 'running': v.count('running'), 'done': v.count('done'), 'failed': v.count('failed')}

    def _refresh(self) -> None:
        n = self.counts()
        busy = n['queued'] + n['running'] > 0
        self.state.busy = busy
        if busy and not self.opened:
            self.state.begin_job('render-batch')
            self.opened = True
        if self.opened:
            frames = sum(j.get('frames_now', 0) for j in list(self.jobs.values()) if j['status'] == 'running')
            self.state.step(f"рисую {n['running']}, в очереди {n['queued']}, готово {n['done']}, отказов {n['failed']} из {n['total']}; кадров в работе {frames}")
        if not busy and self.opened:
            self.state.end_job()
            self.opened = False

    def view(self, jid: str) -> dict | None:
        j = self.jobs.get(jid)
        if j is None:
            return None
        return {k: j.get(k) for k in ('job_id', 'status', 'step', 'metrics', 'error', 'sha256', 'bytes', 'files', 'wall_s', 'render_s', 'queue_s')}

    def submit(self, jid: str, glb: bytes, params: dict) -> dict:
        with self.lock:
            if jid in self.jobs:
                return self.jobs[jid]
            d = os.path.join(self.c['work'], jid)
            os.makedirs(d, exist_ok=True)
            open(os.path.join(d, 'in.glb'), 'wb').write(glb)
            j = {'job_id': jid, 'status': 'queued', 'step': 'очередь', 'dir': d, 'params': params, 't_in': time.time(), 'error': None, 'metrics': None, 'frames_now': 0}
            self.jobs[jid] = j
        threading.Thread(target=self._run, args=(j,), daemon=True).start()
        self._refresh()
        return j

    def _exec(self, j: dict, cmd: list[str], frames_dir: str, total: int) -> int:
        """Blender в своём процессе; вывод — в файл; ход = число готовых кадров; по таймауту — kill СВОЕГО процесса."""
        logp = os.path.join(j['dir'], 'render.log')
        t0 = time.time()
        with open(logp, 'wb') as lf:
            p = self.popen(cmd, stdout=lf, stderr=subprocess.STDOUT, cwd=j['dir'], env=dict(os.environ))
            rc = None
            while rc is None:
                rc = p.poll()
                if rc is not None:
                    break
                if time.time() - t0 > self.c['timeout']:
                    p.kill()
                    p.wait()
                    rc = -9
                    j['error'] = f"render: дольше {self.c['timeout']:g} с — снят"
                    break
                self.sleep(2.0)
                n = count_png(frames_dir)
                if n != j['frames_now']:
                    j['frames_now'] = n
                    j['step'] = f'кадр {n} из {total}'
                    self._refresh()
                self.state.note(f"{j['job_id'][:40]} кадр {n} из {total}: {(tail(logp, 160).splitlines() or [''])[-1][:140]}")
        return rc

    def _run(self, j: dict) -> None:
        self.sem.acquire()
        try:
            j['status'], j['t_run'] = 'running', time.time()
            j['queue_s'] = round(j['t_run'] - j['t_in'], 1)
            p = j['params']
            views, lights = tuple(p['views']), tuple(p['lights'])
            total = len(views) * len(lights)
            j['step'] = f'кадр 0 из {total}'
            self._refresh()
            out = os.path.join(j['dir'], 'out')
            fdir = os.path.join(out, 'f')
            cmd = self.fr.render_cmd(os.path.join(j['dir'], 'in.glb'), fdir, views, lights, int(p['samples']), self.c['threads'], p.get('shade') or 'orig', bool(p.get('alpha')))
            cmd = [x for x in cmd]
            cmd += ['--device', self.c['device']]
            # размер кадра: render_cmd задаёт 1200×900; другое — только явным параметром драйвера
            if p.get('w') and p.get('h'):
                i = cmd.index('--w')
                cmd[i + 1], cmd[cmd.index('--h') + 1] = str(int(p['w'])), str(int(p['h']))
            rc = self._exec(j, cmd, fdir, total)
            j['render_s'] = round(time.time() - j['t_run'], 1)
            if rc != 0:
                j['error'] = j['error'] or f"blender rc={rc}: {tail(os.path.join(j['dir'], 'render.log'), 300)}"
                raise RuntimeError(j['error'])
            got = self.fr.frames_of(out, 'f', views, lights)
            if not got:
                raise RuntimeError(f"кадров меньше ожидаемого {total}: {count_png(fdir)}; {tail(os.path.join(j['dir'], 'render.log'), 200)}")
            if p.get('alpha') and not self.fr.frames_of(fdir, self.fr.ALPHA_SUB, views, lights):
                raise RuntimeError(f"кадров с альфой меньше {total}: {count_png(os.path.join(fdir, self.fr.ALPHA_SUB))}")
            data = pack_zip(fdir, {'render.log': os.path.join(j['dir'], 'render.log')})
            zp = os.path.join(j['dir'], 'result.zip')
            open(zp, 'wb').write(data)
            gpu_line = ''
            for ln in tail(os.path.join(j['dir'], 'render.log'), 200000).splitlines():
                if ln.startswith('GPU:'):
                    gpu_line = ln[:120]
                    break
            j.update(zip=zp, sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), files=len(zipfile.ZipFile(io.BytesIO(data)).namelist()),
                     metrics={'frames': len(got), 'device': self.c['device'], 'gpu': gpu_line}, wall_s=round(time.time() - j['t_in'], 1), status='done', step='готово')
        except Exception as exc:                               # noqa: BLE001 — причина всегда в error (молчаливых except нет)
            j['status'], j['step'] = 'failed', 'отказ'
            j['error'] = j['error'] or f'{type(exc).__name__}: {exc}'
            j['wall_s'] = round(time.time() - j['t_in'], 1)
            log.error('задание %s: %s', j['job_id'], traceback.format_exc())
        finally:
            self.sem.release()
            self._refresh()


class RenderHandler(KW.KitHandler):
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
        except (KeyError, ValueError, zlib.error):
            self.send_json(400, {'error': 'нужен glb_z (zlib→base64 GLB)'})
            return True
        if glb[:4] != b'glTF':
            self.send_json(400, {'error': 'вход не GLB'})
            return True
        views, lights = b.get('views'), b.get('lights')
        fr = self.pool.fr
        if (not isinstance(views, list) or not views or any(v not in fr.VIEW_DEFS for v in views) or len(set(views)) != len(views)
                or not isinstance(lights, list) or not lights or any(x not in fr.ACCEPT_LIGHTS for x in lights) or len(set(lights)) != len(lights)):
            self.send_json(400, {'error': f'views — список из {sorted(fr.VIEW_DEFS)}, lights — из {list(fr.ACCEPT_LIGHTS)}, без повторов'})
            return True
        try:
            samples = int(b.get('samples', 16))
            w, h = int(b.get('w') or 0), int(b.get('h') or 0)
        except (TypeError, ValueError):
            self.send_json(400, {'error': 'samples/w/h — числа'})
            return True
        if not 1 <= samples <= 256 or w < 0 or h < 0 or w > 4096 or h > 4096 or (w == 0) != (h == 0) or b.get('shade', 'orig') not in ('orig', 'recalc', 'flat'):
            self.send_json(400, {'error': 'samples 1…256; w и h вместе, ≤4096; shade orig|recalc|flat'})
            return True
        j = self.pool.submit(jid, glb, {'views': views, 'lights': lights, 'samples': samples, 'w': w, 'h': h, 'shade': b.get('shade', 'orig'), 'alpha': bool(b.get('alpha'))})
        self.send_json(202, {'job_id': jid, 'status': j['status']})
        return True


def selfcheck(c: dict) -> dict:
    """Прогрев: Blender запускается; на режиме GPU — видна CUDA-карта (иначе нода не годится и деньги не жжём)."""
    r = subprocess.run([c['blender'], '-b', '--version'], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f'образ не годится: Blender не запускается: {(r.stderr or r.stdout)[-400:]}')
    info = {'blender': (r.stdout.strip().splitlines() or [''])[0], 'device': c['device']}
    if c['device'] == 'GPU':
        expr = ("import bpy,json;p=bpy.context.preferences.addons['cycles'].preferences;p.compute_device_type='CUDA';p.get_devices();"
                "print('DEV='+json.dumps([[d.name,d.type] for d in p.devices]))")
        r = subprocess.run([c['blender'], '-b', '--python-expr', expr], capture_output=True, text=True, timeout=180)
        line = next((ln for ln in r.stdout.splitlines() if ln.startswith('DEV=')), '')
        devs = json.loads(line[4:]) if line else []
        cuda = [d[0] for d in devs if d[1] == 'CUDA']
        if not cuda:
            raise RuntimeError(f'образ/нода не годятся: Blender не видит CUDA-карту (устройства: {devs}; {(r.stderr or "")[-200:]})')
        info['cuda'] = cuda
    return info


def make_handler(state, pool: Pool, wd, stop, info: dict):
    return RenderHandler.bind(state, wd, stop, VERSION, health_extra=lambda: {'blender': info.get('blender'), 'cuda': info.get('cuda'), 'device': pool.c['device'],
                                                                              'pool': pool.counts(), 'procs': pool.c['procs']}, pool=pool)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    c = cfg()
    os.makedirs(c['work'], exist_ok=True)
    state = KW.State()
    wd = KW.Watchdog(float(os.environ.get('MAX_LIFETIME_S', '7200')), float(os.environ.get('IDLE_S', '900')))
    stop = threading.Event()
    fr = load_forms_render(c)
    pool = Pool(state, c, fr)
    info: dict = {}

    def warm():
        info.update(selfcheck(c))
        state.weights = {'note': 'веса не нужны', 'code': c['code']}

    log.info('воркер %s: процессов %s, устройство %s, Blender %s, код %s', VERSION, c['procs'], c['device'], c['blender'], c['code'])
    return KW.serve(make_handler(state, pool, wd, stop, info), state, wd, stop, [('loading', warm)], log=log)


if __name__ == '__main__':
    sys.exit(main())

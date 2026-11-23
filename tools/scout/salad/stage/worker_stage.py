#!/usr/bin/env python3
"""ВОРКЕР SALAD «ЭТАПЫ КОНВЕЙЕРА ПОКРАСКИ» (T-189/1, T-193/1/1): перенос фото на форму (`tex_visible.py`), заливка невидимого (`tex_fill.py`), карта зон (`ref_zone.py`) и рендер без света на процессоре
ноды (профиль `cpu_stage`). Считает НАШ боевой код без правок логики. КОД ЭТАПА ЕДЕТ В ЗАДАНИИ (T-193/1/1): во входном zip — `code.tar` (срез репозитория по SHA, собирает драйвер `code_tar.py`
из `git archive`), в теле POST — `code_sha` и `code_tar_sha256`; образ — только среда (python, numpy, trimesh, opencv). Запечённый в образ код (`/opt/scout-root`) — запасной путь, по умолчанию ОТКЛЮЧЁН
(STAGE_ALLOW_BAKED=1 включает; нужен только пока гоняют старый образ без code.tar). Воркер едет в env группы (`kit_worker.bundle`).
Видеокарта не нужна (у Salad нет класса без неё — берём самую дешёвую, профиль `cpu_stage`).

HTTP (порт $PORT, 8000; сервер на `::` — kit_worker.make_server):
  GET  /health                 → {"phase", ..., "pool", "procs", "fill_procs", "peak_stage_gb": {"06": …, "07": …}}  — пик памяти этапа (ГБ), по нему правится строка профиля
  POST /jobs                   {"job_id","stage":"06"|"07"|"ref_zone"|"render_unlit" (whitelist; иное — 400),"sku","input_z"(zlib→base64 zip входа),"body_only",
                                "code_sha"(40 hex, обязателен),"code_tar_sha256"(обязателен, сверяется с code.tar),"args"(необязательно: проверенный список, см. `check_args`)} → 202 (повтор того же job_id не дублирует)
        вход любого задания: `code.tar` в zip (срез tools/** по SHA; распаковывается в `<задание>/code`, команда берётся ОТТУДА)
        вход 06: zip с `model.glb`, `photo.png`, `pose_run/…` (папка камеры этапа 4: stage_loss.json, stages/render_view0/*, 04-camera/check.json)
        вход 07: zip с `06-visible/…` (выход этапа 6: visible.glb, known*.png, check.json) и необязательным `parts.npz`
        вход ref_zone: что угодно (файлы идут в `args` как `@in/<путь>`); вход render_unlit: `model.glb`, аргументы `--yaw --pitch --size`
  GET  /jobs/<id>              → {"status": queued|running|done|failed, "step", "metrics", "error", "sha256", "bytes", "files", "wall_s", "queue_s", "run_s", "peak_gb", "code_sha", "code_tar_sha256", "cmd"}
  GET  /jobs/<id>/result       → zip выхода этапа (`06-visible/…`, `07-fill/…` или вся папка выхода для ref_zone/render_unlit) + `_code.json` (code_sha, sha256 tar, команда); только при done
  POST /shutdown               → процесс завершается
Одновременно идёт не больше STAGE_PROCS заданий (по умолчанию 4), из них этапа 07 — не больше STAGE_FILL_PROCS (по умолчанию 2: пик памяти 07 до 9 ГБ при 8 ГБ ноды, замер heavy-slot 22.11).
«Этап не прошёл» (код 1 у 06: камера/покрытие не годятся) — НЕ отказ воркера: выход и check.json есть, status=done, metrics.passed=false. Отказ (failed) — только сбой запуска/нет выхода/таймаут.
После задания рабочие папки `in/`, `code/`, `out/` на ноде удаляются (остаются result.zip и stage.log).
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
import shutil
import subprocess
import sys
import tarfile
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

VERSION = 'stage-worker-2'
MAX_BODY = 160 * 2 ** 20
MAX_UNPACK = 600 * 2 ** 20
MAX_CODE_UNPACK = 80 * 2 ** 20                                 # срез кода: trellis + rules + замыкание ≈ 2 МБ; больше 80 — не тот архив
SHA_RE = re.compile(r'^[0-9a-f]{40}$')
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
JOB_RE = re.compile(r'^[A-Za-z0-9._\-]{1,150}$')
STAGES = ('06', '07')                                          # этапы конвейера со своей папкой выхода (06-visible / 07-fill); их же гоняет драйвер пакета
# WHITELIST команд (T-193/1/1): имя в `stage` → скрипт в коде задания. Любая другая команда — отказ 400. Скрипт берётся из `<задание>/code` (из code.tar), не из образа.
COMMANDS = {
    '06': {'name': 'tex_visible', 'script': 'tools/scout/salad/trellis/tex_visible.py', 'out': '06-visible'},
    '07': {'name': 'tex_fill', 'script': 'tools/scout/salad/trellis/tex_fill.py', 'out': '07-fill'},
    'seam': {'name': 'seam_stage', 'script': 'tools/scout/salad/trellis/seam_stage.py', 'out': '07-seam'},      # T-196/1: сведение шва «фото | заливка» ПОСЛЕ 07 (вход 07-fill + 06-visible)
    '08': {'name': 'material_stage', 'script': 'tools/assets/material_stage.py', 'out': '08-material'},     # T-220/1: материал по частям ПОСЛЕ 07+шва (вход: filled.glb/seam.glb, части, карточка товара, 04/06 check)
    'ref_zone': {'name': 'ref_zone', 'script': 'tools/scout/salad/trellis/ref_zone.py', 'out': ''},
    'render_unlit': {'name': 'render_unlit', 'script': 'tools/scout/salad/recolor_lp.py', 'out': ''},   # модуль с render_unlit; запускается встроенной обёрткой RENDER, не как скрипт
}
CODE_DIRS = ('tools/scout/salad/trellis', 'tools/scout/salad', 'tools/scout')           # куда смотрит import этапа (первым — ближайший к этапу)
ARG_FLAG = re.compile(r'^--[a-z][a-z0-9-]{0,40}$')
ARG_WORD = re.compile(r'^(?:(?!-)[A-Za-z0-9._,:+=-]{1,80}|-[0-9][0-9.]{0,30})$')            # слово не с «-» (иначе «--Bad» прошёл бы как слово), кроме отрицательного числа
ARG_PATH = re.compile(r'^@in/[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-]+){0,6}$')
MAX_ARGS = 40
# вход этапа 6: что обязано лежать в zip (то же, что проверяет tex_visible.load_stage); без этого — отказ до запуска, а не «упало внутри»
NEED_06 = ('model.glb', 'photo.png', 'pose_run/stage_loss.json', 'pose_run/stages/render_view0/ids.npz', 'pose_run/stages/render_view0/uv.npz',
           'pose_run/stages/render_view0/depth.npz', 'pose_run/stages/render_view0/aoi_cos16.png', 'pose_run/stages/render_view0/mask.png')
NEED_07 = ('06-visible/visible.glb', '06-visible/check.json')
NEED_SEAM = ('06-visible/known.png', '07-fill/filled.glb')                                  # шов: маска «известно» этапа 6 и выход 07 (conf*.png — по возможности, нет — запасное)
# 08 (T-220/1): модель берётся из 07-seam/seam.glb, а без шва — из 07-fill/filled.glb; product.json — запись каталога {sid,name,role,params}; 04-camera и 06-visible check — для `photo_signal`
# (06-visible/known.png и visible.glb — цвет частей с фото); части этапа 3 `03-parts/parts.npz`+`parts.json` и `photo.png` — по возможности (нет — части по форме / без сверки тона)
NEED_08 = ('product.json', '04-camera/check.json', '06-visible/check.json')                # + модель: 07-seam/seam.glb ИЛИ 07-fill/filled.glb (missing_inputs)
MODEL_08 = ('07-seam/seam.glb', '07-fill/filled.glb')
FILL_STAGES = ('07', 'seam', '08')                                                           # этапы с большим пиком памяти: держат место из `fill_procs` (шов — на тех же текселях, что 07; 08 — карты по всему листу, пик замеряется пробой)
DRIVER_STAGES = STAGES + ('seam', '08')                                                         # что может гнать драйвер пакета (в образ-запас `seam` не входит: код только из задания)
NEED_RENDER = ('model.glb',)
# рендер без света (команда render_unlit): `recolor_lp.render_unlit` из кода задания; argv: <корень кода> <model.glb> <out.png> [--yaw --pitch --size]
RENDER = ("import sys,os,argparse\n"
          "root=sys.argv[1]\n"
          "for d in reversed(%r): sys.path.insert(0, os.path.join(root, d))\n"
          "import recolor_lp as LP\n"
          "ap=argparse.ArgumentParser(); ap.add_argument('glb'); ap.add_argument('out'); ap.add_argument('--yaw',type=float,default=0.0); ap.add_argument('--pitch',type=float,default=10.0); ap.add_argument('--size',type=int,default=960)\n"
          "a=ap.parse_args(sys.argv[2:]); os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)\n"
          "LP.render_unlit(a.glb, a.yaw, a.pitch, a.size).save(a.out)\n") % (CODE_DIRS,)
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
            'timeout': float(os.environ.get('STAGE_TIMEOUT_S', '900')),
            'allow_baked': os.environ.get('STAGE_ALLOW_BAKED', '0') == '1'}


def script_path(c: dict, stage: str, code_root: str | None = None) -> str:
    """Скрипт команды: из кода ЗАДАНИЯ (`code_root`), без него — из образа (только при STAGE_ALLOW_BAKED=1)."""
    return os.path.join(code_root or c['code'], *COMMANDS[stage]['script'].split('/'))


def check_args(args) -> list[str]:
    """Дополнительные аргументы команды: только `--флаг`, простые слова/числа, `@in/<путь во входе>` и `@out` (папка выхода). Остальное (пробелы, `;`, `$`, `..`, абсолютные пути) — ValueError."""
    if args is None:
        return []
    if not isinstance(args, list) or len(args) > MAX_ARGS or any(not isinstance(x, str) for x in args):
        raise ValueError(f'args: список строк, не больше {MAX_ARGS}')
    for x in args:
        if x == '@out' or ARG_FLAG.match(x) or ARG_WORD.match(x) or (ARG_PATH.match(x) and '..' not in x.split('/')):
            continue
        raise ValueError(f'args: недопустимый аргумент {x[:60]!r}')
    return list(args)


def expand_args(args: list[str], jdir: str, out: str) -> list[str]:
    """`@in/<путь>` → файл входа задания (должен существовать), `@out` → папка выхода."""
    res = []
    for x in args:
        if x == '@out':
            res.append(out)
        elif x.startswith('@in/'):
            p = os.path.realpath(os.path.join(jdir, 'in', x[4:]))
            if not p.startswith(os.path.realpath(os.path.join(jdir, 'in')) + os.sep) or not os.path.isfile(p):
                raise ValueError(f'args: нет файла во входе: {x}')
            res.append(p)
        else:
            res.append(x)
    return res


CODE_TAR_PREFIXES = ('tools/', 'data/flat3d/')                                  # куда code.tar может писать (код и его данные); остальное — отказ


def safe_untar(data: bytes, dest: str, limit: int = MAX_CODE_UNPACK) -> list[str]:
    """Распаковка code.tar только внутрь `dest`: обычные файлы и папки, пути только `tools/…` и `data/flat3d/…` (данные Ш3в: узоры верха, правила класса материала; T-187/7), без абсолютных, `..`, ссылок, устройств, бомб (сумма ≤ limit). Возвращает имена файлов."""
    root = os.path.realpath(dest)
    total, names = 0, []
    try:
        tf = tarfile.open(fileobj=io.BytesIO(data), mode='r:')
    except tarfile.TarError as exc:
        raise ValueError(f'code.tar не читается: {exc}') from exc
    with tf:
        for m in tf.getmembers():
            n = m.name
            if m.isdir():
                continue
            if not m.isreg():
                raise ValueError(f'code.tar: не обычный файл (ссылка/устройство): {n[:80]}')
            if n.startswith('/') or '..' in n.split('/') or '\\' in n or not n.startswith(CODE_TAR_PREFIXES):
                raise ValueError(f'code.tar: недопустимый путь: {n[:80]}')
            total += m.size
            if total > limit:
                raise ValueError(f'code.tar распаковывается в {total / 2 ** 20:.0f} МБ — больше лимита {limit / 2 ** 20:.0f} МБ')
            p = os.path.realpath(os.path.join(dest, n))
            if not p.startswith(root + os.sep):
                raise ValueError(f'code.tar: путь вне папки: {n[:80]}')
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with tf.extractfile(m) as src, open(p, 'wb') as out:
                out.write(src.read())
            names.append(n)
    return names


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


def pack_zip(src_dir: str, extra: dict[str, bytes] | None = None) -> bytes:
    """Выход этапа → zip (пути относительно папки выхода); .pyc и кэши не берём; `extra` — добавочные файлы (`_code.json`)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as z:
        for dp, dn, fn in os.walk(src_dir):
            dn[:] = [d for d in dn if d != '__pycache__']
            for f in sorted(fn):
                p = os.path.join(dp, f)
                z.write(p, os.path.relpath(p, src_dir))
        for n, d in (extra or {}).items():
            z.writestr(n, d)
    return buf.getvalue()


def tail(path: str, n: int = 400) -> str:
    try:
        with open(path, 'rb') as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - n))
            return f.read().decode('utf-8', 'replace').strip()
    except OSError:
        return ''


def stage_command(c: dict, stage: str, jdir: str, sku: str, body_only: bool, has_parts: bool, peak_file: str, code_root: str | None = None,
                  args: list[str] | None = None) -> tuple[list[str], str, str]:
    """(команда, папка выхода, имя папки этапа). Команды — те же, что у локального счёта (`tex_visible.py` CLI, `tex_fill.py run_stage`); скрипт — из `code_root` (код задания).
    `args` (уже проверенные и раскрытые `check_args`/`expand_args`) дописываются в конец команды. У ref_zone/render_unlit папка выхода — вся `out`, имя этапа пустое."""
    py, script = c['python'], script_path(c, stage, code_root)
    out = os.path.join(jdir, 'out')
    extra = list(args or [])
    base = [py, '-c', RUNNER, peak_file, py, '-I']
    if stage == '06':
        cmd = base + [script] + (['--body-only'] if body_only else []) + [os.path.join(jdir, 'in', 'model.glb'), os.path.join(jdir, 'in', 'photo.png'), os.path.join(jdir, 'in', 'pose_run'), out, sku]
        return cmd + extra, out, '06-visible'
    if stage == '07':
        cmd = base + [script, 'run_stage', out, sku, '--visible', os.path.join(jdir, 'in', '06-visible')]
        cmd += ['--parts-npz', os.path.join(jdir, 'in', 'parts.npz')] if has_parts else ['--no-parts-npz']
        return cmd + extra, out, '07-fill'
    if stage == 'seam':
        cmd = base + [script, out, sku, '--fill', os.path.join(jdir, 'in', '07-fill'), '--visible', os.path.join(jdir, 'in', '06-visible')]
        return cmd + extra, out, '07-seam'
    if stage == '08':
        inp = os.path.join(jdir, 'in')
        seam = os.path.join(inp, '07-seam', 'seam.glb')
        glb = seam if os.path.isfile(seam) else os.path.join(inp, '07-fill', 'filled.glb')          # шов есть — берём его модель, нет — выход 07 как есть (так же, как локально без шва)
        cmd = base + [script, 'stage', '--glb', glb, '--run', out, '--sku', sku, '--product', os.path.join(inp, 'product.json'), '--stages-dir', inp, '--no-frame']   # кадр — Blender, на ноде его нет
        if os.path.isfile(os.path.join(inp, '03-parts', 'parts.npz')) and os.path.isfile(os.path.join(inp, '03-parts', 'parts.json')):
            cmd += ['--parts-dir', os.path.join(inp, '03-parts')]
        if os.path.isfile(os.path.join(inp, 'photo.png')):
            cmd += ['--photo', os.path.join(inp, 'photo.png')]
        return cmd + extra, out, '08-material'
    if stage == 'render_unlit':
        return base + ['-c', RENDER, code_root or c['code'], os.path.join(jdir, 'in', 'model.glb'), os.path.join(out, 'render.png')] + extra, out, ''
    return base + [script] + extra, out, ''


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
        return {k: j.get(k) for k in ('job_id', 'status', 'step', 'metrics', 'error', 'sha256', 'bytes', 'files', 'wall_s', 'queue_s', 'run_s', 'peak_gb', 'stage', 'sku', 'code_sha', 'code_tar_sha256', 'cmd')}

    def submit(self, jid: str, stage: str, sku: str, files: dict[str, bytes] | bytes, body_only: bool, code_sha: str = '', code_tar_sha256: str = '', args: list[str] | None = None) -> dict:
        """Принять задание: распаковать вход, распаковать `code.tar` (если есть) в `<задание>/code`. Код — только из задания; без него — только при STAGE_ALLOW_BAKED=1 (запасной путь образа)."""
        if stage not in COMMANDS:
            raise ValueError(f'команда вне whitelist: {stage!r} (разрешены {list(COMMANDS)})')
        if not SHA_RE.match(code_sha or ''):
            raise ValueError('нет code_sha (40 hex) — без SHA кода задание не принимается')
        with self.lock:
            if jid in self.jobs:
                return self.jobs[jid]
            d = os.path.join(self.c['work'], jid)
            os.makedirs(os.path.join(d, 'in'), exist_ok=True)
            names = safe_extract(files, os.path.join(d, 'in')) if isinstance(files, (bytes, bytearray)) else []
            code_root = None
            if 'code.tar' in names:
                tar = open(os.path.join(d, 'in', 'code.tar'), 'rb').read()
                got = hashlib.sha256(tar).hexdigest()
                if not SHA256_RE.match(code_tar_sha256 or '') or got != code_tar_sha256:
                    raise ValueError(f'sha256 code.tar не сошёлся: заявлен {code_tar_sha256 or "—"}, получен {got}')
                safe_untar(tar, os.path.join(d, 'code'))
                code_root = os.path.join(d, 'code')
                if not os.path.isfile(script_path(self.c, stage, code_root)) and stage != 'render_unlit':
                    raise ValueError(f'в code.tar нет скрипта команды {stage}: {COMMANDS[stage]["script"]}')
                if stage == 'render_unlit' and not os.path.isfile(script_path(self.c, stage, code_root)):
                    raise ValueError(f'в code.tar нет модуля рендера: {COMMANDS[stage]["script"]}')
            elif not self.c.get('allow_baked'):
                raise ValueError('во входе нет code.tar, а запасной путь (код образа) отключён: STAGE_ALLOW_BAKED не 1')
            else:
                code_tar_sha256 = ''
            xargs = check_args(args)
            for x in xargs:
                if x.startswith('@in/') and not os.path.isfile(os.path.join(d, 'in', x[4:])):
                    raise ValueError(f'args: нет файла во входе: {x}')
            j = {'job_id': jid, 'stage': stage, 'sku': sku, 'status': 'queued', 'step': 'очередь', 'dir': d, 'body_only': body_only, 'inputs': names, 't_in': time.time(),
                 'error': None, 'metrics': None, 'code_sha': code_sha, 'code_tar_sha256': code_tar_sha256, 'code_root': code_root, 'args': xargs, 'cmd': COMMANDS[stage]['name']}
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
        if stage in FILL_STAGES:
            self.sem_fill.acquire()                           # сначала «место для 07», потом общий слот: иначе 07 в ожидании держал бы слот
        self.sem.acquire()
        try:
            j['status'], j['t_run'] = 'running', time.time()
            j['queue_s'] = round(j['t_run'] - j['t_in'], 1)
            j['step'] = f'этап {stage}: старт'
            self._refresh()
            peak_file = os.path.join(j['dir'], 'peak_kb.txt')
            xargs = expand_args(j['args'], j['dir'], os.path.join(j['dir'], 'out'))
            cmd, out, sname = stage_command(self.c, stage, j['dir'], j['sku'], j['body_only'], os.path.isfile(os.path.join(j['dir'], 'in', 'parts.npz')), peak_file,
                                            code_root=j.get('code_root'), args=xargs)
            rc = self._exec(j, cmd)
            j['run_s'] = round(time.time() - j['t_run'], 1)
            try:
                j['peak_gb'] = round(int(open(peak_file).read().strip()) / 2 ** 20, 3)
                self.peak[stage] = max(self.peak.get(stage, 0.0), j['peak_gb'])
            except (OSError, ValueError):
                j['peak_gb'] = None
            if sname:
                sdir = find_stage_dir(out, sname)
                chk = os.path.join(sdir, 'check.json') if sdir else ''
            else:                                               # ref_zone / render_unlit: выход — вся папка out, check.json не обязателен
                sdir = out if os.path.isdir(out) and any(f for _, _, fs in os.walk(out) for f in fs) else None
                chk = os.path.join(sdir, 'check.json') if sdir else ''
            ok_rc = (0, 1) if stage in ('06', '08') else (0,)   # 06 и 08: код 1 = «этап не прошёл» (выход и check.json есть; падение без check.json — всё равно отказ ниже); остальные: только 0
            if rc not in ok_rc or not sdir or (sname and not os.path.isfile(chk)):
                j['error'] = j['error'] or f"этап {stage} rc={rc}{'' if sdir else ', нет папки выхода'}: {tail(os.path.join(j['dir'], 'stage.log'), 400)}"
                raise RuntimeError(j['error'])
            check = json.load(open(chk, encoding='utf-8')) if os.path.isfile(chk) else {}
            meta = {'code_sha': j['code_sha'], 'code_tar_sha256': j['code_tar_sha256'], 'cmd': j['cmd'], 'stage': stage, 'worker': VERSION, 'args': j['args']}
            data = pack_zip(sdir, {'_code.json': json.dumps(meta, ensure_ascii=False, indent=1).encode()})
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
            for sub in ('in', 'code', 'out'):                  # на ноде остаются только result.zip и stage.log
                shutil.rmtree(os.path.join(j['dir'], sub), ignore_errors=True)
            self.sem.release()
            if stage in FILL_STAGES:
                self.sem_fill.release()
            self._refresh()


def missing_inputs(stage: str, names: list[str]) -> list[str]:
    need = {'06': NEED_06, '07': NEED_07, 'seam': NEED_SEAM, '08': NEED_08, 'render_unlit': NEED_RENDER}.get(stage, ())
    miss = [n for n in need if n not in names]
    if stage == '08' and not any(n in names for n in MODEL_08):
        miss.append(' или '.join(MODEL_08))
    return miss


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
        if stage not in COMMANDS or not sku or len(sku) > 150:
            self.send_json(400, {'error': f'stage — одно из {list(COMMANDS)} (whitelist команд), sku — непустой, до 150 знаков'})
            return True
        code_sha = str(b.get('code_sha') or '')
        if not SHA_RE.match(code_sha):
            self.send_json(400, {'error': 'нет code_sha (40 hex): без SHA кода задание не принимается'})
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
            j = self.pool.submit(jid, stage, sku, data, bool(b.get('body_only')), code_sha, str(b.get('code_tar_sha256') or ''), b.get('args'))
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
    info['code'] = 'baked+job' if c.get('allow_baked') else 'job'
    if c.get('allow_baked'):                                    # запасной путь: код в образе обязан быть; без него (код едет в задании) образ — только среда
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
        state.weights = {'note': 'веса не нужны', 'code': 'в задании (code.tar)' if not c.get('allow_baked') else c['code']}

    log.info('воркер %s: процессов %s (07 — %s), код %s', VERSION, c['procs'], c['fill_procs'], c['code'])
    return KW.serve(make_handler(state, pool, wd, stop, info), state, wd, stop, [('loading', warm)], log=log)


if __name__ == '__main__':
    sys.exit(main())

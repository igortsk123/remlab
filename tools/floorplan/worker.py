#!/usr/bin/env python3
"""Воркер DEV пробы для агентов (план agent-trial-01-upload-grey-tour, T-B): сам ходит на прод по HTTPS.

Цикл: предохранитель → POST /api/trial/worker/claim → GET …/<id>/input (файл) → `pipeline.py job` отдельным процессом
(PDF → PNG, VLM, стенд под heavy_slot) → конвейер мебели `conveyor.py` (версии страницы 1 → 2 → 3 на POST …/bundle; выключить —
TRIAL_FURNISH=0) → POST …/result; heartbeat сразу после claim, сразу при смене шага и не реже
раза в 10 с (шаг из `<папка>/stage`, деньги из `<папка>/spent`; время шага прод метит только по heartbeat), concurrency 1. Ошибка → POST …/fail {code, retryable}. 409 на любой ручке — аренда потеряна: процесс
стенда снимается, задание доделает тот, кто его забрал.
«Обустроить» (Р1): claim с `rebuilds: true` (при TRIAL_FURNISH) может вернуть `rebuild` вместо `job` — пересборка страницы готового
задания по кнопке агента (`process_rebuild` → `conveyor.Rebuild`: одна итоговая версия на …/rebuild/publish, аренда — …/rebuild/heartbeat,
сбой — …/rebuild/fail). Сервер ставит пересборки раньше новых загрузок, но не больше квоты подряд, пока загрузка ждёт.

Предохранитель (задание не брать, но отмечаться «жив» — claim с paused:true): MemAvailable < 3 ГБ; в общей очереди
тяжёлых ждут ≥ 2 класса пробы и выше (`tools/ops/heavy_slot.py:waiting`; наши обычные прогоны не в счёт — T-20261110-29); 3 сбоя подряд по нашей вине → пауза 10 мин; /api/health прода
не 200. Причина — только в журнал DEV (в базе её нет — поправка Codex 09.11).

Окружение: TRIAL_WORKER_TOKEN (обязателен; юнит берёт его из ~/.config/remlab/env), TRIAL_API_URL
(https://remont-lab.online), TRIAL_WORKER_ID (dev-<хост>), TRIAL_WORK_DIR (~/remlab-logs/trial), TRIAL_JOB_TIMEOUT_S (900),
TRIAL_MEM_MIN_GB (3), TRIAL_DEV_KEEP_HOURS (24 — рабочие папки заданий с файлом владельца; потом удаляются),
TRIAL_FP_CACHE (кэш analyze стенда, по умолчанию нет).

  python tools/floorplan/worker.py            # цикл (так запускает юнит remlab-trial-worker.service)
  python tools/floorplan/worker.py --check    # настройки (без токена) и предохранитель сейчас; заданий не берёт
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'ops'))
sys.path.insert(0, str(HERE))
import conveyor  # noqa: E402 — стадии мебели после стен
from conveyor import child_failure  # noqa: E402

VERSION = 'trial-worker/1'
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{22}$')       # = lib/token.ts:TOKEN_RE — id задания (и имя папки)
EXT = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'image/avif': '.avif', 'application/pdf': '.pdf'}
INPUT_MAX = 15 * 1024 * 1024
STAGES = ('raster', 'labels', 'walls', 'repair', 'export')
# = contracts/trial.ts:trialRebuildFailCode — коды сбоя пересборки «Обустроить»
REBUILD_CODES = ('stale', 'timeout', 'pipeline_error', 'internal', 'waiting_capacity', 'nothing_to_furnish', 'source_gone', 'no_match',
                 'cache_miss', 'edits_conflict', 'regress')   # последние три — «перечитать планировку» (T-20261111-02)
CLAIM_READ_MAX = 24 * 1024 * 1024    # claim `reparse` несёт и точные байты версии (≤ 8 МБ, экранированные в JSON) — как `reissue.READ_MAX`
USER_CODES = {'pdf_unreadable', 'unsupported', 'too_large', 'no_plan', 'budget'}   # вина файла, не DEV: в серию сбоев не идут


def log(msg: str) -> None:
    print(time.strftime('%Y-%m-%d %H:%M:%S'), msg, flush=True)


class NetError(Exception):
    pass


@dataclass
class Cfg:
    url: str = 'https://remont-lab.online'
    token: str = ''
    worker_id: str = ''
    base: Path = Path('~/remlab-logs/trial').expanduser()
    poll_s: float = 2.0
    heartbeat_s: float = 10.0
    stage_poll_s: float = 0.25                     # как часто смотреть `<папка>/stage`: смена шага → heartbeat сразу
    job_timeout_s: float = 900.0
    mem_min_gb: float = 3.0
    heavy_wait_max: int = 2
    fail_streak: int = 3
    fail_pause_s: float = 600.0
    health_every_s: float = 30.0
    keep_hours: float = 24.0
    vlm_keep_days: float = 30.0
    http_timeout: float = 30.0
    kill_grace_s: float = 10.0
    retry_s: float = 2.0
    meminfo: str = '/proc/meminfo'
    an_cache: str | None = None
    pipeline: list = field(default_factory=lambda: [sys.executable, str(HERE / 'pipeline.py')])
    # конвейер мебели после стен (`conveyor.py`): версии данных страницы 1 → 2 → 3, потом `done`
    furnish: bool = True
    python: str = sys.executable
    scenes_root: Path = Path(os.environ.get('TRIAL_SCENES_ROOT') or '~/scout-scenes/trial').expanduser()
    living_timeout_s: float = 1800.0             # с ожиданием общей очереди тяжёлых
    bedroom_timeout_s: float = 1800.0
    bundle_timeout_s: float = 180.0
    bundle_max_bytes: int = conveyor.BUNDLE_MAX_BYTES
    stage_cmds: dict | None = None               # тесты: свои команды стадий; None — настоящие скрипты

    @classmethod
    def from_env(cls, env=os.environ) -> 'Cfg':
        def f(k, d):
            try:
                return float(env.get(k, d))
            except ValueError:
                return d
        return cls(url=env.get('TRIAL_API_URL', 'https://remont-lab.online').rstrip('/'),
                   token=env.get('TRIAL_WORKER_TOKEN', ''),
                   worker_id=env.get('TRIAL_WORKER_ID') or f'dev-{socket.gethostname()}'[:64],
                   base=Path(env.get('TRIAL_WORK_DIR') or '~/remlab-logs/trial').expanduser(),
                   job_timeout_s=f('TRIAL_JOB_TIMEOUT_S', 900.0), mem_min_gb=f('TRIAL_MEM_MIN_GB', 3.0),
                   keep_hours=f('TRIAL_DEV_KEEP_HOURS', 24.0), an_cache=env.get('TRIAL_FP_CACHE') or None,
                   furnish=env.get('TRIAL_FURNISH', '1') != '0',
                   scenes_root=Path(env.get('TRIAL_SCENES_ROOT') or '~/scout-scenes/trial').expanduser(),
                   living_timeout_s=f('TRIAL_LIVING_TIMEOUT_S', 1800.0), bedroom_timeout_s=f('TRIAL_BEDROOM_TIMEOUT_S', 1800.0))

    @property
    def vlm_root(self) -> Path:
        return self.base / 'vlm-cache'


def mem_available_gb(path: str = '/proc/meminfo') -> float:
    with open(path, encoding='ascii') as fh:
        for ln in fh:
            if ln.startswith('MemAvailable:'):
                return int(ln.split()[1]) / 1048576
    raise RuntimeError('MemAvailable not found')


def heavy_waiting() -> int:
    """Сколько ждут в общей очереди тяжёлых DEV КЛАССОМ НЕ НИЖЕ ПРОБЫ (`heavy_slot.waiting(SLOT_PRIO_TRIAL)`, T-20261110-29):
    наши обычные прогоны (класс 0) задание не задерживают — оно идёт впереди них и в резерв пробы; ждут другие задания
    агентов — их и считаем. Не прочитать — 0."""
    try:
        import heavy_slot as hs
        if hasattr(hs, 'waiting'):
            return int(hs.waiting(conveyor.SLOT_PRIO_TRIAL))
        buf = io.StringIO()                           # старая версия очереди — как раньше, все ждущие
        hs.status(out=buf)
        m = re.search(r'ЖДУТ: (\d+)', buf.getvalue())
        return int(m.group(1)) if m else 0
    except Exception as e:  # noqa: BLE001 — нет папки очереди и т. п.: предохранитель по очереди не срабатывает
        log(f'heavy-slot status: {type(e).__name__}: {e}')
        return 0


class Api:
    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def call(self, method: str, path: str, body: dict | None = None, headers: dict | None = None,
             auth: bool = True, stream_to: Path | None = None, max_bytes: int = INPUT_MAX, read_max: int = 4 * 1024 * 1024):
        """→ (статус, JSON | None). stream_to — тело (файл) потоком на диск с потолком max_bytes. Сеть — NetError."""
        h = {'User-Agent': VERSION, **(headers or {})}
        if auth:
            h['Authorization'] = f'Bearer {self.cfg.token}'
        data = None
        if body is not None:
            data = json.dumps(body, separators=(',', ':')).encode()
            h['Content-Type'] = 'application/json'
        req = urllib.request.Request(self.cfg.url + path, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=self.cfg.http_timeout) as r:
                if stream_to is not None:
                    return r.status, self._stream(r, stream_to, max_bytes)
                raw = r.read(read_max)
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            try:
                raw = e.read(64 * 1024)
                return e.code, (json.loads(raw) if raw else None)
            except (ValueError, OSError):
                return e.code, None
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise NetError(f'{method} {path}: {type(e).__name__}: {str(e)[:200]}') from None

    @staticmethod
    def _stream(r, dest: Path, max_bytes: int) -> dict:
        n = 0
        tmp = dest.with_name(dest.name + '.part')
        with open(tmp, 'wb') as fh:
            while True:
                b = r.read(1 << 16)
                if not b:
                    break
                n += len(b)
                if n > max_bytes:
                    return {'too_large': True, 'bytes': n}
                fh.write(b)
        os.replace(tmp, dest)
        return {'bytes': n}


class Heartbeat(threading.Thread):
    """Продление аренды раз в heartbeat_s: шаг — из `<папка>/stage`, деньги — из `<папка>/spent`. 409 → lost."""

    def __init__(self, w: 'Worker', lease: dict, wd: Path, path: str = '/api/trial/worker/heartbeat', with_stage: bool = True):
        super().__init__(daemon=True)
        self.w, self.lease, self.wd = w, lease, wd
        self.path, self.with_stage = path, with_stage        # пересборка «Обустроить» — своя ручка, без шага
        self.stop_ev, self.lost = threading.Event(), threading.Event()
        self.sent = []

    def stage(self) -> str:
        try:
            s = (self.wd / 'stage').read_text().strip()
        except OSError:
            s = ''
        return s if s in STAGES else 'raster'

    def progress(self) -> dict | None:
        """Ход пересборки по комнатам (`<папка>/progress.json`, пишет `conveyor.EditRebuild`; T-20261111-16) — только у пересборки."""
        if self.with_stage:
            return None
        try:
            got = json.loads((self.wd / 'progress.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None
        return got if isinstance(got, dict) and isinstance(got.get('rooms'), dict) else None

    def beat(self) -> None:
        body = {**self.lease, 'spentUsd': self.w.spent(self.wd)}
        if self.with_stage:
            body['stage'] = self.stage()
        prog = self.progress()
        if prog is not None:
            body['progress'] = prog
        self.sent.append((time.time(), body.get('stage')))
        try:
            st, _ = self.w.api.call('POST', self.path, body)
        except NetError as e:
            log(f'{self.lease["id"]}: heartbeat: {e}')
            return
        if st == 409:
            log(f'{self.lease["id"]}: аренда потеряна (heartbeat 409)')
            self.lost.set()
        elif st != 200:
            log(f'{self.lease["id"]}: heartbeat {st}')

    def run(self) -> None:
        """Первый удар — сразу после claim (raster), дальше — при каждой смене шага (прод ставит метку времени шага
        только на heartbeat, `lib/trial/repo-worker.ts:heartbeat`) и не реже раза в heartbeat_s."""
        last_t, last_s = 0.0, None
        while not self.stop_ev.is_set() and not self.lost.is_set():
            s = (self.stage(), json.dumps(self.progress(), sort_keys=True))   # смена хода по комнатам — тоже удар сразу
            if s != last_s or time.time() - last_t >= self.w.cfg.heartbeat_s:
                self.beat()
                last_t, last_s = time.time(), s
            self.stop_ev.wait(min(self.w.cfg.stage_poll_s, self.w.cfg.heartbeat_s))


class Worker:
    def __init__(self, cfg: Cfg, api: Api | None = None, waiting=heavy_waiting):
        self.cfg, self.api, self.waiting = cfg, api or Api(cfg), waiting
        self.streak, self.pause_until = 0, 0.0
        self.health = (0.0, True)
        self.last_reason = None
        self.last_clean = 0.0
        self.stop = threading.Event()
        self.child: subprocess.Popen | None = None
        self.done: list = []                         # (id, итог) — для тестов и журнала

    # ── предохранитель ──
    def health_ok(self) -> bool:
        at, ok = self.health
        if time.time() - at < self.cfg.health_every_s:
            return ok
        try:
            st, _ = self.api.call('GET', '/api/health', auth=False)
            ok = st == 200
        except NetError:
            ok = False
        self.health = (time.time(), ok)
        return ok

    def breaker(self) -> str | None:
        if time.time() < self.pause_until:
            return f'fail_streak (пауза до {time.strftime("%H:%M:%S", time.localtime(self.pause_until))})'
        try:
            mem = mem_available_gb(self.cfg.meminfo)
            if mem < self.cfg.mem_min_gb:
                return f'memory {mem:.1f} GB < {self.cfg.mem_min_gb:g}'
        except (OSError, RuntimeError, ValueError) as e:
            return f'meminfo: {e}'
        n = self.waiting()
        if n >= self.cfg.heavy_wait_max:
            return f'heavy_queue {n} waiting'
        if not self.health_ok():
            return 'prod_health'
        return None

    # ── цикл ──
    def loop(self, max_iter: int | None = None) -> None:
        it = 0
        while not self.stop.is_set() and (max_iter is None or it < max_iter):
            it += 1
            self.janitor()
            reason = self.breaker()
            if reason != self.last_reason:
                log(f'предохранитель: {reason}' if reason else 'предохранитель: снят — беру задания')
                self.last_reason = reason
            try:
                st, body = self.api.call('POST', '/api/trial/worker/claim',
                                         {'workerId': self.cfg.worker_id, 'version': VERSION, 'paused': bool(reason),
                                          **({'rebuilds': True, 'listing': True, 'edit': True, 'reparse': True} if self.cfg.furnish else {})},
                                         read_max=CLAIM_READ_MAX)
            except NetError as e:
                log(f'claim: {e}')
                self.stop.wait(max(self.cfg.poll_s, 5))
                continue
            if st != 200:
                log(f'claim: {st} {(body or {}).get("error", "")}')
                self.stop.wait(max(self.cfg.poll_s, 10))
                continue
            job, rb = (body or {}).get('job'), (body or {}).get('rebuild')
            if job and not reason:
                self.process(job)
                continue
            if rb and not reason:
                self.process_rebuild(rb)
                continue
            self.stop.wait(self.cfg.poll_s)

    @staticmethod
    def spent(wd: Path) -> float:
        try:
            return max(0.0, min(100.0, float((wd / 'spent').read_text())))
        except (OSError, ValueError):
            return 0.0

    def _post(self, path: str, body: dict, tries: int = 5) -> int | None:
        """POST с повтором при обрыве (result идемпотентен: тот же хэш тела → 200). → статус или None."""
        for k in range(tries):
            try:
                st, resp = self.api.call('POST', path, body)
                if st < 500:
                    if st not in (200, 409):
                        log(f'{body.get("id")}: {path} {st} {json.dumps(resp, ensure_ascii=False)[:500]}')
                    return st
            except NetError as e:
                log(f'{body.get("id")}: {path}: {e}')
            if k + 1 < tries:
                time.sleep(min(30.0, self.cfg.retry_s * (k + 1)))
        return None

    @staticmethod
    def log(msg: str) -> None:
        log(msg)

    def post_json(self, path: str, body: dict, tries: int = 5) -> tuple[int | None, dict | None]:
        """Как `_post`, но с телом ответа (номер версии) — для `/bundle`. Повтор того же тела безопасен: тот же хэш → `repeated`."""
        for k in range(tries):
            try:
                st, resp = self.api.call('POST', path, body)
                if st < 500:
                    return st, resp
                self.log(f'{body.get("id")}: {path} {st}')
            except NetError as e:
                self.log(f'{body.get("id")}: {path}: {e}')
            if k + 1 < tries:
                time.sleep(min(30.0, self.cfg.retry_s * (k + 1)))
        return None, None

    def run_child(self, cmd: list, log_path: Path, timeout_s: float, hb: Heartbeat, env: dict | None = None) -> tuple[int | None, str | None]:
        """Процесс стадии в своей группе, вывод — в `log_path`. → (код выхода, причина снятия: lost | timeout | stop | None).
        Вывод Python — без буфера (`PYTHONUNBUFFERED`, T-20261110-05): процесс, убитый сигналом (OOM, earlyoom), оставляет в журнале
        всё, что успел напечатать (10.11 разбор листа упал через 456 с с пустым `pipeline.log`)."""
        env = {**(os.environ if env is None else env), 'PYTHONUNBUFFERED': '1'}
        with open(log_path, 'ab') as out:
            self.child = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                                          cwd=str(HERE.parent.parent), env=env)
            deadline = time.time() + timeout_s
            why = None
            while self.child.poll() is None:
                if hb.lost.is_set():
                    why = 'lost'
                elif time.time() > deadline:
                    why = 'timeout'
                elif self.stop.is_set():
                    why = 'stop'
                if why:
                    self._kill()
                    break
                time.sleep(0.2)
        rc, self.child = self.child.returncode, None
        if why is None and hb.lost.is_set():
            why = 'lost'
        return rc, why

    def fail(self, lease: dict, wd: Path, code: str, retryable: bool, detail: str = '', retry_after: int | None = None) -> None:
        body = {**lease, 'code': code, 'retryable': retryable, 'detail': detail[:2000], 'spentUsd': self.spent(wd)}
        if retry_after:
            body['retryAfterSec'] = int(retry_after)
        st = self._post('/api/trial/worker/fail', body)
        log(f'{lease["id"]}: fail {code} retryable={retryable} → {st}')
        self.done.append((lease['id'], f'fail:{code}:{st}'))
        if code != 'waiting_capacity' and code not in USER_CODES:
            self.streak += 1
            if self.streak >= self.cfg.fail_streak:
                self.pause_until = time.time() + self.cfg.fail_pause_s
                log(f'{self.streak} сбоя подряд — пауза {self.cfg.fail_pause_s:g} с')
                self.streak = 0

    def _kill(self) -> None:
        p = self.child
        if p is None or p.poll() is not None:
            return
        try:
            os.killpg(p.pid, signal.SIGTERM)
            p.wait(self.cfg.kill_grace_s)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
        except ProcessLookupError:
            pass

    def process(self, job: dict) -> None:
        jid = str(job.get('id', ''))
        lease = {'id': jid, 'attempt': int(job.get('attempt', 0)), 'leaseToken': str(job.get('leaseToken', ''))}
        mime = job.get('inputMime')
        if not TOKEN_RE.match(jid) or mime not in EXT:
            log(f'claim: странное задание {jid[:40]!r} {mime!r}')
            self.fail(lease, self.cfg.base, 'internal', False, 'bad job id or mime')
            return
        wd = self.cfg.base / jid / f'a{lease["attempt"]}-{time.strftime("%H%M%S")}'
        wd.mkdir(parents=True, exist_ok=True)
        log(f'{jid}: взял (попытка {lease["attempt"]}, {mime}, {job.get("inputBytes")} Б)')
        hb = Heartbeat(self, lease, wd)
        hb.start()
        t0 = time.time()
        try:
            self._process(job, lease, mime, wd, hb)
        finally:
            hb.stop_ev.set()
            hb.join(5)
            log(f'{jid}: {time.time() - t0:.1f} с')

    def _process(self, job: dict, lease: dict, mime: str, wd: Path, hb: Heartbeat) -> None:
        jid = lease['id']
        inp = wd / ('input' + EXT[mime])
        try:
            st, info = self.api.call('GET', f'/api/trial/worker/{jid}/input', stream_to=inp,
                                     headers={'X-Trial-Attempt': str(lease['attempt']), 'X-Trial-Lease': lease['leaseToken']})
        except NetError as e:
            return self.fail(lease, wd, 'internal', True, f'input: {e}')
        if st == 409:
            log(f'{jid}: аренда потеряна (input 409)')
            return
        if st != 200:
            return self.fail(lease, wd, 'internal', st >= 500, f'input http {st}')
        if (info or {}).get('too_large'):
            return self.fail(lease, wd, 'too_large', False, f'input > {INPUT_MAX} B')
        cmd = self.cfg.pipeline + ['job', '--input', str(inp), '--mime', mime, '--workdir', str(wd),
                                   '--vlm-root', str(self.cfg.vlm_root), f'--job-id={jid}',   # id с «-» в начале — не флаг (T-20261111-07)
                                   '--cap-usd', str(min(float(job.get('budgetUsd') or 0.10), 0.10))]
        if job.get('listingText'):
            (wd / 'listing.txt').write_text(str(job['listingText'])[:5000])
            cmd += ['--listing-file', str(wd / 'listing.txt')]
        if self.cfg.an_cache:
            cmd += ['--an-cache', self.cfg.an_cache]
        rc, why = self.run_child(cmd, wd / 'pipeline.log', self.cfg.job_timeout_s, hb,   # стены — класс загрузки тура (T-31)
                                 env={**os.environ, 'HEAVY_SLOT_PRIO': str(conveyor.SLOT_PRIO_TRIAL)})
        if why == 'lost':
            self.done.append((jid, 'lost'))
            return
        if why == 'timeout':
            return self.fail(lease, wd, 'timeout', False, f'pipeline > {self.cfg.job_timeout_s:g}s')
        if why == 'stop':                             # воркер останавливают: задание — назад в очередь без траты попытки
            return self.fail(lease, wd, 'waiting_capacity', True, 'worker stopping', 5)
        res_p, err_p = wd / 'result.json', wd / 'error.json'
        if rc == 0 and res_p.exists():
            res = json.loads(res_p.read_text())
            last = None
            if self.cfg.furnish:                     # стены готовы → версии страницы по очереди (`conveyor.py`), `done` — последним
                cv = conveyor.Conveyor(self, lease, wd, hb, res_p)
                end = cv.run()
                last = cv.last
                if end == 'lost':
                    self.done.append((jid, 'lost'))
                    return
                if end == 'stop':
                    return self.fail(lease, wd, 'waiting_capacity', True, 'worker stopping', 5)
            if self.result(lease, wd, res):
                conveyor.after_done(self, lease, wd, last)
            return
        if err_p.exists():
            e = json.loads(err_p.read_text())
            code = e.get('code') or 'pipeline_error'
            return self.fail(lease, wd, code, bool(e.get('retryable')), str(e.get('detail') or ''),
                             30 if code == 'waiting_capacity' else None)
        # убит сигналом (OOM, earlyoom) или упал без отчёта — один повтор (попыток 2); в причине — сигнал и хвост журнала
        why = child_failure('pipeline', rc, wd / 'pipeline.log')
        log(f'{jid}: {why}')
        self.fail(lease, wd, 'pipeline_error', True, why)

    # ── пересборка «Обустроить» (план agent-trial-08, Р1; T-20261109-27) ──
    def process_rebuild(self, rb: dict) -> None:
        """Пересборка от claim: аренда своя (id пересборки), результат стен — из Postgres (в ответе claim), итог — одна версия
        (`conveyor.Rebuild`). Потеря аренды — процессы стадий снимаются (`run_child` по `hb.lost`), ничего не публикуется."""
        rid, jid = str(rb.get('id', '')), str(rb.get('jobId', ''))
        lease = {'id': rid, 'attempt': int(rb.get('attempt', 0)), 'leaseToken': str(rb.get('leaseToken', ''))}
        if not TOKEN_RE.match(jid) or not TOKEN_RE.match(rid) or not isinstance(rb.get('result'), dict):
            log(f'claim: странная пересборка {rid[:40]!r} задания {jid[:40]!r}')
            self.fail_rebuild(lease, self.cfg.base, 'internal', False, 'bad rebuild id, job id or result')
            return
        wd = self.cfg.base / jid / f'r{lease["attempt"]}-{rid[:6]}-{time.strftime("%H%M%S")}'
        wd.mkdir(parents=True, exist_ok=True)
        res_p = wd / 'result.json'
        res_p.write_text(json.dumps(rb['result'], ensure_ascii=False))
        text, edit, reparse = rb.get('kind') == 'listing', rb.get('kind') == 'edit', rb.get('kind') == 'reparse'
        edits = rb.get('edits') if isinstance(rb.get('edits'), list) else []    # правки комнат агента — к любой пересборке (T-20261110-36)
        ops = rb.get('openingEdits') if isinstance(rb.get('openingEdits'), list) else []   # окна и двери агента — так же (T-20261110-39)
        mime = rb.get('inputMime')
        if text and (mime not in EXT or not str(rb.get('listingText') or '').strip()):
            log(f'claim: пересборка по тексту {rid} без листа/текста ({mime!r})')
            self.fail_rebuild(lease, wd, 'internal', False, 'listing rebuild without mime or text')
            return
        if reparse and (mime not in EXT or not isinstance(rb.get('bundle'), str)):
            log(f'claim: «перечитать планировку» {rid} без листа/версии ({mime!r})')
            self.fail_rebuild(lease, wd, 'internal', False, 'reparse without mime or bundle')
            return
        # текст агента в журнал не пишем — только его длину
        what = f'текст агента ({len(rb["listingText"])} зн.)' if text else ('правка комнаты' if edit else
                                                                          '«перечитать планировку»' if reparse else '«Обустроить»')
        log(f'{jid}: {what} {rid} (попытка {lease["attempt"]}, комнаты {rb.get("rooms")}, правок {len(edits)}, проёмов {len(ops)}, '
            f'версия страницы {rb.get("baseVersion")})')
        hb = Heartbeat(self, lease, wd, path='/api/trial/worker/rebuild/heartbeat', with_stage=False)
        hb.start()
        t0 = time.time()
        cv = None
        try:
            if reparse:
                cv = conveyor.Reparse(self, lease, wd, hb, res_p, jid, rb.get('rooms') or [], str(rb.get('listingText') or ''), mime,
                                      EXT[mime], rb['bundle'], edits=edits, opening_edits=ops, approved=self.reparse_approved(jid),
                                      draft_edits=rb.get('draftEdits') if isinstance(rb.get('draftEdits'), list) else [],
                                      draft_opening_edits=rb.get('draftOpeningEdits') if isinstance(rb.get('draftOpeningEdits'), list) else [])
                end = cv.rebuild()
            elif text:
                end = conveyor.ListingRebuild(self, lease, wd, hb, res_p, jid, rb.get('rooms') or [], str(rb['listingText']),
                                              mime, EXT[mime], edits=edits, opening_edits=ops).rebuild()
            elif edit:
                end = conveyor.EditRebuild(self, lease, wd, hb, res_p, jid, rb.get('rooms') or [], edits, opening_edits=ops,
                                           confirm=rb.get('confirm') is True).rebuild()
            else:
                end = conveyor.Rebuild(self, lease, wd, hb, res_p, jid, rb.get('rooms') or [], edits=edits, opening_edits=ops).rebuild()
        except Exception as e:                       # noqa: BLE001 — сбой кода конвейера: пересборка failed с кодом, воркер живёт
            log(f'{jid}: пересборка {rid}: {type(e).__name__}: {e}')
            end = 'failed:internal'
        finally:
            hb.stop_ev.set()
            hb.join(5)
        log(f'{jid}: пересборка {rid} → {end}, {time.time() - t0:.1f} с')
        if end == 'published':
            self.streak = 0
            self.done.append((rid, 'rebuilt'))
        elif end in ('stale', 'lost'):               # stale — сервер уже пометил пересборку; lost — она не наша
            self.done.append((rid, end))
        elif end == 'stop':
            self.fail_rebuild(lease, wd, 'waiting_capacity', True, 'worker stopping')
        else:
            code = end.split(':', 1)[1] if end.startswith('failed:') else 'pipeline_error'
            self.fail_rebuild(lease, wd, code, code in ('pipeline_error', 'internal'), getattr(cv, 'detail', '') or end)

    def reparse_approved(self, jid: str) -> list:
        """Одобренные ведущим находки сторожа «перечитать планировку» для тура (файл DEV `<base>/reparse-approve/<id>.json` — ключи
        `regress.guard_*`; пишет `reissue.py --reparse --approve`). Нет файла / битый — одобрений нет (разница не выходит)."""
        try:
            got = json.loads((self.cfg.base / 'reparse-approve' / f'{jid}.json').read_text(encoding='utf-8'))
            return [str(k) for k in got.get('keys') or []] if isinstance(got, dict) else []
        except (OSError, ValueError):
            return []

    def fail_rebuild(self, lease: dict, wd: Path, code: str, retryable: bool, detail: str = '') -> None:
        code = code if code in REBUILD_CODES else 'pipeline_error'
        st = self._post('/api/trial/worker/rebuild/fail',
                        {**lease, 'code': code, 'retryable': retryable, 'detail': detail[:2000], 'spentUsd': self.spent(wd)})
        log(f'{lease["id"]}: пересборка fail {code} retryable={retryable} → {st}')
        self.done.append((lease['id'], f'fail:{code}:{st}'))

    def result(self, lease: dict, wd: Path, res: dict) -> bool:
        body = {**lease, 'result': res, 'spentUsd': self.spent(wd)}
        st = self._post('/api/trial/worker/result', body)
        if st == 200:
            self.streak = 0
            self.done.append((lease['id'], 'done'))
            log(f'{lease["id"]}: результат принят')
            return True
        if st == 409:
            self.done.append((lease['id'], 'lost'))
            log(f'{lease["id"]}: результат не принят — аренда потеряна')
        elif st in (413, 422):
            self.fail(lease, wd, 'pipeline_error', False, f'result rejected {st}')
        else:
            self.fail(lease, wd, 'internal', True, f'result http {st}')
        return False

    # ── уборка DEV: файл владельца не держим дольше прода ──
    def janitor(self, now: float | None = None) -> list:
        now = now or time.time()
        if now - self.last_clean < 3600:
            return []
        self.last_clean = now
        gone = []
        base = self.cfg.base
        if not base.is_dir():
            return gone
        for d in base.iterdir():
            if d.is_symlink() or not d.is_dir():
                continue
            if TOKEN_RE.match(d.name):
                keep = self.cfg.keep_hours * 3600
            elif d.name == 'vlm-cache':
                for v in d.iterdir():
                    if v.is_dir() and not v.is_symlink() and now - _newest(v) > self.cfg.vlm_keep_days * 86400:
                        shutil.rmtree(v, ignore_errors=True)
                        gone.append(str(v))
                continue
            else:
                continue
            if now - _newest(d) > keep:
                shutil.rmtree(d, ignore_errors=True)
                gone.append(str(d))
        if gone:
            log(f'уборка: удалено папок {len(gone)}')
        return gone


def _newest(d: Path) -> float:
    t = d.stat().st_mtime
    for p in d.rglob('*'):
        try:
            t = max(t, p.lstat().st_mtime)
        except OSError:
            pass
    return t


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='настройки и предохранитель; заданий не брать')
    a = ap.parse_args(argv)
    cfg = Cfg.from_env()
    if not cfg.token:
        log('нет TRIAL_WORKER_TOKEN в окружении (юнит: EnvironmentFile=%h/.config/remlab/env) — выход')
        return 2
    w = Worker(cfg)
    if a.check:
        log(f'url={cfg.url} worker={cfg.worker_id} base={cfg.base} token=задан ({len(cfg.token)} симв.)')
        log(f'предохранитель: {w.breaker() or "нет — брал бы задания"}')
        return 0

    def _stop(sig, _frm):
        log(f'сигнал {sig}: останавливаюсь')
        w.stop.set()
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(s, _stop)
    cfg.base.mkdir(parents=True, exist_ok=True)
    log(f'{VERSION} старт: {cfg.url} как {cfg.worker_id}')
    w.loop()
    return 0


if __name__ == '__main__':
    sys.exit(main())

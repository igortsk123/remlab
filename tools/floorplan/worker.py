#!/usr/bin/env python3
"""Воркер DEV пробы для агентов (план agent-trial-01-upload-grey-tour, T-B): сам ходит на прод по HTTPS.

Цикл: предохранитель → POST /api/trial/worker/claim → GET …/<id>/input (файл) → `pipeline.py job` отдельным процессом
(PDF → PNG, VLM, стенд под heavy_slot) → POST …/result; heartbeat сразу после claim, сразу при смене шага и не реже
раза в 10 с (шаг из `<папка>/stage`, деньги из `<папка>/spent`; время шага прод метит только по heartbeat), concurrency 1. Ошибка → POST …/fail {code, retryable}. 409 на любой ручке — аренда потеряна: процесс
стенда снимается, задание доделает тот, кто его забрал.

Предохранитель (задание не брать, но отмечаться «жив» — claim с paused:true): MemAvailable < 3 ГБ; в общей очереди
тяжёлых ждут ≥ 2 (`tools/ops/heavy_slot.py:status`); 3 сбоя подряд по нашей вине → пауза 10 мин; /api/health прода
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

VERSION = 'trial-worker/1'
TOKEN_RE = re.compile(r'^[A-Za-z0-9_-]{22}$')       # = lib/token.ts:TOKEN_RE — id задания (и имя папки)
EXT = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'application/pdf': '.pdf'}
INPUT_MAX = 15 * 1024 * 1024
STAGES = ('raster', 'labels', 'walls', 'repair', 'export')
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
                   keep_hours=f('TRIAL_DEV_KEEP_HOURS', 24.0), an_cache=env.get('TRIAL_FP_CACHE') or None)

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
    """Сколько ждут в общей очереди тяжёлых DEV (строка «ЖДУТ: N» `heavy_slot.status`); не прочитать — 0."""
    try:
        import heavy_slot as hs
        buf = io.StringIO()
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
             auth: bool = True, stream_to: Path | None = None, max_bytes: int = INPUT_MAX):
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
                raw = r.read(4 * 1024 * 1024)
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

    def __init__(self, w: 'Worker', lease: dict, wd: Path):
        super().__init__(daemon=True)
        self.w, self.lease, self.wd = w, lease, wd
        self.stop_ev, self.lost = threading.Event(), threading.Event()
        self.sent = []

    def stage(self) -> str:
        try:
            s = (self.wd / 'stage').read_text().strip()
        except OSError:
            s = ''
        return s if s in STAGES else 'raster'

    def beat(self) -> None:
        body = {**self.lease, 'stage': self.stage(), 'spentUsd': self.w.spent(self.wd)}
        self.sent.append((time.time(), body['stage']))
        try:
            st, _ = self.w.api.call('POST', '/api/trial/worker/heartbeat', body)
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
            s = self.stage()
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
                                         {'workerId': self.cfg.worker_id, 'version': VERSION, 'paused': bool(reason)})
            except NetError as e:
                log(f'claim: {e}')
                self.stop.wait(max(self.cfg.poll_s, 5))
                continue
            if st != 200:
                log(f'claim: {st} {(body or {}).get("error", "")}')
                self.stop.wait(max(self.cfg.poll_s, 10))
                continue
            job = (body or {}).get('job')
            if job and not reason:
                self.process(job)
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
                                   '--vlm-root', str(self.cfg.vlm_root), '--job-id', jid,
                                   '--cap-usd', str(min(float(job.get('budgetUsd') or 0.10), 0.10))]
        if job.get('listingText'):
            (wd / 'listing.txt').write_text(str(job['listingText'])[:5000])
            cmd += ['--listing-file', str(wd / 'listing.txt')]
        if self.cfg.an_cache:
            cmd += ['--an-cache', self.cfg.an_cache]
        with open(wd / 'pipeline.log', 'ab') as out:
            self.child = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                                          cwd=str(HERE.parent.parent))
            deadline = time.time() + self.cfg.job_timeout_s
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
        if why == 'lost' or hb.lost.is_set():
            self.done.append((jid, 'lost'))
            return
        if why == 'timeout':
            return self.fail(lease, wd, 'timeout', False, f'pipeline > {self.cfg.job_timeout_s:g}s')
        if why == 'stop':                             # воркер останавливают: задание — назад в очередь без траты попытки
            return self.fail(lease, wd, 'waiting_capacity', True, 'worker stopping', 5)
        res_p, err_p = wd / 'result.json', wd / 'error.json'
        if rc == 0 and res_p.exists():
            return self.result(lease, wd, json.loads(res_p.read_text()))
        if err_p.exists():
            e = json.loads(err_p.read_text())
            code = e.get('code') or 'pipeline_error'
            return self.fail(lease, wd, code, bool(e.get('retryable')), str(e.get('detail') or ''),
                             30 if code == 'waiting_capacity' else None)
        # убит сигналом (OOM, earlyoom) или упал без отчёта — один повтор (попыток 2)
        self.fail(lease, wd, 'pipeline_error', True, f'pipeline rc={rc}')

    def result(self, lease: dict, wd: Path, res: dict) -> None:
        body = {**lease, 'result': res, 'spentUsd': self.spent(wd)}
        st = self._post('/api/trial/worker/result', body)
        if st == 200:
            self.streak = 0
            self.done.append((lease['id'], 'done'))
            log(f'{lease["id"]}: результат принят')
        elif st == 409:
            self.done.append((lease['id'], 'lost'))
            log(f'{lease["id"]}: результат не принят — аренда потеряна')
        elif st in (413, 422):
            self.fail(lease, wd, 'pipeline_error', False, f'result rejected {st}')
        else:
            self.fail(lease, wd, 'internal', True, f'result http {st}')

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

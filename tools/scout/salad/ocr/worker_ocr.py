#!/usr/bin/env python3
"""ВОРКЕР SALAD «КЭШ СЛОВ OCR» (T-176/ocr-salad): лист плана → флаг «на листе есть имена комнат словами» (rapidocr на ПРОЦЕССОРЕ ноды).
Считает ЗАМОРОЖЕННЫЙ код снимка 20261126-2234 без правок: `words_on_sheet.words_on_sheet(путь)` + `words_rules.json` лежат в образе (`/opt/ocr/`, байт в байт — Dockerfile.ocr + frozen/SHA256SUMS).
Воркер ничего не решает про кэш: возвращает ровно то, что вернул `words_on_sheet` (words, found, conf, n_lines), и ключ строки кэша = sha256 ФАЙЛА листа (как `words_on_sheet.sheet_sha`).
Слияние в words_flags.json делает наш драйвер (`merge_words.py`), не нода.

HTTP (порт $PORT, 8000; сервер на `::` — kit_worker.make_server):
  GET  /health              → {"phase": loading|ready|broken, "rapidocr", "onnxruntime", "rules", "models": {файл: sha256[:12]}, ...}; прогрев = движок собран и один холостой лист распознан (модели запечены в образ — скачивания нет)
  POST /jobs                {"job_id", "sheets": [{"id", "sha", "ext", "z"(zlib→base64 файл листа)}]} → 202; повтор того же job_id не дублирует
  GET  /jobs/<id>           → {"status": queued|running|done|failed, "step", "done", "total", "sha256", "bytes", "wall_s"}
  GET  /jobs/<id>/result    → JSON {"rules", "results": {sha: {words, found, conf, n_lines, sheet, ocr_s}}, "errors": {sha: причина}}; только при done
  POST /shutdown            → процесс завершается
Лист, чей sha256 не сошёлся с присланным, не считается (в errors). Любой отказ листа — в errors с причиной (молчаливых except нет); задание с ошибками = failed.
АВТОСТОП: MAX_LIFETIME_S / IDLE_S (kit_worker.Watchdog); драйвер всё равно гасит группу сам и проверяет «0 нод»."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
try:
    import kit_worker as KW                                    # на Salad модуль набора зарегистрирован в sys.modules (KW.bundle)
except ImportError:                                            # локально (тесты): набор лежит выше, в tools/scout/salad
    sys.path.insert(0, os.path.join(HERE, '..'))
    import kit_worker as KW

log = logging.getLogger('ocr-worker')
VERSION = 'ocr-worker-1'
MAX_BODY = 80 * 2 ** 20
JOB_RE = re.compile(r'^[A-Za-z0-9._\-]{1,150}$')
EXTS = ('jpeg', 'jpg', 'png')


def cfg() -> dict:
    return {'code': os.environ.get('OCR_CODE', '/opt/ocr'), 'work': os.environ.get('OCR_WORK', '/tmp/ocr'),
            'procs': max(1, int(os.environ.get('OCR_PROCS', '1')))}


def load_module(code: str):
    """words_on_sheet из кода образа (замороженный снимок). Модуль без rapidocr импортируется где угодно — движок грузится лениво."""
    if code not in sys.path:
        sys.path.insert(0, code)
    sys.modules.pop('words_on_sheet', None)
    import words_on_sheet as W
    return W


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def models_info() -> dict:
    """Какие файлы моделей rapidocr лежат в образе и их sha256[:12] — для сверки с локальным venv ocr-trial (драйвер печатает в отчёт)."""
    try:
        import rapidocr
        d = os.path.join(os.path.dirname(rapidocr.__file__), 'models')
        return {f: sha_bytes(open(os.path.join(d, f), 'rb').read())[:12] for f in sorted(os.listdir(d)) if f.endswith('.onnx')}
    except Exception as exc:                                   # noqa: BLE001 — причина в ответе, не молчим
        return {'error': f'{type(exc).__name__}: {str(exc)[:120]}'}


def versions() -> dict:
    out = {}
    for name in ('rapidocr', 'onnxruntime'):
        try:
            from importlib.metadata import version
            out[name] = version(name)
        except Exception as exc:                               # noqa: BLE001
            out[name] = f'?{type(exc).__name__}'
    return out


class Pool:
    """Очередь заданий ноды: до `procs` одновременно (по умолчанию 1: onnxruntime сам берёт все ядра). Один job_id — одна работа."""

    def __init__(self, state, c: dict, W):
        self.state, self.c, self.W = state, c, W
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
            self.state.begin_job('ocr-batch')
            self.opened = True
        if self.opened:
            sheets = sum(j.get('done_n', 0) for j in list(self.jobs.values()))
            self.state.step(f"считаю {n['running']}, в очереди {n['queued']}, готово {n['done']}, отказов {n['failed']} из {n['total']}; листов обработано {sheets}")
        if not busy and self.opened:
            self.state.end_job()
            self.opened = False

    def view(self, jid: str) -> dict | None:
        j = self.jobs.get(jid)
        return None if j is None else {k: j.get(k) for k in ('job_id', 'status', 'step', 'done_n', 'total', 'error', 'sha256', 'bytes', 'wall_s', 'ocr_s', 'queue_s')}

    def submit(self, jid: str, sheets: list[dict]) -> dict:
        with self.lock:
            if jid in self.jobs:
                return self.jobs[jid]
            j = {'job_id': jid, 'status': 'queued', 'step': 'очередь', 'sheets': sheets, 'total': len(sheets), 'done_n': 0, 't_in': time.time(), 'error': None}
            self.jobs[jid] = j
        threading.Thread(target=self._run, args=(j,), daemon=True).start()
        self._refresh()
        return j

    def one(self, s: dict, d: str) -> dict:
        """Один лист: файл на диск → words_on_sheet (как в снимке). → запись кэша без ключа 'rules' (его ставит драйвер из версии правил образа)."""
        path = os.path.join(d, f"{s['sha'][:16]}.{s['ext']}")
        with open(path, 'wb') as f:
            f.write(s['raw'])
        t0 = time.time()
        r = self.W.words_on_sheet(path)
        return {**r, 'ocr_s': round(time.time() - t0, 1)}

    def _run(self, j: dict) -> None:
        self.sem.acquire()
        try:
            j['status'], j['t_run'] = 'running', time.time()
            j['queue_s'] = round(j['t_run'] - j['t_in'], 1)
            d = os.path.join(self.c['work'], j['job_id'])
            os.makedirs(d, exist_ok=True)
            results, errors = {}, {}
            for s in j['sheets']:
                j['step'] = f"лист {j['done_n'] + 1} из {j['total']}"
                self.state.note(f"{j['job_id'][:40]} {j['step']} ({s['id']})")
                try:
                    results[s['sha']] = {**self.one(s, d), 'sheet': s['id']}
                except Exception as exc:                       # noqa: BLE001 — причина листа всегда в errors
                    errors[s['sha']] = f"{s['id']}: {type(exc).__name__}: {str(exc)[:200]}"
                    log.error('лист %s: %s', s['id'], traceback.format_exc())
                j['done_n'] += 1
                self._refresh()
            body = json.dumps({'rules': self.W.rules_ver(), 'results': results, 'errors': errors}, ensure_ascii=False, sort_keys=True).encode()
            j.update(body=body, sha256=sha_bytes(body), bytes=len(body), ocr_s=round(time.time() - j['t_run'], 1), wall_s=round(time.time() - j['t_in'], 1))
            if errors:
                j['status'], j['step'], j['error'] = 'failed', 'отказ', f'листов с отказом {len(errors)} из {j["total"]}: {list(errors.values())[:3]}'
            else:
                j['status'], j['step'] = 'done', 'готово'
        except Exception as exc:                               # noqa: BLE001
            j['status'], j['step'], j['error'] = 'failed', 'отказ', f'{type(exc).__name__}: {exc}'
            j['wall_s'] = round(time.time() - j['t_in'], 1)
            log.error('задание %s: %s', j['job_id'], traceback.format_exc())
        finally:
            self.sem.release()
            self._refresh()


def parse_sheets(b: dict) -> tuple[list[dict] | None, str]:
    """Тело POST → листы с распакованными байтами; sha256 каждого сверяется. → (листы, '') или (None, причина отказа 400)."""
    raw = b.get('sheets')
    if not isinstance(raw, list) or not raw:
        return None, 'sheets — непустой список'
    out, seen = [], set()
    for s in raw:
        try:
            sid, sha, ext = str(s['id']), str(s['sha']), str(s['ext']).lower()
            data = zlib.decompress(base64.b64decode(s['z']))
        except (KeyError, TypeError, ValueError, zlib.error):
            return None, 'лист: нужны id, sha, ext, z (zlib→base64 файл)'
        if ext not in EXTS:
            return None, f'лист {sid}: ext из {list(EXTS)}'
        if sha_bytes(data) != sha:
            return None, f'лист {sid}: sha256 не сошёлся (ждали {sha[:12]}, получили {sha_bytes(data)[:12]}) — файл повреждён в пути'
        if sha in seen:
            return None, f'лист {sid}: повтор sha256 в задании'
        seen.add(sha)
        out.append({'id': sid, 'sha': sha, 'ext': ext, 'raw': data})
    return out, ''


class OcrHandler(KW.KitHandler):
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
        elif v['status'] not in ('done', 'failed'):
            self.send_json(409, {'error': f"результата нет: статус {v['status']}"})
        else:
            self.send_bytes(200, self.pool.jobs[m.group(1)]['body'], 'application/json')    # и при failed: готовые листы + errors (драйвер сам решает)
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
        sheets, why = parse_sheets(b)
        if sheets is None:
            self.send_json(400, {'error': why})
            return True
        j = self.pool.submit(jid, sheets)
        self.send_json(202, {'job_id': jid, 'status': j['status']})
        return True


def warm_engine(W, c: dict, info: dict) -> None:
    """Прогрев: движок собран, холостой лист (белый квадрат) прошёл весь путь `words_on_sheet` — модели читаются из образа. Падение → broken (деньги не жжём)."""
    import cv2
    import numpy as np
    os.makedirs(c['work'], exist_ok=True)
    p = os.path.join(c['work'], 'warm.png')
    cv2.imwrite(p, np.full((1500, 1500, 3), 255, np.uint8))                 # >1200 px: плитки тоже проходят
    t0 = time.time()
    e = W._engine()
    e._load_det_model()                                                      # rapidocr грузит модели лениво (на пустом листе — не грузит): прогрев обязан поднять все три,
    e._load_cls_model()                                                      # иначе первый настоящий лист заплатит за загрузку, а сломанный образ выяснится не на прогреве
    e._load_rec_model()
    r = W.words_on_sheet(p)
    info.update(versions(), rules=W.rules_ver(), models=models_info(), warm_s=round(time.time() - t0, 1), warm_result=r)


def make_handler(state, pool: Pool, wd, stop, info: dict):
    return OcrHandler.bind(state, wd, stop, VERSION, health_extra=lambda: {**{k: info.get(k) for k in ('rapidocr', 'onnxruntime', 'rules', 'models', 'warm_s')},
                                                                          'pool': pool.counts(), 'procs': pool.c['procs'], 'cores': os.cpu_count()}, pool=pool)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(message)s')
    c = cfg()
    os.makedirs(c['work'], exist_ok=True)
    state = KW.State()
    wd = KW.Watchdog(float(os.environ.get('MAX_LIFETIME_S', '7200')), float(os.environ.get('IDLE_S', '900')))
    stop = threading.Event()
    W = load_module(c['code'])
    pool = Pool(state, c, W)
    info: dict = {}

    def warm():
        warm_engine(W, c, info)
        state.weights = {'note': 'модели в образе', 'code': c['code']}

    log.info('воркер %s: процессов %s, ядер %s, код %s', VERSION, c['procs'], os.cpu_count(), c['code'])
    return KW.serve(make_handler(state, pool, wd, stop, info), state, wd, stop, [('loading', warm)], log=log)


if __name__ == '__main__':
    sys.exit(main())

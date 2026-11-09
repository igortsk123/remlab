#!/usr/bin/env python3
"""Заглушка прод-API пробы (`/api/trial/*`) по контракту `contracts/trial.ts` — для проверки замерщика `trial_e2e.py` без прода.

Что умеет: приём multipart (`file` + `listing` + `consent=yes`, сигнатура JPEG/PNG/WebP/PDF, ≤ 15 МБ) → 201 `{ok,id,url}`;
статус `GET /api/trial/<id>` (`trialJobView`: status/stage/stages[{stage,at}]/createdAt/finishedAt/elapsedSec/queueAhead/
workerAlive/errorCode/resultVersion); результат `GET /api/trial/<id>/result` с ETag/304. Задание «идёт» по времени: очередь
(одно задание за раз, как воркер с concurrency 1) → стадии по `schedule` → done (или failed, если сценарий так велит).
Отказы как у прода: 429/503 с `Retry-After` первым `refuse` загрузкам. Считает запросы по ручкам (тест: «без долбёжки»).

Запуск руками: `python3 tools/ops/trial_stub.py --port 8790 [--speed 0.2] [--fail-every 0] [--no-worker]`.
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Стадии воркера и их длительность в секундах при speed=1 (порядок — `contracts/trial.ts:trialStage`).
SCHEDULE = [("raster", 4.0), ("labels", 25.0), ("walls", 12.0), ("repair", 8.0), ("export", 3.0)]
FILE_MAX = 15 * 1024 * 1024
LISTING_MAX = 5000
CONSENT_YES = {"yes", "1", "true", "on"}
SIGS = [(b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"), (b"%PDF-", "application/pdf")]


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sniff(head: bytes) -> str | None:
    for sig, mime in SIGS:
        if head.startswith(sig):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


class StubState:
    """Задания и сценарий. Время задания считается от момента, когда «воркер» его взял (одно за раз, по порядку)."""

    def __init__(self, speed: float = 1.0, refuse: list[int] | None = None, fail_every: int = 0,
                 worker_alive: bool = True, queue_max: int = 5, schedule: list[tuple[str, float]] | None = None,
                 retry_after: int = 1):
        self.speed = speed
        self.refuse = list(refuse or [])  # коды отказа первым загрузкам по очереди: [429, 503] …
        self.fail_every = fail_every      # каждое N-е задание — failed/no_plan на стадии labels
        self.worker_alive = worker_alive
        self.queue_max = queue_max
        self.schedule = schedule or SCHEDULE
        self.retry_after = retry_after
        self.jobs: dict[str, dict] = {}
        self.order: list[str] = []
        self.hits: dict[str, int] = {}
        self.uploads: list[dict] = []
        self.lock = threading.Lock()

    def hit(self, key: str) -> None:
        with self.lock:
            self.hits[key] = self.hits.get(key, 0) + 1

    def _timeline(self, now: float) -> None:
        """Пересчитать, кто когда взят: следующий берётся, когда предыдущий закончил (concurrency 1)."""
        free_at = 0.0
        for jid in self.order:
            j = self.jobs[jid]
            if not self.worker_alive:
                break
            start = max(j["created"], free_at)
            if start > now:
                break
            j["start"] = start
            t, stages = start, []
            for i, (stage, dur) in enumerate(self.schedule):
                stages.append((stage, t))
                if j["fail"] and stage == "labels":
                    j["fail_at"] = t + dur * self.speed / 2
                    break
                t += dur * self.speed
            j["plan"] = stages
            j["end"] = j.get("fail_at", t)
            free_at = j["end"]

    def view(self, jid: str, now: float) -> dict:
        with self.lock:
            self._timeline(now)
            j = self.jobs[jid]
            stages = [{"stage": s, "at": iso(t)} for s, t in j.get("plan", []) if t <= now]
            end = j.get("end")
            finished = end is not None and end <= now
            if finished:
                status = "failed" if j["fail"] else "done"
                if not j["fail"]:
                    stages.append({"stage": "done", "at": iso(end)})
            elif stages:
                status = "running"
            else:
                status = "queued"
            stage = stages[-1]["stage"] if stages else "queued"
            ahead = None
            if status == "queued":
                # как прод: считаем только ещё не взятые раньше этого (идущее сейчас — не «впереди в очереди»)
                ahead = sum(1 for o in self.order[: self.order.index(jid)] if self.jobs[o].get("start") is None)
            elapsed = int(max(0, (end if finished else now) - j["created"]))
            return {
                "id": jid, "status": status, "stage": stage, "stages": stages, "createdAt": iso(j["created"]),
                "finishedAt": iso(end) if finished else None, "elapsedSec": elapsed, "queueAhead": ahead,
                "workerAlive": self.worker_alive, "errorCode": "no_plan" if finished and j["fail"] else None,
                "resultVersion": 1 if finished and not j["fail"] else 0,
            }

    def create(self, mime: str, size: int, listing: str) -> tuple[int, dict, dict]:
        with self.lock:
            if self.refuse:
                code = self.refuse.pop(0)
                return code, {"ok": False, "error": "daily_cap" if code == 429 else "busy"}, {"Retry-After": str(self.retry_after)}
            now = time.time()
            self._timeline(now)
            waiting = sum(1 for o in self.order if self.jobs[o].get("start") is None)
            if waiting >= self.queue_max:
                return 503, {"ok": False, "error": "busy"}, {"Retry-After": str(self.retry_after)}
            jid = secrets.token_urlsafe(16)[:22]
            n = len(self.order) + 1
            self.jobs[jid] = {"created": now, "fail": bool(self.fail_every) and n % self.fail_every == 0}
            self.order.append(jid)
            self.uploads.append({"id": jid, "mime": mime, "bytes": size, "listing": listing})
            return 201, {"ok": True, "id": jid, "url": f"/try/{jid}"}, {}


ID_RE = re.compile(r"^/api/trial/([A-Za-z0-9_-]{22})(/result)?$")


def make_handler(state: StubState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_a):  # тихо: журнал пишет замерщик
            pass

        def _send(self, code: int, body: dict | None, extra: dict | None = None):
            raw = b"" if body is None else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Cache-Control", "private, no-store")
            if body is not None:
                self.send_header("Content-Type", "application/json")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if self.path != "/api/trial":
                return self._send(404, {"ok": False, "error": "not_found"})
            state.hit("upload")
            ct = self.headers.get("Content-Type", "")
            if not ct.lower().startswith("multipart/form-data"):
                return self._send(415, {"ok": False, "error": "multipart_required"})
            n = int(self.headers.get("Content-Length") or 0)
            if n > FILE_MAX + 1024 * 1024:
                return self._send(413, {"ok": False, "error": "too_large"})
            body = self.rfile.read(n)
            msg = BytesParser(policy=email_policy).parsebytes(b"Content-Type: " + ct.encode() + b"\r\n\r\n" + body)
            fields, file_bytes = {}, None
            for part in msg.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if name == "file":
                    file_bytes = part.get_payload(decode=True) or b""
                elif name:
                    fields[name] = part.get_content()
            if not file_bytes:
                return self._send(400, {"ok": False, "error": "no_file"})
            if len(file_bytes) > FILE_MAX:
                return self._send(413, {"ok": False, "error": "too_large"})
            mime = sniff(file_bytes[:16])
            if not mime:
                return self._send(415, {"ok": False, "error": "unsupported_type"})
            listing = (fields.get("listing") or "").strip()
            if len(listing) > LISTING_MAX:
                return self._send(400, {"ok": False, "error": "listing_too_long"})
            if (fields.get("consent") or "").lower() not in CONSENT_YES:
                return self._send(400, {"ok": False, "error": "consent_required"})
            code, out, extra = state.create(mime, len(file_bytes), listing)
            return self._send(code, out, extra)

        def do_GET(self):
            m = ID_RE.match(self.path)
            if not m or m.group(1) not in state.jobs:
                state.hit("other")
                return self._send(404, {"ok": False, "error": "not_found"})
            jid, is_result = m.group(1), bool(m.group(2))
            state.hit("result" if is_result else "status")
            v = state.view(jid, time.time())
            if not is_result:
                return self._send(200, {"ok": True, "job": v})
            if v["status"] != "done":
                return self._send(404, {"ok": False, "error": "not_ready"})
            etag = f'"v{v["resultVersion"]}"'
            if self.headers.get("If-None-Match") == etag:
                return self._send(304, None, {"ETag": etag})
            result = {"version": 1, "units": "cm", "panels": [{"id": "p1", "title": "Ground", "rooms": [], "walls": [],
                                                               "openings": []}], "flags": [], "timings": {}, "costUsd": 0.0}
            return self._send(200, {"ok": True, "version": v["resultVersion"], "result": result}, {"ETag": etag})

    return Handler


def serve(state: StubState, port: int = 0) -> ThreadingHTTPServer:
    """Поднять заглушку в фоне; порт 0 — свободный. Остановка — `srv.shutdown()`."""
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--speed", type=float, default=1.0, help="множитель длительности стадий (0.1 — в 10 раз быстрее)")
    ap.add_argument("--fail-every", type=int, default=0, help="каждое N-е задание завершать failed/no_plan")
    ap.add_argument("--no-worker", action="store_true", help="воркер «не на связи»: задания стоят в очереди")
    ap.add_argument("--refuse", default="", help="коды отказа первым загрузкам, через запятую (например 429,503)")
    a = ap.parse_args()
    st = StubState(speed=a.speed, fail_every=a.fail_every, worker_alive=not a.no_worker,
                   refuse=[int(x) for x in a.refuse.split(",") if x])
    srv = serve(st, a.port)
    print(f"заглушка /api/trial на http://127.0.0.1:{srv.server_address[1]} (Ctrl+C — стоп)", flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()

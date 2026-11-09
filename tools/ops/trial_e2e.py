#!/usr/bin/env python3
"""Замер пробы «от загрузки до готового» (MASTER-agent-trial T9, задача T-20261109-14): грузит план в `/api/trial` так же,
как страница `/try`, опрашивает статус, пишет журнал стадий и считает p50/p95 — всего, отдельно тёплый/холодный.

    python3 tools/ops/trial_e2e.py --input D=~/plans/D.pdf --listing D=~/plans/D.txt --input E=~/plans/E.jpg -n 3 --live
    python3 tools/ops/trial_e2e.py --report-only ~/remlab-logs/trial-e2e/run-1530     # пересобрать таблицу из runs.json

Адрес — `--base` (по умолчанию прод). Любой адрес, кроме localhost, требует `--live`: каждая загрузка создаёт НАСТОЯЩЕЕ
задание (на проде — платный VLM на DEV). Итог — `<out>/run-<ЧЧММ>/`: `journal.jsonl` (каждое изменение статуса и стадии,
время клиента и сервера), `runs.json` (последний вид задания каждого прогона), `table.md` и `table.tsv`.

Как страница и без долбёжки API (лимиты прода — `lib/ratelimit/index.ts:trialUpload|trialRead`):
- опрос статуса раз в 1,5 с; волна из K заданий — цикл 1,5 с × K/2 (три задания — 80 запросов в минуту при лимите чтения 120 с адреса);
- загрузки — с промежутком `--gap` (200 с: прод пускает 3 загрузки за 10 мин и 10 в сутки с адреса);
- 429/503 — ждём `Retry-After` (не больше `--retry-cap`), не больше 3 повторов; сетевой сбой загрузки НЕ повторяем
  (задание могло создаться — повтор дал бы двойник);
- задание в очереди, а воркер «не на связи» дольше `--no-worker-sec` — серию останавливаем (не копим очередь).

Стадии → этапы: очередь (`queued`, от загрузки до первого шага воркера) · распознавание (`raster`, `labels`) · 3D (`walls`,
`repair`, `export`) · мебель и фото — шаги, которых в контракте ещё нет (T5–T7; имена ниже, неизвестные — в «прочее»).
Время этапов — по меткам сервера (`stages[].at`), итог — `finishedAt − createdAt` (как таймер страницы); «клиент» — от начала
загрузки до того, как опрос увидел конец (включает передачу файла и шаг опроса).
Холодный/тёплый: холодный — первый прогон серии и любой, перед которым воркер простаивал ≥ `--cold-gap` с (по нашим же
прогонам; чужих заданий не видим) — либо задать `--temp cold|warm`. Отдельно — вход: `repeat` — тот же файл и текст уже
были в серии (у воркера кэш VLM по sha256, прогон почти бесплатный и быстрее); `--fresh-input` дописывает в конец файла
безвредный хвост (за маркером конца JPEG/PNG/PDF — картинка та же), чтобы каждый прогон шёл мимо кэша (это платно: VLM ~$0,10).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

DEFAULT_BASE = "https://remont-lab.online"
DEFAULT_OUT = Path("/home/pakar/remlab-logs/trial-e2e")
UA = "remlab-trial-e2e/1"
TERMINAL = {"done", "failed", "cancelled", "expired"}
PHASES = [("queue", "очередь"), ("recognition", "распознавание"), ("3d", "3D"), ("furniture", "мебель"), ("photo", "фото"),
          ("other", "прочее")]
STAGE_PHASE = {
    "queued": "queue", "raster": "recognition", "labels": "recognition", "walls": "3d", "repair": "3d", "export": "3d",
    # будущие шаги (T5 расстановка, T7 кадр) — имена-кандидаты; контракт пока их не знает
    "layout": "furniture", "furniture": "furniture", "products": "furniture", "photo": "photo", "hero": "photo",
}
STAGE_ORDER = ["queued", "raster", "labels", "walls", "repair", "export", "layout", "furniture", "products", "photo",
               "hero", "done"]
GATES = {"warm_p50": 90.0, "warm_max": 150.0, "goal": 180.0}  # agent-trial-01 «Критерии» и цель мастера ≤ 3 мин
MAX_REFUSALS = 3


@dataclass
class Cfg:
    base: str = DEFAULT_BASE
    poll: float = 1.5
    gap: float = 200.0
    retry_cap: float = 900.0
    timeout: float = 900.0
    cold_gap: float = 600.0
    no_worker_sec: float = 45.0
    temp: str = "auto"
    fresh_input: bool = False
    batch: int = 1
    http_timeout: float = 60.0


@dataclass
class Item:
    name: str
    path: Path
    listing: str = ""


@dataclass
class Run:
    n: int
    plan: str
    temp: str
    input: str
    id: str | None = None
    outcome: str = "pending"  # done | failed:<code> | refused:<http>:<error> | upload_error | client_timeout | no_worker
    upload_sec: float | None = None
    client_sec: float | None = None
    server_sec: float | None = None
    phases: dict = field(default_factory=dict)
    retried: bool = False
    result_ok: bool | None = None
    result_bytes: int | None = None
    refusals: int = 0
    polls: int = 0
    started: str = ""
    t0: float = 0.0
    view: dict | None = None


class Http:
    """Тонкий клиент `/api/trial/*`: JSON-ответ, коды, заголовки; HTTP-ошибки — не исключения."""

    def __init__(self, cfg: Cfg):
        self.cfg = cfg

    def req(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        h = {"User-Agent": UA, "Accept": "application/json", **(headers or {})}
        r = urllib.request.Request(self.cfg.base.rstrip("/") + path, data=body, method=method, headers=h)
        try:
            with urllib.request.urlopen(r, timeout=self.cfg.http_timeout) as resp:
                raw = resp.read()
                return resp.status, dict(resp.headers), raw
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers or {}), e.read() or b""


def as_json(raw: bytes) -> dict:
    try:
        v = json.loads(raw or b"{}")
        return v if isinstance(v, dict) else {}
    except ValueError:
        return {}


def retry_after(headers: dict, cap: float, dflt: float = 120.0) -> float:
    v = {k.lower(): x for k, x in headers.items()}.get("retry-after")
    try:
        sec = float(v) if v is not None else dflt
    except ValueError:
        sec = dflt
    return max(1.0, min(sec, cap))


# ── вход ──────────────────────────────────────────────────────────────────────────────────────────────
def mime_of(head: bytes) -> str:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("не JPEG/PNG/WebP/PDF — прод ответит 415")


def file_bytes(item: Item, fresh: bool) -> bytes:
    data = item.path.read_bytes()
    if fresh:  # хвост за маркером конца: декодеры его не читают, sha256 — другой → мимо кэша VLM
        data += b"\n%remlab-e2e " + secrets.token_hex(8).encode() + b"\n"
    return data


def input_hash(data: bytes, listing: str) -> str:
    """Как прод (`lib/trial/upload.ts`): sha256(sha256(файл) + "\\n" + текст)."""
    return hashlib.sha256(f"{hashlib.sha256(data).hexdigest()}\n{listing.strip()}".encode()).hexdigest()


def multipart(data: bytes, filename: str, mime: str, listing: str) -> tuple[bytes, str]:
    b = "----remlab" + secrets.token_hex(12)
    out = bytearray()
    for name, val in (("listing", listing), ("consent", "yes")):
        out += f'--{b}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode() + val.encode() + b"\r\n"
    safe = "".join(c for c in filename if c.isalnum() or c in "._-") or "plan"
    out += f'--{b}\r\nContent-Disposition: form-data; name="file"; filename="{safe}"\r\nContent-Type: {mime}\r\n\r\n'.encode()
    out += data + f"\r\n--{b}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={b}"


# ── разбор вида задания ───────────────────────────────────────────────────────────────────────────────
def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def phase_durations(view: dict) -> tuple[dict, float | None, bool]:
    """Секунды по этапам из меток сервера, итог `finishedAt − createdAt`, и был ли откат (повтор попытки)."""
    created = ts(view["createdAt"])
    end = ts(view["finishedAt"]) if view.get("finishedAt") else None
    marks = [("queued", created)] + [(s["stage"], ts(s["at"])) for s in view.get("stages") or [] if s.get("stage") != "queued"]
    marks.sort(key=lambda m: m[1])
    out: dict[str, float] = {}
    for i, (stage, t) in enumerate(marks):
        if stage == "done":
            continue
        nxt = marks[i + 1][1] if i + 1 < len(marks) else end
        if nxt is None:
            continue
        ph = STAGE_PHASE.get(stage, "other")
        out[ph] = round(out.get(ph, 0.0) + max(0.0, nxt - t), 3)
    idx = [STAGE_ORDER.index(s) if s in STAGE_ORDER else -1 for s, _ in marks]
    retried = any(b < a for a, b in zip(idx, idx[1:]) if a >= 0 and b >= 0)
    return out, (round(end - created, 3) if end is not None else None), retried


def pct(xs: list[float], p: float) -> float | None:
    """Перцентиль с линейной интерполяцией (как numpy по умолчанию); при n ≤ 3 p95 ≈ максимум."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = (len(xs) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return round(xs[lo] + (xs[hi] - xs[lo]) * (k - lo), 1)


# ── прогон ────────────────────────────────────────────────────────────────────────────────────────────
class Series:
    def __init__(self, cfg: Cfg, items: list[Item], n: int, outdir: Path, log=print):
        self.cfg, self.items, self.n, self.outdir, self.log = cfg, items, n, outdir, log
        self.http = Http(cfg)
        self.journal = (outdir / "journal.jsonl").open("a", encoding="utf-8")
        self.runs: list[Run] = []
        self.seen_inputs: set[str] = set()
        self.last_upload: float | None = None
        self.last_finish: float | None = None
        self.abort: str | None = None

    def jot(self, ev: str, run: Run, **kw) -> None:
        rec = {"t": round(time.time(), 3), "ev": ev, "run": run.n, "plan": run.plan, "id": run.id, **kw}
        self.journal.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.journal.flush()

    def _temp(self, now: float) -> str:
        if self.cfg.temp != "auto":
            return self.cfg.temp
        if self.last_finish is None:
            return "cold"
        return "cold" if now - self.last_finish >= self.cfg.cold_gap else "warm"

    def upload(self, run: Run, item: Item) -> bool:
        data = file_bytes(item, self.cfg.fresh_input)
        body, ctype = multipart(data, item.path.name, mime_of(data[:16]), item.listing)
        h = input_hash(data, item.listing)
        run.input = "repeat" if h in self.seen_inputs else "fresh"
        self.seen_inputs.add(h)
        while True:
            t0 = time.time()
            run.started = datetime.fromtimestamp(t0).isoformat(timespec="seconds")
            run.temp = self._temp(t0)
            try:
                code, headers, raw = self.http.req("POST", "/api/trial", body, {"Content-Type": ctype})
            except (urllib.error.URLError, OSError) as e:  # без повтора: задание могло создаться
                run.outcome = "upload_error"
                self.jot("upload_error", run, error=str(e)[:200])
                return False
            js = as_json(raw)
            if code == 201 and js.get("id"):
                run.id, run.upload_sec = js["id"], round(time.time() - t0, 3)
                run.t0 = t0
                self.last_upload = time.time()
                self.jot("uploaded", run, http=code, upload_sec=run.upload_sec, bytes=len(data), input=run.input, temp=run.temp)
                return True
            if code in (429, 503) and run.refusals < MAX_REFUSALS:
                run.refusals += 1
                wait = retry_after(headers, self.cfg.retry_cap)
                self.jot("refused", run, http=code, error=js.get("error"), wait=wait)
                self.log(f"  {run.plan}#{run.n}: {code} {js.get('error')} — жду {wait:.0f} с (Retry-After)")
                time.sleep(wait)
                continue
            run.outcome = f"refused:{code}:{js.get('error')}"
            self.jot("refused_final", run, http=code, error=js.get("error"))
            if code in (429, 503):
                self.abort = f"прод отказывает ({code} {js.get('error')}) после {MAX_REFUSALS} повторов"
            return False

    def poll_once(self, run: Run, state: dict) -> bool:
        """Один опрос; True — прогон закончен (успех, отказ, таймаут, нет воркера)."""
        run.polls += 1
        try:
            code, headers, raw = self.http.req("GET", f"/api/trial/{run.id}")
        except (urllib.error.URLError, OSError) as e:
            state["net_err"] = state.get("net_err", 0) + 1
            self.jot("poll_error", run, error=str(e)[:200])
            if state["net_err"] >= 5:
                run.outcome = "poll_error"
                return True
            state["pause"] = 5.0
            return False
        state["net_err"] = 0
        if code == 429:
            state["pause"] = retry_after(headers, self.cfg.retry_cap, 30.0)
            self.jot("poll_429", run, wait=state["pause"])
            return False
        if code != 200:
            run.outcome = f"status_http:{code}:{as_json(raw).get('error')}"
            self.jot("poll_http", run, http=code)
            return True
        v = as_json(raw).get("job") or {}
        key = (v.get("status"), v.get("stage"), v.get("queueAhead"), v.get("workerAlive"), len(v.get("stages") or []))
        now = time.time()
        if key != state.get("key"):
            state["key"] = key
            self.jot("view", run, rel=round(now - run.t0, 3), status=v.get("status"), stage=v.get("stage"),
                     queueAhead=v.get("queueAhead"), workerAlive=v.get("workerAlive"), elapsedSec=v.get("elapsedSec"),
                     errorCode=v.get("errorCode"))
        run.view = v
        if v.get("status") in TERMINAL:
            run.client_sec = round(now - run.t0, 3)
            run.phases, run.server_sec, run.retried = phase_durations(v)
            run.outcome = "done" if v["status"] == "done" else f"{v['status']}:{v.get('errorCode')}"
            if v["status"] == "done":
                self.fetch_result(run)
            return True
        if v.get("status") == "queued" and v.get("workerAlive") is False:
            state.setdefault("dead_since", now)
            if now - state["dead_since"] >= self.cfg.no_worker_sec:
                run.outcome = "no_worker"
                self.abort = "воркер не на связи — серия остановлена, чтобы не копить очередь"
                return True
        else:
            state.pop("dead_since", None)
        if now - run.t0 > self.cfg.timeout:
            run.outcome = "client_timeout"
            return True
        return False

    def fetch_result(self, run: Run) -> None:
        try:
            code, _h, raw = self.http.req("GET", f"/api/trial/{run.id}/result")
        except (urllib.error.URLError, OSError):
            run.result_ok = False
            return
        js = as_json(raw)
        run.result_ok = code == 200 and isinstance(js.get("result"), dict)
        run.result_bytes = len(raw)
        self.jot("result", run, http=code, bytes=len(raw), ok=run.result_ok)

    def wave(self, pairs: list[tuple[int, Item]]) -> None:
        active: list[tuple[Run, dict]] = []
        for n, item in pairs:
            run = Run(n=n, plan=item.name, temp="", input="")
            self.runs.append(run)
            if self.upload(run, item):
                active.append((run, {}))
            if self.abort:
                break
        cycle = self.cfg.poll * max(1.0, len(active) / 2)  # 3 задания × 1,5 с → 80 запросов в минуту (лимит 120)
        while active:
            time.sleep(max([cycle] + [s.pop("pause", 0.0) for _, s in active]))
            still = []
            for run, st in active:
                if self.poll_once(run, st):
                    self.last_finish = time.time()
                    self.log(f"  {run.plan}#{run.n} [{run.temp}/{run.input}] → {run.outcome}  сервер {run.server_sec} с, "
                             f"клиент {run.client_sec} с")
                else:
                    still.append((run, st))
            active = still
            if self.abort:  # остальные задания волны не ждём: они в той же очереди без воркера
                for r, _ in active:
                    r.outcome = "abandoned"
                break

    def run(self) -> list[Run]:
        order = [it for _ in range(self.n) for it in self.items]
        k = max(1, min(self.cfg.batch, 3))
        for i in range(0, len(order), k):
            if self.abort:
                break
            if self.last_upload is not None:
                wait = self.last_upload + self.cfg.gap - time.time()
                if wait > 0:
                    self.log(f"  пауза {wait:.0f} с между загрузками (лимит прода 3 за 10 мин с адреса)")
                    time.sleep(wait)
            self.wave([(i + j + 1, it) for j, it in enumerate(order[i:i + k])])
        if self.abort:
            self.log(f"! {self.abort}")
        self.journal.close()
        return self.runs


# ── итог ──────────────────────────────────────────────────────────────────────────────────────────────
def fmt(x) -> str:
    return "—" if x is None else (f"{x:.1f}" if isinstance(x, float) else str(x))


def summarize(runs: list[dict]) -> list[dict]:
    ok = [r for r in runs if r["outcome"] == "done"]
    groups = [("все", ok), ("холодные", [r for r in ok if r["temp"] == "cold"]),
              ("тёплые", [r for r in ok if r["temp"] == "warm"])]
    groups += [(f"план {p}", [r for r in ok if r["plan"] == p]) for p in dict.fromkeys(r["plan"] for r in runs)]
    out = []
    for name, rs in groups:
        tot = [r["server_sec"] for r in rs]
        row = {"group": name, "n": len(rs), "p50": pct(tot, 50), "p95": pct(tot, 95),
               "max": max(tot) if tot else None, "client_p50": pct([r["client_sec"] for r in rs], 50)}
        for ph, _ in PHASES:
            row[ph] = pct([r["phases"].get(ph) for r in rs if ph in r["phases"]], 50)
        out.append(row)
    return out


def gate_lines(runs: list[dict]) -> list[str]:
    warm = [r["server_sec"] for r in runs if r["outcome"] == "done" and r["temp"] == "warm"]
    allok = [r["server_sec"] for r in runs if r["outcome"] == "done"]
    bad = [r for r in runs if r["outcome"] != "done"]
    lines = []
    if warm:
        p50, mx = pct(warm, 50), max(warm)
        lines.append(f"- тёплые: p50 {p50} с (гейт ≤ {GATES['warm_p50']:.0f}) — {'ок' if p50 <= GATES['warm_p50'] else 'НЕ ок'}; "
                     f"max {mx:.1f} с (гейт ≤ {GATES['warm_max']:.0f}) — {'ок' if mx <= GATES['warm_max'] else 'НЕ ок'}")
    else:
        lines.append("- тёплых готовых прогонов нет — гейт agent-trial-01 не проверен")
    if allok:
        over = sum(1 for x in allok if x > GATES["goal"])
        lines.append(f"- цель мастера ≤ 3 мин: {len(allok) - over} из {len(allok)} готовых уложились")
    if bad:
        lines.append("- не готово: " + ", ".join(f"{r['plan']}#{r['n']} {r['outcome']}" for r in bad))
    return lines


def write_report(outdir: Path, runs: list[dict], meta: dict) -> str:
    ph_cols = [p for p, _ in PHASES if any(p in r["phases"] for r in runs)] or ["queue"]
    ph_title = dict(PHASES)
    head = ["#", "план", "темп.", "вход", "id", "итог", "загрузка с"] + [ph_title[p] + " с" for p in ph_cols] + \
        ["итого (сервер) с", "клиент с", "откат", "результат"]
    md = [f"# Замер пробы от загрузки до готового — {meta['when']}", "",
          f"Адрес `{meta['base']}` · прогонов {len(runs)} · планы {', '.join(meta['plans'])} · опрос {meta['poll']} с · "
          f"пауза между загрузками {meta['gap']} с · волна {meta['batch']}", "",
          "| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    tsv = ["\t".join(head)]
    for r in runs:
        cells = [r["n"], r["plan"], r["temp"], r["input"], (r["id"] or "—")[:6], r["outcome"], fmt(r["upload_sec"])] + \
            [fmt(r["phases"].get(p)) for p in ph_cols] + [fmt(r["server_sec"]), fmt(r["client_sec"]),
                                                          "да" if r["retried"] else "", fmt(r["result_ok"])]
        md.append("| " + " | ".join(str(c) for c in cells) + " |")
        tsv.append("\t".join(str(c) for c in cells))
    sh = ["группа", "n", "p50 с", "p95 с", "max с", "клиент p50 с"] + [f"{ph_title[p]} p50" for p in ph_cols]
    md += ["", "## Сводка (готовые; время — `finishedAt − createdAt`, этапы — медиана)", "",
           "| " + " | ".join(sh) + " |", "|" + "---|" * len(sh)]
    for s in summarize(runs):
        md.append("| " + " | ".join(fmt(x) for x in [s["group"], s["n"], s["p50"], s["p95"], s["max"], s["client_p50"]] +
                                    [s[p] for p in ph_cols]) + " |")
    md += ["", "## Гейты", ""] + gate_lines(runs)
    if meta.get("abort"):
        md += ["", f"**Серия остановлена:** {meta['abort']}"]
    text = "\n".join(md) + "\n"
    (outdir / "table.md").write_text(text, encoding="utf-8")
    (outdir / "table.tsv").write_text("\n".join(tsv) + "\n", encoding="utf-8")
    return text


def new_run_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    stem = "run-" + datetime.now().strftime("%H%M")
    for i in range(1, 100):
        d = root / (stem if i == 1 else f"{stem}-{i}")
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise RuntimeError("нет свободного имени папки прогона")


def is_local(base: str) -> bool:
    return (urlparse(base).hostname or "") in {"localhost", "127.0.0.1", "::1"}


def parse_named(vals: list[str]) -> list[tuple[str, Path]]:
    out = []
    for v in vals:
        name, _, p = v.partition("=") if "=" in v else ("", "", v)
        path = Path(os.path.expanduser(p))
        out.append((name or path.stem, path))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Замер пробы от загрузки до готового (p50/p95, тёплый/холодный).")
    ap.add_argument("--input", action="append", default=[], help="ИМЯ=путь к плану (JPEG/PNG/WebP/PDF); можно несколько")
    ap.add_argument("--listing", action="append", default=[], help="ИМЯ=путь к тексту объявления для плана ИМЯ")
    ap.add_argument("-n", type=int, default=3, help="прогонов на каждый план (по кругу: D, E, …, D, E, …)")
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--live", action="store_true", help="разрешить настоящие загрузки на нелокальный адрес")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--poll", type=float, default=1.5)
    ap.add_argument("--gap", type=float, default=200.0, help="секунд между загрузками (волнами)")
    ap.add_argument("--batch", type=int, default=1, help="заданий в волне сразу (1–3): замер очереди")
    ap.add_argument("--timeout", type=float, default=900.0, help="потолок одного прогона, с")
    ap.add_argument("--retry-cap", type=float, default=900.0, help="максимум ожидания по Retry-After, с")
    ap.add_argument("--cold-gap", type=float, default=600.0)
    ap.add_argument("--no-worker-sec", type=float, default=45.0)
    ap.add_argument("--temp", choices=["auto", "cold", "warm"], default="auto")
    ap.add_argument("--fresh-input", action="store_true", help="каждый прогон мимо кэша VLM (платно)")
    ap.add_argument("--dry-run", action="store_true", help="проверить входы и показать план прогона, ничего не грузить")
    ap.add_argument("--report-only", type=Path, help="пересобрать table.md/tsv из <папка>/runs.json")
    a = ap.parse_args(argv)

    if a.report_only:
        data = json.loads((a.report_only / "runs.json").read_text(encoding="utf-8"))
        print(write_report(a.report_only, data["runs"], data["meta"]))
        return 0
    if not a.input:
        ap.error("нужен хотя бы один --input")
    listings = {n: p for n, p in parse_named(a.listing)}
    items = []
    for name, p in parse_named(a.input):
        if not p.is_file():
            ap.error(f"нет файла {p}")
        mime_of(p.read_bytes()[:16])
        if p.stat().st_size > 15 * 1024 * 1024:
            ap.error(f"{p}: больше 15 МБ — прод ответит 413")
        lp = listings.get(name)
        items.append(Item(name, p, lp.read_text(encoding="utf-8").strip()[:5000] if lp else ""))
    cfg = Cfg(base=a.base, poll=a.poll, gap=a.gap, retry_cap=a.retry_cap, timeout=a.timeout, cold_gap=a.cold_gap,
              no_worker_sec=a.no_worker_sec, temp=a.temp, fresh_input=a.fresh_input, batch=a.batch)
    total = a.n * len(items)
    waves = math.ceil(total / max(1, min(a.batch, 3)))
    print(f"план: {total} загрузок на {a.base} ({', '.join(i.name for i in items)} × {a.n}), волн {waves}, "
          f"не меньше {(waves - 1) * a.gap / 60:.0f} мин пауз; прод пускает 10 загрузок в сутки с адреса")
    if total > 10 and not is_local(a.base):
        print("! больше 10 загрузок — прод откажет 429 daily_cap после десятой; разбей на дни или на несколько адресов")
    if a.dry_run:
        return 0
    if not is_local(a.base) and not a.live:
        print("отказ: нелокальный адрес без --live (каждая загрузка — настоящее задание)", file=sys.stderr)
        return 2
    outdir = new_run_dir(a.out)
    print(f"журнал: {outdir}")
    s = Series(cfg, items, a.n, outdir)
    runs = s.run()
    meta = {"when": datetime.now().isoformat(timespec="minutes"), "base": a.base, "plans": [i.name for i in items],
            "poll": a.poll, "gap": a.gap, "batch": a.batch, "abort": s.abort}
    dicts = [asdict(r) for r in runs]
    (outdir / "runs.json").write_text(json.dumps({"meta": meta, "runs": dicts}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(write_report(outdir, dicts, meta))
    return 0 if all(r.outcome == "done" for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())

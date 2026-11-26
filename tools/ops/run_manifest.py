#!/usr/bin/env python3
"""Карточка прогона RUN.json (T-20261125-89/2, П1.161 шаг 4): у каждого прогона в КОРНЕ его папки — чей он, чем кончился, что в нём промежуточное.
Нужна, чтобы потом (шаг 6, только со словом владельца) безопасно убирать промежуточное: 25.11 один прогон 13 товаров писал ≈535 МБ (≈7 glb на товар — копия на этапе).
ЭТОТ МОДУЛЬ НИЧЕГО НЕ УДАЛЯЕТ И НЕ ПЕРЕНОСИТ: пишет только RUN.json (и копию битого RUN.json.bad при перезаписи), `reclaimable()` лишь ВОЗВРАЩАЕТ список.

Схема (schema=1; новее известной — отказ, не затираем):
  schema            1
  task              «T-20261125-89/2» (или null)
  who               {"host": машина, "worker": рабочий/ведущий, "user": логин}
  started_utc       ISO-8601 UTC (первый start; повторный start его НЕ меняет), null — если карточку создал finish без start
  finished_utc      ISO-8601 UTC или null
  status            running | ok | fail
  restarts          сколько раз start звали повторно (дозапуск в той же папке)
  inputs            список строк: пути/файлы входов (как передали)
  intermediate      список ОТНОСИТЕЛЬНЫХ подпапок/файлов в папке прогона, которые можно не хранить после вердикта (не «..», не абсолютные, не RUN.json)
  note              строка (необязательно)
Запись атомарная: tmp-файл рядом (fsync) → os.replace. Повторный finish не портит start (меняет только status/finished_utc/note, дополняет intermediate).
Битый JSON — копия в RUN.json.bad (не затирая прежнюю .bad: .bad.1, .bad.2…), потом новая карточка. Карточка старой схемы (нет schema, ключи до v1) читается и при записи
поднимается до v1, незнакомые ключи сохраняются. Параллельные писатели не блокируются (прогон пишет свою карточку один).

Правило «при успехе промежуточное не хранить» — `tools/scout/rules/dev-disk.json` → `run_manifest.drop_intermediate_on_ok` (по умолчанию ВЫКЛ): `reclaimable(dir)` при
выключенном правиле, статусе не ok, битой/новой карточке отдаёт ПУСТОЙ список; при включённом и ok — [{path, bytes, files, free_bytes, link}] (free_bytes — файлы с одной жёсткой ссылкой:
остальное диск не освободит; симлинк в списке с нулями и link=true, мы его не раскрываем).

Библиотека и CLI, зовётся из любого прогона, в т.ч. из скриптов вне репозитория:
  python3 tools/ops/run_manifest.py start  ПАПКА --task T-… [--who имя] [--input П]… [--intermediate ПОДПАПКА]… [--note ТЕКСТ]
  python3 tools/ops/run_manifest.py finish ПАПКА --status ok|fail [--intermediate ПОДПАПКА]… [--note ТЕКСТ]
  python3 tools/ops/run_manifest.py show   ПАПКА [--json] [--assume-enabled]
  из Python: `sys.path.insert(0, "<репо>/tools/ops"); import run_manifest as rm; rm.start(dir, task=…); …; rm.finish(dir, "ok")`
Задачу и рабочего берёт из окружения, если не указаны: REMLAB_TASK; REMLAB_WORKER или REMLAB_ROLE. Код CLI 0; 2 — плохие аргументы / карточка новее схемы / битый путь.
Тест: `python -m pytest tools/ops/tests/test_run_manifest.py -q`. Без внешних зависимостей (python 3.9+)."""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RULES_PATH = ROOT / "tools" / "scout" / "rules" / "dev-disk.json"
SCHEMA = 1
CARD = "RUN.json"
STATUSES = ("running", "ok", "fail")
NO_CARD_STATES = ("нет", "битая")   # состояния read_card, при которых карточки у прогона фактически нет


class ManifestError(Exception):
    """Нельзя безопасно писать карточку (схема новее известной, плохой путь подпапки)."""


def now_utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def card_path(run_dir: str) -> str:
    return os.path.join(os.path.expanduser(str(run_dir)), CARD)


def read_card(run_dir: str) -> dict:
    """Читает карточку. Возвращает {"state", "card"}: state — «нет» | «битая» | «новее схемы» | «старая v0» | running | ok | fail; card — dict или None.
    Только чтение; битую не чинит."""
    p = card_path(run_dir)
    try:
        raw = Path(p).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"state": "нет", "card": None}
    except (OSError, UnicodeDecodeError):
        return {"state": "битая", "card": None}
    try:
        d = json.loads(raw)
    except ValueError:
        return {"state": "битая", "card": None}
    if not isinstance(d, dict):
        return {"state": "битая", "card": None}
    sch = d.get("schema")
    if isinstance(sch, int) and not isinstance(sch, bool) and sch > SCHEMA:
        return {"state": "новее схемы", "card": d}
    if sch is None or not isinstance(sch, int):
        return {"state": "старая v0", "card": d}
    st = d.get("status")
    return {"state": st if st in STATUSES else "битая", "card": d}


def norm_rel(sub: str) -> str:
    """Подпапка промежуточного — только относительная, внутри папки прогона, не сама карточка."""
    s = str(sub).strip().replace("\\", "/")
    parts = [x for x in s.split("/") if x not in ("", ".")]
    if not s or s.startswith("/") or ".." in parts or not parts or parts[0] == CARD or (len(parts) == 1 and parts[0].startswith(CARD + ".")):
        raise ManifestError(f"плохая подпапка промежуточного: {sub!r} (нужна относительная внутри папки прогона)")
    return "/".join(parts)


def _atomic_write(path: str, data: str) -> None:
    tmp = f"{path}.{os.getpid()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)   # только свой tmp-файл после сбоя записи
        except OSError:
            pass
        raise


def _save_bad(path: str) -> None:
    """Копия битого RUN.json рядом (RUN.json.bad, .bad.1 …) — ничего не теряем при перезаписи."""
    try:
        raw = Path(path).read_bytes()
    except OSError:
        return
    n, dst = 0, path + ".bad"
    while os.path.exists(dst):
        n += 1
        dst = f"{path}.bad.{n}"
    tmp = f"{dst}.{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, dst)


def _who(who: str | None) -> dict:
    return {"host": socket.gethostname(), "worker": who or os.environ.get("REMLAB_WORKER") or os.environ.get("REMLAB_ROLE") or None,
            "user": os.environ.get("USER") or os.environ.get("LOGNAME") or None}


def _load_for_write(run_dir: str) -> dict | None:
    """Текущая карточка для правки: dict (старая схема — поднята до v1), None — писать с нуля (нет или битая; битая — копия .bad). Новее схемы — ManifestError."""
    r = read_card(run_dir)
    if r["state"] == "нет":
        return None
    if r["state"] == "битая":
        _save_bad(card_path(run_dir))
        return None
    if r["state"] == "новее схемы":
        raise ManifestError(f"{card_path(run_dir)}: schema={r['card'].get('schema')} новее известной {SCHEMA} — не трогаю")
    d = dict(r["card"])
    d["schema"] = SCHEMA
    if d.get("status") not in STATUSES:
        d["status"] = "running" if d.get("finished_utc") is None else "fail"
    d.setdefault("inputs", [])
    d.setdefault("intermediate", [])
    d["inputs"] = [str(x) for x in d["inputs"]] if isinstance(d["inputs"], list) else [str(d["inputs"])]
    d["intermediate"] = [x for x in d["intermediate"] if isinstance(x, str)] if isinstance(d["intermediate"], list) else []
    return d


def _union(a: list, b: list | None) -> list:
    out = list(a)
    for x in b or []:
        if x not in out:
            out.append(x)
    return out


def start(run_dir: str, task: str | None = None, who: str | None = None, inputs: list | None = None, intermediate: list | None = None,
          note: str | None = None) -> dict:
    """Начало прогона: создаёт папку (если нет) и RUN.json со статусом running. Повторный start: started_utc не меняется, restarts+1, статус снова running."""
    run_dir = os.path.expanduser(str(run_dir))
    inter = [norm_rel(x) for x in (intermediate or [])]
    os.makedirs(run_dir, exist_ok=True)
    d = _load_for_write(run_dir)
    if d is None:
        d = {"schema": SCHEMA, "task": task or os.environ.get("REMLAB_TASK"), "who": _who(who), "started_utc": now_utc(), "finished_utc": None,
             "status": "running", "restarts": 0, "inputs": [str(x) for x in (inputs or [])], "intermediate": inter}
    else:
        d["restarts"] = int(d.get("restarts") or 0) + 1 if d.get("started_utc") else int(d.get("restarts") or 0)
        d["started_utc"] = d.get("started_utc") or now_utc()
        d["finished_utc"] = None
        d["status"] = "running"
        if task:
            d["task"] = task
        if who:
            d["who"] = _who(who)
        d["inputs"] = _union(d["inputs"], [str(x) for x in (inputs or [])])
        d["intermediate"] = _union(d["intermediate"], inter)
    if note:
        d["note"] = note
    _atomic_write(card_path(run_dir), json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    return d


def finish(run_dir: str, status: str, intermediate: list | None = None, note: str | None = None) -> dict:
    """Конец прогона: status ok|fail, finished_utc. started_utc, task, who, inputs не трогает; повторный finish — последний вердикт побеждает, start цел.
    Нет карточки (start не звали) — создаётся с started_utc=null."""
    if status not in ("ok", "fail"):
        raise ManifestError(f"status должен быть ok или fail, а не {status!r}")
    run_dir = os.path.expanduser(str(run_dir))
    inter = [norm_rel(x) for x in (intermediate or [])]
    os.makedirs(run_dir, exist_ok=True)
    d = _load_for_write(run_dir)
    if d is None:
        d = {"schema": SCHEMA, "task": os.environ.get("REMLAB_TASK"), "who": _who(None), "started_utc": None, "finished_utc": None, "status": status,
             "restarts": 0, "inputs": [], "intermediate": []}
        d.setdefault("note", "карточку создал finish: start не вызывали")
    d["status"] = status
    d["finished_utc"] = now_utc()
    d["intermediate"] = _union(d["intermediate"], inter)
    if note:
        d["note"] = note
    _atomic_write(card_path(run_dir), json.dumps(d, ensure_ascii=False, indent=1) + "\n")
    return d


def load_flag(path: Path | None = None) -> bool:
    """drop_intermediate_on_ok из dev-disk.json; нет файла/ключа — ВЫКЛ."""
    try:
        d = json.loads((path or RULES_PATH).read_text(encoding="utf-8"))
        return bool((d.get("run_manifest") or {}).get("drop_intermediate_on_ok", False))
    except (OSError, ValueError, AttributeError):
        return False


def tree_usage(path: str) -> dict:
    """Размер пути без раскрытия симлинков: {bytes, files, free_bytes (nlink==1), link}. Нет пути — нули."""
    out = {"bytes": 0, "files": 0, "free_bytes": 0, "link": False}
    try:
        st = os.lstat(path)
    except OSError:
        return out
    if os.path.islink(path):
        out["link"] = True
        return out
    seen: set = set()

    def add(s: os.stat_result) -> None:
        if s.st_nlink > 1:
            k = (s.st_dev, s.st_ino)
            if k in seen:
                return
            seen.add(k)
        out["bytes"] += s.st_size
        out["files"] += 1
        if s.st_nlink == 1:
            out["free_bytes"] += s.st_size

    if not os.path.isdir(path):
        add(st)
        return out
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_symlink():
                            continue
                        if e.is_dir(follow_symlinks=False):
                            stack.append(e.path)
                        else:
                            add(e.stat(follow_symlinks=False))
                    except OSError:
                        continue
        except OSError:
            continue
    return out


def reclaimable(run_dir: str, enabled: bool | None = None) -> list:
    """Что в прогоне можно НЕ хранить: пусто, если правило выкл (enabled=None — читаем dev-disk.json), карточка не ok / битая / новее схемы, либо список пуст.
    Иначе [{path (относительный), abs, bytes, files, free_bytes, link}] по подпапкам из `intermediate`, что реально лежат внутри папки прогона (realpath; выход наружу — пропуск).
    НЕ УДАЛЯЕТ."""
    if enabled is None:
        enabled = load_flag()
    if not enabled:
        return []
    r = read_card(run_dir)
    if r["state"] != "ok":
        return []
    base = os.path.realpath(os.path.expanduser(str(run_dir)))
    out = []
    for sub in r["card"].get("intermediate") or []:
        try:
            rel = norm_rel(sub)
        except (ManifestError, TypeError):
            continue
        p = os.path.join(base, rel)
        # родитель (не сам путь: симлинк в конце оставляем симлинком) должен лежать внутри папки прогона
        real_parent = os.path.realpath(os.path.dirname(p))
        if real_parent != base and not real_parent.startswith(base + os.sep):
            continue
        if not os.path.lexists(p):
            continue
        u = tree_usage(p)
        out.append({"path": rel, "abs": p, **u})
    return out


def render_show(run_dir: str, assume_enabled: bool | None = None) -> str:
    r = read_card(run_dir)
    lines = [f"{card_path(run_dir)}: {r['state']}"]
    if r["card"]:
        lines.append(json.dumps(r["card"], ensure_ascii=False, indent=1))
    flag = load_flag() if assume_enabled is None else assume_enabled
    rec = reclaimable(run_dir, enabled=flag)
    lines.append(f"правило drop_intermediate_on_ok: {'ВКЛ' if flag else 'ВЫКЛ'}; можно не хранить: " +
                 ("; ".join(f"{x['path']} {x['bytes'] / 1024 ** 2:.1f} МБ/{x['files']} ф (освободится {x['free_bytes'] / 1024 ** 2:.1f} МБ)" for x in rec) if rec else "ничего"))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Карточка прогона RUN.json (ничего не удаляет)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start")
    s.add_argument("dir")
    s.add_argument("--task")
    s.add_argument("--who")
    s.add_argument("--input", action="append", default=[])
    s.add_argument("--intermediate", action="append", default=[])
    s.add_argument("--note")
    f = sub.add_parser("finish")
    f.add_argument("dir")
    f.add_argument("--status", required=True, choices=["ok", "fail"])
    f.add_argument("--intermediate", action="append", default=[])
    f.add_argument("--note")
    w = sub.add_parser("show")
    w.add_argument("dir")
    w.add_argument("--json", action="store_true")
    w.add_argument("--assume-enabled", action="store_true", help="показать «можно не хранить», будто правило ВКЛ (само правило не меняет)")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "start":
            d = start(a.dir, a.task, a.who, a.input, a.intermediate, a.note)
            print(json.dumps(d, ensure_ascii=False))
        elif a.cmd == "finish":
            d = finish(a.dir, a.status, a.intermediate, a.note)
            print(json.dumps(d, ensure_ascii=False))
        else:
            if a.json:
                r = read_card(a.dir)
                print(json.dumps({"state": r["state"], "card": r["card"],
                                  "reclaimable": reclaimable(a.dir, True if a.assume_enabled else None)}, ensure_ascii=False, indent=1))
            else:
                print(render_show(a.dir, True if a.assume_enabled else None))
    except ManifestError as e:
        print(f"run_manifest: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"run_manifest: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

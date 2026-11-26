#!/usr/bin/env python3
"""Замер: чем занят ~/remlab-logs — топ папок по размеру (T-20261125-89/2, П1.161 шаг 4). ТОЛЬКО ЧТЕНИЕ: ничего не удаляет, не переносит и не пишет.

Для каждой папки верхнего уровня `src` (по умолчанию ~/remlab-logs): задача T-… (по имени папки), размер, чем занято (меши glb / кадры png-jpg-видео / кэш npz-npy-pt /
логи и таблицы / прочее — ГБ и число файлов), сколько из этого лежит внутри рабочих копий git (папка с файлом `.git`), возраст (сутки от самой свежей записи),
есть ли карточка RUN.json (tools/ops/run_manifest.py) и её статус. Папки без карточки — одной строкой итога. Второй диск (`dst`, по умолчанию
/mnt/hdd/remlab-logs-arhiv) — отдельной строкой итога; симлинки из src на него не раскрываем (их размер — 0, считаются в «ссылок на HDD»).

Размер — по `lstat` (st_size, без раскрытия симлинков); файл с несколькими жёсткими ссылками считается один раз. Один проход одним потоком; сам себя понижает приоритет
(`os.nice(10)`) — для обхода 120 ГБ с сотнями тысяч файлов запускать `nice -n 19 ionice -c3 python3 tools/ops/logs_size_report.py` (не больше 1 ядра, платного 0).

Запуск: `python3 tools/ops/logs_size_report.py [--src ПАПКА] [--dst ПАПКА] [--top 20] [--json] [--min-gb 0]`; тест: `python -m pytest tools/ops/tests/test_logs_size_report.py -q`.
Код 0; 2 — src не папка. Без внешних зависимостей (python 3.9+)."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_manifest as RM  # noqa: E402  (карточка RUN.json: читаем статус)

GB = 1024 ** 3
CATS = ("glb", "кадры", "кэш", "логи", "прочее")
EXT = {
    "glb": {".glb", ".gltf", ".obj", ".ply", ".stl", ".fbx", ".blend", ".usdz"},
    "кадры": {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".mp4", ".webm", ".mov", ".avif", ".exr", ".hdr"},
    "кэш": {".npz", ".npy", ".pt", ".pth", ".safetensors", ".pkl", ".pickle", ".bin", ".ckpt", ".onnx", ".h5", ".parquet", ".cache"},
    "логи": {".log", ".txt", ".json", ".jsonl", ".md", ".csv", ".tsv", ".yml", ".yaml", ".out", ".err", ".html", ".sql", ".py", ".sh", ".mjs", ".js"},
}
EXT_CAT = {e: c for c, es in EXT.items() for e in es}
TASK_RE = re.compile(r"T-\d{8}-\d+(?:-\d+)?", re.I)
SHORT_RE = re.compile(r"(?:^|[^a-z0-9])t(\d{2,4})(?:-(\d{1,2}))?(?![0-9])", re.I)


def task_of(name: str) -> str:
    """Задача по имени папки: T-20261119-100 → как есть; t183-2 / out-t99-1126 → «T-?-183/2» (номер из имени, дата неизвестна); иначе «—»."""
    m = TASK_RE.search(name)
    if m:
        return m.group(0).upper()
    m = SHORT_RE.search(name)
    if m:
        return f"T-?-{m.group(1)}" + (f"/{m.group(2)}" if m.group(2) else "")
    return "—"


def cat_of(name: str) -> str:
    return EXT_CAT.get(os.path.splitext(name)[1].lower(), "прочее")


def new_acc() -> dict:
    return {"bytes": {c: 0 for c in CATS}, "files": {c: 0 for c in CATS}, "wt_bytes": 0, "wt_roots": 0, "newest": 0.0, "nfiles": 0}


def walk_tree(root: str, acc: dict, seen: set) -> None:
    """Обходит root, накапливая в acc размеры по категориям. Симлинки не раскрываем. Папка с файлом/папкой `.git` — корень рабочей копии (всё под ней — wt_bytes)."""
    stack = [(root, False)]
    while stack:
        d, in_wt = stack.pop()
        try:
            with os.scandir(d) as it:
                entries = list(it)
        except OSError:
            continue
        if not in_wt and any(e.name == ".git" for e in entries):
            in_wt = True
            acc["wt_roots"] += 1
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            acc["newest"] = max(acc["newest"], st.st_mtime)
            if e.is_symlink():
                continue
            if e.is_dir(follow_symlinks=False):
                stack.append((e.path, in_wt))
                continue
            if st.st_nlink > 1:
                key = (st.st_dev, st.st_ino)
                if key in seen:
                    continue
                seen.add(key)
            c = cat_of(e.name)
            acc["bytes"][c] += st.st_size
            acc["files"][c] += 1
            acc["nfiles"] += 1
            if in_wt:
                acc["wt_bytes"] += st.st_size


def measure(src: str, now: float | None = None) -> dict:
    """Все папки верхнего уровня src: список строк + файлы в корне + симлинки. Одна общая «видели» для жёстких ссылок."""
    now = time.time() if now is None else now
    seen: set = set()
    rows, loose_bytes, loose_files, links = [], 0, 0, 0
    with os.scandir(src) as it:
        entries = sorted(it, key=lambda e: e.name)
    for e in entries:
        try:
            if e.is_symlink():
                links += 1
                continue
            if not e.is_dir(follow_symlinks=False):
                st = e.stat(follow_symlinks=False)
                loose_bytes += st.st_size
                loose_files += 1
                continue
        except OSError:
            continue
        acc = new_acc()
        try:
            acc["newest"] = e.stat(follow_symlinks=False).st_mtime
        except OSError:      # папку убрали прямо во время замера (автоуборка/другая сессия) — пропуск
            continue
        walk_tree(e.path, acc, seen)
        card = RM.read_card(e.path)
        rows.append({
            "name": e.name,
            "task": task_of(e.name),
            "bytes": sum(acc["bytes"].values()),
            "by_cat": acc["bytes"],
            "files_by_cat": acc["files"],
            "nfiles": acc["nfiles"],
            "wt_bytes": acc["wt_bytes"],
            "wt_roots": acc["wt_roots"],
            "age_d": round((now - acc["newest"]) / 86400, 1) if acc["newest"] else None,
            "card": card["state"],
        })
    return {"rows": rows, "loose_bytes": loose_bytes, "loose_files": loose_files, "links": links}


def total_of(src: str) -> dict:
    """Итог по всему дереву (для HDD-архива): размер по категориям, число папок верхнего уровня, число файлов."""
    seen: set = set()
    acc = new_acc()
    n_dirs = 0
    try:
        with os.scandir(src) as it:
            for e in it:
                if e.is_dir(follow_symlinks=False):
                    n_dirs += 1
    except OSError:
        return {"present": False}
    walk_tree(src, acc, seen)
    return {"present": True, "bytes": sum(acc["bytes"].values()), "by_cat": acc["bytes"], "nfiles": acc["nfiles"], "dirs": n_dirs, "wt_roots": acc["wt_roots"]}


def gb(b: float) -> str:
    return f"{b / GB:.2f}"


def cat_cell(row: dict) -> str:
    parts = [f"{c} {gb(row['by_cat'][c])}/{row['files_by_cat'][c]}" for c in CATS if row["files_by_cat"][c]]
    return "; ".join(parts) or "пусто"


def render(res: dict, top: int, min_gb: float, hdd: dict | None, src: str) -> str:
    rows = sorted(res["rows"], key=lambda r: -r["bytes"])
    total = sum(r["bytes"] for r in rows) + res["loose_bytes"]
    out = [f"# Замер {src}: {len(rows)} папок + {res['loose_files']} файлов в корне, всего {gb(total)} ГБ (ссылок на HDD: {res['links']})", ""]
    out.append("| # | папка | задача | ГБ | чем занято (ГБ/файлов) | рабочая копия git (ГБ внутри / корней) | возраст, сут | карточка |")
    out.append("|--:|---|---|--:|---|---|--:|---|")
    shown = 0
    for r in rows:
        if r["bytes"] < min_gb * GB or shown >= top:
            break
        shown += 1
        wt = f"{gb(r['wt_bytes'])} / {r['wt_roots']}" if r["wt_roots"] else "нет"
        out.append(f"| {shown} | `{r['name']}` | {r['task']} | {gb(r['bytes'])} | {cat_cell(r)} | {wt} | {r['age_d']} | {r['card']} |")
    top_sum = sum(r["bytes"] for r in rows[:shown])
    out += ["", f"Топ-{shown}: {gb(top_sum)} ГБ из {gb(total)} ({(100 * top_sum / total) if total else 0:.0f} %)."]
    cat_sum = {c: sum(r["by_cat"][c] for r in rows) for c in CATS}
    cat_n = {c: sum(r["files_by_cat"][c] for r in rows) for c in CATS}
    out.append("По всем папкам: " + "; ".join(f"{c} {gb(cat_sum[c])} ГБ / {cat_n[c]} файлов" for c in CATS) + ".")
    wt_all = sum(r["wt_bytes"] for r in rows)
    wt_n = sum(r["wt_roots"] for r in rows)
    out.append(f"Внутри рабочих копий git: {wt_n} копий, {gb(wt_all)} ГБ ({(100 * wt_all / total) if total else 0:.0f} % от всего).")
    nc = [r for r in rows if r["card"] in RM.NO_CARD_STATES]
    out.append(f"Без карточки: {len(nc)} папок, {gb(sum(r['bytes'] for r in nc))} ГБ (из {len(rows)} папок, {gb(sum(r['bytes'] for r in rows))} ГБ); "
               f"с карточкой: {len(rows) - len(nc)} папок.")
    if hdd is not None:
        if hdd.get("present"):
            out.append(f"HDD-архив: {gb(hdd['bytes'])} ГБ, {hdd['dirs']} папок, {hdd['nfiles']} файлов; " +
                       "; ".join(f"{c} {gb(hdd['by_cat'][c])}" for c in CATS) + f"; рабочих копий git внутри: {hdd['wt_roots']}.")
        else:
            out.append("HDD-архив: не смонтирован / нет папки.")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Замер ~/remlab-logs (только чтение)")
    ap.add_argument("--src", default="~/remlab-logs")
    ap.add_argument("--dst", default="/mnt/hdd/remlab-logs-arhiv", help="второй диск; пустая строка — не считать")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--min-gb", type=float, default=0.0)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    src = os.path.expanduser(a.src)
    if not os.path.isdir(src):
        print(f"нет папки {src}", file=sys.stderr)
        return 2
    try:
        os.nice(10)
    except OSError:
        pass
    res = measure(src)
    hdd = total_of(os.path.expanduser(a.dst)) if a.dst else None
    if a.json:
        print(json.dumps({"src": src, "result": res, "hdd": hdd}, ensure_ascii=False, indent=1))
    else:
        print(render(res, a.top, a.min_gb, hdd, src))
    return 0


if __name__ == "__main__":
    sys.exit(main())

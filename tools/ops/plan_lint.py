#!/usr/bin/env python3
"""Линт плана задач `.memory_bank/plan-zadach.md` — правила P-070 (сводное 23.11; снятые P-015/P-019/P-028) проверяет код, а не память агента (T-20261123-23/1, п.1).

Формат пункта (шапка плана): `**Пn.m · машина · исполнитель · N % — что делаю, чтобы что**`, под ним (или в конце строки) скрытый
комментарий с T-ID. Проверки (категории; по умолчанию все — предупреждения, exit 0; `--block КАТ,КАТ` делает выбранные блокирующими):
  PLAN-FORMAT    видимая строка пункта не по формату (нет машины или исполнителя, нет « — » после %)
  PLAN-PCT       % вне {0,10,20,30,40,50,60,70,80,90,95,100}
  PLAN-CHECK     ✅ у пункта, где % не 100
  PLAN-WAIT      🕓 без слова «ждёт:»
  PLAN-TID       у пункта нет T-ID (ни в строке, ни в скрытом комментарии следующей строки)
  PLAN-DIRECTOR  строк «Директор:» в шапке не ровно одна
  PLAN-DUP       один T-ID у двух разных исполнителей (машина + исполнитель)
Видимыми считаются строки вне HTML-комментариев `<!-- … -->` (многострочных тоже); внутри комментария — скрытые блоки «для %».
Без зависимостей (python 3.9+, без node: на algor его нет). Имена машин в код не зашиты: берутся из шапки/самих строк.
Запуск: `python tools/ops/plan_lint.py [план] [--block КАТ,…] [--json]`; тест: `python -m pytest tools/ops/tests/test_plan_lint.py -q`."""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ALLOWED_PCT = {0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}
CATEGORIES = ("PLAN-FORMAT", "PLAN-PCT", "PLAN-CHECK", "PLAN-WAIT", "PLAN-TID", "PLAN-DIRECTOR", "PLAN-DUP")

ITEM = re.compile(r"^(\*\*)?П(\d+)\.(\d+)\s*·\s*(.*)$")
PCT = re.compile(r"(\d+)\s*%")
TID = re.compile(r"\bT-(\d{8}-\d+|\d+)")
FULL = re.compile(r"^(?P<machine>[^·]+?)\s*·\s*(?P<who>[^·]+?)\s*·\s*(?P<pct>\d+)\s*%\s*(?:\([^)]*\)\s*)?—\s*\S")


@dataclass
class Finding:
    cat: str
    line: int
    msg: str

    def __str__(self) -> str:
        return f"{self.cat} :{self.line} — {self.msg}"


def visible_lines(text: str):
    """Строки вне HTML-комментариев: (номер, видимая часть). Комментарий в конце строки отрезается, его текст — отдельно."""
    out, in_c = [], False
    for n, raw in enumerate(text.split("\n"), 1):
        vis, hid, i = "", "", 0
        while i < len(raw):
            if in_c:
                j = raw.find("-->", i)
                if j < 0:
                    hid += raw[i:]
                    i = len(raw)
                else:
                    hid += raw[i:j]
                    in_c, i = False, j + 3
            else:
                j = raw.find("<!--", i)
                if j < 0:
                    vis += raw[i:]
                    i = len(raw)
                else:
                    vis += raw[i:j]
                    in_c, i = True, j + 4
        out.append((n, vis, hid))
    return out


def tids(s: str) -> set[str]:
    return {m.group(0) for m in TID.finditer(s)}


def lint_plan(text: str) -> list[Finding]:
    f: list[Finding] = []
    rows = visible_lines(text.replace("\r\n", "\n"))
    # --- «Директор:» ровно одна строка (в шапке — она в комментарии, поэтому смотрим весь файл, но только начало строки)
    d = [n for n, raw in enumerate(text.split("\n"), 1) if re.match(r"^Директор:", raw)]
    if len(d) != 1:
        f.append(Finding("PLAN-DIRECTOR", d[1] if len(d) > 1 else 1, f"строк «Директор:» {len(d)}, нужна ровно одна"))
    items = []  # (line, machine, who, tids)
    for idx, (n, vis, hid) in enumerate(rows):
        s = vis.strip()
        m = ITEM.match(s)
        if not m:
            continue
        body = m.group(4).rstrip("*").rstrip()
        label = f"П{m.group(2)}.{m.group(3)}"
        full = FULL.match(body)
        pm = PCT.search(body)
        pct = int(pm.group(1)) if pm else None
        if not full:
            f.append(Finding("PLAN-FORMAT", n, f"{label}: нет «машина · исполнитель · N % — текст»"))
        if pct is None:
            f.append(Finding("PLAN-PCT", n, f"{label}: нет процента"))
        elif pct not in ALLOWED_PCT:
            f.append(Finding("PLAN-PCT", n, f"{label}: {pct} % вне ступеней 0,10…90,95,100"))
        if "✅" in s and pct != 100:
            f.append(Finding("PLAN-CHECK", n, f"{label}: ✅ при {pct if pct is not None else '?'} % (✅ только у 100 %)"))
        if "🕓" in s and "ждёт:" not in s:
            f.append(Finding("PLAN-WAIT", n, f"{label}: 🕓 без «ждёт:»"))
        # T-ID: в хвостовом комментарии строки, либо в скрытой строке сразу под пунктом
        ids = tids(hid)
        j = idx + 1
        while not ids and j < len(rows) and not rows[j][1].strip() and rows[j][2].strip():
            ids |= tids(rows[j][2])
            j += 1
        if not ids:
            f.append(Finding("PLAN-TID", n, f"{label}: нет T-ID в скрытом комментарии"))
        if full:
            items.append((n, label, full.group("machine").strip(), full.group("who").strip(), ids))
    by = defaultdict(list)
    for n, label, mach, who, ids in items:
        for t in ids:
            by[re.sub(r"/\d+$", "", t)].append((n, label, mach, who))
    for t, lst in sorted(by.items()):
        owners = {(m, w) for _, _, m, w in lst}
        if len(owners) > 1:
            f.append(Finding("PLAN-DUP", lst[1][0], f"{t} у разных исполнителей: " + "; ".join(f"{lb} {m}/{w}" for _, lb, m, w in lst)))
    return sorted(f, key=lambda x: (x.line, x.cat))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plan", nargs="?", default=".memory_bank/plan-zadach.md")
    ap.add_argument("--block", default="", help="категории через запятую, которые дают exit 1 (остальные — предупреждения)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    p = Path(a.plan)
    if not p.is_file():
        print(f"[plan-lint] файла нет: {p}", file=sys.stderr)
        return 2
    found = lint_plan(p.read_text(encoding="utf-8"))
    block = {c.strip() for c in a.block.split(",") if c.strip()}
    bad = [x for x in found if x.cat in block]
    if a.json:
        print(json.dumps([x.__dict__ for x in found], ensure_ascii=False, indent=1))
    else:
        cnt = defaultdict(int)
        for x in found:
            cnt[x.cat] += 1
        print(f"[plan-lint] {p}: находок {len(found)}" + (" (" + ", ".join(f"{c} {n}" for c, n in sorted(cnt.items())) + ")" if cnt else ""))
        for x in found:
            print(("  ✗ " if x.cat in block else "  ~ ") + str(x))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

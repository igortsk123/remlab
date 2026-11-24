#!/usr/bin/env python3
"""Линт брифов рабочим `.memory_bank/_intake/brief-T-*.md` — обязательные строки правил P-071/P-072 (сводных 23.11; снятые P-024/P-032/P-037/P-041/P-067/P-046) проверяет код
(T-20261123-23/1, п.2). Директор зовёт его перед выдачей брифа; без аргументов смотрит брифы с датой в T-ID не раньше `--since` (23.11).
CI (с 24.11, ревью Fable Б9/Б10): блокирует `--since 2026-11-25 --block BRIEF-PIPELINE,BRIEF-SALAD,BRIEF-CLEAN` — старые брифы не трогаются.
Проверки (категории; по умолчанию предупреждения, exit 0; `--block КАТ,…` — блокирующие):
  BRIEF-LABEL     первая строка — метка `[роль] T-…`
  BRIEF-SALAD     есть вопрос «Salad или наши ядра» (P-072)
  BRIEF-CLEAN     есть «Что чистит шаг» (P-072)
  BRIEF-PIPELINE  нет какой-то из 4 строк конвейера: «правило изменено», «где ещё действует», «шаг пересоберёт», «особый случай» (P-071)
  BRIEF-BOUNDS    нет раздела/строки «Границы» (P-072)
  BRIEF-MEMCHECK  нет «/memory-check не запускать — свод директор» (P-072/P-071)
«N/A: причина» вместо содержимого допустимо — проверяется наличие самой строки, не её смысл. Без зависимостей (python 3.9+).
Запуск: `python tools/ops/brief_lint.py [файл …] [--since 20261123|2026-11-23] [--block КАТ,…] [--root .]`; тест: `python -m pytest tools/ops/tests/test_brief_lint.py -q`."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LABEL = re.compile(r"^\[[^\]\n]{2,40}\]\s+T-\d{8}-\d+")
NAME = re.compile(r"^brief-T-(\d{8})-\d+.*\.md$")
PIPELINE = (("правило изменено", "правило изменено"), ("где ещё действует", "где ещё действует"), ("шаг пересоберёт", "пересоберёт"), ("особый случай", "особый случай"))
CATEGORIES = ("BRIEF-LABEL", "BRIEF-SALAD", "BRIEF-CLEAN", "BRIEF-PIPELINE", "BRIEF-BOUNDS", "BRIEF-MEMCHECK")


def lint_brief(text: str) -> list[tuple[str, str]]:
    t = text.replace("\r\n", "\n").lstrip("﻿")
    low = t.lower()
    first = t.split("\n", 1)[0]
    f: list[tuple[str, str]] = []
    if not LABEL.match(first):
        f.append(("BRIEF-LABEL", f"первая строка не «[роль] T-ГГГГММДД-N …»: «{first[:60]}»"))
    if "salad или наши" not in low:
        f.append(("BRIEF-SALAD", "нет «Salad или наши ядра»"))
    if "что чистит шаг" not in low:
        f.append(("BRIEF-CLEAN", "нет «Что чистит шаг»"))
    # бриф может потребовать строки в отчёте («4 строки конвейера» — P-071 принимает и так), а не нести их текстом
    miss = [] if "строки конвейера" in low else [name for name, key in PIPELINE if key not in low]
    if miss:
        f.append(("BRIEF-PIPELINE", "нет строк конвейера: " + ", ".join(miss)))
    if not re.search(r"^#{1,4}\s*границы|^\**границы\**\b|\bграницы\b\s*:", low, re.M):
        f.append(("BRIEF-BOUNDS", "нет «Границы»"))
    if not re.search(r"memory-check[^\n]{0,80}(не запуска|свод\s+директор|директор[^\n]{0,20}свод)", low):
        f.append(("BRIEF-MEMCHECK", "нет «/memory-check не запускать — свод директор»"))
    return f


def collect(root: Path, since: str) -> list[Path]:
    d = root / ".memory_bank" / "_intake"
    out = []
    for p in sorted(d.glob("brief-T-*.md")):
        m = NAME.match(p.name)
        if m and m.group(1) >= since:
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--since", default="20261123", help="проверять брифы с датой в имени не раньше (ГГГГММДД или ГГГГ-ММ-ДД)")
    ap.add_argument("--block", default="")
    ap.add_argument("--root", default=".")
    a = ap.parse_args(argv)
    a.since = a.since.replace("-", "")
    if not re.fullmatch(r"\d{8}", a.since):
        ap.error("--since: дата ГГГГММДД или ГГГГ-ММ-ДД")
    files = [Path(x) for x in a.files] or collect(Path(a.root), a.since)
    block = {c.strip() for c in a.block.split(",") if c.strip()}
    unknown = block - set(CATEGORIES)
    if unknown:
        ap.error("--block: неизвестные категории " + ", ".join(sorted(unknown)))
    total = bad = 0
    for p in files:
        if not p.is_file():
            print(f"[brief-lint] файла нет: {p}", file=sys.stderr)
            return 2
        found = lint_brief(p.read_text(encoding="utf-8"))
        total += len(found)
        print(f"[brief-lint] {p.name}: " + ("чисто" if not found else f"находок {len(found)}"))
        for cat, msg in found:
            hard = cat in block
            bad += hard
            print(("  ✗ " if hard else "  ~ ") + f"{cat} — {msg}")
    print(f"[brief-lint] брифов {len(files)}, находок {total}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

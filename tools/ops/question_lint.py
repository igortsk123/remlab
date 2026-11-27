#!/usr/bin/env python3
"""Линт вопроса советнику и его ответа (T-20261127-175/7, совет Fable 27 § 2 «Совет советника»): в файле вопроса — обязательное поле «Что уже пробовали (поиск по банку)»,
в ответе — «Сверено с банком». Код проверяет НАЛИЧИЕ и форму поля, не его смысл; пустое поле, «—», «нет», «не знаю» — находка.

Вопрос `vopros-N.md` (категория QUESTION-BANK): есть раздел с заголовком «Что уже пробовали (поиск по банку)» (любой уровень `#`), и в нём
  • хотя бы одна строка-метка `bank_search.py --block`: «Поиск по банку: «запрос» · найдено N мест … · ГГГГ-ММ-ДД» (поиск запускался; «найдено 0» — допустимо), ИЛИ
  • «N/A: причина» (≥ 10 знаков) — когда вопрос не про способ/пробу (например, просьба оценить кадр).
Ответ `otvet-N.md` (категория ANSWER-BANK): есть строка «Сверено с банком: …» (в начале строки, можно жирным), после двоеточия ≥ 10 знаков и не пустышка:
«да — ADR-0455, урок 712; закрытого не предлагаю» или «N/A: причина».
Запуск: `python3 tools/ops/question_lint.py файл …` (вид — по имени `vopros-*`/`otvet-*` или `--kind vopros|otvet`); код 1 — есть находки (`--warn` — всегда 0).
Директор зовёт до отправки вопроса и при приёмке ответа. Шаблон — `.memory_bank/guides/sovetnik-vopros-shablon.md`. Без зависимостей (python 3.9+)."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEAD = re.compile(r"^\s{0,3}#{1,6}\s*(.*?)\s*#*\s*$")
MARK = re.compile(r"^\s*(?:[-*]\s*)?\**Поиск по банку\**\s*:\s*«[^»\n]{2,}»[^\n]*найдено\s+\d+[^\n]*\d{4}-\d{2}-\d{2}", re.I)
NA = re.compile(r"N/A\s*[:：]\s*(\S[^\n]{9,})", re.I)
ANS = re.compile(r"^\s*(?:[-*>]\s*)*\**\s*Сверено с банком\s*\**\s*:\s*\**\s*(.*)$", re.I | re.M)
EMPTY = {"-", "—", "–", "нет", "не знаю", "todo", "tbd", "?", "да", "ок"}


def section(text: str, key: str) -> str | None:
    """Текст раздела, чей заголовок содержит `key` (до следующего заголовка того же или более высокого уровня); нет раздела — None."""
    lines = text.replace("\r\n", "\n").split("\n")
    for i, l in enumerate(lines):
        m = HEAD.match(l)
        if m and key in m.group(1).lower():
            lvl = len(l.lstrip()) - len(l.lstrip().lstrip("#"))
            body = []
            for l2 in lines[i + 1:]:
                m2 = HEAD.match(l2)
                if m2 and (len(l2.lstrip()) - len(l2.lstrip().lstrip("#"))) <= lvl:
                    break
                body.append(l2)
            return "\n".join(body)
    return None


def lint_question(text: str) -> list[tuple[str, str]]:
    body = section(text, "что уже пробовали")
    if body is None or "поиск по банку" not in text.lower().split("что уже пробовали", 1)[1][:80].lower():
        return [("QUESTION-BANK", "нет раздела «Что уже пробовали (поиск по банку)» — сперва `python3 tools/ops/bank_search.py \"запрос\" --block`")]
    if any(MARK.match(l) for l in body.split("\n")):
        return []
    if NA.search(body):
        return []
    return [("QUESTION-BANK", "раздел «Что уже пробовали» без строки поиска («Поиск по банку: «запрос» · найдено N … · дата») и без «N/A: причина» — поиск не запускался")]


def lint_answer(text: str) -> list[tuple[str, str]]:
    ms = ANS.findall(text.replace("\r\n", "\n"))
    if not ms:
        return [("ANSWER-BANK", "нет строки «Сверено с банком: …» (да — что нашёл/чего не предлагаю; либо N/A: причина)")]
    val = max(ms, key=len).strip(" *")
    if val.lower() in EMPTY or len(val) < 10:
        return [("ANSWER-BANK", f"«Сверено с банком» пустое или формальное: «{val[:40]}» — назвать, что найдено в банке (ADR/урок/файл), или «N/A: причина»")]
    return []


def kind_of(path: Path, forced: str | None) -> str:
    if forced:
        return forced
    n = path.name.lower()
    return "otvet" if n.startswith("otvet") else "vopros"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="линт вопроса советнику / ответа (T-20261127-175/7)")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--kind", choices=("vopros", "otvet"), default=None)
    ap.add_argument("--warn", action="store_true", help="только печатать, код всегда 0")
    a = ap.parse_args(argv)
    bad = 0
    for f in a.files:
        p = Path(f)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            print(f"{f}: не прочитан ({e})")
            bad += 1
            continue
        k = kind_of(p, a.kind)
        finds = lint_question(text) if k == "vopros" else lint_answer(text)
        if finds:
            bad += 1
            for cat, msg in finds:
                print(f"{f}: {cat}: {msg}")
        else:
            print(f"{f}: ok ({'вопрос' if k == 'vopros' else 'ответ'})")
    return 0 if (a.warn or not bad) else 1


if __name__ == "__main__":
    sys.exit(main())

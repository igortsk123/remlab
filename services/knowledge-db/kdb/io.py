"""Чтение/запись артефактов: duplicate-key-aware parse, parse-back, JSONL.

Контракт спеки (output_and_state_contract): reject duplicate keys; parse-back
validate; JSONL = один UTF-8 объект на непустую строку.
"""
from __future__ import annotations

import json
from pathlib import Path


class DuplicateKeyError(ValueError):
    pass


def _no_dup_pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise DuplicateKeyError(f"duplicate key: {k!r}")
        d[k] = v
    return d


def parse_json_strict(raw: bytes) -> object:
    """Парс с запретом дублирующихся ключей (на всех уровнях)."""
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dup_pairs)


def load_json_strict(path: Path) -> object:
    return parse_json_strict(path.read_bytes())


def dump_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1) + "\n"


def write_json(path: Path, obj: object) -> None:
    """Запись + parse-back (строгий) + duplicate-key проверка."""
    text = dump_json(obj)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    parse_json_strict(path.read_bytes())


def write_jsonl(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    # parse-back: каждая непустая строка — один объект
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"{path}: пустая строка {i} в JSONL")
        parse_json_strict(line.encode("utf-8"))


def read_jsonl(path: Path) -> list:
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"{path}: пустая строка {i} в JSONL")
        rows.append(parse_json_strict(line.encode("utf-8")))
    return rows

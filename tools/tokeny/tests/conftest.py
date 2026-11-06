"""Тесты не читают журналы, выгрузки и таймеры этой машины: «На 1 % недели» за вчера и сегодня считает свою машину живым счётом
(`~/.claude/projects`, `~/.claude/usage-log.jsonl`), а выгрузки — из папки проектов `TOKENY_PROEKTY` (T-30)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tokeny


@pytest.fixture(autouse=True)
def bez_zhurnalov_mashiny(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr(tokeny, "KORNI", tmp_path / "proekty-pusto")
    monkeypatch.setenv("TOKENY_TAYMER", "-")  # таймер выгрузки этой машины (systemd) в тесты не попадает

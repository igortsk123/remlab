"""Тесты пульса обходов директора `tools/ops/obhod_puls.py` — на подставном журнале и подставном времени (T-20261123-23/1, п.5).
Запуск: `python -m pytest tools/ops/tests/test_obhod_puls.py -q -p no:cacheprovider`. Зима: Лондон = UTC, поэтому «12:00 UTC» = «12:00 Лондон»."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import obhod_puls as op  # noqa: E402


def chk(log, now, **kw):
    return op.check(op.read_log(log), op.parse_iso(now), **kw)


def test_day_fresh_round_is_silent():
    assert chk("2026-11-23T11:58:00Z obhod plan=54 %\n", "2026-11-23T12:05:00") == []


def test_day_round_older_than_15_min():
    r = chk("2026-11-23T11:40:00Z obhod\n", "2026-11-23T12:00:00")
    assert len(r) == 1 and r[0].startswith("❗") and "20 мин" in r[0] and "днём" in r[0]


def test_day_boundary_exactly_15_is_ok_16_is_not():
    assert chk("2026-11-23T12:00:00Z obhod\n", "2026-11-23T12:15:00") == []
    assert len(chk("2026-11-23T12:00:00Z obhod\n", "2026-11-23T12:16:00")) == 1


def test_night_threshold_45():
    log = "2026-11-23T02:00:00Z obhod\n"
    assert chk(log, "2026-11-23T02:40:00") == []          # 40 мин ночью — норма
    r = chk(log, "2026-11-23T02:50:00")                      # 50 мин
    assert len(r) == 1 and "ночью" in r[0] and "45" in r[0]


def test_day_night_edges_in_london():
    log = "2026-11-23T06:30:00Z obhod\n2026-11-22T06:30:00Z utro\n"
    assert chk(log, "2026-11-23T06:59:00") == []             # 29 мин, ещё ночь (до 07:00)
    assert len(chk(log, "2026-11-23T07:05:00")) >= 1         # день: 35 мин > 15


def test_summer_time_uses_london_not_utc():
    # 20 июля 06:10 UTC = 07:10 BST: день, 15-минутная норма
    r = op.check(op.read_log("2026-07-20T05:50:00Z obhod\n"), op.parse_iso("2026-07-20T06:10:00"))
    if op.LONDON is op.timezone.utc:
        return  # нет tzdata — проверка неприменима
    assert r and "днём" in r[0]       # 20 мин днём (> 15) → ❗; при чтении времени как UTC (06:10 — ночь, порог 45) промолчало бы


def test_morning_summary_missing_after_0715():
    log = "2026-11-23T07:10:00Z obhod\n"
    r = chk(log, "2026-11-23T07:16:00")
    assert len(r) == 1 and "утренней сводки" in r[0]
    assert chk(log, "2026-11-23T07:10:00") == []             # до 07:15 рано
    assert chk(log + "2026-11-23T07:04:00Z utro\n", "2026-11-23T07:16:00") == []
    assert chk(log, "2026-11-23T11:30:00") != []             # после окна 11:00 ❗ про сводку уже не шлём (остаётся только про обход)
    assert not any("утренней" in x for x in chk(log, "2026-11-23T11:30:00"))


def test_yesterdays_summary_does_not_count():
    log = "2026-11-22T07:04:00Z utro\n2026-11-23T07:12:00Z obhod\n"
    assert any("утренней" in x for x in chk(log, "2026-11-23T07:20:00"))


def test_empty_log_and_garbage_lines():
    assert "пуст" in chk("", "2026-11-23T12:00:00")[0]
    assert "пуст" in chk("мусор\n# коммент\n", "2026-11-23T12:00:00")[0]
    assert chk("мусор\n2026-11-23T11:59:30Z obhod ok\n", "2026-11-23T12:00:00") == []


def test_cli_missing_log_silent_ok_and_dedupe(tmp_path, capsys):
    log = tmp_path / "o.log"
    assert op.main(["--log", str(log), "--now", "2026-11-23T12:00:00"]) == 1
    assert "журнала обходов нет" in capsys.readouterr().out
    log.write_text("2026-11-23T11:55:00Z obhod\n", encoding="utf-8")
    assert op.main(["--log", str(log), "--now", "2026-11-23T12:00:00", "-v"]) == 0
    assert "✓" in capsys.readouterr().out
    log.write_text("2026-11-23T11:00:00Z obhod\n", encoding="utf-8")
    st = tmp_path / "st"
    a = ["--log", str(log), "--now", "2026-11-23T12:00:00", "--state", str(st), "--dedupe-min", "30"]
    assert op.main(a) == 1 and "❗" in capsys.readouterr().out
    import os
    os.utime(st, (op.parse_iso("2026-11-23T11:59:00").timestamp(),) * 2)
    assert op.main(a) == 1 and capsys.readouterr().out == ""   # то же ❗ чаще раза в 30 мин не повторяется

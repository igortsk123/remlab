"""Тесты карточки прогона `tools/ops/run_manifest.py` (T-20261125-89/2) — только во временной папке pytest (tmp_path), настоящие прогоны не трогаем.

Проверяем: start/finish/show; атомарность (нет остатков tmp, при сбое записи прежняя карточка цела, tmp убран); повторный finish и повторный start не портят started_utc;
finish без start; битый JSON (копия .bad, не затирается), старая схема (поднимается до v1, чужие ключи целы), схема новее (отказ, файл не тронут);
`reclaimable`: ok + флаг ВКЛ → список с размерами; fail / running / флаг ВЫКЛ / битая / нет карточки → пусто; плохие подпапки (.., абсолютные) отбрасываются, симлинк наружу не раскрывается;
CLI; ничего не удаляется (все файлы прогона на месте после reclaimable).
Запуск: `python -m pytest tools/ops/tests/test_run_manifest.py -q -p no:cacheprovider`."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import run_manifest as rm  # noqa: E402


def files_of(p: Path) -> list:
    return sorted(str(x.relative_to(p)) for x in p.rglob("*"))


def mk_run(tmp_path: Path) -> Path:
    run = tmp_path / "run1"
    (run / "stage1").mkdir(parents=True)
    (run / "stage1" / "a.glb").write_bytes(b"x" * 1000)
    (run / "stage1" / "b.png").write_bytes(b"y" * 500)
    (run / "final").mkdir()
    (run / "final" / "m.glb").write_bytes(b"z" * 300)
    return run


def test_start_writes_card(tmp_path):
    run = tmp_path / "новый" / "прогон"
    d = rm.start(str(run), task="T-20261125-89/2", who="rab-6", inputs=["in/a.json"], intermediate=["stage1", "tmp/"])
    c = json.loads((run / "RUN.json").read_text(encoding="utf-8"))
    assert c == d
    assert c["schema"] == 1 and c["status"] == "running" and c["finished_utc"] is None and c["restarts"] == 0
    assert c["task"] == "T-20261125-89/2" and c["who"]["worker"] == "rab-6" and c["who"]["host"]
    assert c["inputs"] == ["in/a.json"] and c["intermediate"] == ["stage1", "tmp"]
    assert c["started_utc"].endswith("Z")
    assert files_of(run) == ["RUN.json"], "кроме карточки ничего не оставлено (tmp убран)"


def test_task_and_who_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("REMLAB_TASK", "T-1-2")
    monkeypatch.delenv("REMLAB_WORKER", raising=False)
    monkeypatch.setenv("REMLAB_ROLE", "рабочий")
    c = rm.start(str(tmp_path / "r"))
    assert c["task"] == "T-1-2" and c["who"]["worker"] == "рабочий"


def test_finish_keeps_start_and_repeat_is_safe(tmp_path):
    run = tmp_path / "r"
    s = rm.start(str(run), task="T-1", intermediate=["a"])
    f1 = rm.finish(str(run), "ok", intermediate=["b"], note="первый")
    assert f1["started_utc"] == s["started_utc"] and f1["task"] == "T-1" and f1["status"] == "ok" and f1["finished_utc"]
    assert f1["intermediate"] == ["a", "b"]
    f2 = rm.finish(str(run), "fail", intermediate=["a"])        # повтор: последний вердикт, start цел, список без дублей
    assert f2["started_utc"] == s["started_utc"] and f2["status"] == "fail" and f2["intermediate"] == ["a", "b"] and f2["note"] == "первый"
    assert json.loads((run / "RUN.json").read_text(encoding="utf-8")) == f2
    assert files_of(run) == ["RUN.json"]


def test_repeat_start_keeps_first_started(tmp_path):
    run = tmp_path / "r"
    s = rm.start(str(run), task="T-1", inputs=["x"])
    rm.finish(str(run), "fail")
    s2 = rm.start(str(run), inputs=["x", "y"])
    assert s2["started_utc"] == s["started_utc"] and s2["restarts"] == 1 and s2["status"] == "running" and s2["finished_utc"] is None
    assert s2["inputs"] == ["x", "y"] and s2["task"] == "T-1"


def test_finish_without_start(tmp_path):
    f = rm.finish(str(tmp_path / "r"), "ok")
    assert f["started_utc"] is None and f["status"] == "ok" and "finish" in f["note"]


def test_finish_bad_status(tmp_path):
    with pytest.raises(rm.ManifestError):
        rm.finish(str(tmp_path / "r"), "running")


def test_atomic_failure_keeps_old_card_and_removes_tmp(tmp_path, monkeypatch):
    run = tmp_path / "r"
    rm.start(str(run), task="T-1")
    before = (run / "RUN.json").read_text(encoding="utf-8")

    def boom(src, dst):
        raise OSError("replace упал")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        rm.finish(str(run), "ok")
    monkeypatch.undo()
    assert (run / "RUN.json").read_text(encoding="utf-8") == before, "прежняя карточка цела"
    assert files_of(run) == ["RUN.json"], "tmp после сбоя убран"


def test_corrupt_card_is_saved_aside(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    (run / "RUN.json").write_text('{"schema": 1, "status": "ru', encoding="utf-8")
    assert rm.read_card(str(run))["state"] == "битая"
    rm.start(str(run), task="T-2")
    assert rm.read_card(str(run))["state"] == "running"
    assert (run / "RUN.json.bad").read_text(encoding="utf-8").startswith('{"schema": 1, "status": "ru')
    (run / "RUN.json").write_text("[1, 2]", encoding="utf-8")   # JSON не словарь — тоже битая; прежняя .bad не затирается
    rm.finish(str(run), "ok")
    assert (run / "RUN.json.bad.1").read_text(encoding="utf-8") == "[1, 2]"
    assert (run / "RUN.json.bad").read_text(encoding="utf-8").startswith('{"schema": 1, "status": "ru')


def test_old_schema_is_upgraded_keeping_extras(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    (run / "RUN.json").write_text(json.dumps({"task": "T-old", "started_utc": "2026-11-01T00:00:00Z", "inputs": "in.json", "extra": 7}), encoding="utf-8")
    assert rm.read_card(str(run))["state"] == "старая v0"
    d = rm.finish(str(run), "ok", intermediate=["s"])
    assert d["schema"] == 1 and d["started_utc"] == "2026-11-01T00:00:00Z" and d["task"] == "T-old" and d["extra"] == 7
    assert d["inputs"] == ["in.json"] and d["intermediate"] == ["s"] and d["status"] == "ok"


def test_newer_schema_refused_and_untouched(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    raw = json.dumps({"schema": 99, "status": "ok", "intermediate": ["a"]})
    (run / "RUN.json").write_text(raw, encoding="utf-8")
    assert rm.read_card(str(run))["state"] == "новее схемы"
    with pytest.raises(rm.ManifestError):
        rm.finish(str(run), "fail")
    assert (run / "RUN.json").read_text(encoding="utf-8") == raw
    assert rm.reclaimable(str(run), enabled=True) == []


@pytest.mark.parametrize("bad", ["../x", "/etc", "a/../../b", "", ".", "RUN.json", "RUN.json.bad"])
def test_bad_intermediate_rejected(tmp_path, bad):
    with pytest.raises(rm.ManifestError):
        rm.start(str(tmp_path / "r"), intermediate=[bad])


def test_reclaimable_ok_and_flag(tmp_path):
    run = mk_run(tmp_path)
    rm.start(str(run), task="T-1", intermediate=["stage1", "нет-такой"])
    assert rm.reclaimable(str(run), enabled=True) == [], "статус running — не отдаём"
    rm.finish(str(run), "ok")
    before = files_of(run)
    assert rm.reclaimable(str(run), enabled=False) == [], "флаг выкл — пусто"
    rec = rm.reclaimable(str(run), enabled=True)
    assert [x["path"] for x in rec] == ["stage1"], "несуществующая подпапка пропущена"
    assert rec[0]["bytes"] == 1500 and rec[0]["files"] == 2 and rec[0]["free_bytes"] == 1500 and rec[0]["link"] is False
    assert files_of(run) == before, "ничего не удалено"


def test_reclaimable_fail_and_missing_card(tmp_path):
    run = mk_run(tmp_path)
    assert rm.reclaimable(str(run), enabled=True) == [], "нет карточки"
    rm.start(str(run), intermediate=["stage1"])
    rm.finish(str(run), "fail")
    assert rm.reclaimable(str(run), enabled=True) == [], "fail — всё держим для разбора"


def test_reclaimable_flag_from_rules_default_off(tmp_path):
    run = mk_run(tmp_path)
    rm.start(str(run), intermediate=["stage1"])
    rm.finish(str(run), "ok")
    off, on = tmp_path / "off.json", tmp_path / "on.json"
    off.write_text(json.dumps({"run_manifest": {"drop_intermediate_on_ok": False}}), encoding="utf-8")
    on.write_text(json.dumps({"run_manifest": {"drop_intermediate_on_ok": True}}), encoding="utf-8")
    assert rm.load_flag(off) is False and rm.load_flag(on) is True
    assert rm.load_flag(tmp_path / "нет.json") is False
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    assert rm.load_flag(tmp_path / "bad.json") is False


def test_repo_rules_default_off():
    assert rm.load_flag() is False, "в dev-disk.json правило по умолчанию ВЫКЛ"


def test_reclaimable_symlink_not_followed_and_hardlink(tmp_path):
    run = mk_run(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.glb").write_bytes(b"q" * 9999)
    os.symlink(outside, run / "link-out")
    os.link(run / "final" / "m.glb", run / "stage1" / "hard.glb")     # жёсткая ссылка на файл вне списка: места не освободит
    rm.start(str(run), intermediate=["link-out", "stage1"])
    rm.finish(str(run), "ok")
    rec = {x["path"]: x for x in rm.reclaimable(str(run), enabled=True)}
    assert rec["link-out"]["link"] is True and rec["link-out"]["bytes"] == 0, "симлинк не раскрываем"
    assert rec["stage1"]["bytes"] == 1800 and rec["stage1"]["free_bytes"] == 1500
    assert (outside / "big.glb").exists()


def test_reclaimable_escape_through_symlink_parent_skipped(tmp_path):
    run = mk_run(tmp_path)
    outside = tmp_path / "outside"
    (outside / "inner").mkdir(parents=True)
    (outside / "inner" / "f").write_bytes(b"1")
    os.symlink(outside, run / "sl")
    rm.start(str(run), intermediate=["sl/inner"])      # путь выходит наружу через симлинк-родителя
    rm.finish(str(run), "ok")
    assert rm.reclaimable(str(run), enabled=True) == []


def test_cli_roundtrip(tmp_path, capsys):
    run = mk_run(tmp_path)
    assert rm.main(["start", str(run), "--task", "T-9", "--input", "in.json", "--intermediate", "stage1"]) == 0
    assert rm.main(["finish", str(run), "--status", "ok"]) == 0
    capsys.readouterr()
    assert rm.main(["show", str(run), "--assume-enabled"]) == 0
    out = capsys.readouterr().out
    assert "T-9" in out and "stage1" in out and "ВЫКЛ" not in out
    assert rm.main(["show", str(run), "--json"]) == 0
    j = json.loads(capsys.readouterr().out)
    assert j["state"] == "ok" and j["reclaimable"] == [], "флаг в правилах выкл — пусто"
    assert rm.main(["show", str(run), "--json", "--assume-enabled"]) == 0
    assert json.loads(capsys.readouterr().out)["reclaimable"][0]["path"] == "stage1"
    assert rm.main(["start", str(run), "--intermediate", "../x"]) == 2


def test_cli_newer_schema_rc2(tmp_path, capsys):
    run = tmp_path / "r"
    run.mkdir()
    (run / "RUN.json").write_text(json.dumps({"schema": 5}), encoding="utf-8")
    assert rm.main(["finish", str(run), "--status", "ok"]) == 2

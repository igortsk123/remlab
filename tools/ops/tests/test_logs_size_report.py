"""Тесты замера `tools/ops/logs_size_report.py` (T-20261125-89/2) — на заглушках во временной папке pytest; только чтение (проверяем, что дерево не изменилось).

Стенд: src с папками — прогон с карточкой и glb/png/npz/log (в т.ч. жёсткая ссылка, считается один раз), рабочая копия git (папка с `.git`), папка со старой записью, битая карточка,
симлинк «на HDD» (не раскрывается), файл в корне; dst — «HDD-архив».
Запуск: `python -m pytest tools/ops/tests/test_logs_size_report.py -q -p no:cacheprovider`."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import logs_size_report as lsr  # noqa: E402
import run_manifest as rm  # noqa: E402

OLD_TS = time.mktime(time.strptime("2020-01-01", "%Y-%m-%d"))


def snapshot(p: Path) -> list:
    return sorted((str(x.relative_to(p)), x.lstat().st_size, x.lstat().st_mtime) for x in p.rglob("*"))


def build(tmp_path: Path):
    src, dst = tmp_path / "logs", tmp_path / "hdd"
    run = src / "T-20261125-89-2"
    (run / "stage1").mkdir(parents=True)
    (run / "stage1" / "a.glb").write_bytes(b"g" * 4000)
    (run / "stage1" / "b.PNG").write_bytes(b"p" * 2000)
    (run / "cache.npz").write_bytes(b"n" * 1000)
    (run / "run.log").write_bytes(b"l" * 100)
    (run / "weird.xyz").write_bytes(b"w" * 50)
    os.link(run / "stage1" / "a.glb", run / "stage1" / "a-copy.glb")      # та же жёсткая ссылка — один раз
    rm.start(str(run), task="T-20261125-89/2")
    rm.finish(str(run), "ok")
    wt = src / "t183-2"
    (wt / "code").mkdir(parents=True)
    (wt / "code" / ".git").write_text("gitdir: /x", encoding="utf-8")
    (wt / "code" / "app.py").write_bytes(b"c" * 700)
    (wt / "code" / "out.glb").write_bytes(b"o" * 300)
    (wt / "frames.png").write_bytes(b"f" * 200)
    old = src / "bedroom-3d-1113"
    old.mkdir()
    (old / "x.jsonl").write_bytes(b"j" * 10)
    os.utime(old / "x.jsonl", (OLD_TS, OLD_TS))
    os.utime(old, (OLD_TS, OLD_TS))
    bad = src / "broken-card"
    bad.mkdir()
    (bad / "RUN.json").write_text("{не json", encoding="utf-8")
    (src / "moved-to-hdd").symlink_to(tmp_path / "hdd")
    (src / "loose.log").write_bytes(b"L" * 33)
    (dst / "T-old").mkdir(parents=True)
    (dst / "T-old" / "m.glb").write_bytes(b"h" * 5000)
    return src, dst


def test_task_of():
    assert lsr.task_of("T-20261119-100") == "T-20261119-100"
    assert lsr.task_of("T-20261119-115-3") == "T-20261119-115-3"
    assert lsr.task_of("t183-2") == "T-?-183/2"
    assert lsr.task_of("out-t99-1126") == "T-?-99"
    assert lsr.task_of("bedroom-3d-1113") == "—"
    assert lsr.task_of("art_chk-1118.py") == "—"


def test_categories():
    assert lsr.cat_of("a.GLB") == "glb" and lsr.cat_of("b.png") == "кадры" and lsr.cat_of("c.npz") == "кэш"
    assert lsr.cat_of("d.log") == "логи" and lsr.cat_of("e") == "прочее" and lsr.cat_of("f.xyz") == "прочее"


def test_measure(tmp_path):
    src, dst = build(tmp_path)
    before = snapshot(tmp_path)
    res = lsr.measure(str(src), now=time.mktime(time.strptime("2020-01-11", "%Y-%m-%d")) + 0)   # «сейчас» = 11.01.2020: возраст старой папки 10 суток
    rows = {r["name"]: r for r in res["rows"]}
    assert set(rows) == {"T-20261125-89-2", "t183-2", "bedroom-3d-1113", "broken-card"}
    r = rows["T-20261125-89-2"]
    assert r["task"] == "T-20261125-89-2" and r["card"] == "ok" and r["wt_roots"] == 0
    assert r["by_cat"]["glb"] == 4000 and r["files_by_cat"]["glb"] == 1, "жёсткая ссылка — один файл"
    assert r["by_cat"]["кадры"] == 2000 and r["by_cat"]["кэш"] == 1000 and r["by_cat"]["прочее"] == 50
    assert r["by_cat"]["логи"] > 100   # run.log + RUN.json
    w = rows["t183-2"]
    assert w["wt_roots"] == 1 and w["wt_bytes"] == 1010 and w["by_cat"]["кадры"] == 200 and w["task"] == "T-?-183/2" and w["card"] == "нет"
    assert rows["bedroom-3d-1113"]["age_d"] == 10.0 and rows["bedroom-3d-1113"]["bytes"] == 10
    assert rows["broken-card"]["card"] == "битая"
    assert res["loose_bytes"] == 33 and res["loose_files"] == 1 and res["links"] == 1, "симлинк не раскрыт и не посчитан"
    assert snapshot(tmp_path) == before, "замер ничего не меняет"


class FakeEntry:
    """Запись каталога, чья папка исчезла между scandir и stat (автоуборка убрала её во время замера)."""
    name = "ушла"
    path = "/нет/такой"

    def is_symlink(self):
        return False

    def is_dir(self, follow_symlinks=True):
        return True

    def stat(self, follow_symlinks=True):
        raise FileNotFoundError(self.path)


def test_measure_survives_vanished_dir(tmp_path, monkeypatch):
    src, dst = build(tmp_path)
    real = os.scandir

    class Ctx:
        def __init__(self, entries):
            self.entries = entries

        def __enter__(self):
            return iter(self.entries)

        def __exit__(self, *a):
            return False

    def fake(path):
        if str(path) == str(src):
            with real(path) as it:
                return Ctx(list(it) + [FakeEntry()])
        return real(path)

    monkeypatch.setattr(os, "scandir", fake)
    res = lsr.measure(str(src))
    assert "ушла" not in {r["name"] for r in res["rows"]} and len(res["rows"]) == 4


def test_total_and_missing_hdd(tmp_path):
    src, dst = build(tmp_path)
    t = lsr.total_of(str(dst))
    assert t["present"] and t["bytes"] == 5000 and t["dirs"] == 1 and t["by_cat"]["glb"] == 5000
    assert lsr.total_of(str(tmp_path / "нет"))["present"] is False


def test_render_and_main(tmp_path, capsys):
    src, dst = build(tmp_path)
    before = snapshot(tmp_path)
    assert lsr.main(["--src", str(src), "--dst", str(dst), "--top", "2"]) == 0
    out = capsys.readouterr().out
    assert "T-20261125-89-2" in out and "HDD-архив: " in out and "Без карточки: 3 папок" in out and "с карточкой: 1 папок" in out
    assert out.count("\n| ") == 3, "шапка + 2 строки топа (разделитель «|--:|» не считается)"
    assert lsr.main(["--src", str(src), "--dst", "", "--json"]) == 0
    j = json.loads(capsys.readouterr().out)
    assert j["hdd"] is None and len(j["result"]["rows"]) == 4
    assert lsr.main(["--src", str(tmp_path / "нет-папки")]) == 2
    assert snapshot(tmp_path) == before

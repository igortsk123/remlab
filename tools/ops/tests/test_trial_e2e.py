"""Тесты замерщика пробы `tools/ops/trial_e2e.py` на заглушке по контракту (`tools/ops/trial_stub.py`); прод не трогаем.

Запуск: `python -m pytest tools/ops/tests/test_trial_e2e.py -q`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import trial_e2e as te  # noqa: E402
import trial_stub as ts  # noqa: E402

FAST = [("raster", 0.08), ("labels", 0.2), ("walls", 0.1), ("repair", 0.05), ("export", 0.05)]  # 0,48 с на задание
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\n%%EOF\n"


@pytest.fixture
def stub():
    made = []

    def start(**kw):
        kw.setdefault("schedule", FAST)
        st = ts.StubState(**kw)
        srv = ts.serve(st)
        made.append(srv)
        return st, f"http://127.0.0.1:{srv.server_address[1]}"

    yield start
    for s in made:
        s.shutdown()


@pytest.fixture
def plans(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    (d / "D.png").write_bytes(PNG)
    (d / "E.pdf").write_bytes(PDF)
    (d / "D.txt").write_text("Living room 4.20m x 3.60m\n", encoding="utf-8")
    return d


def args(base, plans, out, *extra):
    return ["--base", base, "--out", str(out), "--input", f"D={plans / 'D.png'}", "--listing", f"D={plans / 'D.txt'}",
            "--poll", "0.05", "--gap", "0.1", "--retry-cap", "1", *extra]


def load(out):
    run = next(out.glob("run-*"))
    data = json.loads((run / "runs.json").read_text(encoding="utf-8"))
    journal = [json.loads(x) for x in (run / "journal.jsonl").read_text(encoding="utf-8").splitlines()]
    return run, data, journal


# ── чистые функции ────────────────────────────────────────────────────────────────────────────────────
def view(stages, created="2026-11-09T10:00:00.000Z", finished=None, status="done"):
    return {"createdAt": created, "finishedAt": finished, "status": status,
            "stages": [{"stage": s, "at": f"2026-11-09T10:00:{t:06.3f}Z"} for s, t in stages]}


def test_phase_durations_maps_stages_to_phases():
    v = view([("raster", 5), ("labels", 7), ("walls", 30), ("repair", 40), ("export", 44), ("done", 46)],
             finished="2026-11-09T10:00:46.000Z")
    ph, total, retried = te.phase_durations(v)
    assert ph == {"queue": 5.0, "recognition": 25.0, "3d": 16.0}
    assert total == 46.0 and retried is False


def test_phase_durations_failed_and_retry_and_unknown_stage():
    # откат: после walls снова raster (вторая попытка); неизвестный шаг — в «прочее»; конец — finishedAt без done
    v = view([("raster", 2), ("walls", 10), ("raster", 20), ("mystery", 25)], finished="2026-11-09T10:00:30.000Z",
             status="failed")
    ph, total, retried = te.phase_durations(v)
    assert ph == {"queue": 2.0, "recognition": 13.0, "3d": 10.0, "other": 5.0}
    assert total == 30.0 and retried is True


def test_phase_durations_unfinished_has_no_total():
    ph, total, _ = te.phase_durations(view([("raster", 3)], status="running"))
    assert ph == {"queue": 3.0} and total is None


def test_percentiles():
    assert te.pct([10, 20, 30, 40], 50) == 25.0
    assert te.pct([10, 20, 30, 40], 95) == 38.5
    assert te.pct([7.0], 95) == 7.0
    assert te.pct([], 50) is None


def test_input_hash_matches_prod_formula():
    import hashlib
    file_sha = hashlib.sha256(PNG).hexdigest()
    assert te.input_hash(PNG, " txt ") == hashlib.sha256(f"{file_sha}\ntxt".encode()).hexdigest()


def test_fresh_input_changes_hash_keeps_signature(plans):
    it = te.Item("D", plans / "D.png")
    a, b = te.file_bytes(it, True), te.file_bytes(it, True)
    assert a.startswith(PNG) and b.startswith(PNG) and a != b
    assert te.file_bytes(it, False) == PNG


# ── сквозные на заглушке ──────────────────────────────────────────────────────────────────────────────
def test_series_end_to_end(stub, plans, tmp_path):
    st, base = stub()
    out = tmp_path / "out"
    rc = te.main(args(base, plans, out, "--input", f"E={plans / 'E.pdf'}", "-n", "2"))
    assert rc == 0
    run, data, journal = load(out)
    runs = data["runs"]
    assert [r["plan"] for r in runs] == ["D", "E", "D", "E"]
    assert all(r["outcome"] == "done" and r["result_ok"] for r in runs)
    assert [r["temp"] for r in runs] == ["cold", "warm", "warm", "warm"]
    assert [r["input"] for r in runs] == ["fresh", "fresh", "repeat", "repeat"]
    for r in runs:
        assert set(r["phases"]) == {"queue", "recognition", "3d"}
        assert r["server_sec"] == pytest.approx(sum(d for _, d in FAST), abs=0.1)
        assert r["client_sec"] >= r["server_sec"] - 0.05
        assert r["polls"] <= 30  # 0,5 с при опросе 0,05 с ≈ 10–15 запросов
    # страница отправляет то же: текст объявления и согласие дошли, тип файла распознан
    assert st.uploads[0]["listing"] == "Living room 4.20m x 3.60m" and st.uploads[0]["mime"] == "image/png"
    assert st.uploads[1]["mime"] == "application/pdf" and st.uploads[1]["listing"] == ""
    evs = [e["ev"] for e in journal]
    assert evs.count("uploaded") == 4 and evs.count("result") == 4
    stages_seen = {e["stage"] for e in journal if e["ev"] == "view"}
    assert {"raster", "labels", "walls", "done"} <= stages_seen
    md = (run / "table.md").read_text(encoding="utf-8")
    assert "| все | 4 |" in md and "тёплые" in md and "план E" in md and "распознавание" in md
    assert (run / "table.tsv").read_text(encoding="utf-8").count("\n") == 5


def test_gap_between_uploads_respected(stub, plans, tmp_path):
    _st, base = stub(schedule=[("raster", 0.02), ("export", 0.02)])
    out = tmp_path / "out"
    te.main(args(base, plans, out, "-n", "3", "--gap", "0.4"))
    _run, _d, journal = load(out)
    t = [e["t"] for e in journal if e["ev"] == "uploaded"]
    assert len(t) == 3 and all(b - a >= 0.39 for a, b in zip(t, t[1:]))


def test_retry_after_honoured_then_success(stub, plans, tmp_path):
    st, base = stub(refuse=[429], retry_after=1)
    out = tmp_path / "out"
    assert te.main(args(base, plans, out, "-n", "1")) == 0
    _run, data, journal = load(out)
    assert data["runs"][0]["refusals"] == 1 and data["runs"][0]["outcome"] == "done"
    assert st.hits["upload"] == 2
    refused = [e for e in journal if e["ev"] == "refused"]
    assert refused[0]["http"] == 429 and refused[0]["wait"] == 1.0


def test_persistent_refusal_stops_series(stub, plans, tmp_path):
    st, base = stub(refuse=[503] * 10, retry_after=1)
    out = tmp_path / "out"
    assert te.main(args(base, plans, out, "-n", "3")) == 1
    _run, data, _j = load(out)
    assert data["runs"][0]["outcome"] == "refused:503:busy"
    assert len(data["runs"]) == 1 and st.hits["upload"] == 1 + te.MAX_REFUSALS
    assert "отказывает" in data["meta"]["abort"]


def test_no_worker_stops_series_without_piling_queue(stub, plans, tmp_path):
    st, base = stub(worker_alive=False)
    out = tmp_path / "out"
    assert te.main(args(base, plans, out, "-n", "3", "--no-worker-sec", "0.3")) == 1
    _run, data, _j = load(out)
    assert [r["outcome"] for r in data["runs"]] == ["no_worker"]
    assert st.hits["upload"] == 1 and "воркер" in data["meta"]["abort"]


def test_failed_job_reported(stub, plans, tmp_path):
    _st, base = stub(fail_every=1)
    out = tmp_path / "out"
    assert te.main(args(base, plans, out, "-n", "1")) == 1
    run, data, _j = load(out)
    r = data["runs"][0]
    assert r["outcome"] == "failed:no_plan" and r["result_ok"] is None and "recognition" in r["phases"]
    assert "не готово: D#1 failed:no_plan" in (run / "table.md").read_text(encoding="utf-8")


def test_batch_measures_queue(stub, plans, tmp_path):
    _st, base = stub()
    out = tmp_path / "out"
    assert te.main(args(base, plans, out, "-n", "3", "--batch", "3")) == 0
    _run, data, journal = load(out)
    q = [r["phases"]["queue"] for r in data["runs"]]
    assert q[0] < 0.1 and q[1] > 0.4 and q[2] > q[1]  # каждое следующее ждёт предыдущее (concurrency 1)
    ahead = [e["queueAhead"] for e in journal if e["ev"] == "view" and e["run"] == 3 and e["status"] == "queued"]
    assert ahead[0] == 1  # впереди только ещё не взятое №2 (идущее №1 — не «в очереди»)


def test_remote_base_requires_live_and_dry_run_uploads_nothing(plans, tmp_path, capsys):
    out = tmp_path / "out"
    assert te.main(["--input", str(plans / "D.png"), "--base", "https://example.invalid", "--out", str(out)]) == 2
    assert te.main(["--input", str(plans / "D.png"), "--out", str(out), "--dry-run", "-n", "11"]) == 0
    assert not out.exists()
    assert "daily_cap" in capsys.readouterr().out


def test_bad_input_rejected_before_upload(tmp_path):
    bad = tmp_path / "x.gif"
    bad.write_bytes(b"GIF89a....")
    with pytest.raises(ValueError):
        te.main(["--input", str(bad), "--dry-run"])


def test_report_only_rebuilds_table(stub, plans, tmp_path):
    _st, base = stub()
    out = tmp_path / "out"
    te.main(args(base, plans, out, "-n", "1"))
    run = next(out.glob("run-*"))
    (run / "table.md").unlink()
    assert te.main(["--report-only", str(run)]) == 0
    assert "## Гейты" in (run / "table.md").read_text(encoding="utf-8")

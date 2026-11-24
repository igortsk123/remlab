"""Тесты уборки рабочих копий `tools/ops/worktree_prune.py` (T-20261124-52/1) — только во временном репозитории, настоящий не трогаем.

Репозиторий в tmp: main с одним старым коммитом и шесть копий — чистая старая на ветке (снимается), грязная (остаётся), молодая (остаётся),
detached с невлитым коммитом (остаётся), detached влитая (снимается), запертая / симлинк на «HDD» / с процессом внутри (остаются).
Запуск: `python -m pytest tools/ops/tests/test_worktree_prune.py -q -p no:cacheprovider`."""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
import worktree_prune as wp  # noqa: E402

OLD = "2020-01-01T00:00:00+00:00"
OLD_TS = time.mktime(time.strptime("2020-01-01", "%Y-%m-%d"))


@pytest.fixture(autouse=True)
def clean_git_env(monkeypatch):
    for k in [k for k in os.environ if k.startswith("GIT_")]:  # хук pre-push ставит GIT_DIR/GIT_INDEX_FILE — не должны утекать в tmp-репо
        monkeypatch.delenv(k)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.invalid")


def g(cwd, *a, date=None):
    env = dict(os.environ)
    if date:
        env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
    r = subprocess.run(["git", *a], cwd=str(cwd), capture_output=True, text=True, env=env)
    assert r.returncode == 0, (a, r.stderr)
    return r.stdout.strip()


def commit(cwd, name, date):
    Path(cwd, name).write_text(name, encoding="utf-8")
    g(cwd, "add", name)
    g(cwd, "commit", "-q", "-m", name, date=date)


def make_repo(tmp_path):
    repo = tmp_path / "main-repo"
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main")
    commit(repo, "a.txt", OLD)
    g(repo, "branch", "merged-old")                      # влитая старая ветка — удаляется
    wt = tmp_path / "wt"
    wt.mkdir()

    # 1. чистая старая на ветке, свой невлитый коммит (ветка остаётся)
    p = wt / "clean-branch"
    g(repo, "worktree", "add", "-q", "-b", "wt-clean", str(p), "main")
    commit(p, "own.txt", OLD)
    # 2. грязная: неотслеживаемый файл
    p = wt / "dirty"
    g(repo, "worktree", "add", "-q", "-b", "wt-dirty", str(p), "main")
    (p / "scratch.txt").write_text("не сохранено", encoding="utf-8")
    # 3. молодая: свежий коммит
    p = wt / "young"
    g(repo, "worktree", "add", "-q", "-b", "wt-young", str(p), "main")
    commit(p, "young.txt", time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()))
    # 4. detached с невлитым коммитом
    p = wt / "detached-unmerged"
    g(repo, "worktree", "add", "-q", "--detach", str(p), "main")
    commit(p, "lonely.txt", OLD)
    # 5. detached влитая (HEAD = main)
    g(repo, "worktree", "add", "-q", "--detach", str(wt / "detached-merged"), "main")
    # 6. запертая
    g(repo, "worktree", "add", "-q", "-b", "wt-locked", str(wt / "locked"), "main")
    g(repo, "worktree", "lock", str(wt / "locked"))
    # 7. симлинк на «HDD» (как после logs_archive.py): настоящая папка в другом месте, на месте ссылка
    g(repo, "worktree", "add", "-q", "-b", "wt-hdd", str(wt / "hdd-real"), "main")
    (tmp_path / "hdd").mkdir()
    os.rename(wt / "hdd-real", tmp_path / "hdd" / "moved")
    os.symlink(tmp_path / "hdd" / "moved", wt / "hdd-real")
    # 8. процесс внутри
    g(repo, "worktree", "add", "-q", "-b", "wt-busy", str(wt / "busy"), "main")
    for d in wt.iterdir():
        if not d.is_symlink():
            os.utime(d, (OLD_TS, OLD_TS))
    return repo, wt


def run(repo, *extra):
    buf = io.StringIO()
    rc = wp.prune(str(repo), "--apply" in extra, 3.0, "main", False, out=buf)
    return rc, buf.getvalue()


def test_dry_run_changes_nothing(tmp_path):
    repo, wt = make_repo(tmp_path)
    before = sorted(p.name for p in wt.iterdir())
    rc, out = run(repo)
    assert rc == 0
    assert sorted(p.name for p in wt.iterdir()) == before
    assert "снял бы 3" in out and "(сухо)" in out and "clean-branch" in out and "detached-merged" in out and "wt/busy" in out  # busy без процесса — обычная старая копия
    assert g(repo, "branch", "--list", "merged-old")


def test_apply_removes_only_safe_copies(tmp_path):
    repo, wt = make_repo(tmp_path)
    busy = subprocess.Popen([sys.executable, "-c", "input()"], cwd=str(wt / "busy"), stdin=subprocess.PIPE)
    try:
        rc, out = run(repo, "--apply")
    finally:
        busy.stdin.close()
        busy.wait(timeout=20)
    assert rc == 0, out
    left = sorted(p.name for p in wt.iterdir())
    assert left == sorted(["busy", "dirty", "detached-unmerged", "hdd-real", "locked", "young"]), (left, out)
    assert "ИТОГ: снято 2," in out and "отказов 0" in out
    # причины «оставляю» названы
    for why in ("есть несохранённое", "моложе 3 сут", "detached не влита", "заперта", "ссылка на HDD", "процесс внутри"):
        assert why in out, (why, out)
    # ветка снятой копии остаётся (потерь нет), влитая старая ветка удалена (-d), невлитые целы
    assert g(repo, "branch", "--list", "wt-clean")
    assert not g(repo, "branch", "--list", "merged-old")
    assert g(repo, "branch", "--list", "wt-dirty")
    # симлинк на HDD не тронут
    assert (wt / "hdd-real").is_symlink() and (tmp_path / "hdd" / "moved" / "a.txt").is_file()


def test_threshold_from_config_and_cli(tmp_path, capsys):
    repo, wt = make_repo(tmp_path)
    cfg = tmp_path / "dev-disk.json"
    cfg.write_text(json.dumps({"worktree_prune": {"days": 100000, "base": "main"}}), encoding="utf-8")
    assert wp.load_rules(cfg) == {"days": 100000, "base": "main"}
    assert wp.load_rules(tmp_path / "нет.json") == wp.DEFAULTS
    assert wp.main(["--repo", str(repo), "--config", str(cfg), "--no-fetch"]) == 0
    assert "снял бы 0" in capsys.readouterr().out                  # порог огромный — всё «моложе»
    assert wp.main(["--repo", str(repo), "--config", str(cfg), "--days", "3", "--no-fetch"]) == 0
    assert "снял бы 3" in capsys.readouterr().out                  # --days перекрывает конфиг
    assert wp.main(["--repo", str(tmp_path / "нет-репо"), "--no-fetch"]) == 2


def test_real_rules_file_has_worktree_prune_key():
    r = wp.load_rules(wp.RULES_PATH)
    assert r["days"] == 3 and r["base"] == "origin/main"

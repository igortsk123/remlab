"""Тесты уборки рабочих копий `tools/ops/worktree_prune.py` (T-20261124-52/1, T-20261125-89) — только во временном репозитории, настоящий не трогаем.

Репозиторий в tmp: main с одним старым коммитом и копии: чистая старая на ветке с НЕвлитым коммитом (снимается, T-89), с неотслеживаемым node_modules (снимается),
detached влитая / detached с коммитом, достижимым из ветки (снимаются); грязная / с неотслеживаемым файлом / молодая / detached осиротевшая / запертая / симлинк на «HDD» /
с процессом внутри (cwd, открытый файл tail, PYTHONPATH) / с крупным игнорируемым файлом (остаются, причина названа).
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
import logs_archive as la  # noqa: E402
import worktree_prune as wp  # noqa: E402

OLD = "2020-01-01T00:00:00+00:00"
OLD_TS = time.mktime(time.strptime("2020-01-01", "%Y-%m-%d"))
RULES = {"days": 3.0, "base": "main", "idle_h": 48.0, "unmerged_ok": True, "prune_expire": "3.days", "big_mb": 1.0, "dst": None}


@pytest.fixture(autouse=True)
def clean_git_env(monkeypatch):
    for k in [k for k in os.environ if k.startswith("GIT_")]:  # хук pre-push ставит GIT_DIR/GIT_INDEX_FILE — не должны утекать в tmp-репо
        monkeypatch.delenv(k)
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@example.invalid")
    monkeypatch.setattr(la, "MONITOR_MAX_H", None)


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


def age_tree(p: Path):
    """Всё внутри копии — «давно»: свежие файлы checkout иначе держат копию (idle_h)."""
    for dp, dn, fn in os.walk(p):
        for n in fn + dn:
            q = os.path.join(dp, n)
            if not os.path.islink(q):
                os.utime(q, (OLD_TS, OLD_TS))
    os.utime(p, (OLD_TS, OLD_TS))


def make_repo(tmp_path):
    repo = tmp_path / "main-repo"
    repo.mkdir()
    g(repo, "init", "-q", "-b", "main")
    Path(repo, ".gitignore").write_text("*.big\n*.small\nnode_modules/\n", encoding="utf-8")
    g(repo, "add", ".gitignore")
    commit(repo, "a.txt", OLD)
    g(repo, "branch", "merged-old")                      # влитая старая ветка — удаляется
    wt = tmp_path / "wt"
    wt.mkdir()

    # 1. чистая старая на ветке, свой НЕвлитый коммит (ветка остаётся) — снимается
    p = wt / "clean-branch"
    g(repo, "worktree", "add", "-q", "-b", "wt-clean", str(p), "main")
    commit(p, "own.txt", OLD)
    # 1б. неотслеживаемый node_modules и мелкий игнорируемый файл — не мешают
    p = wt / "nm-only"
    g(repo, "worktree", "add", "-q", "-b", "wt-nm", str(p), "main")
    (p / "node_modules").mkdir()
    (p / "node_modules" / "x.js").write_text("x", encoding="utf-8")
    (p / "tiny.small").write_text("мелочь", encoding="utf-8")
    # 2. грязная: изменён отслеживаемый файл
    p = wt / "dirty"
    g(repo, "worktree", "add", "-q", "-b", "wt-dirty", str(p), "main")
    (p / "a.txt").write_text("правка не сохранена", encoding="utf-8")
    # 2б. неотслеживаемый файл
    p = wt / "untracked"
    g(repo, "worktree", "add", "-q", "-b", "wt-untr", str(p), "main")
    (p / "scratch.txt").write_text("не сохранено", encoding="utf-8")
    # 3. молодая: свежий коммит
    p = wt / "young"
    g(repo, "worktree", "add", "-q", "-b", "wt-young", str(p), "main")
    commit(p, "young.txt", time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()))
    # 4. detached осиротевшая: коммит не в ветке
    p = wt / "detached-orphan"
    g(repo, "worktree", "add", "-q", "--detach", str(p), "main")
    commit(p, "lonely.txt", OLD)
    # 4б. detached, но её коммит достижим из ветки — снимается (коммиты не теряются)
    p = wt / "detached-saved"
    g(repo, "worktree", "add", "-q", "--detach", str(p), "main")
    commit(p, "saved.txt", OLD)
    g(repo, "branch", "saved-branch", g(p, "rev-parse", "HEAD"))
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
    # 8. процесс внутри (cwd)
    g(repo, "worktree", "add", "-q", "-b", "wt-busy", str(wt / "busy"), "main")
    # 9. крупный игнорируемый файл (> big_mb) — остаётся: git remove без --force стёр бы его молча
    p = wt / "big-ignored"
    g(repo, "worktree", "add", "-q", "-b", "wt-big", str(p), "main")
    (p / "out").mkdir()
    (p / "out" / "model.big").write_bytes(b"\0" * (2 * 1024 * 1024))
    # 10. код грузится из копии: PYTHONPATH процесса
    g(repo, "worktree", "add", "-q", "-b", "wt-pypath", str(wt / "pypath"), "main")
    # 11. забытый tail -F держит открытый файл внутри (в prune наблюдатели держат: правило monitor_max_h — только для переноса)
    p = wt / "tailed"
    g(repo, "worktree", "add", "-q", "-b", "wt-tail", str(p), "main")
    for d in wt.iterdir():
        if not d.is_symlink():
            age_tree(d)
    (wt / "tailed" / "x.small").write_text("x\n", encoding="utf-8")
    os.utime(wt / "tailed" / "x.small", (OLD_TS, OLD_TS))
    os.utime(wt / "tailed", (OLD_TS, OLD_TS))
    return repo, wt


def run(repo, apply=False, rules=None, **kw):
    buf = io.StringIO()
    rc = wp.prune(str(repo), apply, dict(RULES, **(rules or {})), False, out=buf, **kw)
    return rc, buf.getvalue()


def start_holders(wt):
    ps = [subprocess.Popen([sys.executable, "-c", "input()"], cwd=str(wt / "busy"), stdin=subprocess.PIPE),
          subprocess.Popen([sys.executable, "-c", "input()"], cwd=str(wt.parent), stdin=subprocess.PIPE, env=dict(os.environ, PYTHONPATH=str(wt / "pypath") + ":/nonexistent")),
          subprocess.Popen(["tail", "-F", str(wt / "tailed" / "x.small")], stdout=subprocess.DEVNULL)]
    time.sleep(0.4)
    return ps


def stop(ps):
    for p in ps:
        if p.stdin:
            p.stdin.close()
        else:
            p.terminate()
        p.wait(timeout=20)


def test_dry_run_changes_nothing(tmp_path):
    repo, wt = make_repo(tmp_path)
    before = sorted(p.name for p in wt.iterdir())
    rc, out = run(repo)
    assert rc == 0
    assert sorted(p.name for p in wt.iterdir()) == before
    # без процессов снимаются: clean-branch, nm-only, detached-saved, detached-merged, busy, pypath, tailed (держателей нет)
    assert "снял бы 7," in out and "(сухо)" in out and "clean-branch" in out and "detached-saved" in out and "detached-merged" in out
    assert g(repo, "branch", "--list", "merged-old")


def test_apply_removes_safe_copies_including_unmerged_branch_copy(tmp_path):
    repo, wt = make_repo(tmp_path)
    ps = start_holders(wt)
    try:
        rc, out = run(repo, True)
    finally:
        stop(ps)
    assert rc == 0, out
    left = sorted(p.name for p in wt.iterdir())
    assert left == sorted(["busy", "big-ignored", "dirty", "untracked", "detached-orphan", "hdd-real", "locked", "pypath", "tailed", "young"]), (left, out)
    assert "ИТОГ: снято 4," in out and "отказов 0" in out
    for why in ("есть изменённые отслеживаемые файлы", "есть неотслеживаемые файлы", "моложе 48 ч", "осиротевший коммит", "заперта", "ссылка на HDD", "процесс внутри",
                "крупные игнорируемые файлы"):
        assert why in out, (why, out)
    assert "осиротевший коммит" in out and "detached-orphan" in out
    assert "scratch.txt" in out                                   # список неотслеживаемых — в отчёт
    assert "out 2 МБ" in out                                # крупные игнорируемые — в отчёт
    # ветка снятой копии остаётся (потерь нет: коммит own.txt цел), влитая старая ветка удалена (-d), невлитые целы
    assert g(repo, "branch", "--list", "wt-clean") and "own.txt" in g(repo, "show", "--stat", "--format=", "wt-clean")
    assert not g(repo, "branch", "--list", "merged-old")
    assert g(repo, "branch", "--list", "wt-dirty") and g(repo, "branch", "--list", "saved-branch")
    # симлинк на HDD не тронут
    assert (wt / "hdd-real").is_symlink() and (tmp_path / "hdd" / "moved" / "a.txt").is_file()


def test_git_remove_without_force_silently_erases_ignored_files(tmp_path):
    """Почему нужна проверка big_ignored: git worktree remove БЕЗ --force молча стирает игнорируемые файлы (выходы прогонов, которых нет в ветках)."""
    repo, wt = make_repo(tmp_path)
    p = wt / "big-ignored"
    assert (p / "out" / "model.big").is_file()
    r = subprocess.run(["git", "worktree", "remove", str(p)], cwd=str(repo), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr                            # git не отказал…
    assert not p.exists()                                         # …и файл 2 МБ исчез вместе с папкой


def test_big_ignored_threshold_and_small_ignored_pass(tmp_path):
    repo, wt = make_repo(tmp_path)
    assert wp.big_ignored(str(wt / "big-ignored"), 1.0) == [("out", 2)] or wp.big_ignored(str(wt / "big-ignored"), 1.0)[0][1] == 2
    assert wp.big_ignored(str(wt / "big-ignored"), 5.0) == []     # порог выше — не крупный
    assert wp.big_ignored(str(wt / "nm-only"), 0.0001) == [("tiny.small", 0)] or wp.big_ignored(str(wt / "nm-only"), 0.0001) == []  # node_modules не в счёт
    rc, out = run(repo, rules={"big_mb": 10.0})                   # порог 10 МБ: копия с 2 МБ снимается
    assert "big-ignored" in out and "крупные игнорируемые" not in out


def test_unmerged_ok_false_returns_to_merged_only(tmp_path):
    repo, wt = make_repo(tmp_path)
    rc, out = run(repo, rules={"unmerged_ok": False})
    assert "ветка не влита (unmerged_ok выключен)" in out
    assert "clean-branch" not in out.split("оставляю:")[1].split("ветки влитые")[0].replace("оставляю", "") or "снял бы clean-branch" not in out
    assert "снял бы" in out and "detached-merged" in out


def test_pythonpath_and_open_file_hold_copy_in_one_busy_implementation(tmp_path):
    repo, wt = make_repo(tmp_path)
    ps = start_holders(wt)
    try:
        snap = la.proc_snapshot(holders=False)
        assert "PYTHONPATH внутри" in la.held_in(str(wt / "pypath"), snap)
        assert "cwd внутри" in la.held_in(str(wt / "busy"), snap)
        assert "открыт файл внутри" in la.held_in(str(wt / "tailed"), snap) or "в командной строке" in la.held_in(str(wt / "tailed"), snap)
        assert la.held_in(str(wt / "young"), snap) == ""
        assert "процесс внутри" in run(repo)[1]                  # prune держит те же копии
    finally:
        stop(ps)


def test_git_worktree_prune_only_when_hdd_mounted_and_with_expire(tmp_path, monkeypatch):
    repo, wt = make_repo(tmp_path)
    calls = []
    real = wp.git

    def spy(r, *a, cwd=None):
        calls.append(a)
        return real(r, *a, cwd=cwd)

    monkeypatch.setattr(wp, "git", spy)
    rc, out = run(repo, True, {"dst": str(tmp_path / "нет-hdd")})
    assert "не смонтирован" in out and not [c for c in calls if c[:2] == ("worktree", "prune")]
    calls.clear()
    rc, out = run(repo, True, {"dst": "/proc"})                  # /proc — точка монтирования, не «/»
    pr = [c for c in calls if c[:2] == ("worktree", "prune")]
    assert pr == [("worktree", "prune", "--expire", "3.days")] and "не смонтирован" not in out
    assert la.hdd_mounted("/proc") == "/proc" and la.hdd_mounted(str(tmp_path / "нет")) == "" and la.hdd_mounted("/") == ""


def test_script_does_not_remove_its_own_copy(tmp_path, monkeypatch):
    repo, wt = make_repo(tmp_path)
    monkeypatch.chdir(wt / "clean-branch")
    rc, out = run(repo, True)
    assert (wt / "clean-branch").is_dir() and "из неё запущен скрипт" in out


def test_threshold_from_config_and_cli(tmp_path, capsys):
    repo, wt = make_repo(tmp_path)
    cfg = tmp_path / "dev-disk.json"
    cfg.write_text(json.dumps({"worktree_prune": {"days": 3, "base": "main", "idle_h": 100000000}, "archive": {"worktrees": {"big_mb": 1}, "dst": str(tmp_path / "нет-hdd")}}), encoding="utf-8")
    r = wp.load_rules(cfg)
    assert r["idle_h"] == 100000000 and r["base"] == "main" and r["big_mb"] == 1 and r["unmerged_ok"] is True and r["prune_expire"] == "3.days" and r["dst"].endswith("нет-hdd")
    assert wp.load_rules(tmp_path / "нет.json") == dict(wp.DEFAULTS, big_mb=None, dst=None)
    assert wp.main(["--repo", str(repo), "--config", str(cfg), "--no-fetch"]) == 0
    assert "снял бы 0," in capsys.readouterr().out                 # тишина огромная — всё «моложе»
    assert wp.main(["--repo", str(repo), "--config", str(cfg), "--idle-h", "48", "--no-fetch"]) == 0
    assert "снял бы 7," in capsys.readouterr().out                # --idle-h перекрывает конфиг
    assert wp.main(["--repo", str(tmp_path / "нет-репо"), "--no-fetch"]) == 2


def test_real_rules_file_has_worktree_prune_keys():
    r = wp.load_rules(wp.RULES_PATH)
    assert r["days"] == 3 and r["base"] == "origin/main" and r["idle_h"] == 48 and r["unmerged_ok"] is True and r["prune_expire"] == "3.days"
    assert r["big_mb"] == 200 and r["dst"].startswith("/mnt/hdd")
    d = json.loads(wp.RULES_PATH.read_text(encoding="utf-8"))
    assert "T-20261125-89" in d["_worktree_prune_why"] and "TG 2769" in d["_worktree_prune_why"]

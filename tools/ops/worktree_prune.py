#!/usr/bin/env python3
"""Уборка рабочих копий git (worktree) remlab — постоянный инструмент (T-20261124-52/1; владелец 24.11 TG 2626: «старые рабочие копии
можно удалять автоматически»; разовый образец директора — ~/remlab-logs/wt-prune/wt_prune.py, 24.11 снял 41 копию, диск 18 → 23 ГБ).

Снимает ТОЛЬКО копию, у которой одновременно:
  • это не основная копия, не запертая (`git worktree lock`), не симлинк (папки, перенесённые на HDD `logs_archive.py`, — пропуск, не отказ);
  • она на ВЕТКЕ (ветка остаётся — `git worktree remove` её не трогает, потерь нет) ИЛИ отсоединена (detached), но её коммиты уже в base
    (предок base либо у каждого коммита есть патч-двойник в base — `git cherry` без «+»); detached невлитая держит коммиты одна — остаётся;
  • `git status --porcelain --untracked-files=all` пуст (несохранённого и неотслеживаемого нет);
  • последний коммит и mtime папки старше `days` суток;
  • ни у одного процесса текущая папка не внутри (виден только свой пользователь — чужие процессы ядро не показывает).
Удаление — `git worktree remove` без `--force`: на грязной копии git сам откажет (это «отказ», в итог). Потом ветки, влитые в base и
старше `days` суток, не занятые ни одной копией, — `git branch -d` (только -d: невлитую git не даст стереть).

Порог суток и база — `tools/scout/rules/dev-disk.json` → `worktree_prune` ({"days": 3, "base": "origin/main"}); `--days`/`--base` перекрывают.
По умолчанию СУХО — только список; `--apply` — делать. Вывод: «оставляю: причина N», по строке на снимаемую копию, итог
«снято N, ≈M МБ, отказов K» (сухо — «снял бы …»). Код 0; 1 — были отказы git при удалении; 2 — не репозиторий/плохие аргументы.
Крон (ставит директор, не код): раз в сутки ночью `python3 tools/ops/worktree_prune.py --apply >> ~/remlab-logs/wt-prune/cron.log 2>&1`.
Запуск: `python3 tools/ops/worktree_prune.py [--apply] [--repo ПАПКА] [--days N] [--base REF] [--no-fetch] [--config JSON]`;
тест: `python -m pytest tools/ops/tests/test_worktree_prune.py -q`. Без зависимостей (python 3.9+)."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RULES_PATH = ROOT / "tools" / "scout" / "rules" / "dev-disk.json"
DEFAULTS = {"days": 3.0, "base": "origin/main"}


def load_rules(path: Path) -> dict:
    try:
        r = json.loads(path.read_text(encoding="utf-8")).get("worktree_prune", {})
    except (OSError, ValueError, AttributeError):
        r = {}
    return {k: r.get(k, v) for k, v in DEFAULTS.items()}


def git(repo: str, *a: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *a], cwd=cwd or repo, capture_output=True, text=True)


def list_worktrees(repo: str) -> list[dict]:
    out, cur = [], {}
    for line in git(repo, "worktree", "list", "--porcelain").stdout.splitlines() + [""]:
        if not line:
            if cur:
                out.append(cur)
            cur = {}
        else:
            k, _, v = line.partition(" ")
            cur[k] = v
    return out


def busy_paths() -> set[str]:
    """Текущие папки процессов (чужие пользователи недоступны — ядро не даёт)."""
    out: set[str] = set()
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                out.add(os.readlink(f"/proc/{pid}/cwd"))
            except OSError:
                pass
    return out


def size_mb(p: str) -> int:
    r = subprocess.run(["du", "-sm", p], capture_output=True, text=True)
    try:
        return int(r.stdout.split()[0])
    except (IndexError, ValueError):
        return 0


def keep_reason(repo: str, w: dict, base: str, days: float, busy: set[str], now: float) -> str | None:
    """Причина оставить копию или None (можно снимать)."""
    p = w["worktree"]
    if os.path.islink(p):
        return "ссылка на HDD (перенесена logs_archive)"
    if not os.path.isdir(p):
        return "папки нет"
    if "locked" in w:
        return "заперта"
    if any(b == p or b.startswith(p + "/") for b in busy):
        return "процесс внутри"
    head = w.get("HEAD", "")
    if "branch" not in w and git(repo, "merge-base", "--is-ancestor", head, base).returncode != 0:
        # отсоединённая: коммиты держит только эта копия, пока нет патч-двойников в base
        if any(l.startswith("+") for l in git(repo, "cherry", base, head).stdout.splitlines()):
            return "detached не влита"
    st = git(repo, "status", "--porcelain", "--untracked-files=all", cwd=p)
    if st.returncode != 0:
        return "git status не отвечает"
    if st.stdout.strip():
        return "есть несохранённое"
    ct = int(git(repo, "log", "-1", "--format=%ct", head).stdout.strip() or now)
    age = (now - max(ct, os.path.getmtime(p))) / 86400
    if age < days:
        return f"моложе {days:g} сут"
    return None


def prune(repo: str, apply: bool, days: float, base: str, fetch: bool, out=None) -> int:
    def say(*a):
        print(*a, file=out or sys.stdout)

    if not os.path.isdir(repo) or git(repo, "rev-parse", "--git-dir").returncode != 0:
        say(f"[worktree-prune] не репозиторий git: {repo}")
        return 2
    if fetch and git(repo, "fetch", "-q", "origin").returncode != 0:
        say("[worktree-prune] ⚠ fetch не удался — base может отставать (это только осторожнее: влитым считается меньше)")
    if git(repo, "rev-parse", "--verify", "-q", base).returncode != 0:
        say(f"[worktree-prune] нет ссылки base: {base}")
        return 2
    now = time.time()
    wts = list_worktrees(repo)
    busy = busy_paths()
    keeps: dict[str, int] = {}
    todo: list[str] = []
    for w in wts[1:]:
        why = keep_reason(repo, w, base, days, busy, now)
        if why:
            keeps[why] = keeps.get(why, 0) + 1
        else:
            todo.append(w["worktree"])
    say(f"[worktree-prune] {time.strftime('%Y-%m-%d %H:%M:%S')} {'--apply' if apply else 'сухо'}; копий {len(wts) - 1}, base {base}, порог {days:g} сут")
    say("оставляю: " + (", ".join(f"{k} {v}" for k, v in sorted(keeps.items(), key=lambda x: -x[1])) or "ничего"))
    done = fail = mb = 0
    for p in todo:
        sz = size_mb(p)
        if not apply:
            mb += sz
            say(f"  снял бы {p} ({sz} МБ)")
            continue
        r = git(repo, "worktree", "remove", p)
        if r.returncode == 0:
            done += 1
            mb += sz
            say(f"  снял {p} ({sz} МБ)")
        else:
            fail += 1
            say(f"  ОТКАЗ {p}: {r.stderr.strip()[:120]}")
    # ветки: влитые в base, старше порога, не занятые копией (список копий — после снятия), не main/текущая
    held = {w.get("branch", "").removeprefix("refs/heads/") for w in list_worktrees(repo)}
    cur = git(repo, "symbolic-ref", "--short", "-q", "HEAD").stdout.strip()
    bdel, bdone, bfail = [], 0, 0
    for line in git(repo, "branch", "--merged", base, "--format=%(refname:short)").stdout.splitlines():
        b = line.strip()
        if not b or b in held or b in ("main", "master", cur, base):
            continue
        ct = int(git(repo, "log", "-1", "--format=%ct", b).stdout.strip() or now)
        if (now - ct) / 86400 >= days:
            bdel.append(b)
    for b in bdel if apply else []:
        if git(repo, "branch", "-d", b).returncode == 0:
            bdone += 1
        else:
            bfail += 1
    say(f"ветки влитые старше {days:g} сут: {len(bdel)}" + (f"; удалено {bdone}, git отказал {bfail}" if apply else " (сухо)"))
    say(f"ИТОГ: {'снято' if apply else 'снял бы'} {done if apply else len(todo)}, ≈{mb} МБ, отказов {fail}")
    return 1 if fail else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="делать (по умолчанию сухо)")
    ap.add_argument("--repo", default=None, help="основная копия (по умолчанию — репозиторий, где лежит скрипт)")
    ap.add_argument("--days", type=float, default=None)
    ap.add_argument("--base", default=None)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--config", default=str(RULES_PATH))
    a = ap.parse_args(argv)
    rules = load_rules(Path(a.config))
    days = rules["days"] if a.days is None else a.days
    base = rules["base"] if a.base is None else a.base
    if days < 0:
        ap.error("--days: не меньше 0")
    repo = a.repo
    if repo is None:
        # скрипт мог быть запущен из рабочей копии: убираем worktree ОСНОВНОГО репозитория
        r = git(str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir")
        repo = str(Path(r.stdout.strip()).parent) if r.returncode == 0 and r.stdout.strip() else str(ROOT)
    return prune(os.path.abspath(repo), a.apply, days, base, not a.no_fetch)


if __name__ == "__main__":
    sys.exit(main())

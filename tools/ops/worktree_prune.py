#!/usr/bin/env python3
"""Уборка рабочих копий git (worktree) remlab — постоянный инструмент (T-20261124-52/1; владелец 24.11 TG 2626: «старые рабочие копии
можно удалять автоматически»; T-20261125-89 / владелец TG 2769 «поручить уборку»: 25.11 диск упал до 11,5 ГБ — в ~/remlab-logs 230 копий по ≈185 МБ).

Снимает ТОЛЬКО копию, у которой одновременно (пороги — `tools/scout/rules/dev-disk.json` → `worktree_prune`, чисел в коде нет, кроме запасных на случай, если файла правил нет):
  • это не основная копия, не запертая (`git worktree lock`), не симлинк (папки, перенесённые на HDD `logs_archive.py`, — пропуск), не та копия, из которой запущен скрипт;
  • коммиты не теряются: копия на ВЕТКЕ (ветка остаётся — `git worktree remove` её не трогает) ИЛИ отсоединена (detached), но её HEAD ДОСТИЖИМ из какой-либо ветки
    (локальной или `origin/*`, `git for-each-ref --contains`) либо у каждого коммита есть патч-двойник в base (`git cherry` без «+»). Влитость в base НЕ требуется (T-89:
    невлитая, но чистая копия на ветке или с коммитом, достижимым из ветки, снимается; `unmerged_ok: false` возвращает прежнее «только влитые»).
    Detached, чей HEAD не достижим ни из одной ветки, — НЕ снимается, строка «осиротевший коммит <sha>» в отчёт (копия — единственный держатель коммитов);
  • `git status --porcelain` без изменённых ОТСЛЕЖИВАЕМЫХ файлов; неотслеживаемые (кроме путей с node_modules/__pycache__) — копию НЕ снимаем, их список — в отчёт;
  • последняя запись в копии старше `idle_h` часов: самый свежий файл/папка внутри (без `.git`, `node_modules`, `__pycache__`) и последний коммит;
  • в копии нет ИГНОРИРУЕМЫХ (.gitignore) файлов крупнее `archive.worktrees.big_mb` (200 МБ; кроме node_modules/__pycache__): `git worktree remove` без --force стирает их молча — это выходы прогонов
    (glb, кадры), которых нет ни в одной ветке (поправка Fable п.1);
  • копию не держит процесс — ОДНА реализация занятости с переносом папок, `logs_archive.proc_snapshot/held_in`: cwd, открытый файл, её путь в командной строке, PYTHONPATH в окружении
    (код грузится из копии), держатели heavy-slot (`holder*`, строка cmd=). Забытый `tail -F … | grep` здесь ДЕРЖИТ (правило monitor_max_h — только для переноса папок). Виден только
    процесс этой машины; сессии на других машинах видны лишь по записям файлов (`idle_h`).
Удаление — `git worktree remove` БЕЗ `--force`: на грязной копии git сам откажет («отказ» в итог); в конце `git worktree prune --expire <prune_expire>` — ТОЛЬКО если HDD
(`archive.dst`) смонтирован: без него записи копий, ушедших туда по ссылке (worktrees_block=false), стёрлись бы (поправка Fable п.2). Потом ветки, влитые в base и старше `days`
суток, не занятые ни одной копией, — `git branch -d` (только -d: невлитую git не даст стереть).

По умолчанию СУХО — только список; `--apply` — делать. Вывод: «оставляю: причина N», по строке на снимаемую копию, итог «ИТОГ: снял бы N, ≈M МБ (≈X ГБ), отказов K; оставлю L».
Код 0; 1 — были отказы git при удалении; 2 — не репозиторий/плохие аргументы.
Запуск: `python3 tools/ops/worktree_prune.py [--apply] [--repo ПАПКА] [--idle-h Ч] [--days N] [--base REF] [--no-fetch] [--config JSON]`; часовой запуск — юнит
`infra/server/dev-disk/remlab-logs-archive-hourly.service` (сперва это, потом перенос на HDD); тест: `python -m pytest tools/ops/tests/test_worktree_prune.py -q`. Без внешних зависимостей (python 3.9+)."""
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
sys.path.insert(0, str(HERE))
import logs_archive as LA  # noqa: E402  (общие: наблюдатели tail, держатели heavy-slot)

RULES_PATH = ROOT / "tools" / "scout" / "rules" / "dev-disk.json"
DEFAULTS = {"days": 3.0, "base": "origin/main", "idle_h": 48.0, "unmerged_ok": True, "prune_expire": "3.days"}   # запасные значения, если файла правил нет; источник — dev-disk.json
SKIP_DIRS = {".git", "node_modules", "__pycache__"}


def load_rules(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        r = d.get("worktree_prune", {})
        arch = d.get("archive") or {}
    except (OSError, ValueError, AttributeError):
        r, arch = {}, {}
    out = {k: r.get(k, v) for k, v in DEFAULTS.items()}
    out["big_mb"] = (arch.get("worktrees") or {}).get("big_mb")     # один порог «крупного» с logs_archive --worktrees; нет — проверка выключена
    out["dst"] = os.path.expanduser(arch["dst"]) if arch.get("dst") else None   # HDD: без него `git worktree prune` не делаем
    return out


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


def newest_write(path: str, floor: float) -> float:
    """Самое свежее время записи внутри копии (файлы и папки; без .git, node_modules, __pycache__; симлинки не раскрываем). Нашли не старше `floor` — выходим сразу."""
    best = os.lstat(path).st_mtime
    stack = [path]
    while stack and best < floor:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        m = e.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    best = max(best, m)
                    if best >= floor:
                        return best
                    if e.is_dir(follow_symlinks=False) and e.name not in SKIP_DIRS:
                        stack.append(e.path)
        except OSError:
            continue
    return best


def size_mb(p: str) -> int:
    r = subprocess.run(["du", "-sm", p], capture_output=True, text=True)
    try:
        return int(r.stdout.split()[0])
    except (IndexError, ValueError):
        return 0


def reachable(repo: str, head: str) -> bool:
    """HEAD достижим из какой-либо ветки — локальной или origin/* (коммиты не пропадут при снятии копии)."""
    r = git(repo, "for-each-ref", "--contains", head, "--count=1", "--format=%(refname)", "refs/heads", "refs/remotes")
    return r.returncode == 0 and bool(r.stdout.strip())


def big_ignored(p: str, big_mb: float) -> list:
    """Игнорируемые (.gitignore) файлы/папки копии крупнее big_mb: [(путь, МБ)]. `git worktree remove` БЕЗ --force такие файлы молча стирает (git их «не видит»), а это выходы прогонов
    (glb, кадры, npz), которых нет ни в одной ветке. node_modules и __pycache__ (восстановимы) не в счёт."""
    r = git(p, "status", "--porcelain", "--ignored", cwd=p)
    out = []
    for ln in r.stdout.splitlines():
        if not ln.startswith("!!"):
            continue
        rel = ln[3:].strip().strip('"').rstrip("/")
        if any(part in SKIP_DIRS for part in rel.split("/")):
            continue
        q = os.path.join(p, rel)
        if os.path.islink(q):
            continue
        d = subprocess.run(["du", "-sk", "--", q], capture_output=True, text=True)
        try:
            mb = int(d.stdout.split()[0]) / 1024
        except (IndexError, ValueError):
            continue
        if mb > big_mb:
            out.append((rel, round(mb)))
    return out


def keep_reason(repo: str, w: dict, base: str, rules: dict, snap: list, now: float, info: dict | None = None) -> str | None:
    """Причина оставить копию или None (можно снимать). info — сюда кладём untracked/orphan для отчёта."""
    info = info if info is not None else {}
    p = w["worktree"]
    if os.path.islink(p):
        return "ссылка на HDD (перенесена logs_archive)"
    if not os.path.isdir(p):
        return "папки нет"
    if "locked" in w:
        return "заперта"
    own = {os.path.realpath(os.getcwd()), os.path.realpath(str(ROOT))}
    rp = os.path.realpath(p)
    if any(o == rp or o.startswith(rp + "/") for o in own):
        return "из неё запущен скрипт"
    why = LA.held_in(p, snap)                                  # одна реализация занятости (logs_archive): cwd, командная строка, открытые файлы, PYTHONPATH, держатели heavy-slot
    if why:
        info["held"] = why
        return "процесс внутри"
    head = w.get("HEAD", "")
    twins = None                                              # патч-двойники в base у всех коммитов (git cherry без «+»)

    def merged_somehow() -> bool:
        nonlocal twins
        if git(repo, "merge-base", "--is-ancestor", head, base).returncode == 0:
            return True
        if twins is None:
            twins = not any(l.startswith("+") for l in git(repo, "cherry", base, head).stdout.splitlines())
        return twins

    if "branch" not in w:
        if not reachable(repo, head) and not merged_somehow():
            info["orphan"] = head[:9]
            return "осиротевший коммит (detached, ни в одной ветке)"
    if not rules.get("unmerged_ok", True) and not merged_somehow():
        return "ветка не влита (unmerged_ok выключен)"
    st = git(repo, "status", "--porcelain", cwd=p)
    if st.returncode != 0:
        return "git status не отвечает"
    tracked, untracked = [], []
    for ln in st.stdout.splitlines():
        path = ln[3:].strip().strip('"')
        if ln.startswith("??"):
            if not any(part in SKIP_DIRS for part in path.split("/")):
                untracked.append(path)
        elif ln.strip():
            tracked.append(path)
    if tracked:
        return "есть изменённые отслеживаемые файлы"
    if untracked:
        info["untracked"] = untracked
        return "есть неотслеживаемые файлы"
    big = big_ignored(p, float(rules["big_mb"])) if rules.get("big_mb") is not None else []
    if big:
        info["big"] = big
        return f"крупные игнорируемые файлы (> {float(rules['big_mb']):g} МБ)"
    idle_s = float(rules["idle_h"]) * 3600
    ct = int(git(repo, "log", "-1", "--format=%ct", head).stdout.strip() or now)
    last = max(ct, newest_write(p, floor=now - idle_s))
    if now - last < idle_s:
        return f"моложе {float(rules['idle_h']):g} ч"
    return None


def prune(repo: str, apply: bool, rules: dict, fetch: bool, out=None, proc_root: str = "/proc", heavy_dir: str | None = None) -> int:
    def say(*a):
        print(*a, file=out or sys.stdout)

    base, days = rules["base"], float(rules["days"])
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
    LA.MONITOR_NOTES.clear()
    snap = LA.proc_snapshot(proc_root, None, holders=True, heavy_dir=heavy_dir)   # наблюдатели tail держат и здесь: правило monitor_max_h — только для переноса папок (поправка Fable)
    keeps: dict[str, int] = {}
    todo: list[str] = []
    orphans: list[tuple[str, str]] = []
    untracked_of: list[tuple[str, list]] = []
    bigs: list[tuple[str, list]] = []
    for w in wts[1:]:
        info: dict = {}
        why = keep_reason(repo, w, base, rules, snap, now, info)
        if why:
            keeps[why] = keeps.get(why, 0) + 1
            if "orphan" in info:
                orphans.append((w["worktree"], info["orphan"]))
            if "untracked" in info:
                untracked_of.append((w["worktree"], info["untracked"]))
            if "big" in info:
                bigs.append((w["worktree"], info["big"]))
        else:
            todo.append(w["worktree"])
    say(f"[worktree-prune] {time.strftime('%Y-%m-%d %H:%M:%S')} {'--apply' if apply else 'сухо'}; копий {len(wts) - 1}, base {base}, тишина ≥ {float(rules['idle_h']):g} ч"
        + ("" if rules.get("unmerged_ok", True) else ", только влитые"))
    say("оставляю: " + (", ".join(f"{k} {v}" for k, v in sorted(keeps.items(), key=lambda x: -x[1])) or "ничего"))
    for p, lst in bigs[:60]:
        say(f"  крупные игнорируемые в {p}: " + ", ".join(f"{n} {mb} МБ" for n, mb in lst[:4]) + (f" (+{len(lst) - 4})" if len(lst) > 4 else ""))
    for p, sha in orphans:
        say(f"  осиротевший коммит {sha} в {p}")
    for p, lst in untracked_of[:60]:
        say(f"  неотслеживаемые в {p}: {', '.join(lst[:4])}" + (f" (+{len(lst) - 4})" if len(lst) > 4 else ""))
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
    if apply:
        mnt = LA.hdd_mounted(rules["dst"]) if rules.get("dst") else ""
        if mnt:                                                # без смонтированного HDD записи копий, ушедших туда по ссылке, `git worktree prune` стёр бы (поправка Fable, п.2)
            git(repo, "worktree", "prune", "--expire", str(rules["prune_expire"]))
        else:
            say(f"[worktree-prune] ⚠ HDD ({rules.get('dst')}) не смонтирован — `git worktree prune` не делаю")
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
    left = sum(keeps.values())
    say(f"ИТОГ: {'снято' if apply else 'снял бы'} {done if apply else len(todo)}, ≈{mb} МБ (≈{mb / 1024:.1f} ГБ), отказов {fail}; оставлю {left}")
    return 1 if fail else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="делать (по умолчанию сухо)")
    ap.add_argument("--repo", default=None, help="основная копия (по умолчанию — репозиторий, где лежит скрипт)")
    ap.add_argument("--idle-h", type=float, default=None, help="тишина в копии, часов (перекрывает worktree_prune.idle_h)")
    ap.add_argument("--days", type=float, default=None, help="возраст влитых веток для git branch -d")
    ap.add_argument("--base", default=None)
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--config", default=str(RULES_PATH))
    a = ap.parse_args(argv)
    rules = load_rules(Path(a.config))
    if a.days is not None:
        rules["days"] = a.days
    if a.base is not None:
        rules["base"] = a.base
    if a.idle_h is not None:
        rules["idle_h"] = a.idle_h
    if float(rules["days"]) < 0 or float(rules["idle_h"]) < 0:
        ap.error("--days/--idle-h: не меньше 0")
    repo = a.repo
    if repo is None:
        # скрипт мог быть запущен из рабочей копии: убираем worktree ОСНОВНОГО репозитория
        r = git(str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir")
        repo = str(Path(r.stdout.strip()).parent) if r.returncode == 0 and r.stdout.strip() else str(ROOT)
    return prune(os.path.abspath(repo), a.apply, rules, not a.no_fetch)


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""НОЧНОЙ ПЕРЕНОС СТАРЫХ ПАПОК ~/remlab-logs НА HDD (T-20261123-35; владелец TG 2227/2230, P-072 «Диск pakardev»).

ЗАЧЕМ. 23.11 диск pakardev дошёл до 100 %: ~/remlab-logs (144 ГБ) — выводы задач, их никто не читает после приёмки, но часть папок — вход чужих
скриптов и планов. Удалять нельзя (вывод пакета ещё нужен как «до» в сравнении), поэтому папка уезжает на /mnt/hdd, а на месте остаётся ссылка.

ЧТО УЕЗЖАЕТ (правила — tools/scout/rules/dev-disk.json → archive): папка первого уровня src, у которой
  • самый свежий файл (и сама папка) старше `days` суток (по умолчанию 5);
  • на её ИМЯ нет ссылок в репозитории (`git grep -F` по имени: код, rules, планы, CI; журналы и архив памяти из `refs_exclude` — история, не вход — не считаются) —
    «на неё ссылаются» = остаётся;
  • это не рабочая копия git (в ней `.git`; и не путь из `git worktree list`) и не вложенная в неё, и её не держит процесс (cwd, открытый файл,
    имя в командной строке);
  • не ссылка (symlink — уже перенесена), не скрытая, не в `never`.
КАК. Сухо по умолчанию: список «перенесу X (размер, освободит), причина» и итог. `--apply` переносит: `rsync -aH --remove-source-files <папка>/ <dst>/<папка>/`,
затем убирает ПУСТЫЕ каталоги (os.rmdir, только пустые) и ставит ссылку; не опустела — ссылки нет, строка ❗ (данные целы и там, и там — разбор руками).
Перед переносом каждую папку проверяем заново (свежий файл появился, процесс взял — пропуск). Места на HDD ≥ размер × 1,1 + `min_hdd_free_gb`, иначе пропуск.
Файлы данных никакими командами не удаляются: уходят только rsync'ом (`--remove-source-files` удаляет файл лишь после успешной копии).
СЧЁТ ОСВОБОЖДЁННОГО. Диск освобождают только файлы с ОДНОЙ жёсткой ссылкой (st_nlink==1, как `find -links 1`; один inode — один раз): файл с
второй ссылкой (на него смотрит и другая папка) после переноса места не вернёт. «Размер» — полный, «освободит» — по st_nlink==1.
  python3 tools/ops/logs_archive.py                  # сухо: список и размеры
  python3 tools/ops/logs_archive.py --apply [--digest] [--limit N]
  python3 tools/ops/logs_archive.py --json           # сухо, машинно
  python3 tools/ops/logs_archive.py --days 2         # разовый порог суток (прикинуть, сколько освободит)
  python3 tools/ops/logs_archive.py --worktrees-ok   # (или archive.worktrees_block=false в rules) переносить и папки с рабочими копиями git: путь в
                                                     # .git/worktrees/*/gitdir остаётся прежним и через ссылку работает; по умолчанию такие папки остаются
Переопределения для проверки: LOGS_ARCHIVE_RULES (файл правил), LOGS_ARCHIVE_REPO (репозиторий для поиска ссылок)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
RULES_PATH = os.path.join(ROOT, 'tools', 'scout', 'rules', 'dev-disk.json')
GB = 1024 ** 3
DEFAULTS = {'src': '~/remlab-logs', 'dst': '/mnt/hdd/remlab-logs-arhiv', 'days': 5, 'min_hdd_free_gb': 50, 'never': [], 'worktrees_block': True, 'refs_exclude': []}


def rules() -> dict:
    p = os.environ.get('LOGS_ARCHIVE_RULES') or RULES_PATH
    try:
        with open(p, encoding='utf-8') as f:
            r = (json.load(f).get('archive')) or {}
    except (OSError, ValueError):
        r = {}
    out = {k: r.get(k, v) for k, v in DEFAULTS.items()}
    out['src'] = os.path.expanduser(out['src'])
    out['dst'] = os.path.expanduser(out['dst'])
    return out


def newest_mtime(path: str, floor: float = 0.0) -> float:
    """Самое свежее время изменения среди самой папки и всего внутри (symlink не раскрываем). Нашли файл свежее `floor` — выходим сразу."""
    best = os.lstat(path).st_mtime
    stack = [path]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        m = e.stat(follow_symlinks=False).st_mtime
                    except OSError:
                        continue
                    best = max(best, m)
                    if floor and best >= floor:
                        return best
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
        except OSError:
            continue
    return best


def sizes(path: str) -> tuple[int, int]:
    """(полный размер, освободит) в байтах: освободит — файлы с st_nlink==1; один inode считается один раз."""
    total = freed = 0
    seen = set()
    for dp, _dn, fn in os.walk(path, followlinks=False):
        for f in fn:
            try:
                st = os.lstat(os.path.join(dp, f))
            except OSError:
                continue
            if os.path.islink(os.path.join(dp, f)):
                continue
            key = (st.st_dev, st.st_ino)
            if key in seen:
                continue
            seen.add(key)
            total += st.st_size
            if st.st_nlink == 1:
                freed += st.st_size
    return total, freed


def repo_refs(names: list, repo: str, exclude: list | None = None) -> set:
    """Какие из имён встречаются в отслеживаемых файлах репозитория (один `git grep -o -F -f`: печатает найденные подстроки)."""
    if not names:
        return set()
    with tempfile.NamedTemporaryFile('w', suffix='.pat', delete=False) as f:
        f.write('\n'.join(names) + '\n')
        pat = f.name
    try:
        r = subprocess.run(['git', '-C', repo, 'grep', '-h', '-o', '-F', '-f', pat, '--', '.'] + [f':(exclude){x}' for x in (exclude or [])], capture_output=True, text=True, timeout=300)
        if r.returncode not in (0, 1):                       # 1 — совпадений нет (норма); больше — git не смог (нет репо и т.п.)
            return set(names)
        return {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    except (OSError, subprocess.SubprocessError):
        return set(names)                                    # не смогли проверить — считаем, что ссылаются на всё (ничего не переносим)
    finally:
        try:
            os.unlink(pat)
        except OSError:
            pass


def worktree_paths(repo: str) -> set:
    try:
        r = subprocess.run(['git', '-C', repo, 'worktree', 'list', '--porcelain'], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return set()
    return {os.path.realpath(ln.split(' ', 1)[1]) for ln in r.stdout.splitlines() if ln.startswith('worktree ')}


def busy_by(path: str, proc_root: str = '/proc') -> str:
    """Что держит папку: процесс с cwd/открытым файлом внутри или её именем в командной строке (свои процессы тоже). '' — никто."""
    real = os.path.realpath(path)
    pref = real.rstrip('/') + '/'
    me = os.getpid()
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit() and int(p) != me]
    except OSError:
        return ''
    for p in pids:
        base = f'{proc_root}/{p}'
        try:
            cwd = os.readlink(f'{base}/cwd')
            if cwd == real or cwd.startswith(pref):
                return f'pid {p}: cwd внутри'
            cmd = open(f'{base}/cmdline', 'rb').read().replace(b'\0', b' ').decode('utf-8', 'replace')
            if pref in cmd or cmd.rstrip().endswith(real):
                return f'pid {p}: в командной строке'
            for fd in os.listdir(f'{base}/fd'):
                try:
                    t = os.readlink(f'{base}/fd/{fd}')
                except OSError:
                    continue
                if t == real or t.startswith(pref):
                    return f'pid {p}: открыт файл внутри'
        except OSError:
            continue
    return ''


def candidates(r: dict, repo: str, now: float | None = None, refs=None, busy=None) -> tuple[list, list]:
    """(к переносу, пропущено с причинами). Запись: {name, path, total, freed, age_d, why}."""
    now = time.time() if now is None else now
    cutoff = now - float(r['days']) * 86400
    src = r['src']
    try:
        names = sorted(n for n in os.listdir(src) if not n.startswith('.'))
    except OSError:
        return [], [('—', f'нет папки {src}')]
    wt = worktree_paths(repo)
    dirs = []
    skipped = []
    for n in names:
        p = os.path.join(src, n)
        if os.path.islink(p):
            continue                                            # уже перенесена
        if not os.path.isdir(p):
            continue                                            # одиночные файлы-журналы — дело disk-keeper
        if n in (r.get('never') or []):
            skipped.append((n, 'в never'))
            continue
        real = os.path.realpath(p)
        if os.path.isdir(os.path.join(p, '.git')):
            skipped.append((n, 'полный клон git (.git — папка)'))
            continue
        if r.get('worktrees_block', True) and (os.path.exists(os.path.join(p, '.git')) or any(w == real or w.startswith(real + '/') for w in wt)):
            skipped.append((n, 'рабочая копия git (или содержит) — worktrees_block'))
            continue
        if newest_mtime(p, floor=cutoff) >= cutoff:
            skipped.append((n, f'свежая (≤ {r["days"]} сут)'))
            continue
        dirs.append(n)
    referenced = refs(dirs, repo) if refs else repo_refs(dirs, repo, r.get('refs_exclude') or [])
    todo = []
    for n in dirs:
        p = os.path.join(src, n)
        if n in referenced:
            skipped.append((n, 'на имя есть ссылка в репозитории'))
            continue
        who = (busy or busy_by)(p)
        if who:
            skipped.append((n, f'занята: {who}'))
            continue
        total, freed = sizes(p)
        todo.append({'name': n, 'path': p, 'total': total, 'freed': freed, 'age_d': round((now - newest_mtime(p)) / 86400, 1)})
    return todo, skipped


def hdd_free_gb(dst: str) -> float:
    d = dst
    while d and not os.path.exists(d):
        d = os.path.dirname(d)
    st = os.statvfs(d or '/')
    return st.f_bavail * st.f_frsize / GB


def move_one(c: dict, r: dict, now: float | None = None, busy=None, rsync=None) -> tuple[bool, str]:
    """Перенос одной папки: перепроверка → rsync → пустые каталоги → ссылка. (успех, строка). Данные удаляет только rsync после успешной копии."""
    p, n, dst = c['path'], c['name'], r['dst']
    now = time.time() if now is None else now
    if os.path.islink(p) or not os.path.isdir(p):
        return False, f'{n}: уже не папка — пропуск'
    if newest_mtime(p, floor=now - float(r['days']) * 86400) >= now - float(r['days']) * 86400:
        return False, f'{n}: появился свежий файл — пропуск'
    who = (busy or busy_by)(p)
    if who:
        return False, f'{n}: занята ({who}) — пропуск'
    need = c['total'] * 1.1 / GB + float(r['min_hdd_free_gb'])
    free = hdd_free_gb(dst)
    if free < need:
        return False, f'❗ {n}: на HDD свободно {free:.0f} ГБ, нужно {need:.0f} — пропуск'
    target = os.path.join(dst, n)
    os.makedirs(target, exist_ok=True)
    cmd = ['rsync', '-aH', '--remove-source-files', p + '/', target + '/']
    rc = (rsync or (lambda cm: subprocess.run(cm, capture_output=True, text=True).returncode))(cmd)
    if rc != 0:
        return False, f'❗ {n}: rsync вернул {rc} — ссылки нет, данные на месте и частично на HDD'
    for dp, dn, fn in os.walk(p, topdown=False, followlinks=False):
        try:
            os.rmdir(dp)                                      # только пустой; непустой — исключение, оставляем
        except OSError:
            pass
    if os.path.exists(p):
        return False, f'❗ {n}: после rsync не опустела — ссылку не ставлю (разбор руками)'
    os.symlink(target, p)
    return True, f'{n}: перенесено → {target} ({c["total"] / GB:.2f} ГБ, освободило {c["freed"] / GB:.2f} ГБ)'


def alert(text: str) -> None:
    try:
        sys.path.insert(0, HERE)
        import disk_guard as DG
        DG._journal(text)
        DG._send_tg(text)
    except Exception:
        pass


def main(argv: list) -> int:
    apply_ = '--apply' in argv
    r = rules()
    if '--days' in argv and argv.index('--days') + 1 < len(argv):   # разовый порог для сухого прикидочного прогона (в правилах — archive.days)
        r['days'] = float(argv[argv.index('--days') + 1])
    if '--worktrees-ok' in argv:                              # перенос и рабочих копий git: ссылка на месте сохраняет путь, записанный в .git/worktrees/*/gitdir
        r['worktrees_block'] = False
    repo = os.environ.get('LOGS_ARCHIVE_REPO') or ROOT
    todo, skipped = candidates(r, repo)
    todo.sort(key=lambda c: -c['freed'])
    limit = int(argv[argv.index('--limit') + 1]) if '--limit' in argv and argv.index('--limit') + 1 < len(argv) else 0
    if limit:
        todo = todo[:limit]
    if '--json' in argv:
        print(json.dumps({'todo': todo, 'skipped': skipped, 'src': r['src'], 'dst': r['dst'], 'days': r['days']}, ensure_ascii=False, indent=1))
        return 0
    tot = sum(c['total'] for c in todo)
    fr = sum(c['freed'] for c in todo)
    print(f'{r["src"]} → {r["dst"]} · старше {r["days"]} сут и без ссылок из репозитория: {len(todo)} папок, {tot / GB:.1f} ГБ, освободит {fr / GB:.1f} ГБ ({"ПЕРЕНОС" if apply_ else "сухо"})')
    for c in todo:
        print(f'  {"перенесу" if not apply_ else "переношу"} {c["name"]}  {c["total"] / GB:.2f} ГБ, освободит {c["freed"] / GB:.2f} ГБ, возраст {c["age_d"]} сут')
    for n, why in skipped:
        print(f'  оставляю {n}: {why}')
    if not apply_:
        return 0
    moved = got = 0
    fails = []
    for c in todo:
        ok, line = move_one(c, r)
        print('  ' + line)
        if ok:
            moved += 1
            got += c['freed']
        elif '❗' in line:
            fails.append(line)
    free = os.statvfs(r['src'])
    left = free.f_bavail * free.f_frsize / GB
    summary = f'DIGEST:логи: перенесено {moved} из {len(todo)}, освободило {got / GB:.1f} ГБ, свободно на диске {left:.0f} ГБ'
    if '--digest' in argv:
        print(summary)
    else:
        print(summary.replace('DIGEST:', ''))
    if fails:
        alert('❗ перенос логов на HDD: ' + '; '.join(fails)[:900])
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

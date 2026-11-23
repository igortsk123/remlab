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
  python3 tools/ops/logs_archive.py --worktrees      # СУХО: рабочие копии git, которые можно снять + крупные выходы внутри (T-20261123-38)
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


WT_DEFAULTS = {'idle_h': 12, 'big_mb': 200, 'base': 'origin/main', 'jobs': 4}


def rules() -> dict:
    p = os.environ.get('LOGS_ARCHIVE_RULES') or RULES_PATH
    try:
        with open(p, encoding='utf-8') as f:
            r = (json.load(f).get('archive')) or {}
    except (OSError, ValueError):
        r = {}
    out = {k: r.get(k, v) for k, v in DEFAULTS.items()}
    out['wt'] = dict(WT_DEFAULTS, **(r.get('worktrees') or {}))
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


# ───────────── --worktrees: СУХОЙ список рабочих копий git под src, которые можно снять (T-20261123-38) ─────────────
# Решает директор (`git worktree remove` — его шаг); здесь ничего не удаляется и не переносится. «Можно снять» = ВСЕ условия:
#   • HEAD — предок `base` (origin/main: влито) ИЛИ ветка удалена (нет ни локальной, ни origin/<ветка>) — тогда пометка «не влито»: коммиты живут только здесь;
#   • `git status --porcelain --ignored` пусто, кроме ссылки/папки node_modules; (отдельный раздел can_ign — мешает только игнорируемое: кэши, .next);
#   • нет процесса с cwd/открытым файлом/именем в командной строке внутри; последняя правка старше `idle_h` часов; не locked; каталог на месте.
# Каталога нет (prunable) — отдельная строка «сирота» (чинится `git worktree prune`, места не освобождает).
# Размер — по файлам с одной жёсткой ссылкой (st_nlink==1; ссылка node_modules не считается). Крупные выходы внутри рабочих копий (не в git: `??`/`!!`
# записи status размером ≥ big_mb МБ, кроме node_modules) выводятся отдельным списком — для ВСЕХ копий, в том числе занятых, с отметкой «ссылка в репо».

def _git(repo: str, *args, timeout: int = 120):
    try:
        p = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 99, ''


def list_worktrees(repo: str, src: str) -> list:
    """Рабочие копии из `git worktree list --porcelain`, лежащие под src (главная копия и чужие места не берутся)."""
    rc, out = _git(repo, 'worktree', 'list', '--porcelain')
    items, cur = [], {}
    for ln in out.splitlines() + ['']:
        if not ln.strip():
            if cur:
                items.append(cur)
            cur = {}
            continue
        k, _, v = ln.partition(' ')
        cur[k] = v or True
    base = os.path.abspath(src).rstrip('/') + '/'
    res = []
    for it in items[1:]:                                       # первая — главная копия
        p = it.get('worktree', '')
        if os.path.abspath(p).startswith(base):
            res.append({'path': p, 'head': it.get('HEAD', ''), 'branch': (it['branch'].replace('refs/heads/', '') if it.get('branch') else None),
                        'locked': 'locked' in it, 'prunable': 'prunable' in it})
    return res


def status_entries(path: str) -> tuple[list, bool]:
    """([(код, путь)], ok) из `git status --porcelain --ignored` в рабочей копии."""
    rc, out = _git(path, 'status', '--porcelain', '--ignored', timeout=300)
    if rc != 0:
        return [], False
    ents = []
    for ln in out.splitlines():
        if len(ln) > 3:
            ents.append((ln[:2], ln[3:].strip('"')))
    return ents, True


def wt_info(w: dict, repo: str, r: dict, now: float, busy=None) -> dict:
    """Всё про одну рабочую копию + вердикт: can / maybe (ветки нет, не влито) / hold / orphan. Только чтение."""
    cfg = r['wt']
    p, base = w['path'], cfg['base']
    inf = dict(w, size=0, freed=0, merged=False, merged_local=False, branch_gone=False, dirty=[], big=[], why=[], verdict='hold', idle_h=None)
    if not os.path.isdir(p):
        inf.update(verdict='orphan', why=['каталога нет — `git worktree prune`'])
        return inf
    head = w['head'] or 'HEAD'
    inf['merged'] = _git(repo, 'merge-base', '--is-ancestor', head, base)[0] == 0
    inf['merged_local'] = _git(repo, 'merge-base', '--is-ancestor', head, 'main')[0] == 0
    if w['branch']:
        local = _git(repo, 'rev-parse', '--verify', '-q', f'refs/heads/{w["branch"]}')[0] == 0
        remote = _git(repo, 'rev-parse', '--verify', '-q', f'refs/remotes/origin/{w["branch"]}')[0] == 0
        inf['branch_gone'] = not (local or remote)
    ents, ok = status_entries(p)
    inf['dirty'] = [f'{c} {n}' for c, n in ents if not (c == '!!' and n.rstrip('/') == 'node_modules')]
    inf['entries'] = [(c, n) for c, n in ents if n.rstrip('/') != 'node_modules']
    why = []
    if not ok:
        why.append('git status не отработал')
    if inf['dirty']:
        why.append(f'не чисто: {len(inf["dirty"])} (напр. {inf["dirty"][0][:60]})')
    if w['locked']:
        why.append('locked')
    who = (busy or busy_by)(p)
    if who:
        why.append(f'занята: {who}')
    floor = now - cfg['idle_h'] * 3600
    newest = newest_mtime(p, floor=floor)
    inf['idle_h'] = round((now - newest) / 3600, 1)
    if newest >= floor:
        why.append(f'правили {inf["idle_h"]} ч назад (< {cfg["idle_h"]})')
    if not inf['merged'] and not inf['branch_gone']:
        why.append('не влито в ' + base + (' (влито в локальный main)' if inf['merged_local'] else ''))
    inf['size'], inf['freed'] = sizes(p)
    inf['why'] = why
    real_dirty = [d for d in inf['dirty'] if not d.startswith('!!')]
    if inf['dirty'] and not real_dirty and why and all(x.startswith('не чисто') for x in why) and inf['merged']:
        inf['verdict'] = 'can_ign'                              # единственная помеха — игнорируемое (`!!`: __pycache__, .pytest_cache, .next, tsbuildinfo…); трекаемого и нетрекаемого нет
        inf['why'] = [f'только игнорируемое ({len(inf["dirty"])}): ' + ', '.join(sorted({d[3:].rstrip("/") for d in inf["dirty"]})[:3])[:90]]
    if not why:
        inf['verdict'] = 'can' if inf['merged'] else 'maybe'
        if not inf['merged']:
            inf['why'] = ['⚠ ветки нет, HEAD НЕ влит — коммиты живут только здесь']
    return inf


def big_outputs(infos: list, repo: str, r: dict) -> list:
    """Крупные записи вне git внутри рабочих копий (`??`/`!!` ≥ big_mb МБ, кроме node_modules); флаг «ссылка в репозитории» — по имени записи."""
    thr = r['wt']['big_mb'] * 1024 * 1024
    rows = []
    for inf in infos:
        if inf['verdict'] == 'orphan':
            continue
        for c, n in inf.get('entries', []):
            full = os.path.join(inf['path'], n.rstrip('/'))
            if os.path.islink(full) or not os.path.exists(full):
                continue
            total, freed = sizes(full) if os.path.isdir(full) else (os.lstat(full).st_size, os.lstat(full).st_size if os.lstat(full).st_nlink == 1 else 0)
            if total >= thr:
                rows.append({'wt': inf['path'], 'entry': n, 'kind': 'не отслеживается' if c == '??' else 'в .gitignore', 'total': total, 'freed': freed})
    refd = repo_refs(sorted({os.path.basename(x['entry'].rstrip('/')) for x in rows}), repo, r.get('refs_exclude') or []) if rows else set()
    for x in rows:
        x['ref'] = os.path.basename(x['entry'].rstrip('/')) in refd
    rows.sort(key=lambda x: -x['freed'])
    return rows


def worktrees_report(r: dict, repo: str, now: float | None = None, busy=None, as_json: bool = False) -> int:
    now = time.time() if now is None else now
    from concurrent.futures import ThreadPoolExecutor
    wts = list_worktrees(repo, r['src'])
    with ThreadPoolExecutor(max_workers=int(r['wt']['jobs'])) as ex:
        infos = list(ex.map(lambda w: wt_info(w, repo, r, now, busy), wts))
    big = big_outputs(infos, repo, r)
    rev = _git(repo, 'rev-parse', '--short', r['wt']['base'])[1].strip()
    if as_json:
        print(json.dumps({'base': r['wt']['base'], 'base_sha': rev, 'worktrees': [{k: v for k, v in i.items() if k != 'entries'} for i in infos], 'big': big}, ensure_ascii=False, indent=1))
        return 0
    home = os.path.expanduser('~')

    def sh(p):
        return '~' + p[len(home):] if p.startswith(home) else p

    def row(i):
        ref = i['branch'] or f'detached {i["head"][:8]}'
        m = 'да' if i['merged'] else ('в main, не в origin' if i['merged_local'] else 'нет')
        return f'{sh(i["path"])}\t{ref}\t{m}\t{i["freed"] / GB:.2f} ГБ\t' + ('; '.join(i['why']) or 'ВСЁ ЧИСТО')
    print(f'рабочие копии git под {r["src"]}: {len(infos)}; база сравнения {r["wt"]["base"]} = {rev}; сухо, ничего не удалено')
    for title, v in (('МОЖНО СНЯТЬ (`git worktree remove`)', 'can'), ('МОЖНО СНЯТЬ, ЕСЛИ КЭШ ИЗ .gitignore НЕ СЧИТАТЬ (влито; трекаемого и нетрекаемого нет, мешают только `!!`)', 'can_ign'), ('РЕШАЕТ ДИРЕКТОР (ветки нет, коммиты не влиты)', 'maybe'), ('ДЕРЖИМ', 'hold'), ('СИРОТЫ (`git worktree prune`)', 'orphan')):
        part = sorted((i for i in infos if i['verdict'] == v), key=lambda i: -i['freed'])
        tot = sum(i['freed'] for i in part)
        print(f'\n== {title}: {len(part)} шт, освободит {tot / GB:.1f} ГБ\nпуть\tветка/SHA\tвлито\tразмер\tпочему')
        for i in part:
            print(row(i))
    held_gb = sum(x['freed'] for x in big if True)
    print(f'\n== КРУПНЫЕ ВЫХОДЫ ВНУТРИ РАБОЧИХ КОПИЙ (вне git, ≥ {r["wt"]["big_mb"]} МБ): {len(big)} шт, {held_gb / GB:.1f} ГБ\nкопия\tзапись\tчто\tразмер\tссылка в репо')
    for x in big:
        print(f'{sh(x["wt"])}\t{x["entry"]}\t{x["kind"]}\t{x["freed"] / GB:.2f} ГБ\t{"есть" if x["ref"] else "нет"}')
    return 0


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
    if '--worktrees' in argv:
        if apply_:
            print('--worktrees — только сухой список: рабочие копии снимает владелец/директор (`git worktree remove`)', file=sys.stderr)
            return 2
        return worktrees_report(r, repo, as_json='--json' in argv)
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

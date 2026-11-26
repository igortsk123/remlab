#!/usr/bin/env python3
"""НОЧНОЙ ПЕРЕНОС СТАРЫХ ПАПОК ~/remlab-logs НА HDD (T-20261123-35; владелец TG 2227/2230, P-072 «Диск pakardev»).

ЗАЧЕМ. 23.11 диск pakardev дошёл до 100 %: ~/remlab-logs (144 ГБ) — выводы задач, их никто не читает после приёмки, но часть папок — вход чужих
скриптов и планов. Удалять нельзя (вывод пакета ещё нужен как «до» в сравнении), поэтому папка уезжает на /mnt/hdd, а на месте остаётся ссылка.

ЧТО УЕЗЖАЕТ (правила — tools/scout/rules/dev-disk.json → archive): папка первого уровня src, у которой
  • самый свежий файл (и сама папка) старше `days` суток (по умолчанию 5);
  • на её ИМЯ нет ссылок из КОДА (`git grep -F` по имени в `refs_scope`: tools/, app/, lib/, .github/ … — код, правила tools/scout/rules, CI; T-20261124-67) —
    «на неё ссылаются» = остаётся. Упоминание в `.memory_bank/**` (брифы, планы, паспорта, ADR) папку НЕ держит: у неё лишь пометка «упомянута в N доках» (пути из памяти
    продолжают работать — на месте остаётся ссылка). Нет `refs_scope` в правилах — как раньше, весь репозиторий (минус `refs_exclude`);
  • она не вход/выход ЖИВОГО прогона (`live_refs`): путь на неё в командной строке любого живого процесса, держателя heavy-slot (`holder*`, строка cmd=) и реестра
    групп Salad (`holder_registry`: pid → тот же процесс), а также в файлах, названных в этих командных строках (`--rules x.json`, `--inputs …`: `out_root`, `base_root`,
    `shard_inputs_glob`, `--parts-root`, `--catalog` и любые строки-пути внутри; глубина 3; шаблон `sh*` держит все совпавшие папки);
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
  python3 tools/ops/logs_archive.py --days 2         # разовый порог суток (прикинуть, сколько освободит); без --days порог АДАПТИВНЫЙ (ниже)
  python3 tools/ops/logs_archive.py --apply --digest --if-low   # ЧАСОВОЙ запуск: свободно ≥ верхней ступени — выходит сразу, иначе переносит с адаптивным порогом
АДАПТИВНЫЙ ПОРОГ (T-20261124-20, rules archive.adaptive): свободно на диске src < 20 ГБ → days=1, < 25 → 2, иначе archive.days (5). 24.11 днём диск падал
до 14,4 ГБ (старт тяжёлых прогонов закрыт при < 15, dev-disk.json start_min_free_gb) — ночного порога 5 суток не хватало при 5–10 ГБ прогонов в день.
Часовой и ночной запуски не идут вместе (замок на время --apply). Перенос, как и раньше, только rsync со ссылкой на месте; рабочие копии git остаются (worktrees_block).
  python3 tools/ops/logs_archive.py --worktrees-ok   # (или archive.worktrees_block=false в rules) переносить и папки с рабочими копиями git: путь в
                                                     # .git/worktrees/*/gitdir остаётся прежним и через ссылку работает; по умолчанию такие папки остаются
УДАЛЕНИЕ СО ВТОРОГО ДИСКА (T-20261124-67; слово владельца TG 2685/2686 24.11): `--prune-hdd` — папки в `dst`, ПРОЛЕЖАВШИЕ там `hdd_prune.days` суток (14; считается от
самого позднего из: свежий файл внутри, момент переноса = время ссылки на основном диске), КРОМЕ папок, на которые ссылается код (refs_scope), которые держит живой прогон
и которые названы в ДЕЙСТВУЮЩЕМ плане (`.memory_bank/plans/*.md`, `status:` не completed/cancelled; нет `status:` — действующий). Сухо — всегда: список «удалил бы: N папок,
X ГБ» (и в обычном сухом прогоне строка итога). Удаляет только `--prune-hdd --apply` (первый запуск — директор после проверки списка): папку на HDD (shutil.rmtree), затем
висячую ссылку на основном диске (только если она ведёт ровно туда), строка в журнал (что, сколько ГБ). Ссылки, не папки, и всё вне `dst` не трогаются.
ЗАБЫТЫЕ ЖДУНЫ И СЕРВЕРЫ (T-20261126-96/1, правило `archive.stale_holder_hours` = 12, владелец TG 3008): процесс старше порога, чья командная строка — только ожидание (цикл
`while/until … sleep` без тяжёлого внутри) либо `python3 -m http.server`, не держатель heavy-slot, папку от ПЕРЕНОСА не держит (процесс не убивается; строка «забытый ждун/сервер — не
держит: pid, возраст, команда» в выводе и DIGEST). Удаление `--prune-hdd` и снятие рабочих копий держат его, как раньше. Нет ключа в rules — выключено.
ЗАЩИЩЁННОЕ (T-20261125-75/2): `~/remlab-inputs` (входы наборов: копии + MANIFEST.tsv, tools/ops/inputs_check.py) скрипт НЕ ТРОГАЕТ никогда — ни перенос, ни удаление с HDD; `protected_by` (по realpath: совпадает, внутри или родитель)
проверяется у src/dst (отказ, код 2), у каждого кандидата, в move_one и prune_one; правило `archive.protected` только добавляет папки. 25.11 вход комода уехал вместе с папкой логов — входам набора там не место.
Переопределения для проверки: LOGS_ARCHIVE_RULES (файл правил), LOGS_ARCHIVE_REPO (репозиторий для поиска ссылок)."""
from __future__ import annotations

import fnmatch
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
RULES_PATH = os.path.join(ROOT, 'tools', 'scout', 'rules', 'dev-disk.json')
GB = 1024 ** 3
DEFAULTS = {'src': '~/remlab-logs', 'dst': '/mnt/hdd/remlab-logs-arhiv', 'days': 5, 'min_hdd_free_gb': 50, 'never': [], 'worktrees_block': True, 'refs_exclude': [], 'adaptive': [], 'refs_scope': None, 'memory_paths': None, 'hdd_prune': {'days': 14}, 'protected': [],
            'monitor_max_h': None, 'stale_holder_hours': None, 'grow_alert_gb': None, 'grow_window_h': None, 'grow_top': None, 'grow_alert_every_h': None, 'forecast_window_h': None, 'forecast_warn_h': None}   # T-89: нет ключа в rules — наблюдатели держат как прежде, сторож роста выключен (чисел порогов в коде нет — они в dev-disk.json)
PROTECTED_DEFAULT = ['~/remlab-inputs']   # входы наборов (T-20261125-75/2): не переносить, не удалять; правило `archive.protected` только ДОБАВЛЯЕТ папки


WT_DEFAULTS = {'idle_h': 12, 'big_mb': 200, 'base': 'origin/main', 'jobs': 4}


def free_gb(path: str) -> float:
    """Свободно на диске, где лежит path (ГБ, доступное обычному пользователю — как видит `df`)."""
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize / GB


def effective_days(r: dict, free: float) -> tuple[float, str]:
    """Адаптивный порог суток (T-20261124-20): чем меньше свободно, тем свежее папки уезжают. `archive.adaptive` = [{free_lt_gb, days}, …]:
    берётся ступень с САМЫМ малым free_lt_gb, под которую подходит `free` (свободно < free_lt_gb); иначе — обычное `days` правила. Порог только
    СНИЖАЕТ days (min), поднять выше обычного правила ступень не может. Возвращает (сутки, пояснение)."""
    base = float(r['days'])
    steps = sorted(((float(s['free_lt_gb']), float(s['days'])) for s in (r.get('adaptive') or [])), key=lambda x: x[0])
    for lt, d in steps:
        if free < lt:
            return min(d, base), f'свободно {free:.1f} ГБ < {lt:g}: адаптивный порог {min(d, base):g} сут (обычный {base:g})'
    return base, f'свободно {free:.1f} ГБ: обычный порог {base:g} сут'


def top_free_lt(r: dict) -> float:
    """Верхняя граница адаптивных ступеней (свободно ≥ неё — ночного порога достаточно); 0 — ступеней нет."""
    return max((float(s['free_lt_gb']) for s in (r.get('adaptive') or [])), default=0.0)


def lock_path() -> str:
    return os.environ.get('LOGS_ARCHIVE_LOCK') or os.path.join(tempfile.gettempdir(), 'remlab-logs-archive.lock')


def take_lock():
    """Эксклюзивный замок на время переноса: часовой и ночной запуски не идут вместе (rsync одной папки из двух процессов). None — замок занят."""
    import fcntl
    f = open(lock_path(), 'a+')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


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
    out['protected'] = list(PROTECTED_DEFAULT) + [x for x in (out.get('protected') or []) if x not in PROTECTED_DEFAULT]
    return out


def protected_by(path: str, r: dict) -> str:
    """Защищённая папка (~/remlab-inputs и `archive.protected`), с которой path совпадает, лежит в ней ИЛИ содержит её (родитель) — по realpath; нет — ''.
    Такой путь ни переносу на HDD, ни удалению с HDD, ни src/dst не подходит: входы наборов (MANIFEST, sha) должны лежать на месте (25.11: вход комода уехал вместе с папкой логов)."""
    rp = os.path.realpath(os.path.expanduser(path))
    for x in list(PROTECTED_DEFAULT) + list(r.get('protected') or []):
        root = os.path.realpath(os.path.expanduser(x))
        if rp == root or rp.startswith(root + os.sep) or root.startswith(rp.rstrip(os.sep) + os.sep):
            return root
    return ''


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


def repo_refs(names: list, repo: str, exclude: list | None = None, scope: list | None = None) -> set:
    """Какие из имён встречаются в отслеживаемых файлах репозитория (один `git grep -o -F -f`: печатает найденные подстроки); `scope` — только эти пути (код), иначе весь репозиторий."""
    if not names:
        return set()
    with tempfile.NamedTemporaryFile('w', suffix='.pat', delete=False) as f:
        f.write('\n'.join(names) + '\n')
        pat = f.name
    try:
        r = subprocess.run(['git', '-C', repo, 'grep', '-h', '-o', '-F', '-f', pat, '--'] + list(scope or ['.']) + [f':(exclude){x}' for x in (exclude or [])], capture_output=True, text=True, timeout=300)
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


# ───────────── забытые наблюдатели (T-20261125-89, владелец TG 2769) ─────────────
# `tail -F x.log | grep …` с позавчера держал папку как «живой прогон»: открытый файл/путь в командной строке. Наблюдатель старше `archive.monitor_max_h` часов папку НЕ держит
# (процесс не убиваем; в отчёт — строка «наблюдатель старше N ч — не держит»). Порог — только из rules (None — выключено: держит, как раньше).
MONITOR_MAX_H = None                                   # ставит main() из rules; параметр monitor_max_h функций перекрывает
MONITOR_NOTES: list = []                               # строки «наблюдатель … не держит» за этот запуск (main печатает)
MONITOR_PIPE = ('grep', 'egrep', 'fgrep', 'awk', 'sed', 'stdbuf', 'head', 'cut', 'tr')   # что может стоять в трубе после tail
_TAIL_FOLLOW = re.compile(r'^(-(?!-)[A-Za-z0-9]*[fF][A-Za-z0-9]*|--follow(=.*)?)$')


def is_monitor_cmd(args: list) -> bool:
    """Командная строка — ТОЛЬКО `tail -f|-F …` (в `bash -c` — вся строка) и, возможно, труба в grep/awk/sed/…: чистый наблюдатель, ничего не пишет и не считает.
    Любое `;` `&&` `$(` `` ` `` `>` (кроме `2>&1`) — не наблюдатель (осторожно: такой процесс держит как прежде)."""
    if not args:
        return False
    if os.path.basename(args[0]) in ('bash', 'sh', 'dash', 'zsh'):
        ci = next((k for k, a in enumerate(args[1:], 1) if re.fullmatch(r'-[a-z]*c[a-z]*', a)), None)
        if ci is None or ci + 1 >= len(args):
            return False
        line = args[ci + 1]
    else:
        line = ' '.join(shlex.quote(a) for a in args)
    line = line.replace('2>&1', ' ')
    if re.search(r'[;&><`]|\$\(', line):
        return False
    try:
        lex = shlex.shlex(line, posix=True, punctuation_chars='|')
        lex.whitespace_split = True
        toks = list(lex)
    except ValueError:
        return False
    segs: list = [[]]
    for t in toks:
        if t == '|':
            segs.append([])
        elif set(t) == {'|'}:
            return False                                   # `||` — не труба
        else:
            segs[-1].append(t)
    if any(not s for s in segs):
        return False
    for i, s in enumerate(segs):
        k = 0
        while k < len(s) and (os.path.basename(s[k]) == 'stdbuf' or (k and s[k - 1] == 'stdbuf' and s[k].startswith('-'))):
            k += 1                                         # `stdbuf -oL tail -F …`
        if k >= len(s):
            return False
        exe = os.path.basename(s[k])
        if i == 0:
            if exe != 'tail' or not any(_TAIL_FOLLOW.match(a) for a in s[k + 1:]):
                return False
        elif exe not in MONITOR_PIPE:
            return False
    return True


def proc_age_h(pid: str, proc_root: str = '/proc', now: float | None = None) -> float | None:
    """Возраст процесса в часах (starttime из /proc/<pid>/stat + btime из /proc/stat); не прочитать — None (тогда процесс считается свежим)."""
    try:
        st = open(f'{proc_root}/{pid}/stat', encoding='utf-8', errors='replace').read()
        rest = st[st.rindex(')') + 2:].split()
        start_ticks = int(rest[19])
        btime = next(int(ln.split()[1]) for ln in open(f'{proc_root}/stat', encoding='utf-8') if ln.startswith('btime '))
        return ((time.time() if now is None else now) - (btime + start_ticks / os.sysconf('SC_CLK_TCK'))) / 3600
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def stale_monitor(pid: str, args: list, proc_root: str = '/proc', monitor_max_h: float | None = None) -> str:
    """'' — не наблюдатель или ещё свежий; иначе строка-пояснение «наблюдатель старше N ч — не держит» (и в MONITOR_NOTES, один раз на pid)."""
    mh = MONITOR_MAX_H if monitor_max_h is None else monitor_max_h
    if mh is None or not is_monitor_cmd(args):
        return ''
    age = proc_age_h(pid, proc_root)
    if age is None or age <= float(mh):
        return ''
    line = f'наблюдатель старше {float(mh):g} ч — не держит: pid {pid} ({age:.0f} ч): {" ".join(args)[:90]}'
    if not any(f'pid {pid} ' in n for n in MONITOR_NOTES):
        MONITOR_NOTES.append(line)
    return line


# ───────────── забытые ждуны и пробные серверы (T-20261126-96/1; владелец TG 3006→3008 «2. да», решение Fable 26.11) ─────────────
# 26.11 три забытых процесса 1,7–2,7 суток держали 14 ГБ: два цикла-«ждуна» файла, который уже не появится (`while [ ! -f … ]; do sleep`, `until grep … ; do sleep`), и пробный
# `python3 -m http.server` с рабочей папкой внутри. Процесс старше `archive.stale_holder_hours` часов, чья командная строка — ТОЛЬКО ожидание (цикл while/until … sleep, где в
# цикле и после него стоят лишь «лёгкие» команды из WAIT_OK; ни python/node/blender/…, ни записи в файлы) либо `python3 -m http.server`, и который не держатель heavy-slot (и не его
# потомок), папку от ПЕРЕНОСА на HDD НЕ держит. Процесс не убиваем; в отчёт и DIGEST — «забытый ждун/сервер — не держит: pid, возраст, команда». Послабление — ТОЛЬКО для переноса:
# `--prune-hdd` (удаление), worktree_prune и снятие рабочих копий держат такой процесс, как раньше (stale_h не передают). Дочерний `sleep N` ждуна (тот же cwd, всегда «свежий») — тоже не держит.
# Порог — только из rules (None — выключено: держит, как раньше). Условие «в папке нет новых файлов за эти часы» уже даёт `days` (≥ 1 сут > 12 ч).
STALE_NOTES: list = []                                  # строки «забытый ждун/сервер — не держит» за этот запуск (main печатает и кладёт в DIGEST)
WAIT_OK = frozenset({'sleep', 'test', '[', '[[', 'ls', 'wc', 'cat', 'grep', 'egrep', 'fgrep', 'pgrep', 'pidof', 'date', 'echo', 'printf', 'cut', 'tr', 'head', 'tail', 'sort', 'uniq',
                     'stat', 'cd', 'true', 'false', ':', 'basename', 'dirname', 'nproc', 'hostname', 'uptime', 'ps', 'du', 'df', 'touch', 'continue', 'break', 'sed'})   # только читают и ждут: данных не пишут, тяжёлого не считают (`sed` — без -i; `touch` — пустой файл)
_WAIT_KW = frozenset({'while', 'until', 'do', 'done', 'if', 'then', 'else', 'elif', 'fi', '!', '{', '}'})
_OK_REDIR = re.compile(r'(?:\d?>>?\s*/dev/null|&>\s*/dev/null|2>&1)')
_ASSIGN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')


def _wait_segments(line: str) -> list | None:
    """Простые команды строки (токены) — подстановки $(…) раскрыты в свои команды; None — разобрать нельзя или есть запись/ввод из файла (не ждун)."""
    line = _OK_REDIR.sub(' ', line)
    line = re.sub(r'\$\(\([^()]*\)\)', 'X', line)          # арифметика $((N+1)) — не команда (заглушка X без пробелов: `N=$(…)` остаётся присваиванием)
    inner: list = []
    while True:                                            # $(…) без вложенности: внутреннее — отдельные команды, на месте — заглушка
        new = re.sub(r'\$\(([^()]*)\)', lambda m: (inner.append(m.group(1)), 'X')[1], line)
        if new == line:
            break
        line = new
    if '$(' in line or '`' in line or '>' in line or re.search(r'<<|<\(', line):
        return None                                        # запись в файл, heredoc, подстановка процесса, вложенные $(…) — не ждун; чтение `< файл` (wc -l < f) допустимо
    segs: list = []
    for text in [line] + inner:
        try:
            lex = shlex.shlex(text, posix=True, punctuation_chars=';&|()')
            lex.whitespace_split = True
            toks = list(lex)
        except ValueError:
            return None
        cur: list = []
        for t in toks:
            if set(t) <= set(';&|()'):
                if cur:
                    segs.append(cur)
                cur = []
            else:
                cur.append(t)
        if cur:
            segs.append(cur)
    return segs


def is_wait_cmd(args: list) -> str:
    """'ждун' — командная строка только ждёт (цикл while/until … sleep N, всё внутри и после — из WAIT_OK, без записи в файлы; `bash -c "…"`, в том числе после `timeout N`);
    'сервер' — `python3 -m http.server …` (не `--cgi`); '' — всё остальное (осторожно: такой процесс держит как прежде)."""
    args = list(args)
    if len(args) > 2 and os.path.basename(args[0]) == 'timeout':
        args = args[2:]
    if not args:
        return ''
    exe = os.path.basename(args[0]).lstrip('-')
    if re.fullmatch(r'python[0-9.]*', exe):
        i = 1
        while i < len(args) and args[i].startswith('-') and args[i] != '-m':
            i += 1
        if i + 1 < len(args) and args[i] == '-m' and args[i + 1] == 'http.server' and '--cgi' not in args:
            return 'сервер'
        return ''
    if exe not in ('bash', 'sh', 'dash', 'zsh'):
        return ''
    ci = next((k for k, a in enumerate(args[1:], 1) if re.fullmatch(r'-[a-z]*c[a-z]*', a)), None)
    if ci is None or ci + 1 >= len(args) or not re.search(r'\b(while|until)\b', args[ci + 1]) or not re.search(r'\bsleep\b', args[ci + 1]):
        return ''
    segs = _wait_segments(args[ci + 1])
    if not segs:
        return ''
    loop = slept = False
    for s in segs:
        k = 0
        while k < len(s) and (s[k] in _WAIT_KW or _ASSIGN.match(s[k])):
            loop = loop or s[k] in ('while', 'until')
            k += 1
        if k >= len(s):
            continue
        if s[k] == 'for':
            continue                                       # `for f in список` — заголовок цикла, сам ничего не запускает
        cmd = os.path.basename(s[k])
        if cmd not in WAIT_OK:
            return ''                                      # в строке есть что-то кроме ожидания и чтения (python, rm, mv, node …) — не ждун
        if cmd == 'tail' and any(_TAIL_FOLLOW.match(a) for a in s[k + 1:]):
            return ''                                      # tail -f внутри цикла — не ожидание файла
        if cmd == 'sed' and any(re.fullmatch(r'-[A-Za-z]*i[A-Za-z]*|--in-place.*', a) for a in s[k + 1:]):
            return ''                                      # sed -i пишет в файл
        slept = slept or cmd == 'sleep'
    return 'ждун' if loop and slept else ''


def _ppid(pid: str, proc_root: str) -> str:
    try:
        st = open(f'{proc_root}/{pid}/stat', encoding='utf-8', errors='replace').read()
        return st[st.rindex(')') + 2:].split()[1]
    except (OSError, ValueError, IndexError):
        return ''


def stale_waiters(pids: list, proc_root: str = '/proc', stale_h: float | None = None, heavy_dir: str | None = None) -> set:
    """Множество pid забытых ждунов/серверов старше stale_h часов, не держателей heavy-slot (и не их потомков), плюс их прямые потомки (`sleep N` в цикле держит cwd ждуна).
    Пусто — порога нет или таких нет. Строки «не держит» — в STALE_NOTES (один раз на pid)."""
    if stale_h is None:
        return set()
    heavy = {pid for pid, _lb, _ar in holder_cmds(proc_root, heavy_dir)}
    out: set = set()
    for p in pids:
        try:
            args = [a.decode('utf-8', 'replace') for a in open(f'{proc_root}/{p}/cmdline', 'rb').read().split(b'\0') if a]
        except OSError:
            continue
        kind = is_wait_cmd(args) if args else ''
        if not kind:
            continue
        age = proc_age_h(p, proc_root)
        if age is None or age <= float(stale_h):
            continue
        q, hit = p, False
        for _ in range(12):                                # держатель heavy-slot — он сам или предок: держит всегда
            if q in heavy:
                hit = True
                break
            q = _ppid(q, proc_root)
            if not q or q == '0':
                break
        if hit:
            continue
        out.add(p)
        if not any(f'pid {p} ' in n for n in STALE_NOTES):
            STALE_NOTES.append(f'забытый ждун/сервер — не держит: pid {p} ({age:.0f} ч, {kind}): {" ".join(args)[:90]}')
    if out:
        for p in pids:
            if p not in out and _ppid(p, proc_root) in out:
                out.add(p)                                 # `sleep N` из цикла-ждуна: тот же cwd, возраст секунды — но это не отдельный процесс
    return out


def proc_snapshot(proc_root: str = '/proc', monitor_max_h: float | None = None, holders: bool = False, heavy_dir: str | None = None, stale_h: float | None = None) -> list:
    """ОДНА реализация «что держит папки» (T-89: busy_by и worktree_prune — это она): [{pid, cwd, cmd, fds, pypath, holder}] по всем видимым процессам (кроме себя, забытых
    наблюдателей tail старше monitor_max_h и — только если задан stale_h, то есть при переносе — забытых ждунов/серверов старше stale_h): cwd, командная строка, открытые файлы,
    PYTHONPATH из /proc/<pid>/environ (виден только свой пользователь); holders=True добавляет живых держателей heavy-slot (их cmd=). Один обход /proc на любое число папок."""
    snap: list = []
    me = os.getpid()
    try:
        pids = [p for p in os.listdir(proc_root) if p.isdigit() and int(p) != me]
    except OSError:
        pids = []
    stale = stale_waiters(pids, proc_root, stale_h, heavy_dir)
    for p in pids:
        if p in stale:
            continue                                            # забытый ждун/сервер (и его sleep) не держит перенос
        base = f'{proc_root}/{p}'
        try:
            raw = open(f'{base}/cmdline', 'rb').read()
        except OSError:
            raw = b''
        if raw and stale_monitor(p, [a.decode('utf-8', 'replace') for a in raw.split(b'\0') if a], proc_root, monitor_max_h):
            continue                                            # забытый наблюдатель не держит
        e = {'pid': p, 'cwd': '', 'cmd': raw.replace(b'\0', b' ').decode('utf-8', 'replace'), 'fds': [], 'pypath': [], 'holder': ''}
        try:
            e['cwd'] = os.readlink(f'{base}/cwd')
        except OSError:
            pass
        try:
            for fd in os.listdir(f'{base}/fd'):
                try:
                    t = os.readlink(f'{base}/fd/{fd}')
                except OSError:
                    continue
                if t.startswith('/'):
                    e['fds'].append(t)
        except OSError:
            pass
        try:
            for kv in open(f'{base}/environ', 'rb').read().split(b'\0'):
                if kv.startswith(b'PYTHONPATH='):
                    e['pypath'] = [x for x in kv[11:].decode('utf-8', 'replace').split(':') if x.startswith('/')]
        except OSError:
            pass
        snap.append(e)
    if holders:
        for pid, label, args in holder_cmds(proc_root, heavy_dir):
            snap.append({'pid': pid, 'cwd': '', 'cmd': ' '.join(args), 'fds': [], 'pypath': [], 'holder': label})
    return snap


def held_in(path: str, snap: list) -> str:
    """Что из снимка держит папку: cwd внутри, её путь в командной строке, открытый файл внутри, PYTHONPATH внутри (код грузится из этой копии). '' — никто."""
    for real in {os.path.realpath(path), os.path.abspath(path)}:
        pref = real.rstrip('/') + '/'
        for e in snap:
            who = (f'держатель heavy-slot «{e["holder"]}»' if e['holder'] else f'pid {e["pid"]}')
            if e['cwd'] == real or e['cwd'].startswith(pref):
                return f'{who}: cwd внутри'
            if pref in e['cmd'] or e['cmd'].rstrip().endswith(real):
                return f'{who}: в командной строке'
            if any(t == real or t.startswith(pref) for t in e['fds']):
                return f'{who}: открыт файл внутри'
            if any(x == real or x.startswith(pref) for x in e['pypath']):
                return f'{who}: PYTHONPATH внутри'
    return ''


def busy_by(path: str, proc_root: str = '/proc', monitor_max_h: float | None = None, stale_h: float | None = None, heavy_dir: str | None = None) -> str:
    """Что держит папку: процесс с cwd/открытым файлом внутри, её именем в командной строке или PYTHONPATH внутри (свои процессы тоже). '' — никто.
    Забытый наблюдатель (`tail -F … | grep`, старше monitor_max_h) не держит; при stale_h (только перенос) не держит и забытый ждун/сервер старше stale_h часов."""
    return held_in(path, proc_snapshot(proc_root, monitor_max_h, heavy_dir=heavy_dir, stale_h=stale_h))


def memory_mentions(names: list, repo: str, paths: list | None = None) -> dict:
    """{имя: в скольких файлах памяти упомянуто} — только пометка в отчёте, папку не держит. Один `git grep -o -H -F -f`; сбой — пусто."""
    if not names:
        return {}
    with tempfile.NamedTemporaryFile('w', suffix='.pat', delete=False) as f:
        f.write('\n'.join(names) + '\n')
        pat = f.name
    try:
        r = subprocess.run(['git', '-C', repo, 'grep', '-o', '-H', '-F', '-f', pat, '--'] + list(paths or ['.memory_bank']), capture_output=True, text=True, timeout=300)
        files: dict = {}
        for ln in r.stdout.splitlines():
            fn, _, hit = ln.partition(':')
            if hit.strip():
                files.setdefault(hit.strip(), set()).add(fn)
        return {n: len(v) for n, v in files.items()}
    except (OSError, subprocess.SubprocessError):
        return {}
    finally:
        try:
            os.unlink(pat)
        except OSError:
            pass


# ───────────── что держит папку: живой прогон (T-20261124-67) ─────────────
LIVE_SUFFIX = ('.json', '.txt', '.tsv', '.csv', '.sh', '.yml', '.yaml', '.cfg', '.toml')   # файлы из командной строки, внутри которых ищем пути
LIVE_MAX_BYTES, LIVE_MAX_FILES, LIVE_DEPTH, GLOB_CH = 2_000_000, 300, 3, '*?['


def _expand(x: str) -> str:
    return os.path.expanduser(os.path.expandvars(x))


def src_regex(src: str) -> re.Pattern:
    """Путь на папку первого уровня src в любой записи: полный, через ~ и через $HOME. Группа 1 — имя папки (может быть шаблоном с * ? [)."""
    exp = os.path.expanduser(src).rstrip('/')
    forms = {exp, os.path.realpath(exp), src.rstrip('/')}
    home = os.path.expanduser('~').rstrip('/')
    for f in list(forms):
        if f.startswith(home + '/'):
            rel = f[len(home) + 1:]
            forms |= {'~/' + rel, '$HOME/' + rel, '${HOME}/' + rel}
    alt = '|'.join(re.escape(f) for f in sorted(forms, key=len, reverse=True))
    return re.compile('(?:' + alt + r")/([^/\s\"'`{}:,;()<>|\\]+)")


def hold_of(name: str, live: dict) -> str:
    """Причина, по которой живой прогон держит папку `name` ('' — не держит). Ключ live — имя или шаблон (`sh*`)."""
    for pat, why in live.items():
        if pat == name or (any(c in pat for c in GLOB_CH) and fnmatch.fnmatchcase(name, pat)):
            return why
    return ''


def _file_refs(path: str, rx: re.Pattern, out: dict, why: str, seen: set, depth: int) -> None:
    """Пути на src внутри текстового файла (и внутри файлов, на которые он ссылается; глубина LIVE_DEPTH, потолок LIVE_MAX_FILES файлов)."""
    if depth <= 0 or path in seen or len(seen) >= LIVE_MAX_FILES:
        return
    seen.add(path)
    try:
        st = os.stat(path)
        if not stat.S_ISREG(st.st_mode) or st.st_size > LIVE_MAX_BYTES:
            return
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return
    for m in rx.finditer(text):
        out.setdefault(m.group(1), why)
    for tok in set(re.findall(r"[~$/][^\s\"'`,;()<>|\[\]{}*?]+", text)):
        q = _expand(tok)
        if q.endswith(LIVE_SUFFIX) and os.path.isfile(q):
            _file_refs(q, rx, out, why + ' → ' + os.path.basename(q), seen, depth - 1)


def live_refs(src: str, proc_root: str = '/proc', heavy_dir: str | None = None, monitor_max_h: float | None = None, stale_h: float | None = None) -> dict:
    """{имя папки или шаблон: причина} — что сейчас вход/выход живого прогона. Источники: командная строка КАЖДОГО живого процесса (в том числе держателя heavy-slot и
    процесса из реестра групп Salad — это те же процессы), строка `cmd=` в `holder*` heavy-slot, файлы, названные в этих командных строках (правила `--rules x.json`, списки
    входов): любая строка-путь на src внутри (out_root, base_root, shard_inputs_glob, parts_root, catalog …) — и файлы, на которые они ссылаются. Ничего не читает вне этого."""
    rx = src_regex(src)
    out: dict = {}
    seen: set = set()
    me = str(os.getpid())

    def scan(pid: str, args: list, cwd: str, tag: str) -> None:
        line = ' '.join(args)
        why = f'{tag} pid {pid}: {line[:90]}'
        for m in rx.finditer(line):
            out.setdefault(m.group(1), why + ' (командная строка)')
        for a in args[1:]:
            a = a.split('=', 1)[1] if a.startswith('--') and '=' in a else a
            fp = _expand(a)
            if cwd and not os.path.isabs(fp):
                fp = os.path.join(cwd, fp)
            if fp.endswith(LIVE_SUFFIX) and os.path.isfile(fp):
                _file_refs(fp, rx, out, why + ' → ' + os.path.basename(fp), seen, LIVE_DEPTH)

    try:
        pids = [x for x in os.listdir(proc_root) if x.isdigit() and x != me]
    except OSError:
        pids = []
    stale = stale_waiters(pids, proc_root, stale_h, heavy_dir)         # только при переносе (stale_h): забытый ждун/сервер — не вход и не выход прогона
    for pid in pids:
        if pid in stale:
            continue
        try:
            raw = open(f'{proc_root}/{pid}/cmdline', 'rb').read()
        except OSError:
            continue
        args = [a.decode('utf-8', 'replace') for a in raw.split(b'\0') if a]
        if not args:
            continue
        if stale_monitor(pid, args, proc_root, monitor_max_h):      # забытый `tail -F … | grep` старше monitor_max_h: не вход и не выход прогона
            continue
        try:
            cwd = os.readlink(f'{proc_root}/{pid}/cwd')
        except OSError:
            cwd = ''
        scan(pid, args, cwd, 'процесс')
    for pid, label, args in holder_cmds(proc_root, heavy_dir):     # держатели heavy-slot: их cmd= (запись живёт, пока жив держатель)
        scan(pid, args, '', f'держатель heavy-slot «{label}»')
    return out


def holder_cmds(proc_root: str = '/proc', heavy_dir: str | None = None) -> list:
    """[(pid, label, args)] живых держателей heavy-slot (файлы `holder*` в HEAVY_SLOT_DIR: pid=, label=, cmd=). Общий источник для live_refs и worktree_prune."""
    hd = heavy_dir if heavy_dir is not None else os.path.expanduser(os.environ.get('HEAVY_SLOT_DIR') or '~/.cache/remlab-heavy-slot')
    try:
        files = sorted(f for f in os.listdir(hd) if f.startswith('holder') and '.tmp' not in f)
    except OSError:
        files = []
    res = []
    for f in files:
        kv: dict = {}
        try:
            for ln in open(os.path.join(hd, f), encoding='utf-8', errors='replace'):
                k, _, v = ln.rstrip('\n').partition('=')
                kv[k] = v
        except OSError:
            continue
        pid, cmd = kv.get('pid', ''), kv.get('cmd', '')
        if pid.isdigit() and cmd and os.path.exists(f'{proc_root}/{pid}'):
            try:
                args = shlex.split(cmd)
            except ValueError:
                args = cmd.split()
            res.append((pid, kv.get('label', ''), args))
    return res


# ───────────── удаление со второго диска (T-20261124-67) ─────────────
ACTIVE_NOT = ('completed', 'cancelled', 'canceled', 'done', 'archived')


def active_plan_files(repo: str) -> list:
    """Файлы `.memory_bank/plans/*.md` с `status:` не из закрытых (нет `status:` — действующий)."""
    d = os.path.join(repo, '.memory_bank', 'plans')
    out = []
    try:
        fns = sorted(f for f in os.listdir(d) if f.endswith('.md'))
    except OSError:
        return []
    for f in fns:
        try:
            head = ''.join(open(os.path.join(d, f), encoding='utf-8', errors='replace').readlines()[:40])
        except OSError:
            continue
        m = re.search(r'^status:\s*[\'"]?([\w-]+)', head, re.M)
        if not m or m.group(1).lower() not in ACTIVE_NOT:
            out.append(os.path.join(d, f))
    return out


def plan_mentions(names: list, repo: str) -> dict:
    """{имя: файл действующего плана, где оно названо}."""
    hit: dict = {}
    for fp in active_plan_files(repo):
        try:
            text = open(fp, encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for n in names:
            if n not in hit and n in text:
                hit[n] = os.path.basename(fp)
    return hit


def moved_at(r: dict, name: str, path: str) -> float:
    """Когда папка попала на HDD: время ссылки на основном диске (создаётся при переносе); нет ссылки — ctime папки на HDD (rsync -a сохраняет mtime, ctime — момент записи)."""
    link = os.path.join(os.path.expanduser(r['src']), name)
    try:
        if os.path.islink(link):
            return os.lstat(link).st_mtime
        return os.stat(path).st_ctime
    except OSError:
        return time.time()


def hdd_candidates(r: dict, repo: str, now: float | None = None, refs=None, live=None, plans=None) -> tuple[list, list]:
    """(удалил бы с HDD, оставляю с причинами). Запись: {name, path, total, age_d}. Возраст — от самого позднего: свежий файл внутри / момент переноса."""
    now = time.time() if now is None else now
    hp = r.get('hdd_prune') or {}
    days = float(hp.get('days', 14))
    cutoff = now - days * 86400
    dst = os.path.expanduser(r['dst'])
    try:
        names = sorted(n for n in os.listdir(dst) if not n.startswith('.'))
    except OSError:
        return [], []
    dirs, skipped = [], []
    for n in names:
        p = os.path.join(dst, n)
        if os.path.islink(p) or not os.path.isdir(p):
            continue
        if n in (r.get('never') or []):
            skipped.append((n, 'в never'))
            continue
        hit = protected_by(p, r)
        if hit:
            skipped.append((n, f'защищено ({hit}): входы наборов'))
            continue
        if newest_mtime(p, floor=cutoff) >= cutoff or moved_at(r, n, p) >= cutoff:
            skipped.append((n, f'лежит на HDD меньше {days:g} сут или менялась'))
            continue
        dirs.append(n)
    scope = r.get('refs_scope')
    code = refs(dirs, repo) if refs else repo_refs(dirs, repo, r.get('refs_exclude') or [], scope)
    lv = live() if live else live_refs(r['src'])
    pm = plans(dirs, repo) if plans else plan_mentions(dirs, repo)
    todo = []
    for n in dirs:
        if n in code:
            skipped.append((n, 'на имя ссылается код/правила/CI'))
            continue
        why = hold_of(n, lv)
        if why:
            skipped.append((n, f'вход/выход живого прогона: {why}'))
            continue
        if n in pm:
            skipped.append((n, f'названа в действующем плане {pm[n]}'))
            continue
        p = os.path.join(dst, n)
        total, _ = sizes(p)
        todo.append({'name': n, 'path': p, 'total': total, 'age_d': round((now - max(newest_mtime(p), moved_at(r, n, p))) / 86400, 1)})
    return todo, skipped


def prune_one(c: dict, r: dict, now: float | None = None, live=None) -> tuple[bool, str]:
    """Удаление одной папки на HDD: перепроверка (внутри dst, не ссылка, не стала живой/свежей) → rmtree → висячая ссылка на основном диске (только ведущая ровно сюда)."""
    n, p = c['name'], c['path']
    dst = os.path.realpath(os.path.expanduser(r['dst']))
    now = time.time() if now is None else now
    if len(dst.strip('/').split('/')) < 2:
        return False, f'❗ {n}: dst {dst!r} слишком короткий — отказ'
    hit = protected_by(p, r)
    if hit:
        return False, f'❗ {n}: защищено ({hit}) — отказ удалять'
    if os.path.islink(p) or not os.path.isdir(p) or os.path.dirname(os.path.realpath(p)) != dst:
        return False, f'{n}: не папка прямо в {dst} — пропуск'
    days = float((r.get('hdd_prune') or {}).get('days', 14))
    if newest_mtime(p, floor=now - days * 86400) >= now - days * 86400:
        return False, f'{n}: появился свежий файл — пропуск'
    why = hold_of(n, (live or (lambda: live_refs(r['src'])))())
    if why:
        return False, f'{n}: стала входом живого прогона ({why}) — пропуск'
    shutil.rmtree(p)
    link = os.path.join(os.path.expanduser(r['src']), n)
    note = ''
    if os.path.islink(link) and os.path.realpath(link) == os.path.realpath(p) or (os.path.islink(link) and os.readlink(link) == p):
        os.unlink(link)
        note = ', висячая ссылка убрана'
    return True, f'{n}: удалено с HDD ({c["total"] / GB:.2f} ГБ){note}'


def candidates(r: dict, repo: str, now: float | None = None, refs=None, busy=None, live=None, docs=None) -> tuple[list, list]:
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
        hit = protected_by(p, r)
        if hit:
            skipped.append((n, f'защищено ({hit}): входы наборов'))
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
    referenced = refs(dirs, repo) if refs else repo_refs(dirs, repo, r.get('refs_exclude') or [], r.get('refs_scope'))
    sh = r.get('stale_holder_hours')                                 # T-96/1: забытый ждун/сервер не держит ПЕРЕНОС (не удаление с HDD); нет порога — вызовы ровно как раньше
    kw = {} if sh is None else {'stale_h': sh}
    lv = live() if live else live_refs(r['src'], **kw)               # вход/выход живого прогона — вне зависимости от возраста и памяти
    dm = docs(dirs, repo) if docs else (memory_mentions([n for n in dirs if n not in referenced], repo, r.get('memory_paths')) if r.get('refs_scope') else {})
    todo = []
    for n in dirs:
        p = os.path.join(src, n)
        if n in referenced:
            skipped.append((n, 'на имя есть ссылка в репозитории'))
            continue
        held = hold_of(n, lv)
        if held:
            skipped.append((n, f'вход/выход живого прогона: {held}'))
            continue
        who = (busy or (lambda q: busy_by(q, **kw)))(p)
        if who:
            skipped.append((n, f'занята: {who}'))
            continue
        total, freed = sizes(p)
        todo.append({'name': n, 'path': p, 'total': total, 'freed': freed, 'age_d': round((now - newest_mtime(p)) / 86400, 1), 'docs': dm.get(n, 0)})
    return todo, skipped


def hdd_free_gb(dst: str) -> float:
    d = dst
    while d and not os.path.exists(d):
        d = os.path.dirname(d)
    st = os.statvfs(d or '/')
    return st.f_bavail * st.f_frsize / GB


def move_one(c: dict, r: dict, now: float | None = None, busy=None, rsync=None, live=None) -> tuple[bool, str]:
    """Перенос одной папки: перепроверка → rsync → пустые каталоги → ссылка. (успех, строка). Данные удаляет только rsync после успешной копии."""
    p, n, dst = c['path'], c['name'], r['dst']
    now = time.time() if now is None else now
    hit = protected_by(p, r)
    if hit:
        return False, f'❗ {n}: защищено ({hit}) — отказ переносить'
    if os.path.islink(p) or not os.path.isdir(p):
        return False, f'{n}: уже не папка — пропуск'
    if newest_mtime(p, floor=now - float(r['days']) * 86400) >= now - float(r['days']) * 86400:
        return False, f'{n}: появился свежий файл — пропуск'
    sh = r.get('stale_holder_hours')                                  # T-96/1: перенос — забытый ждун/сервер не держит; нет порога — вызовы как раньше
    kw = {} if sh is None else {'stale_h': sh}
    who = (busy or (lambda q: busy_by(q, **kw)))(p)
    if who:
        return False, f'{n}: занята ({who}) — пропуск'
    held = hold_of(n, (live or (lambda: live_refs(r['src'], **kw)))())
    if held:
        return False, f'{n}: стала входом живого прогона ({held}) — пропуск'
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


# ───────────── сторож роста (T-20261125-89, владелец TG 2769) ─────────────
# 25.11 прогоны писали ≈45 ГБ за сутки (полные меши и кадры на каждый вариант), архив берёт только старше суток — диск упал до 11 ГБ. Раз в час снимок размеров папок src; за окно
# `grow_window_h` суммарный РОСТ (сумма положительных приростов по папкам: перенос/удаление других папок рост не скрывают) больше `grow_alert_gb` — WARN:disk_grow с тремя самыми
# растущими папками (имя задачи). Повтор тревоги — не чаще `grow_alert_every_h`. Пороги — только из rules (`archive.grow_*`); нет `grow_alert_gb` — сторож выключен.
def growth_state_path() -> str:
    return os.environ.get('LOGS_GROWTH_STATE') or os.path.expanduser('~/.cache/remlab-logs-growth/snap.json')


def du_children(src: str, timeout: int = 1800) -> dict:
    """{имя папки: байт} — размеры папок первого уровня src (ссылки на HDD не раскрываем, скрытые не считаем). Один `du`: жёсткая ссылка между папками считается один раз."""
    try:
        names = sorted(n for n in os.listdir(src) if not n.startswith('.') and os.path.isdir(os.path.join(src, n)) and not os.path.islink(os.path.join(src, n)))
    except OSError:
        return {}
    out: dict = {}
    for i in range(0, len(names), 200):
        chunk = names[i:i + 200]
        try:
            res = subprocess.run(['du', '-sB1', '--', *chunk], cwd=src, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            continue
        for ln in res.stdout.splitlines():
            sz, _, nm = ln.partition('\t')
            if sz.isdigit() and nm in chunk:
                out[nm] = int(sz)
    return out


def hdd_mounted(dst: str) -> str:
    """Точка монтирования, на которой лежит dst (не «/»), если dst существует; иначе ''. `git worktree prune` без HDD стёр бы записи копий, лежащих на нём (ссылки повисли бы)."""
    p = os.path.realpath(os.path.expanduser(dst))
    if not os.path.exists(p):
        return ''
    while True:
        if os.path.ismount(p):
            return p if p != os.sep else ''
        q = os.path.dirname(p)
        if q == p:
            return ''
        p = q


def hours_to_stop(free_gb_now: float, stop_gb: float, gross_gb: float, span_h: float) -> float | None:
    """Прогноз: часов до стопа (свободно упадёт до stop_gb) при скорости роста gross_gb за span_h часов; роста нет — None."""
    if span_h <= 0 or gross_gb <= 0:
        return None
    return max(free_gb_now - stop_gb, 0.0) / (gross_gb / span_h)


def growth_check(r: dict, now: float | None = None, du=None, state_path: str | None = None, free: float | None = None, stop_gb: float | None = None) -> tuple[str, str]:
    """(строка отчёта, WARN или ''). Снимок размеров → файл состояния; сравнение со снимком не новее grow_window_h часов назад (самый старый в окне + 30 мин допуск).
    Меньше часа истории — только снимок, вердикта нет. Прогноз «часов до стопа» (T-89 п.6, Fable): (свободно − stop_gb) ÷ скорость роста за forecast_window_h часов;
    меньше forecast_warn_h — WARN:disk_stop с тремя самыми растущими папками (stop_gb — dev-disk.json start_min_free_gb, ниже него старты прогонов закрыты)."""
    thr, win = r.get('grow_alert_gb'), r.get('grow_window_h')
    if thr is None or win is None:
        return '', ''
    now = time.time() if now is None else now
    sp = state_path or growth_state_path()
    try:
        st = json.load(open(sp, encoding='utf-8'))
        snaps = [s for s in st.get('snaps', []) if isinstance(s, dict) and 't' in s and 'sizes' in s]
        alerted = float(st.get('alerted_t', 0))
        alerted_stop = float(st.get('alerted_stop_t', 0))
    except (OSError, ValueError, AttributeError):
        snaps, alerted, alerted_stop = [], 0.0, 0.0
    cur = (du or du_children)(r['src'])
    keep_s = float(win) * 2 * 3600 + 7200
    snaps = [s for s in snaps if now - s['t'] <= keep_s] + [{'t': now, 'sizes': cur}]
    ref = next((s for s in snaps[:-1] if now - s['t'] <= float(win) * 3600 + 1800), None)
    msg, warn = '', ''
    if ref is None or now - ref['t'] < 3600:
        msg = 'рост логов: снимок записан, истории меньше часа — вердикта нет'
    else:
        d = {n: v - ref['sizes'].get(n, 0) for n, v in cur.items()}
        gross = sum(x for x in d.values() if x > 0)
        top = sorted(((x, n) for n, x in d.items() if x > 0), reverse=True)[:int(r.get('grow_top') or 3)]
        span = (now - ref['t']) / 3600
        msg = f'рост логов за {span:.0f} ч: +{gross / GB:.1f} ГБ (порог {float(thr):g})'
        if gross / GB > float(thr):
            warn = f'WARN:disk_grow: ~/remlab-logs вырос на {gross / GB:.0f} ГБ за {span:.0f} ч (порог {float(thr):g}); больше всех: ' + '; '.join(f'{n} +{x / GB:.1f} ГБ' for x, n in top)
            msg += ' — ТРЕВОГА'
    send = bool(warn) and now - alerted >= float(r.get('grow_alert_every_h') or 0) * 3600
    fw, fh = r.get('forecast_window_h'), r.get('forecast_warn_h')
    stop_warn = ''
    if fw is not None and fh is not None and free is not None and stop_gb is not None:
        fref = next((s for s in snaps[:-1] if now - s['t'] <= float(fw) * 3600 + 1800), None)
        if fref is not None and now - fref['t'] >= 3600:
            fd = {n: v - fref['sizes'].get(n, 0) for n, v in cur.items()}
            fgross = sum(x for x in fd.values() if x > 0) / GB
            fspan = (now - fref['t']) / 3600
            h = hours_to_stop(free, float(stop_gb), fgross, fspan)
            if h is None:
                msg += f'; прогноз: рост за {fspan:.0f} ч нет — до стопа не дойдём'
            else:
                msg += f'; прогноз: свободно {free:.1f} ГБ, рост {fgross / fspan:.1f} ГБ/ч за {fspan:.0f} ч → до стопа ({float(stop_gb):g} ГБ) ≈ {h:.1f} ч'
                if h < float(fh):
                    ftop = sorted(((x, n) for n, x in fd.items() if x > 0), reverse=True)[:int(r.get('grow_top') or 3)]
                    stop_warn = (f'WARN:disk_stop: свободно {free:.0f} ГБ, логи растут {fgross / fspan:.1f} ГБ/ч (за {fspan:.0f} ч) → до стопа ({float(stop_gb):g} ГБ) ≈ {h:.0f} ч (порог {float(fh):g}); растут: '
                                 + '; '.join(f'{n} +{x / GB:.1f} ГБ' for x, n in ftop))
    send_stop = bool(stop_warn) and now - alerted_stop >= float(r.get('grow_alert_every_h') or 0) * 3600
    try:
        os.makedirs(os.path.dirname(sp), exist_ok=True)
        json.dump({'snaps': snaps, 'alerted_t': now if send else alerted, 'alerted_stop_t': now if send_stop else alerted_stop}, open(sp, 'w', encoding='utf-8'))
    except OSError:
        pass
    if send:
        alert('❗ ' + warn)
    if send_stop:
        alert('❗ ' + stop_warn)
    return msg, '\n'.join(x for x in (warn, stop_warn) if x)


def main(argv: list) -> int:
    apply_ = '--apply' in argv
    r = rules()
    global MONITOR_MAX_H
    MONITOR_MAX_H = r.get('monitor_max_h')                    # забытые наблюдатели tail -F старше порога папку не держат (T-89)
    if '--growth' in argv:                                    # сторож роста: до --if-low (часовой запуск считает рост и при свободном месте)
        try:
            gfree = free_gb(r['src'])
            gstop = json.load(open(os.environ.get('LOGS_ARCHIVE_RULES') or RULES_PATH, encoding='utf-8')).get('start_min_free_gb')   # граница «стоп»: старты прогонов закрыты (один источник)
        except (OSError, ValueError):
            gfree, gstop = None, None
        gmsg, gwarn = growth_check(r, free=gfree, stop_gb=gstop)
        if gmsg:
            print(gmsg)
        if gwarn:
            print(gwarn)
    for what, path in (('src', r['src']), ('dst', r['dst'])):
        hit = protected_by(path, r)
        if hit:
            print(f'❗ отказ: {what} {path} совпадает с защищённой {hit} или связан с ней (входы наборов, T-20261125-75/2) — перенос и удаление её не трогают', file=sys.stderr)
            return 2
    why_days = ''
    if '--days' in argv and argv.index('--days') + 1 < len(argv):   # разовый порог для сухого прикидочного прогона (в правилах — archive.days)
        r['days'] = float(argv[argv.index('--days') + 1])
    elif '--worktrees' not in argv:
        try:
            free = free_gb(r['src'])
        except OSError:
            free = None
        if free is not None:
            if '--if-low' in argv and free >= top_free_lt(r):  # часовой запуск: места хватает — ночного порога достаточно, ничего не сканируем
                print(f'свободно {free:.1f} ГБ ≥ {top_free_lt(r):g}: часовой перенос не нужен')
                return 0
            r['days'], why_days = effective_days(r, free)
    if '--worktrees-ok' in argv:                              # перенос и рабочих копий git: ссылка на месте сохраняет путь, записанный в .git/worktrees/*/gitdir
        r['worktrees_block'] = False
    repo = os.environ.get('LOGS_ARCHIVE_REPO') or ROOT
    if '--worktrees' in argv:
        if apply_:
            print('--worktrees — только сухой список: рабочие копии снимает владелец/директор (`git worktree remove`)', file=sys.stderr)
            return 2
        return worktrees_report(r, repo, as_json='--json' in argv)
    lock = take_lock() if apply_ else None
    if apply_ and lock is None:
        print('перенос уже идёт (замок занят) — пропуск')
        return 0
    todo, skipped = candidates(r, repo)
    todo.sort(key=lambda c: -c['freed'])
    limit = int(argv[argv.index('--limit') + 1]) if '--limit' in argv and argv.index('--limit') + 1 < len(argv) else 0
    if limit:
        todo = todo[:limit]
    hdd_todo, hdd_skipped = hdd_candidates(r, repo) if ('--prune-hdd' in argv or not apply_) else ([], [])
    if '--json' in argv:
        print(json.dumps({'todo': todo, 'skipped': skipped, 'src': r['src'], 'dst': r['dst'], 'days': r['days'], 'hdd_prune': {'todo': hdd_todo, 'skipped': hdd_skipped}}, ensure_ascii=False, indent=1))
        return 0
    tot = sum(c['total'] for c in todo)
    fr = sum(c['freed'] for c in todo)
    if why_days:
        print(why_days)
    print(f'{r["src"]} → {r["dst"]} · старше {r["days"]} сут и без ссылок из репозитория: {len(todo)} папок, {tot / GB:.1f} ГБ, освободит {fr / GB:.1f} ГБ ({"ПЕРЕНОС" if apply_ else "сухо"})')
    for c in todo:
        print(f'  {"перенесу" if not apply_ else "переношу"} {c["name"]}  {c["total"] / GB:.2f} ГБ, освободит {c["freed"] / GB:.2f} ГБ, возраст {c["age_d"]} сут' + (f', упомянута в {c["docs"]} доках' if c.get('docs') else ''))
    for n, why in skipped:
        print(f'  оставляю {n}: {why}')
    for ln in MONITOR_NOTES:                                  # T-89: забытые наблюдатели, которые папку не держат (процесс не убит)
        print(f'  {ln}')
    for ln in STALE_NOTES:                                    # T-96/1: забытые ждуны и пробные серверы — тоже не держат перенос (процесс не убит; гасить — дело владельца/директора)
        print(f'  {ln}')
    if STALE_NOTES and apply_ and '--digest' in argv and '--prune-hdd' not in argv:
        head = 'забытый ждун/сервер — не держит: '
        print('DIGEST:' + head + '; '.join(n[len(head):] for n in STALE_NOTES)[:420])
    hp_days = float((r.get('hdd_prune') or {}).get('days', 14))
    if hdd_todo or hdd_skipped or '--prune-hdd' in argv:
        ht = sum(c['total'] for c in hdd_todo)
        print(f'{r["dst"]} · лежат на HDD дольше {hp_days:g} сут, не держат код/живой прогон/действующий план: {len(hdd_todo)} папок, {ht / GB:.1f} ГБ ({"УДАЛЕНИЕ" if apply_ and "--prune-hdd" in argv else "сухо — удалил бы"})')
        for c in sorted(hdd_todo, key=lambda x: -x['total']):
            print(f'  {"удалю" if apply_ and "--prune-hdd" in argv else "удалил бы"} {c["name"]}  {c["total"] / GB:.2f} ГБ, возраст {c["age_d"]} сут')
        for n, why in hdd_skipped:
            if not why.startswith('лежит на HDD меньше'):
                print(f'  на HDD оставляю {n}: {why}')
    if apply_ and '--prune-hdd' in argv:
        pr = pg = 0
        pfails = []
        for c in hdd_todo:
            ok_, line = prune_one(c, r)
            print('  ' + line)
            alert_line = f'логи на HDD: {line}'
            try:
                sys.path.insert(0, HERE)
                import disk_guard as DG
                DG._journal(alert_line)
            except Exception:
                pass
            if ok_:
                pr += 1
                pg += c['total']
            elif '❗' in line:
                pfails.append(line)
        print(f'DIGEST:логи на HDD: удалено {pr} из {len(hdd_todo)} (старше {hp_days:g} сут), освободило {pg / GB:.1f} ГБ')
        if pfails:
            alert('❗ удаление логов на HDD: ' + '; '.join(pfails)[:900])
        return 1 if pfails else 0
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
    summary = f'DIGEST:логи: перенесено {moved} из {len(todo)} (порог {r["days"]:g} сут), освободило {got / GB:.1f} ГБ, свободно на диске {left:.0f} ГБ'
    if '--digest' in argv:
        print(summary)
    else:
        print(summary.replace('DIGEST:', ''))
    if fails:
        alert('❗ перенос логов на HDD: ' + '; '.join(fails)[:900])
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

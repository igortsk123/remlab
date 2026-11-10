#!/usr/bin/env python3
"""УБОРКА ДИСКА DEV, ВТОРОЙ КРУГ (T-20261110-30): то, что не видит сторож рабочих папок `disk-keeper.py`.

ЗАЧЕМ. 10.11 на / pakardev (391 ГБ) осталось 7 ГБ: сторож рабочих папок убирает только черновики задач старше недели, а место
съедали влитые рабочие копии (.claude/worktrees, 47 штук — 16 ГБ), кэши стенда разбора планов (floorplan-bench/cache-*, 10 ГБ
за сутки), старые поколения мешей и тома стендов БД. Здесь — правила на них: `tools/scout/rules/dev-disk-clean.json`.

ПРАВИЛА (kind):
  worktree          — рабочая копия: ветка в main, git status пуст, не locked, idle_h без изменений, ни один процесс в ней;
  cache_dirs        — папки кэша по маске: idle_days ни чтения, ни записи, процесс не держит;
  mesh_generations  — поколение меша, на которое не указывает НИЧТО (база, реестр ассетов, галерея, самое свежее у товара);
                      уходят только тяжёлые файлы, json-записи остаются; база не ответила — правило пусто;
  docker_volumes    — висячий том docker, в котором найдены наши таблицы (проба только на чтение), старше min_age_days;
  docker_containers — остановленный контейнер стенда БД (по имени), кроме never.
НЕ ТРОГАЕТ НИКОГДА: путь с `.memory_bank`, `_secrets`, `.env*` в любом звене; ссылки; всё вне корней правила; чужие тома.

РЕЖИМЫ. По умолчанию — сухой: список «уберу» с причинами и сумма по правилам. `--apply` удаляет ТОЛЬКО по правилам с
`approved: true` (по умолчанию все false — включает владелец), перед удалением каждый кандидат проверяется заново.
`--digest` — строка `DIGEST:диск-уборка …` для ночной сводки (шаг disk_clean в refresh_daily.sh, без --apply);
темп и прогноз — из истории `free.tsv` в log_dir; место кончится раньше forecast_warn_days — `WARN:disk_forecast:`.
`--report` — размеры областей и запись за 7/14 суток (долго: обход дисков, ночью не зовётся).
  ~/venvs/scout/bin/python tools/ops/disk_clean.py                 # сухой прогон
  ~/venvs/scout/bin/python tools/ops/disk_clean.py --digest        # то же + строка сводки
  ~/venvs/scout/bin/python tools/ops/disk_clean.py --only worktrees,bench_cache
  ~/venvs/scout/bin/python tools/ops/disk_clean.py --report
  python -m pytest tools/ops/tests/test_disk_clean.py -q            # тесты на временной папке
Переопределения: DISK_CLEAN_HOME (вместо ~), DISK_CLEAN_RULES (файл правил)."""
import datetime
import fnmatch
import glob
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
GB = 1024 ** 3
FORBIDDEN = ('.memory_bank', '_secrets')

_spec = importlib.util.spec_from_file_location('disk_keeper', os.path.join(HERE, 'disk-keeper.py'))
DK = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(DK)          # du (жёсткие ссылки — честно), newest_after: тот же счёт, что у первого круга
du = DK.du


def home():
    return os.environ.get('DISK_CLEAN_HOME') or os.path.expanduser('~')


def rules_path():
    return os.environ.get('DISK_CLEAN_RULES') or os.path.join(REPO, 'tools', 'scout', 'rules', 'dev-disk-clean.json')


def expand(p):
    return os.path.join(home(), p[2:]) if p.startswith('~/') else p


def forbidden(p):
    """Звено пути из запретного списка (банк памяти, секреты, .env*) — такой путь не удаляется ни при каком правиле."""
    return any(x in FORBIDDEN or x.startswith('.env') for x in os.path.realpath(p).split(os.sep))


def sh(cmd, timeout=120, inp=None):
    """→ (код, stdout). Не запустилось — (-1, текст ошибки)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=inp)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def newest_mtime(path, skip=()):
    """Самое свежее время изменения в дереве (папки `skip` по имени не обходим); 0 — не прочли."""
    t = 0.0
    for dp, dn, fn in os.walk(path, followlinks=False):
        dn[:] = [d for d in dn if d not in skip]
        for n in [dp] + [os.path.join(dp, x) for x in fn]:
            try:
                t = max(t, os.lstat(n).st_mtime)
            except OSError:
                pass
    return t


def newest_touch(path):
    """Самое свежее из чтения и записи файлов (atime на relatime — с точностью до суток, для «не читали неделю» хватает).
    У папок — только запись: atime папки двигает любой обход (и этот же), иначе кэш никогда не стал бы «нетронутым»."""
    t = 0.0
    for dp, dn, fn in os.walk(path, followlinks=False):
        try:
            t = max(t, os.lstat(dp).st_mtime)
        except OSError:
            pass
        for x in fn:
            try:
                st = os.lstat(os.path.join(dp, x))
                t = max(t, st.st_mtime, st.st_atime)
            except OSError:
                pass
    return t


def proc_refs():
    """Что держат СВОИ процессы: (рабочие папки, строки команд и окружений). Чужие /proc не читаются — их и нет в наших папках."""
    cwds, texts = [], []
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            cwds.append(os.path.realpath(os.readlink(f'/proc/{pid}/cwd')))
        except OSError:
            pass
        for f in ('cmdline', 'environ'):
            try:
                texts.append(open(f'/proc/{pid}/{f}', 'rb').read().replace(b'\0', b' ').decode('utf-8', 'ignore'))
            except OSError:
                pass
    return cwds, texts


def busy(path, refs):
    rp = os.path.realpath(path)
    cwds, texts = refs
    return any(c == rp or c.startswith(rp + os.sep) for c in cwds) or any(rp in t or path in t for t in texts)


# ── правила: каждое → список кандидатов {rule, target, bytes, why, act} и список «оставлено» (target, причина) ──────────

def rule_worktree(R, refs, now):
    repo = expand(R['repo'])
    base = os.path.realpath(os.path.join(repo, R.get('dir', '.claude/worktrees')))
    keep = set(R.get('keep') or [])
    idle = float(R.get('idle_h', 48)) * 3600
    main = R.get('main', 'main')
    code, out = sh(['git', '-C', repo, 'worktree', 'list', '--porcelain'], timeout=60)
    if code != 0:
        return [], [(repo, f'git worktree list не прочитан ({code}) — правило пусто')]
    wts, cur = [], {}
    for line in out.split('\n') + ['']:
        if not line.strip():
            if cur:
                wts.append(cur)
            cur = {}
            continue
        k, _, v = line.partition(' ')
        cur[k] = v or True
    out_, kept = [], []
    for w in wts:
        p = w.get('worktree')
        if not isinstance(p, str) or os.path.dirname(os.path.realpath(p)) != base:
            continue          # основная копия и копии вне папки правила — не наши
        name = os.path.basename(p)
        why = None
        if name in keep:
            why = 'в списке keep'
        elif not os.path.isdir(p) or os.path.islink(p):
            why = 'папки нет (prunable) — git worktree prune, не удаление'
        elif w.get('locked'):
            why = 'locked'
        elif forbidden(p):
            why = 'запретный путь'
        if why is None:
            head = w.get('HEAD', '')
            c, _ = sh(['git', '-C', repo, 'merge-base', '--is-ancestor', head, main], timeout=60)
            if c != 0:
                # влита переносом (cherry-pick / rebase): каждый коммит ветки есть в main по содержимому — `git cherry` даёт только «-»
                c2, ch = sh(['git', '-C', repo, 'cherry', main, head], timeout=120)
                own = [x for x in ch.split('\n') if x.strip()]
                if c2 != 0 or not own or any(x.startswith('+') for x in own):
                    n = sum(1 for x in own if x.startswith('+'))
                    why = f'ветка не влита в {main}' + (f': {n} коммитов не в {main}' if n else '') + \
                          (f" ({w.get('branch', '').replace('refs/heads/', '')})" if w.get('branch') else '')
        links = []
        if why is None:
            c, st = sh(['git', '-C', p, 'status', '--porcelain', '--untracked-files=normal'], timeout=120)
            rest = []
            for x in st.splitlines():
                f = x[3:].rstrip('/')
                # ссылка node_modules → основная копия (.gitignore ловит только папку `node_modules/`, не ссылку) — не правка
                if x.startswith('?? ') and f in (R.get('untracked_links') or []) and os.path.islink(os.path.join(p, f)):
                    links.append(os.path.join(p, f))
                elif x.strip():
                    rest.append(x)
            if c != 0:
                why = 'git status не прочитан'
            elif rest:
                why = f'незакоммиченное: {len(rest)} строк git status'
        if why is None:
            age = now - newest_mtime(p, skip=('node_modules', '.next', '.git'))
            if age < idle:
                why = f'менялась {age / 3600:.0f} ч назад (порог {idle / 3600:.0f})'
        if why is None and busy(p, refs):
            why = 'в ней работает процесс'
        if why:
            kept.append((p, why))
            continue
        out_.append({'rule': R['id'], 'target': p, 'bytes': du(p), 'act': ['git-wt', repo, p] + links,
                     'why': f"влита в {main}, чистая, без изменений {(now - newest_mtime(p, skip=('node_modules', '.next', '.git'))) / 86400:.1f} сут"})
    return out_, kept


def rule_cache_dirs(R, refs, now):
    idle = float(R.get('idle_days', 7)) * 86400
    out, kept = [], []
    for g in R['globs']:
        for p in sorted(glob.glob(expand(g))):
            if not os.path.isdir(p) or os.path.islink(p) or forbidden(p):
                continue
            age = now - newest_touch(p)
            if age < idle:
                kept.append((p, f'читали или писали {age / 86400:.1f} сут назад (порог {idle / 86400:.0f})'))
            elif busy(p, refs):
                kept.append((p, 'держит процесс'))
            else:
                out.append({'rule': R['id'], 'target': p, 'bytes': du(p), 'act': ['rmtree', p],
                            'why': f'кэш без обращений {age / 86400:.0f} сут'})
    return out, kept


GEN_RE = re.compile(r'([\w.-]+)/([0-9a-f]{8,})(?:/|$)')


def db_values(sqls):
    """Значения из DEV-базы по списку запросов; None — база не ответила (тогда правило не даёт ничего)."""
    vals = []
    for q in sqls:
        c, out = sh(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-q', '-t', '-A',
                     '-v', 'ON_ERROR_STOP=1'], timeout=300, inp=q.rstrip(';') + ';')
        if c != 0:
            return None
        vals += [x for x in out.split('\n') if x.strip()]
    return vals


def gen_refs(root, texts):
    """Пары (товар, поколение), названные в текстах путём `<root>/<товар>/<поколение>`."""
    root = root.rstrip('/') + '/'
    refs = set()
    for t in texts:
        for chunk in t.split(root)[1:]:
            m = GEN_RE.match(chunk)
            if m:
                refs.add((m.group(1), m.group(2)))
    return refs


def rule_mesh_generations(R, refs, now, db=db_values):
    root = expand(R['root'])
    if not os.path.isdir(root):
        return [], [(root, 'нет папки')]
    vals = db(R.get('refs_sql') or [])
    keep_sku = db(R.get('keep_sku_sql') or [])
    if vals is None or keep_sku is None:
        return [], [(root, 'база DEV не ответила — старые поколения не считаю (WARN)')]
    texts = list(vals)
    files = [expand(f) for f in R.get('refs_files') or []]
    for g in R.get('refs_newest') or []:
        c = sorted(glob.glob(expand(g)), key=lambda x: os.path.getmtime(x))
        files += c[-1:]
    for f in files:
        try:
            texts.append(open(f, encoding='utf-8', errors='ignore').read())
        except OSError:
            return [], [(f, 'файл ссылок не прочитан — старые поколения не считаю (WARN)')]
    named = gen_refs(root, texts)
    keep_sku = {s.replace(':', '_') for s in keep_sku} | set(keep_sku)
    min_age = float(R.get('min_age_days', 14)) * 86400
    heavy = R.get('heavy') or ['*.glb']
    markers = R.get('keep_markers') or []
    out, kept = [], []
    for sku in sorted(os.listdir(root)):
        sd = os.path.join(root, sku)
        if not os.path.isdir(sd) or os.path.islink(sd):
            continue
        gens = [g for g in os.listdir(sd) if os.path.isdir(os.path.join(sd, g)) and not os.path.islink(os.path.join(sd, g))]
        if len(gens) < 2:
            continue      # единственное поколение товара — его и показываем
        def mf(g):
            try:
                return os.path.getmtime(os.path.join(sd, g, 'manifest.json'))
            except OSError:
                return 0.0
        newest = max(gens, key=mf)
        for g in gens:
            gd = os.path.join(sd, g)
            why = None
            if g == newest:
                why = 'самое свежее поколение товара'
            elif (sku, g) in named:
                why = 'на него указывает база / реестр / галерея'
            elif sku in keep_sku:
                why = 'товар в очереди переделки'
            elif any(os.path.exists(os.path.join(gd, m)) for m in markers):
                why = 'есть запись починки'
            elif now - newest_mtime(gd) < min_age:
                why = 'моложе срока'
            if why:
                if why != 'самое свежее поколение товара':
                    kept.append((gd, why))
                continue
            fs = [os.path.join(gd, f) for f in sorted(os.listdir(gd))
                  if any(fnmatch.fnmatch(f, h) for h in heavy) and os.path.isfile(os.path.join(gd, f))
                  and not os.path.islink(os.path.join(gd, f))]
            size = sum(du(f) for f in fs)
            if fs and size:
                out.append({'rule': R['id'], 'target': gd, 'bytes': size, 'act': ['rmfiles', gd] + fs,
                            'why': f'старое поколение ({len(gens)} у товара), ни одной ссылки; уйдут {", ".join(os.path.basename(f) for f in fs)}'})
    return out, kept


def docker_volume_sizes():
    c, out = sh(['docker', 'system', 'df', '-v'], timeout=600)
    sizes, on = {}, False
    if c != 0:
        return None
    units = {'B': 1, 'kB': 1e3, 'KB': 1e3, 'MB': 1e6, 'GB': 1e9, 'TB': 1e12}
    for line in out.split('\n'):
        if line.startswith('VOLUME NAME'):
            on = True
            continue
        if on and (not line.strip() or line.startswith('Build cache')):
            if sizes:
                break
            continue
        if on:
            parts = line.split()
            m = re.match(r'^([\d.]+)([kKMGT]?B)$', parts[-1]) if len(parts) >= 3 else None
            if m:
                sizes[parts[0]] = int(float(m.group(1)) * units[m.group(2)])
    return sizes


def probe_volumes(names, markers, image):
    """Чей том: одноразовый контейнер монтирует тома ТОЛЬКО на чтение, без сети. → {том: 'наш' | 'pg17 без наших маркеров' | 'не postgres'}.
    Ищем маркеры в каталоге (base/*/1259 = pg_class) И в журнале WAL: короткоживущий стенд гасят до контрольной точки —
    его таблицы и строки есть только в pg_wal (10.11: висячие тома стендов — пустой каталог, а в WAL «flat215», «112923»)."""
    res = {}
    for i in range(0, len(names), 40):
        part = names[i:i + 40]
        cmd = ['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'sh']
        for j, n in enumerate(part):
            cmd += ['-v', f'{n}:/v/{j}:ro']
        pat = '|'.join(re.escape(m) for m in markers)
        script = ('for d in /v/*; do i=${d#/v/}; if [ -f $d/PG_VERSION ]; then '
                  f'if cat $d/base/*/1259 $d/pg_wal/0* 2>/dev/null | grep -aqE "{pat}"; then echo "$i наш"; else echo "$i pg$(cat $d/PG_VERSION)-без-наших-маркеров"; fi; '
                  'else echo "$i не-postgres"; fi; done')
        c, out = sh(cmd + [image, '-c', script], timeout=600)
        if c != 0:
            continue
        for line in out.split('\n'):
            k, _, v = line.partition(' ')
            if k.isdigit() and int(k) < len(part):
                res[part[int(k)]] = v.replace('-', ' ')
    return res


def rule_docker_volumes(R, refs, now, docker=None):
    d = docker or {}
    c, out = d.get('ls') or sh(['docker', 'volume', 'ls', '-q', '-f', 'dangling=true'], timeout=120)
    if c != 0:
        return [], [('docker', 'docker volume ls не прочитан')]
    names = [x for x in out.split() if x]
    if not names:
        return [], []
    sizes = d['sizes'] if 'sizes' in d else docker_volume_sizes()
    created = d.get('created')
    if created is None:
        created = {}
        c, out = sh(['docker', 'volume', 'inspect', '-f', '{{.Name}} {{.CreatedAt}}'] + names, timeout=120)
        for line in out.split('\n') if c == 0 else []:
            n, _, t = line.partition(' ')
            try:
                created[n] = datetime.datetime.strptime(t.strip()[:19], '%Y-%m-%dT%H:%M:%S').replace(
                    tzinfo=datetime.timezone.utc).timestamp()
            except ValueError:
                pass
    if 'owner' in d:
        owner = d['owner']
    else:
        # висячий том никто не пишет — ответ пробы держим в кэше (иначе каждую ночь читать ~3 ГБ WAL); маркеры сменились — заново
        cp = os.path.join(expand(R.get('cache_dir') or '~/remlab-logs/disk-clean'), 'volume-owner.json')
        key = 'v2|' + '|'.join(R.get('markers') or [])
        try:
            cache = json.load(open(cp, encoding='utf-8'))
            cache = cache.get('v', {}) if cache.get('markers') == key else {}
        except (OSError, ValueError):
            cache = {}
        todo = [n for n in names if n not in cache]
        if todo:
            cache.update(probe_volumes(todo, R.get('markers') or [], R.get('probe_image', 'alpine:3')))
            try:
                os.makedirs(os.path.dirname(cp), exist_ok=True)
                json.dump({'markers': key, 'v': {n: cache[n] for n in names if n in cache}}, open(cp + '.tmp', 'w', encoding='utf-8'),
                          ensure_ascii=False)
                os.replace(cp + '.tmp', cp)
            except OSError:
                pass
        owner = cache
    min_age = float(R.get('min_age_days', 7)) * 86400
    out_, kept = [], []
    for n in names:
        who = owner.get(n, 'не проверен')
        age = now - created.get(n, now)
        size = (sizes or {}).get(n, 0)
        if who != 'наш':
            kept.append((f'том {n[:12]}', f'{who}, {size / 1e9:.2f} ГБ — не наш или не понятно чей, не трогаю'))
        elif age < min_age:
            kept.append((f'том {n[:12]}', f'наш, создан {age / 86400:.1f} сут назад (порог {min_age / 86400:.0f})'))
        else:
            out_.append({'rule': R['id'], 'target': f'том {n}', 'bytes': size, 'act': ['docker-vol', n],
                         'why': f'висячий, в нём наши таблицы, создан {age / 86400:.0f} сут назад'})
    return out_, kept


def rule_docker_containers(R, refs, now, docker=None):
    d = docker or {}
    c, out = d.get('ps') or sh(['docker', 'ps', '-a', '--format', '{{.Names}}\t{{.State}}'], timeout=120)
    if c != 0:
        return [], [('docker', 'docker ps не прочитан')]
    rx = re.compile(R['name_re'])
    never = set(R.get('never') or [])
    lim = float(R.get('exited_days', 7)) * 86400
    out_, kept = [], []
    for line in out.split('\n'):
        name, _, state = line.partition('\t')
        if not name or not rx.match(name):
            continue
        if name in never:
            kept.append((f'контейнер {name}', 'в списке never'))
            continue
        if state.strip() != 'exited':
            kept.append((f'контейнер {name}', f'состояние {state.strip()}'))
            continue
        fin = (d.get('finished') or {}).get(name)
        if fin is None:
            c2, t = sh(['docker', 'inspect', '-f', '{{.State.FinishedAt}}', name], timeout=60)
            try:
                fin = datetime.datetime.strptime(t.strip()[:19], '%Y-%m-%dT%H:%M:%S').replace(
                    tzinfo=datetime.timezone.utc).timestamp() if c2 == 0 else now
            except ValueError:
                fin = now
        if now - fin < lim:
            kept.append((f'контейнер {name}', f'остановлен {(now - fin) / 86400:.1f} сут назад (порог {lim / 86400:.0f})'))
            continue
        out_.append({'rule': R['id'], 'target': f'контейнер {name}', 'bytes': 0, 'act': ['docker-ctr', name],
                     'why': f'стенд БД остановлен {(now - fin) / 86400:.0f} сут; место вернётся, когда уйдёт его том (pg_volumes)'})
    return out_, kept


KINDS = {'worktree': rule_worktree, 'cache_dirs': rule_cache_dirs, 'mesh_generations': rule_mesh_generations,
         'docker_volumes': rule_docker_volumes, 'docker_containers': rule_docker_containers}


def plan(rules, only=None, now=None, refs=None):
    now = now or time.time()
    refs = refs if refs is not None else proc_refs()
    items, kept = [], []
    for R in rules['rules']:
        if only and R['id'] not in only:
            continue
        a, b = KINDS[R['kind']](R, refs, now)
        items += a
        kept += [(R['id'], t, w) for t, w in b]
    return items, kept


def remove(item, rules):
    """Удалить одного кандидата. → (байт, ошибка|None). Ничего вне правил: запретный путь, ссылка — отказ."""
    act = item['act']
    kind = act[0]
    if kind in ('rmtree', 'rmfiles', 'git-wt'):
        target = act[1] if kind != 'git-wt' else act[2]
        if forbidden(target) or os.path.islink(target):
            return 0, f'{target}: запретный путь или ссылка'
    if kind == 'git-wt':
        for ln in act[3:]:      # сперва ссылки node_modules (снимается ссылка, не то, куда она ведёт), иначе git скажет «untracked»
            if os.path.dirname(ln) != act[2] or not os.path.islink(ln):
                return 0, f'{ln}: не ссылка в корне копии — не трогаю'
            try:
                os.unlink(ln)
            except OSError as e:
                return 0, f'{ln}: {e}'
        c, out = sh(['git', '-C', act[1], 'worktree', 'remove', act[2]], timeout=300)   # без --force: грязную git не отдаст
        return (item['bytes'], None) if c == 0 else (0, f'{act[2]}: git worktree remove: {out.strip()[:150]}')
    if kind == 'rmtree':
        errs = []
        shutil.rmtree(act[1], onerror=lambda f, x, e: errs.append(f'{x}: {e[1]}'))
        return item['bytes'], (f'{act[1]}: {len(errs)} ошибок, первая {errs[0]}' if errs else None)
    if kind == 'rmfiles':
        freed = 0
        for f in act[2:]:
            if os.path.dirname(f) != act[1] or os.path.islink(f):
                return freed, f'{f}: вне папки поколения'
            s = du(f)
            try:
                os.remove(f)
                freed += s
            except OSError as e:
                return freed, f'{f}: {e}'
        return freed, None
    if kind == 'docker-vol':
        c, out = sh(['docker', 'volume', 'rm', act[1]], timeout=120)
        return (item['bytes'], None) if c == 0 else (0, f'том {act[1][:12]}: {out.strip()[:150]}')
    if kind == 'docker-ctr':
        c, out = sh(['docker', 'rm', act[1]], timeout=120)       # без -v: том станет висячим и уйдёт следующим шагом
        return (0, None) if c == 0 else (0, f'контейнер {act[1]}: {out.strip()[:150]}')
    return 0, f'неизвестное действие {kind}'


# ── история места, темп, прогноз ──────────────────────────────────────────────────────────────────────────────────

def history(log_dir, free, cand, now, write=True):
    """Дописать (время, свободно, кандидаты) в free.tsv и вернуть темп ГБ/сутки по записи ~сутки назад (None — истории мало)."""
    p = os.path.join(log_dir, 'free.tsv')
    rows = []
    try:
        for line in open(p, encoding='utf-8'):
            a = line.split('\t')
            if len(a) >= 2:
                rows.append((float(a[0]), float(a[1])))
    except (OSError, ValueError):
        pass
    if write:
        with open(p, 'a', encoding='utf-8') as f:
            f.write(f'{now:.0f}\t{free:.0f}\t{cand:.0f}\n')
    old = [r for r in rows if 20 * 3600 <= now - r[0] <= 8 * 86400]
    if not old:
        return None
    t0, f0 = min(old, key=lambda r: abs(now - r[0] - 86400))
    return (f0 - free) / GB / ((now - t0) / 86400)     # плюс — место уходит


def write_log(log_dir, keep, lines, now):
    os.makedirs(log_dir, exist_ok=True)
    stamp = time.strftime('%Y-%m-%d_%H%M%S', time.gmtime(now))
    with open(os.path.join(log_dir, f'{stamp}.log'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    logs = sorted(x for x in os.listdir(log_dir) if re.match(r'^\d{4}-\d\d-\d\d_\d{6}\.log$', x))
    for x in logs[:-keep] if keep > 0 else []:     # свой журнал — только свои файлы по маске
        try:
            os.remove(os.path.join(log_dir, x))
        except OSError:
            pass


# ── отчёт по областям ─────────────────────────────────────────────────────────────────────────────────────────────

def area_stats(path, now):
    """(байт на диске, записано за 7 сут, за 14 сут) — живые файлы, жёсткие ссылки один раз."""
    tot = d7 = d14 = 0
    seen = set()
    for dp, dn, fn in os.walk(path, followlinks=False):
        for n in fn:
            try:
                st = os.lstat(os.path.join(dp, n))
            except OSError:
                continue
            if st.st_nlink > 1:
                k = (st.st_dev, st.st_ino)
                if k in seen:
                    continue
                seen.add(k)
            b = st.st_blocks * 512
            tot += b
            age = now - st.st_mtime
            d7 += b if age < 7 * 86400 else 0
            d14 += b if age < 14 * 86400 else 0
    return tot, d7, d14


def report(rules, now):
    print('ОБЛАСТИ (ГБ: на диске · записано за 7 сут · за 14 сут):')
    for A in rules.get('report_areas') or []:
        p = expand(A['path'])
        if not os.path.isdir(p):
            continue
        if A.get('foreign'):
            c, out = sh(['nice', '-n', '15', 'ionice', '-c3', 'du', '-sx', '--block-size=1', p], timeout=1800)
            size = int(out.split()[0]) if c == 0 and out.split() and out.split()[0].isdigit() else 0
            print(f"  {A['path']:<28} {size / GB:6.1f}      —      —   {A['owner']} (чужой проект: только размер)")
            continue
        tot, d7, d14 = area_stats(p, now)
        print(f"  {A['path']:<28} {tot / GB:6.1f} {d7 / GB:6.1f} {d14 / GB:6.1f}   {A['owner']}")
    c, out = sh(['docker', 'system', 'df'], timeout=600)
    if c == 0:
        print('DOCKER:\n' + '\n'.join('  ' + x for x in out.strip().split('\n')))


def main(argv):
    rules = json.load(open(rules_path(), encoding='utf-8'))
    now = time.time()
    if '--report' in argv:
        report(rules, now)
        return 0
    apply = '--apply' in argv
    only = None
    if '--only' in argv:
        only = set(argv[argv.index('--only') + 1].split(','))
    items, kept = plan(rules, only, now)
    approved = {R['id'] for R in rules['rules'] if R.get('approved')}
    lines, by = [], {}
    for it in sorted(items, key=lambda x: (x['rule'], -x['bytes'])):
        ok = it['rule'] in approved
        lines.append(f"{'удаляю' if apply and ok else 'уберу'} [{it['rule']}{'' if ok else ', ждёт одобрения'}]: {it['target']} — "
                     f"{it['bytes'] / 2 ** 20:.0f} МБ ({it['why']})")
        by[it['rule']] = by.get(it['rule'], 0) + it['bytes']
    for rid, t, w in kept:
        lines.append(f'оставлено [{rid}]: {t} — {w}')
    warns = [f'WARN:disk_clean: {rid}: {w}' for rid, t, w in kept if '(WARN)' in w]
    freed, fails = 0, []
    if apply:
        again, _ = plan(rules, approved & (only or approved), time.time())   # заново: что изменилось, пока считали, — остаётся
        live = {(x['rule'], x['target']) for x in again}
        for it in items:
            if it['rule'] not in approved:
                continue
            if (it['rule'], it['target']) not in live:
                fails.append(f"{it['target']}: при повторной проверке уже не кандидат — оставлено")
                continue
            b, err = remove(it, rules)
            freed += b
            if err:
                fails.append(err)
    for f in fails:
        lines.append(f'не удалено: {f}')
    total = sum(by.values())
    free = shutil.disk_usage(home()).free
    log_dir = expand(rules.get('log_dir', '~/remlab-logs/disk-clean'))
    os.makedirs(log_dir, exist_ok=True)
    rate = history(log_dir, free, total, now)
    parts = ', '.join(f'{k} {v / GB:.1f}' for k, v in sorted(by.items(), key=lambda x: -x[1]))
    tempo = ''
    if rate is not None:
        tempo = f', за сутки {"−" if rate > 0 else "+"}{abs(rate):.0f} ГБ'
        if rate > 0.5:
            days = free / GB / rate
            tempo += f' (при таком темпе хватит на ~{days:.0f} сут)'
            if days < float(rules.get('forecast_warn_days', 3)):
                warns.append(f'WARN:disk_forecast: на DEV свободно {free / GB:.0f} ГБ, уходит {rate:.0f} ГБ/сут — кончится через '
                             f'~{days:.1f} сут; можно снять {total / GB:.1f} ГБ ({parts or "нечего"})')
    mode = f'убрано {freed / GB:.1f} ГБ' if apply and approved else 'сухо, правила ждут одобрения' if not approved else 'сухо'
    line = (f'диск-уборка ({mode}): свободно {free / GB:.0f} ГБ{tempo}; можно снять {total / GB:.1f} ГБ'
            + (f' ({parts})' if parts else '') + f'; одобрено правил {len(approved)}/{len(rules["rules"])}')
    if fails:
        warns.append(f'WARN:disk_clean: не удалено {len(fails)} (первое: {fails[0][:150]})')
    lines += warns + [line]
    write_log(log_dir, int(rules.get('log_keep', 30)), lines, now)
    for x in lines:
        if x.startswith('оставлено') and '--verbose' not in argv and '(WARN)' not in x:
            continue
        print(x)
    print(f'журнал: {log_dir} (оставленное с причинами — там же; на экран: --verbose)')
    if '--digest' in argv:
        print('DIGEST:' + line)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

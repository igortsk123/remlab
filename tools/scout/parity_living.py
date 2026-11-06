#!/usr/bin/env python3
"""СТЕНД ПАРИТЕТА КОМНАТ (room-pipeline-01 Б-3, T-20261105-41 гостиная, T-20261105-54 спальня и прихожая): одна команда
до и после правки общего конвейера доказывает, что комната не изменилась.

ЧТО СРАВНИВАЕМ (артефакты комнаты, нормализованные; шаги комнаты, шум — явным списком в `rules/parity-living.json`):
  catalog — выборка адаптера `catalog_items.items(<комната>)`; у гостиной — и тень против compose2 (`catalog_items_shadow`, цель 0);
  smoke   — (гостиная) экзамен-смоук (сцены `smoke_manifest.py`, как `run.sh smoke`): отчёт по сценам + раскладки солвера;
  demo    — `demo-data.json` flat215 (`flat215_demo.py` в свою папку, без публикации); спальня — под флагом комнаты
            (`FLAT215_ROOMS_ENABLED`, как T-32) на банке этого же стенда; у прихожей демо нет — шаг пропускается явно;
  cams    — ракурсы камер вариантов демо (`variants[].cams`, считает `tools/flat3d/demo-cams.mjs`);
  bank    — банк комплектов рядом (живой не трогаем); сборщик — по профилю комнаты (`composer.plugin` →
            `room_profile.COMPOSERS`): гостиная — compose2 `--style --bands all`, спальня/прихожая — compose_bedroom/compose_hall;
  exam    — экзамен комнаты (`bedroom_exam.py` / `hall_exam.py`): строки сцен + сводка.

КАК (уроки 525–527). Каждый прогон — своя копия кода (ревизия git или рабочее дерево) в `~/remlab-scratch/parity/run-…`
на ЗАМОРОЖЕННЫХ данных (`freeze`: git-игнорируемые входы основной копии, один раз; в копию — жёсткими ссылками, запись в
такой файл сначала делает свою копию). В каждом Python-процессе стоит сторож `parity_guard.py`: запись вне копии —
отказ, все чтения — в журнал (входы мимо копии и отсутствующие входы видны), сеть — запись на эталоне и воспроизведение на
сверке. Входы эталона — хеши: файлы данных, которые прочли; файлы вне копии; ответы сети; содержимое таблиц БД, которые
прогон читал (по счётчикам `pg_stat_user_tables`). Сверка на других входах — отказ (код 3): «эталон старше данных».

  parity_living.py freeze                                   # заморозить данные (печатает папку)
  parity_living.py snapshot [--room living|bedroom|hall] [--rev main] [--data DIR] [--steps …] [--into REF]  # эталон «до»
  parity_living.py compare --ref FILE [--rev WORKTREE] [--steps …] [--inject REL=SRC]   # «после»; комната — из эталона
  parity_living.py diff --ref FILE --run STAND               # сверка уже прогнанного стенда без пересчёта
  parity_living.py --selftest                               # без базы и сети
Коды: 0 — равно, 1 — есть различия, 2 — шаг упал / сторож поймал запись, 3 — эталон устарел (входы другие).
Тяжёлое (смоук, демо, банк) идёт по шагам, по одному, с `nice` и `ACC_WORKERS` из правил (DEV обслуживает живое демо).
"""
from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, '..', '..'))
RULES_PATH = os.path.join(HERE, 'rules', 'parity-living.json')
GUARD = os.path.join(HERE, 'parity_guard.py')
sys.path.insert(0, os.path.join(REPO, 'tools', 'ops'))     # heavy_slot — общая очередь тяжёлых прогонов (T-57)
VERSION = 2              # 2 — база тоже заморожена (копия на момент freeze)
STEPS = ('catalog', 'smoke', 'demo', 'cams', 'bank', 'exam')   # cams — из того же прогона демо; шаги комнаты — rules.rooms


def rules() -> dict:
    return json.load(open(RULES_PATH, encoding='utf-8'))


def home(R: dict) -> str:
    return os.path.expanduser(os.environ.get('PARITY_HOME') or R['home'])


def main_copy() -> str:
    """Основная копия репо (первая в `git worktree list`) — источник данных для заморозки."""
    out = subprocess.run(['git', '-C', REPO, 'worktree', 'list', '--porcelain'], capture_output=True, text=True, check=True).stdout
    return out.split('\n', 1)[0].split(' ', 1)[1].strip()


def sha_file(p: str) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def sha_obj(o) -> str:
    return hashlib.sha256(json.dumps(o, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


# ---------------------------------------------------------------- нормализация и сверка (чистые функции)

def normalize(o, noise_keys: set, subs: list):
    """Без полей-шума (по имени ключа на любой глубине); строки — с заменой путей стенда/копий на метки."""
    if isinstance(o, dict):
        return {k: normalize(v, noise_keys, subs) for k, v in o.items() if k not in noise_keys}
    if isinstance(o, list):
        return [normalize(v, noise_keys, subs) for v in o]
    if isinstance(o, str):
        for pat, rep in subs:
            o = pat.sub(rep, o)
    return o


def subs_for(R: dict, roots: dict) -> list:
    """Замены в строках: пути (стенд, основная копия, папка демо) → метки; плюс регулярки шума из правил."""
    out = [(re.compile(re.escape(p)), f'<{name}>') for name, p in sorted(roots.items(), key=lambda kv: -len(kv[1])) if p]
    return out + [(re.compile(x['re']), x['to']) for x in R['noise'].get('strings', [])]


def items_of(name: str, obj) -> dict:
    """Артефакт → {id элемента: значение}: расхождение показываем по элементам (сцена, товар, вариант), а не «файл другой»."""
    if name == 'catalog':
        return {c['offer_id']: c for c in obj['items']} | ({'_shadow': obj['shadow']} if 'shadow' in obj else {})   # тень — у гостиной
    if name == 'smoke':
        return {f"report/{r.get('scene')}": r for r in obj['report']} | {f'layout/{k}': v for k, v in obj['layouts'].items()} \
            | {'_manifest': obj['manifest']}
    if name == 'demo':
        out = {}
        for k, v in obj.items():
            if k == 'variants' and isinstance(v, list):
                out.update({f"variants/{x.get('id', i)}": x for i, x in enumerate(v)})
            elif k == 'feeds' and isinstance(v, dict):
                out.update({f'feeds/{r}': x for r, x in v.items()})
            else:
                out[k] = v
        return out
    if name == 'cams':
        return dict(obj)
    if name == 'bank':
        sets = obj.get('sets', obj) if isinstance(obj, dict) else obj
        if isinstance(sets, list):
            out = {}
            for i, s in enumerate(sets):         # гостиная — id; банки комнат — ячейка room|purpose|band|style|tier
                k = f"set/{(s.get('id') or s.get('cell') or s.get('set', i)) if isinstance(s, dict) else i}"
                out[k if k not in out else f'{k}#{i}'] = s
            return out | ({k: v for k, v in obj.items() if k != 'sets'} if isinstance(obj, dict) else {})
        return dict(obj)
    if name == 'exam':
        return {f"row/{r.get('id')}": r for r in obj['rows']} | {'_summary': obj['summary']}
    raise ValueError(f'неизвестный артефакт {name}')


def leaf_diff(a, b, path: str = '', out: list | None = None, limit: int = 8) -> list:
    """Первые различия по листьям: путь, эталон, сейчас."""
    out = [] if out is None else out
    if len(out) >= limit:
        return out
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b), key=str):
            if a.get(k, '<нет>') != b.get(k, '<нет>'):
                leaf_diff(a.get(k, '<нет>'), b.get(k, '<нет>'), f'{path}.{k}', out, limit)
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                leaf_diff(x, y, f'{path}[{i}]', out, limit)
    else:
        out.append({'path': path or '.', 'ref': _short(a), 'now': _short(b)})
    return out


def _short(v):
    s = json.dumps(v, ensure_ascii=False)
    return v if len(s) <= 160 else s[:157] + '…'


def compare_items(ref: dict, now: dict, sample: int = 12) -> dict:
    """ref/now — {id: значение}. → только в эталоне / только сейчас / разные (с первыми различиями)."""
    only_ref = sorted(k for k in ref if k not in now)
    only_now = sorted(k for k in now if k not in ref)
    changed = sorted(k for k in ref if k in now and ref[k] != now[k])
    return {'n_ref': len(ref), 'n_now': len(now), 'diff': len(only_ref) + len(only_now) + len(changed),
            'only_ref': only_ref[:sample], 'only_now': only_now[:sample], 'n_only_ref': len(only_ref),
            'n_only_now': len(only_now), 'n_changed': len(changed),
            'changed': [{'id': k, 'first': leaf_diff(ref[k], now[k])} for k in changed[:sample]]}


def stale_inputs(ref: dict, now: dict) -> list:
    """Входы эталона и сверки: {'files': {путь: sha}, 'external': {…}, 'db': {таблица: отпечаток}, 'net': {…}}.
    Отказ — по любому входу, который эталон видел и который сейчас другой или пропал. Новые входы сверки (читала то, чего
    эталон не читал) — не отказ: их значение то же, что при заморозке (файлы) или будет видно в различиях."""
    out = []
    for kind in ('files', 'external', 'db', 'net'):
        for k, v in (ref.get(kind) or {}).items():
            w = (now.get(kind) or {}).get(k)
            if w != v:
                out.append({'kind': kind, 'key': k, 'ref': v, 'now': w})
    return out


# ---------------------------------------------------------------- заморозка данных

def _ignored(main: str, dirs: list) -> list:
    r = subprocess.run(['git', '-C', main, 'status', '--ignored', '--porcelain', '-z', '--', *dirs], capture_output=True, check=True)
    return [x[3:].decode() for x in r.stdout.split(b'\0') if x.startswith(b'!! ')]   # -z: имена по-русски без кавычек


def is_key_file(rel: str) -> bool:
    """`.env*` (ключи и их образцы) в стенд не попадают никогда — ни данными, ни кодом, ни затравкой: нет ключа — нет платного."""
    return os.path.basename(rel).startswith('.env')


def frozen_rel(F: dict, rel: str) -> bool:
    """Берётся ли git-игнорируемый файл основной копии в заморозку (exclude/keep из правил + запрет ключей)."""
    if is_key_file(rel):
        return False
    return not any(fnmatch.fnmatch(rel, g) for g in F['exclude']) or any(fnmatch.fnmatch(rel, g) for g in F['keep'])


def key_files_in(root: str) -> list:
    return sorted(os.path.relpath(os.path.join(d, f), root) for d, _sub, fs in os.walk(root) for f in fs if is_key_file(f))


def freeze(R: dict) -> str:
    main = main_copy()
    F = R['freeze']
    stamp = time.strftime('%Y%m%d-%H%M%S')
    dst = os.path.join(home(R), f'data-{stamp}')
    files: dict = {}
    for rel in _ignored(main, F['dirs']):
        paths = []
        full = os.path.join(main, rel)
        if os.path.isdir(full):
            for d, _sub, fs in os.walk(full):
                paths += [os.path.relpath(os.path.join(d, f), main) for f in fs]
        else:
            paths.append(rel)
        for p in paths:
            if not frozen_rel(F, p):
                continue
            src = os.path.join(main, p)
            if not os.path.isfile(src) or os.path.islink(src):
                continue
            out = os.path.join(dst, 'files', p)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            shutil.copy2(src, out)
            files[p] = sha_file(out)
    seeds = {}
    for name, src in F['seed'].items():
        src = os.path.expanduser(src)
        if os.path.isdir(src):
            for d, _sub, fs in os.walk(src):
                for f in fs:
                    if is_key_file(f):
                        continue
                    s = os.path.join(d, f)
                    rel = os.path.join(name, os.path.relpath(s, src))
                    o = os.path.join(dst, 'seed', rel)
                    os.makedirs(os.path.dirname(o), exist_ok=True)
                    shutil.copy2(s, o)
                    seeds[rel] = sha_file(o)
        elif os.path.isfile(src):
            o = os.path.join(dst, 'seed', name)
            os.makedirs(os.path.dirname(o), exist_ok=True)
            shutil.copy2(src, o)
            seeds[name] = sha_file(o)
    dbi = freeze_db(stamp) if F.get('db', True) else None
    man = {'version': VERSION, 'frozen_at': time.strftime('%Y-%m-%d %H:%M:%S'), 'main': main, 'db': dbi,
           'main_head': subprocess.run(['git', '-C', main, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip(),
           'files': files, 'seed': seeds, 'size_mb': round(sum(os.path.getsize(os.path.join(dst, 'files', p)) for p in files) / 1e6, 1)}
    leak = key_files_in(dst)
    if leak:
        raise SystemExit(f'заморозка: в папке файлы ключей {leak[:5]} — так быть не должно (is_key_file), остановлено')
    json.dump(man, open(os.path.join(dst, 'manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'заморожено: {len(files)} файлов данных ({man["size_mb"]} МБ), затравок {len(seeds)}, база '
          + (f"{dbi['name']} ({dbi['size']}, {dbi['seconds']} с)" if dbi else 'живая (без копии)') + f' → {dst}')
    return dst


# ---------------------------------------------------------------- стенд: копия кода + данные + сторож

def _copy_code(rev: str, dst: str, R: dict) -> str:
    """Код ревизии в dst. WORKTREE — рабочее дерево этого репо (отслеживаемые + новые неигнорируемые файлы)."""
    os.makedirs(dst, exist_ok=True)
    skip = R['code_skip']
    if rev == 'WORKTREE':
        ls = subprocess.run(['git', '-C', REPO, 'ls-files', '-co', '--exclude-standard', '-z'], capture_output=True, check=True).stdout
        for rel in (x.decode() for x in ls.split(b'\0') if x):
            if any(rel.startswith(s) for s in skip) or is_key_file(rel) or not os.path.isfile(os.path.join(REPO, rel)):
                continue
            o = os.path.join(dst, rel)
            os.makedirs(os.path.dirname(o), exist_ok=True)
            shutil.copy2(os.path.join(REPO, rel), o)
        head = subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(['git', '-C', REPO, 'status', '--porcelain', '--untracked-files=normal'],
                               capture_output=True, text=True).stdout.strip()
        return f'{head}+worktree' if dirty else head
    sha = subprocess.run(['git', '-C', REPO, 'rev-parse', rev], capture_output=True, text=True, check=True).stdout.strip()
    arch = subprocess.run(['git', '-C', REPO, 'archive', sha, '--', '.', *[f':(exclude){s}' for s in skip],
                           ':(exclude,glob)**/.env*'],
                          capture_output=True, check=True).stdout
    subprocess.run(['tar', '-x', '-C', dst], input=arch, check=True)
    return sha


def _link_tree(src_root: str, rels, dst_root: str, skip_existing: bool = True) -> list:
    clash = []
    for rel in rels:
        o = os.path.join(dst_root, rel)
        if os.path.exists(o):
            if skip_existing:
                clash.append(rel)
                continue
        os.makedirs(os.path.dirname(o), exist_ok=True)
        os.link(os.path.join(src_root, rel), o)
    return clash


def build_stand(R: dict, rev: str, data: str, tag: str, inject: list) -> dict:
    man = json.load(open(os.path.join(data, 'manifest.json'), encoding='utf-8'))
    stand = os.path.join(home(R), f"run-{time.strftime('%Y%m%d-%H%M%S')}-{tag}")
    repo = os.path.join(stand, 'repo')
    sha = _copy_code(rev, repo, R)
    clash = _link_tree(os.path.join(data, 'files'), man['files'], repo)      # код ревизии важнее данных
    nm = os.path.join(man['main'], 'node_modules')
    if os.path.isdir(nm) and not os.path.exists(os.path.join(repo, 'node_modules')):
        os.symlink(nm, os.path.join(repo, 'node_modules'))                    # зависимости — только чтение
    for spec in inject:                                                       # подмешанное различие — только в копии
        rel, src = spec.split('=', 1)
        o = os.path.join(repo, rel)
        if os.path.exists(o):
            os.replace(o, o + '.parity-orig')
        shutil.copy2(os.path.expanduser(src), o)
    site = os.path.join(stand, '_site')
    os.makedirs(site, exist_ok=True)
    import parity_guard as PGd
    open(os.path.join(site, 'sitecustomize.py'), 'w', encoding='utf-8').write(PGd.SITECUSTOMIZE)
    shutil.copy2(GUARD, os.path.join(site, 'parity_guard_impl.py'))
    for d in ('out', 'tmp', 'logs', 'seed'):
        os.makedirs(os.path.join(stand, d), exist_ok=True)
    _link_tree(os.path.join(data, 'seed'), man['seed'], os.path.join(stand, 'seed'), skip_existing=False)
    leak = key_files_in(stand)
    if leak:
        raise SystemExit(f'стенд: файлы ключей в копии {leak[:5]} — остановлено (is_key_file)')
    return {'stand': stand, 'repo': repo, 'rev': rev, 'sha': sha, 'data': data, 'manifest': man, 'clash': clash,
            'inject': inject}


def data_db(man: dict) -> str:
    return (man.get('db') or {}).get('name') or LIVE_DB


def stand_env(R: dict, S: dict, net: str) -> dict:
    stand = S['stand']
    env = {k: v for k, v in os.environ.items() if not k.startswith(('PARITY_', 'SETS_', 'ACC_', 'FLAT215_', 'LAYOUT_', 'STYLE_',
                                                                    'BEDROOM_', 'HALL_', 'ROOM_', 'MESH_LUMA', 'REMLAB_DEVDB'))}
    db = data_db(S['manifest'])
    if db != LIVE_DB:        # все вызовы psql кода — в замороженную копию (`parity_guard.route_db`; читатели с env — тоже)
        env.update(PARITY_DB=db, REMLAB_DEVDB_NAME=db)
    deny = [S['manifest']['main'], os.path.expanduser('~/scout-scenes'), S['data']]
    env.update(PARITY_ROOT=stand, PARITY_GUARD=os.path.join(stand, '_site', 'parity_guard_impl.py'),
               PARITY_ALLOW=os.pathsep.join([os.path.join(stand, 'tmp'), os.path.expanduser('~/.cache'), '/dev/null',
                                             os.path.expanduser('~/.local/share/pnpm')]),
               PARITY_DENY=os.pathsep.join(deny), PARITY_NET=net, PARITY_NET_DIR=os.path.join(S['data'], 'net'),
               PYTHONPATH=os.path.join(stand, '_site'), TMPDIR=os.path.join(stand, 'tmp'), PYTHONDONTWRITEBYTECODE='1',
               MESH_LUMA_CACHE=os.path.join(stand, 'seed', 'mesh-luma-cache.json'))
    return env


@contextlib.contextmanager
def heavy(R: dict, S: dict, step: str, need_gb: float | None = None):
    """ТЯЖЁЛЫЙ ШАГ — ЧЕРЕЗ ОБЩУЮ ОЧЕРЕДЬ МАШИНЫ (`tools/ops/heavy_slot.py`, T-20261105-57; до того — свой цикл ожидания, T-41):
    одно тяжёлое за раз на DEV, взявший очередь ждёт MemAvailable ≥ `memory.min_gb` (банк — `bank_gb`) и держит слот, пока идёт
    шаг (ведущий 05.11: earlyoom снимал `remlab-render` живого демо, когда два прогона стартовали разом). Строки ожидания —
    в журнал шага и в `~/remlab-logs/heavy-slot.log`; кто держит — `tools/ops/heavy-slot.sh --status`. → свободно ГБ."""
    import heavy_slot as HS
    M = R['memory']
    need = need_gb if need_gb is not None else M['min_gb']
    log = os.path.join(S['stand'], 'logs', f'{step}.log')
    with HS.heavy_slot(f"parity-{S.get('room', 'living')}-{step}", min_gb=need, poll=M['poll_s'], report=M['report_s'],
                       say=lambda m: _say(log, m), cmd=f"parity_living {step} {S['stand']}") as info:
        yield info['free_gb'] if info['free_gb'] is not None else HS.mem_available_gb()


def _say(log: str, msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print('  ' + line, flush=True)
    with open(log, 'a', encoding='utf-8') as fh:
        fh.write(line + '\n')


def smoke_workers(R: dict, free_gb: float) -> int:
    """Солверов смоука параллельно: из правил, но не больше, чем помещается сверх порога (по `memory.per_worker_gb` на солвер)."""
    M = R['memory']
    return max(1, min(R['acc_workers'], int((free_gb - M['min_gb']) // M['per_worker_gb']) + 1))


def _held_env() -> dict:
    """Слот очереди у стенда — потомкам (если они сами зовут слот, вложенный вызов не ждёт стенд)."""
    return {'HEAVY_SLOT_HELD': os.environ['HEAVY_SLOT_HELD']} if 'HEAVY_SLOT_HELD' in os.environ else {}


def _run(S: dict, env: dict, step: str, argv: list, extra_env: dict | None = None, cwd: str | None = None) -> dict:
    log = os.path.join(S['stand'], 'logs', f'{step}.log')
    t = time.time()
    with open(log, 'a', encoding='utf-8') as fh:
        fh.write(f"$ {' '.join(argv)}\n")
        fh.flush()
        r = subprocess.run(['nice', '-n', '10', *argv], cwd=cwd or os.path.join(S['repo'], 'tools', 'scout'),
                           env={**env, **(extra_env or {}), **_held_env()}, stdout=fh, stderr=subprocess.STDOUT)
    return {'rc': r.returncode, 'seconds': round(time.time() - t, 1), 'log': log}


PY = os.path.expanduser('~/venvs/scout/bin/python')


def step_catalog(R, S, env) -> tuple[dict, dict]:
    """Выборка адаптера `catalog_items.items(<комната>, with_assets=True)`; у комнат с тенью (гостиная) — и тень против compose2."""
    room, rr = S['room'], R['rooms'][S['room']]
    out = os.path.join(S['stand'], 'out', 'catalog.json')
    shadow = os.path.join(S['stand'], 'out', 'shadow')
    code = ('import json,sys; sys.path.insert(0,".")\n'
            'import catalog_items as CI\n'
            f'it=[c.to_dict() for c in CI.items({room!r}, with_assets=True)]\n'
            'res={"items":sorted(it,key=lambda c:c["offer_id"])}\n')
    if rr.get('shadow'):
        code += ('import catalog_items_shadow as SH\n'
                 f'res["rc_shadow"]=SH.run({room!r}, {shadow!r})\n'
                 f'res["shadow"]=json.load(open({os.path.join(shadow, f"catalog-shadow-{room}.json")!r}))\n')
    code += f'json.dump(res,open({out!r},"w"),ensure_ascii=False)\n'
    st = _run(S, env, 'catalog', [PY, '-c', code])
    return st, ({'catalog': json.load(open(out, encoding='utf-8'))} if st['rc'] == 0 else {})


def step_smoke(R, S, env) -> tuple[dict, dict]:
    sc = os.path.join(S['repo'], 'tools', 'scout')
    man = os.path.join(sc, 'smoke-manifest.json')
    with heavy(R, S, 'smoke') as free:
        workers = smoke_workers(R, free)
        st = _run(S, env, 'smoke', [PY, 'smoke_manifest.py'])
        if st['rc'] != 0:
            return st, {}
        st2 = _run(S, env, 'smoke', [PY, 'acceptance_run.py', 'zoned'],
                   {'ACC_WORKERS': str(workers), 'ACC_MANIFEST': man, 'ACC_REPORT_SUFFIX': '-smoke'})
    st2['seconds'] += st['seconds']
    if st2['rc'] != 0:
        return st2, {}
    rep = [json.loads(ln) for ln in open(os.path.join(sc, 'acceptance-report-zoned-smoke.jsonl'), encoding='utf-8') if ln.strip()]
    lay = {}
    for f in sorted(os.listdir(sc)):
        if re.fullmatch(r'v3set\d+-layout-acc-zoned-.+\.json', f):
            lay[f] = json.load(open(os.path.join(sc, f), encoding='utf-8'))
    return st2, {'smoke': {'report': sorted(rep, key=lambda r: str(r.get('scene'))), 'layouts': lay,
                           'manifest': json.load(open(man, encoding='utf-8'))}}


def step_demo(R, S, env) -> tuple[dict, dict]:
    """Демо flat215 в свою папку стенда (без публикации). Комната кроме гостиной — проверочным флагом сборки рядом
    (`FLAT215_ROOMS_ENABLED`, как T-32) на банке, собранном этим же стендом (живого банка комнаты может не быть)."""
    dm = R['rooms'][S['room']].get('demo') or {}
    extra = {}
    if dm.get('rooms_enabled'):
        bank = S.get('bank_out') or _compose(R, S, env)[1]
        if not bank:
            return {'rc': 2, 'seconds': 0, 'log': os.path.join(S['stand'], 'logs', 'bank.log')}, {}
        extra = {'FLAT215_ROOMS_ENABLED': dm['rooms_enabled'], dm['bank_env']: bank}
    out = os.path.join(S['stand'], 'out', 'demo')
    os.makedirs(out, exist_ok=True)
    seed = os.path.join(S['stand'], 'seed', 'demo')
    if os.path.isdir(seed):                     # вчерашнее демо — вход (псевдонимы вариантов, фото уже скачаны)
        for d, _sub, fs in os.walk(seed):
            for f in fs:
                s = os.path.join(d, f)
                o = os.path.join(out, os.path.relpath(s, seed))
                os.makedirs(os.path.dirname(o), exist_ok=True)
                shutil.copy2(s, o) if f.endswith('.json') else os.link(s, o)
    with heavy(R, S, 'demo'):
        st = _run(S, env, 'demo', [PY, 'flat215_demo.py'], {'FLAT215_DEMO_OUT': out, **extra})
    if st['rc'] != 0:
        return st, {}
    d = json.load(open(os.path.join(out, 'demo-data.json'), encoding='utf-8'))
    cams = {str(v.get('id', i)): v.get('cams') for i, v in enumerate(d.get('variants') or [])}
    return st, {'demo': d, 'cams': cams}


def _compose(R, S, env) -> tuple[dict, str | None]:
    """Сборщик наборов комнаты — по профилю (`composer.plugin` → `room_profile.COMPOSERS`, из кода ревизии в стенде, не
    зашито); как его звать (ключи, куда пишет) — `rules.composers[<plugin>]`. Пишет рядом, в папку стенда."""
    room = S['room']
    probe = _run(S, env, 'bank', [PY, '-c', 'import json,room_profile as RP; P=RP.load(%r); c=P["composer"]["plugin"]; '
                                          'print("COMPOSER", json.dumps([c, RP.COMPOSERS[c]]))' % room])
    line = [x for x in open(probe['log'], encoding='utf-8').read().splitlines() if x.startswith('COMPOSER ')]
    if probe['rc'] != 0 or not line:
        return probe, None
    plugin, script = json.loads(line[-1][9:])
    how = R['composers'].get(plugin)
    if not how or not script:
        _say(probe['log'], f'сборщик {plugin!r} ({script}) стенд запускать не умеет — нет rules.composers[{plugin!r}]')
        return dict(probe, rc=2), None
    out = os.path.join(S['stand'], 'out', how.get('out') or f'bank-{room}.json')
    with heavy(R, S, 'bank', R['memory']['bank_gb']):     # сборщик — один процесс (compose2 --bands all ~2 ГБ, потоки)
        st = _run(S, env, 'bank', [PY, os.path.join(S['repo'], script), *how['args']], {how['out_env']: out})
    st['seconds'] += probe['seconds']
    st['composer'] = plugin
    if st['rc'] != 0:
        return st, None
    S['bank_out'] = out
    return st, out


def step_bank(R, S, env) -> tuple[dict, dict]:
    st, out = _compose(R, S, env)
    if not out:
        return st, {}
    bank = json.load(open(out, encoding='utf-8'))
    rp = os.path.splitext(out)[0] + '.report.json'                      # отчёт сборщика комнаты (пустые назначения, меши)
    if os.path.exists(rp):
        bank = {'sets': bank if isinstance(bank, list) else bank.get('sets', bank), 'report': json.load(open(rp, encoding='utf-8'))}
    return st, {'bank': bank}


def step_exam(R, S, env) -> tuple[dict, dict]:
    """Экзамен комнаты (`bedroom_exam.py` / `hall_exam.py`): сцены → солвер → строки с раскладкой + сводка. Гейт FAIL (rc 1 при
    готовой сводке) — результат, а не поломка: попадает в артефакт; поломка — нет сводки."""
    ex = R['rooms'][S['room']]['exam']
    sc = os.path.join(S['repo'], 'tools', 'scout')
    with heavy(R, S, 'exam'):
        st = _run(S, env, 'exam', [PY, ex['script']], {f"{ex['env']}_OUT": os.path.join(S['stand'], 'out', 'exam'),
                                                      f"{ex['env']}_SUFFIX": '-parity'})
    summ = os.path.join(sc, f"{ex['report']}-parity.json")
    rows_p = os.path.join(sc, f"{ex['report']}-parity.jsonl")
    if not os.path.exists(summ):
        return dict(st, rc=st['rc'] or 2), {}
    rows = [json.loads(ln) for ln in open(rows_p, encoding='utf-8') if ln.strip()]
    st = dict(st, exam_rc=st['rc'], rc=0)
    return st, {'exam': {'rows': sorted(rows, key=lambda r: str(r.get('id'))), 'summary': json.load(open(summ, encoding='utf-8'))}}


RUNNERS = {'catalog': step_catalog, 'smoke': step_smoke, 'demo': step_demo, 'bank': step_bank, 'exam': step_exam}


# ---------------------------------------------------------------- база: какие таблицы читали и их отпечаток

LIVE_DB = 'remlab'


def _psql(sql: str, db: str = LIVE_DB) -> list:
    r = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', db,
                        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f'],
                       input=sql, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'БД: {r.stderr[:300]}')
    return [ln.split('\x1f') for ln in r.stdout.rstrip('\n').split('\n') if ln]   # не strip(): \x1f — «пробел» для str.strip


def db_scans(db: str) -> dict:
    """Счётчики чтений таблиц замороженной копии — её читает только стенд, поэтому прирост = ровно то, что прочёл прогон."""
    return {r[0]: int(r[1] or 0) + int(r[2] or 0) for r in _psql(
        "select relname, seq_scan, idx_scan from pg_stat_user_tables where schemaname='public'", db)}


def freeze_db(stamp: str) -> dict:
    """Копия базы на один момент (pg_dump — один снимок транзакции) в отдельную базу того же контейнера, только чтение.
    Живая база не меняется: pg_dump только читает. Удаление копий — уборка ведущего (`drop database <имя>`)."""
    name = 'remlab_parity_' + re.sub(r'\D', '_', stamp)
    _psql(f'create database {name}', 'postgres')
    t = time.time()
    r = subprocess.run(['docker', 'exec', 'remlab-devdb', 'sh', '-c',
                        f'pg_dump -U remlab -d {LIVE_DB} --no-owner --no-privileges | psql -U remlab -d {name} -q -v ON_ERROR_STOP=1'],
                       capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f'копия базы {name} не снялась: {r.stderr[-400:]}')
    _psql(f'alter database {name} set default_transaction_read_only = on', 'postgres')   # скрытая запись прогона — громкая ошибка
    size = _psql(f"select pg_size_pretty(pg_database_size('{name}'))", 'postgres')[0][0]
    return {'name': name, 'seconds': round(time.time() - t, 1), 'size': size}


def db_fingerprint(tables, db: str = LIVE_DB) -> dict:
    out = {}
    for t in sorted(tables):
        if not re.fullmatch(r'[a-z_][a-z0-9_]*', t):
            continue
        r = _psql(f'select count(*), coalesce(md5(string_agg(md5(x::text), \'\' order by md5(x::text))), \'\') from "{t}" x', db)
        out[t] = f'{r[0][0]}:{r[0][1]}'
    return out


# ---------------------------------------------------------------- журнал сторожа

def trace_summary(S: dict, R: dict) -> dict:
    stand = os.path.realpath(S['stand'])
    repo = os.path.realpath(S['repo'])
    ok_ext = [os.path.realpath(os.path.expanduser(p)) for p in R['trace']['external_ok']] \
        + [os.path.realpath(os.path.join(S['manifest']['main'], 'node_modules')),      # зависимости — ссылкой, только чтение
           os.path.realpath(os.path.join(S['data'], 'net'))]      # записи сети — вход «сеть» (хеш ответа в inputs.net), не файл
    reads, missing, outside, denied, net, miss, sock = {}, set(), set(), [], {}, set(), set()
    db_routed, db_other = 0, set()
    tdir = os.path.join(stand, '_trace')
    for f in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        for ln in open(os.path.join(tdir, f), encoding='utf-8'):
            try:
                e = json.loads(ln)
            except ValueError:
                continue
            k = e['k']
            if k == 'read':
                p = e['path']
                if p.startswith(repo + os.sep):
                    rel = os.path.relpath(p, repo)
                    if not e['exists']:
                        missing.add(rel)
                    else:
                        reads[rel] = True
                elif not p.startswith(stand + os.sep) and not any(p == o or p.startswith(o + os.sep) for o in ok_ext) \
                        and e['exists'] and os.path.isfile(p):
                    outside.add(p)
            elif k == 'deny':
                denied.append(f"{e['op']} {e['path']}")
            elif k == 'net':
                net[e['url']] = e['ok']
            elif k == 'net_miss':
                miss.add(e['url'])
            elif k == 'socket':
                sock.add(e['addr'])
            elif k == 'db':
                if e['routed']:
                    db_routed += 1
                else:
                    db_other.add(' '.join(e['argv'])[:200])
    man = S['manifest']['files']
    files_read = {rel: man[rel] for rel in reads if rel in man}
    miss_ok = R['trace']['missing_ok']
    missing = sorted(m for m in missing if not any(fnmatch.fnmatch(m, g) for g in miss_ok))
    return {'files_read': files_read, 'outside': {p: sha_file(p) for p in sorted(outside)}, 'missing': missing,
            'denied': sorted(set(denied)), 'net': net, 'net_miss': sorted(miss), 'sockets': sorted(sock),
            'db_routed': db_routed, 'db_other': sorted(db_other)}


def net_inputs(S: dict, urls) -> dict:
    import parity_guard as PGd
    out = {}
    for u in sorted(urls):
        p = os.path.join(S['data'], 'net', PGd.net_key(u) + '.json')
        out[u] = json.load(open(p, encoding='utf-8')).get('sha', 'err') if os.path.exists(p) else None
    return out


# ---------------------------------------------------------------- прогон

def run_all(R: dict, room: str, rev: str, data: str, steps: list, tag: str, net: str, inject: list) -> dict:
    S = build_stand(R, rev, data, f'{tag}-{room}', inject)
    S['room'] = room
    env = stand_env(R, S, net)
    print(f'стенд: {S["stand"]} · комната {room} · код {rev} ({S["sha"][:12]}) · данные {os.path.basename(data)} · сеть {net}', flush=True)
    db = data_db(S['manifest'])
    scans0 = db_scans(db)
    roots = {'STAND': os.path.realpath(S['stand']), 'MAIN': S['manifest']['main'], 'HOME': os.path.expanduser('~')}
    noise = set(R['noise']['keys'])
    subs = subs_for(R, roots)
    res = {'version': VERSION, 'room': room, 'at': time.strftime('%Y-%m-%d %H:%M:%S'), 'rev': rev, 'sha': S['sha'], 'data': data,
           'stand': S['stand'], 'steps': {}, 'artifacts': {}, 'inject': inject, 'clash': S['clash']}
    dumps = os.path.join(S['stand'], 'dumps')
    os.makedirs(dumps, exist_ok=True)
    rr = R['rooms'][room]
    for s, why in rr.get('skip', {}).items():
        if s in steps:
            print(f'  шаг {s}: ПРОПУЩЕН — {why}', flush=True)
            res.setdefault('skipped', {})[s] = why
    wanted = [s for s in rr['steps'] if s in RUNNERS and (s in steps or (s == 'demo' and 'cams' in steps))]
    for s in wanted:
        print(f'  шаг {s}…', flush=True)
        st, arts = RUNNERS[s](R, S, env)
        res['steps'][s] = st
        print(f"  шаг {s}: rc {st['rc']}, {st['seconds']} с, журнал {st['log']}", flush=True)
        for name, obj in arts.items():
            if name not in steps:
                continue
            norm = normalize(obj, noise | set(R['noise'].get(name, [])), subs)
            dump = os.path.join(dumps, f'{name}.json')
            json.dump(norm, open(dump, 'w', encoding='utf-8'), ensure_ascii=False)
            its = items_of(name, norm)
            if is_empty(name, norm):
                res.setdefault('empty', []).append(name)
            res['artifacts'][name] = {'sha': sha_obj(norm), 'n': len(its), 'dump': dump,
                                      'items': {k: sha_obj(v) for k, v in its.items()}}
    scans1 = db_scans(db)
    read_tables = {t for t, n in scans1.items() if n > scans0.get(t, 0)} - set(R['db']['ignore'])
    tr = trace_summary(S, R)
    res['trace'] = {k: v for k, v in tr.items() if k not in ('files_read', 'outside', 'net')} | {
        'n_files_read': len(tr['files_read']), 'n_outside': len(tr['outside']), 'n_net': len(tr['net'])}
    res['inputs'] = {'files': tr['files_read'], 'external': tr['outside'], 'db_tables': sorted(read_tables),
                     'net': net_inputs(S, tr['net']), 'db_name': db}
    json.dump(res, open(os.path.join(S['stand'], 'result.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


def is_empty(name: str, obj) -> bool:
    """Пустой каталог комнаты или банк без наборов: эталон на таких данных ничего не проверяет (T-54: заморозка раньше загрузки
    прихожей в room_catalog — 0 товаров, 0 наборов, «равно» было бы враньём)."""
    if name == 'catalog':
        return not obj.get('items')
    if name == 'bank':
        sets = obj.get('sets', obj) if isinstance(obj, dict) else obj
        return isinstance(sets, list) and not sets
    return False


def _problems(res: dict) -> list:
    out = [f"шаг {s} упал (rc {st['rc']}, {st['log']})" for s, st in res['steps'].items() if st['rc'] != 0]
    out += [f'{n}: пусто — данных комнаты в заморозке нет (переморозить после загрузки)' for n in res.get('empty', [])]
    t = res['trace']
    out += [f'сторож: запрещённая запись {d}' for d in t['denied'][:10]]
    return out


def _print_trace(res: dict) -> None:
    t = res['trace']
    if t['missing']:
        print(f"  ВНИМАНИЕ: код искал {len(t['missing'])} входов, которых нет в копии (не заморожены?): "
              + ', '.join(t['missing'][:8]), flush=True)
    if t['n_outside']:
        print(f"  входы вне копии (хешированы в эталон): {t['n_outside']}", flush=True)
    if t['net_miss']:
        print(f"  сеть: запросов без записи {len(t['net_miss'])}: " + ', '.join(t['net_miss'][:5]), flush=True)
    if t.get('db_other'):
        print(f"  ВНИМАНИЕ: вызовы базы мимо копии ({len(t['db_other'])}): " + ' | '.join(t['db_other'][:3]), flush=True)
    if t['sockets']:
        print(f"  ВНИМАНИЕ: соединения мимо записи сети: {', '.join(t['sockets'][:5])}", flush=True)


def check_stale(ref: dict) -> list:
    """Входы эталона сейчас: файлы данных, что прочли (в замороженной папке), файлы вне копии, таблицы БД."""
    data, inp = ref['data'], ref['inputs']
    now = {'files': {rel: sha_file(os.path.join(data, 'files', rel)) for rel in inp['files']
                     if os.path.exists(os.path.join(data, 'files', rel))},
           'external': {p: (sha_file(p) if os.path.isfile(p) else None) for p in inp['external']},
           'db': db_fingerprint(inp['db_tables'], inp.get('db_name', LIVE_DB))}
    return stale_inputs({k: inp.get(k) for k in ('files', 'external', 'db')}, now)


def _print_stale(stale: list) -> None:
    print(f'ЭТАЛОН УСТАРЕЛ: входы сменились ({len(stale)}) — переснимите snapshot на текущих данных:')
    for x in stale[:12]:
        print(f"  {x['kind']}: {x['key']}")


def merge_ref(old: dict, new: dict) -> dict:
    """Эталон пачками (--into): шаги и артефакты дописываются, входы объединяются."""
    if old.get('room', 'living') != new.get('room', 'living'):
        raise SystemExit(f"--into: эталон комнаты {old.get('room', 'living')}, пачка — {new.get('room')}")
    out = dict(old)
    out['steps'] = {**old['steps'], **new['steps']}
    out['skipped'] = {**old.get('skipped', {}), **new.get('skipped', {})}
    out['empty'] = sorted(set(old.get('empty', [])) | set(new.get('empty', [])))
    out['artifacts'] = {**old['artifacts'], **new['artifacts']}
    out['stands'] = old.get('stands', [old['stand']]) + [new['stand']]
    t0, t1 = old['trace'], new['trace']
    out['trace'] = {k: sorted(set(t0.get(k, [])) | set(t1.get(k, []))) for k in ('missing', 'denied', 'net_miss', 'sockets',
                                                                                  'db_other')} | {
        k: t0.get(k, 0) + t1.get(k, 0) for k in ('n_files_read', 'n_outside', 'n_net', 'db_routed')}
    i0, i1 = old['inputs'], new['inputs']
    out['inputs'] = {'files': {**i0['files'], **i1['files']}, 'external': {**i0['external'], **i1['external']},
                     'net': {**i0['net'], **i1['net']}, 'db_tables': sorted(set(i0['db_tables']) | set(i1['db_tables'])),
                     'db_name': i0.get('db_name', LIVE_DB)}
    return out


def cmd_snapshot(R: dict, argv: list) -> int:
    into = _arg(argv, '--into')
    old = json.load(open(into, encoding='utf-8')) if into else None
    room = old.get('room', 'living') if old else _arg(argv, '--room', 'living')
    steps = _steps(argv, R, room)
    if into:                                  # пачка к уже снятому эталону: те же данные и тот же код, входы не сменились
        stale = check_stale(old)
        if stale:
            _print_stale(stale)
            return 3
        rev, data = old['sha'], old['data']
    else:
        rev = _arg(argv, '--rev', 'main')
        data = _arg(argv, '--data') or freeze(R)
    res = run_all(R, room, rev, data, steps, 'ref', 'record', [])
    if into:
        res = merge_ref(old, res)
    res['inputs']['db'] = db_fingerprint(res['inputs']['db_tables'], res['inputs']['db_name'])
    bad = _problems(res)
    _print_trace(res)
    ref = into or os.path.join(home(R), f"{room}-{time.strftime('%Y%m%d-%H%M%S')}.json")
    res['ref_path'] = ref
    json.dump(res, open(ref, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f"эталон: {ref} · комната {room} · артефакты: " + ', '.join(f"{k} {v['n']}" for k, v in res['artifacts'].items())
          + ''.join(f' · {s} пропущен' for s in res.get('skipped', {})))
    if bad:
        print('ЭТАЛОН НЕГОДЕН:\n  ' + '\n  '.join(bad))
        return 2
    return 0


def diff_artifacts(ref: dict, now: dict, steps) -> tuple[dict, int]:
    """Артефакты эталона против текущих ({имя: {sha, n, dump}}) → ({имя: сводка различий}, всего различий)."""
    out, total = {}, 0
    for name in steps:
        a, b = ref['artifacts'].get(name), now.get(name)
        if not b:
            out[name] = {'diff': None, 'why': 'не собран'}
            total += 1
            continue
        if a['sha'] == b['sha']:
            out[name] = {'diff': 0, 'n': b['n']}
            continue
        c = compare_items(items_of(name, json.load(open(a['dump'], encoding='utf-8'))),
                          items_of(name, json.load(open(b['dump'], encoding='utf-8'))))
        out[name] = c
        total += c['diff']
    return out, total


def print_artifacts(arts: dict) -> None:
    for name, c in arts.items():
        if c.get('diff') == 0:
            print(f"  {name}: равно ({c['n']} элементов)")
        elif c.get('diff') is None:
            print(f"  {name}: НЕ СОБРАН")
        else:
            print(f"  {name}: РАЗЛИЧИЙ {c['diff']} (только в эталоне {c['n_only_ref']}, только сейчас {c['n_only_now']}, "
                  f"разные {c['n_changed']})")
            if c['only_ref']:
                print(f"    пропали: {', '.join(c['only_ref'][:5])}" + (' …' if c['n_only_ref'] > 5 else ''))
            if c['only_now']:
                print(f"    появились: {', '.join(c['only_now'][:5])}" + (' …' if c['n_only_now'] > 5 else ''))
            for ch in c['changed'][:3]:
                f0 = ch['first'][0] if ch['first'] else {}
                print(f"    {ch['id']}: {f0.get('path')} было {f0.get('ref')!r} → стало {f0.get('now')!r}")


def cmd_diff(R: dict, argv: list) -> int:
    """Сверка уже прогнанного стенда (его `dumps/`) с эталоном без пересчёта — например, прерванной сверки: что успело."""
    ref_p, run = _arg(argv, '--ref'), _arg(argv, '--run')
    if not ref_p or not run:
        raise SystemExit('diff --ref <комната-….json> --run <папка стенда run-…>')
    ref = json.load(open(ref_p, encoding='utf-8'))
    now = {}
    for f in sorted(os.listdir(os.path.join(run, 'dumps'))):
        name = f[:-5]
        if name in ref['artifacts']:
            obj = json.load(open(os.path.join(run, 'dumps', f), encoding='utf-8'))
            now[name] = {'sha': sha_obj(obj), 'n': len(items_of(name, obj)), 'dump': os.path.join(run, 'dumps', f)}
    steps = [s for s in ref['artifacts'] if s in now]
    missing = [s for s in ref['artifacts'] if s not in now]
    arts, total = diff_artifacts(ref, now, steps)
    print_artifacts(arts)
    if missing:
        print(f"  не досчитано в {os.path.basename(run)}: {', '.join(missing)}")
    out = os.path.join(run, 'parity-report-diff.json')
    json.dump({'ref': ref_p, 'run': run, 'artifacts': arts, 'missing': missing}, open(out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print(f'отчёт: {out}')
    return 0 if total == 0 else 1


def cmd_compare(R: dict, argv: list) -> int:
    ref_p = _arg(argv, '--ref')
    if not ref_p:
        raise SystemExit('--ref <комната-….json> обязателен')
    ref = json.load(open(ref_p, encoding='utf-8'))
    if ref.get('version') != VERSION:
        print(f"эталон версии {ref.get('version')}, стенд {VERSION} — переснимите snapshot")
        return 3
    room = ref.get('room', 'living')                  # эталоны T-41 — без поля: гостиная
    steps = [s for s in _steps(argv, R, room) if s in ref['artifacts']]
    for s, why in R['rooms'][room].get('skip', {}).items():
        print(f'  шаг {s}: ПРОПУЩЕН — {why}')
    data = ref['data']
    stale = check_stale(ref)
    if stale:
        _print_stale(stale)
        return 3
    if ref['inputs'].get('db_name', LIVE_DB) != LIVE_DB:   # справка: сверка идёт на заморозке; живые данные могли уйти вперёд
        drift = stale_inputs({'db': ref['inputs']['db']}, {'db': db_fingerprint(ref['inputs']['db_tables'])})
        frozen = json.load(open(os.path.join(data, 'manifest.json'), encoding='utf-8'))['frozen_at']
        print(f"данные заморожены {frozen}; живая база с тех пор сменилась в {len(drift)} из {len(ref['inputs']['db_tables'])} "
              f"прочитанных таблиц" + (f" ({', '.join(d['key'] for d in drift[:6])}) — сверка честная (те же входы), "
                                      f"но эталон описывает не сегодняшний каталог" if drift else ''))
    res = run_all(R, room, _arg(argv, '--rev', 'WORKTREE'), data, steps, 'cmp', 'replay', _args(argv, '--inject'))
    _print_trace(res)
    bad = _problems(res)
    late = stale_inputs({'db': ref['inputs']['db']}, {'db': db_fingerprint(ref['inputs']['db_tables'], ref['inputs'].get('db_name', LIVE_DB))})
    report = {'ref': ref_p, 'room': room, 'now': os.path.join(res['stand'], 'result.json'), 'rev': res['rev'], 'sha': res['sha'],
              'problems': bad, 'db_changed_during_run': late, 'artifacts': {}}
    report['artifacts'], total = diff_artifacts(ref, res['artifacts'], steps)
    out = os.path.join(res['stand'], 'parity-report.json')
    json.dump(report, open(out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print_artifacts(report['artifacts'])
    if late:
        print(f'ВНИМАНИЕ: БД сменилась за время сверки ({len(late)} таблиц) — различия могут быть от данных')
    print(f'отчёт: {out}')
    if bad:
        print('СВЕРКА НЕГОДНА:\n  ' + '\n  '.join(bad))
        return 2
    if late:
        return 3
    return 0 if total == 0 else 1


def _arg(argv, k, default=None):
    return argv[argv.index(k) + 1] if k in argv else default


def _args(argv, k) -> list:
    return [argv[i + 1] for i, a in enumerate(argv) if a == k and i + 1 < len(argv)]


def _steps(argv, R: dict, room: str) -> list:
    """Шаги комнаты (`rules.rooms.<комната>.steps` + явно пропускаемые `skip`); `--steps` — подмножество."""
    if room not in R['rooms']:
        raise SystemExit(f"комната {room!r}? стенд знает {', '.join(R['rooms'])} (rules.rooms)")
    rr = R['rooms'][room]
    known = list(rr['steps']) + list(rr.get('skip', {}))
    s = _arg(argv, '--steps')
    out = known if not s else [x.strip() for x in s.split(',') if x.strip()]
    bad = [x for x in out if x not in known]
    if bad:
        raise SystemExit(f'шаги {bad} у комнаты {room} нет; есть {known}')
    return out


# ---------------------------------------------------------------- самопроверка (без базы и сети)

def _raises(f) -> bool:
    try:
        f()
    except SystemExit:
        return True
    return False


def selftest() -> int:
    import tempfile
    bad = 0
    os.makedirs(os.path.expanduser('~/.cache'), exist_ok=True)   # временные папки — не в /tmp (квота DEV, урок 528); в CI HOME пуст

    def ok(name, cond):
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += not cond
    R = rules()
    roots = {'STAND': '/x/run-1', 'MAIN': '/home/u/remlab'}
    subs = subs_for(R, roots)
    noise = set(R['noise']['keys'])
    a = {'scene': 's1', 'duration_s': 3.1, 'path': '/x/run-1/repo/tools/scout/v.json', 'p': [{'x': 1, 'duration_s': 9}]}
    b = {'scene': 's1', 'duration_s': 7.4, 'path': '/x/run-2/repo/tools/scout/v.json', 'p': [{'x': 1, 'duration_s': 2}]}
    roots2 = dict(roots, STAND='/x/run-2')
    ok('шум: время и путь стенда не различие', normalize(a, noise, subs) == normalize(b, noise, subs_for(R, roots2)))
    c = dict(b, p=[{'x': 2, 'duration_s': 2}])
    na, nc = normalize(a, noise, subs), normalize(c, noise, subs_for(R, roots2))
    ok('подмешанное различие видно', na != nc and leaf_diff(na, nc) == [{'path': '.p[0].x', 'ref': 1, 'now': 2}])
    ref = {'report': [{'scene': 's1', 'ok': True}, {'scene': 's2', 'ok': True}], 'layouts': {'v3set1-layout-acc-zoned-s1.json': {'x': 1}},
           'manifest': ['s1', 's2']}
    now = {'report': [{'scene': 's1', 'ok': True}, {'scene': 's3', 'ok': True}], 'layouts': {'v3set1-layout-acc-zoned-s1.json': {'x': 2}},
           'manifest': ['s1', 's3']}
    cmp = compare_items(items_of('smoke', ref), items_of('smoke', now))
    ok('сверка по элементам: только там, только тут, разные',
       cmp['only_ref'] == ['report/s2'] and cmp['only_now'] == ['report/s3'] and cmp['n_changed'] == 2 and cmp['diff'] == 4)
    ok('равные артефакты — 0', compare_items(items_of('smoke', ref), items_of('smoke', json.loads(json.dumps(ref))))['diff'] == 0)
    dm = {'variants': [{'id': 'a', 'cams': [1]}, {'id': 'b'}], 'feeds': {'диван': [1]}, 'room': {'w': 1}}
    ok('демо: варианты и ленты — отдельные элементы', set(items_of('demo', dm)) == {'variants/a', 'variants/b', 'feeds/диван', 'room'})
    ri = {'files': {'tools/scout/sets3.json': 'a'}, 'db': {'products': '10:x'}, 'external': {}}
    ok('входы те же — не устарел', stale_inputs(ri, json.loads(json.dumps(ri))) == [])
    st = stale_inputs(ri, {'files': {'tools/scout/sets3.json': 'a'}, 'db': {'products': '11:y'}})
    ok('таблица сменилась — эталон устарел', [s['key'] for s in st] == ['products'])
    ok('файл пропал — эталон устарел', stale_inputs(ri, {'files': {}, 'db': ri['db']})[0]['key'] == 'tools/scout/sets3.json')
    with tempfile.TemporaryDirectory(dir=os.path.expanduser('~/.cache')) as td:
        import threading
        import heavy_slot as HS
        os.makedirs(os.path.join(td, 'logs'))
        mi = os.path.join(td, 'meminfo')
        put = lambda gb: open(mi, 'w').write(f'MemAvailable: {int(gb * 1048576)} kB\n')  # noqa: E731
        put(2.0)
        keep = {k: os.environ.get(k) for k in ('HEAVY_SLOT_DIR', 'HEAVY_SLOT_LOG', 'HEAVY_SLOT_MEMINFO', 'HEAVY_SLOT_HELD')}
        os.environ.update(HEAVY_SLOT_DIR=os.path.join(td, 'slot'), HEAVY_SLOT_LOG=os.path.join(td, 'slot.log'), HEAVY_SLOT_MEMINFO=mi)
        os.environ.pop('HEAVY_SLOT_HELD', None)
        try:
            threading.Timer(0.3, put, (7.0,)).start()
            with heavy({'memory': dict(R['memory'], poll_s=0.05, report_s=10)}, {'stand': td, 'room': 'hall'}, 'bank', 6) as free:
                inside = HS.is_held() and _held_env() == {'HEAVY_SLOT_HELD': str(os.getpid())}
            lines = open(os.path.join(td, 'logs', 'bank.log'), encoding='utf-8').read()
            ok('память: тяжёлый шаг — через общую очередь (heavy_slot): ждёт ≥ 6 ГБ, держит слот на шаг, потомкам — HEAVY_SLOT_HELD',
               free == 7.0 and inside and not HS.is_held() and 'ждёт память' in lines and 'взял' in lines
               and 'parity-hall-bank' in open(os.path.join(td, 'slot.log'), encoding='utf-8').read())
        finally:
            for k, v in keep.items():
                os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    ok('память: солверов смоука — сколько помещается сверх порога, не меньше одного',
       smoke_workers(R, 6.0) == 1 and smoke_workers(R, 30.0) == R['acc_workers'])
    # комнаты (T-54): шаги из правил, сборщик — по профилю, у каждого плагина профиля есть «как звать»
    import room_profile as RP
    rooms_ok = True
    for room, rr in R['rooms'].items():
        plugin = RP.load(room)['composer']['plugin']
        rooms_ok &= set(rr['steps']) <= set(STEPS) and not set(rr['steps']) & set(rr.get('skip', {})) \
            and plugin in R['composers'] and bool(RP.COMPOSERS.get(plugin)) and ('bank' in rr['steps'])
        if 'exam' in rr['steps']:
            rooms_ok &= os.path.exists(os.path.join(HERE, rr['exam']['script']))
    ok('комнаты: шаги известны, пропуски не пересекаются с шагами, сборщик профиля стенд звать умеет', rooms_ok)
    ok('комнаты: у прихожей demo/cams — явный пропуск; у спальни — шаг; лишний шаг — отказ',
       _steps([], R, 'hall')[-2:] == ['demo', 'cams'] and 'demo' in _steps([], R, 'bedroom')
       and _steps(['--steps', 'bank,exam'], R, 'hall') == ['bank', 'exam']
       and _raises(lambda: _steps(['--steps', 'smoke'], R, 'hall')) and _raises(lambda: _steps([], R, 'kitchen9')))
    rb = {'sets': [{'cell': 'bedroom-1|master|eco|scandi|base', 'slots': [1]}, {'cell': 'bedroom-1|master|eco|scandi|base'},
                   {'cell': 'b|x', 'slots': []}], 'report': {'empty': ['кабинет']}}
    ok('банк комнаты: по ячейке (повтор — с номером) + отчёт сборщика', set(items_of('bank', rb)) == {
        'set/bedroom-1|master|eco|scandi|base', 'set/bedroom-1|master|eco|scandi|base#1', 'set/b|x', 'report'})
    ex = {'rows': [{'id': 's1', 'pass': True, 'seconds': 1.2}, {'id': 's2', 'pass': False}],
          'summary': {'gate': 'PASS', 'slow': [], 'max_seconds': 1.2, 'solve': '1/1'}}
    ex2 = json.loads(json.dumps(ex))
    ex2['rows'][0]['seconds'], ex2['summary'].update(gate='FAIL', slow=['s1'], max_seconds=11.0)
    nz = noise | set(R['noise']['exam'])
    ok('пусто: каталог без товаров и банк без наборов — эталон негоден, отчёт сборщика без наборов — тоже',
       is_empty('catalog', {'items': []}) and is_empty('bank', {'sets': [], 'report': {}}) and is_empty('bank', [])
       and not is_empty('catalog', {'items': [1]}) and not is_empty('bank', rb) and not is_empty('exam', ex)
       and _problems({'steps': {}, 'trace': {'denied': []}, 'empty': ['catalog']})[0].startswith('catalog: пусто'))
    ok('экзамен: строки по сцене + сводка; время и производный гейт — шум',
       set(items_of('exam', ex)) == {'row/s1', 'row/s2', '_summary'}
       and normalize(ex, nz, subs) == normalize(ex2, nz, subs))
    ex2['rows'][1]['pass'] = True
    ok('экзамен: сцена сменила исход — различие', compare_items(items_of('exam', normalize(ex, nz, subs)),
                                                             items_of('exam', normalize(ex2, nz, subs)))['diff'] == 1)
    F = R['freeze']
    ok('ключи: .env* не замораживаются и не копируются ни по какому пути (в т.ч. новые: экзамены, банки комнат)',
       not any(frozen_rel(F, p) for p in ('tools/scout/.env', 'tools/scout/.env.local', 'services/planner-solver/.env',
                                           'tools/scout/rooms/x/.env.bak', '.env.example', 'tools/scout/bedroom-exam-0105/.env'))
       and not any(frozen_rel(F, p) for p in ('tools/scout/bedroom-exam-report.jsonl', 'tools/scout/hall-exam-1105-2100/a.png',
                                               'tools/scout/sets-bedroom.next.json', 'tools/scout/sets-hall.next.report.json'))
       and frozen_rel(F, 'tools/scout/style-scores-bedroom.json') and frozen_rel(F, 'tools/scout/sets3.json'))
    with tempfile.TemporaryDirectory(dir=os.path.expanduser('~/.cache')) as td:
        os.makedirs(os.path.join(td, 'a', 'b'))
        open(os.path.join(td, 'a', 'b', '.env.x'), 'w').close()
        open(os.path.join(td, 'a', 'ok.json'), 'w').close()
        ok('ключи: проверка папки стенда находит .env* на любой глубине', key_files_in(td) == [os.path.join('a', 'b', '.env.x')])
    import parity_guard as PGr
    live =['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-tA']
    ok('база: `-d remlab` → копия; без -d — копия; `-d postgres` — не трогаем; строка shell — тоже; не база — None',
       PGr.route_db(live, 'cp') == (live[:8] + ['cp', '-tA'], True)
       and PGr.route_db(live[:5] + ['-tA'], 'cp')[0][5:7] == ['-d', 'cp']
       and PGr.route_db(live[:7] + ['-d', 'postgres'], 'cp') == (live[:7] + ['-d', 'postgres'], False)
       and PGr.route_db('docker exec -i remlab-devdb psql -U remlab -d remlab -c x', 'cp')
       == ('docker exec -i remlab-devdb psql -U remlab -d cp -c x', True)
       and PGr.route_db(['ls', '-d', 'remlab'], 'cp') == (['ls', '-d', 'remlab'], None))
    # сторож: отдельный процесс со сторожем — запись мимо стенда, копия при записи в жёсткую ссылку, сеть
    with tempfile.TemporaryDirectory(dir=os.path.expanduser('~/.cache')) as td:
        stand, outside, frozen = (os.path.join(td, x) for x in ('stand', 'outside', 'frozen'))
        for d in (stand, outside, frozen, os.path.join(stand, '_site')):
            os.makedirs(d)
        open(os.path.join(frozen, 'f.json'), 'w').write('{"v": 1}')
        os.link(os.path.join(frozen, 'f.json'), os.path.join(stand, 'f.json'))
        import parity_guard as PGd
        open(os.path.join(stand, '_site', 'sitecustomize.py'), 'w').write(PGd.SITECUSTOMIZE)
        page = os.path.join(td, 'page.txt')
        open(page, 'w').write('ответ')
        env = dict(os.environ, PARITY_ROOT=stand, PARITY_GUARD=GUARD, PARITY_DENY=frozen + os.pathsep + outside,
                   PARITY_ALLOW='', PYTHONPATH=os.path.join(stand, '_site'), PARITY_NET='record',
                   PARITY_NET_DIR=os.path.join(frozen, 'net'))    # как на стенде: запись сети внутри замороженных данных
        code = ('import json,os,urllib.request\n'
                'r={}\n'
                'try:\n open(%r,"w").write("x"); r["outside"]="written"\n'
                'except PermissionError: r["outside"]="denied"\n'
                'open("f.json","w").write(\'{"v": 2}\')\n'
                'r["read"]=open("nope.json").read() if os.path.exists("nope.json") else "none"\n'
                'r["net"]=urllib.request.urlopen("file://%s?v=123").read().decode()\n'
                'print(json.dumps(r))\n') % (os.path.join(outside, 'leak.txt'), page)
        p = subprocess.run([sys.executable, '-c', code], cwd=stand, env=env, capture_output=True, text=True)
        r = json.loads(p.stdout or '{}') if p.returncode == 0 else {}
        ok('сторож: запись вне стенда — отказ', r.get('outside') == 'denied' and not os.path.exists(os.path.join(outside, 'leak.txt')))
        ok('сторож: запись в жёсткую ссылку не портит замороженный файл',
           open(os.path.join(frozen, 'f.json')).read() == '{"v": 1}' and open(os.path.join(stand, 'f.json')).read() == '{"v": 2}')
        ok('сеть: запись ответа', r.get('net') == 'ответ')
        open(page, 'w').write('другой ответ')
        env['PARITY_NET'] = 'replay'
        code2 = ('import urllib.request,urllib.error\n'
                 'print(urllib.request.urlopen("file://%s?v=999").read().decode())\n'
                 'try:\n urllib.request.urlopen("file://%s/none")\nexcept urllib.error.URLError: print("miss")\n') % (page, td)
        p2 = subprocess.run([sys.executable, '-c', code2], cwd=stand, env=env, capture_output=True, text=True)
        ok('сеть: воспроизведение — ответ эталона, «мимо кэша» v= не мешает; нет записи — отказ',
           p2.stdout.split() == ['ответ', 'miss'])
        tr = ''.join(open(os.path.join(stand, '_trace', f)).read() for f in os.listdir(os.path.join(stand, '_trace')))
        ok('журнал: запрет, чтение отсутствующего входа нет (exists-проверка), промах сети',
           '"deny"' in tr and '"net_miss"' in tr)
    print('selftest:', 'OK' if not bad else f'{bad} FAIL')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return selftest()
    if not argv:
        print(__doc__)
        return 1
    R = rules()
    os.makedirs(home(R), exist_ok=True)
    cmd = argv[0]
    if cmd == 'freeze':
        freeze(R)
        return 0
    if cmd == 'snapshot':
        return cmd_snapshot(R, argv[1:])
    if cmd == 'compare':
        return cmd_compare(R, argv[1:])
    if cmd == 'diff':
        return cmd_diff(R, argv[1:])
    raise SystemExit(f'команда {cmd}? есть freeze | snapshot | compare | diff | --selftest')


if __name__ == '__main__':
    sys.path.insert(0, HERE)
    sys.exit(main(sys.argv[1:]))

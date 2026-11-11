#!/usr/bin/env python3
"""Регресс разбора планировок ПО КОМНАТАМ (T-20261110-38/3): два кода на одних листах → комнаты, двери, окна и ядро спальни.
  python tools/floorplan/regress.py snapshot <коммит> <папка>              код коммита (`git archive`) — сторона «до»
  python tools/floorplan/regress.py run <код> <папка> [--cases f.tsv] [--no-trial] [--only a,b] [-j 4] [--env K=V] [--no-cache]
                                                                        прогон листов из кэша VLM (0 $) → <папка>/<лист>/result.json;
                                         лист с тем же отпечатком входов (код разбора, --env, питон и пакеты, лист, ответы VLM) —
                                         готовым из общего кэша `~/remlab-logs/regress-cache` (`regress_cache.py`, T-20261111-18)
  python tools/floorplan/regress.py cmp <до> <после> [--accept f.tsv] [--all]   таблица; rc 1 — есть «сломано», 3 — один и тот же код

Листы — `~/remlab-logs/trial/*/a1-*` (загрузки проб, как T-38) и строки `--cases` (TSV: имя, лист, объявление|-, [папка VLM]).
Папка VLM — прогон `pipeline.run(cache_only)` прямо с неё (лист «Этажи»: кэш labels4 вне общего), иначе — `pipeline.py job
--cache-only` (как воркер). Тяжёлое — под общей очередью: `tools/ops/heavy-slot.sh <метка> -- python … run …`.

Почему не байты result.json: T-38/2 сравнил новый код с ним же (снимки 20:33 и 22:40 — оба после правки) и записал «21 лист байт
в байт», а /1 видел потерю дверей только суммой по листу (rgK −96) и счёл её ложными дверями. Здесь каждая папка прогона хранит
манифест с хешем кода (`code_sha`); `cmp` одного кода с собой — отказ (rc 3). Сравнение — по каждой названной комнате: двери,
окна, ядро спальни/гостиной (`trial_bundle.core_geometry`, один и тот же код страницы для обеих сторон).
Метки: СЛОМАНО — комнаты нет, у комнаты пропали все двери или все окна, ядро стало отказом, лист не собрался;
ИСПРАВЛЕНО — отказ ядра стал ядром, лист собрался; ИНАЧЕ — другое число дверей/окон/ядро (смотреть глазами; намеренное —
строкой в `--accept`: лист<TAB>комната<TAB>почему); БЕЗ ИЗМЕНЕНИЙ."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRIAL = Path(os.path.expanduser('~/remlab-logs/trial'))
VLM_CACHE = TRIAL / 'vlm-cache'
CACHE_DIR = Path(os.path.expanduser('~/remlab-logs/regress-cache'))   # общий кэш листов (`regress_cache.py`)
PY = os.environ.get('FP_PY') or sys.executable
ROOM_TOL_CM = 30.0      # проём относится к комнате, если его середина не дальше от её контура (полстены + запас)
TIMEOUT_S = 1800

# ───────────────────────── прогон ─────────────────────────


def code_sha(code: Path) -> str:
    """Хеш исходников разбора (`tools/floorplan/*.py`) — по нему `cmp` узнаёт сравнение кода с самим собой."""
    h = hashlib.sha256()
    for p in sorted((Path(code) / 'tools' / 'floorplan').glob('*.py')):
        h.update(p.name.encode() + b'\0' + p.read_bytes() + b'\0')
    return h.hexdigest()[:16]


def code_rev(code: Path) -> str | None:
    f = Path(code) / 'REV'
    if f.exists():
        return f.read_text().strip()
    try:
        rev = subprocess.run(['git', '-C', str(code), 'rev-parse', '--short', 'HEAD'], capture_output=True, text=True,
                             timeout=20).stdout.strip()
        dirty = subprocess.run(['git', '-C', str(code), 'status', '--porcelain', '--', 'tools/floorplan'], capture_output=True,
                               text=True, timeout=60).stdout.strip()
        return (rev + ('+правки' if dirty else '')) or None
    except (OSError, subprocess.SubprocessError):
        return None


def snapshot(rev: str, out: Path, repo: Path = HERE.parents[1]) -> Path:
    """Код коммита `rev` (разбор, очередь тяжёлых, шлюз VLM) → `out` + файл REV."""
    out.mkdir(parents=True, exist_ok=False)
    full = subprocess.run(['git', '-C', str(repo), 'rev-parse', rev], capture_output=True, text=True, check=True).stdout.strip()
    # scout — все модули верхнего уровня: разбор берёт оттуда шлюз VLM и его зависимости (env_keys …); отпечаток кэша
    # (`regress_cache.code_files`) у снимка тогда тот же, что у рабочей копии того же коммита
    arc = subprocess.run(['git', '-C', str(repo), 'archive', full, 'tools/floorplan', 'tools/ops', ':(glob)tools/scout/*.py'],
                         capture_output=True, check=True).stdout
    subprocess.run(['tar', '-x', '-C', str(out)], input=arc, check=True)
    (out / 'REV').write_text(full[:8] + '\n')
    return out


def trial_cases(root: Path = TRIAL) -> list[dict]:
    """Загрузки проб `<root>/<объявление>/a1-*` (лист input.*, объявление listing.txt) — набор регресса T-38."""
    out = []
    for r in sorted(root.glob('*/a1-*')):
        ins = sorted(r.glob('input.*'))
        if not ins:
            continue
        lst = r / 'listing.txt'
        out.append({'id': f'{r.parent.name}-{r.name}', 'image': str(ins[0]), 'listing': str(lst) if lst.exists() else None,
                    'vlm_dir': None})
    return out


def read_cases(path: Path) -> list[dict]:
    """TSV: имя, лист, объявление|-, [папка VLM]; `#` — комментарий."""
    out = []
    for ln in Path(path).read_text().splitlines():
        if not ln.strip() or ln.startswith('#'):
            continue
        f = [os.path.expanduser(x.strip()) for x in ln.split('\t')]
        out.append({'id': f[0], 'image': f[1], 'listing': None if len(f) < 3 or f[2] in ('', '-') else f[2],
                    'vlm_dir': f[3] if len(f) > 3 and f[3] not in ('', '-') else None})
    return out


MIME = {'.pdf': 'application/pdf', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.avif': 'image/avif'}

RUN_DIRECT = (
    'import json, sys\n'
    'sys.path.insert(0, sys.argv[1])\n'
    'import pipeline\n'
    'lt = open(sys.argv[4], errors="replace").read() if sys.argv[4] != "-" else ""\n'
    'try:\n'
    '    res = pipeline.run(sys.argv[2], lt, sys.argv[3], vlm_dir=sys.argv[5], slot=False, cache_only=True)\n'
    'except pipeline.TrialError as e:\n'
    '    open(sys.argv[3] + "/error.json", "w").write(json.dumps({"code": e.code, "detail": e.detail}))\n'
    '    sys.exit(3)\n'
    'open(sys.argv[3] + "/result.json", "w").write(json.dumps(res, separators=(",", ":")))\n')


def case_cmd(code: Path, c: dict, wd: Path) -> list[str]:
    fp = Path(code) / 'tools' / 'floorplan'
    if c.get('vlm_dir'):
        return [PY, '-c', RUN_DIRECT, str(fp), c['image'], str(wd), c.get('listing') or '-', c['vlm_dir']]
    cmd = [PY, str(fp / 'pipeline.py'), 'job', '--input', c['image'], '--mime',
           MIME.get(Path(c['image']).suffix.lower(), 'image/png'), '--workdir', str(wd), '--vlm-root', str(VLM_CACHE),
           '--cache-only', '--no-slot', '--job-id', f"regress-{c['id']}"]
    if c.get('listing'):
        cmd += ['--listing-file', c['listing']]
    return cmd


def clean_env(extra: dict) -> dict:
    """Окружение прогона: без чужих FP_* (FP_REDRAW, FP_POCKET … из оболочки) — только заданные `--env`."""
    env = {k: v for k, v in os.environ.items() if not k.startswith('FP_')}
    env.update(extra)
    return env


def run_cases(code: Path, out: Path, cases: list[dict], jobs: int = 4, extra_env: dict | None = None,
              cache_dir: Path | None = None) -> dict:
    """`cache_dir` — общий кэш листов (`regress_cache.py`, T-20261111-18); None — без кэша (`--no-cache`)."""
    import regress_cache as RC
    code, out = Path(code).resolve(), Path(out)
    out.mkdir(parents=True, exist_ok=False)                        # новая папка: старые выводы не трогаем
    env = clean_env(extra_env or {})
    man = {'code': str(code), 'code_sha': code_sha(code), 'rev': code_rev(code), 'env': extra_env or {},
           'started': time.strftime('%Y-%m-%d %H:%M:%S'), 'cases': {}}
    why = 'выключен (--no-cache)' if cache_dir is None else RC.bypass_reason(extra_env)
    store = fpr = None
    if why is None:
        store, fpr = RC.Store(cache_dir), RC.Fingerprint(code, PY, env, extra_env)
        man['cache'] = {'dir': str(cache_dir), 'fingerprint': fpr.digest[:16]}
    else:
        man['cache'] = {'off': why}
        print(f'кэш не используем: {why}', flush=True)

    def one(c):
        wd = out / c['id']
        log_p = Path(str(wd) + '.log')
        t0 = time.time()
        cmd = case_cmd(code, c, wd)
        try:
            k1 = RC.case_key(fpr, cmd, c, wd) if fpr else None
        except OSError:                                            # листа/объявления нет — разбор сам скажет, кэш мимо
            k1 = None
        hit = store.get(k1) if k1 else None
        if hit:
            e = store.restore(hit[1], wd, log_p, hit[0])
            print(f"{time.strftime('%H:%M:%S')} {c['id']} rc={e['rc']} кэш {hit[0][:12]}", flush=True)
            return c['id'], {'image': c['image'], 'listing': c.get('listing'), 'vlm_dir': c.get('vlm_dir'), 'rc': e['rc'],
                             'sec': round(time.time() - t0, 1), 'cached': hit[0][:16], 'parse_sec': e.get('sec')}
        with open(log_p, 'w') as log:
            try:
                rc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, cwd=str(code),
                                    timeout=TIMEOUT_S).returncode
            except subprocess.TimeoutExpired:
                rc = 124
        sec = round(time.time() - t0, 1)
        k2 = None
        if k1 and rc in RC.CACHED_RC:
            k2 = store.put(k1, RC.vlm_deps(c, wd, VLM_CACHE), wd, log_p,
                           {'case': c['id'], 'rc': rc, 'sec': sec, 'rev': man['rev'], 'code': str(code)})
        print(f"{time.strftime('%H:%M:%S')} {c['id']} rc={rc} {sec:.0f} с", flush=True)
        return c['id'], {'image': c['image'], 'listing': c.get('listing'), 'vlm_dir': c.get('vlm_dir'), 'rc': rc, 'sec': sec,
                         'cached': None, 'stored': k2 and k2[:16]}

    with ThreadPoolExecutor(max(1, jobs)) as ex:
        for k, v in ex.map(one, cases):
            man['cases'][k] = v
    man['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    hits = sum(1 for v in man['cases'].values() if v.get('cached'))
    man['cache'].update(hits=hits, parsed=len(man['cases']) - hits)
    (out / 'manifest.json').write_text(json.dumps(man, ensure_ascii=False, indent=1))
    return man

# ───────────────────────── сводка и сравнение ─────────────────────────


def _core(panel: dict, room: dict, page):
    if page is None or room.get('kind') not in ('bedroom', 'living'):
        return None
    TB, TR, cfg = page
    try:
        g = TB.core_geometry(panel, room, cfg)
    except TR.Refusal as e:
        return f'ОТКАЗ {e.code}'
    except Exception as e:  # noqa: BLE001 — сбой страницы на этой комнате: видно в таблице, сравнение идёт дальше
        return f'СБОЙ {type(e).__name__}'
    return f"ядро {float(g['w']):.0f}×{float(g['d']):.0f}"


def summarize(res: dict, page=None) -> dict:
    """result.json → {'rooms': n, 'doors', 'windows', 'other_ops', 'named': {панель/имя: [комната…]}}; комната — {'c', 'doors',
    'windows', 'ops', 'core', 'area'}. Проём — в каждой комнате, чей контур не дальше ROOM_TOL_CM от его середины (дверь между
    двумя комнатами считается у обеих). Безымянные куски — только в итогах листа."""
    from shapely.geometry import Point, Polygon
    out = {'rooms': 0, 'doors': 0, 'windows': 0, 'other_ops': 0, 'named': {}}
    for p in res.get('panels') or []:
        ops = p.get('openings') or []
        for o in ops:
            k = o.get('kind')
            out['doors' if k == 'door' else 'windows' if k == 'window' else 'other_ops'] += 1
        for r in p.get('rooms') or []:
            out['rooms'] += 1
            name = ' '.join(str(r.get('name') or '').split())
            if not name or len(r.get('contour') or []) < 3:
                continue
            poly = Polygon(r['contour']).buffer(0)
            ring = poly.boundary
            mine = sorted((o.get('kind'), round(float(o.get('widthCm') or 0))) for o in ops
                          if ring.distance(Point(o['c'])) <= ROOM_TOL_CM)
            c = poly.centroid
            out['named'].setdefault(f"{p.get('id')}/{name}", []).append(
                {'c': (round(c.x, 1), round(c.y, 1)), 'area': round(float(r.get('areaM2') or 0), 2),
                 'doors': sum(1 for k, _ in mine if k in ('door', 'opening')), 'windows': sum(1 for k, _ in mine if k == 'window'),
                 'ops': mine, 'core': _core(p, r, page)})
    return out


def pair_rooms(a: list, b: list) -> tuple[list, list, list]:
    """Одноимённые комнаты листа: пары по ближайшему центру (один-к-одному) → (пары, только в a, только в b)."""
    cand = sorted(((x[1]['c'][0] - y[1]['c'][0]) ** 2 + (x[1]['c'][1] - y[1]['c'][1]) ** 2, i, j)
                  for i, x in enumerate(enumerate(a)) for j, y in enumerate(enumerate(b)))
    ua, ub, pairs = set(range(len(a))), set(range(len(b))), []
    for _, i, j in cand:
        if i in ua and j in ub:
            pairs.append((a[i], b[j]))
            ua.discard(i)
            ub.discard(j)
    return pairs, [a[i] for i in sorted(ua)], [b[j] for j in sorted(ub)]


def _fail(core) -> bool:
    return bool(core) and not core.startswith('ядро')


def judge(x: dict | None, y: dict | None) -> tuple[str, str]:
    """Комната «до» x и «после» y → (метка, почему)."""
    if x and not y:
        return 'СЛОМАНО', 'комнаты нет'
    if y and not x:
        return 'ИНАЧЕ', 'новая комната'
    if x['doors'] > 0 and y['doors'] == 0:
        return 'СЛОМАНО', f"пропали все двери ({x['doors']} → 0)"
    if x['windows'] > 0 and y['windows'] == 0:
        return 'СЛОМАНО', f"пропали все окна ({x['windows']} → 0)"
    ops = f"дверей {x['doors']} → {y['doors']}"     # ядро появилось/пропало вместе с дверями — видно, не снятием ли дверей
    if x['core'] and not _fail(x['core']) and _fail(y['core']):
        return 'СЛОМАНО', f"{x['core']} → {y['core']}, {ops}"
    if _fail(x['core']) and y['core'] and not _fail(y['core']):
        return 'ИСПРАВЛЕНО', f"{x['core']} → {y['core']}, {ops}"
    if (x['doors'], x['windows'], x['core']) != (y['doors'], y['windows'], y['core']):
        return 'ИНАЧЕ', f"дверей {x['doors']} → {y['doors']}, окон {x['windows']} → {y['windows']}" + \
            (f", {x['core']} → {y['core']}" if x['core'] != y['core'] else '')
    return 'БЕЗ ИЗМЕНЕНИЙ', ''


def load_side(d: Path) -> tuple[dict, dict]:
    """Папка прогона → (манифест, {лист: result | {'_error': код}})."""
    d = Path(d)
    mf = d / 'manifest.json'
    man = json.loads(mf.read_text()) if mf.exists() else {}
    out = {}
    names = man.get('cases') or {p.name: {} for p in d.iterdir() if p.is_dir()}
    for n in names:
        r, e = d / n / 'result.json', d / n / 'error.json'
        if r.exists():
            out[n] = json.loads(r.read_text())
        else:
            out[n] = {'_error': json.loads(e.read_text()).get('code') if e.exists() else 'нет result.json'}
    return man, out


def read_accept(path: Path | None) -> dict:
    if not path:
        return {}
    acc = {}
    for ln in Path(path).read_text().splitlines():
        f = ln.split('\t')
        if len(f) >= 2 and not ln.startswith('#'):
            acc[(f[0], f[1])] = f[2] if len(f) > 2 else 'принято'
    return acc


def compare(A: dict, B: dict, page=None, accept: dict | None = None) -> tuple[list, dict]:
    """{лист: result} «до» и «после» → (строки (лист, комната, метка, почему), итог по меткам). Принятое `accept` — метка
    «ПРИНЯТО» с причиной (не считается сломанным)."""
    accept = accept or {}
    rows, tot = [], {}

    def add(sheet, room, mark, why):
        if mark != 'БЕЗ ИЗМЕНЕНИЙ' and (sheet, room) in accept:
            mark, why = 'ПРИНЯТО', f'{why} · {accept[(sheet, room)]}'
        rows.append((sheet, room, mark, why))
        tot[mark] = tot.get(mark, 0) + 1

    for s in sorted(set(A) | set(B)):
        ra, rb = A.get(s), B.get(s)
        ea, eb = (ra or {'_error': 'нет прогона'}).get('_error'), (rb or {'_error': 'нет прогона'}).get('_error')
        if ea or eb:
            if ea and eb:
                add(s, '*', 'БЕЗ ИЗМЕНЕНИЙ' if ea == eb else 'ИНАЧЕ', f'{ea} → {eb}')
            elif eb:
                add(s, '*', 'СЛОМАНО', f'лист не собрался: {eb}')
            else:
                add(s, '*', 'ИСПРАВЛЕНО', f'{ea} → собрался')
            continue
        sa, sb = summarize(ra, page), summarize(rb, page)
        head = f"комнат {sa['rooms']} → {sb['rooms']}, дверей {sa['doors']} → {sb['doors']}, окон {sa['windows']} → {sb['windows']}"
        add(s, '*', 'БЕЗ ИЗМЕНЕНИЙ' if (sa['rooms'], sa['doors'], sa['windows']) == (sb['rooms'], sb['doors'], sb['windows'])
            else 'ИНАЧЕ', head)
        for k in sorted(set(sa['named']) | set(sb['named'])):
            pairs, oa, ob = pair_rooms(sa['named'].get(k, []), sb['named'].get(k, []))
            for x, y in pairs:
                add(s, k, *judge(x, y))
            for x in oa:
                add(s, k, *judge(x, None))
            for y in ob:
                add(s, k, *judge(None, y))
    return rows, tot


# ───────────────────────── сторож «перечитать планировку» (T-20261111-02) ─────────────────────────
# Гейт, а не отчёт: прежний `result` тура и перечитанный → пары комнат (по геометрии в пикселях листа, не по имени и номеру) и находки.
# Находка — {'key', 'level': 'block'|'change', 'text'}; ключ стабилен для того же кода и кэша (значения в нём), по нему ведущий одобряет
# КОНКРЕТНУЮ разницу тура (`approved`). Блок — потеря: у жилой комнаты нет пары / слилась, сменился жилой тип, площадь разошлась больше
# max(2 м², 20 %), пропали все двери или окна, обставленная стала отказом / ждёт проверки, пропали товары, цены или ссылки. Прочее
# (число проёмов, масштаб, новые и пропавшие нежилые комнаты) — «изменение»: тоже не выходит без одобрения.

LIVING = ('living', 'bedroom')
PAIR_IOU = 0.5           # пара комнат: пересечение / объединение контуров в пикселях листа
AREA_ABS, AREA_REL = 2.0, 0.20
SCALE_REL = 0.01


def _px(res: dict) -> float | None:
    """см → пиксели листа: см·ppm/100; без масштаба — None."""
    try:
        return float((res.get('scale') or {}).get('ppm') or 0) / 100.0 or None
    except (TypeError, ValueError):
        return None


def _poly(room: dict, k: float):
    from shapely.geometry import Polygon
    pts = room.get('contour') or []
    if len(pts) < 3:
        return None
    p = Polygon([(float(x) * k, float(y) * k) for x, y in pts]).buffer(0)
    return p if not p.is_empty and p.area > 0 else None


def _room_ops(panel: dict, room: dict) -> tuple[int, int]:
    """(двери, окна) у стены комнаты — как `summarize` (проём в ROOM_TOL_CM от контура)."""
    from shapely.geometry import Point, Polygon
    pts = room.get('contour') or []
    if len(pts) < 3:
        return 0, 0
    ring = Polygon(pts).buffer(0).boundary
    near = [o.get('kind') for o in panel.get('openings') or [] if ring.distance(Point(o['c'])) <= ROOM_TOL_CM]
    return sum(1 for k in near if k in ('door', 'opening')), sum(1 for k in near if k == 'window')


def _rooms_of(res: dict) -> list[tuple[dict, dict]]:
    return [(p, r) for p in res.get('panels') or [] for r in p.get('rooms') or []]


def _norm(x):
    """Числа — одним видом: `result` из Postgres (jsonb) приходит с 310 вместо 310.0 и с другим порядком ключей."""
    if isinstance(x, dict):
        return {k: _norm(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_norm(v) for v in x]
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return round(float(x), 6)
    return x


def same_canon(a: dict, b: dict) -> bool:
    """Прочитано то же самое: результат без времени и расхода (они меняются от прогона к прогону)."""
    def strip(x):
        return _norm({k: v for k, v in x.items() if k not in ('timings', 'costUsd')})
    return json.dumps(strip(a), sort_keys=True) == json.dumps(strip(b), sort_keys=True)


def pair_canon(old: dict, new: dict) -> dict:
    """Пары комнат прежнего и перечитанного `result` той же панели: один-к-одному по пересечению контуров в пикселях листа (масштаб мог
    смениться — см у сторон разные), не меньше PAIR_IOU. → {'pairs': {(панель, id старой): id новой}, 'lost': {(панель, id): почему},
    'added': [(панель, id новой)], 'k': см нового на см старого}."""
    ko, kn = _px(old), _px(new)
    if ko is None or kn is None:                 # у одной стороны масштаба нет — сравнение в см как есть
        ko = kn = 1.0
    O = [(p['id'], r, _poly(r, ko)) for p, r in _rooms_of(old)]
    N = [(p['id'], r, _poly(r, kn)) for p, r in _rooms_of(new)]
    cand = []
    for i, (po, ro, a) in enumerate(O):
        for j, (pn, rn, b) in enumerate(N):
            if po == pn and a is not None and b is not None and a.intersects(b):
                inter = a.intersection(b).area
                cand.append((inter / a.union(b).area, i, j))
    pairs, used_o, used_n = {}, set(), set()
    for iou, i, j in sorted(cand, reverse=True):
        if iou >= PAIR_IOU and i not in used_o and j not in used_n:
            used_o.add(i)
            used_n.add(j)
            pairs[(O[i][0], str(O[i][1]['id']))] = str(N[j][1]['id'])
    by_new = {(N[j][0], str(N[j][1]['id'])): j for j in range(len(N))}
    owner = {by_new[(po, nid)]: (po, oid) for (po, oid), nid in pairs.items()}
    lost = {}
    for i, (po, ro, a) in enumerate(O):
        if i in used_o:
            continue
        why = 'нет контура' if a is None else 'нет пары'
        if a is not None:
            cover = sorted(((a.intersection(b).area / a.area, j) for j, (pn, _, b) in enumerate(N) if pn == po and b is not None
                            and a.intersects(b)), reverse=True)
            parts = sorted(j for f, j in cover if f >= 0.2 and N[j][2].intersection(a).area / N[j][2].area >= 0.5)
            if cover and cover[0][0] >= 0.5 and cover[0][1] in owner:
                other = next(r for p, r in _rooms_of(old) if (p['id'], str(r['id'])) == owner[cover[0][1]])
                why = f"слилась с «{other.get('name') or other['id']}»"
            elif len(parts) >= 2:
                why = 'распалась на ' + ' + '.join(f"«{N[j][1].get('name') or N[j][1]['id']}»" for j in parts)
        lost[(po, str(ro['id']))] = why
    added = [(pn, str(rn['id'])) for j, (pn, rn, _) in enumerate(N) if j not in used_n]
    return {'pairs': pairs, 'lost': lost, 'added': added, 'k': (ko / kn) if kn else 1.0}


def _f(key: str, level: str, text: str) -> dict:
    return {'key': key, 'level': level, 'text': text}


def guard_canon(old: dict, new: dict, pc: dict) -> list[dict]:
    """Находки по разбору (прежний и перечитанный `result`, пары `pair_canon`)."""
    out = []
    so, sn = old.get('scale') or {}, new.get('scale') or {}
    po_, pn_ = float(so.get('ppm') or 0), float(sn.get('ppm') or 0)
    if so.get('status') != sn.get('status') or (po_ and pn_ and abs(pn_ / po_ - 1) > SCALE_REL):
        out.append(_f(f"scale:{so.get('status')}/{po_:.1f}→{sn.get('status')}/{pn_:.1f}", 'change',
                      f"масштаб {so.get('status')} {po_:.1f} → {sn.get('status')} {pn_:.1f} пикс/м"))
    if old.get('ceilingCm') != new.get('ceilingCm'):
        out.append(_f(f"ceiling:{old.get('ceilingCm')}→{new.get('ceilingCm')}", 'change',
                      f"потолок {old.get('ceilingCm')} → {new.get('ceilingCm')} см"))
    newp = {p['id']: p for p in new.get('panels') or []}
    for p, r in _rooms_of(old):
        k = (p['id'], str(r['id']))
        name, kind = r.get('name') or r['id'], r.get('kind')
        live = kind in LIVING
        tag = f"{p['id']}/{r['id']}"
        if k in pc['lost']:
            out.append(_f(f'{tag}:lost', 'block' if live else 'change', f"«{name}» ({kind}): {pc['lost'][k]}"))
            continue
        nid = pc['pairs'][k]
        np_ = newp[p['id']]
        nr = next(x for x in np_['rooms'] if str(x['id']) == nid)
        if nr.get('kind') != kind:
            out.append(_f(f"{tag}:kind:{kind}→{nr.get('kind')}", 'block' if live else 'change',
                          f"«{name}»: тип {kind} → {nr.get('kind')}"))
        ao, an = float(r.get('areaM2') or 0), float(nr.get('areaM2') or 0)
        if abs(an - ao) > max(AREA_ABS, AREA_REL * ao):
            out.append(_f(f'{tag}:area:{ao:.1f}→{an:.1f}', 'block' if live else 'change', f"«{name}»: площадь {ao:.1f} → {an:.1f} м²"))
        (do, wo), (dn, wn) = _room_ops(p, r), _room_ops(np_, nr)
        if do > 0 and dn == 0:
            out.append(_f(f'{tag}:doors:{do}→0', 'block', f"«{name}»: пропали все двери ({do} → 0)"))
        elif do != dn:
            out.append(_f(f'{tag}:doors:{do}→{dn}', 'change', f"«{name}»: дверей {do} → {dn}"))
        if wo > 0 and wn == 0:
            out.append(_f(f'{tag}:windows:{wo}→0', 'block', f"«{name}»: пропали все окна ({wo} → 0)"))
        elif wo != wn:
            out.append(_f(f'{tag}:windows:{wo}→{wn}', 'change', f"«{name}»: окон {wo} → {wn}"))
    for pid, nid in pc['added']:
        nr = next(x for x in newp[pid]['rooms'] if str(x['id']) == nid)
        out.append(_f(f"{pid}/+{nid}:new:{nr.get('kind')}", 'change', f"новая комната «{nr.get('name') or nid}» ({nr.get('kind')})"))
    return out


def page_rooms(bundle: dict) -> dict:
    """Страница тура → {(панель, id плана): {'page', 'kind', 'state', 'outcome', 'goods', 'bad'}}: товары с ценой и ссылкой, `bad` —
    без цены или ссылки."""
    src = {x['id']: (p['id'], str(x.get('src_id'))) for p in (bundle.get('trial') or {}).get('panels') or [] for x in p.get('rooms') or []}
    goods: dict = {}
    for v in bundle.get('variants') or []:
        g = goods.setdefault(v.get('room_id'), [0, 0])
        for it in v.get('items') or []:
            s = it.get('sku') or {}
            g[0 if (s.get('price') or 0) > 0 and s.get('url') else 1] += 1
    out = {}
    for r in bundle.get('apartment_rooms') or []:
        if r['id'] in src:
            g = goods.get(r['id'], [0, 0])
            out[src[r['id']]] = {'page': r['id'], 'kind': r.get('kind'), 'state': r.get('furniture_state'),
                                 'outcome': r.get('furniture_outcome'), 'goods': g[0], 'bad': g[1]}
    return out


def _furnished(x: dict | None) -> bool:
    return bool(x) and x['state'] == 'ready' and x['outcome'] == 'furnished'


def guard_page(old_b: dict, new_b: dict, pc: dict) -> list[dict]:
    """Находки по готовой странице ПОСЛЕ правок агента: обставленная комната осталась обставленной, с товарами, ценами и ссылками."""
    out = []
    po, pn = page_rooms(old_b), page_rooms(new_b)
    for k, x in po.items():
        if not _furnished(x) and not x['goods']:
            continue
        tag = f'{k[0]}/{k[1]}'
        y = pn.get((k[0], pc['pairs'].get(k))) if k in pc['pairs'] else None
        if y is None:
            out.append(_f(f'{tag}:page:lost', 'block', f"{x['page']}: комнаты нет на новой странице"))
            continue
        if _furnished(x) and not _furnished(y):
            out.append(_f(f"{tag}:page:{y['state']}/{y['outcome']}", 'block',
                          f"{x['page']}: была обставлена → {y['state']} / {y['outcome']}"))
        elif x['goods'] and not y['goods']:
            out.append(_f(f'{tag}:page:goods:{x["goods"]}→0', 'block', f"{x['page']}: товаров {x['goods']} → 0"))
        if y['bad'] > x['bad']:
            out.append(_f(f"{tag}:page:bad:{x['bad']}→{y['bad']}", 'block', f"{x['page']}: товаров без цены или ссылки {x['bad']} → {y['bad']}"))
    return out


def verdict(findings: list[dict], approved=()) -> tuple[str, list[dict]]:
    """→ (итог, неодобренные находки): 'clean' — разницы нет; 'approved' — вся разница одобрена; 'block' — есть неодобренная потеря;
    'change' — неодобренное изменение (нужна приёмка ведущего)."""
    left = [f for f in findings if f['key'] not in set(approved)]
    if not findings:
        return 'clean', []
    if not left:
        return 'approved', []
    return ('block' if any(f['level'] == 'block' for f in left) else 'change'), left


def detail_of(left: list[dict], limit: int = 2000) -> str:
    """Разбор для `error_detail` пересборки (≤ 2000 знаков): блоки первыми, ключ — для файла одобрения."""
    lines = [f"{'БЛОК' if f['level'] == 'block' else 'изм.'} {f['text']} [{f['key']}]"
             for f in sorted(left, key=lambda f: f['level'] != 'block')]
    s = '\n'.join(lines)
    return s if len(s) <= limit else s[:limit - 1] + '…'


def table_rows(old: dict, new: dict, pc: dict, old_b: dict | None = None, new_b: dict | None = None) -> list[dict]:
    """Таблица оператору «комната: было → стало» (пара, тип, площадь, двери, окна, обставлена, товары)."""
    po, pn = page_rooms(old_b or {}), page_rooms(new_b or {})
    newp = {p['id']: p for p in new.get('panels') or []}
    rows = []

    def side(p, r, pg):
        d, w = _room_ops(p, r)
        return {'id': str(r['id']), 'name': r.get('name'), 'kind': r.get('kind'), 'area': round(float(r.get('areaM2') or 0), 1),
                'doors': d, 'windows': w, 'state': (pg or {}).get('outcome') or (pg or {}).get('state'), 'goods': (pg or {}).get('goods')}
    for p, r in _rooms_of(old):
        k = (p['id'], str(r['id']))
        nid = pc['pairs'].get(k)
        nr = next((x for x in newp[p['id']]['rooms'] if str(x['id']) == nid), None) if nid else None
        rows.append({'panel': p['id'], 'was': side(p, r, po.get(k)), 'now': side(newp[p['id']], nr, pn.get((p['id'], nid))) if nr else None,
                     'why': pc['lost'].get(k)})
    for pid, nid in pc['added']:
        nr = next(x for x in newp[pid]['rooms'] if str(x['id']) == nid)
        rows.append({'panel': pid, 'was': None, 'now': side(newp[pid], nr, pn.get((pid, nid))), 'why': 'новая'})
    return rows


def load_page(code: Path | None = None):
    """Код страницы тура (`trial_bundle.core_geometry`) — один для обеих сторон: сравниваем разбор, а не страницу."""
    sc = str(Path(code or HERE.parents[1]) / 'tools' / 'scout')
    sys.path.insert(0, sc)
    try:
        import trial_bundle as TB
        import trial_room as TR
        return TB, TR, TR.rules()
    except Exception as e:  # noqa: BLE001 — без страницы сравнение идёт по дверям и окнам
        print(f'ядро не считаем: {type(e).__name__}: {e}', file=sys.stderr)
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sp = ap.add_subparsers(dest='cmd', required=True)
    s = sp.add_parser('snapshot')
    s.add_argument('rev')
    s.add_argument('out')
    r = sp.add_parser('run')
    r.add_argument('code')
    r.add_argument('out')
    r.add_argument('--cases', action='append', default=[])
    r.add_argument('--no-trial', action='store_true', help='без загрузок ~/remlab-logs/trial/*/a1-*')
    r.add_argument('--only', help='имена листов через запятую')
    r.add_argument('-j', '--jobs', type=int, default=4)
    r.add_argument('--env', action='append', default=[], help='K=V для прогона (FP_* из оболочки не берутся)')
    r.add_argument('--no-cache', action='store_true', help='разобрать всё заново, кэш не читать и не писать')
    r.add_argument('--cache-dir', default=str(CACHE_DIR), help='общий кэш листов (по умолчанию ~/remlab-logs/regress-cache)')
    c = sp.add_parser('cmp')
    c.add_argument('before')
    c.add_argument('after')
    c.add_argument('--accept')
    c.add_argument('--page-code', help='копия кода со страницей тура (tools/scout); по умолчанию — эта')
    c.add_argument('--no-core', action='store_true')
    c.add_argument('--all', action='store_true', help='печатать и «без изменений»')
    c.add_argument('--allow-same', action='store_true', help='сравнить один и тот же код (проверка повторяемости)')
    a = ap.parse_args(argv)
    if a.cmd == 'snapshot':
        print(snapshot(a.rev, Path(a.out)))
        return 0
    if a.cmd == 'run':
        cases = [] if a.no_trial else trial_cases()
        for f in a.cases:
            cases += read_cases(Path(f))
        if a.only:
            keep = set(a.only.split(','))
            cases = [x for x in cases if x['id'] in keep]
        if not cases:
            print('нет листов', file=sys.stderr)
            return 2
        env = dict(kv.split('=', 1) for kv in a.env)
        man = run_cases(Path(a.code), Path(a.out), cases, a.jobs, env,
                        None if a.no_cache else Path(os.path.expanduser(a.cache_dir)))
        bad = [k for k, v in man['cases'].items() if v['rc'] not in (0, 3)]
        cc = man['cache']
        print(f"листов {len(cases)} · код {man['rev']} ({man['code_sha']}) · сбоев {len(bad)} {bad}")
        print(f"кэш: из кэша {cc.get('hits', 0)}, разобрано {cc.get('parsed', len(cases))}"
              + (f" (кэш не используем: {cc['off']})" if cc.get('off') else ''))
        return 1 if bad else 0
    ma, A = load_side(Path(a.before))
    mb, B = load_side(Path(a.after))
    if ma.get('code_sha') and ma.get('code_sha') == mb.get('code_sha') and ma.get('env') == mb.get('env') and not a.allow_same:
        print(f"ОТКАЗ: «до» и «после» — один и тот же код ({ma.get('rev')}, {ma['code_sha']}) — регресс так ничего не ловит",
              file=sys.stderr)
        return 3
    page = None if a.no_core else load_page(Path(a.page_code) if a.page_code else None)
    rows, tot = compare(A, B, page, read_accept(Path(a.accept) if a.accept else None))
    print(f"до: {ma.get('rev')} ({ma.get('code_sha')}) {ma.get('env') or ''} · после: {mb.get('rev')} ({mb.get('code_sha')}) "
          f"{mb.get('env') or ''} · листов {len(set(A) | set(B))}")
    for s, k, m, why in rows:
        if a.all or m != 'БЕЗ ИЗМЕНЕНИЙ' or k == '*':
            print(f'{m:14} {s} {k}: {why}')
    print('ИТОГ', json.dumps(tot, ensure_ascii=False))
    return 1 if tot.get('СЛОМАНО') else 0


if __name__ == '__main__':
    sys.exit(main())

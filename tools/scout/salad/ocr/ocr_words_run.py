#!/usr/bin/env python3
"""ПРОБА/ПАКЕТ SALAD «КЭШ СЛОВ OCR» (T-176/ocr-salad): листы планов → слова/флаги на нодах Salad (rapidocr на процессоре, образ Dockerfile.ocr) → results-<suffix>.json → слияние `merge_words.py`.
Драйвер — общий набор (`kit_driver.run_probe`): деньги, потолок, гашение и проверка «0 нод» — там; здесь только «что отправить и как забрать». Одна группа = одна нода = одна часть листов (`--part K/N`).
Ключ кэша = sha256 ФАЙЛА листа (как words_on_sheet.sheet_sha); версия правил — хеш frozen/words_rules.json (12 знаков) = ключ `rules` записи. Лист, уже посчитанный под этими правилами в `--cache`, не отправляется.

Запуск (платный — только под heavy-slot --prio 2, потолок на ВЕСЬ пакет ≤$5 и ≤2 ч, ≤10 нод, тариф low):
  PROBA 10:  heavy-slot.sh t176-ocr-proba --prio 2 -- python ocr_words_run.py --image ghcr.io/…/mesh-ocr-cpu@sha256:… --ids IDS --sheets-dirs D1,D2 --cache words_flags.json --probe-from words_flags.json --probe-n 10 --apply
  ПАКЕТ:     то же без --probe-from, по одной команде на часть: --part 1/6 --suffix b1 … --part 6/6 --suffix b6
Без --apply — только разбор: план (сколько листов, частей, что уже в кэше), тело группы без секретов, проверка образа (группа НЕ создаётся). `--plan` — только счёт листов без Salad. `--stop-only --suffix X` — погасить группу X и проверить «0 нод».
Выход: <out>/results-<suffix>.json {"rules", "results": {sha: {words, found, conf, n_lines, sheet, ocr_s}}}, <out>/items-<suffix>.json (по заданиям: время, отказы), для пробы — <out>/probe-table-<suffix>.md."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
SALAD = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, SALAD)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, '..', '..', 'render_gpu')))        # bench_run (group_state/instances/stop_and_verify)
sys.path.insert(0, os.path.join(SALAD, 'pose'))
import kit_driver as KD  # noqa: E402
import kit_worker as KW  # noqa: E402
import pose_trial as PT  # noqa: E402
from kit_driver import say  # noqa: E402

WORK_TYPE = 'cpu_stage'                       # профиль ресурсов rules/salad-resources.json: 4 vCPU / 8 ГБ, тариф low (замер T-189/1). Драйвер Salad создаёт группы только с картой — берём самую дешёвую из профиля (GTX 1650), её CUDA образ не использует
CARD = KD.resource_profile(WORK_TYPE)['card']
PORT = 8000
WORKER = os.path.join(HERE, 'worker_ocr.py')
FROZEN = os.path.join(HERE, 'frozen')
PREFIX = 'ocr-words'
CONF_TOL = 0.01
SHEET_EXT = ('jpeg', 'jpg', 'png')


def rules_ver() -> str:
    """Версия правил — как words_on_sheet.rules_ver(): sha256 words_rules.json, 12 знаков."""
    with open(os.path.join(FROZEN, 'words_rules.json'), 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]


def sheet_sha(path: str) -> str:
    """Ключ кэша — sha256 ФАЙЛА листа (то же, что words_on_sheet.sheet_sha)."""
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def find_sheet(sid: str, dirs: list[str]) -> str | None:
    """Файл листа `<папка>/<id>/plan.(jpeg|jpg|png)` — в первой папке, где он есть."""
    for d in dirs:
        for ext in SHEET_EXT:
            p = os.path.join(os.path.expanduser(d), sid, f'plan.{ext}')
            if os.path.isfile(p):
                return p
    return None


def load_cache(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return {}
    return json.load(open(path, encoding='utf-8'))


def plan_todo(ids: list[str], dirs: list[str], cache: dict, rules: str) -> dict:
    """Что считать: {'todo': [{id, path, sha, ext}], 'cached': [...id], 'no_file': [...id]}. Уже в кэше под ЭТИМИ правилами — не считаем."""
    todo, cached, no_file, seen = [], [], [], set()
    for sid in ids:
        p = find_sheet(sid, dirs)
        if p is None:
            no_file.append(sid)
            continue
        sha = sheet_sha(p)
        if sha in seen:
            continue                                     # два id на один файл — считаем один раз
        seen.add(sha)
        if (cache.get(sha) or {}).get('rules') == rules:
            cached.append(sid)
        else:
            todo.append({'id': sid, 'path': p, 'sha': sha, 'ext': p.rsplit('.', 1)[1].lower()})
    return {'todo': todo, 'cached': cached, 'no_file': no_file}


def take_part(items: list, part: str) -> list:
    """`K/N` → каждый N-й, начиная с K-го (круговая раздача — части ровные и по размеру листов, и по порядку списка)."""
    k, n = (int(x) for x in part.split('/'))
    if not 1 <= k <= n:
        raise ValueError(f'--part {part}: нужно K/N, 1 ≤ K ≤ N')
    return items[k - 1::n]


def chunks(items: list, n: int) -> list[list]:
    return [items[i:i + n] for i in range(0, len(items), n)]


def probe_pick(cache: dict, ids: list[str], dirs: list[str], rules: str, n: int) -> tuple[list[dict], dict]:
    """n листов для пробы из УЖЕ посчитанных: запись есть, правила те же, файл листа сейчас имеет тот же sha (иначе сравнение с чужим листом). Выбор — равномерно по отсортированным id,
    чтобы в пробу попали и листы со словами, и без. → (todo-записи, ожидание {sha: запись кэша})."""
    ok = []
    for sid in sorted(ids):
        p = find_sheet(sid, dirs)
        if p is None:
            continue
        sha = sheet_sha(p)
        e = cache.get(sha)
        if e and e.get('rules') == rules:
            ok.append({'id': sid, 'path': p, 'sha': sha, 'ext': p.rsplit('.', 1)[1].lower()})
    if len(ok) < n:
        raise ValueError(f'для пробы нужно {n} уже посчитанных листов, есть {len(ok)}')
    step = len(ok) / n
    pick = [ok[int(i * step)] for i in range(n)]
    return pick, {t['sha']: cache[t['sha']] for t in pick}


def compare(expect: dict, got: dict, tol: float = CONF_TOL) -> list[dict]:
    """Сверка с кэшем: words, found, n_lines — ТОЧНО; conf — ±tol. → строки таблицы {sheet, sha, words/found/n_lines/conf: (ждали, получили), ok, why}."""
    rows = []
    for sha, e in expect.items():
        g = got.get(sha)
        if g is None:
            rows.append({'sheet': e.get('sheet'), 'sha': sha[:12], 'ok': False, 'why': 'нет в ответе ноды'})
            continue
        why = [k for k in ('words', 'found', 'n_lines') if g.get(k) != e.get(k)]
        if abs(float(g.get('conf', 0)) - float(e.get('conf', 0))) > tol + 1e-9:
            why.append('conf')
        rows.append({'sheet': e.get('sheet'), 'sha': sha[:12], 'words': (e.get('words'), g.get('words')), 'found': (e.get('found'), g.get('found')),
                     'n_lines': (e.get('n_lines'), g.get('n_lines')), 'conf': (e.get('conf'), g.get('conf')), 'ocr_s': g.get('ocr_s'), 'ok': not why, 'why': ','.join(why)})
    return rows


def table_md(rows: list[dict]) -> str:
    out = ['| лист | words (кэш→нода) | found | n_lines | conf | сек | итог |', '|---|---|---|---|---|---|---|']
    for r in rows:
        if 'words' not in r:
            out.append(f"| {r['sheet']} | — | — | — | — | — | ❌ {r['why']} |")
            continue
        out.append(f"| {r['sheet']} | {r['words'][0]}→{r['words'][1]} | {r['found'][0]}→{r['found'][1]} | {r['n_lines'][0]}→{r['n_lines'][1]} | {r['conf'][0]}→{r['conf'][1]} | {r['ocr_s']} | {'✅' if r['ok'] else '❌ ' + r['why']} |")
    n_ok = sum(1 for r in rows if r['ok'])
    out.append(f'\nсовпало {n_ok} из {len(rows)}')
    return '\n'.join(out)


def worker_command(path: str | None = None) -> tuple[list[str], str]:
    return KW.bundle(path or WORKER)


def build_body(name: str, image: str, tier: str, class_id: str, auth: dict, life_s: int, idle_s: int, worker_z: str | None = None) -> dict:
    env = {'PORT': str(PORT), 'MAX_LIFETIME_S': str(life_s), 'IDLE_S': str(idle_s), 'OCR_PROCS': '1', 'DEPLOYMENT_EPOCH': f'20261127-{name}'}
    command = None
    if worker_z:
        command, env['KIT_WORKER_Z'] = worker_command()[0], worker_z
    return KD.group_body(name, image, tier, class_id, PORT, env, auth, command, work_type=WORK_TYPE, card=CARD)


def job_id(suffix: str, i: int, sheets: list[dict]) -> str:
    h = hashlib.sha256(''.join(s['sha'] for s in sheets).encode()).hexdigest()[:10]
    return f'ocr-{suffix}-{i}-{h}'


def submit_pack(gw, a, todo: list[dict], t: float) -> tuple[dict | None, dict]:
    """Отправить все листы части заданиями по `--chunk` листов (POST /jobs через общий post_job; лист — zlib+base64). Любое не принято → отказ пакета с причиной."""
    ids: dict[str, list[str]] = {}
    for i, part in enumerate(chunks(todo, a.chunk)):
        sheets = [{'id': s['id'], 'sha': s['sha'], 'ext': s['ext'], 'z': base64.b64encode(zlib.compress(open(s['path'], 'rb').read(), 6)).decode()} for s in part]
        jid = job_id(a.suffix, i, part)
        body = {'job_id': jid, 'sheets': sheets}
        c, r, _t = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        if c == -1:                                                                         # воркер задания не видит; job_id идемпотентен — один повтор
            say(f'задание {jid}: POST без ответа — повтор один раз')
            c, r, _t = KD.post_job(gw, '/jobs', body, f'/jobs/{jid}', say_fn=say)
        say(f'задание {jid}: листов {len(part)}, POST /jobs → {c} (≈{len(json.dumps(body)) / 2 ** 20:.1f} МБ)', str(r)[:120] if c != 202 else '')
        if c != 202:
            return None, {'http': c, 'detail': r, 'job': jid, 'accepted': list(ids)}
        ids[jid] = [s['sha'] for s in part]
    return {'key': 'pack', 'id': f'pack-{int(t)}', 't0': t, 'ids': ids, 'got': {}, 'results': {}}, {}


def poll_pack(gw, a, cur: dict, expect: dict, rules: str) -> tuple[str, dict]:
    """Все задания закончились? Готовые забираем (sha256 ответа и версию правил сверяем), отказы листов считаем с причинами. Пока кто-то идёт — 'running'."""
    running = 0
    for jid, shas in cur['ids'].items():
        if jid in cur['got']:
            continue
        c, v = gw.call('GET', f'/jobs/{jid}', timeout=30)
        if c != 200 or v.get('status') in ('queued', 'running'):
            running += 1                                                                    # шлюз моргнул — не провал; зависание ловят потолок денег и сторож хода
            continue
        c2, data = gw.call('GET', f'/jobs/{jid}/result', timeout=120, raw=True)
        if c2 != 200 or not data:
            running += 1
            continue
        rec = {k: v.get(k) for k in ('status', 'wall_s', 'ocr_s', 'queue_s', 'bytes', 'sha256', 'error')}
        if hashlib.sha256(data).hexdigest() != v.get('sha256'):
            cur['got'][jid] = {**rec, 'status': 'failed', 'error': f'sha256 ответа не сошёлся: ждали {v.get("sha256")}'}
            continue
        body = json.loads(data)
        if body.get('rules') != rules:
            cur['got'][jid] = {**rec, 'status': 'failed', 'error': f'версия правил на ноде {body.get("rules")} ≠ {rules} — образ не тот'}
            continue
        cur['results'].update(body.get('results') or {})
        cur['got'][jid] = {**rec, 'n_ok': len(body.get('results') or {}), 'errors': body.get('errors') or {}}
    if running:
        return 'running', {}
    items = cur['got']
    missing = [s for sh in cur['ids'].values() for s in sh if s not in cur['results']]
    bad = {j: v.get('error') or v.get('errors') for j, v in items.items() if v.get('status') == 'failed' or v.get('errors')}
    info = {'items': items, 'ok': len(cur['results']), 'total': sum(len(s) for s in cur['ids'].values()), 'missing': len(missing),
            'metrics': {'ok': len(cur['results']), 'failed': bad}}
    os.makedirs(a.out, exist_ok=True)
    json.dump({'rules': rules, 'results': cur['results']}, open(os.path.join(a.out, f'results-{a.suffix}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    json.dump(items, open(os.path.join(a.out, f'items-{a.suffix}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if expect:                                                                              # проба: сверка с кэшем
        rows = compare(expect, cur['results'])
        md = table_md(rows)
        open(os.path.join(a.out, f'probe-table-{a.suffix}.md'), 'w', encoding='utf-8').write(md + '\n')
        info['probe'] = {'ok': sum(1 for r in rows if r['ok']), 'total': len(rows)}
        say('ПРОБА: ' + md.splitlines()[-1])
        if any(not r['ok'] for r in rows):
            return 'failed', {'status': 'failed', 'error': 'СТОП: проба не совпала с кэшем — ' + md.splitlines()[-1], **info}
    if bad or missing:
        return 'failed', {'status': 'failed', 'error': f'отказов: заданий {len(bad)}, листов без результата {len(missing)}', **info}
    return 'done', info


def make_spec(a, todo: list[dict], expect: dict, rules: str) -> KD.Spec:
    def build(name, class_id, auth):
        return build_body(name, a.image, a.tier, class_id, auth, min(a.max_min * 60 + 600, 3 * 3600), a.idle_s, worker_z=None if getattr(a, 'worker_from_image', False) else worker_command()[1])

    def preflight():
        miss = [s['path'] for s in todo if not os.path.isfile(s['path'])]
        if miss or not todo:
            return False, f'нет входных файлов: {miss[:4]}' if miss else 'нечего считать (все листы уже в кэше?)'
        return True, f'листов {len(todo)}, заданий {len(chunks(todo, a.chunk))}'

    return KD.Spec(prefix=PREFIX, card=CARD, model='ocr-words', jobs=['pack'], build_body=build, work_type=WORK_TYPE, submit=lambda gw, k, t: submit_pack(gw, a, todo, t),
                   poll=lambda gw, cur, t: poll_pack(gw, a, cur, expect, rules), preflight=preflight, ready_keys=('version', 'rapidocr', 'onnxruntime', 'rules', 'cores', 'warm_s'),
                   z_keys=('KIT_WORKER_Z',), worker_file=WORKER)


def read_ids(path: str) -> list[str]:
    return [ln.strip() for ln in open(os.path.expanduser(path), encoding='utf-8') if ln.strip() and not ln.startswith('#')]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--image', help='образ группы: имя@sha256:digest (по тегу — отказ, ADR-0137)')
    ap.add_argument('--ids', help='файл со списком id листов (по строке)')
    ap.add_argument('--sheets-dirs', default='', help='папки листов через запятую: <папка>/<id>/plan.*; ищется в порядке перечисления')
    ap.add_argument('--cache', default='', help='words_flags.json цели: уже посчитанные под этими правилами листы пропускаются')
    ap.add_argument('--part', default='1/1', help='K/N — какая часть списка идёт на ЭТУ ноду (N нод = N команд)')
    ap.add_argument('--chunk', type=int, default=6, help='листов в одном задании')
    ap.add_argument('--probe-from', default='', help='проба: взять --probe-n УЖЕ посчитанных листов из этого words_flags.json и сверить результат ноды (words/found/n_lines точно, conf ±0,01)')
    ap.add_argument('--probe-n', type=int, default=10)
    ap.add_argument('--out', default=os.path.expanduser('~/remlab-logs/t176/ocr-salad/out'))
    ap.add_argument('--tier', default='low', choices=['low'], help='ТОЛЬКО low (владелец TG 2626)')
    ap.add_argument('--probe-cap', type=float, default=0.3, help='потолок денег, пока не готово первое задание, $')
    ap.add_argument('--cap', type=float, default=0.5, help='потолок на ЭТУ ноду, $ (на весь пакет ≤$5: cap × число нод)')
    ap.add_argument('--max-min', type=int, default=100, help='жизнь группы, мин (пакет ≤2 ч)')
    ap.add_argument('--running-min', type=int, default=30)
    ap.add_argument('--health-min', type=int, default=8)
    ap.add_argument('--start-min', type=int, default=20)
    ap.add_argument('--ready-min', type=int, default=30)
    ap.add_argument('--stall-min', type=int, default=5)
    ap.add_argument('--stall-gb', type=float, default=0.05)
    ap.add_argument('--job-min', type=int, default=0)
    ap.add_argument('--idle-s', type=int, default=600)
    ap.add_argument('--worker-from-image', action='store_true')
    ap.add_argument('--suffix', default=time.strftime('%m%d%H%M', time.gmtime()))
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--plan', action='store_true', help='только счёт листов (без Salad)')
    ap.add_argument('--stop-only', action='store_true')
    a = ap.parse_args()
    import bench_run as BR
    import migrate_groups as MG
    if a.stop_only:
        MG.env_from_file()
        return 0 if KD.stop_and_verify(BR, f'{PREFIX}-{a.suffix}') else 1
    if not a.ids or not a.sheets_dirs:
        sys.exit('нужны --ids и --sheets-dirs')
    rules = rules_ver()
    dirs = [d for d in a.sheets_dirs.split(',') if d]
    ids = read_ids(a.ids)
    expect: dict = {}
    if a.probe_from:
        todo, expect = probe_pick(load_cache(a.probe_from), ids, dirs, rules, a.probe_n)
        say(f'ПРОБА: {len(todo)} уже посчитанных листов: {[t["id"] for t in todo]}')
    else:
        p = plan_todo(ids, dirs, load_cache(a.cache), rules)
        say(f'план: в списке {len(ids)}, уже в кэше {len(p["cached"])}, нет файла листа {len(p["no_file"])} {p["no_file"][:5]}, считать {len(p["todo"])}')
        todo = take_part(p['todo'], a.part)
        say(f'часть {a.part}: листов {len(todo)}, заданий {len(chunks(todo, a.chunk))}')
    if a.plan:
        return 0
    if not a.image:
        sys.exit('нужен --image')
    return PT_run(a, MG, BR, todo, expect, rules)


def PT_run(a, MG, BR, todo, expect, rules) -> int:                    # noqa: N802
    rc = KD.run_probe(a, MG, BR, make_spec(a, todo, expect, rules))
    try:
        stopped = json.load(open(os.path.join(a.out, f'summary-{PREFIX}-{a.suffix}.json'), encoding='utf-8')).get('stopped_by') or ''
    except (OSError, ValueError):
        stopped = ''
    nxt = PT.fallback_tier(a.tier, stopped)
    if nxt:
        say(f'нет машин на тарифе {a.tier}; выше low не поднимаем (правило владельца 24.11, TG 2626) — стоп, строкой ведущему')
    return rc


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""КРУГ «НА 5» (T-20261123-29/1): одна команда — пересчитать шаг конвейера и следующие на золотых 5, посмотреть результат «до | после».

  tools/assets/loop5.sh --code-ref <SHA> --from 07            # 06 | 07 | 08; без --apply платного нет (--dry: только разбор)
  tools/assets/loop5.sh --code-ref <SHA> --from 07 --dry

Что делает:
 1. Берёт золотых 5 и пути «до» из rules/loop5.json (список в коде не зашит), строки входов — из пакета 29.
 2. Делит товары между ≤`machines` нодами Salad (профиль cpu_stage, low) и запускает по `stage_trial.py` на ноду параллельно:
    --from 06 → 06,07,seam,08; --from 07 → 07,seam,08 (вход 07 — 06-visible из «до»); --from 08 → 08 (вход — 07-fill и 06-visible из «до»).
    Код этапов едет в задании из `git archive <SHA>` (вход — только `--code-ref`; ветка/HEAD разрешаются в SHA и пишутся в итог).
 3. Пока идёт Salad, считает на наших ядрах листы «со всех сторон» для «до» (кэш `<out_root>/base-sheets/`), потом для «после».
 4. Складывает страницу `<out_root>/<прогон>/page/index.html` (+ png «до над после» на товар) и `summary.json` со временем, ценой и отказами.
 5. Сразу после листов «после» сам гоняет автооценку `sides_eval.py` (5 признаков × 6 сторон) и кладёт в `summary.json` (ключ `eval`) и наверх `page/index.html` таблицу
    worst-first + общий % «все 5». «Перёд» листа «после» — `front_axis_resolved` (orient → камера 04 по геометрии → unknown), не голая камера 04 (T-47).
Деплоя нет, `.env*` не читается (ключ Salad берёт сам драйвер как у T-220). Временное — `<out_root>/<прогон>/`."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import html
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
RULES = os.path.join(ROOT, 'tools', 'scout', 'rules', 'loop5.json')
STAGE_TRIAL = os.path.join(ROOT, 'tools', 'scout', 'salad', 'stage', 'stage_trial.py')
HEAVY = os.path.join(ROOT, 'tools', 'ops', 'heavy-slot.sh')


def say(msg: str) -> None:
    print(time.strftime('%H:%M:%S', time.gmtime()), msg, flush=True)


def ex(p: str) -> str:
    return os.path.expanduser(p)


def load_rules(path: str = RULES) -> dict:
    r = json.load(open(path, encoding='utf-8'))
    for k in ('golden', 'base_root', 'shard_inputs_glob', 'python', 'image', 'catalog', 'parts_root', 'stages', 'machines', 'caps', 'out_root', 'heavy_slot', 'sheets'):
        if k not in r:
            raise KeyError(f'rules/loop5.json: нет ключа {k}')
    if not r['golden'] or len(set(r['golden'])) != len(r['golden']):
        raise ValueError('rules/loop5.json: golden пуст или с повторами')
    return r


def resolve_sha(ref: str, repo: str = ROOT) -> str:
    """SHA коммита из ссылки; нет такого — отказ (код этапов едет в задании ровно по SHA)."""
    p = subprocess.run(['git', '-C', repo, 'rev-parse', '--verify', '--quiet', f'{ref}^{{commit}}'], capture_output=True, text=True)
    if p.returncode or not p.stdout.strip():
        raise SystemExit(f'--code-ref {ref}: нет такого коммита в {repo}')
    return p.stdout.strip()


def base_dirs(rules: dict, skus: list[str]) -> dict[str, str]:
    """{товар: папка «до»} — первая найденная `<base_root>/sh*/<товар>`; нет — отказ с перечнем."""
    out, miss = {}, []
    for s in skus:
        hit = sorted(glob.glob(os.path.join(ex(rules['base_root']), '*', s)), key=lambda p: (not os.path.basename(os.path.dirname(p)).startswith('sh'), p))
        if hit:
            out[s] = hit[0]                                                   # основная папка — из шардов sh* (полная цепочка); redo*/прочее — только для «до» 08
        else:
            miss.append(s)
    if miss:
        raise SystemExit(f'нет «до» в {rules["base_root"]}: {miss}')
    return out


def before_glb(rules: dict, sku: str, primary: str) -> str:
    """material.glb «до»: самый свежий из всех папок товара в base_root (повторный расчёт 08 лежит в redo*/ рядом с шардом)."""
    c = [p for p in glob.glob(os.path.join(ex(rules['base_root']), '*', sku, '08-material', 'material.glb')) if os.path.isfile(p)]
    return max(c, key=os.path.getmtime) if c else os.path.join(primary, '08-material', 'material.glb')


def need_files(start: str, base: dict[str, str]) -> list[str]:
    """Бесплатная проверка входов «до» под выбранный шаг (до создания платной группы)."""
    need = {'06': [], '07': ['06-visible/visible.glb', '06-visible/check.json'], '08': ['06-visible/visible.glb', '06-visible/known.png', '07-fill/filled.glb']}[start]
    return [f'{s}: нет {n}' for s, d in base.items() for n in need if not os.path.isfile(os.path.join(d, n))]


def split(skus: list[str], machines: int) -> list[list[str]]:
    n = max(1, min(int(machines), len(skus)))
    parts = [skus[i::n] for i in range(n)]
    return [p for p in parts if p]


def keep_photo(src: str, keep_dir: str, sku: str) -> str:
    """Копия фото товара в папку прогона (T-34, директор 23.11): этапы пишут в свои json путь фото из входа (04-camera.photo, 05-delight.source_photo), а исходник бывает во /tmp и пропадает — 09 не сверит с палитрой.
    Путь в входе и в json этапов — на копию в `<прогон>/photos/<товар>.<расширение>`. Нет исходника, но копия с прошлого захода есть — берём её; нет ни того ни другого — ошибка."""
    ext = os.path.splitext(src)[1] or '.png'
    dst = os.path.join(keep_dir, sku + ext)
    if src and os.path.isfile(src) and os.path.getsize(src) > 0:
        os.makedirs(keep_dir, exist_ok=True)
        if not (os.path.isfile(dst) and os.path.getsize(dst) == os.path.getsize(src)):
            tmp = dst + '.tmp'
            shutil.copyfile(src, tmp)
            os.replace(tmp, dst)
        return dst
    if os.path.isfile(dst) and os.path.getsize(dst) > 0:
        return dst
    raise SystemExit(f'нет фото товара {sku}: {src or "(пусто)"} — исходник пропал, копии в прогоне нет')


def shard_inputs(rules: dict, skus: list[str], start: str, base: dict[str, str], keep_dir: str | None = None) -> dict[str, dict]:
    """Строки входа stage_trial для товаров (06 и 07 — из пакета 29; для 07 добавляется vis = 06-visible «до»).
    keep_dir — фото копируются туда и в входе стоит путь копии (см. keep_photo)."""
    allv: dict[str, dict] = {}
    for f in sorted(glob.glob(ex(rules['shard_inputs_glob']))):
        allv.update(json.load(open(f, encoding='utf-8')))
    miss = [s for s in skus if s not in allv]
    if miss:
        raise SystemExit(f'нет строки входа в {rules["shard_inputs_glob"]}: {miss}')
    sel = {s: json.loads(json.dumps(allv[s])) for s in skus}
    if keep_dir:
        for s in skus:
            if sel[s].get('photo'):
                sel[s]['photo'] = keep_photo(sel[s]['photo'], keep_dir, s)
    if start == '07':
        for s in skus:
            sel[s]['vis'] = os.path.join(base[s], '06-visible')
    return sel


def warm_on(rules: dict) -> bool:
    return bool((rules.get('warm') or {}).get('enabled'))


def suffix_of(rules: dict, run_id: str, idx: int, rnd: int = 0) -> str:
    """Имя группы Salad (суффикс). Тёплая нода (T-34) — постоянное имя `w<нода>-<6 знаков digest образа>` (один образ — одна нода; смена образа — новое имя), общее для всех прогонов и повторов;
    иначе — на прогон (`l5<прогон>s<нода>[r<повтор>]`)."""
    var = ((rules.get('node') or {}).get('variant') or '')[:1]                         # другой размер ноды — другое имя (тёплую 4/8 не подхватить как 8/16)
    if warm_on(rules):
        m = re.search(r'@sha256:([0-9a-f]{6})', rules['image'])
        return f'w{idx}{var}-{m.group(1) if m else "x"}'
    return f'l5{run_id}s{idx}{var}' + (f'r{rnd}' if rnd else '')


def queue_on(rules: dict) -> bool:
    """Общая очередь товаров (T-34): ноды берут товар из общей папки и ведут его 07→шов→08 без барьера этапов; иначе — товары делятся по нодам заранее и идут этапами."""
    return bool((rules.get('queue') or {}).get('enabled'))


def node_count(rules: dict, n_skus: int) -> int:
    """Сколько нод: при очереди — не больше товаров и не больше rules.machines; без неё — как раньше (split)."""
    return min(n_skus, int(rules['machines'])) if queue_on(rules) else len(split(['x'] * n_skus, rules['machines']))


def stop_group(rules: dict, run_id: str, idx: int, rnd: int = 0) -> bool:
    """Погасить группу ноды и проверить «0 нод» (страховка при падении драйвера; для тёплой — команда `--warm-stop`)."""
    p = subprocess.run([ex('~/venvs/scout/bin/python'), '-I', STAGE_TRIAL, '--stop-only', '--suffix', suffix_of(rules, run_id, idx, rnd)], capture_output=True, text=True, timeout=300)
    return p.returncode == 0


def photos(rules: dict, keep_dir: str | None = None) -> dict[str, str]:
    """Настоящее фото товара для листа (вырезка из входов пакета 29: `photo`); frame-photo.png 07 у шкафа — боковой кадр (р.2, 23.11)."""
    out = {}
    for f in sorted(glob.glob(ex(rules['shard_inputs_glob']))):
        with open(f, encoding='utf-8') as fh:
            out.update({s: v.get('photo') or '' for s, v in json.load(fh).items()})
    if keep_dir:                                           # копия в прогоне надёжнее исходника
        for s in list(out):
            c = glob.glob(os.path.join(keep_dir, s + '.*'))
            if c and not c[0].endswith('.tmp'):
                out[s] = c[0]
    return out


def check_sheet_photos(photo: dict, skus: list[str]) -> None:
    """Фото для колонки ФОТО листа — ТОЛЬКО настоящее фото входа 06 (`photo` из входов пакета). Запасного `07-fill/frame-photo.png` нет: это боковой
    кадр-рендер 07, на нём мерки листа врут (T-21, 23.11). Нет фото — отказ ДО платного прогона, с перечнем товаров и причиной."""
    miss = [f'{s}: {photo.get(s) or "(photo не задан во входах)"}' for s in skus if not photo.get(s) or not os.path.isfile(photo[s])]
    if miss:
        raise SystemExit(f'нет фото входа 06 для листов (frame-photo.png 07 — не фото, запасным не берётся): {miss[:5]}{"…" if len(miss) > 5 else ""}')


SALAD_LIST = 'https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers'
GROUP_PREFIX = 'trial-stage-'                                                     # имя группы Salad = префикс stage_trial + суффикс ноды (suffix_of)


def _salad_items() -> list[dict]:
    """Список групп проекта в Salad — один GET (бесплатно). Через curl: WAF Salad режет python-UA (ADR-0137). Ключ — из env или ~/scout-scenes/salad.env (в журнал не идёт)."""
    key = os.environ.get('SALAD_API_KEY', '')
    if not key:
        with open(ex('~/scout-scenes/salad.env'), encoding='utf-8') as f:
            for line in f:
                k, _, v = line.strip().partition('=')
                if k == 'SALAD_API_KEY' and v:
                    key = v.strip('"\'')
    if not key:
        raise RuntimeError('нет SALAD_API_KEY')
    p = subprocess.run(['curl', '-sS', '--fail', '--max-time', '30', '-H', f'Salad-Api-Key: {key}', SALAD_LIST], capture_output=True, text=True, timeout=45)
    if p.returncode != 0:
        raise RuntimeError(f'список групп Salad не получен: curl rc={p.returncode} {p.stderr.strip()[:120]}')
    return json.loads(p.stdout).get('items') or []


def salad_live(fetch=None) -> dict[str, int]:
    """{группа: живых машин} — всё, что не stopped/failed (подъём считается занятым: платная машина уже есть). Как ~/remlab-logs/router-r4/salad_live.sh."""
    out: dict[str, int] = {}
    for x in (fetch or _salad_items)():
        cs = x.get('current_state') or {}
        ic = cs.get('instance_status_counts') or {}
        run = sum(int(ic.get(k) or 0) for k in ('allocating_count', 'creating_count', 'running_count'))
        n = max(run, 1 if cs.get('status') in ('running', 'deploying', 'pending') else 0)
        if n:
            out[str(x.get('name'))] = n
    return out


def cap_machines(rules: dict, wanted: int, run_id: str, fetch=None) -> tuple[int, int, list[str]]:
    """Потолок живых машин Salad на всех (rules.salad_ceiling, владелец TG 1754: ≤10). → (сколько нод можно, живых чужих, свои уже тёплые).
    Свои тёплые ноды этого прогона (те же имена — подхватим, а не создадим) в «чужие» не входят. Не вышло прочитать счёт — исключение (на деньгах молча не стартуем)."""
    ceiling = int(rules.get('salad_ceiling', 10))
    live = salad_live(fetch)
    mine = {GROUP_PREFIX + suffix_of(rules, run_id, i) for i in range(wanted)}
    mine_live = sorted(n for n in live if n in mine)
    other = sum(v for n, v in live.items() if n not in mine)
    return max(0, min(wanted, ceiling - other)), other, mine_live


def free_gb(path: str) -> float:
    import shutil
    os.makedirs(path, exist_ok=True)
    return shutil.disk_usage(path).free / 2**30


def tag_of(idx: int, rnd: int = 0) -> str:
    return f'sh{idx}' if rnd == 0 else f'sh{idx}r{rnd}'


def stage_cmd(rules: dict, sha: str, start: str, idx: int, skus: list[str], run_dir: str, run_id: str, base_tree: str | None, inputs_file: str | None, apply: bool, rnd: int = 0,
              queue: str | None = None) -> list[str]:
    """Команда одной ноды: heavy-slot → timeout → stage_trial. Всё, кроме пути, — из rules. rnd>0 — повтор упавших (свои папка и группа).
    queue — папка общей очереди: все ноды пишут в один `out/q`, а не каждая в свой `out/sh<N>`."""
    c, hs = rules['caps'], rules['heavy_slot']
    tag = tag_of(idx, rnd)
    out = os.path.join(run_dir, 'out', 'q' if queue else tag)
    t = int(c['job_wait_min']) * 60 + 600
    py = ex(rules['python'])
    cmd = [HEAVY, f'paid-loop5-{run_id}-{tag}', '--min-gb', str(hs['min_gb_salad']), '--cores', str(hs['cores_salad']), '--prio', str(hs['prio']), '--timeout', str(t + 300), '--',
           'timeout', '-k', '20', str(t), py, '-I', STAGE_TRIAL, '--image', rules['image'], '--stages', rules['stages'][start], '--out', out, '--suffix', suffix_of(rules, run_id, idx, rnd),
           '--code-ref', sha, '--repo', ROOT, '--catalog', ex(rules['catalog']), '--probe-cap', str(c['probe_usd']), '--cap', str(c['cap_usd']), '--max-min', str(c['max_min'])]
    if rules.get('parts_root'):
        cmd += ['--parts-root', ex(rules['parts_root'])]
    if warm_on(rules):
        wm = rules['warm']
        cmd += ['--keep-warm', str(wm['idle_min']), '--warm-life-min', str(wm['life_min']), '--warm-min-left-min', str(wm['min_left_min'])]
    nd = rules.get('node') or {}
    if nd.get('variant'):
        cmd += ['--variant', nd['variant']]
    for k, flag in (('procs', '--procs'), ('fill_procs', '--fill-procs'), ('threads', '--threads')):
        if nd.get(k):
            cmd += [flag, str(nd[k])]
    if queue:
        cmd += ['--queue', queue, '--nodes', str(node_count(rules, len(skus))), '--slots', str(int((rules.get('queue') or {}).get('slots') or 0)), '--requeue-max', str(int((rules.get('queue') or {}).get('requeue_max', 1)))]
    if start == '08':
        cmd += ['--fill-root', base_tree, '--vis-root', base_tree, '--skus', ','.join(skus)]
        if rules.get('pose_root'):
            pr = rules['pose_root']
            cmd += ['--pose-root', ','.join(ex(x) for x in (pr if isinstance(pr, list) else [pr]))]            # несколько корней: камера этапа 4 лежит в разных пакетах (t173-4, t184 pose-out-rest/g*)
    else:
        cmd += ['--inputs', inputs_file]
    if apply:
        cmd.append('--apply')
    return cmd


def sheet_job(rules: dict, glb: str, photo: str, png: str) -> list[str]:
    """Старый путь (mode != batch): один процесс на товар, numpy-рендер `loop5_sides.py` (≈5 мин на товар)."""
    c = [a.format(python=ex(rules['python']), root=ROOT) for a in rules['sheets']['cmd']]
    return c + [glb, photo, png]


def sheet_items(jobs: list[tuple]) -> list[dict]:
    """items.json для `sides_sheet.py batch`: id = имя png без расширения; «перед» = камера фото (az из 06-visible/check.json товара)."""
    items = []
    for j in jobs:
        g, p, o = j[:3]
        it = {'id': os.path.splitext(os.path.basename(o))[0], 'glb': g, 'photo': p}
        if len(j) > 3 and j[3]:
            it['check06'] = j[3]
        if len(j) > 4 and j[4] is not None:
            it['az'] = float(j[4])                                       # «перёд» решён front_axis (T-47): камера листа = θ, check06 для ракурса не нужен
        items.append(it)
    return items


def batch_cmd(rules: dict, items_path: str, out: str) -> list[str]:
    """Команда листов браузером (T-27, tools/assets/sides_sheet.py batch): один Chromium, товары по очереди; под heavy-slot (ядра/память — rules.heavy_slot.*_batch)."""
    hs = rules['heavy_slot']
    c = [a.format(python=ex(rules['python']), root=ROOT) for a in rules['sheets']['cmd']]
    return [HEAVY, 'loop5-sheets', '--min-gb', str(hs['min_gb_sheets_batch']), '--cores', str(hs['cores_sheets_batch']), '--prio', str(hs['prio']), '--timeout', '1500', '--',
            *c, *(['--clay'] if rules['sheets'].get('clay') else []), '--items', items_path, '--out', out]


def run_sheets(rules: dict, jobs: list[tuple], log: str) -> int:
    """Листы «со всех сторон» на наших ядрах под heavy-slot; готовые png (непустые) пропускаются. mode=batch — браузером одним вызовом (все jobs в одной папке), иначе — по процессу на товар."""
    todo = [j for j in jobs if not (os.path.isfile(j[2]) and os.path.getsize(j[2]) > 0)]               # пустой png (диск был полон) — не «готово»
    if not todo:
        return 0
    for j in todo:
        os.makedirs(os.path.dirname(j[2]), exist_ok=True)
    if rules['sheets'].get('mode') == 'batch':
        outs = {os.path.dirname(j[2]) for j in todo}
        if len(outs) != 1:
            raise ValueError(f'листы batch: все png в одной папке, получено {sorted(outs)}')
        items_path = log + '.items.json'
        with open(items_path, 'w', encoding='utf-8') as f:
            json.dump(sheet_items(todo), f, ensure_ascii=False, indent=1)
        cmd = batch_cmd(rules, items_path, outs.pop())
    else:
        lst = log + '.list'
        with open(lst, 'w', encoding='utf-8') as f:
            for j in todo:
                f.write(' '.join(shlex.quote(x) for x in sheet_job(rules, *j[:3])) + '\n')
        hs = rules['heavy_slot']
        par = int(rules['sheets']['parallel'])
        cmd = [HEAVY, 'loop5-sheets', '--min-gb', str(hs['min_gb_sheets']), '--cores', str(hs['cores_sheets']), '--prio', str(hs['prio']), '--timeout', '1500', '--',
               'bash', '-c', f'xargs -P{par} -I{{}} bash -c {{}} < {shlex.quote(lst)}']
    with open(log, 'w', encoding='utf-8') as lf:
        return subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT).returncode


def front_of(rules: dict, glb: str, check06: str, res_dir: str, base_dir: str) -> dict:
    """«Перёд» листа товара = front_axis_resolved (tools/scout/front_axis.py): orient (если лежит `07-fill/orient.json` результата или «до») → камера 04 по геометрии → unknown.
    Неизвестен — лист по камере 04 как раньше, флаг front_unknown в таблице."""
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))
    import front_axis as FA
    op = next((p for p in (os.path.join(d, '07-fill', 'orient.json') for d in (res_dir, base_dir) if d) if os.path.isfile(p)), None)
    return FA.resolve_from_files(glb, check06, op)


def run_eval(rules: dict, sheets_dir: str, out_dir: str, items: list[dict]) -> dict:
    """sides_eval.batch по листам «после» (+ глина, если rules.sheets.clay): {sku: {score, ok, fails:[{view, feature, r}], front}} и сводка {items, passed_all, passed_all_pct, worst_first}.
    Предохранитель ракурса front_guard выключен: перёд уже решён front_axis (у items есть az и нет check06)."""
    sys.path.insert(0, HERE)
    import sides_eval as SE
    by_id = {it['id']: it for it in items}
    r = SE.batch(sheets_dir, out_dir, [i for i in by_id], items=by_id)
    out = {}
    for sku, v in r['eval'].items():
        fails = []
        for view, fs in v['views'].items():
            for f, d in fs.items():
                if f != 'na' and d.get('r') is not None and d['r'] > 1:
                    fails.append({'view': view, 'feature': f, 'r': d['r']})
        out[sku] = {'score': v['score'], 'ok': v['ok'], 'fails': sorted(fails, key=lambda x: -x['r']), 'views': v['views']}
    return {'per_sku': out, 'summary': r['summary']}


def eval_html(ev: dict, fronts: dict | None = None) -> str:
    """Таблица worst-first: сверху общий % «все 5»; по товару — решётка признак × сторона (число r, > 1 красным), «перёд» и его источник."""
    s = ev['summary']
    feats = ['patches', 'sharpness', 'uniform', 'pattern', 'underpaint']
    views = ['перед', '3/4', 'бок', 'зад', 'др. бок', 'верх']
    pct = s.get('passed_all_pct')
    out = [f'<h2>Автооценка: все 5 признаков на всех сторонах — {s["passed_all"]} из {s["items"]}' + (f' ({pct} %)' if pct is not None else '') + '</h2>'
           '<p>Худшие сверху. Число — «насколько плохо к допуску» (r ≤ 1 — прошло, красным — не прошло); «—» — признак к стороне не применяется.</p>']
    for sku in s['worst_first']:
        v = ev['per_sku'][sku]
        fr = (fronts or {}).get(sku) or {}
        fl = ' '.join(fr.get('flags') or [])
        src = fr.get('source') or ('не решён' if fr else '')
        sc = '—' if v['score'] is None else f'{v["score"]:.2f}'
        rows = []
        for f in feats:
            cells = []
            for vw in views:
                d = (v['views'].get(vw) or {}).get(f) if 'na' not in (v['views'].get(vw) or {}) else None
                if not d or d.get('r') is None:
                    cells.append('<td>—</td>')
                else:
                    bad = d['r'] > 1
                    cells.append(f'<td style="{"background:#fbb;font-weight:bold" if bad else ""}">{d["r"]:.2f}</td>')
            rows.append(f'<tr><th align="left">{f}</th>{"".join(cells)}</tr>')
        out.append(f'<h4>{html.escape(sku)} — оценка {sc} {"✓ все 5" if v["ok"] else "✗"} · перёд: {html.escape(str(src))} {html.escape(fl)}</h4>'
                   f'<table border="1" cellpadding="3" style="border-collapse:collapse;font-size:13px"><tr><th></th>{"".join(f"<th>{x}</th>" for x in views)}</tr>{"".join(rows)}</table>')
    return ''.join(out)


def eval_after(rules: dict, run_dir: str, jobs: list[tuple], fronts: dict) -> tuple[dict | None, str]:
    """Оценка листов «после» сама, без ручного шага: (ev, html таблицы). Нет ни одного листа — (None, ''); сбой оценки не роняет круг (❗ в странице и в журнале)."""
    sheets = os.path.join(run_dir, 'sheets')
    items = [it for it in sheet_items(jobs) if os.path.isfile(os.path.join(sheets, it['id'] + '.png')) and os.path.getsize(os.path.join(sheets, it['id'] + '.png')) > 0]
    if not items:
        return None, '<p>❗ автооценка: нет ни одного листа «после»</p>'
    try:
        ev = run_eval(rules, sheets, os.path.join(run_dir, 'eval'), items)
    except Exception as e:  # noqa: BLE001
        say(f'❗ автооценка не посчиталась: {type(e).__name__}: {e}')
        return None, f'<p>❗ автооценка не посчиталась: {html.escape(str(e))}</p>'
    s0 = ev['summary']
    say(f'автооценка: все 5 на всех сторонах {s0["passed_all"]} из {s0["items"]} ({s0["passed_all_pct"]} %); худший: {s0["worst_first"][:3]}')
    return ev, eval_html(ev, fronts)


def compose(rules: dict, run_dir: str, sha: str, start: str, rows: list[dict], ev_html: str = '') -> str:
    """Страница «до | после»: png «до над после» на товар + index.html."""
    from PIL import Image, ImageDraw
    page = os.path.join(run_dir, 'page')
    os.makedirs(page, exist_ok=True)
    for r in rows:
        r['img'] = ''
        if all(r.get(k) and os.path.isfile(r[k]) and os.path.getsize(r[k]) > 0 for k in ('before_png', 'after_png')):
            a, b = Image.open(r['before_png']).convert('RGB'), Image.open(r['after_png']).convert('RGB')
            w = max(a.width, b.width)
            im = Image.new('RGB', (w, a.height + b.height + 36), 'white')
            d = ImageDraw.Draw(im)
            d.text((6, 4), 'BEFORE  (out-batch2, T-20)', fill='black')
            im.paste(a, (0, 18))
            d.text((6, a.height + 22), f'AFTER  (code {sha[:8]}, from {start})', fill='black')
            im.paste(b, (0, a.height + 36))
            r['img'] = f'{r["sku"]}.png'
            im.save(os.path.join(page, r['img']))
    body = []
    for r in rows:
        st = r['status']
        pic = f'<img src="{r["img"]}" style="max-width:100%">' if r['img'] else '<p>нет листа «после»</p>'
        body.append(f'<h3>{html.escape(r["sku"])} — {html.escape(st)}</h3>{pic}')
    doc = (f'<!doctype html><meta charset="utf-8"><title>круг на 5 — {sha[:8]}</title><body style="font-family:sans-serif;margin:16px">'
           f'<h2>Круг на 5 · код {sha[:8]} · с шага {start}</h2><p>Сверху — «до» (пакет T-20), снизу — «после» (этот прогон). Листы: фото и 6 видов: перед, 3/4, бок, зад, другой бок, верх.</p>'
           + ev_html + ''.join(body) + '</body>')
    p = os.path.join(page, 'index.html')
    open(p, 'w', encoding='utf-8').write(doc)
    return p


def done_sku(d: str) -> bool:
    p = os.path.join(d, '08-material', 'material.glb')
    return os.path.isfile(p) and os.path.getsize(p) > 0


def collect(run_dir: str, skus: list[str]) -> tuple[dict[str, str], dict]:
    """{товар: папка результата с готовым 08-material} (по всем нодам и повторам) и сводка денег/минут нод из summary-trial-stage-*.json."""
    res, money = {}, {'cost_usd_est': 0.0, 'running_s': 0.0, 'groups': 0, 'stop_verified': True, 'kept_warm': 0, 'adopted_warm': 0}
    money['items'] = {}                                                                # товар → секунды по этапам (очередь: из итога цепочки ноды), для таблицы «шаг · с/товар»
    for d in sorted(glob.glob(os.path.join(run_dir, 'out', '*'))):                     # out/sh<N> (делёж заранее) и out/q (общая очередь)
        for s in skus:
            if done_sku(os.path.join(d, s)):
                res[s] = os.path.join(d, s)
        for f in glob.glob(os.path.join(d, 'summary-trial-stage-*.json')):
            with open(f, encoding='utf-8') as fh:
                j = json.load(fh)
            for k, v in (((j.get('jobs') or {}).get('chain') or {}).get('done') or {}).items():
                money['items'][k] = v.get('stage_s') or {}
            money['groups'] += 1
            money['cost_usd_est'] += float(j.get('cost_usd_est') or 0)
            money['running_s'] += float(j.get('running_s') or 0)
            money['kept_warm'] += 1 if j.get('kept_warm') else 0
            money['adopted_warm'] += 1 if j.get('adopted_warm') else 0
            money['stop_verified'] = money['stop_verified'] and bool(j.get('stop_verified') or j.get('kept_warm'))
    return res, money


def run_round(rules: dict, sha: str, start: str, skus: list[str], run_dir: str, run_id: str, base: dict[str, str], base_tree: str | None, apply: bool, rnd: int) -> tuple[list[int], list[list[str]]]:
    """Один заход: товары → ≤machines нод параллельно; после — страховочная остановка групп. → (коды драйверов, группы)."""
    cmds, procs = [], []
    if queue_on(rules):                                                                # все ноды видят весь список товаров и одну очередь `queue-r<заход>`; кто свободен — берёт следующий
        groups = [list(skus) for _ in range(node_count(rules, len(skus)))]
        qdir = os.path.join(run_dir, f'queue-r{rnd}')
        inp = None
        if start != '08':
            inp = os.path.join(run_dir, f'inputs-q{rnd}.json')
            with open(inp, 'w', encoding='utf-8') as fh:
                json.dump(shard_inputs(rules, skus, start, base, os.path.join(run_dir, 'photos')), fh, ensure_ascii=False, indent=1)
        for i in range(len(groups)):
            cmds.append(stage_cmd(rules, sha, start, i, skus, run_dir, run_id, base_tree, inp, apply, rnd, queue=qdir))
    else:
        groups = split(skus, rules['machines'])
        for i, g in enumerate(groups):
            inp = None
            if start != '08':
                inp = os.path.join(run_dir, f'inputs-{tag_of(i, rnd)}.json')
                with open(inp, 'w', encoding='utf-8') as fh:
                    json.dump(shard_inputs(rules, g, start, base, os.path.join(run_dir, 'photos')), fh, ensure_ascii=False, indent=1)
            cmds.append(stage_cmd(rules, sha, start, i, g, run_dir, run_id, base_tree, inp, apply, rnd))
    with open(os.path.join(run_dir, f'plan-r{rnd}.json'), 'w', encoding='utf-8') as fh:
        json.dump({'sha': sha, 'from': start, 'groups': groups, 'cmds': cmds, 'apply': apply}, fh, ensure_ascii=False, indent=1)
    for i, c in enumerate(cmds):
        if not apply:
            say('РАЗБОР: ' + ' '.join(shlex.quote(x) for x in c))
        lf = open(os.path.join(run_dir, f'log-{tag_of(i, rnd)}.log'), 'w', encoding='utf-8')  # noqa: SIM115 — закрываем после wait
        procs.append((subprocess.Popen(c, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL), lf))
    return procs, groups


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='круг «на 5»: пересчёт шага и следующих на золотых 5 + листы «до | после»')
    ap.add_argument('--code-ref', default='', help='SHA/ветка: чей код этапов считает Salad (в итог пишется SHA)')
    ap.add_argument('--from', dest='start', default='', choices=['', '06', '07', '08'], help='с какого шага пересчитывать (этот и следующие)')
    ap.add_argument('--skus', default='', help='подмножество золотых через запятую (по умолчанию все)')
    ap.add_argument('--run-id', default=time.strftime('%H%M', time.gmtime()))
    ap.add_argument('--dry', action='store_true', help='только разбор: проверки и команды, Salad не создаётся, листов нет')
    ap.add_argument('--machines', type=int, default=0, help='сколько нод одновременно (по умолчанию rules.machines; меньше — если рядом уже идёт другой прогон)')
    ap.add_argument('--no-warm', action='store_true', help='не греть ноды между прогонами (как до T-34): группа на прогон, гасится в конце')
    ap.add_argument('--warm-stop', action='store_true', help='погасить тёплые ноды сейчас (с проверкой «0 нод») и выйти')
    ap.add_argument('--rules', default=RULES)
    a = ap.parse_args(argv)
    t0 = time.time()
    rules = load_rules(a.rules)
    if a.machines:
        rules['machines'] = min(a.machines, int(rules['machines']))
    if a.no_warm:
        rules.setdefault('warm', {})['enabled'] = False
    if a.warm_stop:
        rules.setdefault('warm', {})['enabled'] = True
        bad = [i for i in range(int(rules['machines'])) if not stop_group(rules, a.run_id, i)]
        say(f'тёплые ноды погашены: {int(rules["machines"]) - len(bad)} из {int(rules["machines"])}' + (f'; ❗ не подтверждено у нод {bad}' if bad else ''))
        return 1 if bad else 0
    if not a.warm_stop and (not a.code_ref or not a.start):
        raise SystemExit('нужны --code-ref и --from 06|07|08 (или --warm-stop)')
    skus = [s for s in rules['golden'] if not a.skus or s in a.skus.split(',')]
    if not skus:
        raise SystemExit('нет товаров: --skus не совпал с золотыми')
    sha = resolve_sha(a.code_ref)
    base = base_dirs(rules, skus)
    bad = need_files(a.start, base)
    if bad:
        raise SystemExit('нет входов «до» для шага: ' + '; '.join(bad[:6]))
    want = node_count(rules, len(skus))
    try:                                                                           # потолок живых машин Salad на всех: перед стартом смотрим живой счёт, нод = min(запрошено, 10 − чужие живые)
        can, other, mine_live = cap_machines(rules, want, a.run_id)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as exc:
        if not a.dry:
            raise SystemExit(f'не смог прочитать живой счёт Salad ({exc}) — платный прогон не стартую (потолок {rules.get("salad_ceiling", 10)})')
        say(f'⚠ живой счёт Salad не прочитан ({exc}) — в разборе потолок не проверен')
        can, other, mine_live = want, -1, []
    if other >= 0:
        say(f'Salad живо: чужих машин {other}, своих тёплых {len(mine_live)}; потолок {rules.get("salad_ceiling", 10)} → нод можно {can} из {want}')
    if can <= 0:
        raise SystemExit(f'ОТКАЗ: потолок {rules.get("salad_ceiling", 10)} живых машин Salad исчерпан (чужих живых {other}) — прогон не стартую; дождись освобождения или погаси лишнее')
    if can < want:
        say(f'нод урезано {want} → {can} по потолку живых машин')
        rules['machines'] = can
    run_dir = os.path.join(ex(rules['out_root']), f'{a.run_id}-from{a.start}-{sha[:8]}')
    os.makedirs(os.path.join(run_dir, 'out'), exist_ok=True)
    say(f'круг на 5: код {sha[:8]} ({a.code_ref}), с шага {a.start} → этапы {rules["stages"][a.start]}; товаров {len(skus)}, нод Salad {node_count(rules, len(skus))} (≤{rules["machines"]}), '
        f'{"общая очередь, слотов на ноду " + str((rules.get("queue") or {}).get("slots") or "по fill_procs") if queue_on(rules) else "товары делятся заранее"}; папка {run_dir}')
    say('Salad или ядра: Salad (CPU-нода low, цепочка 06→08 на 5 товаров ≈ $0,01), как в T-20; листы — наши ядра')
    base_tree = None
    if a.start == '08':
        base_tree = os.path.join(run_dir, 'base')
        os.makedirs(base_tree, exist_ok=True)
        for s, d in base.items():
            if not os.path.lexists(os.path.join(base_tree, s)):
                os.symlink(d, os.path.join(base_tree, s))
    min_gb = float(rules.get('min_free_gb', 2))
    if not a.dry and free_gb(run_dir) < min_gb:
        raise SystemExit(f'мало места на диске: свободно {free_gb(run_dir):.1f} ГБ < {min_gb} ГБ (rules.min_free_gb) — платный прогон не стартую')
    photo = photos(rules, os.path.join(run_dir, 'photos'))
    if not a.dry:
        check_sheet_photos(photo, skus)
    rcs, rnd_log = [], []
    t_salad = 0.0
    sheets_before = {s: os.path.join(ex(rules['out_root']), 'base-sheets-b', f'{s}.png') for s in skus}
    rc_b = 0
    sheets_s = [0.0, 0.0]                                                  # секунды на листы «до» и «после»
    todo = list(skus)
    for rnd in range(int(rules.get('retry_rounds', 1)) + 1):
        if not todo:
            break
        procs, groups = run_round(rules, sha, a.start, todo, run_dir, a.run_id, base, base_tree, not a.dry, rnd)
        if rnd == 0 and not a.dry:
            # «до»: листы на наших ядрах параллельно с Salad (кэш на все прогоны)
            jobs = [(before_glb(rules, s, base[s]), photo[s], sheets_before[s], os.path.join(base[s], '06-visible', 'check.json')) for s in skus]
            os.makedirs(os.path.join(ex(rules['out_root']), 'base-sheets-b'), exist_ok=True)
            t_sb = time.time()
            rc_b = run_sheets(rules, jobs, os.path.join(run_dir, 'sheets-before.log'))
            sheets_s[0] = round(time.time() - t_sb, 1)
            say(f'листы «до»: rc={rc_b}, готово {sum(os.path.isfile(p) and os.path.getsize(p) > 0 for p in sheets_before.values())} из {len(skus)}')
        codes = []
        for p, lf in procs:
            codes.append(p.wait())
            lf.close()
        rcs += codes
        if not a.dry:
            for i, c in enumerate(codes):
                if warm_on(rules) and c == 0:
                    continue                                                   # чистый конец: нода осталась тёплой — сама остановится через rules.warm.idle_min простоя
                if not stop_group(rules, a.run_id, i, rnd):
                    say(f'❗ группа {suffix_of(rules, a.run_id, i, rnd)}: остановка не подтверждена — гасить вручную (stage_trial --stop-only --suffix {suffix_of(rules, a.run_id, i, rnd)})')
        t_salad = time.time() - t0
        say(f'Salad, заход {rnd}: коды {codes}, {t_salad / 60:.1f} мин от старта')
        if a.dry:
            return 1 if any(rcs) else 0
        res, money = collect(run_dir, skus)
        todo = [s for s in skus if s not in res]
        if todo and rnd < int(rules.get('retry_rounds', 1)):
            say(f'повтор только упавших ({len(todo)}): {todo}')
    res, money = collect(run_dir, skus)
    sheets_after = {s: os.path.join(run_dir, 'sheets', f'{s}.png') for s in skus}
    jobs = [(os.path.join(res[s], '08-material', 'material.glb'), photo[s], sheets_after[s],
             next((c for c in (os.path.join(res[s], '06-visible', 'check.json'), os.path.join(base[s], '06-visible', 'check.json')) if os.path.isfile(c)), '')) for s in skus if s in res]
    fronts = {}
    for j in list(jobs):                                                   # «перёд» листа «после» — front_axis_resolved, не голая камера 04 (T-47)
        sku = os.path.splitext(os.path.basename(j[2]))[0]
        fronts[sku] = front_of(rules, j[0], j[3], res[sku], base[sku]) if j[3] else {'theta': None, 'flags': ['front_unknown:no_check06'], 'source': None}
        if fronts[sku].get('theta') is not None:
            jobs[jobs.index(j)] = (*j[:4], fronts[sku]['theta'])
        say(f'перёд {sku[-12:]}: θ={fronts[sku].get("theta")} ({fronts[sku].get("source")}) {fronts[sku].get("flags") or ""}')
    t_sa = time.time()
    rc_a = run_sheets(rules, jobs, os.path.join(run_dir, 'sheets-after.log'))
    sheets_s[1] = round(time.time() - t_sa, 1)
    ev, ev_html = eval_after(rules, run_dir, jobs, fronts)
    rows = []
    for s in skus:
        ok = s in res
        rows.append({'sku': s, 'status': 'пересчитан' if ok else 'ОТКАЗ (нет 08-material/material.glb — см. log-sh*.log)', 'before_png': sheets_before[s], 'after_png': sheets_after[s]})
    page = compose(rules, run_dir, sha, a.start, rows, ev_html)
    t_all = time.time() - t0
    summ = {'code_ref': a.code_ref, 'sha': sha, 'from': a.start, 'run_dir': run_dir, 'page': page, 'seconds_salad': round(t_salad), 'seconds_total': round(t_all), 'codes': rcs, 'sheets_rc': [rc_b, rc_a], 'sheets_s': sheets_s,
            'money': money, 'skus': {r['sku']: r['status'] for r in rows},
            'eval': None if ev is None else {'passed_all': ev['summary']['passed_all'], 'items': ev['summary']['items'], 'passed_all_pct': ev['summary']['passed_all_pct'], 'worst_first': ev['summary']['worst_first'],
                                              'per_sku': {k: {'score': v['score'], 'ok': v['ok'], 'fails': v['fails'], 'front': {x: (fronts.get(k) or {}).get(x) for x in ('theta', 'source', 'flags')}} for k, v in ev['per_sku'].items()}}}
    with open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8') as fh:
        json.dump(summ, fh, ensure_ascii=False, indent=1)
    say(f'ГОТОВО за {t_all / 60:.1f} мин (Salad {t_salad / 60:.1f}); нод {money["groups"]}, ≈${money["cost_usd_est"]:.3f}, остановка подтверждена: {money["stop_verified"]}; страница {page}')
    fails = [r['sku'] for r in rows if r['status'] != 'пересчитан']
    if fails:
        say(f'ОТКАЗЫ: {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

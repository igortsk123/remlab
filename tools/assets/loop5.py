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
Деплоя нет, `.env*` не читается (ключ Salad берёт сам драйвер как у T-220). Временное — `<out_root>/<прогон>/`."""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import html
import json
import os
import shlex
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


def shard_inputs(rules: dict, skus: list[str], start: str, base: dict[str, str]) -> dict[str, dict]:
    """Строки входа stage_trial для товаров (06 и 07 — из пакета 29; для 07 добавляется vis = 06-visible «до»)."""
    allv: dict[str, dict] = {}
    for f in sorted(glob.glob(ex(rules['shard_inputs_glob']))):
        allv.update(json.load(open(f, encoding='utf-8')))
    miss = [s for s in skus if s not in allv]
    if miss:
        raise SystemExit(f'нет строки входа в {rules["shard_inputs_glob"]}: {miss}')
    sel = {s: json.loads(json.dumps(allv[s])) for s in skus}
    if start == '07':
        for s in skus:
            sel[s]['vis'] = os.path.join(base[s], '06-visible')
    return sel


def stage_cmd(rules: dict, sha: str, start: str, idx: int, skus: list[str], run_dir: str, run_id: str, base_tree: str | None, inputs_file: str | None, apply: bool) -> list[str]:
    """Команда одной ноды: heavy-slot → timeout → stage_trial. Всё, кроме пути, — из rules."""
    c, hs = rules['caps'], rules['heavy_slot']
    out = os.path.join(run_dir, 'out', f'sh{idx}')
    t = int(c['job_wait_min']) * 60 + 600
    py = ex(rules['python'])
    cmd = [HEAVY, f'paid-loop5-{run_id}-sh{idx}', '--min-gb', str(hs['min_gb_salad']), '--cores', str(hs['cores_salad']), '--prio', str(hs['prio']), '--timeout', str(t + 300), '--',
           'timeout', '-k', '20', str(t), py, '-I', STAGE_TRIAL, '--image', rules['image'], '--stages', rules['stages'][start], '--out', out, '--suffix', f'l5{run_id}s{idx}',
           '--code-ref', sha, '--repo', ROOT, '--catalog', ex(rules['catalog']), '--probe-cap', str(c['probe_usd']), '--cap', str(c['cap_usd']), '--max-min', str(c['max_min'])]
    if rules.get('parts_root'):
        cmd += ['--parts-root', ex(rules['parts_root'])]
    if start == '08':
        cmd += ['--fill-root', base_tree, '--vis-root', base_tree, '--skus', ','.join(skus)]
        if rules.get('pose_root'):
            cmd += ['--pose-root', ex(rules['pose_root'])]
    else:
        cmd += ['--inputs', inputs_file]
    if apply:
        cmd.append('--apply')
    return cmd


def sheet_job(rules: dict, glb: str, photo: str, png: str) -> list[str]:
    c = [a.format(python=ex(rules['python']), root=ROOT) for a in rules['sheets']['cmd']]
    return c + [glb, photo, png]


def run_sheets(rules: dict, jobs: list[tuple[str, str, str]], log: str) -> int:
    """Листы «со всех сторон» на наших ядрах под heavy-slot (параллельно `parallel`); готовые png пропускаются."""
    todo = [j for j in jobs if not os.path.isfile(j[2])]
    if not todo:
        return 0
    lst = log + '.list'
    with open(lst, 'w', encoding='utf-8') as f:
        for g, p, o in todo:
            os.makedirs(os.path.dirname(o), exist_ok=True)
            f.write(' '.join(shlex.quote(x) for x in sheet_job(rules, g, p, o)) + '\n')
    hs = rules['heavy_slot']
    par = int(rules['sheets']['parallel'])
    cmd = [HEAVY, 'loop5-sheets', '--min-gb', str(hs['min_gb_sheets']), '--cores', str(hs['cores_sheets']), '--prio', str(hs['prio']), '--timeout', '1500', '--',
           'bash', '-c', f'xargs -P{par} -I{{}} bash -c {{}} < {shlex.quote(lst)}']
    with open(log, 'w', encoding='utf-8') as lf:
        return subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT).returncode


def compose(rules: dict, run_dir: str, sha: str, start: str, rows: list[dict]) -> str:
    """Страница «до | после»: png «до над после» на товар + index.html."""
    from PIL import Image, ImageDraw
    page = os.path.join(run_dir, 'page')
    os.makedirs(page, exist_ok=True)
    for r in rows:
        r['img'] = ''
        if r.get('before_png') and r.get('after_png') and os.path.isfile(r['before_png']) and os.path.isfile(r['after_png']):
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
           + ''.join(body) + '</body>')
    p = os.path.join(page, 'index.html')
    open(p, 'w', encoding='utf-8').write(doc)
    return p


def collect(run_dir: str, skus: list[str], nshards: int) -> tuple[dict[str, str], dict]:
    """{товар: папка результата} и сводка денег/минут нод из summary-trial-stage-*.json."""
    res, money = {}, {'cost_usd_est': 0.0, 'running_s': 0.0, 'groups': 0, 'stop_verified': True}
    for i in range(nshards):
        d = os.path.join(run_dir, 'out', f'sh{i}')
        for s in skus:
            if os.path.isdir(os.path.join(d, s)):
                res[s] = os.path.join(d, s)
        for f in glob.glob(os.path.join(d, 'summary-trial-stage-*.json')):
            j = json.load(open(f, encoding='utf-8'))
            money['groups'] += 1
            money['cost_usd_est'] += float(j.get('cost_usd_est') or 0)
            money['running_s'] += float(j.get('running_s') or 0)
            money['stop_verified'] = money['stop_verified'] and bool(j.get('stop_verified'))
    return res, money


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='круг «на 5»: пересчёт шага и следующих на золотых 5 + листы «до | после»')
    ap.add_argument('--code-ref', required=True, help='SHA/ветка: чей код этапов считает Salad (в итог пишется SHA)')
    ap.add_argument('--from', dest='start', required=True, choices=['06', '07', '08'], help='с какого шага пересчитывать (этот и следующие)')
    ap.add_argument('--skus', default='', help='подмножество золотых через запятую (по умолчанию все)')
    ap.add_argument('--run-id', default=time.strftime('%H%M', time.gmtime()))
    ap.add_argument('--dry', action='store_true', help='только разбор: проверки и команды, Salad не создаётся, листов нет')
    ap.add_argument('--rules', default=RULES)
    a = ap.parse_args(argv)
    t0 = time.time()
    rules = load_rules(a.rules)
    skus = [s for s in rules['golden'] if not a.skus or s in a.skus.split(',')]
    if not skus:
        raise SystemExit('нет товаров: --skus не совпал с золотыми')
    sha = resolve_sha(a.code_ref)
    base = base_dirs(rules, skus)
    bad = need_files(a.start, base)
    if bad:
        raise SystemExit('нет входов «до» для шага: ' + '; '.join(bad[:6]))
    run_dir = os.path.join(ex(rules['out_root']), f'{a.run_id}-from{a.start}-{sha[:8]}')
    os.makedirs(os.path.join(run_dir, 'out'), exist_ok=True)
    groups = split(skus, rules['machines'])
    say(f'круг на 5: код {sha[:8]} ({a.code_ref}), с шага {a.start} → этапы {rules["stages"][a.start]}; товаров {len(skus)}, нод Salad {len(groups)} (≤{rules["machines"]}); папка {run_dir}')
    say('Salad или ядра: Salad (CPU-нода low, цепочка 06→08 на 5 товаров ≈ $0,01), как в T-20; листы — наши ядра')
    base_tree = None
    if a.start == '08':
        base_tree = os.path.join(run_dir, 'base')
        os.makedirs(base_tree, exist_ok=True)
        for s, d in base.items():
            if not os.path.lexists(os.path.join(base_tree, s)):
                os.symlink(d, os.path.join(base_tree, s))
    cmds, procs = [], []
    for i, g in enumerate(groups):
        inp = None
        if a.start != '08':
            inp = os.path.join(run_dir, f'inputs-sh{i}.json')
            json.dump(shard_inputs(rules, g, a.start, base), open(inp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        cmds.append(stage_cmd(rules, sha, a.start, i, g, run_dir, a.run_id, base_tree, inp, not a.dry))
    json.dump({'code_ref': a.code_ref, 'sha': sha, 'from': a.start, 'groups': groups, 'cmds': cmds, 'dry': a.dry}, open(os.path.join(run_dir, 'plan.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if a.dry:
        for c in cmds:
            say('РАЗБОР: ' + ' '.join(shlex.quote(x) for x in c))
    for i, c in enumerate(cmds):
        lf = open(os.path.join(run_dir, f'log-sh{i}.log'), 'w', encoding='utf-8')
        procs.append((subprocess.Popen(c, stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL), lf))
    # «до»: листы на наших ядрах параллельно с Salad (кэш на все прогоны)
    sheets_before = {s: os.path.join(ex(rules['out_root']), 'base-sheets', f'{s}.png') for s in skus}
    rc_b = 0
    if not a.dry:
        jobs = [(before_glb(rules, s, base[s]), os.path.join(base[s], '07-fill', 'frame-photo.png'), sheets_before[s]) for s in skus]
        os.makedirs(os.path.join(ex(rules['out_root']), 'base-sheets'), exist_ok=True)
        rc_b = run_sheets(rules, jobs, os.path.join(run_dir, 'sheets-before.log'))
        say(f'листы «до»: rc={rc_b}, готово {sum(os.path.isfile(p) for p in sheets_before.values())} из {len(skus)} (кэш {os.path.join(ex(rules["out_root"]), "base-sheets")})')
    rcs = []
    for p, lf in procs:
        rcs.append(p.wait())
        lf.close()
    t_salad = time.time() - t0
    say(f'Salad: коды {rcs}, {t_salad / 60:.1f} мин от старта')
    if a.dry:
        return 1 if any(rcs) else 0
    res, money = collect(run_dir, skus, len(groups))
    sheets_after = {s: os.path.join(run_dir, 'sheets', f'{s}.png') for s in skus}
    jobs = [(os.path.join(res[s], '08-material', 'material.glb'), os.path.join(res[s], '07-fill', 'frame-photo.png') if os.path.isfile(os.path.join(res[s], '07-fill', 'frame-photo.png'))
             else os.path.join(base[s], '07-fill', 'frame-photo.png'), sheets_after[s]) for s in skus if s in res and os.path.isfile(os.path.join(res[s], '08-material', 'material.glb'))]
    rc_a = run_sheets(rules, jobs, os.path.join(run_dir, 'sheets-after.log'))
    rows = []
    for s in skus:
        ok = s in res and os.path.isfile(os.path.join(res[s], '08-material', 'material.glb'))
        rows.append({'sku': s, 'status': 'пересчитан' if ok else 'ОТКАЗ (нет 08-material/material.glb — см. log-sh*.log)', 'before_png': sheets_before[s], 'after_png': sheets_after[s]})
    page = compose(rules, run_dir, sha, a.start, rows)
    t_all = time.time() - t0
    summ = {'code_ref': a.code_ref, 'sha': sha, 'from': a.start, 'run_dir': run_dir, 'page': page, 'seconds_salad': round(t_salad), 'seconds_total': round(t_all), 'codes': rcs, 'sheets_rc': [rc_b, rc_a],
            'money': money, 'skus': {r['sku']: r['status'] for r in rows}}
    json.dump(summ, open(os.path.join(run_dir, 'summary.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    say(f'ГОТОВО за {t_all / 60:.1f} мин (Salad {t_salad / 60:.1f}); нод {money["groups"]}, ≈${money["cost_usd_est"]:.3f}, остановка подтверждена: {money["stop_verified"]}; страница {page}')
    fails = [r['sku'] for r in rows if r['status'] != 'пересчитан']
    if fails:
        say(f'ОТКАЗЫ: {fails}')
    return 1 if fails or any(rcs) else 0


if __name__ == '__main__':
    sys.exit(main())

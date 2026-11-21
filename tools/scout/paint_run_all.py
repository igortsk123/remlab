#!/usr/bin/env python3
"""Прогон ВСЕХ этапов пути покраски на ОДНОМ run (план paint-photo-fill-01, T-20261121-169/4, обвязка для сквозной приёмки).

ЗАЧЕМ. Этапы 01–08 писали разные исполнители в разные папки прогонов; настоящая приёмка — один товар прошёл все этапы подряд своим кодом, и этап 9 прочитал ИХ check.json.
Обвязка ничего не считает сама: вызывает команду каждого этапа из `rules/paint-run-all.json` (что запускать — там, не в коде), после каждого читает check.json этапа
и НЕ даёт этапу вход, не прошедший гейт предыдущего: этап «заблокирован», если любой из его `needs` в статусе отказ/нет (мягкий — идёт дальше, как в этапе 9).
Незапущенный/заблокированный этап честно остаётся без check.json — этап 9 покажет «нет этапа».

Запуск (БЕЗ запуска по умолчанию нельзя: сперва `plan`; платного/сетевого обвязка не запускает, тяжёлые шаги — через tools/ops/heavy-slot.sh):
  paint_run_all.py plan <run> <sku> --native родной.glb --photo фото.rgba.png --product-role «комод» [--channels legs,handles]   только напечатать, что и в каком порядке пойдёт
  paint_run_all.py run  <run> <sku> --native … --photo …  [--force] [--only 01-02,04] [--root КОРЕНЬ-репо] [--heavy]               выполнить; повтор пропускает этапы с готовым check.json
  paint_run_all.py status <run> <sku>                                                                                          статусы этапов (без запуска)
Журнал: `<run>/<sku>/run_all.json` (шаги, rc, секунды, статус этапов).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'paint-run-all.json')
sys.path.insert(0, HERE)
import paint_check as PC  # noqa: E402  (классификация этапов — тот же код, что в этапе 9)
import paint_stage as PS  # noqa: E402

_PH = re.compile(r'\{(\w+)\}')


def load_rules(path: str = RULES) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def stage_status(run: str, sku: str, stage: str, check_rules: dict) -> dict:
    """Статус этапа по его check.json (папку НЕ создаём: `PS.stage_dir` создаёт, а чтение не должно)."""
    chk = PS.read_check(os.path.join(run, PS.safe_name(sku), stage))
    return PC.classify_stage(stage, chk, check_rules, run)


def make_ctx(run: str, sku: str, a: dict, rules: dict, stage_dones: dict | None = None) -> dict:
    root = a.get('root') or os.path.abspath(os.path.join(HERE, '..', '..'))
    home = os.path.expanduser('~')
    work = os.path.join(run, PS.safe_name(sku), 'work')
    ctx = {'py': os.path.join(home, 'venvs', 'scout', 'bin', 'python'), 'blender': os.path.join(home, 'opt', 'blender-4.5.9', 'blender'),
           'root': root, 'run': run, 'sku': sku, 'sku_dir': os.path.join(run, PS.safe_name(sku)), 'work': work,
           'prep_glb': os.path.join(work, sku + '-n1024.glb'), 'native': a.get('native', ''), 'photo': a.get('photo', ''),
           'product_role': a.get('product_role', ''), 'channels': a.get('channels', ''), 'cam_az_args': ''}
    ctx.update(rules.get('paths', {}))
    return ctx


def cam_az_args(run: str, sku: str, check_rules: dict, rules: dict) -> list:
    """Азимут камеры в этап 3 — ТОЛЬКО если этап 4 passed (иначе роли с фронтом воздерживаются)."""
    chk = PS.read_check(os.path.join(run, PS.safe_name(sku), rules['camera_stage']))
    if not chk or not chk.get('passed'):
        return []
    try:
        pj = json.load(open(os.path.join(run, PS.safe_name(sku), 'pose.json'), encoding='utf-8'))
        return ['--cam-az', str(pj['camera']['az'])]
    except (OSError, ValueError, KeyError):
        return []


def _subst(argv: list, ctx: dict) -> list:
    out = []
    for tok in argv:
        miss = [k for k in _PH.findall(tok) if k not in ctx]
        if miss:
            raise KeyError(f'в шаге неизвестная подстановка {miss}: {tok}')
        t = _PH.sub(lambda m: str(ctx[m.group(1)]), tok)
        out.append(t)
    return out


def resolve_steps(stage: dict, ctx: dict, extra: dict | None = None) -> list:
    """Шаги этапа с подставленными путями: [{argv, heavy, retry_extra}]. Пустое `{channels}`/`{product_role}` — соответствующие флаги выпадают (`optional`)."""
    steps = []
    for s in stage.get('steps', []):
        argv = []
        for tok in s['argv']:
            if tok == '{cam_az_args}':
                argv += (extra or {}).get('cam_az_args', [])
                continue
            m = _PH.fullmatch(tok)
            if m and m.group(1) in ('channels', 'product_role') and not ctx.get(m.group(1)):
                if argv and argv[-1].startswith('--'):
                    argv.pop()                                              # убрать и сам флаг без значения
                continue
            argv.append(tok)
        steps.append({'argv': _subst(argv, ctx), 'heavy': s.get('heavy'), 'retry_extra': s.get('retry_extra'), 'cwd': s.get('cwd')})
    return steps


def resolve_files(stage: dict, ctx: dict) -> dict:
    """Служебные файлы этапа (манифест, product.json): {путь: содержимое}; строки внутри проходят те же подстановки."""
    def sub(o):
        if isinstance(o, str):
            return _PH.sub(lambda m: str(ctx[m.group(1)]), o)
        if isinstance(o, list):
            return [sub(x) for x in o]
        if isinstance(o, dict):
            return {k: sub(v) for k, v in o.items()}
        return o
    return {sub(k): sub(v) for k, v in stage.get('write_files', {}).items()}


def _heavy(step: dict, name: str, ctx: dict, rules: dict) -> list:
    h = step.get('heavy')
    if not h:
        return step['argv']
    return [os.path.join(ctx['root'], rules['heavy_slot']), f"paint-{name}-{ctx['sku'][-6:]}", '--prio', str(h.get('prio', 1)),
            '--min-gb', str(h.get('min_gb', 3)), '--cores', str(h.get('cores', 2)), '--'] + step['argv']


def plan(run: str, sku: str, a: dict, rules: dict, check_rules: dict, only: list | None = None) -> list:
    """Чистое решение «что и в каком порядке» по текущим check.json: [{stage, action: run|skip|blocked|pending, why, steps}] — без запуска."""
    ctx = make_ctx(run, sku, a, rules)
    res = []
    state = {}                                                              # этап → статус «как будет» (для блокировки зависимых в плане)
    force = a.get('force')
    for name in rules['order']:
        st = rules['stages'][name]
        if only and name not in only:
            continue
        produces = st['produces']
        have = [stage_status(run, sku, p, check_rules) for p in produces]
        blocked = []
        for n in st.get('needs', []):
            s = state.get(n) or stage_status(run, sku, n, check_rules)['status']
            if s in ('refused', 'missing'):
                blocked.append(f'{n}: {s}')
        item = {'stage': name, 'produces': produces, 'steps': [], 'why': ''}
        if blocked:
            item.update(action='blocked', why='; '.join(blocked))
            for p in produces:
                state[p] = 'missing'
        elif st.get('pending'):
            item.update(action='pending', why=st['pending'])
            for p in produces:
                state[p] = 'missing'
        elif not force and all(h['status'] != 'missing' for h in have):
            item.update(action='skip', why='check.json уже есть: ' + ', '.join(f"{h['stage']}={h['status']}" for h in have))
            for h in have:
                state[h['stage']] = h['status']
        else:
            extra = {'cam_az_args': cam_az_args(run, sku, check_rules, rules)}
            item.update(action='run', steps=resolve_steps(st, ctx, extra), files=resolve_files(st, ctx))
            for p in produces:
                state[p] = 'ok'                                             # оптимистично: настоящий статус — после запуска
        res.append(item)
    return res


def _run_step(step: dict, name: str, ctx: dict, rules: dict, timeout: int, use_heavy: bool) -> dict:
    def go(extra):
        argv = list(step['argv']) + (extra or [])
        t = {'argv': argv, 'heavy': step.get('heavy') if use_heavy else None}
        cmd = _heavy(t, name, ctx, rules) if use_heavy else argv
        t0 = time.time()
        try:
            p = subprocess.run(cmd, cwd=step.get('cwd') or ctx['root'], timeout=timeout, capture_output=True, text=True)
            return {'cmd': cmd, 'rc': p.returncode, 'seconds': round(time.time() - t0, 1), 'tail': (p.stdout + p.stderr)[-600:]}
        except subprocess.TimeoutExpired:
            return {'cmd': cmd, 'rc': 124, 'seconds': round(time.time() - t0, 1), 'tail': 'таймаут'}
    r = go(None)
    if r['rc'] != 0 and step.get('retry_extra'):
        r['retried_with'] = step['retry_extra']
        r = go(step['retry_extra']) | {'first_rc': r['rc']}
    return r


def execute(run: str, sku: str, a: dict, rules: dict, check_rules: dict, only: list | None = None, timeout: int = 3600) -> dict:
    """Выполнить по порядку; перед каждым этапом гейт считается заново по ФАКТИЧЕСКИМ check.json (не по плану)."""
    log = {'sku': sku, 'run': run, 'stages': [], 'started': time.strftime('%Y-%m-%d %H:%M:%S')}
    ctx = make_ctx(run, sku, a, rules)
    os.makedirs(ctx['work'], exist_ok=True)
    for name in rules['order']:
        if only and name not in only:
            continue
        item = next(i for i in plan(run, sku, a, rules, check_rules, [name]))   # решение по фактическому состоянию на сейчас
        entry = {'stage': name, 'action': item['action'], 'why': item['why'], 'steps': []}
        if item['action'] == 'run':
            for path, body in item['files'].items():
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(body, f, ensure_ascii=False, indent=1)
            for s in item['steps']:
                r = _run_step(s, name, ctx, rules, timeout, bool(a.get('heavy')))
                entry['steps'].append(r)
                if r['rc'] != 0:
                    break                                                   # дальнейшие шаги этапа без первого не имеют смысла; статус скажет check.json
        entry['status'] = {p: stage_status(run, sku, p, check_rules)['status'] for p in rules['stages'][name]['produces']}
        log['stages'].append(entry)
        _save(ctx, log)
    log['finished'] = time.strftime('%Y-%m-%d %H:%M:%S')
    _save(ctx, log)
    return log


def _save(ctx: dict, log: dict) -> None:
    os.makedirs(ctx['sku_dir'], exist_ok=True)
    with open(os.path.join(ctx['sku_dir'], 'run_all.json'), 'w', encoding='utf-8') as f:
        json.dump(log, f, ensure_ascii=False, indent=1)


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Прогон всех этапов покраски на одном run: каждый этап своим кодом, без входа, не прошедшего гейт предыдущего')
    ap.add_argument('cmd', choices=('plan', 'run', 'status'))
    ap.add_argument('run')
    ap.add_argument('sku')
    ap.add_argument('--native', default='')
    ap.add_argument('--photo', default='')
    ap.add_argument('--product-role', default='')
    ap.add_argument('--channels', default='')
    ap.add_argument('--root', default='')
    ap.add_argument('--only', default='')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--heavy', action='store_true', help='тяжёлые шаги — через tools/ops/heavy-slot.sh (на pakardev всегда включать)')
    ap.add_argument('--timeout', type=int, default=3600)
    a = ap.parse_args(argv)
    rules, cr = load_rules(), PC.load_rules()
    only = [x for x in a.only.split(',') if x] or None
    d = {'native': a.native, 'photo': a.photo, 'product_role': a.product_role, 'channels': a.channels, 'root': a.root, 'force': a.force, 'heavy': a.heavy}
    if a.cmd == 'status':
        for name in rules['order']:
            for p in rules['stages'][name]['produces']:
                s = stage_status(a.run, a.sku, p, cr)
                print(f"{p:12} {cr['words'][s['status']]:10} {s['reason']}")
        return 0
    if a.cmd == 'plan':
        for it in plan(a.run, a.sku, d, rules, cr, only):
            print(f"{it['stage']:8} {it['action']:8} {it['why']}")
            for path in it.get('files', {}):
                print('           [файл] ' + path)
            for s in it['steps']:
                print('           ' + ' '.join(_heavy(s, it['stage'], make_ctx(a.run, a.sku, d, rules), rules) if a.heavy else s['argv']))
        return 0
    miss = [k for k in ('native', 'photo') if not d[k]]
    if miss:
        print('нужны --native и --photo', file=sys.stderr)
        return 2
    log = execute(a.run, a.sku, d, rules, cr, only, a.timeout)
    for e in log['stages']:
        print(e['stage'], e['action'], e['status'], e['why'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

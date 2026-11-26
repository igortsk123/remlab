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


def product_record(a: dict, sku: str) -> dict | None:
    """Запись товара из выгрузки каталога (`--catalog`, JSON-список или одна запись {sid, name, role, params} — тот же формат, что `material_class.py build --input`
    и `product.json` этапа 8; чтение каталога здесь не дублируется — файл готовит тот же путь). Нет файла или товара → None."""
    p = a.get('catalog')
    if not p:
        return None
    with open(p, encoding='utf-8') as f:
        data = json.load(f)
    for r in data if isinstance(data, list) else [data]:
        if r.get('sid') == sku:
            return {'sid': sku, 'name': r.get('name') or '', 'role': r.get('role') or '', 'params': r.get('params') or {}}
    return None


def catalog_channels(record: dict | None) -> tuple[str, str]:
    """Каналы материала и их классы из записи каталога — тем же `material_class.classify`, что у этапа 8: ("legs,frame", "legs=wood_solid,frame=wood_solid"). Нет записи/ошибка — пусто."""
    if not record:
        return '', ''
    try:
        sys.path.insert(0, os.path.join(HERE, '..', 'assets'))
        import material_class as mc
        res = mc.classify(mc.load_rules(), {'role': record.get('role') or '', 'name': record.get('name') or '', 'params': record.get('params') or {}})
        parts = res.get('parts') or {}
    except Exception:
        return '', ''
    ks = sorted(k for k, v in parts.items() if isinstance(v, dict) and v.get('class'))
    main = (res.get('class') or '') if isinstance(res, dict) else ''
    return ','.join(ks), ','.join([f"{k}={parts[k]['class']}" for k in ks] + ([f'main={main}'] if main else []))


def prep_glb_path(a: dict, sku: str) -> str | None:
    """Готовая форма этапа 2 (`--prep-glb` явно, либо `--prep-dir` + `<sku>-n1024.glb`); нет — None (форму строит этап 01-02)."""
    if a.get('prep_glb'):
        return a['prep_glb']
    if a.get('prep_dir'):
        return os.path.join(a['prep_dir'], sku + '-n1024.glb')
    return None


def make_ctx(run: str, sku: str, a: dict, rules: dict, stage_dones: dict | None = None) -> dict:
    root = a.get('root') or os.path.abspath(os.path.join(HERE, '..', '..'))
    home = os.path.expanduser('~')
    work = os.path.join(run, PS.safe_name(sku), 'work')
    pythons = {k: os.path.join(home, v) for k, v in rules['pythons'].items()}                          # интерпретаторы — из правил (`pythons`), не из кода
    ctx = {'py': pythons[rules.get('default_python', 'scout')], 'pythons': pythons, 'blender': os.path.join(home, 'opt', 'blender-4.5.9', 'blender'),
           'root': root, 'run': run, 'sku': sku, 'sku_dir': os.path.join(run, PS.safe_name(sku)), 'work': work,
           'prep_glb': os.path.join(work, sku + '-n1024.glb'), 'native': a.get('native', ''), 'photo': a.get('photo', ''),
           'channels': a.get('channels', ''), 'cam_az_args': [], '_record': product_record(a, sku)}
    ctx['prep_glb'] = prep_glb_path(a, sku) or ctx['prep_glb']
    ctx['channel_classes'] = a.get('channel_classes', '')
    if ctx['_record'] and not ctx['channels']:                                                        # каналы — из каталога (раньше уходили пустыми: роли с каналом frame/handles/shade не срабатывали)
        ctx['channels'], ctx['channel_classes'] = catalog_channels(ctx['_record'])
    ctx['product_role'] = a.get('product_role') or (ctx['_record'] or {}).get('role', '')
    ctx['photo_cam'], ctx['photo_vis'], ctx['body_only_args'] = ctx['photo'], ctx['photo'], []
    ctx['card'] = os.path.join(work, 'card.json') if ctx['_record'] else ''                          # плоская карточка (`$card_flat`) для шагов с --card (зерно, T-99/7); нет записи каталога — флаг выпадает
    ctx.update(rules.get('paths', {}))
    return ctx


def dynamic_ctx(run: str, sku: str, ctx: dict, rules: dict, state: dict | None = None, check_rules: dict | None = None) -> dict:
    """Значения, зависящие от ФАКТИЧЕСКИХ check.json предыдущих этапов (правила — `rules.dynamic`, по порядку, поздние видят ранние):
    `from_extra [этап, ключ]` — значение из extra (нет → fallback); `file_if_ok [этап, файл]` — файл этапа, если этап passed, мерка не N/A и файл есть (иначе fallback);
    `if_extra_true [этап, ключ]` + `args` — список аргументов, если флаг в extra истинный; `if_extra_true_any [[этап, ключ], …]` — если истинна любая из пар;
    `if_stage_ok {stage, file, args, else_args}` — `args` (с `{path}` = файл этапа), если этап прошёл (ok/soft; в плане — «как будет» из `state`) и файл есть, иначе `else_args`
    (этап 07: части этапа 3 — основной путь, геометрическое разбиение — запасной, когда 3 отказ/нет; файл отказанного 3 мог остаться на диске — потому запасной путь просит явный флаг)."""
    out = dict(ctx)
    base = os.path.join(run, PS.safe_name(sku))
    for key, d in rules.get('dynamic', {}).items():
        if 'from_extra' in d:
            chk = PS.read_check(os.path.join(base, d['from_extra'][0])) or {}
            out[key] = (chk.get('extra') or {}).get(d['from_extra'][1]) or out[d['fallback']]
        elif 'file_if_ok' in d:
            st, fn = d['file_if_ok']
            chk = PS.read_check(os.path.join(base, st)) or {}
            path = os.path.join(base, st, fn)
            usable = chk.get('passed') and not (chk.get('metric') or {}).get('na') and os.path.exists(path)
            out[key] = path if usable else out[d['fallback']]
        elif 'if_extra_true' in d or 'if_extra_true_any' in d:
            pairs = [d['if_extra_true']] if 'if_extra_true' in d else list(d['if_extra_true_any'])      # любая из пар [этап, ключ] истинна → args
            on = False
            for st_, key_ in pairs:
                chk = PS.read_check(os.path.join(base, st_)) or {}
                on = on or bool((chk.get('extra') or {}).get(key_))
            out[key] = list(d['args']) if on else []
        elif 'if_stage_ok' in d:
            c = d['if_stage_ok']
            st = (state or {}).get(c['stage']) or stage_status(run, sku, c['stage'], check_rules or {})['status']
            path = os.path.join(base, c['stage'], c['file'])
            planned = not os.path.exists(os.path.join(base, c['stage'], 'check.json'))               # этап ещё не запускался: файл появится в прогоне
            use = st in ('ok', 'soft') and (os.path.exists(path) or planned)
            out[key] = [x.replace('{path}', path) for x in (c['args'] if use else c.get('else_args', []))]
    return out


def soft_camera_ok(chk: dict, sc: dict) -> bool:
    """«Мягкая» камера (P-062: включать только после просмотра): этап 4 не passed, но силуэт совпал (главная метрика ок, miss/extra ок) и не сошлись ТОЛЬКО перечисленные
    метрики нижней полосы (грубая маска ног) — азимут годится для ролей с фронтом (он задаёт лишь «где перёд»), красить по такой камере по-прежнему нельзя."""
    if not sc.get('enabled'):
        return False
    ms = chk.get('metrics') or {}
    bad = [k for k, v in ms.items() if isinstance(v, dict) and v.get('ok') is False]
    return bool((chk.get('metric') or {}).get('ok')) and bool(bad) and all(k in sc.get('only_failed', []) for k in bad)


def cam_az_args(run: str, sku: str, check_rules: dict, rules: dict) -> list:
    """Азимут камеры в этап 3 — ТОЛЬКО если этап 4 passed (иначе роли с фронтом воздерживаются)."""
    chk = PS.read_check(os.path.join(run, PS.safe_name(sku), rules['camera_stage']))
    if not chk or not (chk.get('passed') or soft_camera_ok(chk, rules.get('soft_camera') or {})):
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


def _step_on(s: dict, ctx: dict) -> bool:
    """Шаг с `enabled_by` ({file, key}: файл правил от корня репо, ключ верхнего уровня) выпадает из плана, пока флаг там не true:
    выключенный шаг не берёт слот heavy-slot и не пишет ничего (T-63: ВЫКЛ = main)."""
    e = s.get('enabled_by')
    if not e:
        return True
    try:
        with open(os.path.join(ctx['root'], e['file']), encoding='utf-8') as f:
            v = json.load(f)
        for k in str(e['key']).split('.'):                                          # ключ может быть вложенным через точку («dilate.uv_gutter_px»: 0 = выкл); обычный ключ — как раньше (T-99/7)
            v = v.get(k) if isinstance(v, dict) else None
        return bool(v)
    except (OSError, ValueError):
        return False                                                                # нет файла правил — шаг не нужен


def resolve_steps(stage: dict, ctx: dict, extra: dict | None = None) -> list:
    """Шаги этапа с подставленными путями: [{argv, heavy, retry_extra}]. Пустое `{channels}`/`{product_role}` — соответствующие флаги выпадают (`optional`)."""
    steps = []
    ctx = {**ctx, **(extra or {})}
    if stage.get('python'):                                                             # этапу нужен другой интерпретатор (правила: `stages.<этап>.python` → `pythons`)
        if stage['python'] not in ctx['pythons']:
            raise KeyError(f"у этапа python {stage['python']!r}, а в правилах `pythons` его нет")
        ctx['py'] = ctx['pythons'][stage['python']]
    for s in stage.get('steps', []):
        if not _step_on(s, ctx):
            continue
        argv = []
        for tok in s['argv']:
            m = _PH.fullmatch(tok)
            if m and isinstance(ctx.get(m.group(1)), list):
                argv += [str(x) for x in ctx[m.group(1)]]                   # {cam_az_args}, {body_only_args}: список аргументов (пустой — ничего)
                continue
            if m and m.group(1) in ('channels', 'product_role', 'channel_classes', 'card') and not ctx.get(m.group(1)):
                if argv and argv[-1].startswith('--'):
                    argv.pop()                                              # убрать и сам флаг без значения
                continue
            argv.append(tok)
        steps.append({'argv': _subst(argv, ctx), 'heavy': s.get('heavy'), 'retry_extra': s.get('retry_extra'), 'cwd': s.get('cwd'),
                      **({'abstain_report': s['abstain_report']} if s.get('abstain_report') else {})})
    return steps


def resolve_files(stage: dict, ctx: dict) -> dict:
    """Служебные файлы этапа (манифест, product.json): {путь: содержимое}; строки внутри проходят те же подстановки."""
    def sub(o):
        if o == '$product_record':
            return ctx['_record']
        if o == '$card_flat':                                                           # карточка плоско: name, role + params (как card.json у проб; нужна зерну для габарита → см на текстель)
            r = ctx['_record'] or {}
            return {'name': r.get('name'), 'role': r.get('role'), **(r.get('params') or {})}
        if isinstance(o, str):
            return _PH.sub(lambda m: str(ctx[m.group(1)]), o)
        if isinstance(o, list):
            return [sub(x) for x in o]
        if isinstance(o, dict):
            return {k: sub(v) for k, v in o.items()}
        return o
    files = {sub(k): sub(v) for k, v in stage.get('write_files', {}).items()}
    for s in stage.get('steps', []):                                                    # служебные файлы ВКЛЮЧЁННОГО шага (выключенный не пишет ничего — main байт в байт, T-99/7)
        if s.get('write_files') and _step_on(s, ctx) and (ctx['_record'] or '$card_flat' not in s['write_files'].values()):
            files.update({sub(k): sub(v) for k, v in s['write_files'].items()})
    return files


def _heavy(step: dict, name: str, ctx: dict, rules: dict) -> list:
    h = step.get('heavy')
    if not h:
        return step['argv']
    return [os.path.join(ctx['root'], rules['heavy_slot']), f"paint-{name}-{ctx['sku'][-6:]}", '--prio', str(h.get('prio', 1)),
            '--min-gb', str(h.get('min_gb', 3)), '--cores', str(h.get('cores', 2)), '--'] + step['argv']


def _tolerated(run: str, sku: str, need: str, st: dict) -> bool:
    """Отказ нужного этапа не блокирует этот, если в его extra истинен флаг из `needs_tolerate` (напр. 04 bottom_shape_mismatch: корпус лёг, низ — нет → 06 идёт с --body-only)."""
    flags = st.get('needs_tolerate', {}).get(need, [])
    chk = PS.read_check(os.path.join(run, PS.safe_name(sku), need)) or {}
    return any((chk.get('extra') or {}).get(f) for f in flags)


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
            if s == 'refused' and _tolerated(run, sku, n, st):
                continue
            if s in ('refused', 'missing'):
                blocked.append(f'{n}: {s}')
        if st.get('needs_catalog') and ctx['_record'] is None and not blocked:
            blocked.append('нет записи товара в каталоге (--catalog: JSON с {sid, name, role, params}; params не выдумываем)')
        item = {'stage': name, 'produces': produces, 'steps': [], 'why': ''}
        if blocked:
            item.update(action='blocked', why='; '.join(blocked))
            for p in produces:
                state[p] = 'missing'
        elif st.get('adoptable') and prep_glb_path(a, sku) and not all(h['status'] != 'missing' for h in have):
            src = a.get('prep_run') or ''
            pst = [stage_status(src, sku, p, check_rules) for p in produces] if src else []
            bad = [f"{x['stage']}: {x['status']}" for x in pst if x['status'] in ('refused', 'missing')]
            if not os.path.exists(ctx['prep_glb']):
                bad.append(f"нет файла формы {ctx['prep_glb']}")
            if not src:
                bad.append('не задан --prep-run (прогон, где этапы 01–02 уже сделаны)')
            if bad:
                item.update(action='blocked', why='готовая форма: ' + '; '.join(bad))
                for p in produces:
                    state[p] = 'missing'
            else:
                item.update(action='adopt', why=f"готовая форма {ctx['prep_glb']}; check.json этапов из {src}", adopt={'from': src, 'stages': produces})
                for x in pst:
                    state[x['stage']] = x['status']
        elif st.get('pending'):
            item.update(action='pending', why=st['pending'])
            for p in produces:
                state[p] = 'missing'
        elif not force and all(h['status'] != 'missing' for h in have):
            item.update(action='skip', why='check.json уже есть: ' + ', '.join(f"{h['stage']}={h['status']}" for h in have))
            for h in have:
                state[h['stage']] = h['status']
        else:
            dctx = dynamic_ctx(run, sku, ctx, rules, state, check_rules)
            dctx['cam_az_args'] = cam_az_args(run, sku, check_rules, rules)
            item.update(action='run', steps=resolve_steps(st, dctx), files=resolve_files(st, dctx))
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
        if item['action'] == 'adopt':
            import shutil
            for stg in item['adopt']['stages']:
                shutil.copytree(os.path.join(item['adopt']['from'], PS.safe_name(sku), stg), os.path.join(run, PS.safe_name(sku), stg), symlinks=True, dirs_exist_ok=False)
            entry['adopted_from'] = item['adopt']['from']
        if item['action'] == 'run':
            for path, body in item['files'].items():
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(body, f, ensure_ascii=False, indent=1)
            for i, s in enumerate(item['steps']):
                r = _run_step(s, f'{name}-{i + 1}', ctx, rules, timeout, bool(a.get('heavy')))     # имя заявки heavy-slot у каждого шага своё
                entry['steps'].append(r)
                if r['rc'] != 0:
                    break                                                   # дальнейшие шаги этапа без первого не имеют смысла; статус скажет check.json
                if rules.get('abstain_is_stop') and s.get('abstain_report'):        # проба (T-99/7, правило директора 26.11): воздержание ВКЛЮЧЁННОГО шага — СТОП всего прогона, не «rc 0 → дальше»
                    try:
                        _ab = json.load(open(os.path.join(ctx['sku_dir'], s['abstain_report']), encoding='utf-8')).get('abstain')
                    except (OSError, ValueError):
                        _ab = 'нет отчёта шага (%s)' % s['abstain_report']
                    if _ab:
                        r['abstain'] = str(_ab)[:300]
                        log['stopped'] = {'stage': name, 'step': i + 1, 'abstain': r['abstain'], 'report': s['abstain_report']}
                        break
        if log.get('stopped'):
            entry['status'] = {p: stage_status(run, sku, p, check_rules)['status'] for p in rules['stages'][name]['produces']}
            log['stages'].append(entry)
            break
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
    ap.add_argument('--prep-glb', default='', help='готовая форма этапа 2 (файл); этапы 01–02 не строятся, их check.json копируются из --prep-run')
    ap.add_argument('--prep-dir', default='', help='папка готовых форм `<sku>-n1024.glb` (вместо --prep-glb для пакета)')
    ap.add_argument('--prep-run', default='', help='прогон, где этапы 01–02 уже сделаны (`<prep-run>/<sku>/01-trellis`, `02-prep`)')
    ap.add_argument('--catalog', default='', help='выгрузка каталога: JSON-список (или одна запись) {sid, name, role, params}; нужен этапу 8, тип товара берётся оттуда, если нет --product-role')
    ap.add_argument('--only', default='')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--heavy', action='store_true', help='тяжёлые шаги — через tools/ops/heavy-slot.sh (на pakardev всегда включать)')
    ap.add_argument('--timeout', type=int, default=3600)
    a = ap.parse_args(argv)
    rules, cr = load_rules(), PC.load_rules()
    only = [x for x in a.only.split(',') if x] or None
    d = {'native': a.native, 'photo': a.photo, 'product_role': a.product_role, 'channels': a.channels, 'root': a.root, 'catalog': a.catalog, 'prep_glb': a.prep_glb, 'prep_dir': a.prep_dir, 'prep_run': a.prep_run, 'force': a.force, 'heavy': a.heavy}
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
            for i, s in enumerate(it['steps']):
                print('           ' + ' '.join(_heavy(s, f"{it['stage']}-{i + 1}", make_ctx(a.run, a.sku, d, rules), rules) if a.heavy else s['argv']))
        return 0
    miss = [k for k in ('native', 'photo') if not d[k] and not (k == 'native' and (a.prep_glb or a.prep_dir))]
    if miss:
        print('нужны --native и --photo', file=sys.stderr)
        return 2
    log = execute(a.run, a.sku, d, rules, cr, only, a.timeout)
    for e in log['stages']:
        print(e['stage'], e['action'], e['status'], e['why'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

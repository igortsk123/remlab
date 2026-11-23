#!/usr/bin/env python3
"""Этап 9 «проверка» нового пути покраски (план paint-photo-fill-01 § «Проверка на каждом этапе»; T-20261121-169/4).
ЗАЧЕМ. Путь длинный (8 этапов до проверки), владелец смотрит только готовое. Этот шаг собирает ответы ВСЕХ этапов товара в одно решение «можно показывать владельцу или нет, и почему»,
плюс одна картинка «лента этапов» (контрольный кадр каждого этапа с подписью), чтобы глазом сразу видно, где путь сломался.

Что делает по `<run>/<sku>/`:
  ① читает `check.json` этапов 01…08 (через `paint_stage.read_check`, свой формат не заводит) и для каждого решает: прошёл / мягко / отказ / нет этапа;
  ② на итоговом GLB (первый `*.glb` из `outputs` этапа 08, иначе 07) запускает сторож охвата `salad/trellis/tex_coverage.py` (`process` → `verdict` keep/repaint/reject, пороги — его `THRESHOLDS`);
  ②б на нём же сторож палитры `paint_palette.py` (T-20261121-174/1): доля площади поверхности с малиновой «служебной заливкой» (протекла из StableGen/Qwen в атлас) сверх
     допуска (порог + такой же цвет на фото товара) → отказ; малая доля → пометка; пороги — `rules/paint-check.json` → `palette`;
  ③ итог товара: «готов к показу владельцу» — только если все 8 этапов есть и нет ни одного «отказ», и сторож охвата не reject, и палитра не «отказ»; «мягко» (и repaint) не блокирует — «готов с пометкой»;
  ④ пишет `<run>/<sku>/09-check/`: `check.json` (через `paint_stage.write_check`; `passed` = готов к показу; в `extra` — таблица этапов, охват, итог, пометки),
     `frame.png` (лента этапов), и общий `<run>/run_summary.tsv` (товар × этапы, итог, первая причина, пометки, ключевые числа охвата).
ЕДИНСТВЕННЫЙ ИСТОЧНИК. Пороги мерок — в самих этапах (читаем `ok`/`threshold` из их check.json, не копируем); охвата — `tex_coverage.THRESHOLDS`; здесь (`rules/paint-check.json`) —
только обязательные этапы, какие мерки «мягкие» (флаг `soft: true` в check.json этапа главнее таблицы), где итоговый GLB. ID товаров в коде нет.
Этапы одного товара могут лежать в РАЗНЫХ папках прогона (пока их гнали порознь): `--stage-run 06-visible=<папка прогона>` (повторяемый ключ) подставляет папку для этапа, остальные — из `<run>`.

  paint_check.py run <run> <sku> [--stage-run ЭТАП=ПАПКА …] [--no-coverage]
  paint_check.py batch <run> [--skus a,b] [--stage-run …] [--no-coverage]      все товары папки `<run>` (или --skus); пишет и `run_summary.tsv`
  paint_check.py table <run>                                                   пересобрать `run_summary.tsv` по готовым `09-check/check.json`
Окружение: `PAINT_STAGE_DIR` — папка с paint_stage.py (если не рядом). Тяжёлое (охват на 150k граней) — запускать под `tools/ops/heavy-slot.sh <метка> --prio 1 -- …`.
"""
from __future__ import annotations

import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'paint-check.json')
STAGE = '09-check'
sys.path.insert(0, os.environ.get('PAINT_STAGE_DIR') or HERE)
import paint_decisions as PD  # noqa: E402  (4 состояния pass/fail/uncertain/not_applicable по реестру; без numpy)
import paint_stage as PS  # noqa: E402  (общий писатель/читатель check.json)

SEV = {'ok': 0, 'soft': 1, 'refused': 2, 'missing': 2}


def load_rules(path: str = RULES) -> dict:
    with open(path, encoding='utf-8') as f:
        r = json.load(f)
    for k in ('required_stages', 'soft', 'final_glb', 'coverage', 'words', 'final_words', 'titles'):
        if k not in r:
            raise ValueError(f'paint-check.json: нет раздела {k}')
    return r


# ----------------------------------------------------------------------------------------------- этап ---------
def _is_soft(stage: str, name: str, m: dict, rules: dict) -> bool:
    if m.get('soft') is True:                                            # сам этап назвал мерку мягкой — главнее таблицы
        return True
    s = rules['soft']
    spec = s.get(stage)
    return spec == '*' or name in (spec or []) or name in s.get('everywhere', [])


def classify_stage(stage: str, chk: dict | None, rules: dict, src_run: str | None = None) -> dict:
    """Решение по этапу из его check.json: status ok | soft | refused | missing, причина, непрошедшие мерки (жёсткие/мягкие), все мерки как есть."""
    out = {'stage': stage, 'status': 'missing', 'reason': 'нет check.json (этап не запускался или файл битый)', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'run': src_run}
    if chk is None:
        return out
    ms = {}
    if chk.get('metric'):
        ms[chk['metric'].get('name') or 'metric'] = chk['metric']
    for k, v in (chk.get('metrics') or {}).items():
        if v:
            ms.setdefault(k, v)
    out['metrics'] = {k: {key: m.get(key) for key in ('value', 'threshold', 'op', 'ok') if key in m} for k, m in ms.items()}
    if chk.get('passed'):
        out.update(status='ok', reason='')
        return out
    failed = [k for k, m in ms.items() if m.get('ok') is False]               # ok None = N/A: не провал
    out['soft_failed'] = [k for k in failed if _is_soft(stage, k, ms[k], rules)]
    out['hard_failed'] = [k for k in failed if k not in out['soft_failed']]
    out['reason'] = chk.get('reason') or ('не прошли: ' + ', '.join(failed) if failed else 'этап не прошёл без названной мерки')
    out['status'] = 'soft' if failed and not out['hard_failed'] else 'refused'   # не прошёл, мерку не назвал — жёстко
    return out


def find_final_glb(run: str, sku: str, rules: dict, stage_runs: dict | None = None) -> str | None:
    for st in rules['final_glb']['stages']:
        d = os.path.join((stage_runs or {}).get(st, run), PS.safe_name(sku), st)
        chk = PS.read_check(d)
        for o in (chk or {}).get('outputs') or []:
            p = os.path.join(d, o)
            if o.lower().endswith('.glb') and os.path.exists(p):
                return p
    return None


# ---------------------------------------------------------------------------------------------- охват --------
def run_coverage(glb: str, out_dir: str, rules: dict) -> dict:
    """Сторож охвата на итоговом GLB: `tex_coverage.process` + `verdict`. Возвращает {verdict, why, metrics}."""
    sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
    import tex_coverage as TC  # noqa: E402  (тяжёлые numpy/trimesh — только здесь)
    c = rules['coverage']
    res = TC.process(glb, out_dir, yaw=c['yaw'], grid=c['grid'], view_res=c['view_res'], write_glb=False, ext_n=c['ext_n'])
    flat = TC.flat_metrics(res)
    return {'verdict': res['verdict'], 'why': res['verdict_why'], 'metrics': {k: flat.get(k) for k in c['show_metrics']}, 'seconds': res['time_s']['all']}


def load_guard(rules: dict) -> dict:
    """Общие правила малинового (один файл на виды и атлас): `rules.palette.guard_rules` рядом с rules/paint-check.json. Только json, без numpy."""
    return json.load(open(os.path.join(os.path.dirname(RULES), rules['palette']['guard_rules']), encoding='utf-8'))


def run_palette(glb: str, photo: str | None, guard: dict) -> dict:
    """Сторож палитры (`paint_palette.py`): доля площади поверхности с малиновой заглушкой + такая же доля на фото. Тяжёлые numpy/trimesh — только здесь."""
    import paint_palette as PP  # noqa: E402
    return PP.run_palette(glb, photo, guard)


def find_photo(run: str, sku: str, rules: dict, stage_runs: dict | None = None) -> str | None:
    """Фото товара — из `extra` check.json этапа `palette.photo_stage` (ключи `photo_keys`): своего пути не заводим, берём тот, что этап записал."""
    p = rules['palette']
    d = os.path.join((stage_runs or {}).get(p['photo_stage'], run), PS.safe_name(sku), p['photo_stage'])
    ex = (PS.read_check(d) or {}).get('extra') or {}
    for k in p['photo_keys']:
        if ex.get(k) and os.path.exists(ex[k]):
            return ex[k]
    return None


def classify_palette(glb: str | None, photo: str | None, rules: dict, pal_fn=None) -> dict:
    """Малиновая заглушка вне палитры фото (T-20261121-174/1): доля площади > допуска → отказ; > мягкого порога → пометка. Не измерено (нет GLB/сторож упал) → missing, не «ок»."""
    out = {'stage': 'palette', 'status': 'missing', 'reason': 'нет итогового GLB (этап 08/07 не выдал файл)', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'glb': glb}
    c = rules['palette']
    if not c.get('enabled', True):
        out.update(status='ok', reason='')
        return out
    if not glb:
        return out
    guard = load_guard(rules)
    hard_share, soft_share = float(guard['magenta']['obj_frac_max']), float(guard['magenta_baked']['soft_frac'])
    try:
        r = (pal_fn or run_palette)(glb, photo, guard)
    except Exception as e:                                                       # сторож упал — не «ок»: нет измерения
        out['reason'] = f'сторож палитры упал: {type(e).__name__}: {str(e)[:120]}'
        return out
    if r.get('share') is None:
        out['reason'] = 'сторож палитры: в GLB нет текстуры цвета — нечего мерить'
        return out
    share, ph = float(r['share']), float(r.get('photo_share') or 0.0)
    hard, soft = hard_share + ph, soft_share + ph
    out['metrics'] = {'magenta_surface_pct': {'value': round(share * 100, 3), 'threshold': round(hard * 100, 3), 'op': '<='},
                      'photo_magenta_pct': {'value': round(ph * 100, 3)}}
    out['rgb'] = r.get('rgb')
    def why(limit: float, word: str) -> str:
        return (f"малиновая заглушка {share * 100:.2f} % площади ({word} {limit * 100:.2f} % = порог {(hard_share if word == 'допуск' else soft_share) * 100:.2f} % "
                f"+ на фото {ph * 100:.1f} %): служебная заливка «не покрашено» протекла в текстуру")
    if share > hard:
        out.update(status='refused', reason=why(hard, 'допуск'), hard_failed=['palette'])
    elif share > soft:
        out.update(status='soft', reason=why(soft, 'мягкий порог'), soft_failed=['palette'])
    else:
        out.update(status='ok', reason='')
    return out


def run_surface(glb: str | None, run: str, sku: str, out_dir: str, stage_runs: dict | None = None) -> dict:
    """Мерки паспорта на итоговом GLB (T-20261123-19/1, `paint_surface_checks.py`): верх ↔ фото, затёк между группами, пустая плоскость. known — этап 6, части — этап 8 (если есть)."""
    import paint_surface_checks as PSC  # noqa: E402  (numpy/trimesh — только здесь)
    sr = stage_runs or {}
    pj = os.path.join(run, PS.safe_name(sku), 'work', 'product.json')                                  # класс каталога — только подсказка (флаг role_mismatch, в гейт не идёт)
    role = (json.load(open(pj, encoding='utf-8')).get('role') if os.path.exists(pj) else None)
    return PSC.classify(glb, os.path.join(sr.get('06-visible', run), PS.safe_name(sku), '06-visible', 'known.png'), os.path.join(sr.get('08-material', run), PS.safe_name(sku), '08-material', 'parts08.npz'), out_dir=out_dir, role=role)


def classify_coverage(glb: str | None, rules: dict, out_dir: str, cov_fn=None) -> dict:
    out = {'stage': 'coverage', 'status': 'missing', 'reason': 'нет итогового GLB (этап 08/07 не выдал файл)', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'glb': glb, 'verdict': None}
    c = rules['coverage']
    if not c.get('enabled', True):
        out.update(status='ok', reason='')
        return out
    if not glb:
        return out
    try:
        r = (cov_fn or run_coverage)(glb, out_dir, rules)
    except Exception as e:                                                       # сторож упал — не «ок»: нет измерения
        out['reason'] = f'сторож охвата упал: {type(e).__name__}: {str(e)[:120]}'
        return out
    st = c['outcome'].get(r['verdict'], 'refused')
    out.update(status=st, verdict=r['verdict'], reason='' if st == 'ok' else 'охват: ' + '; '.join(r['why']), metrics={k: {'value': v} for k, v in r['metrics'].items()}, seconds=r.get('seconds'))
    if st == 'soft':
        out['soft_failed'] = ['coverage']
    elif st == 'refused':
        out['hard_failed'] = ['coverage']
    return out


# ----------------------------------------------------------------------------------------------- товар --------
def judge_product(stages: list, cov: dict, rules: dict, pal: dict | None = None, surf: dict | None = None) -> dict:
    """Итог товара: ready | ready_with_notes | not_ready, первая блокирующая причина, список пометок."""
    allst = stages + [cov] + ([pal] if pal else []) + ([surf] if surf else [])
    block = [s for s in allst if s['status'] in ('refused', 'missing')]
    notes = [f"{s['stage']}: {s['reason']}" for s in allst if s['status'] == 'soft']
    if block:
        b = block[0]
        return {'final': 'not_ready', 'reason': f"{b['stage']}: {b['reason']}", 'notes': notes, 'blocking': [s['stage'] for s in block]}
    return {'final': 'ready_with_notes' if notes else 'ready', 'reason': '', 'notes': notes, 'blocking': []}


def check_product(run: str, sku: str, rules: dict, stage_runs: dict | None = None, cov_fn=None, ribbon: bool = True, with_coverage: bool = True, pal_fn=None, surf_fn=None) -> dict:
    t0 = time.time()
    sr = stage_runs or {}
    stages = []
    for st in rules['required_stages']:
        base = sr.get(st, run)
        d = os.path.join(base, PS.safe_name(sku), st)
        stages.append(classify_stage(st, PS.read_check(d), rules, base))
        stages[-1]['dir'] = d
    out_dir = PS.stage_dir(run, sku, STAGE)
    glb = find_final_glb(run, sku, rules, sr)
    if with_coverage:
        cov = classify_coverage(glb, rules, out_dir, cov_fn)
    else:
        cov = {'stage': 'coverage', 'status': 'missing', 'reason': 'сторож охвата не запускался (--no-coverage)', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'glb': glb, 'verdict': None}
    pal = classify_palette(glb, find_photo(run, sku, rules, sr), rules, pal_fn) if with_coverage else \
        {'stage': 'palette', 'status': 'missing', 'reason': 'сторож палитры не запускался (--no-coverage)', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'glb': glb}
    surf = (surf_fn or run_surface)(glb, run, sku, out_dir, sr) if with_coverage and rules.get('surface', {}).get('enabled', True) else \
        {'stage': 'surface', 'status': 'ok', 'reason': '', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'glb': glb}
    verdict = judge_product(stages, cov, rules, pal, surf)
    dec = PD.decide_product(stages, {'coverage': cov, 'palette': pal, 'surface': surf})     # рядом со старым флагом, итог (`passed`) не меняет — решения в тени
    frame = None
    if ribbon:
        frame = build_ribbon(sku, stages, cov, verdict, rules, os.path.join(out_dir, PS.FRAME), pal)
    n_block = len(verdict['blocking'])
    missing = [s['stage'] for s in stages if s['status'] == 'missing']
    hard = [s['stage'] for s in stages if s['status'] == 'refused'] + (['coverage'] if cov['status'] == 'refused' else []) + (['palette'] if pal['status'] == 'refused' else []) + (['surface'] if surf['status'] in ('refused', 'missing') else [])
    doc = PS.write_check(
        out_dir, STAGE, sku, passed=verdict['final'] != 'not_ready',
        metric={'name': 'blocking_stages', 'value': n_block, 'threshold': 0, 'op': '<='},
        metrics={'stages_missing': {'value': len(missing), 'threshold': 0, 'op': '<='}, 'hard_refusals': {'value': len(hard), 'threshold': 0, 'op': '<='},
                 'soft_notes': {'value': len(verdict['notes'])}},
        reason=verdict['reason'], seconds=time.time() - t0, outputs=['check.json'] + ([PS.FRAME] if frame else []), frame=frame,
        final=verdict['final'], final_ru=rules['final_words'][verdict['final']], notes=verdict['notes'], blocking=verdict['blocking'],
        stages=[{k: s[k] for k in ('stage', 'status', 'reason', 'hard_failed', 'soft_failed', 'metrics', 'run')} for s in stages],
        coverage={k: cov.get(k) for k in ('status', 'verdict', 'reason', 'metrics', 'glb', 'seconds')},
        palette={k: pal.get(k) for k in ('status', 'reason', 'metrics', 'rgb')},
        surface={k: surf.get(k) for k in ('status', 'reason', 'metrics')}, decisions=dec)
    return doc


# ------------------------------------------------------------------------------------------------ лента -------
def _font(size: int):
    from PIL import ImageFont
    for p in ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'DejaVuSans.ttf', '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf'):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


COL = {'ok': (46, 160, 90), 'soft': (222, 160, 20), 'refused': (205, 55, 55), 'missing': (140, 140, 140)}


def _cut(text: str, n: int) -> str:
    text = ' '.join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + '…'


def build_ribbon(sku: str, stages: list, cov: dict, verdict: dict, rules: dict, path: str, pal: dict | None = None) -> str:
    """Сводный кадр: контрольный кадр каждого этапа (`frame` из check.json) с подписью «этап · слово», причина под ней; цвет рамки = статус. Сетка `columns` в ряд, последняя ячейка — охват."""
    from PIL import Image, ImageDraw
    rb = rules['ribbon']
    W, H, HEAD = rb['cell_w'], rb['img_h'], rb['head_h']
    cols = rb['columns']
    cells = stages + [cov] + ([pal] if pal else [])
    rows = -(-len(cells) // cols)
    top = 56
    img = Image.new('RGB', (cols * W, top + rows * (HEAD + H)), (245, 245, 245))
    dr = ImageDraw.Draw(img)
    f1, f2, f3 = _font(20), _font(15), _font(24)
    fin = verdict['final']
    dr.rectangle([0, 0, cols * W, top], fill=COL['ok'] if fin == 'ready' else COL['soft'] if fin == 'ready_with_notes' else COL['refused'])
    dr.text((12, 13), _cut(f"{sku} — {rules['final_words'][fin]}" + (f": {verdict['reason']}" if verdict['reason'] else ''), 120), fill='white', font=f3)
    for i, s in enumerate(cells):
        x, y = (i % cols) * W, top + (i // cols) * (HEAD + H)
        c = COL[s['status']]
        dr.rectangle([x, y, x + W - 1, y + HEAD + H - 1], outline=c, width=4)
        dr.rectangle([x, y, x + W - 1, y + HEAD - 1], fill=(255, 255, 255))
        dr.text((x + 10, y + 6), f"{rules['titles'].get(s['stage'], s['stage'])} — {rules['words'][s['status']]}", fill=c, font=f1)
        dr.text((x + 10, y + 34), _cut(s['reason'] or _metric_line(s), 78), fill=(60, 60, 60), font=f2)
        fp = None
        if s['stage'] not in ('coverage', 'palette') and s.get('dir'):
            fn = (PS.read_check(s['dir']) or {}).get('frame') or PS.FRAME
            fp = os.path.join(s['dir'], fn)
        if fp and os.path.exists(fp):
            try:
                im = Image.open(fp).convert('RGB')
                k = min((W - 8) / im.width, (H - 8) / im.height)
                im = im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
                img.paste(im, (x + (W - im.width) // 2, y + HEAD + (H - im.height) // 2))
                continue
            except OSError:
                pass
        txt = _cov_text(s) if s['stage'] == 'coverage' else _pal_text(s) if s['stage'] == 'palette' else ['кадра нет']
        for j, line in enumerate(txt):
            dr.text((x + 14, y + HEAD + 14 + j * 24), _cut(line, 60), fill=(90, 90, 90), font=f2)
    img.save(path)
    return PS.FRAME


def _metric_line(s: dict) -> str:
    ms = s.get('metrics') or {}
    first = next(iter(ms.items()), None)
    return f"{first[0]} {first[1].get('value')}" if first else ''


def _pal_text(s: dict) -> list:
    if s['status'] == 'missing':
        return [s['reason']]
    m = s.get('metrics') or {}
    return [f"малиновая заглушка: {(m.get('magenta_surface_pct') or {}).get('value')} % площади", f"допуск: {(m.get('magenta_surface_pct') or {}).get('threshold')} %",
            f"на фото такого цвета: {(m.get('photo_magenta_pct') or {}).get('value')} %"]


def _cov_text(s: dict) -> list:
    if s['status'] == 'missing':
        return [s['reason']]
    return [f"решение сторожа: {s.get('verdict')}"] + [f"{k.replace('_pct', '').replace('_', ' ')}: {v.get('value')} %" for k, v in (s.get('metrics') or {}).items()]


# ------------------------------------------------------------------------------------------- таблица прогона --
def table_rows(run: str, rules: dict) -> list:
    rows = []
    for sku in sorted(d for d in os.listdir(run) if os.path.isdir(os.path.join(run, d, STAGE))):
        c = PS.read_check(os.path.join(run, sku, STAGE))
        if not c:
            continue
        ex = c.get('extra') or {}
        st = {s['stage']: s['status'] for s in ex.get('stages') or []}
        cov = ex.get('coverage') or {}
        rows.append({'sku': sku, 'final': ex.get('final_ru', ''), **{s: rules['words'].get(st.get(s, 'missing'), '') for s in rules['required_stages']},
                     'coverage': rules['words'].get(cov.get('status', 'missing'), '') + (f" ({cov.get('verdict')})" if cov.get('verdict') else ''),
                     'palette': rules['words'].get((ex.get('palette') or {}).get('status', 'missing'), '') if ex.get('palette') else '',
                     'magenta_surface_pct': (((ex.get('palette') or {}).get('metrics') or {}).get('magenta_surface_pct') or {}).get('value'),
                     'first_reason': (c.get('reason') or '')[:160], 'soft_notes': ' | '.join(ex.get('notes') or [])[:240],
                     **{k: ((cov.get('metrics') or {}).get(k) or {}).get('value') for k in rules['coverage']['show_metrics']}})
    return rows


def write_run_summary(run: str, rules: dict) -> str:
    rows = table_rows(run, rules)
    cols = ['sku', 'final'] + rules['required_stages'] + ['coverage', 'palette', 'magenta_surface_pct', 'first_reason', 'soft_notes'] + rules['coverage']['show_metrics']
    path = os.path.join(run, 'run_summary.tsv')
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write('\t'.join(cols) + '\n')
        for r in rows:
            f.write('\t'.join('' if r.get(c) is None else str(r[c]).replace('\t', ' ').replace('\n', ' ') for c in cols) + '\n')
    os.replace(tmp, path)
    return path


def check_batch(run: str, rules: dict, skus: list | None = None, stage_runs: dict | None = None, cov_fn=None, with_coverage: bool = True, pal_fn=None) -> list:
    skus = skus or sorted(d for d in os.listdir(run) if os.path.isdir(os.path.join(run, d)) and d != STAGE)
    docs = []
    for i, sku in enumerate(skus, 1):
        try:
            d = check_product(run, sku, rules, stage_runs, cov_fn, True, with_coverage, pal_fn)
        except Exception as e:                                                  # один товар не валит прогон
            d = PS.write_check(PS.stage_dir(run, sku, STAGE), STAGE, sku, passed=False, reason=f'этап проверки упал: {type(e).__name__}: {str(e)[:120]}')
        print(f"[{i}/{len(skus)}] {sku} {d['extra'].get('final_ru', '?')} {d['reason'][:110]}", flush=True)
        docs.append(d)
    write_run_summary(run, rules)
    return docs


def _parse_stage_runs(vals: list) -> dict:
    out = {}
    for v in vals or []:
        k, _, p = v.partition('=')
        if not p:
            raise SystemExit(f'--stage-run {v!r}: нужно ЭТАП=ПАПКА')
        out[k] = os.path.expanduser(p)
    return out


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Этап 9 «проверка» пути покраски: сводит check.json этапов 01–08 + сторож охвата → готов ли товар к показу')
    sub = ap.add_subparsers(dest='cmd', required=True)
    for n in ('run', 'batch', 'table'):
        p = sub.add_parser(n)
        p.add_argument('run')
        if n == 'run':
            p.add_argument('sku')
        if n == 'batch':
            p.add_argument('--skus', default='')
        if n != 'table':
            p.add_argument('--stage-run', action='append', default=[])
            p.add_argument('--no-coverage', action='store_true')
    a = ap.parse_args(argv)
    rules = load_rules()
    if a.cmd == 'table':
        print(write_run_summary(a.run, rules))
        return 0
    sr = _parse_stage_runs(a.stage_run)
    if a.cmd == 'run':
        d = check_product(a.run, a.sku, rules, sr, with_coverage=not a.no_coverage)
        write_run_summary(a.run, rules)
        print(json.dumps({k: d['extra'][k] for k in ('final_ru', 'notes', 'blocking')} | {'reason': d['reason']}, ensure_ascii=False, indent=1))
        return 0
    docs = check_batch(a.run, rules, [s for s in a.skus.split(',') if s] or None, sr, with_coverage=not a.no_coverage)
    from collections import Counter
    print(dict(Counter(d['extra'].get('final_ru', 'упал') for d in docs)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))

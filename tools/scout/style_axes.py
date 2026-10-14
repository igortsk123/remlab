#!/usr/bin/env python3
"""Стиль по осям признаков (план conv-01, ADR-0269): ответы VLM 1–10 по осям → вектор 0–10 по шести стилям.

ЗАЧЕМ. Владелец 13.10: наводящие вопросы («много ли металла», «какой цвет преобладает») работали лучше прямого
«какой это стиль»; эталонной разметки человеком не будет (ADR-0251). Оси, вопросы и диапазоны стилей —
`rules/style-axes.json` (исследование по открытым источникам), формула и числа — `rules/style-formula.json`
(разбор Codex 13.10). Здесь только ЧИСТЫЙ расчёт: без сети и базы, проверяется `--selftest`.

ФОРМУЛА. Совместимость оси со стилем f = 1 внутри диапазона, линейно до 0 за 3 балла за краем. По стилю:
  M — средняя совместимость (вес strong 1.0 / supporting 0.4),
  D — диагностичность: f·(1 − средняя f остальных стилей) — признак подходит ЭТОМУ и не подходит прочим.
Сначала среднее внутри пяти блоков осей (форма, декор, материалы, отделка, цвет), потом между блоками — чтобы
связанные оси не голосовали много раз. R = 10·(0.5·M + 0.5·D). Нейтральная ваза совместима со всеми (M≈1), но не
диагностична (D≈0) → около 5, а не 10. Надёжность ρ = q·min(1, n_eff/5) (q — доля ожидаемого веса, которую
модель увидела) тянет балл к 5, если ответов мало; q<0.5 или n_eff<4 — «мало данных», порог 6 не проходит.
Пары, которые легко спутать (сканди/джапанди…), — небольшая поправка ±0.75 по разделяющим осям. Вето пока нет.

  python3 style_axes.py --selftest
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
AXES_PATH = os.path.join(HERE, 'rules', 'style-axes.json')
FORMULA_PATH = os.path.join(HERE, 'rules', 'style-formula.json')
NA = 'na'   # ось к предмету неприменима (убрать из знаменателя); None — «не видно» (пропуск в покрытии)


def load(axes_path: str = AXES_PATH, formula_path: str = FORMULA_PATH) -> tuple[dict, dict]:
    return json.load(open(axes_path, encoding='utf-8')), json.load(open(formula_path, encoding='utf-8'))


def applies(axis: dict, role: str) -> bool:
    a = axis.get('applies_to', 'all')
    return a == 'all' or role in (a or [])


def fit(x: float, rng: list, falloff: float) -> float:
    lo, hi = rng
    d = lo - x if x < lo else (x - hi if x > hi else 0.0)
    return max(0.0, 1.0 - d / falloff)


def score(answers: dict, role: str, axes_doc: dict, formula: dict) -> dict:
    """answers: {axis_id: число 1–10 | None (не видно) | 'na' (неприменимо)} → баллы и служебные величины."""
    styles = axes_doc['styles']
    axes = {a['id']: a for a in axes_doc['axes'] if applies(a, role)}
    fo, W = float(formula['fit_falloff']), formula['weights']
    block_of = {ax: b for b, xs in formula['blocks'].items() for ax in xs}

    def f(ax: str, st: str) -> float | None:
        ps = (axes[ax].get('per_style') or {}).get(st)
        x = answers.get(ax)
        if not ps or x is None or x == NA:
            return None
        return fit(float(x), ps['range'], fo)

    out = {'scores': {}, 'M': {}, 'D': {}, 'q': {}, 'n_eff': {}, 'insufficient': {}}
    for st in styles:
        blocks: dict = {}
        expected = observed = 0.0
        ws: list = []
        for ax, a in axes.items():
            ps = (a.get('per_style') or {}).get(st)
            if not ps or answers.get(ax) == NA:
                continue
            w = float(W.get(ps.get('marker', 'supporting'), 0.4))
            expected += w
            fs = f(ax, st)
            if fs is None:
                continue
            observed += w
            ws.append(w)
            others = [v for t in styles if t != st for v in [f(ax, t)] if v is not None]
            diag = fs * (1 - sum(others) / len(others)) if others else 0.0
            b = blocks.setdefault(block_of.get(ax, ax), [0.0, 0.0, 0.0])
            b[0] += w * fs
            b[1] += w * diag
            b[2] += w
        bm = [b[0] / b[2] for b in blocks.values() if b[2]]
        bd = [b[1] / b[2] for b in blocks.values() if b[2]]
        M = sum(bm) / len(bm) if bm else 0.0
        D = sum(bd) / len(bd) if bd else 0.0
        R = 10 * (formula['mix']['compat'] * M + formula['mix']['diagnostic'] * D)
        q = observed / expected if expected else 0.0
        n_eff = (sum(ws) ** 2 / sum(w * w for w in ws)) if ws else 0.0
        rel = formula['reliability']
        rho = q * min(1.0, n_eff / rel['n_eff_full'])
        out['scores'][st] = 5 + rho * (R - 5)
        out['M'][st], out['D'][st], out['q'][st], out['n_eff'][st] = round(M, 3), round(D, 3), round(q, 3), round(n_eff, 2)
        out['insufficient'][st] = q < rel['min_q'] or n_eff < rel['min_n_eff']

    # пары, которые легко спутать: симметричная поправка по разделяющим осям
    pt = formula['pair_tiebreak']
    shift = {st: 0.0 for st in styles}
    for p in axes_doc.get('confusable_pairs', []):
        s, t = p['pair']
        diffs = [fs - ft for ax in p.get('separating_axes', []) if ax in axes
                 for fs, ft in [(f(ax, s), f(ax, t))] if fs is not None and ft is not None]
        if len(diffs) < pt['min_separators']:
            continue
        c = sum(diffs) / len(diffs)
        shift[s] += pt['k'] * c
        shift[t] -= pt['k'] * c
    for st in styles:
        adj = max(-pt['cap'], min(pt['cap'], shift[st]))
        out['scores'][st] = round(max(0.0, min(10.0, out['scores'][st] + adj)), 2)

    u = formula['universal']
    out['universal'] = (min(out['q'].values() or [0]) >= u['min_q']
                        and min(out['n_eff'].values() or [0]) >= u['min_n_eff']
                        and sum(1 for st in styles if out['M'][st] >= u['min_compat']) >= u['min_styles']
                        and max(out['D'].values() or [1]) <= u['max_diag'])
    thr = formula['in_style_min']
    out['in_style'] = [st for st in styles if out['scores'][st] >= thr and not out['insufficient'][st]]
    return out


def score_v2(answers: dict, role: str, axes_doc: dict, formula: dict) -> dict:
    """Версия 2 (Codex 14.10, после стенда): подписанный вклад вместо «совместимости»; отсутствие признака почти не
    голосует; признак учитывается там, где его можно увидеть; гладкий товар — universal, а не минимализм."""
    v2 = formula['v2']
    styles = axes_doc['styles']
    axes = {a['id']: a for a in axes_doc['axes'] if applies(a, role)}
    fo, W = float(formula['fit_falloff']), formula['weights']
    block_of = {ax: b for b, xs in formula['blocks'].items() for ax in xs}
    group = next((g for g, rs in v2['role_groups'].items() if role in rs), None)
    x = {k: (None if v in (NA, 'na') else v) for k, v in answers.items()}
    for ax, (dep, thr) in v2['gate'].items():          # тон дерева — только если дерево видно; золото — если виден металл
        if (x.get(dep) or 0) < thr:
            x[ax] = None
    out = {'scores': {}, 'universal': False, 'top': []}
    for st in styles:
        blocks: dict = {}
        for ax, a in axes.items():
            ps = (a.get('per_style') or {}).get(st)
            v = x.get(ax)
            if not ps or v is None:
                continue
            opp = (v2['opportunity'].get(ax) or {}).get(group, 1.0)
            w = float(W.get(ps.get('marker', 'supporting'), 0.4)) * opp
            if ax == 'wood_visibility' and group == 'мягкая' and st in v2['soft_wood_styles']:
                if v < v2['soft_wood_neutral_below']:
                    continue                            # у дивана дерево — ножки: мало дерева не против сканди
                w = float(W['supporting'])
            if w <= 0:
                continue
            f = fit(float(v), ps['range'], fo)
            alpha = v2['alpha_low_range'] if ps['range'][0] <= v2['low_range_max_lo'] else 1.0
            po = v2['presence_only'].get(ax)
            if po is not None and st not in po:
                alpha = 0.0                             # «нет золота» — не довод ни за один стиль, кроме против неоклассики
            e = alpha * f - v2['penalty'] * (1 - f)
            b = blocks.setdefault(block_of.get(ax, ax), [0.0, 0.0])
            b[0] += w * e
            b[1] += w
        es = [b[0] / b[1] for b in blocks.values() if b[1]]
        E = sum(es) / len(es) if es else 0.0
        out['scores'][st] = round(max(0.0, min(10.0, 5 + v2['scale'] * E)), 2)
    ranked = sorted(out['scores'].items(), key=lambda kv: -kv[1])
    out['universal'] = ranked[0][1] < v2['universal_below']
    out['top'] = [ranked[0][0]] + ([ranked[1][0]] if ranked[0][1] - ranked[1][1] < v2['second_style_gap'] else [])
    return out


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool, extra: object = '') -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name + (f'  {extra}' if not cond else ''))
        bad += 0 if cond else 1

    axes, formula = load()
    ok('16 осей, у каждой вопрос и якоря 1/10', len(axes['axes']) >= 12 and all(
        a.get('question_ru') and a.get('scale_1_ru') and a.get('scale_10_ru') for a in axes['axes']))
    ok('у каждой оси есть источник', all(a.get('sources') for a in axes['axes']))
    ok('блоки формулы — только из известных осей', all(
        x in {a['id'] for a in axes['axes']} for xs in formula['blocks'].values() for x in xs))
    ok('fit: внутри 1, на 3 за краем 0', fit(5, [4, 6], 3) == 1 and fit(9, [4, 6], 3) == 0 and abs(fit(7, [4, 6], 3) - 2 / 3) < 1e-9)

    # лофт-стеллаж: чёрный металл, тёмное грубое дерево, видно лампы нет (не светильник)
    loft = {'wood_visibility': 6, 'wood_tone_lightness': 2, 'metal_visibility': 9, 'metal_gold': 1, 'surface_gloss': 2,
            'raw_imperfection': 8, 'ornament_level': 1, 'visual_lightness': 6, 'low_profile': 3, 'colour_warmth': 5,
            'colour_saturation': 1, 'colour_lightness': 2, 'material_mix': 6, 'hardware_prominence': 5}
    r = score(loft, 'стеллаж', axes, formula)
    top = max(r['scores'], key=r['scores'].get)
    ok('лофт-стеллаж: лучший стиль — лофт, балл ≥ 6', top == 'лофт' and r['scores']['лофт'] >= 6, r['scores'])
    ok('лофт-стеллаж: сканди ниже 6', r['scores']['сканди'] < 6, r['scores'])

    # нейтральная ваза: средние значения, ничего выразительного
    vase = {'wood_visibility': 1, 'metal_visibility': 1, 'metal_gold': None, 'surface_gloss': 4, 'raw_imperfection': 2,
            'ornament_level': 2, 'colour_warmth': 5, 'colour_saturation': 2, 'colour_lightness': 7, 'material_mix': 1,
            'wood_tone_lightness': None}
    r = score(vase, 'ваза', axes, formula)
    ok('нейтральная ваза не получает 10 во всех стилях (D гасит)', max(r['scores'].values()) < 8, r['scores'])

    # мало ответов → «мало данных», порог не проходит
    r = score({'metal_visibility': 9, 'colour_lightness': 2}, 'стеллаж', axes, formula)
    ok('два ответа из 14 — мало данных, в стиль не попадает', all(r['insufficient'].values()) and not r['in_style'], r['in_style'])

    # неоклассика: латунь, декор, блеск
    neo = {'wood_visibility': 4, 'wood_tone_lightness': 4, 'metal_visibility': 4, 'metal_gold': 9, 'surface_gloss': 7,
           'raw_imperfection': 1, 'ornament_level': 7, 'visual_lightness': 5, 'low_profile': 3, 'colour_warmth': 7,
           'colour_saturation': 4, 'colour_lightness': 7, 'material_mix': 5, 'hardware_prominence': 8}
    r = score(neo, 'комод', axes, formula)
    ok('комод с латунью и декором — неоклассика лучшая', max(r['scores'], key=r['scores'].get) == 'неоклассика', r['scores'])

    # v2: гладкий серый диван без признаков — универсальный, а не «минимализм»
    plain = {'wood_visibility': 1, 'metal_visibility': 1, 'surface_gloss': 2, 'raw_imperfection': 1, 'ornament_level': 2,
             'visual_lightness': 3, 'low_profile': 6, 'colour_warmth': 5, 'colour_saturation': 2, 'colour_lightness': 5,
             'material_mix': 2, 'textile_texture': 3}
    r2 = score_v2(plain, 'диван', axes, formula)
    ok('v2: гладкий диван без признаков — ни один стиль не выше 6.5 (нет выраженного сигнала)', max(r2['scores'].values()) < 6.5, r2['scores'])
    r2 = score_v2(loft, 'стеллаж', axes, formula)
    ok('v2: лофт-стеллаж — лофт первым', r2['top'][0] == 'лофт', r2['scores'])
    sk = {'wood_visibility': 2, 'metal_visibility': 1, 'surface_gloss': 2, 'raw_imperfection': 2, 'ornament_level': 1,
          'visual_lightness': 8, 'low_profile': 4, 'colour_warmth': 6, 'colour_saturation': 2, 'colour_lightness': 9,
          'material_mix': 2, 'textile_texture': 8}
    r2 = score_v2(sk, 'кресло', axes, formula)
    ok('v2: светлое фактурное кресло на тонких ножках — сканди не проваливается из-за «мало дерева»', r2['scores']['сканди'] >= 6, r2['scores'])
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else (print(__doc__) or 0))

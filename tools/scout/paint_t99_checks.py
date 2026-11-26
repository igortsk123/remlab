#!/usr/bin/env python3
"""T-99/11: автопроверки Fable 14 §4 (№1, 2, 3, 7) — по ГРАНЯМ и по текселям, ВИДИМЫМ СНАРУЖИ (не одним числом на текстуру: внутренние слои тумбы и плиты размывают среднее).
Пороги — rules/t99-checks.json (стартовые, гипотеза пилота); ID товаров в коде нет.
  paint_t99_checks.py keep  <до.glb> <после.glb> [--mark метка.png] [--known known.png] [--json out.json]   №1 + №2 по двум GLB (до/после шага 07)
  paint_t99_checks.py light <L_наш/фото> <C_наш/фото> <разница_оттенка°>                                    №3 (числа даёт lum_cmp.py по кадру mk_top.py)
Класс тексела = (часть: плита|тумба) × (сторона по нормали) × (видна на фото | нет); рисунок = std светлоты L минус размытие внутри класса (текстурные единицы L 0..100).
№7 — `judge_tone(числа)`: числа берутся из отчётов шагов (part_material.json, 07 report), здесь только пороги и вердикт."""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
AX = [('верх', (0, 1, 0)), ('низ', (0, -1, 0)), ('бок+x', (1, 0, 0)), ('бок-x', (-1, 0, 0)), ('бок+z', (0, 0, 1)), ('бок-z', (0, 0, -1))]


def load_rules() -> dict:
    with open(os.path.join(HERE, 'rules', 't99-checks.json'), encoding='utf-8') as f:
        return json.load(f)


def face_classes(g: dict, T: int):
    """→ (id грани на тексель T×T, сторона на грань, «видна снаружи» на грань, «плита» на грань). Снаружи = самая передняя хотя бы на одном из 6 осевых ортографических видов."""
    import tex_coverage as TC
    V, F, UV = g['V'], g['F'], g['UV']
    P = V[F]
    nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1)[:, None], 1e-12)
    axes = np.stack([np.array(a, float) for _, a in AX], 1)
    side = np.argmax(nrm @ axes, 1)
    cen = P.mean(1)
    res = 1024
    lo, hi = V.min(0), V.max(0)
    ext = float((hi - lo).max()) * 1.02
    c0 = (lo + hi) / 2
    vis = np.zeros(len(F), bool)
    for _, a in AX:
        a = np.array(a, float)
        r = np.cross(a, [0, 1, 0] if abs(a[1]) < 0.9 else [1, 0, 0])
        r /= np.linalg.norm(r)
        u = np.cross(r, a)
        q = V - c0
        xy = np.stack([(0.5 + q @ r / ext) * res, (0.5 - q @ u / ext) * res], 1)
        ids, _ = TC.raster(xy, F, res, q @ a)
        vis[np.unique(ids[ids >= 0])] = True
    vis &= (nrm @ axes).max(1) > 0.5                                    # косые (скругления) — отдельно
    y = cen[:, 1]
    bins = np.linspace(y.min(), y.max() + 1e-9, 41)
    bi = np.digitize(y, bins) - 1
    wd = np.array([max(np.ptp(cen[bi == k][:, 0]) if (bi == k).any() else 0, np.ptp(cen[bi == k][:, 2]) if (bi == k).any() else 0) for k in range(40)])
    plate = (wd > 0.8 * wd.max())[np.clip(bi, 0, 39)]
    xy_t = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
    ids_t, _ = TC.raster(xy_t, F, T)
    return ids_t.reshape(T, T), side, vis, plate


def pattern(L, m, R: dict):
    import cv2
    mf = m.astype(np.float32)
    s = cv2.GaussianBlur(L * mf, (0, 0), float(R['pattern_blur_px']))
    w = cv2.GaussianBlur(mf, (0, 0), float(R['pattern_blur_px']))
    k = int(R['pattern_erode_px'])
    me = cv2.erode(m.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
    if int(me.sum()) < int(R['pattern_min_eroded']):
        return None
    return float((L - s / np.maximum(w, 1e-4))[me].std())


def lum(tex) -> np.ndarray:
    import cv2
    return cv2.cvtColor(np.asarray(tex)[..., :3].astype(np.uint8), cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32) * 100 / 255


def table(g: dict, known, R: dict, cache: dict | None = None) -> dict:
    """{(часть, сторона, 'фото'|'нет фото'|'—'): {'n','L','pattern'}} по внешним граням."""
    T = np.asarray(g['tex']).shape[0]
    ids, side, vis, plate = cache['cls'] if cache and 'cls' in cache else face_classes(g, T)
    if cache is not None:
        cache['cls'] = (ids, side, vis, plate)
    L = lum(g['tex'])
    safe = np.clip(ids, 0, None)
    ok = (ids >= 0) & vis[safe]
    rows = {}
    for pn, pm in (('плита', True), ('тумба', False)):
        for si, (sn, _) in enumerate(AX):
            for kk in ((True, False) if known is not None else (None,)):
                m = ok & (plate[safe] == pm) & (side[safe] == si)
                if kk is not None:
                    m &= (known == kk)
                if int(m.sum()) < int(R['pattern_min_texels']):
                    continue
                rows[(pn, sn, 'фото' if kk else ('нет фото' if kk is not None else '—'))] = {'n': int(m.sum()), 'L': round(float(L[m].mean()), 2), 'pattern': pattern(L, m, R)}
    return rows


def check_keep(before: dict, after: dict, changed_marked: int, R: dict) -> dict:
    """№1: рисунок по каждой грани после / до ≥ ratio_min (грани, где до рисунок ≥ pattern_min); изменённых текселей с меткой зерна ≤ changed_marked_max."""
    c = R['keep']
    rows, bad = {}, []
    for k, b in before.items():
        a = after.get(k)
        if a is None or b['pattern'] is None or b['pattern'] < float(c['pattern_min']) or a['pattern'] is None:
            continue
        r = a['pattern'] / b['pattern']
        rows['/'.join(k)] = round(r, 3)
        if r < float(c['ratio_min']):
            bad.append('/'.join(k))
    ok = not bad and int(changed_marked) <= int(c['changed_marked_max'])
    return {'ok': ok, 'ratio': rows, 'faces_below': bad, 'changed_marked': int(changed_marked), 'threshold': {'ratio_min': c['ratio_min'], 'changed_marked_max': c['changed_marked_max']}}


def check_no_flat(rows: dict, R: dict) -> dict:
    """№2: у деревянной группы нет грани без рисунка: рисунок грани ≥ share_of_median_min × медиана рисунка по граням (внешние стороны из rules)."""
    c = R['no_flat']
    pats = {k: v['pattern'] for k, v in rows.items() if k[1] in c['sides'] and v['pattern'] is not None}
    if not pats:
        return {'ok': None, 'why': 'нет граней с рисунком для медианы'}
    med = float(np.median(list(pats.values())))
    flat = ['/'.join(k) for k, v in pats.items() if v < float(c['share_of_median_min']) * med]
    return {'ok': not flat, 'median': round(med, 3), 'flat_faces': flat, 'threshold': {'share_of_median_min': c['share_of_median_min']}}


def check_light(L_ratio: float, C_ratio: float, hue_diff_deg: float, R: dict) -> dict:
    """№3: верх сверху под светом сайта против фото: L в [0,92; 1,08], C в [0,9; 1,15], оттенок ≤ 3°."""
    c = R['light']
    ok = {'L': c['L_ratio'][0] <= L_ratio <= c['L_ratio'][1], 'C': c['C_ratio'][0] <= C_ratio <= c['C_ratio'][1], 'hue': abs(hue_diff_deg) <= float(c['hue_deg_max'])}
    return {'ok': all(ok.values()), 'parts': ok, 'L_ratio': round(L_ratio, 3), 'C_ratio': round(C_ratio, 3), 'hue_diff_deg': round(hue_diff_deg, 2), 'threshold': c}


def judge_tone(m: dict, R: dict) -> dict:
    """№7 (ответ 12 §4). m: {hue_diff_deg, chroma_over_L_rel, channel_gain_spread, group_median_shift, top_deviating_texels_pct} — какие числа есть, те и судятся (нет → не судится, не «ок»)."""
    c = R['tone']
    rules = {'hue_diff_deg': lambda v: abs(v) <= c['hue_deg_max'], 'chroma_over_L_rel': lambda v: abs(v) <= c['chroma_over_L_rel'], 'channel_gain_spread': lambda v: v <= c['channel_gain_spread_max'],
             'group_median_shift': lambda v: v <= c['group_median_shift_max'], 'top_deviating_texels_pct': lambda v: v <= c['top_deviating_texels_pct_max']}
    res = {k: bool(f(m[k])) for k, f in rules.items() if m.get(k) is not None}
    return {'ok': (all(res.values()) if res else None), 'parts': res, 'not_measured': [k for k in rules if m.get(k) is None]}


def changed_marked_count(before_tex, after_tex, mark, eps: float) -> int:
    d = np.abs(np.asarray(after_tex)[..., :3].astype(np.int16) - np.asarray(before_tex)[..., :3].astype(np.int16)).max(-1) > float(eps)
    return int((d & np.asarray(mark, bool)).sum())


def _png_mask(path: str, T: int):
    import cv2
    from PIL import Image
    m = np.asarray(Image.open(path).convert('L')) > 127
    return m if m.shape == (T, T) else cv2.resize(m.astype(np.uint8), (T, T), interpolation=cv2.INTER_NEAREST).astype(bool)


def main(argv=None) -> int:
    a = sys.argv[1:] if argv is None else argv
    R = load_rules()
    if a and a[0] == 'light':
        r = check_light(float(a[1]), float(a[2]), float(a[3]), R)
        print(json.dumps(r, ensure_ascii=False))
        return 0 if r['ok'] else 1
    if a and a[0] == 'keep':
        import tex_coverage as TC
        gb, ga = TC.load_geoms(a[1])[0], TC.load_geoms(a[2])[0]
        T = np.asarray(gb['tex']).shape[0]
        mark = _png_mask(a[a.index('--mark') + 1], T) if '--mark' in a else None
        known = _png_mask(a[a.index('--known') + 1], T) if '--known' in a else None
        cache: dict = {}
        tb, ta = table(gb, known, R, cache), table(ga, known, R, cache)
        cm = changed_marked_count(gb['tex'], ga['tex'], mark, R['keep']['changed_eps']) if mark is not None else 0
        out = {'before': {'/'.join(k): v for k, v in tb.items()}, 'after': {'/'.join(k): v for k, v in ta.items()}, 'check1_keep': check_keep(tb, ta, cm, R), 'check2_no_flat_after': check_no_flat(ta, R)}
        if '--json' in a:
            with open(a[a.index('--json') + 1], 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False, indent=1)
        print(json.dumps({k: out[k] for k in ('check1_keep', 'check2_no_flat_after')}, ensure_ascii=False, indent=1))
        return 0 if out['check1_keep']['ok'] and out['check2_no_flat_after']['ok'] is not False else 1
    print(__doc__)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())

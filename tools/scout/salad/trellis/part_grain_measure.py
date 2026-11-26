#!/usr/bin/env python3
"""Мера «есть направленный рисунок» у группы части и класс «узор, не волокно» (T-20261125-93/3; замеры — ~/remlab-logs/t93/f2, план paint-trial-item-01). ВЫКЛЮЧЕНО (`rules/part-grain.json` → pattern_measure.enabled=false).

ЗАЧЕМ. Волокно дерева из библиотеки (part_grain) кладётся на группу по карточке и тону; на не-дереве (велюр «под дерево по тону», ПВХ-плёнка с тиснением, рейки) оно ложное. Мера смотрит на ФОТО группы:
  1. окна 32 px по надёжным текселям (known ∧ conf ≥ conf_min, эрозия, вдали от перепадов светлоты), в каждом когерентность и угол тензора структуры в полосе DoG σ1–6;
  2. доля окон «coh ≥ coh_min ∧ угол ±angle_tol от медианного угла группы» + площадь A наибольшей связной надёжной области:
     окон ≥ windows_min, A ≥ area_min; доверительный интервал Уилсона (ci_z) доли k/n: нижняя граница > p_split → «есть»; верхняя < p_split → «нет»; иначе или мало окон/площади → «не видно» (T-93/5);
  3. класс «узор, не волокно» (рейки, тиснение, ромбы) по двум общим признакам — любой из них (`ac_pattern_min`, `dev_pattern_min_deg`):
     (а) регулярность шага: пик нормированной автокорреляции мелкой полосы L (как `surface_passport.ac_peak`) ≥ ac_pattern_min — печать/рисунок, не зерно;
     (б) направление относительно панели: медианное отклонение направления полос окон от ближайшей оси панели (3D, через якобиан развёртки грани; оси — `part_grain.plane_axes`) ≥ dev_pattern_min_deg
         при ≥ dev_windows_min окон с известной осью (волокно идёт вдоль оси панели; устойчиво диагональное — узор). Круглая/мелкая плоскость — ось неизвестна (признак «не видно»).
  4. решение `resolve_patterns`: «есть» → волокно; «узор» / «нет» → ровный тон; «не видно» → (1) наследовать от группы того же товара той же семьи (ножки/остальное) с тоном в inherit_de76 и решением;
     (2) нет — карточка в узком смысле, поле ПО РОЛИ части (T-93/6, `role_card` в rules; роль из этапа 03/Ш4а, не из имени): массив/шпон/порода (solid_words) → волокно, ЛДСП/МДФ/ДСП/ПВХ (board_words) → ровный;
     роль unknown или поля для роли в карточке нет → ровный; в поле ткань/велюр/кожа → ровный; (3) слова неоднозначны → ровный тон. Запрет: поле ЭТОЙ части — ткань/велюр/кожа → волокна нет и при уверенном «есть». Путь (measure / inherit / card / default) — в записи.
Числа — только из rules; ID товаров в коде нет. Маска изломов (fold_near_mask) НЕ вводится (T-93/2: почти ничего не меняет).

  python3 tests_part_grain_measure.py
"""
from __future__ import annotations

import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def pm_rules(rules: dict | None) -> dict | None:
    """Включённые правила меры или None (выключено/ключа нет — модуль не влияет ни на что)."""
    pm = (rules or {}).get('pattern_measure')
    return pm if pm and pm.get('enabled') else None


# ------------------------------------------------------------------ окна ---------------------------------------------------------------------------
def lab_L(rgb) -> np.ndarray:
    x = np.asarray(rgb)[..., :3].astype(np.float64) / 255.0
    x = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    y = 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]
    f = np.where(y > 0.008856, np.cbrt(y), 7.787 * y + 16 / 116)
    return 116 * f - 16


def reliable_mask(L, known, conf, gmask, pm: dict) -> np.ndarray:
    """Надёжные тексели группы: известные фото ∧ conf ≥ conf_min ∧ эрозия edge_px ∧ вдали от перепадов светлоты (max−min на 3 px > jump_L, расширение jump_pad)."""
    from scipy import ndimage as ndi
    ok = np.asarray(gmask, bool) & np.asarray(known, bool) & (np.asarray(conf, np.float64) >= float(pm['conf_min']))
    jump = ndi.binary_dilation(ndi.maximum_filter(L, size=3) - ndi.minimum_filter(L, size=3) > float(pm['jump_L']), iterations=int(pm['jump_pad']))
    return ndi.binary_erosion(ok, iterations=int(pm['edge_px'])) & ~jump


def largest_cc(rel) -> int:
    from scipy import ndimage as ndi
    lab, n = ndi.label(rel)
    return int(np.bincount(lab.ravel())[1:].max()) if n else 0


def window_stats(L, rel, pm: dict) -> list:
    """Окна window_px по надёжным (покрытие ≥ cover_min): [{'x','y','coh','angle','cover'}]; тензор структуры по полосе DoG σ(band_sigma) внутри окна (отступ 3 px от края надёжных)."""
    from scipy import ndimage as ndi
    w, pad, T = int(pm['window_px']), int(pm['pad_px']), L.shape[0]
    s_lo, s_hi = float(pm['band_sigma'][0]), float(pm['band_sigma'][1])
    out = []
    if not rel.any():
        return out
    ys, xs = np.where(rel)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    ii = np.pad(np.cumsum(np.cumsum(rel.astype(np.int32), 0), 1), ((1, 0), (1, 0)))
    for y in range(y0, max(y1 - w + 1, y0 + 1), w):
        for x in range(x0, max(x1 - w + 1, x0 + 1), w):
            if y + w > T or x + w > L.shape[1]:
                continue
            s = ii[y + w, x + w] - ii[y, x + w] - ii[y + w, x] + ii[y, x]
            if s < float(pm['cover_min']) * w * w:
                continue
            ya, yb, xa, xb = max(y - pad, 0), min(y + w + pad, T), max(x - pad, 0), min(x + w + pad, L.shape[1])
            Lp, mp = L[ya:yb, xa:xb], rel[ya:yb, xa:xb]
            inner = np.zeros(mp.shape, bool)
            inner[y - ya:y - ya + w, x - xa:x - xa + w] = True
            wgt = mp.astype(np.float64)

            def blur(a, sg):
                return ndi.gaussian_filter(a * wgt, sg) / np.maximum(ndi.gaussian_filter(wgt, sg), 1e-6)
            band = blur(Lp, s_lo) - blur(Lp, s_hi)
            gy, gx = np.gradient(band)
            wt = (ndi.binary_erosion(mp, iterations=3) & inner).astype(np.float64)
            if wt.sum() < float(pm['min_win_px']):
                continue
            sxx, syy, sxy = ((a_ * wt).sum() for a_ in (gx * gx, gy * gy, gx * gy))
            tr = sxx + syy
            if tr <= 1e-9:
                continue
            out.append({'x': int(x), 'y': int(y), 'coh': float(np.sqrt((sxx - syy) ** 2 + 4 * sxy ** 2) / tr), 'angle': float(np.degrees(0.5 * np.arctan2(2 * sxy, sxx - syy))), 'cover': float(s / (w * w))})
    return out


def axial_median(angles) -> float:
    a = np.radians(2 * np.asarray(angles, np.float64))
    return float(np.degrees(np.arctan2(np.sin(a).mean(), np.cos(a).mean())) / 2.0)


def passing_windows(wins: list, pm: dict) -> list:
    """Окна «есть направленный рисунок»: coh ≥ coh_min ∧ угол в ±angle_tol от медианного угла группы (медиана — по окнам с coh ≥ coh_min, иначе по всем)."""
    if not wins:
        return []
    t = float(pm['coh_min'])
    good = [w['angle'] for w in wins if w['coh'] >= t]
    ref = axial_median(good) if good else axial_median([w['angle'] for w in wins])
    return [w for w in wins if w['coh'] >= t and abs((w['angle'] - ref + 90) % 180 - 90) <= float(pm['angle_tol_deg'])]


def wilson(k: int, n: int, z: float) -> tuple:
    """Доверительный интервал Уилсона для доли k/n (z — квантиль, 1,645 ≈ 90 %). n = 0 → (0, 1): ничего не известно."""
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1.0 + z * z / n
    c = (p + z * z / (2.0 * n)) / d
    h = z * np.sqrt(p * (1.0 - p) / n + z * z / (4.0 * n * n)) / d
    return float(max(0.0, c - h)), float(min(1.0, c + h))


def share_verdict(k: int, n_win: int, area: int, pm: dict) -> str:
    """«есть» / «нет» / «не видно» по k окнам с волокном из n_win и площади A (T-93/5, вердикт Fable): граница доверия одного уровня (Уилсон, ci_z) против одного порога p_split —
    «нет» только если ВЕРХНЯЯ граница < p_split, «есть» только если НИЖНЯЯ > p_split, иначе «не видно». Ширина группы в решении не участвует: малое число окон само даёт широкий интервал."""
    if n_win < int(pm['windows_min']) or area < int(pm['area_min_px']):
        return 'не видно'
    lo, hi = wilson(k, n_win, float(pm['ci_z']))
    if lo > float(pm['p_split']):
        return 'есть'
    if hi < float(pm['p_split']):
        return 'нет'
    return 'не видно'


# ------------------------------------------------------------------ геометрия: направление относительно осей панели ----------------------------------
class FaceFrame:
    """Растр развёртки (id грани на тексель), якобиан UV→3D по граням и оси панелей (part_grain.plane_axes по центрам граней плоскости). Строится один раз на геометрию."""

    def __init__(self, V, F, UV, T: int, face_plane, plane_normal, rules: dict):
        import part_grain as PG
        import tex_coverage as TC
        self.V, self.F = np.asarray(V, np.float64), np.asarray(F, np.int64)
        px = np.stack([np.asarray(UV, float)[:, 0] * T, (1.0 - np.asarray(UV, float)[:, 1]) * T], 1)
        ids, _ = TC.raster(px, self.F, T)
        self.ids = np.asarray(ids).reshape(T, T)
        P0, P1, P2 = self.V[self.F[:, 0]], self.V[self.F[:, 1]], self.V[self.F[:, 2]]
        self.P0, self.P1, self.P2 = P0, P1, P2
        q0 = px[self.F[:, 0]]
        self.q1, self.q2 = px[self.F[:, 1]] - q0, px[self.F[:, 2]] - q0
        self.det = self.q1[:, 0] * self.q2[:, 1] - self.q1[:, 1] * self.q2[:, 0]
        self.fp, self.pn = np.asarray(face_plane), np.asarray(plane_normal)
        cen = (P0 + P1 + P2) / 3.0
        self.axes = {}
        for pl in np.unique(self.fp):
            if pl < 0:
                continue
            fs = np.where(self.fp == pl)[0]
            if len(fs) < 4:
                continue
            c1, c2, rl = PG.plane_axes(cen[fs], self.pn[pl], None, rules)
            self.axes[int(pl)] = (c1, c2, bool(rl))

    def dev_deg(self, gmask, x: int, y: int, w: int, angle_deg: float):
        """Отклонение (0…45°) направления полос окна от ближайшей оси панели; None — ось неизвестна (нет плоскости, круглая/мелкая, вырожденная грань).
        angle_deg — угол ГРАДИЕНТА в окне (как `window_stats`); линия полосы ⟂ градиенту."""
        blk = self.ids[y:y + w, x:x + w][np.asarray(gmask, bool)[y:y + w, x:x + w]]
        blk = blk[blk >= 0]
        if not len(blk):
            return None
        fid = int(np.bincount(blk).argmax())
        pl = int(self.fp[fid])
        if pl not in self.axes or abs(self.det[fid]) < 1e-9:
            return None
        c1, c2, rl = self.axes[pl]
        if rl:
            return None
        a = np.radians(angle_deg)
        ld = np.array([-np.sin(a), np.cos(a)])
        minv = np.array([[self.q2[fid, 1], -self.q2[fid, 0]], [-self.q1[fid, 1], self.q1[fid, 0]]]) / self.det[fid]
        jm = np.stack([self.P1[fid] - self.P0[fid], self.P2[fid] - self.P0[fid]], 1) @ minv
        v = jm @ ld
        n = self.pn[pl]
        v = v - (v @ n) * n
        nv = float(np.linalg.norm(v))
        if nv < 1e-12:
            return None
        v = v / nv
        return float(min(np.degrees(np.arccos(min(1.0, abs(float(v @ c1))))), np.degrees(np.arccos(min(1.0, abs(float(v @ c2)))))))


def ac_context(L, known, pm: dict):
    """Как паспорт 07: мелкая полоса L (σ=grain_fine_px, размытие нормировано по ВСЕМ известным текселям, эрозия known_erode_px) и маска kc. Считается один раз на текстуру."""
    from scipy import ndimage as ndi
    kc = ndi.binary_erosion(np.asarray(known, bool), iterations=int(pm['known_erode_px'])) if int(pm['known_erode_px']) > 0 else np.asarray(known, bool)
    w = kc.astype(np.float64)
    sg = float(pm['grain_fine_px'])
    fine = L - ndi.gaussian_filter(L * w, sg, mode='nearest') / np.maximum(ndi.gaussian_filter(w, sg, mode='nearest'), 1e-9)
    return fine.astype(np.float32), kc


def ac_value(ctx, gmask, pm: dict):
    """Пик автокорреляции мелкой полосы L по известным текселям группы (как паспорт 07: `surface_passport.ac_peak`); мало текселей (< ac_min_texels) → None (признака нет)."""
    fine, kc = ctx
    msk = kc & np.asarray(gmask, bool)
    if int(msk.sum()) < int(pm['ac_min_texels']):
        return None
    import surface_passport as SP
    return float(SP.ac_peak(fine, msk, int(pm['ac_lag_lo_px']), int(pm['ac_lag_hi_px']), float(pm['ac_clip_k'])))


def measure_group(L, known, conf, gmask, pm: dict, ff: FaceFrame | None = None, ac_ctx=None) -> dict:
    """Мера группы: доля окон, их число, площадь A, ac_peak, отклонение от осей, класс. verdict ∈ fiber | pattern | no | unseen (unseen = «не видно»)."""
    rel = reliable_mask(L, known, conf, gmask, pm)
    wins = window_stats(L, rel, pm)
    ps = passing_windows(wins, pm)
    share = (len(ps) / len(wins)) if wins else None
    area = largest_cc(rel)
    base = share_verdict(len(ps), len(wins), area, pm)
    ci = wilson(len(ps), len(wins), float(pm['ci_z'])) if wins else None
    ac = ac_value(ac_ctx if ac_ctx is not None else ac_context(L, known, pm), gmask, pm)
    devs = []
    if ff is not None:
        for w in ps:
            d = ff.dev_deg(gmask, w['x'], w['y'], int(pm['window_px']), w['angle'])
            if d is not None:
                devs.append(d)
    dev_med = float(np.median(devs)) if devs else None
    edge = float(pm['edge_frac'])
    ac_lo, ac_hi = float(pm['ac_pattern_min']) * (1 - edge), float(pm['ac_pattern_min']) * (1 + edge)
    dv_lo, dv_hi = (float(x) for x in pm['dev_unsure_deg'])
    by_ac = ac is not None and ac > ac_hi                                                        # уверенный повтор шага (выше полосы «на грани»)
    by_dev = len(devs) >= int(pm['dev_windows_min']) and dev_med > dv_hi                         # уверенное диагональное направление
    unsure = []                                                                                  # Г: значение ближе edge_frac к порогу — «не видно»
    if ac is not None and ac_lo <= ac <= ac_hi:
        unsure.append('повтор шага ac_peak %.2f на грани порога %.2f (%.2f–%.2f)' % (ac, float(pm['ac_pattern_min']), ac_lo, ac_hi))
    if len(devs) >= int(pm['dev_windows_min']) and dv_lo <= dev_med <= dv_hi:
        unsure.append('направление %.0f° на грани порога %.0f° (%.0f–%.0f°)' % (dev_med, float(pm['dev_pattern_min_deg']), dv_lo, dv_hi))
    a_min = float(pm['area_min_px'])
    if a_min * (1 - edge) <= area < a_min * (1 + edge):
        unsure.append('площадь %d на грани порога %d' % (area, int(a_min)))
    if base == 'нет':
        verdict, why = 'no', 'окон с волокном %d из %d, верхняя граница Уилсона %.2f < %.2f' % (len(ps), len(wins), ci[1], float(pm['p_split']))
    elif by_ac or by_dev:
        verdict, why = 'pattern', ('повтор шага ac_peak %.2f > %.2f' % (ac, ac_hi)) if by_ac else ('направление %.0f° от осей панели > %.0f° (окон с осью %d)' % (dev_med, dv_hi, len(devs)))
    elif unsure:
        verdict, why = 'unseen', 'на грани: ' + '; '.join(unsure)
    elif base == 'есть':
        verdict, why = 'fiber', 'окон с волокном %d из %d, нижняя граница Уилсона %.2f > %.2f, повтор и направление не «узор»' % (len(ps), len(wins), ci[0], float(pm['p_split']))
    else:
        verdict, why = 'unseen', 'не видно: окон %d, A %d, %s' % (len(wins), area, 'окон нет' if ci is None else 'окон с волокном %d, интервал Уилсона %.2f–%.2f накрывает порог %.2f' % (len(ps), ci[0], ci[1], float(pm['p_split'])))
    return {'verdict': verdict, 'why': why, 'share': None if share is None else round(share, 3), 'ci': None if ci is None else [round(ci[0], 3), round(ci[1], 3)], 'n_windows': len(wins), 'n_pass': len(ps), 'area': area,
            'ac_peak': None if ac is None else round(ac, 3), 'n_dev': len(devs), 'dev_med': None if dev_med is None else round(dev_med, 1), 'base': base}


# ------------------------------------------------------------------ решение: наследование, карточка --------------------------------------------------
def card_text(card: dict | None, role: str | None, name: str, rules: dict) -> str:
    """Текст материала карточки для части в том же смысле, что `part_grain.part_is_wood` (ножки — «Материал ножек», остальное — корпус/фасад/столешница/каркас)."""
    card = card or {}
    legs = role == 'legs' if role else any(w in (name or '').lower() for w in rules['leg_part_words'])
    keys = rules['leg_card_keys'] if legs else rules['wood_card_keys']
    return ' '.join(str(v).lower() for k, v in card.items() if any(s in k.lower() for s in keys))


def has_upholstery(text: str, pm: dict) -> bool:
    """В тексте поля карточки названа обивочная ткань/кожа (ткань, велюр, экокожа, рогожка, вельвет…): слова целиком по началу (upholstery_stems) или точно (upholstery_exact: «лен», «кожа»)."""
    stems, exact = tuple(pm['upholstery_stems']), set(pm['upholstery_exact'])
    return any(t in exact or t.startswith(stems) for t in re.findall(r'[а-яёa-z]+', (text or '').lower()))


def role_field(card: dict | None, role: str | None, rules: dict) -> dict:
    """Поле карточки по РОЛИ части (T-93/6, вердикт Fable (а)); роль — из этапа 03 / Ш4а, имя части не используется.
    → {'status': 'legacy' | 'unknown' | 'nofield' | 'ok', 'text': str, 'fields': [имена полей], 'role': str}:
      legacy — роль не пришла (None/''): прежнее правило card_text (поля корпуса/ножек по имени); unknown — роль «unknown» или нет в карте role_card: «не видно», поля нет;
      nofield — у роли в карте есть ключи, но в карточке такого поля нет (соседней роли НЕ подставляем); ok — поля найдены, text — их значения."""
    pm = rules['pattern_measure']
    r = (role or '').strip()
    if not r:
        return {'status': 'legacy', 'text': '', 'fields': [], 'role': ''}
    keys = (pm.get('role_card') or {}).get(r)
    if r == 'unknown' or not keys:
        return {'status': 'unknown', 'text': '', 'fields': [], 'role': r}
    hit = [(k, v) for k, v in (card or {}).items() if any(s in k.lower() for s in keys)]
    if not hit:
        return {'status': 'nofield', 'text': '', 'fields': [], 'role': r}
    return {'status': 'ok', 'text': ' '.join(str(v).lower() for _k, v in hit), 'fields': [k for k, _v in hit], 'role': r}


def field_summary(parts: list, rules: dict) -> dict:
    """Счётчик для отчёта (на каталоге названия полей поплывут): сколько групп по статусам поля карточки; перечень «роль есть, поля нет» и «роль не названа»."""
    cnt = {'ok': 0, 'nofield': 0, 'unknown': 0, 'legacy': 0}
    nof, unk = [], []
    for p in parts:
        f = role_field(p.get('card'), p.get('role'), rules)
        cnt[f['status']] += 1
        if f['status'] == 'nofield':
            nof.append('%s:%s' % (p['id'], f['role']))
        elif f['status'] == 'unknown':
            unk.append('%s:%s' % (p['id'], f['role']))
    return {'groups': len(parts), 'field_found': cnt['ok'], 'field_not_found': cnt['nofield'], 'role_unknown': cnt['unknown'], 'role_missing_legacy': cnt['legacy'],
            'field_not_found_ids': nof, 'role_unknown_ids': unk}


def card_decision(text: str, pm: dict) -> tuple:
    """Карточка в узком смысле: solid_words (массив/шпон/порода) → волокно; иначе board_words (ЛДСП/МДФ/ДСП/ПВХ) → ровный; пусто/ни того ни другого → ровный (default)."""
    if any(w in text for w in pm['solid_words']):
        return 'fiber', 'card', 'карточка: массив/шпон/порода'
    if any(w in text for w in pm['board_words']):
        return 'flat', 'card', 'карточка: плита (ЛДСП/МДФ/ДСП/ПВХ) — ровный тон'
    return 'flat', 'default', 'карточки нет или материал не назван — ровный тон'


def _name_has(p: dict, words) -> bool:
    n = (p.get('name') or '').lower()
    return any(w in n for w in words)


def is_legs(p: dict, rules: dict) -> bool:
    """Семья «ножки/опоры»: роль legs; роль не названа/unknown — по словам имени (leg_part_words)."""
    role = p.get('role')
    if role in (None, '', 'unknown'):
        return _name_has(p, rules['leg_part_words'])
    return role == 'legs'


def material_clusters(parts: list, rules: dict) -> dict:
    """{id части: номер материала товара}. Ножки товара — ОДИН материал (в карточке один «Материал ножек»; ножки не соприкасаются, паспорт Ш4а их по границам не склеивает);
    остальные группы — один материал, если их тона связаны цепочкой ΔE76 ≤ inherit_de76. Части с именем «не дерево» (подушка/сиденье/ручка…) в материалы не входят."""
    pm = rules['pattern_measure']
    mem = [p for p in parts if not _name_has(p, rules['non_wood_part_words'])]
    par = {p['id']: p['id'] for p in mem}

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a

    legs = [p for p in mem if is_legs(p, rules)]
    for p in legs[1:]:
        par[find(p['id'])] = find(legs[0]['id'])
    rest = [p for p in mem if not is_legs(p, rules)]
    for i, a in enumerate(rest):
        for b in rest[i + 1:]:
            if a.get('tone_lab') is None or b.get('tone_lab') is None:
                continue
            if float(np.linalg.norm(np.asarray(a['tone_lab'], float) - np.asarray(b['tone_lab'], float))) <= float(pm['inherit_de76']):
                par[find(a['id'])] = find(b['id'])
    return {p['id']: find(p['id']) for p in mem}


def _tone_d(a: dict, b: dict) -> float:
    if a.get('tone_lab') is None or b.get('tone_lab') is None:
        return 1e9
    return float(np.linalg.norm(np.asarray(a['tone_lab'], float) - np.asarray(b['tone_lab'], float)))


def resolve_patterns(parts: list, rules: dict) -> dict:
    """{id части: {'decision': 'fiber'|'flat', 'path': 'measure'|'material'|'inherit'|'card'|'default', 'why', 'verdict', 'from'}}. parts[i]: id, name, role, tone_lab, card, measure (dict из `measure_group` | None).
    Порядок (T-93/4): (1) своя мера — «есть»/«узор»/уверенное «нет» («нет» — только по верхней границе Уилсона, см. measure_group);
    (2) МАТЕРИАЛ товара: уверенное «есть» хотя бы у одной группы материала решает за все группы материала (кроме «узора»); (3) «не видно» наследует от уверенной группы материала, СНАЧАЛА с той же ролью, потом любой;
    (4) карточка в узком смысле — поле ПО РОЛИ части (T-93/6, `role_field`): роль unknown → «не видно», ровный; поля для роли в карточке нет → ровный (поле соседней роли не подставляется); роль не пришла (None) — прежнее правило;
    в поле ткань/велюр/кожа → ровный; (5) ровный. Запрет: если поле карточки ЭТОЙ части — ткань/велюр/кожа/вельвет, волокна нет и при уверенном «есть» (мера, материал). Части с именем «не дерево» — только своя мера/карточка (в материал не входят)."""
    pm = rules['pattern_measure']
    out = {}
    mat = material_clusters(parts, rules)
    by_id = {p['id']: p for p in parts}
    fields = {p['id']: role_field(p.get('card'), p.get('role'), rules) for p in parts}           # T-93/6: поле карточки по роли (не по имени)
    for p in parts:
        m = p.get('measure') or {}
        v = m.get('verdict')
        if v in ('fiber', 'pattern', 'no'):
            out[p['id']] = {'decision': 'fiber' if v == 'fiber' else 'flat', 'path': 'measure', 'why': m.get('why'), 'verdict': v, 'from': None}
    own = dict(out)                                                                              # решения по собственной мере (до материала)
    # (2) материал: «есть» решает за все
    for mid in sorted(set(mat.values())):
        mem = [by_id[i] for i, c in mat.items() if c == mid]
        yes = [p for p in mem if p['id'] in own and own[p['id']]['verdict'] == 'fiber']
        if not yes:
            continue
        for p in mem:
            o = own.get(p['id'])
            if o is not None and o['verdict'] in ('fiber', 'pattern'):
                continue
            src = min(yes, key=lambda q: (0 if (q.get('role') == p.get('role')) else 1, _tone_d(p, q)))
            out[p['id']] = {'decision': 'fiber', 'path': 'material', 'verdict': 'unseen' if o is None else o['verdict'], 'from': src['id'],
                            'why': 'материал товара: у группы %s уверенное «есть» (%s) — решает за все группы материала%s' % (src['id'], (own[src['id']].get('why') or '')[:60], '' if o is None else '; своё «нет» было уверенным — переопределено')}
    # (3) «не видно»: от уверенной (нет/узор) группы того же материала — роль, затем любая
    for p in parts:
        if p['id'] in out or p['id'] not in mat:
            continue
        cand = [by_id[i] for i, c in mat.items() if c == mat[p['id']] and i in own and own[i]['verdict'] in ('no', 'pattern')]
        if cand:
            q = min(cand, key=lambda q: (0 if (q.get('role') == p.get('role')) else 1, _tone_d(p, q)))
            out[p['id']] = {'decision': 'flat', 'path': 'inherit', 'verdict': 'unseen', 'from': q['id'],
                            'why': 'наследовано от группы %s материала (%s, решение «%s»)' % (q['id'], 'та же роль' if q.get('role') == p.get('role') else 'другая роль', own[q['id']]['verdict'])}
    # (4–5) карточка / ровный
    for p in parts:
        if p['id'] in out:
            continue
        if _name_has(p, rules['non_wood_part_words']):                                          # явно недеревянное по имени (подушка, сиденье, ручка…): карточка корпуса к нему не относится
            out[p['id']] = {'decision': 'flat', 'path': 'card', 'why': 'имя части — не дерево (%s)' % p.get('name'), 'verdict': 'unseen', 'from': None}
            continue
        f = fields[p['id']]
        if f['status'] == 'legacy':                                                              # роль не пришла — прежнее правило карточки
            dec, path, why = card_decision(card_text(p.get('card'), None, p.get('name', ''), rules), pm)
        elif f['status'] == 'unknown':
            dec, path, why = 'flat', 'default', 'роль части «%s» — не названа: поля карточки нет, «не видно» → ровный тон' % (f['role'] or 'unknown')
        elif f['status'] == 'nofield':
            dec, path, why = 'flat', 'default', 'в карточке нет поля для роли «%s» (соседней роли не подставляем) → ровный тон' % f['role']
        elif has_upholstery(f['text'], pm):
            dec, path, why = 'flat', 'card', 'поле карточки роли «%s» (%s): ткань/велюр/кожа → ровный, волокна нет' % (f['role'], '; '.join(f['fields'])[:60])
        else:
            dec, path, why = card_decision(f['text'], pm)
        out[p['id']] = {'decision': dec, 'path': path, 'why': why, 'verdict': 'unseen', 'from': None}
    # запрет (T-93/6): карточка ЭТОЙ части называет ткань/велюр/кожу/вельвет → волокна нет даже при уверенном «есть» по мере и по голосу материала
    for p in parts:
        o, f = out[p['id']], fields[p['id']]
        if o['decision'] == 'fiber' and f['status'] == 'ok' and has_upholstery(f['text'], pm):
            out[p['id']] = {'decision': 'flat', 'path': 'card', 'verdict': o.get('verdict'), 'from': None,
                            'why': 'запрет: поле карточки роли «%s» (%s) — ткань/велюр/кожа: волокна нет, хотя было «%s» (%s)' % (f['role'], '; '.join(f['fields'])[:60], o['path'], (o.get('why') or '')[:50])}
    for p in parts:
        out[p['id']]['field'] = {'role': fields[p['id']]['role'], 'status': fields[p['id']]['status'], 'fields': fields[p['id']]['fields'][:4]}
    return out

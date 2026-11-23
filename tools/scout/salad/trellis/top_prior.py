#!/usr/bin/env python3
"""Ш3в плана paint-photo-fill-01 (T-20261121-173/3): верх деревянной столешницы, которого нет на единственном фото.

ЗАЧЕМ. Горизонтальная плита (стол, тумба, комод) снята вровень — верх на фото не виден (камера el≈8°, верх = 70–90 % текселей, а граней — единицы %). Слепое продолжение
цвета фасада даёт чужой тон. Здесь верх получает ГИПОТЕЗУ тона и рисунка с провенансом и честным «не знаю»; фактический рисунок восстановить нельзя.

ГОЛОСА (каждый — свой Lab верха; пороги — только `tools/scout/rules/top-prior.json`, ID товаров в коде нет):
  edge    — кромка той же плиты: видимые вертикальные тексели в верхней полосе под плоскостью верха (тот же материал, что верх, чаще всего);
  plane   — видимая вертикальная плоскость того же тела (фасад/боковина), без кромки и ножек;
  trellis — родной цвет TRELLIS.2 на текселях верха (`tex_fill.draft_texels`): тексели ≈ цвет фона фото (ΔE00 < `bg_de00`) НЕ считаются; их много — голос = unknown;
  card    — слово карточки («Материал столешницы» через `material_class.classify`): только КЛАСС (дерево/декор/другое), не цвет.
РЕШЕНИЕ (`decide`, чистая функция): класс «другое» (металл/стекло/камень/керамика/пластик) → маршрут в этап 08, тон не выводится; иначе главный голос edge → plane → trellis;
несогласие главного с trellis (ΔE00 > `agree_de00`) → нейтральный верх + `unknown` (правило P-062); edge против plane — подсказка «верх другого материала», тон остаётся кромки
(`edge_plane_disagree`: prefer_edge | unknown); голосов нет → unknown. Провенанс: photo_top / same_part_inference / library_prior / trellis_prior / unknown.
РЕЖИМ: `enabled=false, mode=dry` — только отчёт `top_prior.json` и кадр «было | гипотеза»; текстура продукта не меняется.

  python3 top_prior.py dry <run> [--card '{"Материал столешницы": "…", "role": "стол обеденный"}'] [--out ДИР]
  python3 tests_top_prior.py
"""
from __future__ import annotations

import json
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
RULES_PATH = os.path.join(ROOT, 'tools', 'scout', 'rules', 'top-prior.json')
SOURCES = ('photo_top', 'same_part_inference', 'library_prior', 'trellis_prior', 'unknown')


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _de(a, b) -> float:
    """ΔE00 двух цветов Lab (общая реализация меры охвата `tex_coverage.de2000_v`)."""
    import tex_coverage as TC
    return float(TC.de2000_v(np.asarray([a], np.float64), np.asarray([b], np.float64))[0])


# ---------------------------------------------------------------- класс по слову карточки ---------------------------
def card_class(card: dict | None, rules: dict) -> dict:
    """Класс верха по карточке: {'class': <id material_class>|None, 'group': library|decor|other|None, 'reason'}. Только класс — цвета из слов не берём (мерка ABO: слово цвета относится ко всей вещи)."""
    if not card:
        return {'class': None, 'group': None, 'reason': 'нет карточки'}
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'assets'))
    import material_class as MC
    mr = MC.load_rules()
    params = {k: v for k, v in card.items() if k != 'role' and k != 'name'}
    rec = MC.classify(mr, {'role': card.get('role') or '', 'name': card.get('name') or '', 'params': params})
    cls = rec.get('class')
    for grp, ids in rules['classes'].items():
        if cls in ids:
            out = {'class': cls, 'group': grp, 'reason': rec.get('reason'), 'stage': rec.get('stage'), 'confidence': rec.get('confidence')}
            text = ' '.join(str(v) for v in card.values()).lower()
            hit = next((w for w in rules.get('wood_look_words', []) if re.search(r'(?<![а-яёa-z])' + re.escape(w), text)), None)   # слово начинается с основы («тик» не в «пластик»)
            if grp == 'decor' and hit:
                out.update(group='library', reason=f"{rec.get('reason')}; слова карточки называют дерево («{hit}») — узор дерева")
            return out
    return {'class': cls, 'group': None, 'reason': rec.get('reason'), 'stage': rec.get('stage')}


def card_pattern(card: dict | None, rules: dict) -> dict:
    """Класс рисунка товара по слову карточки: {'bin_classes': […], 'layout': 'planks'|'none', 'word': слово|None}. Первая запись by_word, чьё слово встретилось (с начала слова); нет — default."""
    text = ' '.join(str(v) for v in (card or {}).values()).lower()
    for e in rules['pattern']['by_word']:
        for w in e['words']:
            if re.search(r'(?<![а-яёa-z])' + re.escape(w), text):
                return {'bin_classes': list(e['bin_classes']), 'layout': e['layout'], 'word': w}
    return dict(rules['pattern']['default'], word=None)


def photo_band_std(photo_path: str | None, rules: dict):
    """Высокочастотный разброс L в верхней полосе силуэта фото каталога (гладкий ход по x вычтен). Нет файла/пикселей — None."""
    if not photo_path or not os.path.exists(photo_path):
        return None
    import tex_coverage as TC
    from PIL import Image
    pb = rules['pattern']['photo_band']
    im = Image.open(photo_path)
    rgb = np.asarray(im.convert('RGB')).astype(np.uint8)
    alpha = (np.asarray(im)[..., 3] > pb['alpha_min']) if im.mode == 'RGBA' else (rgb.min(axis=2) < pb['white_max'])
    rows = np.where(alpha.any(axis=1))[0]
    if len(rows) == 0:
        return None
    y0, H = int(rows.min()), int(rows.max() - rows.min() + 1)
    L = TC.rgb2lab(rgb.reshape(-1, 3)).reshape(rgb.shape)[..., 0]
    k = max(pb['min_rows'], int(pb['frac'] * H))
    band = np.zeros_like(alpha)
    band[y0 + 2:y0 + 2 + k] = True
    core = band & alpha & np.roll(band & alpha, 3, 1) & np.roll(band & alpha, -3, 1)
    w, vals = pb['hp_window'], []
    for y in np.where(core.any(axis=1))[0]:
        row = L[y][core[y]]
        if len(row) < 2 * w:
            continue
        vals.append((row - np.convolve(row, np.ones(w) / w, mode='same'))[w // 2 + 1:-(w // 2 + 1)])
    v = np.concatenate(vals) if vals else np.zeros(0)
    return round(float(v.std()), 3) if len(v) >= pb['min_px'] else None


def photo_groove_dL(photo_path: str | None, rules: dict):
    """Глубина шва между планками по фото каталога (единицы L): поперечный минимум высокочастотной составляющей под верхней кромкой силуэта. Нет данных — None."""
    if not photo_path or not os.path.exists(photo_path):
        return None
    import tex_coverage as TC
    from PIL import Image
    g, pb = rules['pattern']['groove'], rules['pattern']['photo_band']
    im = Image.open(photo_path)
    rgb = np.asarray(im.convert('RGB')).astype(np.uint8)
    alpha = (np.asarray(im)[..., 3] > pb['alpha_min']) if im.mode == 'RGBA' else (rgb.min(axis=2) < pb['white_max'])
    rows = np.where(alpha.any(axis=1))[0]
    cols = np.where(alpha.any(axis=0))[0]
    if len(rows) == 0:
        return None
    H = int(rows.max() - rows.min() + 1)
    L = TC.rgb2lab(rgb.reshape(-1, 3)).reshape(rgb.shape)[..., 0]
    k, w = max(g['min_rows'], int(g['band_frac'] * H)), g['hp_window']
    x0, x1 = int(cols.min() + g['x_from'] * (cols.max() - cols.min())), int(cols.min() + g['x_to'] * (cols.max() - cols.min()))
    mins = []
    for x in range(x0, x1):
        ys = np.where(alpha[:, x])[0]
        if len(ys) == 0:
            continue
        col = L[ys[0] + 2:ys[0] + 2 + k, x]
        if len(col) < k:
            continue
        hp = (col - np.convolve(col, np.ones(w) / w, mode='same'))[w // 2 + 1:-(w // 2 + 1)]
        hp = hp[hp > -g['edge_reject_L']]
        if len(hp) >= 4:
            mins.append(float(hp.min()))
    if len(mins) < g['min_cols']:
        return None
    return round(float(np.clip(-np.median(mins), g['min_dL'], g['max_dL'])), 2)


def card_dims(card: dict | None) -> dict:
    """Толщина верха и наибольший габарит из карточки, см: «Толщина столешницы 1 см», «160x90» в названии/модификации. Нет — None (полоса кромки по умолчанию)."""
    out = {'thickness_cm': None, 'length_cm': None, 'width_cm': None}
    if not card:
        return out
    for k, v in card.items():
        if 'толщина' in str(k).lower() and 'столеш' in str(k).lower():
            m = re.search(r'(\d+(?:[.,]\d+)?)\s*(мм|см)?', str(v))
            if m:
                x = float(m.group(1).replace(',', '.'))
                out['thickness_cm'] = x / 10.0 if (m.group(2) == 'мм' or x > 12) else x
    text = ' '.join(str(v) for v in card.values())
    m = re.search(r'(\d{2,3})\s*[xх×]\s*(\d{2,3})', text)
    if m:
        out['length_cm'] = float(max(int(m.group(1)), int(m.group(2))))
        out['width_cm'] = float(min(int(m.group(1)), int(m.group(2))))
    return out


# ---------------------------------------------------------------- решение (чистая функция) -------------------------
def decide(voices: dict, rules: dict) -> dict:
    """voices: {'edge'|'plane'|'trellis': {'lab': [L,a,b], 'n': число текселей, 'bg_share': доля ≈ фону (trellis)}|None, 'card': {'group': …}|None}.
    → {'source','type','tone_lab','confidence','agree','candidates','reason','route','other_material_hint','trellis_unknown'}"""
    r = rules['decision']
    out = {'source': 'unknown', 'type': 'unknown', 'tone_lab': None, 'confidence': 'none', 'agree': None, 'candidates': [], 'reason': '', 'route': 'library',
           'other_material_hint': False, 'trellis_unknown': False}
    card = voices.get('card') or {}
    if card.get('group') == 'other':
        out.update(type='other_class', route='stage08', reason=f"класс верха по карточке «{card.get('class')}» — не дерево: тон по фото не выводится, материал решает этап 08")
        return out
    use = {}
    flat_fallback = None
    for k, nmin in (('edge', r['min_edge_texels']), ('plane', r['min_plane_texels']), ('trellis', r['min_trellis_texels'])):
        v = voices.get(k)
        if v is None or v.get('lab') is None or v.get('n', 0) < nmin:
            out['candidates'].append({'voice': k, 'used': False, 'why': 'нет данных' if v is None or v.get('lab') is None else f"тексели {v.get('n', 0)} < {nmin}"})
            continue
        if k == 'trellis' and v.get('flat_std') is not None and v['flat_std'] < r['trellis_flat_std']:
            out['trellis_unknown'] = True
            out['candidates'].append({'voice': k, 'used': False, 'why': f"плоская заливка (разброс L {v['flat_std']:.1f} < {r['trellis_flat_std']}): против других голосов не спорит; сам по себе — запасной тон, low", 'lab': [round(float(x), 1) for x in v['lab']],
                                      'flat_std': round(float(v['flat_std']), 2)})
            flat_fallback = np.asarray(v['lab'], np.float64)
            continue
        if k == 'trellis' and v.get('bg_share', 0.0) > r['bg_share_max']:
            out['trellis_unknown'] = True
            out['candidates'].append({'voice': k, 'used': False, 'why': f"тексели ≈ фон фото: {100 * v['bg_share']:.0f} % > {100 * r['bg_share_max']:.0f} %", 'bg_share': round(v['bg_share'], 3)})
            continue
        use[k] = np.asarray(v['lab'], np.float64)
        c = {'voice': k, 'used': True, 'lab': [round(float(x), 1) for x in v['lab']], 'n': int(v['n'])}
        if k == 'trellis':
            c['bg_share'] = round(float(v.get('bg_share', 0.0)), 3)
        out['candidates'].append(c)
    primary = 'edge' if 'edge' in use else ('plane' if 'plane' in use else ('trellis' if 'trellis' in use else None))
    if primary is None and flat_fallback is not None:
        out.update(source='trellis_prior', type='trellis_only', confidence='low', tone_lab=[round(float(x), 1) for x in flat_fallback], agree=True,
                   reason='голосов по фото нет; запасной тон — плоская заливка TRELLIS (низкая уверенность, не измерено по фото)')
        return out
    if primary is None:
        out['reason'] = 'ни один голос не набрал текселей — верх нейтральный'
        return out
    tone = use[primary]
    out['agree'] = True
    for c in out['candidates']:
        if c.get('used') and c['voice'] != primary:
            c['dE00_to_primary'] = round(_de(tone, use[c['voice']]), 1)
    if primary == 'edge' and 'plane' in use:
        d = _de(tone, use['plane'])
        if d > r['edge_de00']:
            out['other_material_hint'] = True
            if r['edge_plane_disagree'] == 'unknown':
                out.update(agree=False, reason=f'кромка и плоскость расходятся на ΔE00 {d:.1f} > {r["edge_de00"]} — верх другого материала, правило: unknown')
                return out
    if 'trellis' in use and primary != 'trellis':
        d = _de(tone, use['trellis'])
        if d > r['agree_de00']:
            out.update(agree=False, reason=f'{primary} и родной цвет TRELLIS расходятся на ΔE00 {d:.1f} > {r["agree_de00"]} → нейтральный верх, unknown')
            return out
    n_agree = 1 + sum(1 for k in use if k != primary and _de(tone, use[k]) <= (r['edge_de00'] if k in ('edge', 'plane') else r['agree_de00']))
    out['tone_lab'] = [round(float(x), 1) for x in tone]
    if primary == 'trellis':
        out.update(source='trellis_prior', confidence='low', type='trellis_only', reason='только родной цвет TRELLIS (не измерено по фото)')
    else:
        out.update(source='same_part_inference', type='other_material_hint' if out['other_material_hint'] else 'continuation',
                   confidence='high' if n_agree >= 2 else ('medium' if primary == 'edge' else 'low'),
                   reason=f'главный голос «{primary}», согласных голосов {n_agree} из {len(use)}')
    return out


def library_bin(tone_lab, kind: str, library: dict, rules: dict, cls: str | None = None, bin_classes: list | None = None) -> dict:
    """Бин библиотеки по тону: kind 'decor' (плоская плёнка/краска/ЛДСП) — без рисунка; 'library' — ближайший по ΔE00 скан дерева. → {'bin','dE00','grain_axis','tile_cm'}."""
    if tone_lab is None:
        return {'bin': None}
    if kind != 'library':
        return {'bin': 'flat', 'dE00': 0.0}
    best = None
    fam = rules.get('bin_families', {}).get(cls or '', rules.get('bin_families', {}).get('default', ['wood']))
    for a, v in library['items'].items():
        if v.get('family', 'wood') not in fam:
            continue
        if bin_classes and v.get('pattern_class', 'straight') not in bin_classes:
            continue
        d = _de(tone_lab, v['lab'])
        if best is None or d < best[0]:
            best = (d, a, v)
    if best is None:
        return {'bin': None, 'note': f'нет бинов семейств {fam} и классов {bin_classes}'}
    mx = rules.get('library_max_de00')
    if mx is not None and best[0] > mx:
        return {'bin': 'flat', 'dE00': 0.0, 'nearest': best[1], 'nearest_dE00': round(best[0], 1), 'note': f'ближайший бин дальше {mx} ΔE00 от тона — плоский тон, рисунок не рисуем'}
    return {'bin': best[1], 'dE00': round(best[0], 1), 'lab': best[2]['lab'], 'grain_axis': best[2].get('grain_axis'), 'tile_cm': best[2].get('tile_cm'), 'family': best[2].get('family', 'wood'), 'pattern_class': best[2].get('pattern_class')}


# ---------------------------------------------------------------- голоса по прогону -------------------------------
def _levels(tx, cfg: dict) -> dict:
    """Тексели «верха» (нормаль вверх, верхний уровень), вертикальные и границы по высоте (кадр куба: Y вверх)."""
    up = tx.N[:, 1] > cfg['cos_top']
    if up.sum() == 0:
        return {}
    ytop = float(np.quantile(tx.Q[up, 1], cfg['top_level_q']))
    top = up & (tx.Q[:, 1] > ytop - cfg['top_level_tol'])
    return {'up': up, 'top': top, 'ytop': ytop, 'ymin': float(tx.Q[:, 1].min()), 'ymax': float(tx.Q[:, 1].max())}


def rim_cut(q, lab, sel, ytop, cfg: dict):
    """Полоса `edge` — кромка плиты верха. Если на этапе 3 плита и корпус — одна часть, а под светлой плитой тёмный фасад (комод с контрастным верхом), в полосу попадает фасад и голос берёт его тон.
    Общее правило (не по товару): идём от верха вниз слоями `rim_bin`; опорный цвет — медиана первых `rim_ref_texels` текселей; первый слой (≥ `rim_bin_min` текселей), чья медиана ушла от опорной больше `rim_de00` (ΔE00),
    — начало фасада: всё ниже него из голоса убираем. `rim_de00` ≤ 0 — правило выключено. → (маска, глубина среза в единицах кадра | None)."""
    de0 = float(cfg.get('rim_de00', 0) or 0)
    idx = np.flatnonzero(sel)
    if de0 <= 0 or len(idx) < 2 * cfg['rim_ref_texels']:
        return sel, None
    layer = (np.maximum(ytop - q[idx], 0.0) / cfg['rim_bin']).astype(int)
    ref, got = None, 0
    for li in range(int(layer.max()) + 1):
        m = layer == li
        n = int(m.sum())
        if ref is None:
            got += n
            if got >= cfg['rim_ref_texels']:
                ref = np.median(lab[idx[layer <= li]], axis=0)
            continue
        if n < cfg['rim_bin_min']:
            continue
        if _de(np.median(lab[idx[m]], axis=0), ref) > de0:
            out = np.zeros_like(sel)
            out[idx[layer < li]] = True
            return out, li * cfg['rim_bin']
    return sel, None


def rim_split(q, lab, edge, plane, ytop, cfg: dict):
    """Один срез на оба голоса верха: плита и фасад — одна часть, поэтому и полоса `edge`, и полоса `plane` (вертикальные тексели верхней трети) могут захватить фасад под светлой плитой.
    Глубина считается на объединении (опора — самые верхние тексели), ниже неё в голоса ничего не берём. → (edge, plane, глубина | None)."""
    both, depth = rim_cut(q, lab, edge | plane, ytop, cfg)
    return edge & both, plane & both, depth


def _real_known(run_dir: str, n: int):
    """Маски «взято с фото» этапа 6 (`06-visible/known.png`, known1.png…) — настоящий вход голосов. Нет файла — (None, None)."""
    from PIL import Image
    out = []
    for i in range(n):
        fp = os.path.join(run_dir, '06-visible', 'known.png' if i == 0 else f'known{i}.png')
        if not os.path.exists(fp):
            return None, None
        out.append(np.asarray(Image.open(fp).convert('L')) > 127)
    return out, 'stage06_known_png'


def analyze(run_dir: str, card: dict | None, rules: dict | None = None, filled_glb: str | None = None, photo: str | None = None) -> dict:
    """Голоса и решение для одного прогона (папка со стадиями 01/03/06/07). Только чтение; возвращает отчёт и данные для кадра."""
    import tex_coverage as TC
    import tex_fill as TF
    rules = rules or load_rules()
    vis = os.path.join(run_dir, '06-visible', 'visible.glb')
    geoms = TC.load_geoms(vis)
    known, known_src = _real_known(run_dir, len(geoms))
    if known is None:                                                         # нет known.png: только геометрическая видимость с запасных ракурсов — на невидимом верху это заливка, не фото (урок Киннера 21.11)
        known, known_src = TF.known_from_photo(geoms), 'geometry_only'
    roles = {}
    pj = os.path.join(run_dir, '03-parts', 'parts.json')
    if os.path.exists(pj):
        with open(pj, encoding='utf-8') as f:
            roles = {p['id']: p.get('role') for p in json.load(f).get('parts', [])}
    parts_npz = os.path.join(run_dir, '03-parts', 'parts.npz')
    parts = TF.parts_from_npz(parts_npz, geoms)[0] if os.path.exists(parts_npz) else None
    draft = None
    dg = os.path.join(run_dir, '01-trellis', 'model.glb')
    if os.path.exists(dg):
        draft = TF.draft_texels(geoms, TC.load_geoms(dg), None)
    return analyze_data(geoms, known, known_src, parts, roles, draft, card, rules, photo)


def analyze_data(geoms: list, known: list, known_src: str, parts, roles: dict, draft, card: dict | None, rules: dict, photo: str | None = None) -> dict:
    """Голоса и решение по данным в памяти (без чтения папки прогона): `analyze` и этап 07 (`stage07`) зовут одно и то же. parts — части граней по геометриям | None; roles — {id части: роль};
    draft — `tex_fill.draft_texels` (родной цвет TRELLIS) | None."""
    import tex_coverage as TC
    import tex_fill as TF
    cfg, dcfg = dict(rules['geometry']), rules['decision']
    dims = card_dims(card)
    if dims['thickness_cm'] and dims['length_cm']:
        cfg['edge_band'] = max(cfg['edge_band_min'], min(cfg['edge_band'], cfg['edge_band_k'] * dims['thickness_cm'] / dims['length_cm']))
    ctr, size = TF.frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    P = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
    bg_lab = np.asarray(TC.rgb2lab(np.asarray([rules['background_rgb']], np.uint8)))[0]
    E, PL, TR, OV, top_all, texs = [], [], [], [], [], []
    RIM = []
    top_part_roles, n_top = {}, 0
    for gi, g in enumerate(geoms):
        T = TF._grid(g)
        tx = TF.Tex(g, P[offs[gi]:offs[gi + 1]], T, None if parts is None else parts[gi])
        lv = _levels(tx, cfg)
        if not lv:
            continue
        rgb = np.asarray(g['tex'])[..., :3].reshape(-1, 3)[tx.ti]
        lab = TC.rgb2lab(rgb)
        kn = known[gi].reshape(-1)[tx.ti]
        notbg = np.array([True] * len(lab)) if len(lab) == 0 else (TC.de2000_v(lab, np.broadcast_to(bg_lab, lab.shape)) >= dcfg['bg_de00'])
        vert = np.abs(tx.N[:, 1]) < cfg['cos_vert']
        band = tx.Q[:, 1] > lv['ytop'] - cfg['edge_band']
        legs = np.isin(tx.part, [p for p, r in roles.items() if r in ('legs', 'handles', 'shade')]) if roles else np.zeros(len(lab), bool)
        same = np.isin(tx.part, np.unique(tx.part[lv['top']]))                    # «та же часть»: этап 3 развёл плиту верха и царгу/корпус — их цвета не одно и то же (Киннер: царга бежевая, верх медовый)
        edge = kn & vert & band & (tx.Q[:, 1] <= lv['ytop'] + cfg['edge_above']) & notbg & ~legs & same
        plane = kn & vert & (tx.Q[:, 1] > lv['ymin'] + cfg['plane_from'] * (lv['ymax'] - lv['ymin'])) & ~band & notbg & ~legs & same
        n_edge0, n_plane0 = int(edge.sum()), int(plane.sum())
        edge, plane, rim_depth = rim_split(tx.Q[:, 1], lab, edge, plane, lv['ytop'], cfg)
        RIM.append({'gi': gi, 'cut_depth': None if rim_depth is None else round(float(rim_depth), 4), 'edge_texels': int(edge.sum()), 'plane_texels': int(plane.sum()), 'edge_before': n_edge0, 'plane_before': n_plane0})
        other_vert = kn & vert & ~same & notbg & ~legs                              # соседняя часть (царга/корпус): только в отчёт, голосом не служит
        OV.append(lab[other_vert])
        E.append(lab[edge])
        PL.append(lab[plane])
        top = lv['top']
        n_top += int(top.sum())
        for p in np.unique(tx.part[top]):
            top_part_roles[int(p)] = roles.get(int(p))
        if draft is not None:
            dl = draft['lab'][gi].reshape(-1, 3)[tx.ti]
            dok = draft['ok'][gi].reshape(-1)[tx.ti]
            sel = top & dok
            if sel.any():
                isbg = TC.de2000_v(dl[sel], np.broadcast_to(bg_lab, dl[sel].shape)) < dcfg['bg_de00']
                TR.append((dl[sel][~isbg], int(sel.sum()), int(isbg.sum())))
        top_all.append({'gi': gi, 'tx': tx, 'top': top, 'kn': kn, 'lab': lab})
        texs.append(np.asarray(g['tex']).copy())
    cat = lambda L: np.concatenate(L) if L else np.zeros((0, 3))
    ed, pl = cat(E), cat(PL)
    ov = cat(OV)
    voices = {'edge': {'lab': TF.tone_of(ed, TF.FILL).tolist() if len(ed) else None, 'n': int(len(ed))},
              'plane': {'lab': TF.tone_of(pl, TF.FILL).tolist() if len(pl) else None, 'n': int(len(pl))}}
    if TR:
        good, tot, nbg = cat([t[0] for t in TR]), sum(t[1] for t in TR), sum(t[2] for t in TR)
        voices['trellis'] = {'lab': TF.tone_of(good, TF.FILL).tolist() if len(good) else None, 'n': int(len(good)), 'bg_share': nbg / max(tot, 1), 'n_all': int(tot),
                             'flat_std': float(good[:, 0].std()) if len(good) else None}
    else:
        voices['trellis'] = None
    cc = card_class(card, rules)
    voices['card'] = cc
    res = decide(voices, rules)
    lib_path = os.path.join(ROOT, rules['library'])
    pat_spec = card_pattern(card, rules)
    res['pattern_spec'] = pat_spec
    res['library'] = library_bin(res['tone_lab'], cc.get('group') or 'library', json.load(open(lib_path, encoding='utf-8')), rules, cc.get('class'), pat_spec['bin_classes']) if os.path.exists(lib_path) else {'bin': None, 'note': 'нет library.json'}
    res['other_part_vertical'] = {'n': int(len(ov)), 'lab': [round(float(x), 1) for x in TF.tone_of(ov, TF.FILL)] if len(ov) else None, 'note': 'вертикальные видимые тексели ДРУГИХ частей (царга/корпус); голосом не служат'}
    res['top_texels'] = n_top
    res['edge_rim'] = RIM
    res['known_source'] = known_src
    res['evidence_std_L'] = photo_band_std(photo, rules)
    res['evidence_source'] = 'photo_band' if res['evidence_std_L'] is not None else 'default'
    res['groove_dL'] = photo_groove_dL(photo, rules)
    res['groove_source'] = 'photo' if res['groove_dL'] is not None else 'fallback'
    res['card_dims'] = dict(dims, edge_band=round(cfg['edge_band'], 4))
    res['top_parts'] = {str(k): v for k, v in top_part_roles.items()}
    res['top_own_part'] = any(r == 'top' for r in top_part_roles.values())
    res['card_class'] = cc
    res['mode'] = rules['mode']
    return {'report': res, 'voices': voices, 'geoms': geoms, 'top_all': top_all, 'size': size, 'ctr': ctr}


# ---------------------------------------------------------------- кадр «было | гипотеза» --------------------------
def _fold_pattern(pat: np.ndarray, ov: int) -> np.ndarray:
    """Первые `ov` столбцов плитки смешиваются (smoothstep) с её последними `ov` столбцами (после них идёт продолжение «в начало»), последние `ov` отрезаются; то же по строкам. Разброс узора в полосе
    выравнивается (сумма независимых кусков). Результат короче на `ov` по каждой оси."""
    n = pat.shape[0]
    t = (np.arange(ov, dtype=np.float64) + 0.5) / ov
    w = t * t * (3.0 - 2.0 * t)                                           # вес «своего» куска: 0 у стыка → 1 на краю полосы
    k = np.sqrt(w * w + (1.0 - w) ** 2)

    def fold(a, ax):
        a = np.moveaxis(a, ax, 0)
        head, tail = a[:ov], a[n - ov:]
        sh = (ov,) + (1,) * (a.ndim - 1)
        mixed = (w.reshape(sh) * head + (1.0 - w.reshape(sh)) * tail) / k.reshape(sh)
        return np.moveaxis(np.concatenate([mixed, a[ov:n - ov]], axis=0), 0, ax)
    return fold(fold(pat, 1), 0)


def seamless_pattern(pat: np.ndarray, overlap, step: int | None = None) -> np.ndarray:
    """Бесшовная плитка узора (T-187/7, правило директора 22.11 «узор без видимых стыков»): перекрытие `overlap` = [мин, макс] доли стороны (8–16 %) — берётся то из диапазона, где скачок на стыке
    `seam_jump` минимален (стык уходит от сучка/края доски); не зеркало — волокно не отражается. Узор 512² — JPEG с блоками 8×8: перекрытие подбирается так, чтобы стык был на середине блока, не на его границе
    (иначе мерка видит ступеньку блока, а не шов). Плитка короче на перекрытие — период берётся по `shape` результата. Число вместо диапазона — одно значение; 0 — выключено."""
    n = pat.shape[0]
    lo, hi = (overlap if isinstance(overlap, (list, tuple)) else (overlap, overlap))
    if hi <= 0 or n < 16:
        return pat
    st = step or (8 if n % 8 == 0 else max(1, n // 64))
    cand = sorted({int(round(f * n)) for f in np.linspace(lo, hi, 9)})
    if n % 8 == 0:
        cand = sorted({c + (n - c - 4) % 8 for c in cand})                 # стык (n − ov) ≡ 4 (mod 8)
    cand = [c for c in cand if 2 <= c <= n // 3]
    if not cand:
        return pat
    best = min(cand, key=lambda c: seam_jump(_fold_pattern(pat, c)))
    return _fold_pattern(pat, best)


def seam_jump(pat: np.ndarray) -> float:
    """Мерка стыка плитки: средний |скачок L| через стык / средний |скачок L| между соседними столбцами (строками) внутри плитки; максимум по осям. ≤1,3 — стыка не видно (правило владельца-директора 22.11)."""
    L = pat[:, :, 0]
    out = []
    for a in (L, L.T):
        inner = np.abs(np.diff(a, axis=1)).mean()
        seam = np.abs(a[:, 0] - a[:, -1]).mean()
        out.append(seam / max(inner, 1e-9))
    return float(max(out))


def gutter_into(img: np.ndarray, ti_all, painted_idx, gutter: int) -> int:
    """Желоб после покраски верха (T-187/7: видимая линия на столе у шва островков UV): `fill()` дублирует цвет островка в `gutter` пикселей вокруг него ДО хуков, а хук красит верх позже — желоб у
    перекрашенных текселей оставался старым, билинейная выборка у шва брала его цвет. Здесь: непокрытые текселы атласа в пределах `gutter` от ближайшего ПЕРЕКРАШЕННОГО тексела получают его цвет.
    `img` (T,T,C) правится на месте; `ti_all` — плоские индексы покрытых текселей геометрии, `painted_idx` — перекрашенных. → число текселей желоба."""
    from scipy.ndimage import distance_transform_edt
    t = img.shape[0]
    occ = np.zeros(t * t, bool)
    occ[np.asarray(ti_all)] = True
    pm = np.zeros(t * t, bool)
    pm[np.asarray(painted_idx)] = True
    occ, pm = occ.reshape(t, t), pm.reshape(t, t)
    if gutter <= 0 or not pm.any():
        return 0
    dist, (iy, ix) = distance_transform_edt(~occ, return_indices=True)
    g = (~occ) & (dist <= gutter) & pm[iy, ix]
    img[g, :3] = img[iy[g], ix[g], :3]
    return int(g.sum())


def hypothesis_textures(an: dict, rules: dict, base_texs: list, length_cm: float, library_dir: str | None = None) -> list:   # length_cm — габарит для подписи; масштаб узора — по плитке бина
    """Копия текстур с верхом, закрашенным гипотезой: тон (Lab) + узор бина (отклонение его Lab от среднего), волокна вдоль длинной стороны. Известные по фото тексели не трогаем."""
    import tex_coverage as TC
    import tex_fill as TF
    from PIL import Image
    rep = an['report']
    out = [t.copy() for t in base_texs]
    tone = rep.get('tone_lab')
    if tone is None and rules.get('unknown_policy', 'keep') == 'keep':
        rep['applied'] = 'нет: тона нет (unknown / не дерево) — верх не тронут'
        return out
    tone = np.asarray(tone if tone is not None else rules['neutral_top_lab'], np.float64)
    lib = rep.get('library') or {}
    pat = None
    if lib.get('bin') not in (None, 'flat') and library_dir:
        p = os.path.join(library_dir, lib['bin'] + '.jpg')                # узор бина 512×512 (`top_library_pat512.py`; rules `library_pat`) — один источник и локально, и на Salad
        if os.path.exists(p):
            im = np.asarray(Image.open(p).convert('RGB').resize((512, 512)), np.uint8)
            L = TC.rgb2lab(im.reshape(-1, 3)).reshape(512, 512, 3)
            pat = L - L.reshape(-1, 3).mean(0)
            ev, pr_ = rep.get('evidence_std_L'), rules['pattern']
            amp = pr_['amp_default'] if ev is None else float(np.clip(ev / max(float(pat[:, :, 0].std()), 1e-6), pr_['amp_min'], 1.0))
            rep['pattern_amp'] = round(amp, 2)
            pat = seamless_pattern(pat * amp, pr_.get('seam_overlap', 0.0))          # плитка без стыков (амплитуда до смешивания: полоса честно выравнивается)
            if lib.get('grain_axis') == 'v':
                pat = np.transpose(pat, (1, 0, 2))
    tile = (lib.get('tile_cm') or [None])[0] or rules['fallback_tile_cm']
    tr = next((c for c in rep.get('candidates', []) if c.get('voice') == 'trellis' and c.get('used') and c.get('lab')), None)
    retint = bool(rules.get('retint_native', True)) and tr is not None          # голос trellis участвует (верх не плоский) и согласен (иначе тона не было бы) — рисунок модели настоящий
    if retint:
        delta = tone - np.asarray(tr['lab'], np.float64)
        rep['applied'] = f"сдвиг тона существующего верха на ΔLab {np.round(delta, 1).tolist()} (узор модели не заменён)"
    painted: dict = {}
    for t in an['top_all']:
        tx, top, kn = t['tx'], t['top'], t['kn']
        sel = top & ~kn
        if not sel.any():
            continue
        if retint:
            img = out[t['gi']]
            flat = img.reshape(-1, img.shape[2])
            idx = tx.ti[sel]
            cur = TC.rgb2lab(flat[idx, :3].astype(np.uint8))
            flat[idx, :3] = TF.lab2rgb(cur + delta)
            out[t['gi']] = flat.reshape(img.shape)
            continue
        Q = tx.Q[sel]
        # длинная ось верха — по разбросу точек в плоскости X–Z (кадр куба)
        xz = Q[:, [0, 2]] - Q[:, [0, 2]].mean(0)
        w, v = np.linalg.eigh(np.cov(xz.T)) if len(xz) > 3 else (np.ones(2), np.eye(2))
        ax = v[:, 1]
        u = (xz @ ax) * an['size'] * 100.0 / tile                           # сантиметры вдоль длинной стороны → доли плитки
        s = (xz @ np.array([-ax[1], ax[0]])) * an['size'] * 100.0 / tile
        lab = np.tile(tone, (int(sel.sum()), 1))
        planks = rep.get('pattern_spec', {}).get('layout') == 'planks'
        if planks:                                                          # планки: индекс планки вдоль ширины, свой сдвиг узора и тон на планку, шов между ними
            pr = rules['pattern']
            dm = rep.get('card_dims') or {}
            wcm = dm.get('width_cm') or 90.0
            n_pl = max(1, int(round(wcm / pr['plank_target_cm'])))
            plank_cm = wcm / n_pl
            s_cm = s * tile
            s_cm = s_cm - s_cm.min()
            pi = np.floor(s_cm / plank_cm).astype(int)
            frac = (s_cm / plank_cm) - pi
            h = (pi * 2654435761) % 4294967296                                # детерминированный «случайный» сдвиг по индексу планки
            u = u + (h % 1000) / 1000.0
            s = (s_cm - pi * plank_cm) / tile                               # внутри планки — своя полоса узора (волокно идёт вдоль неё)
            jit = (((h >> 8) % 1000) / 500.0 - 1.0) * pr['plank_tone_jitter_L']
            groove = (frac * plank_cm < pr['plank_groove_cm']) | (frac * plank_cm > plank_cm - pr['plank_groove_cm'] / 2)
        if pat is not None:
            m = pat.shape[0]                                                # сторона плитки (после бесшовной обработки короче 512)
            iu = (np.floor((u % 1.0) * m)).astype(int) % m
            iv = (np.floor((s % 1.0) * m)).astype(int) % m
            lab = lab + pat[iv, iu]
        if planks:
            lab[:, 0] += jit
            gd = rep.get('groove_dL')
            lab[groove, 0] -= rules['pattern']['groove']['fallback_dL'] if gd is None else gd
        rgb = TF.lab2rgb(lab)
        img = out[t['gi']]
        flat = img.reshape(-1, img.shape[2]) if img.ndim == 3 else None
        idx = tx.ti[sel]
        flat[idx, :3] = rgb
        out[t['gi']] = flat.reshape(img.shape)
        painted.setdefault(t['gi'], []).append((tx.ti, idx))
    gut = int(TF.FILL.get('gutter', 0))
    rep['gutter_texels'] = sum(gutter_into(out[gi], np.concatenate([a for a, _b in lst]), np.concatenate([b for _a, b in lst]), gut) for gi, lst in painted.items())
    return out


# ---------------------------------------------------------------- этап 07: верх по Ш3в ----------------------------
CONF_RANK = {'none': 0, 'low': 1, 'medium': 2, 'high': 3}


def choose_top_tone(synth_lab, top_lab, S: dict) -> dict:
    """Тон верха без фото (T-28/1): кандидат 06-synth (тон с острого угла) против Ш3в (по кромке/голосам). Берём synth, если |ΔL| к Ш3в ≤ `max_dL` (одно мнение — не спорим) ИЛИ synth светлый
    (L ≥ `light_min_L`) и Ш3в темнее него больше чем на `light_max_darker` (светлое не темнеет: белая столешница 18286 L100 → Ш3в 88); иначе Ш3в. Чистая функция.
    → {'use': 'synth'|'top', 'lab': [...], 'why': str, 'dL': float}"""
    if not S.get('enabled', False) or synth_lab is None or top_lab is None:
        return {'use': 'top', 'lab': None if top_lab is None else [float(x) for x in top_lab], 'why': 'кандидата synth нет или правило выключено', 'dL': None}
    sl, tl = float(synth_lab[0]), float(top_lab[0])
    dl = sl - tl
    if abs(dl) <= float(S['max_dL']):
        return {'use': 'synth', 'lab': [float(x) for x in synth_lab], 'why': f'|ΔL| {abs(dl):.1f} ≤ {S["max_dL"]}: synth и Ш3в близки — берём synth', 'dL': round(dl, 1)}
    if sl >= float(S['light_min_L']) and dl > float(S['light_max_darker']):
        return {'use': 'synth', 'lab': [float(x) for x in synth_lab], 'why': f'synth светлый (L {sl:.0f} ≥ {S["light_min_L"]}), Ш3в темнее на {dl:.1f} > {S["light_max_darker"]} — светлое не темнеет', 'dL': round(dl, 1)}
    return {'use': 'top', 'lab': [float(x) for x in top_lab], 'why': f'ΔL {dl:+.1f}: расхождение, не светлый случай — Ш3в', 'dL': round(dl, 1)}


def synth_top_lab(an: dict, synth, min_texels: int, diag: dict | None = None):
    """Медиана Lab 06-цвета у текселей верха без фото, которые 06 закрасил по тону с острого угла (synth-маска). synth = (маски по геометриям, текстуры 06). → (lab, n) | None."""
    import tex_coverage as TC
    if not synth:
        return None
    masks, tex06 = synth
    if diag is not None:
        diag['n_masks'] = len(masks)
        diag['n_synth_all'] = int(sum(int(np.asarray(m).sum()) for m in masks))
    labs = []
    for t in an['top_all']:
        gi = t['gi']
        if gi >= len(masks):
            continue
        sel = np.asarray(masks[gi], bool).reshape(-1)[t['tx'].ti] & t['top'] & ~t['kn']
        if sel.any():
            flat = np.asarray(tex06[gi]).reshape(-1, np.asarray(tex06[gi]).shape[-1])[:, :3]
            labs.append(TC.rgb2lab(flat[t['tx'].ti][sel].astype(np.uint8)))
    if diag is not None:
        diag['n_synth_top_hidden'] = int(sum(len(x) for x in labs))
    if not labs:
        return None
    lab = np.concatenate(labs)
    if len(lab) < int(min_texels):
        return None
    return np.median(lab, axis=0), int(len(lab))


def stage07_gate(res: dict, rules: dict) -> tuple:
    """Правило на ВСЕ товары (T-187/7): верх красим тоном Ш3в, если решение дало тон и его уверенность ≥ `stage07.min_confidence` (rules/top-prior.json); иначе верх остаётся как есть
    (донор / тон своей зоны этапа 07). → (применять, причина). Чистая функция."""
    S = rules.get('stage07', {})
    if not S.get('enabled', False):
        return False, 'stage07.enabled = false'
    if res.get('tone_lab') is None:
        return False, f"тона нет ({res.get('type')}: {res.get('reason')})"
    grp = (res.get('card_class') or {}).get('group')
    if grp not in S.get('groups', ['library', 'decor']):
        return False, f"класс верха по карточке «{(res.get('card_class') or {}).get('class')}» (группа {grp}) — Ш3в только для дерева/декора под дерево"
    need = S.get('min_confidence', 'medium')
    if CONF_RANK.get(res.get('confidence'), 0) < CONF_RANK[need]:
        return False, f"уверенность {res.get('confidence')} < {need}"
    return True, f"уверенность {res.get('confidence')} ≥ {need}"


def _top_tones(an: dict, texs: list, tag: str) -> dict:
    """Мерка «было→стало» по верху (в отчёт 07): медиана Lab ВИДИМЫХ с фото текселей верха (`photo_top_lab`, n) и невидимых (`hidden_<tag>_lab`); dE00 невидимого к видимому — `hidden_<tag>_dE_to_photo`
    (видимых текселей верха мало — читателю смотреть `photo_top_n`)."""
    import tex_coverage as TC
    ph, hid = [], []
    for t in an['top_all']:
        img = np.asarray(texs[t['gi']])
        flat = img.reshape(-1, img.shape[-1])[:, :3]
        lab = TC.rgb2lab(flat[t['tx'].ti][t['top']].astype(np.uint8))
        kn = t['kn'][t['top']]
        ph.append(lab[kn])
        hid.append(lab[~kn])
    ph, hid = (np.concatenate(x) if x else np.zeros((0, 3)) for x in (ph, hid))
    out = {'photo_top_n': int(len(ph)), 'photo_top_lab': None if not len(ph) else [round(float(x), 1) for x in np.median(ph, axis=0)],
           f'hidden_{tag}_lab': None if not len(hid) else [round(float(x), 1) for x in np.median(hid, axis=0)]}
    if len(ph) and len(hid):
        out[f'hidden_{tag}_dE_to_photo'] = round(_de(np.median(hid, axis=0), np.median(ph, axis=0)), 1)
    return out


def stage07(geoms: list, tex_after: list, known: list, parts, roles: dict | None, draft, card: dict | None = None, photo: str | None = None, rules: dict | None = None,
            library_dir: str | None = None, synth=None) -> tuple:
    """Хук этапа 07 (T-187/7; канон paint-photo-fill-01, строка 7: «верх — Ш3в»). Верх (горизонтальная плита, нормаль вверх) — только тексели, которых нет на фото (`top & ~known`; known не меняется).
    → (текстуры, отчёт). Отчёт: `top_source` — photo_top (весь верх с фото) | no_top (верха нет) | same_part_inference | trellis_prior | as_before (уверенности нет — как делал 07) и поля решения."""
    import tex_coverage as TC  # noqa: F401
    rules = rules or load_rules()
    an = analyze_data(geoms, known, 'stage07', parts, roles or {}, draft, card, rules, photo)
    res = an['report']
    n_top = int(sum(int(t['top'].sum()) for t in an['top_all']))
    n_hid = int(sum(int((t['top'] & ~t['kn']).sum()) for t in an['top_all']))
    rep = {'top_source': 'as_before', 'applied': False, 'min_confidence': rules.get('stage07', {}).get('min_confidence'), 'source': res.get('source'), 'type': res.get('type'),
           'confidence': res.get('confidence'), 'tone_lab': res.get('tone_lab'), 'reason': res.get('reason'), 'route': res.get('route'), 'n_top': n_top, 'n_top_hidden': n_hid,
           'texels_changed': 0, 'top_class': {k: (res.get('card_class') or {}).get(k) for k in ('class', 'group')}, 'library': (res.get('library') or {}).get('bin'), 'other_material_hint': res.get('other_material_hint')}
    rep.update(_top_tones(an, tex_after, 'before'))
    if n_top == 0:
        rep['top_source'] = 'no_top'
        return [np.asarray(t) for t in tex_after], rep
    if n_hid == 0:
        rep['top_source'] = 'photo_top'
        return [np.asarray(t) for t in tex_after], rep
    ok, why = stage07_gate(res, rules)
    rep['gate'] = why
    if not ok:
        return [np.asarray(t) for t in tex_after], rep
    SC = rules.get('stage07', {}).get('synth_candidate') or {}
    if not SC.get('enabled', False) or synth is None:
        rep['synth_candidate'] = {'skipped': 'правило выключено' if not SC.get('enabled', False) else 'маски synth не переданы (cfg.synth_dir)'}
    if SC.get('enabled', False) and synth is not None:                       # T-28/1: тон-кандидат 06-synth против Ш3в (светлое не темнеет)
        _dg = {}
        sy = synth_top_lab(an, synth, int(SC.get('min_texels', 500)), _dg)
        src = 'synth'
        if sy is None and rep.get('photo_top_lab') and int(rep.get('photo_top_n') or 0) >= int(SC.get('photo_min_texels', 10)):
            sy = (np.asarray(rep['photo_top_lab'], float), int(rep['photo_top_n']))                # synth нет: кандидат — немногие фото-тексели верха (светлое не темнеет)
            src = 'photo'
        if sy is None:
            rep['synth_candidate'] = dict(_dg, skipped=f'synth-текселей верха без фото < {SC.get("min_texels", 500)} или нет; фото-текселей верха < {SC.get("photo_min_texels", 10)}')
        if sy is not None:
            ch = choose_top_tone(sy[0], res['tone_lab'], SC)
            rep['synth_candidate'] = {'source': src, 'synth_lab': [round(float(x), 1) for x in sy[0]], 'n': sy[1], 'top_lab': [round(float(x), 1) for x in res['tone_lab']], 'use': ch['use'], 'why': ch['why'], 'dL': ch['dL']}
            if ch['use'] == 'synth':
                res['tone_lab'] = [round(float(x), 1) for x in ch['lab']]
                rep['tone_lab'] = res['tone_lab']
    r2 = dict(rules, retint_native=bool(rules.get('stage07', {}).get('retint_native', False)), unknown_policy='keep')
    lib = library_dir if library_dir is not None else os.path.join(ROOT, rules['library_pat'])
    out = hypothesis_textures(an, r2, [np.asarray(t) for t in tex_after], rules['fallback_length_cm'], lib if os.path.isdir(lib) else None)
    ta = _top_tones(an, out, 'after')
    S = rules.get('stage07', {})
    db, da = rep.get('hidden_before_dE_to_photo'), ta.get('hidden_after_dE_to_photo')
    if rep['photo_top_n'] >= S.get('min_photo_top', 50) and db is not None and da is not None and da > db + S.get('photo_worse_de00', 0.0):
        rep.update(gate=f'верх виден на фото ({rep["photo_top_n"]} тексел.): Ш3в дальше от фото (ΔE00 {da} > {db}) — оставлено как есть', hidden_after_dE_to_photo=da, rejected_by_photo=True)
        return [np.asarray(t) for t in tex_after], rep
    rep.update(ta)
    ch = int(sum(int((np.asarray(o)[..., :3] != np.asarray(b)[..., :3]).any(axis=-1).sum()) for o, b in zip(out, tex_after)))
    rep.update(pattern='library' if res.get('pattern_amp') is not None else 'tone_only', applied=True, top_source=res['source'], texels_changed=ch, pattern_amp=res.get('pattern_amp'), applied_note=res.get('applied'), gutter_texels=res.get('gutter_texels'))
    return out, rep


def render_pair(geoms, before, after, path: str, elevation: float = 55.0, azimuth: float = 0.0, res: int = 720) -> None:
    import tex_fill as TF
    from PIL import Image
    a = TF.render_ortho(geoms, before, azimuth, res, 1.25, elevation)
    b = TF.render_ortho(geoms, after, azimuth, res, 1.25, elevation)
    Image.fromarray(np.concatenate([a, np.full((a.shape[0], 12, 3), 255, np.uint8), b], axis=1)).save(path)


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('dry')
    d.add_argument('run')
    d.add_argument('--photo', default='', help='фото каталога (RGBA/белый фон): контраст узора из его верхней полосы; нет — запасной коэффициент')
    d.add_argument('--card', default='')
    d.add_argument('--out', default='')
    d.add_argument('--length-cm', type=float, default=0.0)
    d.add_argument('--rules', default='', help='файл правил вместо rules/top-prior.json (например, с rim_de00: 0 — прогон «как было»)')
    d.add_argument('--lib-pat', default='', help='папка узоров бинов 512×512 (<бин>.jpg); по умолчанию rules `library_pat`')
    a = ap.parse_args(argv)
    rules = load_rules(a.rules) if a.rules else load_rules()
    card = json.loads(a.card) if a.card else None
    an = analyze(a.run, card, rules, photo=a.photo or None)
    out = a.out or os.path.join(a.run, '07-fill')
    os.makedirs(out, exist_ok=True)
    rep = {k: v for k, v in an['report'].items()}
    with open(os.path.join(out, 'top_prior.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    import tex_coverage as TC
    fg = os.path.join(a.run, '07-fill', 'filled.glb')
    base = TC.load_geoms(fg if os.path.exists(fg) else os.path.join(a.run, '06-visible', 'visible.glb'))
    before = [np.asarray(g['tex']).copy() for g in base]
    lib_dir = os.path.expanduser(a.lib_pat) if a.lib_pat else os.path.join(ROOT, rules['library_pat'])
    after = hypothesis_textures(an, rules, before, a.length_cm or rules['fallback_length_cm'], lib_dir)
    render_pair(base, before, after, os.path.join(out, 'top_prior_frame.png'))
    rep['pattern_amp'] = an['report'].get('pattern_amp')
    rep['before_source'] = '07-fill/filled.glb' if os.path.exists(fg) else '06-visible/visible.glb (07 не запускался)'
    with open(os.path.join(out, 'top_prior.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    print(json.dumps({k: rep[k] for k in ('source', 'type', 'tone_lab', 'confidence', 'agree', 'reason', 'library', 'other_material_hint', 'trellis_unknown')}, ensure_ascii=False, default=str))
    for c in rep['candidates']:
        print('  ', c)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

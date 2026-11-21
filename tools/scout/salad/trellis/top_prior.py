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


def card_dims(card: dict | None) -> dict:
    """Толщина верха и наибольший габарит из карточки, см: «Толщина столешницы 1 см», «160x90» в названии/модификации. Нет — None (полоса кромки по умолчанию)."""
    out = {'thickness_cm': None, 'length_cm': None}
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


def library_bin(tone_lab, kind: str, library: dict, rules: dict, cls: str | None = None) -> dict:
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
        d = _de(tone_lab, v['lab'])
        if best is None or d < best[0]:
            best = (d, a, v)
    if best is None:
        return {'bin': None, 'note': f'нет бинов семейств {fam}'}
    return {'bin': best[1], 'dE00': round(best[0], 1), 'lab': best[2]['lab'], 'grain_axis': best[2].get('grain_axis'), 'tile_cm': best[2].get('tile_cm'), 'family': best[2].get('family', 'wood')}


# ---------------------------------------------------------------- голоса по прогону -------------------------------
def _levels(tx, cfg: dict) -> dict:
    """Тексели «верха» (нормаль вверх, верхний уровень), вертикальные и границы по высоте (кадр куба: Y вверх)."""
    up = tx.N[:, 1] > cfg['cos_top']
    if up.sum() == 0:
        return {}
    ytop = float(np.quantile(tx.Q[up, 1], cfg['top_level_q']))
    top = up & (tx.Q[:, 1] > ytop - cfg['top_level_tol'])
    return {'up': up, 'top': top, 'ytop': ytop, 'ymin': float(tx.Q[:, 1].min()), 'ymax': float(tx.Q[:, 1].max())}


def analyze(run_dir: str, card: dict | None, rules: dict | None = None, filled_glb: str | None = None) -> dict:
    """Голоса и решение для одного прогона (папка со стадиями 01/03/06/07). Только чтение; возвращает отчёт и данные для кадра."""
    import tex_coverage as TC
    import tex_fill as TF
    rules = rules or load_rules()
    cfg, dcfg = dict(rules['geometry']), rules['decision']
    dims = card_dims(card)
    if dims['thickness_cm'] and dims['length_cm']:
        cfg['edge_band'] = max(cfg['edge_band_min'], min(cfg['edge_band'], cfg['edge_band_k'] * dims['thickness_cm'] / dims['length_cm']))
    vis = os.path.join(run_dir, '06-visible', 'visible.glb')
    geoms = TC.load_geoms(vis)
    known = TF.known_from_photo(geoms)
    ctr, size = TF.frame_of(geoms)
    offs = np.cumsum([0] + [len(g['V']) for g in geoms])
    P = (np.concatenate([np.asarray(g['V'], np.float64) for g in geoms]) - ctr) / size
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
    bg_lab = np.asarray(TC.rgb2lab(np.asarray([rules['background_rgb']], np.uint8)))[0]
    E, PL, TR, OV, top_all, texs = [], [], [], [], [], []
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
    res['library'] = library_bin(res['tone_lab'], cc.get('group') or 'library', json.load(open(lib_path, encoding='utf-8')), rules, cc.get('class')) if os.path.exists(lib_path) else {'bin': None, 'note': 'нет library.json'}
    res['other_part_vertical'] = {'n': int(len(ov)), 'lab': [round(float(x), 1) for x in TF.tone_of(ov, TF.FILL)] if len(ov) else None, 'note': 'вертикальные видимые тексели ДРУГИХ частей (царга/корпус); голосом не служат'}
    res['top_texels'] = n_top
    res['card_dims'] = dict(dims, edge_band=round(cfg['edge_band'], 4))
    res['top_parts'] = {str(k): v for k, v in top_part_roles.items()}
    res['top_own_part'] = any(r == 'top' for r in top_part_roles.values())
    res['card_class'] = cc
    res['mode'] = rules['mode']
    return {'report': res, 'voices': voices, 'geoms': geoms, 'top_all': top_all, 'size': size, 'ctr': ctr}


# ---------------------------------------------------------------- кадр «было | гипотеза» --------------------------
def hypothesis_textures(an: dict, rules: dict, base_texs: list, length_cm: float, library_dir: str | None = None) -> list:   # length_cm — габарит для подписи; масштаб узора — по плитке бина
    """Копия текстур с верхом, закрашенным гипотезой: тон (Lab) + узор бина (отклонение его Lab от среднего), волокна вдоль длинной стороны. Известные по фото тексели не трогаем."""
    import tex_coverage as TC
    import tex_fill as TF
    from PIL import Image
    rep = an['report']
    out = [t.copy() for t in base_texs]
    tone = rep.get('tone_lab')
    tone = np.asarray(tone if tone is not None else rules['neutral_top_lab'], np.float64)
    lib = rep.get('library') or {}
    pat = None
    if lib.get('bin') not in (None, 'flat') and library_dir:
        p = os.path.join(library_dir, lib['bin'], 'diff.jpg')
        if os.path.exists(p):
            im = np.asarray(Image.open(p).convert('RGB').resize((512, 512)), np.uint8)
            L = TC.rgb2lab(im.reshape(-1, 3)).reshape(512, 512, 3)
            pat = L - L.reshape(-1, 3).mean(0)
            if lib.get('grain_axis') == 'v':
                pat = np.transpose(pat, (1, 0, 2))
    tile = (lib.get('tile_cm') or [None])[0] or rules['fallback_tile_cm']
    for t in an['top_all']:
        tx, top, kn = t['tx'], t['top'], t['kn']
        sel = top & ~kn
        if not sel.any():
            continue
        Q = tx.Q[sel]
        # длинная ось верха — по разбросу точек в плоскости X–Z (кадр куба)
        xz = Q[:, [0, 2]] - Q[:, [0, 2]].mean(0)
        w, v = np.linalg.eigh(np.cov(xz.T)) if len(xz) > 3 else (np.ones(2), np.eye(2))
        ax = v[:, 1]
        u = (xz @ ax) * an['size'] * 100.0 / tile                           # сантиметры вдоль длинной стороны → доли плитки
        s = (xz @ np.array([-ax[1], ax[0]])) * an['size'] * 100.0 / tile
        lab = np.tile(tone, (int(sel.sum()), 1))
        if pat is not None:
            iu = (np.floor((u % 1.0) * 512)).astype(int) % 512
            iv = (np.floor((s % 1.0) * 512)).astype(int) % 512
            lab = lab + pat[iv, iu]
        rgb = TF.lab2rgb(lab)
        img = out[t['gi']]
        flat = img.reshape(-1, img.shape[2]) if img.ndim == 3 else None
        idx = tx.ti[sel]
        flat[idx, :3] = rgb
        out[t['gi']] = flat.reshape(img.shape)
    return out


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
    d.add_argument('--card', default='')
    d.add_argument('--out', default='')
    d.add_argument('--length-cm', type=float, default=0.0)
    d.add_argument('--lib-raw', default='', help='папка со сканами бинов (<бин>/diff.jpg); по умолчанию data/flat3d/top-library/raw')
    a = ap.parse_args(argv)
    rules = load_rules()
    card = json.loads(a.card) if a.card else None
    an = analyze(a.run, card, rules)
    out = a.out or os.path.join(a.run, '07-fill')
    os.makedirs(out, exist_ok=True)
    rep = {k: v for k, v in an['report'].items()}
    with open(os.path.join(out, 'top_prior.json'), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, 'item') else str(o))
    import tex_coverage as TC
    fg = os.path.join(a.run, '07-fill', 'filled.glb')
    base = TC.load_geoms(fg if os.path.exists(fg) else os.path.join(a.run, '06-visible', 'visible.glb'))
    before = [np.asarray(g['tex']).copy() for g in base]
    lib_dir = os.path.expanduser(a.lib_raw) if a.lib_raw else os.path.join(ROOT, os.path.dirname(rules['library']), 'raw')
    after = hypothesis_textures(an, rules, before, a.length_cm or rules['fallback_length_cm'], lib_dir)
    render_pair(base, before, after, os.path.join(out, 'top_prior_frame.png'))
    print(json.dumps({k: rep[k] for k in ('source', 'type', 'tone_lab', 'confidence', 'agree', 'reason', 'library', 'other_material_hint', 'trellis_unknown')}, ensure_ascii=False, default=str))
    for c in rep['candidates']:
        print('  ', c)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

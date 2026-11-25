#!/usr/bin/env python3
"""Зерно дерева на части — шаг после тона Ш4а (T-20261124-69/4; план paint-material-01). ВЫКЛЮЧЕНО (`rules/part-grain.json` → enabled=false): ни одного байта текстуры не трогает.

ЗАЧЕМ. Тон Ш4а — ровная заливка части. У деревянных частей на фото виден рисунок волокон: ровная заливка выглядит пластиком. Здесь на ровный тон кладётся узор ТОЛЬКО по светлоте L
(a/b не трогаем: цветная крапка при бледном тоне — причина «серо-сирени», T-69/3); цвет и средняя светлота части остаются теми, что задал тон.

ЧТО ДЕЛАЕТ (общее правило, без ID и имён товаров; пороги — `rules/part-grain.json`):
  1. `plan_grain` — решение по каждой части: дерево (по карточке/имени части или флагом вызывающего) · тон ровный (σL ≤ even_tone_sigma_max) · ≥ min_texels · бин библиотеки по тону
     · АМПЛИТУДА с двумя предохранителями: (1) потолок amp_max; (2) зерно по фото только при высокочастотной σL фото ≥ photo_sigma_min, иначе амплитуда = медиана амплитуд соседних частей
     этого же товара с видимым рисунком, а их нет → зерна нет. Отказ записывается причиной (счётчик в отчёте, молчаливых пропусков нет).
  2. `apply_grain` — узор в текстуру: ось зерна по плоскости (`parts_role_planes.merge_planes`; круглая плита — ось ширины товара), плитка по `tile_cm` бина, два слоя шагов, сдвиг/зеркало
     по хэшу плоскости, только L; меняются ТОЛЬКО тексели маски части.
  Вход для Ш4а: маска части (bool по текселям `tx.ti`) + тон Lab части; всё остальное — в `parts[i]`.
  Заливка непокрытых текселей — НЕ здесь (код 07/08, T-70 `texel_pad`).

  python3 tests_part_grain.py
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..', '..'))
RULES_PATH = os.path.join(ROOT, 'tools', 'scout', 'rules', 'part-grain.json')

import tex_coverage as TC  # noqa: E402
import top_prior as TP  # noqa: E402


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as fh:
        r = json.load(fh)
    if not (0 < r['amp_min'] < r['amp_max'] <= 1.0):
        raise ValueError('part-grain.json: amp_min/amp_max вне пределов (0 < min < max ≤ 1)')
    if not (0 < r['photo_sigma_min'] < 10) or not (0 < r['even_tone_sigma_max'] < 20) or r['min_texels'] < 1 or r['round_ratio'] < 1.0:
        raise ValueError('part-grain.json: пороги вне допустимых пределов')
    if len(r['tile_layers']) < 1 or len(r['no_tile_layers']) < 1:
        raise ValueError('part-grain.json: нужен хотя бы один слой шага')
    return r


# ------------------------------------------------------------------ материал части ----------------------------------------------------------------
def part_is_wood(name: str, card: dict | None, rules: dict, role: str | None = None) -> bool:
    """Дерево ли часть по карточке и имени части (для Ш4а, если у него нет своего решения). Ножки/стойки — по «Материал ножек»; обивка/ручки/лампа/клавиши — не дерево; корпус/фасад/столешница — по их словам."""
    n = (name or '').lower()
    card = card or {}
    if role:                                   # роль р.1 (top/legs/facade/side/back/body — выход Ш4а): ножки — по «Материал ножек», остальное — корпус/фасад/столешница
        keys = rules['leg_card_keys'] if role == 'legs' else rules['wood_card_keys']
        t = ' '.join(str(v).lower() for k, v in card.items() if any(s_ in k.lower() for s_ in keys))
        return any(w in t for w in rules['wood_words'])
    txt = lambda keys: ' '.join(str(v).lower() for k, v in card.items() if any(s in k.lower() for s in keys))  # noqa: E731
    if any(w in n for w in rules['non_wood_part_words']):
        return False
    t = txt(rules['leg_card_keys']) if any(w in n for w in rules['leg_part_words']) else txt(rules['wood_card_keys'])
    return any(w in t for w in rules['wood_words'])


# ------------------------------------------------------------------ фото: высокочастотная σL ------------------------------------------------------
def photo_hf_sigma(L_frame, mask, rules: dict):
    """σL «зерна» на фото части: из L вычтено сглаживание по маске части (окно photo_hf_window_px) — плавный свет/тень рисунком не считается. → float | None (мало пикселей).
    L_frame — (h,w) светлота кадра фото в системе кадра 04, mask — (h,w) bool пикселей этой части."""
    import cv2
    w = int(rules['photo_hf_window_px'])
    Lf = np.asarray(L_frame, np.float32)
    mm = np.asarray(mask, bool)
    mf = mm.astype(np.float32)
    num = cv2.blur(Lf * mf, (w, w))
    den = cv2.blur(mf, (w, w))
    ok = mm & (den > 0.6)
    if int(ok.sum()) < int(rules['photo_hf_min_px']):
        return None
    res = Lf[ok] - num[ok] / den[ok]
    return float(1.4826 * np.median(np.abs(res - np.median(res))))


# ------------------------------------------------------------------ бин и узор ---------------------------------------------------------------------
_LIB_CACHE: dict = {}


def _library(tp_rules: dict) -> dict:
    p = os.path.join(ROOT, tp_rules['library'])
    if p not in _LIB_CACHE:
        with open(p, encoding='utf-8') as fh:
            _LIB_CACHE[p] = json.load(fh)
    return _LIB_CACHE[p]


def load_pattern(tone_lab, rules: dict, classes: list | None = None):
    """Бин библиотеки по тону → (описание бина, узор L (m,m) float, нулевое среднее, бесшовный, ось по бину; σL узора). Нет бина/flat → (описание, None, 0.0)."""
    from PIL import Image
    tp = TP.load_rules()
    lib = _library(tp)
    b = TP.library_bin(tone_lab, 'library', lib, dict(tp, library_max_de00=rules['library_max_de00']), None, classes)
    if b.get('bin') in (None, 'flat'):
        return b, None, 0.0
    path = os.path.join(ROOT, tp['library_pat'], b['bin'] + '.jpg')
    im = np.asarray(Image.open(path).convert('RGB').resize((512, 512)), np.uint8)
    L = TC.rgb2lab(im.reshape(-1, 3)).reshape(512, 512, 3)[:, :, :1].astype(np.float64)
    pat = L - L.reshape(-1, 1).mean(0)
    pat = np.concatenate([pat, np.zeros_like(pat), np.zeros_like(pat)], axis=2)       # узор только по L
    pat = TP.seamless_pattern(pat, tp['pattern'].get('seam_overlap', 0.0))
    pat = pat[:, :, 0]
    if b.get('grain_axis') == 'v':
        pat = pat.T
    pat = pat - pat.mean()
    return b, np.ascontiguousarray(pat), float(pat.std())


# ------------------------------------------------------------------ решение по частям ---------------------------------------------------------------
def plan_grain(parts: list, rules: dict | None = None) -> dict:
    """Решение по каждой части. parts[i] = {'id', 'name', 'is_wood' (bool; нет — по part_is_wood с 'card'), 'tone_lab', 'tone_sigma' (σL тона внутри части), 'n_texels',
    'photo_sigma' (float | None), 'card' (dict | None), 'classes' (классы бина | None)}. → {id: {'apply': bool, 'reason': str, 'bin', 'amp', 'amp_source', 'pat', 'pat_std'}}.
    Амплитуда: фото-доказательство (σ ≥ photo_sigma_min) → σ/σ_узора в [amp_min, amp_max]; иначе — медиана амплитуд частей с доказательством; их нет → 'no_photo_evidence'."""
    rules = rules or load_rules()
    out: dict = {}
    evid: dict = {}
    for p in parts:
        pid = p['id']
        rec = {'apply': False, 'reason': None, 'bin': None, 'amp': None, 'amp_source': None, 'pat': None, 'pat_std': 0.0}
        out[pid] = rec
        wood = p.get('is_wood')
        if wood is None:
            wood = part_is_wood(p.get('name', ''), p.get('card'), rules)
        if not wood:
            rec['reason'] = 'not_wood'
            continue
        if int(p.get('n_texels', 0)) < rules['min_texels']:
            rec['reason'] = 'too_small'
            continue
        if p.get('tone_lab') is None or p.get('tone_sigma') is None:
            rec['reason'] = 'no_tone'
            continue
        if float(p['tone_sigma']) > rules['even_tone_sigma_max']:
            rec['reason'] = 'tone_not_even'          # градиент Ш4а — зерно поверх градиента отдельной задачей
            continue
        b, pat, pstd = load_pattern(p['tone_lab'], rules, p.get('classes'))
        rec['bin'] = {k: b.get(k) for k in ('bin', 'dE00', 'tile_cm', 'grain_axis')}
        if pat is None:
            rec['reason'] = 'no_bin'
            continue
        rec['pat'], rec['pat_std'] = pat, pstd
        ps = p.get('photo_sigma')
        if ps is not None and float(ps) >= rules['photo_sigma_min']:
            amp = float(np.clip(float(ps) / max(pstd, 1e-6), rules['amp_min'], rules['amp_max']))
            rec.update(amp=amp, amp_source='photo')
            evid[pid] = amp
    med = float(np.median(list(evid.values()))) if evid else None
    for p in parts:
        rec = out[p['id']]
        if rec['pat'] is None or rec['reason'] is not None:
            continue
        if rec['amp_source'] is None:
            if med is None:
                rec['reason'] = 'no_photo_evidence'
                rec['pat'] = None
                continue
            rec.update(amp=float(np.clip(med, rules['amp_min'], rules['amp_max'])), amp_source='neighbors')
        rec.update(apply=True, reason='ok')
    return out


# ------------------------------------------------------------------ оси и узор по текселям ----------------------------------------------------------------
def hsh(x: int) -> int:
    return (int(x) * 2654435761 + 40503) % 4294967296


def sample_pat(pat, u_cm, s_cm, tile_cm, key: int, layers: list):
    """Узор по плоскости: слои разного шага, у каждого свой сдвиг и зеркало по `key` (хэш плоскости), сумма / sqrt(n) — решётки плитки нет. u — вдоль волокна, s — поперёк."""
    m = pat.shape[0]
    acc = 0.0
    for k, f in enumerate(layers):
        h = hsh(int(key) * 7 + k * 131)
        su, ss = (h % 1000) / 1000.0, ((h >> 10) % 1000) / 1000.0
        fu, fs = (-1.0 if (h >> 20) & 1 else 1.0), (-1.0 if (h >> 21) & 1 else 1.0)
        u = (fu * u_cm / (tile_cm[0] * f) + su) % 1.0
        s_ = (fs * s_cm / (tile_cm[1] * f) + ss) % 1.0
        acc = acc + pat[np.floor(s_ * m).astype(int) % m, np.floor(u * m).astype(int) % m]
    return acc / np.sqrt(len(layers))


def _unit(v, fallback):
    v = np.asarray(v, np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-9 else np.asarray(fallback, np.float64)


def plane_axes(q_cm, n_plane, width_axis, rules: dict):
    """Оси зерна в плоскости с нормалью n_plane по текселям q_cm (N,3): c1 — вдоль волокна, c2 = n × c1. Вытянутая плоскость — длинная ось текселей; круглая/квадратная (отношение осей < round_ratio) —
    ось ширины товара (width_axis), спроецированная в плоскость. → (c1, c2, round_like)."""
    n = _unit(n_plane, (0, 1, 0))
    q = np.asarray(q_cm, np.float64)
    q = q - q.mean(0)
    qp = q - (q @ n)[:, None] * n
    w, ev = np.linalg.eigh(np.cov(qp.T) if len(qp) > 3 else np.eye(3))
    # две большие оси в плоскости: собственные числа по возрастанию, наименьшее ≈ 0 (нормаль)
    big, mid = float(w[2]), float(max(w[1], 1e-12))
    round_like = big / mid < rules['round_ratio']
    if round_like:
        wa = np.zeros(3) if width_axis is None else np.asarray(width_axis, np.float64)
        c1 = wa - (wa @ n) * n
        if np.linalg.norm(c1) < 1e-6:
            for ax in ((1, 0, 0), (0, 0, 1), (0, 1, 0)):
                c1 = np.asarray(ax, np.float64) - (np.asarray(ax, np.float64) @ n) * n
                if np.linalg.norm(c1) > 1e-6:
                    break
    else:
        c1 = ev[:, 2]
        c1 = c1 - (c1 @ n) * n
    c1 = _unit(c1, (1, 0, 0))
    c2 = _unit(np.cross(n, c1), (0, 0, 1))
    return c1, c2, round_like


def apply_grain(tex, tx, parts: list, masks: dict, face_plane, plane_normal, cm_per_unit: float | None, width_axis=None, rules: dict | None = None, enabled: bool | None = None, plan: dict | None = None):
    """Зерно на текстуру. tex — (H,W,3) uint8 после тона Ш4а; tx — растр развёртки (`tex_fill.Tex`: ti, Q, N, f); parts — как в `plan_grain` (+ 'id'); masks[id] — bool по текселям tx
    (какие тексели части красить: маска части ∩ «тон Ш4а лёг»); face_plane — (m,) id плоскости на грань (−1 — не плоскость), plane_normal — (k,3); cm_per_unit — см на единицу кадра;
    width_axis — ось ширины товара (кадр 04). → (новая текстура, отчёт). Выключено (rules.enabled / enabled=False) → (tex БЕЗ изменений, отчёт enabled=False)."""
    rules = rules or load_rules()
    on = rules['enabled'] if enabled is None else bool(enabled)
    rep = {'enabled': on, 'parts': {}, 'applied': 0, 'skipped': {}, 'texels_changed': 0}
    if not on:
        return tex, rep
    import tex_fill as TF
    plan = plan if plan is not None else plan_grain(parts, rules)
    out = np.array(tex, copy=True)
    flat = out.reshape(-1, 3)
    scale = float(cm_per_unit or 100.0)
    fpt = np.asarray(face_plane)[tx.f]
    for p in parts:
        pid = p['id']
        d = plan[pid]
        r = {'apply': d['apply'], 'reason': d['reason'], 'bin': d['bin'], 'amp': None if d['amp'] is None else round(d['amp'], 3), 'amp_source': d['amp_source']}
        rep['parts'][pid] = r
        if not d['apply']:
            rep['skipped'][d['reason']] = rep['skipped'].get(d['reason'], 0) + 1
            continue
        sel = np.asarray(masks[pid], bool)
        if not sel.any():
            r.update(apply=False, reason='empty_mask')
            rep['skipped']['empty_mask'] = rep['skipped'].get('empty_mask', 0) + 1
            continue
        tc = (d['bin'] or {}).get('tile_cm') or [0, 0]
        if tc[0] and tc[1]:
            tile, layers = (float(tc[0]), float(tc[1])), rules['tile_layers']
        else:
            tile, layers = tuple(rules['fallback_tile_cm']), rules['no_tile_layers']
        tone = np.asarray(p['tone_lab'], np.float64)
        qall = tx.Q[sel] * scale
        # части без значимой плоскости — главные оси текселей части (трёхосный запасной путь)
        w3, ev3 = np.linalg.eigh(np.cov((qall - qall.mean(0)).T))
        a1, a2, a3 = ev3[:, 2], ev3[:, 1], ev3[:, 0]
        n_pl_groups = 0
        groups = [int(g) for g in np.unique(fpt[sel])]
        for g in groups:
            tgt = sel & (fpt == g)
            if not tgt.any():
                continue
            q = tx.Q[tgt] * scale
            nn = tx.N[tgt]
            if g >= 0 and int(tgt.sum()) >= rules['min_plane_texels']:
                c1, c2, _rl = plane_axes(q, plane_normal[g], width_axis, rules)
                u_cm, s_cm = q @ c1, q @ c2
                key = g + 1
                n_pl_groups += 1
            else:
                u_cm = q @ a1
                s_cm = np.where(np.abs(nn @ a2) < np.abs(nn @ a3), q @ a2, q @ a3)
                key = 777 + int(pid)
            lab = np.tile(tone, (int(tgt.sum()), 1))
            lab[:, 0] = np.clip(lab[:, 0] + d['amp'] * sample_pat(d['pat'], u_cm, s_cm, tile, key, layers), 0.0, 100.0)
            flat[tx.ti[tgt]] = TF.lab2rgb(lab)
            rep['texels_changed'] += int(tgt.sum())
        r.update(planes_used=n_pl_groups, groups=len(groups))
        rep['applied'] += 1
    return out, rep


# ------------------------------------------------------------------ плоскости для вызывающего -------------------------------------------------------------
def planes_for(V, F):
    """Плоскости меша через `tools/assets/parts_role_planes.merge_planes` (правила `part-role-planes.json`). → (face_plane (m,), normal (k,3)). Вызывать один раз на геометрию."""
    sys.path.insert(0, os.path.join(ROOT, 'tools', 'assets'))
    import parts_role_planes as PRP
    pl = PRP.merge_planes(V, F, **{k: v for k, v in PRP.load_rules().items() if k in ('ang_deg', 'tol_rel', 'min_share')})
    return np.asarray(pl.face_plane), np.asarray(pl.normal)


# ------------------------------------------------------------------ вход от Ш4а (part_material, р.3) -------------------------------------------------------
def parts_from_masks(npz, tx, tex, card: dict | None = None, photo_sigma: dict | None = None, rules: dict | None = None):
    """Выход Ш4а `06-visible/part_material_masks.npz` → (parts для plan_grain, masks по текселям tx). Ключи npz: group_map (T×T int16, группа по текселю, −1 = не красили), names (имя группы),
    tone_srgb (плоский тон группы, (G,3), 0..255 или 0..1), painted_group (bool: группу красил Ш4а), roles (английский ключ роли р.1 на группу: top/legs/facade/side/back/body; names — русские имена групп), texture_size. Берутся только painted_group. Дерево — по карточке и имени (`part_is_wood`; номер материала Ш4а —
    «один материал = один тон», классов он не несёт). Ровность тона (`tone_sigma`) — σL текстуры под маской группы (Ш4а кладёт плоский тон → ≈0; градиент → отказ tone_not_even).
    photo_sigma — {id группы: σL фото (`photo_hf_sigma`)}; нет — None (предохранитель 2 берёт соседей)."""
    rules = rules or load_rules()
    z = npz if isinstance(npz, dict) else dict(np.load(npz, allow_pickle=False))
    gm = np.asarray(z['group_map']).reshape(-1)
    if gm.size != np.asarray(tex).shape[0] * np.asarray(tex).shape[1]:
        raise ValueError(f'group_map {np.asarray(z["group_map"]).shape} не совпадает с текстурой {np.asarray(tex).shape[:2]}')
    gt = gm[tx.ti]
    if 'texture_size' in z and int(np.asarray(z['texture_size']).reshape(-1)[0]) != int(np.asarray(tex).shape[0]):
        raise ValueError('texture_size в npz не совпадает с текстурой')
    names = [str(x) for x in np.asarray(z['names']).reshape(-1)]
    roles = [str(x) for x in np.asarray(z['roles']).reshape(-1)] if 'roles' in z else [None] * len(names)
    tone = np.asarray(z['tone_srgb'], np.float64).reshape(-1, 3)
    if tone.size and tone.max() <= 1.5:
        tone = tone * 255.0
    painted = np.asarray(z['painted_group'], bool).reshape(-1)
    flat = np.asarray(tex).reshape(-1, 3)[tx.ti]
    parts, masks = [], {}
    for g in range(len(names)):
        if g >= len(painted) or not painted[g]:
            continue
        m = gt == g
        n = int(m.sum())
        lab = TC.rgb2lab(np.clip(np.round(tone[g]), 0, 255).astype(np.uint8).reshape(1, 3))[0]
        sig = float(TC.rgb2lab(flat[m])[:, 0].std()) if n >= 20 else None
        parts.append({'id': g, 'name': names[g], 'is_wood': part_is_wood(names[g], card, rules, roles[g] if g < len(roles) else None), 'tone_lab': [float(x) for x in lab], 'tone_sigma': sig,
                      'n_texels': n, 'photo_sigma': (photo_sigma or {}).get(g), 'card': card})
        masks[g] = m
    return parts, masks

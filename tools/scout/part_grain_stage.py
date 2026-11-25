#!/usr/bin/env python3
"""Шаг «зерно дерева» после Ш4а (T-20261124-69/4; правила — rules/part-grain.json, расчёт — salad/trellis/part_grain.py). ВЫКЛЮЧЕНО по умолчанию (enabled=false): ничего не пишет, код возврата 0.

ЗАЧЕМ. Ш4а красит часть ровным тоном; здесь на деревянные группы ложится узор волокон только по светлоте L поверх этого тона (тон не трогается). Порядок: 06 → part_material (Ш4а) → ЭТОТ ШАГ → 07.

Что делает: читает `<run>/<sku>/06-visible/{visible.glb, part_material_masks.npz}` (выход Ш4а), камеру/кадр этапа 4 (`--pose-run`) и фото входа 06; σL фото по группам на кадре 04, масштаб в см по карточке,
ось ширины товара (круглая плита) — из камеры; плоскости меша; `part_grain.apply_grain`. Исходный `visible.glb` сохраняется как `visible.pre-grain.glb` (повторный запуск идёт от него); новый visible.glb — та же геометрия, текстура с зерном.
known/conf/prov/tone_only НЕ трогаются. След — `06-visible/part_grain.json`: решение по каждой группе (причина отказа, бин, амплитуда и её источник), счётчики, время. Любая причина воздержаться (нет npz Ш4а, нет камеры,
нет групп-дерева) — след с причиной, 06/07 идут как раньше, код возврата 0.

  python tools/scout/part_grain_stage.py --run RUN --sku SKU --photo ФОТО.png --pose-run ПАПКА_ПОЗЫ [--card CARD.json] [--out-dir 06-visible] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
TR = os.path.join(HERE, 'salad', 'trellis')
sys.path[:0] = [TR, HERE]

OUT = 'part_grain.json'
STAGE_DIR = '06-visible'
PRE = 'visible.pre-grain.glb'
VERSION = 1


class Abstain(Exception):
    """Воздержание: причина идёт в след, 06/07 красят как раньше."""


def load_card(path: str | None) -> dict | None:
    if not path:
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return d.get('card') if isinstance(d.get('card'), dict) else d


def swap_tex_glb(src: str, tex: np.ndarray, dst: str) -> None:
    """GLB с той же геометрией, текстура заменена (PNG без потерь); материал не меняется."""
    import io

    import a1_tone as A
    from PIL import Image
    j, b = A.read_glb(src)
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(tex)).save(buf, 'PNG')
    nj, nb = A.swap_texture(j, b, buf.getvalue())
    nj['images'][A.base_color_image(nj)]['mimeType'] = 'image/png'
    A.write_glb(dst, nj, nb)


def group_photo_sigma(L_frame, valid, ids, cos_f, face_group, roles, face_ny, rules: dict) -> dict:
    """σL фото по группам на кадре 04: {id группы: σ | None}. Верх (роль top) — грани, смотрящие вверх (|n_y|>0.8), с любого угла; остальные — грани к камере (cos ≥ 0.3).
    `face_group` — группа на грань (значение ≥ числа групп = «не красили»); ids — id грани на пиксель кадра (−1 фон)."""
    import part_grain as PG
    nF = len(face_group)
    fid = np.clip(ids, 0, nF - 1)
    gpix = np.where(valid & (ids >= 0), np.asarray(face_group)[fid], -1)
    out = {}
    for g, role in enumerate(roles):
        m = gpix == g
        m = m & (np.abs(np.asarray(face_ny)[fid]) > 0.8) if role == 'top' else m & (cos_f >= 0.3)
        out[g] = PG.photo_hf_sigma(L_frame, m, rules) if m.any() else None
    return out


def process(a, rules: dict, d: str, rep: dict) -> None:
    import part_grain as PG
    import pose_fit as PF
    import ref_zone as RZ
    import tex_coverage as TC
    import tex_fill as TF
    import tex_visible as TV
    from PIL import Image
    t0 = time.time()
    mp = os.path.join(d, 'part_material_masks.npz')
    if not os.path.exists(mp):
        raise Abstain('нет part_material_masks.npz (Ш4а не красил или выключен)')
    pre = os.path.join(d, PRE)
    vis = os.path.join(d, 'visible.glb')
    src = pre if os.path.exists(pre) else vis
    if not os.path.exists(src):
        raise Abstain('нет visible.glb этапа 6')
    geoms = TV.load_shape(src)
    if len(geoms) != 1:
        raise Abstain('в visible.glb %d геометрий, шаг берёт одну' % len(geoms))
    g = geoms[0]
    V, F = np.asarray(g['V'], np.float64), np.asarray(g['F'], np.int64)
    nF = len(F)
    tex = np.asarray(g['tex'])[..., :3].astype(np.uint8)
    z = dict(np.load(mp, allow_pickle=False))
    names = [str(x) for x in np.asarray(z['names']).reshape(-1)]
    roles = [str(x) for x in np.asarray(z['roles']).reshape(-1)] if 'roles' in z else [''] * len(names)
    if 'face_group' not in z or len(z['face_group']) != nF:
        raise Abstain('face_group в npz нет или длина ≠ числу граней 06 (меши разошлись)')
    fgrp = np.asarray(z['face_group']).astype(np.int64)
    st = TV.load_stage(a.pose_run)
    st, _zi = TV.zbuffer_fix(geoms, st)
    cam = st.get('camera') or {}
    if cam.get('az') is None:
        raise Abstain('нет камеры этапа 4 (az)')
    ctr, size = TF.frame_of(geoms)
    P = (V - ctr) / size
    card = load_card(a.card)
    cpu, src_cm = PG.cm_per_unit(float(np.ptp(P, 0).max()) * size, card, rules), 'card'
    if cpu is None:
        cpu, src_cm = rules['fallback_length_cm'] / float(np.ptp(P, 0).max()), 'fallback_length_cm'
    else:
        cpu = cpu * size                                              # см на единицу КАДРА (P нормирован на size)
    rep.update(cm_per_unit=round(float(cpu), 3), cm_source=src_cm)
    # σL фото по группам (кадр 04)
    ph = np.asarray(Image.open(a.photo).convert('RGBA'))
    rgb, okp = TV.photo_to_frame(ph, st['P'], st['px'])
    Lf = TC.rgb2lab(rgb.reshape(-1, 3)).reshape(st['px'], st['px'], 3)[..., 0]
    n3 = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    n3 = n3 / np.maximum(np.linalg.norm(n3, axis=1), 1e-30)[:, None]
    valid = st['mask'] & okp & (st['ids'] >= 0)
    sig = group_photo_sigma(Lf, valid, st['ids'], st['cos'], fgrp, roles, n3[:, 1], rules)
    rep['photo_sigma'] = {names[k]: (None if v is None else round(float(v), 2)) for k, v in sig.items()}
    # ось ширины товара (круглая плита) — по камере 04; нет — запасная ось в плоскости
    width = None
    try:
        _C, right, up, fwd = PF.cam_basis(cam['az'], cam['el'], cam['d'])
        ob, _dl = RZ.object_basis(V, F, (right, up, fwd))
        width = np.asarray(ob[0], np.float64)
    except Exception as e:  # noqa: BLE001
        rep['width_axis'] = 'fallback (%s)' % type(e).__name__
    tx = TF.Tex(g, P, TF._grid(g), None)
    parts, masks = PG.parts_from_masks(z, tx, tex, card, sig, rules)
    if not parts:
        raise Abstain('Ш4а не покрасил ни одной группы (painted_group пуст)')
    fp, pn = PG.planes_for(V, F)
    new, r = PG.apply_grain(tex, tx, parts, masks, fp, pn, cpu, width, rules, enabled=True)
    rep['groups'] = {str(k): dict(v, name=names[k]) for k, v in r['parts'].items()}
    rep.update(applied=r['applied'], skipped=r['skipped'], texels_changed=r['texels_changed'], planes=int(len(pn)))
    if r['applied'] == 0:
        raise Abstain('зерно не легло ни на одну группу (причины: %s)' % r['skipped'])
    if not os.path.exists(pre):
        shutil.copy2(vis, pre)                                       # исходник один раз; повторный запуск идёт от него
    swap_tex_glb(src, new, vis)
    rep['seconds'] = round(time.time() - t0, 1)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', required=True)
    ap.add_argument('--sku', required=True)
    ap.add_argument('--photo', required=True)
    ap.add_argument('--pose-run', required=True)
    ap.add_argument('--card', default='')
    ap.add_argument('--rules', default='')
    ap.add_argument('--out-dir', default='', help='папка 06-visible для пробы вместо <run>/<sku>/06-visible')
    ap.add_argument('--force', action='store_true', help='включить шаг независимо от rules.enabled (замер/проба)')
    a = ap.parse_args(argv)
    import part_grain as PG
    rules = PG.load_rules(a.rules or PG.RULES_PATH)
    if not rules.get('enabled') and not a.force:
        print('part_grain: выключено (rules.enabled=false) — ничего не меняю')
        return 0
    d = a.out_dir or os.path.join(a.run, a.sku, STAGE_DIR)
    os.makedirs(d, exist_ok=True)
    rep = {'version': VERSION, 'rule': 'R-PART-GRAIN', 'sku': a.sku, 'abstain': None}
    try:
        process(a, rules, d, rep)
    except Abstain as e:
        rep['abstain'] = str(e)
    except Exception as e:  # noqa: BLE001 — шаг не роняет конвейер: 06/07 идут как раньше, причина в след
        rep['abstain'] = 'сбой: %s: %s' % (type(e).__name__, e)
        traceback.print_exc()
    with open(os.path.join(d, OUT), 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=float)
    print('part_grain:', 'зерно на %s групп' % rep.get('applied') if not rep['abstain'] else 'воздержался — ' + rep['abstain'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

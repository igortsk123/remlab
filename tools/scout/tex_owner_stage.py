#!/usr/bin/env python3
"""Шаг «владелец текселя» после Ш4а (вариант А, шаги 5–6; T-20261126-97/1 фаза 2). Правила — rules/tex-owner.json, расчёт — tex_owner.py. ВЫКЛЮЧЕНО по умолчанию (enabled=false): ничего не пишет, код возврата 0.

ЗАЧЕМ. После Ш4а в развёртке остаются куски старого цвета у граней без роли и крап на границах островов (грань задевает тексель соседнего острова). Шаг даёт каждому тексель одного владельца-грань,
роль грани без роли берёт у плоской панели, непокрытые гранями тексели у острова получают отступ тоном группы. Порядок: 06 → Ш4а → ЭТОТ ШАГ → зерно (part_grain_stage) → 07.

Читает `<run>/<sku>/06-visible/{visible.glb, part_material_masks.npz, _partmaterial/rel.npz}`; исходный `visible.glb` сохраняет как `visible.pre-owner.glb` (повторный запуск идёт от него); пишет новый visible.glb
(та же геометрия, новая baseColor-текстура), расширенный group_map в part_material_masks.npz и след `tex_owner.json`: числа по шагам, сторож «покрытые без покраски». Любая причина воздержаться — след с причиной, код 0.

  python tools/scout/tex_owner_stage.py --run RUN --sku SKU [--rules ФАЙЛ.json] [--out-dir 06-visible] [--force]
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
sys.path[:0] = [HERE]

OUT = 'tex_owner.json'
STAGE_DIR = '06-visible'
PRE = 'visible.pre-owner.glb'
RULES_PATH = os.path.join(HERE, 'rules', 'tex-owner.json')
VERSION = 1


class Abstain(Exception):
    """Воздержание: причина идёт в след, остальные шаги идут как раньше."""


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding='utf-8') as fh:
        r = json.load(fh)
    rr, ow = r['roles'], r['owner']
    if not (0 < float(rr['crease_deg']) < 90) or not (0 < float(rr['alien_max_frac']) < 1) or float(rr['weld_scale']) <= 0:
        raise ValueError('tex-owner.json: roles вне допустимых пределов')
    if not (0 <= float(ow['shrink_texel']) < 4) or int(ow['pad_px']) < 1 or int(ow['pad_px']) % 2 == 0 or not (0 <= int(ow['raster_bits']) <= 8):
        raise ValueError('tex-owner.json: owner вне допустимых пределов (pad_px нечётный ≥ 1)')
    dl = r['dilate']
    if not (0 <= int(dl['uv_gutter_px']) <= 64) or not (0 < float(dl['guard_dl_max']) < 100):
        raise ValueError('tex-owner.json: dilate вне допустимых пределов (uv_gutter_px 0…64, guard_dl_max > 0)')
    return r


def process(rules: dict, d: str, rep: dict) -> None:
    import tex_owner as TO
    t0 = time.time()
    mp = os.path.join(d, 'part_material_masks.npz')
    if not os.path.exists(mp):
        raise Abstain('нет part_material_masks.npz (Ш4а не красил или выключен)')
    pre = os.path.join(d, PRE)
    vis = os.path.join(d, 'visible.glb')
    src = pre if os.path.exists(pre) else vis
    if not os.path.exists(src):
        raise Abstain('нет visible.glb этапа 6')
    z = {k: v for k, v in np.load(mp, allow_pickle=False).items()}
    for k in ('face_group', 'group_map', 'tone_srgb', 'painted_group', 'texture_size', 'names'):
        if k not in z:
            raise Abstain('в part_material_masks.npz нет поля %s' % k)
    names = [str(x) for x in np.asarray(z['names']).reshape(-1)]
    painted = np.asarray(z['painted_group'], bool)
    if not painted.any():
        raise Abstain('Ш4а не покрасил ни одной группы (painted_group пуст)')
    fg = np.asarray(z['face_group']).astype(int)
    T = int(z['texture_size'])
    js, binb = TO.read_glb(src)
    tex = TO.tex_of(js, binb, 0)
    if tex.shape[0] != T or tex.shape[1] != T:
        raise Abstain('текстура %s не равна texture_size %d (шаг считает квадрат)' % (tex.shape[:2], T))
    P, UV, F = TO.read_geom(src)
    if len(F) != len(fg):
        raise Abstain('face_group %d ≠ числу граней 06 %d (меши разошлись)' % (len(fg), len(F)))
    fg2, info = TO.face_roles(P, F, fg, len(names), rules)
    rep['roles'] = info
    ids = TO.owner_ids(UV, F, T, rules)
    new, gmap, per = TO.apply_owner(tex, np.asarray(z['group_map']).copy(), ids, fg2, painted, np.asarray(z['tone_srgb']), names, rules)
    rep['groups'] = per
    kn = None
    rp = os.path.join(d, '_partmaterial', 'rel.npz')
    if os.path.exists(rp):
        kn = np.asarray(np.load(rp)['known'], bool)
    rep['guard'] = TO.guard_unpainted(ids, gmap, kn)
    if not os.path.exists(pre):
        shutil.copy2(vis, pre)                                       # исходник один раз; повторный запуск идёт от него
    TO.write_glb_with_tex(src, new, vis)
    z['group_map'] = gmap
    np.savez_compressed(mp, **z)
    rep['seconds'] = round(time.time() - t0, 1)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', required=True)
    ap.add_argument('--sku', required=True)
    ap.add_argument('--rules', default='')
    ap.add_argument('--out-dir', default='', help='папка 06-visible для пробы вместо <run>/<sku>/06-visible')
    ap.add_argument('--force', action='store_true', help='включить шаг независимо от rules.enabled (замер/проба)')
    a = ap.parse_args(argv)
    rules = load_rules(a.rules or RULES_PATH)
    if not rules.get('enabled') and not a.force:
        print('tex_owner: выключено (rules.enabled=false) — ничего не меняю')
        return 0
    d = a.out_dir or os.path.join(a.run, a.sku, STAGE_DIR)
    os.makedirs(d, exist_ok=True)
    rep = {'version': VERSION, 'rule': 'R-TEX-OWNER', 'sku': a.sku, 'abstain': None}
    try:
        process(rules, d, rep)
    except Abstain as e:
        rep['abstain'] = str(e)
    except Exception as e:  # noqa: BLE001 — шаг не роняет конвейер: остальные шаги идут как раньше, причина в след
        rep['abstain'] = 'сбой: %s: %s' % (type(e).__name__, e)
        traceback.print_exc()
    with open(os.path.join(d, OUT), 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=float)
    print('tex_owner:', 'текстура переписана, групп %d' % len(rep.get('groups') or {}) if not rep['abstain'] else 'воздержался — ' + rep['abstain'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

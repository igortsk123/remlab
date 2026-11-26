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
sys.path[:0] = [HERE, os.path.join(HERE, 'salad', 'trellis')]

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
    tg = r['tone_guard']
    if (not (0 < float(tg['dl_max']) < 100) or not (0 < float(tg['dab_max']) < 200) or int(tg['min_px']) < 1 or not (0 <= float(tg['min_area_frac']) < 1) or not (0 <= float(tg['cos_min']) < 1)
            or int(tg['panel_min_px']) < 1 or int(tg['panel_min_texels']) < 1 or not (0 <= float(tg['stop_area_frac']) <= 1) or not (0 < float(tg['stop_dl']) < 100) or not (0 < float(tg['stop_dab']) < 200)):
        raise ValueError('tex-owner.json: tone_guard вне допустимых пределов (dl_max/stop_dl 0…100, dab_max/stop_dab 0…200, min_px/panel_min_px/panel_min_texels ≥ 1, min_area_frac/cos_min 0…1, stop_area_frac 0…1)')
    return r


def photo_frame(d: str, src_glb: str, photo: str, pose_run: str) -> tuple:
    """Кадр камеры 04 с ФОТО: (ids граней, фото в кадре, valid, cos, откуда). Боевой путь — фото + папка позы (как у зерна); для готовых 06 разбора без них — rel.npz Ш4а (--keep-work).
    Нет ни того ни другого → (None, …, причина): сторож пишет «не проверено», не стоп."""
    if photo and pose_run and os.path.exists(photo):
        import tex_visible as TV
        from PIL import Image
        geoms = TV.load_shape(src_glb)
        if len(geoms) != 1:
            return None, None, None, None, 'в visible.glb %d геометрий' % len(geoms)
        st = TV.load_stage(pose_run)
        st, _zi = TV.zbuffer_fix(geoms, st)
        if not st.get('camera') or st['camera'].get('az') is None:
            return None, None, None, None, 'нет камеры этапа 4 (az)'
        rgb, okp = TV.photo_to_frame(np.asarray(Image.open(photo).convert('RGBA')), st['P'], st['px'])
        return st['ids'], rgb, st['mask'] & okp & (st['ids'] >= 0), st['cos'], 'фото+поза'
    rp = os.path.join(d, '_partmaterial', 'rel.npz')
    if os.path.exists(rp):
        r = np.load(rp, allow_pickle=False)
        if all(k in r.files for k in ('ids', 'prgb_reg', 'valid', 'cosf')):
            return r['ids'], r['prgb_reg'], np.asarray(r['valid'], bool), r['cosf'], 'rel.npz Ш4а'
    return None, None, None, None, 'нет фото/позы и нет rel.npz'


def tone_guard_run(rules: dict, d: str, src_glb: str, P, F, fg, fg2, z: dict, names: list, photo: str, pose_run: str, tex=None, ids_tex=None) -> dict:
    """Сторож «не отдавать»: цвет детали до owner (фото, где видна; иначе текстура 06) против тона её группы. Нет кадра фото — проверка по 06 (если есть tex/ids_tex), иначе «не проверено» (всё отдаётся как раньше)."""
    import tex_owner as TO
    area = TO.face_areas(P, F)
    ids, rgb, valid, cosf, how = photo_frame(d, src_glb, photo, pose_run)
    rr = rules['roles']
    _n, comp = TO.panels(P, F, float(rr['crease_deg']), float(rr['weld_scale']))
    if ids is None:
        if tex is None:
            n = len(names)
            giv = (fg2 >= 0) & (fg2 < n) & (fg2 != fg)
            return {'стоп': False, 'причина': '', 'не_проверено': how, 'доля_отдано_площади': round(float(area[giv].sum() / max(float(area.sum()), 1e-20)), 4), 'по_группам': {}, 'детали': [], 'не_отдать': []}
        ids = np.full(ids_tex.shape, -1, np.int64)                      # кадра нет — пустой кадр: все панели идут по текстуре 06
        rgb, valid, cosf = np.zeros(ids.shape + (3,), np.uint8), np.zeros(ids.shape, bool), None
        how = 'нет фото/позы: только текстура 06 (%s)' % how
    res = TO.guard_tone(ids, rgb, valid, fg, fg2, comp, area, np.asarray(z['tone_srgb']), np.asarray(z['painted_group'], bool), names, rules, cosf, tex, ids_tex)
    res['кадр'] = how
    return res


def process(rules: dict, d: str, rep: dict, photo: str = '', pose_run: str = '') -> None:
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
    if rules['tone_guard']['enabled']:
        tgr = tone_guard_run(rules, d, src, P, F, fg, fg2, z, names, photo, pose_run, tex, ids)
        rep['tone_guard'] = tgr
        if tgr['стоп']:
            raise Abstain(tgr['причина'])                                # воздержание = СТОП прогона (abstain_is_stop): текстуру и visible.glb не трогаем, 07 не идёт
        if tgr['не_отдать']:
            nd = np.asarray(tgr['не_отдать'], np.int64)
            fg2 = fg2.copy()
            fg2[nd] = fg[nd]                                             # «не отдавать»: грани панели остаются с прежней ролью → метки зерна нет, 07 красит их как раньше (sub_tone и др.)
        tgr['не_отдано_граней'] = len(tgr['не_отдать'])
        tgr['не_отдать'] = []                                            # индексы в след не пишем (тысячи); строки по панелям — в 'детали'
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
    ap.add_argument('--photo', default='', help='сырое фото входа 06 — для сторожа «тон фото области ↔ тон группы» (вместе с --pose-run)')
    ap.add_argument('--pose-run', default='', help='папка позы (<run>/<sku>) с 04-camera — кадр камеры для сторожа')
    a = ap.parse_args(argv)
    rules = load_rules(a.rules or RULES_PATH)
    if not rules.get('enabled') and not a.force:
        print('tex_owner: выключено (rules.enabled=false) — ничего не меняю')
        return 0
    d = a.out_dir or os.path.join(a.run, a.sku, STAGE_DIR)
    os.makedirs(d, exist_ok=True)
    rep = {'version': VERSION, 'rule': 'R-TEX-OWNER', 'sku': a.sku, 'abstain': None}
    try:
        process(rules, d, rep, a.photo, a.pose_run)
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

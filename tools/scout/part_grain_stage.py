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
MASK = 'part_grain_mask.png'
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


def pick_by_passport(d: str, parts: list, rules: dict, rep: dict, Lf, valid, st, fgrp, roles: list, face_ny, photo_shape, names: list) -> None:
    """T-99/12 шаг 2: паспорт рисунка фото по группам (кадр 04, px/см кадра = px_per_cm фото из Ш4а × масштаб кадра; доля крупного — по фото без теней этапа 05, если оно есть) →
    `part_grain_pick.pick` кладёт в каждую часть p['pick'] (образец по рисунку, один на материал); `plan_grain` берёт его вместо бина по тону. Нет px_per_cm/паспортов — ничего не кладёт (путь по тону), причина в следе."""
    import part_grain_pick as PK
    from PIL import Image
    import tex_coverage as TC
    import tex_visible as TV
    pj = os.path.join(d, 'part_material.json')
    ppc_photo = 0.0
    if os.path.exists(pj):
        with open(pj, encoding='utf-8') as fh:
            ppc_photo = float(json.load(fh).get('px_per_cm') or 0.0)
    if ppc_photo <= 0:
        rep['pattern_pick'] = {'note': 'нет px_per_cm в part_material.json — образец по тону'}
        return
    px = int(st['px'])
    ppc = ppc_photo * px / float(max(photo_shape[0], photo_shape[1]))
    Ld = None
    dp = os.path.join(d, '..', '05-delight', 'delight.rgba.png')
    if os.path.exists(dp):
        rgb, _ok = TV.photo_to_frame(np.asarray(Image.open(dp).convert('RGBA')), st['P'], px)
        Ld = TC.rgb2lab(rgb.reshape(-1, 3)).reshape(px, px, 3)[..., 0]
    pas = PK.group_passports(Lf, valid, st['ids'], st['cos'], fgrp, roles, face_ny, ppc, Ld)
    pk = PK.pick(parts, pas, rules, ppc)
    for p in parts:
        if p['id'] in pk:
            p['pick'] = pk[p['id']]
    rep['pattern_pick'] = {'px_per_cm_frame': round(ppc, 2), 'no_shadow_photo': Ld is not None, 'passports': {names[g]: v for g, v in pas.items()},
                           'picked': {str(p['id']): {k: v for k, v in pk[p['id']].items()} for p in parts if p['id'] in pk}}


def strip_sigma(L, mask, blur_frac: float, erode_px: int, min_texels: int):
    """Разброс светлоты «в полосе рисунка»: σ(L − размытие) по текселям mask (эродированной): то, что Fable 14 называет «обычным разбросом в полосе» (мелкая полоса: волокно, не тон и не свет).
    blur_frac — σ размытия в долях стороны текстуры (15 px при 2048 → 0,0073). → σ или None (мало текселей)."""
    import cv2
    T = L.shape[0]
    L = np.asarray(L, np.float32)
    hf = L - cv2.GaussianBlur(L, (0, 0), max(1.0, float(blur_frac) * T))
    k = 2 * int(erode_px) + 1
    me = cv2.erode(np.asarray(mask, np.uint8), np.ones((k, k), np.uint8)).astype(bool)
    if int(me.sum()) < int(min_texels):
        return None
    return float(hf[me].std())


def amp_from_strip(d: str, parts: list, tex_new, rules: dict, rep: dict, tx=None, fp=None, masks=None, face_part=None) -> dict:
    """T-99/11 шаг 4 (Fable 14 п.3): размах волокна — по ФОТО, не по потолку библиотеки. По каждой применённой группе: σ полосы фото (известные тексели ∩ группа, фото-текстура ДО тона Ш4а)
    и σ полосы нашей новой текстуры (вся группа); k = clip(цель · σ_фото / σ_наша, 1, k_max) — множитель на размах группы (k ≤ 1 — не гасим: ослаблять — дело предохранителей зерна). → {id: k}."""
    import part_grain_measure as PGM
    import tex_visible as TV
    from PIL import Image
    cfg = rules['amp_strip']
    def pick(pre, cur):
        p_ = os.path.join(d, pre)
        return p_ if os.path.exists(p_) else os.path.join(d, cur)
    gp = TV.load_shape(pick('visible.pre-partmaterial.glb', 'visible.glb'))[0]
    L_ph = PGM.lab_L(np.asarray(gp['tex'])[..., :3])
    L_new = PGM.lab_L(np.asarray(tex_new)[..., :3])
    T = L_ph.shape[0]
    kp = pick('known.pre-partmaterial.png', 'known.png')
    known = np.asarray(Image.open(kp).convert('L')) > 127 if os.path.exists(kp) else np.zeros((T, T), bool)
    z = np.load(os.path.join(d, 'part_material_masks.npz'))
    gm = np.asarray(z['group_map'])
    out = {}
    planes_img = None
    if tx is not None and fp is not None:                                  # плоскость на тексель (изображение T×T): размах считаем и по плоскостям (тумба и верх — один «верх» Ш4а, но разный рисунок)
        planes_img = np.full(T * T, -2, np.int64)
        planes_img[np.asarray(tx.ti)] = np.asarray(fp)[np.asarray(tx.f)]
        planes_img = planes_img.reshape(T, T)

    def kk(sf, so):
        return float(np.clip(float(cfg['target']) * sf / so, 1.0, float(cfg['k_max'])))
    for p in parts:
        grp = gm == p['id']
        sf = strip_sigma(L_ph, grp & known, cfg['blur_frac'], cfg['erode_px'], cfg['min_texels'])
        so = strip_sigma(L_new, grp & known, cfg['blur_frac'], cfg['erode_px'], cfg['min_texels'])
        if so is None:
            so = strip_sigma(L_new, grp, cfg['blur_frac'], cfg['erode_px'], cfg['min_texels'])
        e = {'σ_фото': None if sf is None else round(sf, 3), 'σ_наша': None if so is None else round(so, 3), 'k': 1.0}
        kpart = 1.0
        if sf is not None and so is not None and so > 1e-6:
            kpart = kk(sf, so)
            e['k'] = round(kpart, 3)
        pk = {}
        if planes_img is not None:
            e['planes'] = {}
            for g in np.unique(planes_img[grp]):
                if g < 0:
                    continue
                pm = grp & (planes_img == g) & known
                sfp, sop = strip_sigma(L_ph, pm, cfg['blur_frac'], cfg['erode_px'], cfg['min_texels']), strip_sigma(L_new, pm, cfg['blur_frac'], cfg['erode_px'], cfg['min_texels'])
                if sfp is not None and sop is not None and sop > 1e-6:
                    pk[int(g)] = kk(sfp, sop)
                    e['planes'][str(int(g))] = {'σ_фото': round(sfp, 3), 'σ_наша': round(sop, 3), 'k': round(pk[int(g)], 3)}
        if (rules.get('detail_unity') or {}).get('enabled') and face_part is not None and planes_img is not None:     # T-99/12 шаг 4: ОДНО усиление на деталь (гнутая нога разбита на плоскости — разные k давали блоки): k по всем текселям детали, всем её плоскостям
            part_img = np.full(T * T, -2, np.int64)
            part_img[np.asarray(tx.ti)] = np.asarray(face_part)[np.asarray(tx.f)]
            part_img = part_img.reshape(T, T)
            e['details'] = {}
            pk = {}
            for u in np.unique(part_img[grp]):
                if u < 0:
                    continue
                dm = grp & (part_img == u)
                sfd, sod = strip_sigma(L_ph, dm & known, cfg['blur_frac'], cfg['erode_px'], cfg['min_texels']), strip_sigma(L_new, dm & known, cfg['blur_frac'], cfg['erode_px'], cfg['min_texels'])
                if sfd is None or sod is None or sod <= 1e-6:
                    continue
                ku = kk(sfd, sod)
                e['details'][str(int(u))] = {'σ_фото': round(sfd, 3), 'σ_наша': round(sod, 3), 'k': round(ku, 3)}
                pls = planes_img[dm]
                for g in np.unique(pls[pls >= 0]):                       # плоскость — детали, у которой в ней больше текселей (плоскость склеила несколько деталей — отдаём большей)
                    if int(((part_img == u) & (planes_img == g) & grp).sum()) * 2 >= int(((planes_img == g) & grp).sum()) or int(g) not in pk:
                        pk[int(g)] = ku
        if kpart > 1.0 + 1e-6 or any(v > 1.0 + 1e-6 for v in pk.values()):
            out[p['id']] = {'k': kpart, 'planes': pk}
        rep.setdefault('amp_strip', {})[str(p['name'])] = e
    return out


def measure_parts(d: str, parts: list, z: dict, V, F, fp, pn, rules: dict) -> dict:
    """Мера группы по ФОТО-текстуре до тона Ш4а (`*.pre-partmaterial.*`; нет — текущие файлы 06): parts[i]['measure'] = `part_grain_measure.measure_group`. → {имя группы: запись} для следа."""
    import part_grain_measure as PGM
    import tex_visible as TV
    from PIL import Image
    pm = rules['pattern_measure']

    def pick(pre, cur):
        p = os.path.join(d, pre)
        return p if os.path.exists(p) else os.path.join(d, cur)
    gp = TV.load_shape(pick('visible.pre-partmaterial.glb', 'visible.glb'))[0]
    L = PGM.lab_L(np.asarray(gp['tex'])[..., :3])
    T = L.shape[0]
    kp, cp = pick('known.pre-partmaterial.png', 'known.png'), pick('conf.pre-partmaterial.png', 'conf.png')
    known = np.asarray(Image.open(kp).convert('L')) > 127 if os.path.exists(kp) else np.zeros((T, T), bool)
    conf = np.asarray(Image.open(cp).convert('L')) / 255.0 if os.path.exists(cp) else np.ones((T, T))
    gm = np.asarray(z['group_map'])
    ff = PGM.FaceFrame(V, F, gp['UV'], T, fp, pn, rules)
    out = {}
    known_ac = known                                         # повтор шага — на ТОМ ЖЕ «известном», что у паспорта 07 (`tex_fill.load_known_png`): без текселей provenance=4 (synth, не наблюдались), пока synth_trusted=false; иначе значения вдвое ниже паспортных (T-93/3: рейки 0,14 против 0,28)
    pv_path = pick('prov.pre-partmaterial.png', 'prov.png')
    try:
        import tex_fill as TF
        if not TF.synth_known_trusted() and os.path.exists(pv_path):
            pv = np.asarray(Image.open(pv_path))
            if pv.ndim == 2 and pv.shape == known.shape:
                known_ac = known & (pv != 4)
    except ImportError:                                      # нет tex_fill в срезе кода — как раньше, известное целиком
        pass
    actx = PGM.ac_context(L, known_ac, pm)
    for p in parts:
        p['measure'] = PGM.measure_group(L, known, conf, gm == p['id'], pm, ff, actx)
        out[str(p['id'])] = dict(p['measure'], id=int(p['id']), name=str(p['name']))
    return out


def detail_bands(Ld, sel, ppc: float, pd: dict):
    """Полосы деталей фото без теней в кадре: (крупное, мелкое) в единицах L. Тень и свет — всё, что шире blur_cm (срез >5 см = тень), вычитается размытием по грани-в-лоб (нормированная свёртка по маске sel,
    чтобы край и фон не тянули). Крупное = от split_cm до blur_cm (дуги, «соборы»), мелкое = от fine_cm до split_cm (поры, штрих)."""
    import cv2
    m = sel.astype(np.float32)
    L = np.where(sel, Ld, 0.0).astype(np.float32)

    def blur(cm):
        s = max(float(cm) * ppc, 0.6)
        num = cv2.GaussianBlur(L, (0, 0), s)
        den = cv2.GaussianBlur(m, (0, 0), s)
        return np.where(den > 1e-3, num / np.maximum(den, 1e-3), 0.0)
    b_fine, b_split, b_hi = blur(pd['fine_cm']), blur(pd['split_cm']), blur(pd['blur_cm'])
    coarse = np.where(sel, b_split - b_hi, 0.0)
    fine = np.where(sel, b_fine - b_split, 0.0)
    return coarse, fine


def photo_detail_step(tex_in, tone_tex, tx, g: dict, st: dict, Ld, valid, fgrp, names: list, ppc: float, rules: dict, rep: dict, face_n=None):
    """T-99/12 шаг 5: рисунок С ФОТО на лице группы (тумба Хостера): слой деталей фото без теней (этап 05) поверх тона Ш4а — только грани в лоб, свет/тени шире blur_cm вычтены.
    Текселю группы, видимому с камеры в лоб и надёжному, — тон Ш4а (tone_tex, до зерна) + деталь фото (L, усилено gain_*); остальным текселям группы остаётся зерно образца. → (текстура, маска «деталь с фото»)."""
    import cv2
    import tex_coverage as TC
    import tex_visible as TV
    from scipy.ndimage import map_coordinates
    pd = rules['photo_detail']
    info = {'applied': False, 'groups': pd['groups'], 'ppc_frame': round(float(ppc), 2)}
    rep['photo_detail'] = info
    gi = [i for i, n in enumerate(names) if n in pd['groups']]
    if not gi:
        info['reason'] = 'нет групп %s среди %s' % (pd['groups'], names)
        return tex_in, None
    px = int(st['px'])
    ids = np.clip(st['ids'], 0, len(fgrp) - 1)
    ingrp = valid & np.isin(fgrp[ids], gi) & (st['cos'] >= float(pd['cos_min']))
    if int(ingrp.sum()) < int(pd['min_px']):
        info['reason'] = 'в лоб видно %d px (< %d)' % (int(ingrp.sum()), int(pd['min_px']))
        return tex_in, None
    er = int(pd['edge_px'])
    sel = cv2.erode(ingrp.astype(np.uint8), np.ones((2 * er + 1, 2 * er + 1), np.uint8)).astype(bool) if er > 0 else ingrp
    coarse, fine = detail_bands(Ld, sel, ppc, pd)
    D = np.clip(float(pd['gain_coarse']) * coarse + float(pd['gain_fine']) * fine, -float(pd['clip_L']), float(pd['clip_L']))
    T = tx.T
    F = np.asarray(g['F'], np.int64)
    import pose_fit as PF
    fr, why_fr = TV.cube_frame([g], st)
    if fr is None:
        info['reason'] = 'нет камеры для проекции: %s' % why_fr
        return tex_in, None
    ti, f = tx.ti, tx.f
    # точка тексела (кадр P) → куб камеры: подобие по вершинам (to_cube — масштаб/сдвиг/поворот), затем проекция камерой этапа 4; грани линейной картой не берём — на мелких треугольниках (22 тыс. граней) она не строится
    A = np.hstack([np.asarray(tx.P, np.float64), np.ones((len(tx.P), 1))])
    M, *_ = np.linalg.lstsq(A, np.asarray(fr['P'], np.float64), rcond=None)
    Qc = np.hstack([tx.Q, np.ones((len(tx.Q), 1))]) @ M
    xs_, ys_, _Zq = PF.project(Qc, fr['cam'])
    x, y = xs_ * px, ys_ * px
    ing_t = np.isin(fgrp[f], gi)
    inside = (x >= 0.5) & (x <= px - 0.5) & (y >= 0.5) & (y <= px - 0.5) & ing_t
    xi, yi = np.clip(np.floor(x).astype(np.int64), 0, px - 1), np.clip(np.floor(y).astype(np.int64), 0, px - 1)
    fpx = ids[yi, xi]
    same_pl = (face_n[fpx] * tx.N).sum(1) >= float(pd['plane_cos'])        # тот же наклон, что у грани под пикселем (спиной к камере и чужая плоскость не берутся)
    use = inside & sel[yi, xi] & np.isin(fgrp[fpx], gi) & same_pl
    info['funnel'] = {'texels_group': int(ing_t.sum()), 'inside_frame': int(inside.sum()), 'on_sel': int((inside & sel[yi, xi]).sum()), 'same_plane': int(use.sum()), 'sel_px': int(sel.sum()), 'ingrp_px': int(ingrp.sum())}
    n_use = int(use.sum())
    info.update(texels_in_group=int((np.isin(fgrp[f], gi)).sum()), texels_with_detail=n_use)
    if n_use == 0:
        info['reason'] = 'ни один тексель группы не лёг на «в лоб»'
        return tex_in, None
    d_t = map_coordinates(D.astype(np.float32), [y[use] - 0.5, x[use] - 0.5], order=1, mode='nearest')
    flat_new = tex_in.reshape(-1, 3).copy()
    base = tone_tex.reshape(-1, 3)[ti[use]]
    lab = TC.rgb2lab(base.astype(np.float64))
    lab[:, 0] = np.clip(lab[:, 0] + d_t, 0.0, 100.0)
    import tex_fill as TF
    rgb = TF.lab2rgb(lab)
    flat_new[ti[use]] = rgb
    msk = np.zeros(T * T, bool)
    msk[ti[use]] = True
    info.update(applied=True, detail_L_std=round(float(np.std(d_t)), 2), coarse_std=round(float(np.std(coarse[sel])), 2), fine_std=round(float(np.std(fine[sel])), 2), frame_px=int(sel.sum()))
    return flat_new.reshape(tex_in.shape), msk.reshape(T, T)


def thin_plate_step(tex, z, roles: list, V, g: dict, d: str, tp: dict, rep: dict):
    """Ф.7 «тонкая плита — один материал»: после зерна. → (текстура, маска перекрашенных | None). Нет роли «верх» / known.png — воздержание с причиной в след (текстура та же)."""
    import thin_plate as TPL
    from PIL import Image
    info = {'applied': False, 'reason': None}
    rep['thin_plate'] = info
    kp = os.path.join(d, 'known.png')
    top = [i for i, r in enumerate(roles) if r == 'top']
    if not top:
        info['reason'] = 'нет группы с ролью «верх»'
        return tex, None
    if not os.path.exists(kp):
        info['reason'] = 'нет known.png (маска «взято с фото»)'
        return tex, None
    known = np.asarray(Image.open(kp).convert('L')) > 127
    if known.shape != tex.shape[:2]:
        info['reason'] = 'known.png %s ≠ текстура %s' % (known.shape, tex.shape[:2])
        return tex, None
    uv = np.asarray(g['UV'], np.float64)
    uv_img = np.stack([uv[:, 0], 1.0 - uv[:, 1]], 1)                  # строка текстуры = v_glTF·T (trimesh отдаёт 1 − v)
    new, ch, inf = TPL.apply(tex, np.asarray(g['V'], np.float64), uv_img, np.asarray(g['F'], np.int64), np.asarray(z['face_group']).astype(np.int64), top[0], known, tp)
    info.update(inf)
    if not inf.get('applied'):
        return tex, None
    return new, ch


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
    if (rules.get('pattern_pick') or {}).get('enabled'):                    # T-99/12 шаг 2: образец библиотеки по РИСУНКУ фото, один на материал (выкл — строки не выполняются, выбор по тону как раньше)
        pick_by_passport(d, parts, rules, rep, Lf, valid, st, fgrp, roles, n3[:, 1], np.asarray(ph).shape, names)
    if (rules.get('pattern_measure') or {}).get('enabled'):                  # T-20261125-93/3: мера «есть рисунок» / «узор» по фото ДО тона Ш4а (выкл — строка не выполняется)
        rep['pattern_measure'] = measure_parts(d, parts, z, V, F, fp, pn, rules)
        import part_grain_measure as PGM_
        rep['pattern_measure_fields'] = PGM_.field_summary(parts, rules)       # T-93/6: счётчик «поле карточки для роли не найдено» / «роль не названа»
    axis_ctx = None
    ac = rules.get('axis_check') or {}
    if ac.get('enabled'):                                                  # T-20261124-57/5: контекст проверки оси зерна (кадр 04, фото) — только отчёт
        fr, _note = TV.cube_frame(geoms, st)
        if fr is not None and fr['C'] is not None:
            xs, ys, _Z = PF.project(fr['P'], fr['cam'])
            n_px = int(st['px'])
            axis_ctx = {'L': Lf, 'ids': st['ids'], 'valid': valid & (st['cos'] >= float(ac['cos_min'])), 'xy': np.stack([xs * n_px, ys * n_px], 1), 'P': P, 'F': F}
        else:
            rep['axis_check'] = 'нет перспективной камеры — проверка оси не считалась'
    face_part = None
    pnp = os.path.join(d, '..', '03-parts', 'parts.npz')                 # части этапа 3 (id на грань): ось зерна запасного пути — ось ДЕТАЛИ (rules.fallback_axis_per_part)
    if (rules.get('axis_per_part') or rules.get('fallback_axis_per_part')) and os.path.exists(pnp):
        fpz = np.asarray(np.load(pnp)['part']).astype(np.int64)
        face_part = fpz if len(fpz) == nF else None
    new, r = PG.apply_grain(tex, tx, parts, masks, fp, pn, cpu, width, rules, enabled=True, axis_ctx=axis_ctx, face_part=face_part)
    if (rules.get('amp_strip') or {}).get('enabled'):                     # T-99/11 шаг 4: размах по фото — второй проход с множителем на группу (выкл — строки не выполняются)
        ks = amp_from_strip(d, parts, new, rules, rep, tx=tx, fp=fp, masks=masks, face_part=face_part)
        if ks:
            plan2 = PG.plan_grain(parts, rules)
            for pid, kd in ks.items():
                if plan2.get(pid, {}).get('apply') and plan2[pid].get('amp') is not None:
                    plan2[pid]['plane_k'] = {int(g): float(v) for g, v in kd['planes'].items()}
                    plan2[pid]['plane_k_default'] = float(kd['k'])
            new, r = PG.apply_grain(tex, tx, parts, masks, fp, pn, cpu, width, rules, enabled=True, plan=plan2, axis_ctx=axis_ctx, face_part=face_part)
            rep['amp_strip_applied'] = {str(pid): {'часть': round(kd['k'], 3), 'плоскости': {str(g): round(v, 3) for g, v in kd['planes'].items()}} for pid, kd in ks.items()}
    rep['groups'] = {str(k): dict(v, name=names[k]) for k, v in r['parts'].items()}
    rep.update(applied=r['applied'], skipped=r['skipped'], texels_changed=r['texels_changed'], planes=int(len(pn)))
    pd_mask = None
    if (rules.get('photo_detail') or {}).get('enabled'):                    # T-99/12 шаг 5: рисунок с фото на лице группы (выкл — строки не выполняются)
        ppc_pd = 0.0
        pjp = os.path.join(d, 'part_material.json')
        if os.path.exists(pjp):
            with open(pjp, encoding='utf-8') as fh:
                ppc_pd = float(json.load(fh).get('px_per_cm') or 0.0) * int(st['px']) / float(max(np.asarray(ph).shape[0], np.asarray(ph).shape[1]))
        dpp = os.path.join(d, '..', '05-delight', 'delight.rgba.png')
        if ppc_pd <= 0:
            rep['photo_detail'] = {'applied': False, 'reason': 'нет px_per_cm в part_material.json'}
        else:
            if os.path.exists(dpp):
                rgb_d, _ok = TV.photo_to_frame(np.asarray(Image.open(dpp).convert('RGBA')), st['P'], int(st['px']))
                Ld_ = TC.rgb2lab(rgb_d.reshape(-1, 3)).reshape(int(st['px']), int(st['px']), 3)[..., 0]
                src_d = '05-delight (без теней)'
            else:
                Ld_, src_d = Lf, 'фото как есть (05 нет)'
            new, pd_mask = photo_detail_step(new, tex, tx, g, st, Ld_, valid, fgrp, names, ppc_pd, rules, rep, face_n=n3)
            rep['photo_detail']['source'] = src_d
    tp_mask = None
    if (rules.get('thin_plate') or {}).get('enabled'):                      # T-97/1 ф.7: тонкая плита — низ и торец тоном и волокном лица (выкл — строки не выполняются)
        new, tp_mask = thin_plate_step(new, z, roles, V, g, d, rules['thin_plate'], rep)
    if r['applied'] == 0 and tp_mask is None:
        raise Abstain('зерно не легло ни на одну группу (причины: %s)' % r['skipped'])
    if not os.path.exists(pre):
        shutil.copy2(vis, pre)                                       # исходник один раз; повторный запуск идёт от него
    swap_tex_glb(src, new, vis)
    gmap = np.asarray(z['group_map'])
    applied_g = [int(k) for k, v in r['parts'].items() if v.get('apply')]
    mk = np.isin(gmap, applied_g)                                    # метка «зерно уже есть»: 07 (заливка и верх top_prior) на этих текселях своей фактуры не кладёт
    if pd_mask is not None:
        mk = mk | pd_mask                                            # шаг 5: тексели с деталью фото — тоже «уже есть»
    if tp_mask is not None:
        mk = mk | tp_mask                                          # ф.7: перекрашенные низ/торец плиты — тоже «уже есть» (07 своей фактуры не кладёт)
    Image.fromarray((mk * 255).astype(np.uint8)).save(os.path.join(d, MASK))
    rep['mask_texels'] = int(mk.sum())
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
    if rep['abstain'] and os.path.exists(os.path.join(d, MASK)):
        os.remove(os.path.join(d, MASK))                              # воздержались — старой метки не оставляем (07 не должен пропускать фактуру там, где зерна нет)
    with open(os.path.join(d, OUT), 'w', encoding='utf-8') as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=1, default=float)
    print('part_grain:', 'зерно на %s групп' % rep.get('applied') if not rep['abstain'] else 'воздержался — ' + rep['abstain'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

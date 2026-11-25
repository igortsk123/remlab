#!/usr/bin/env python3
"""Этап «материал части» после 06 (T-20261124-63, Ш4а плана paint-material-01; правила — rules/part-material.json, расчёт — part_material.py).

ЗАЧЕМ. Роль-часть (верх, ножки, фасад, бок, зад) красится ОДНИМ ровным тоном «большинства» с фото своей плоскости (не кромки в тени), а не тексель за тексель, как у 06;
невидимое — по лесенке (бок своей полосой, зад = бок, иначе тон донора; донора нет — остаётся 06/07, пометка «не уверен»). Рисунок фасада — фото 06 на лицевой грани остаётся.

Что делает: читает `<run>/<sku>/06-visible/{visible.glb, known.png, conf.png, check.json}`, роли областей (`--roles-dir` с roles.json + roles-faces.npz, иначе считает
`parts_role_regions.build_roles` по `<run>/<sku>/03-parts`), камеру/кадр — этап 4 (`--pose-run`) и фото входа 06. Подбирает тон под светом сайта (model-viewer, кадр с камеры фото).
Исходные `visible.glb`/`known.png`/`conf.png` сохраняются как `*.pre-partmaterial.*` (повторный запуск идёт от них); этап 7 читает новый visible.glb, покрашенные тексели без фото — в tone_only.png (known/conf не меняются); для зерна — part_material_masks.npz
(07 их не перезаливает). След — `06-visible/part_material.json`: решение, причина, тон групп (доля главного кластера), кого красим/кто «не уверен», ΔE2000 и сдвиг оттенка кадр↔фото.
ВЫКЛЮЧЕНО (rules.enabled=false) — НИЧЕГО не пишет, код возврата 0: папка 06-visible байт в байт как без шага. Любая причина воздержаться (не тот тип, нет ролей/камеры/gltfpack,
рендер упал) — след с причиной, 06/07 красят как раньше, код возврата 0.

  python tools/scout/part_material_stage.py --run RUN --sku SKU --glb ПОДГОТОВЛЕННЫЙ.glb --photo ФОТО.png --pose-run ПАПКА_ПОЗЫ [--product-role РОЛЬ] [--roles-dir ПАПКА]
         [--channels a,b] [--channel-classes k=v,..] [--out-dir ПАПКА_ДЛЯ_ПРОБЫ]
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
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
sys.path.insert(0, os.path.join(HERE, '..', 'assets'))
import part_material as PM  # noqa: E402

VERSION = 1
STAGE_DIR = '06-visible'
OUT = 'part_material.json'
KEEP = {'visible.glb': 'visible.pre-partmaterial.glb', 'known.png': 'known.pre-partmaterial.png', 'conf.png': 'conf.pre-partmaterial.png'}


class Abstain(Exception):
    """Воздержание: причина идёт в след, 06/07 красят как раньше."""


def _json(path: str) -> dict:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def load_roles(a, glb: str, cam_az: float | None, nF: int) -> tuple[np.ndarray, np.ndarray, str]:
    """(роль по граням, conf, откуда). Готовые файлы — `--roles-dir`; иначе считаем по 03-parts."""
    rd = a.roles_dir
    if rd and os.path.exists(os.path.join(rd, 'roles-faces.npz')):
        z = np.load(os.path.join(rd, 'roles-faces.npz'), allow_pickle=True)
        return np.asarray(z['role']).astype(str), np.asarray(z['conf'], float), 'roles-dir'
    pd = os.path.join(a.run, a.sku, '03-parts')
    if not (os.path.exists(os.path.join(pd, 'parts.json')) and os.path.exists(os.path.join(pd, 'parts.npz'))):
        raise Abstain('нет ролей: ни --roles-dir, ни %s/parts.json+parts.npz' % pd)
    import parts_role_regions as PRR
    doc = json.load(open(os.path.join(pd, 'parts.json'), encoding='utf-8'))
    part = np.load(os.path.join(pd, 'parts.npz'))['part']
    names = [''] * (max(p['id'] for p in doc['parts']) + 1)
    for p in doc['parts']:
        names[p['id']] = p['name']
    v, f = PRR.load_mesh(glb)
    cc = dict(kv.split('=', 1) for kv in a.channel_classes.split(',') if '=' in kv and not kv.startswith('main='))
    res = PRR.build_roles(v, f, part, names, a.product_role or None, set(filter(None, a.channels.split(','))), cc, cam_az, glb=glb)
    return np.asarray(res['face_role']).astype(str), np.asarray(res['face_conf'], float), '03-parts'


def process(a, rules: dict, d: str, rep: dict) -> None:
    import parts_roles as PR
    import tex_visible as TV
    from PIL import Image
    t0 = time.time()
    grp = PR.group_of(a.product_role or None)
    rep['group'] = grp
    if grp not in rules['groups']:
        raise Abstain('тип «%s» (группа %s) вне rules.groups %s' % (a.product_role, grp, rules['groups']))
    vis = os.path.join(d, 'visible.glb')
    src_glb = os.path.join(d, KEEP['visible.glb']) if os.path.exists(os.path.join(d, KEEP['visible.glb'])) else vis
    if not os.path.exists(src_glb):
        raise Abstain('нет visible.glb этапа 6 (06 не дошёл)')
    chk = _json(os.path.join(d, 'check.json'))
    cam = ((chk.get('extra') or {}).get('camera')) or {}
    geoms = TV.load_shape(src_glb)
    if len(geoms) != 1:
        raise Abstain('в visible.glb %d геометрий, модуль берёт одну' % len(geoms))
    g = geoms[0]
    st = TV.load_stage(a.pose_run)
    st, _zi = TV.zbuffer_fix(geoms, st)
    if not st.get('camera') or st['camera'].get('az') is None:
        raise Abstain('нет камеры этапа 4 (az)')
    nF = len(g['F'])
    role, conf, rsrc = load_roles(a, a.glb, cam.get('az', st['camera'].get('az')), nF)
    if len(role) != nF:
        raise Abstain('роли на %d граней, меш 06 — %d (меши разошлись)' % (len(role), nF))
    rep['roles_from'] = rsrc
    flab, names = PM.role_groups(role, conf, rules)
    if not names:
        raise Abstain('ни одна роль не дала группу (unknown/conf < %s)' % rules['min_conf'])
    rep['groups'] = names
    n, area, _c = PM.face_geom(g['V'], g['F'])
    vis0 = st['mask'] & (st['ids'] >= 0)                                    # «внутренность» (ниша, проём, низ): тень по форме — тон по ним не материал, грани группе не принадлежат
    occl = PM.pixel_occlusion(st['depth'], vis0, st['cos'], st['px_len'], rules)
    inner, oinfo = PM.interior_faces(np.clip(st['ids'], 0, nF - 1), occl, vis0, nF, rules)
    inner = PM.interior_clusters(g['V'], g['F'], inner, area, rules)
    oinfo['граней_кусками'] = int(inner.sum())
    inner = PM.ring_faces(st['ids'], vis0, inner, nF, rules)
    inner = PM.grow_faces(g['V'], g['F'], inner, rules)
    flab = np.where(inner, len(names), flab).astype(np.int16)
    wk0 = os.path.join(d, '_partmaterial')
    os.makedirs(wk0, exist_ok=True)
    mp_ = np.full(st['ids'].shape + (3,), 255, np.uint8)                                # карта внутренности для просмотра (--keep-work): серое — группы, красное — внутренность, белое — вне объекта
    fid0 = np.clip(st['ids'], 0, nF - 1)
    mp_[vis0] = (200, 200, 200)
    mp_[vis0 & inner[fid0]] = (230, 40, 40)
    Image.fromarray(mp_).save(os.path.join(wk0, 'interior-map.png'))
    rep['interior'] = {**oinfo, 'граней_с_ростом': int(inner.sum()), 'доля_площади': round(float(area[inner].sum() / area.sum()), 4)}
    rep['area_share'] = {gn: round(float(area[flab == i].sum() / area.sum()), 4) for i, gn in enumerate(names)}
    P = np.asarray(Image.open(a.photo).convert('RGBA'))
    prgb, pmask = TV.photo_to_frame(P, st['P'], st['px'])
    ids, cosf = st['ids'], st['cos']
    valid = st['mask'] & pmask & (ids >= 0)
    fid = np.clip(ids, 0, nF - 1)
    pp = np.where(valid, flab[fid], -1)
    comp_px = PM.components(g['V'], g['F'])[fid]
    tones = PM.group_tones(prgb, pp, names, cosf, rules, comp_px)
    keep, borrowed, same = PM.pick_sources(tones, rules, rep['area_share'])
    rep['pattern_keep'] = sorted(keep)
    rep['borrowed'] = borrowed
    rep['same_as_facade'] = same
    if not any(t['own'] for t in tones.values()):
        raise Abstain('ни у одной группы нет своих чистых пикселей')
    ctl = np.asarray(g['tex'])
    if ctl.ndim != 3:
        raise Abstain('текстура 06 не прочиталась')
    ctl = ctl[..., :3].astype(np.uint8)
    T = ctl.shape[0]
    texmap = PM.uv_label_map(g['UV'], g['F'], flab, T)
    work = os.path.join(d, '_partmaterial')
    os.makedirs(work, exist_ok=True)
    fit, tl = rules['fit'], rules['tools']
    base, basel = os.path.join(work, 'base.glb'), os.path.join(work, 'basel.glb')
    if not PM.simplify(src_glb, base, rules):
        raise Abstain('нет gltfpack (%s) или он упал — кадры подбора не снять' % tl['gltfpack'])
    pal = np.array(rules['palette'], np.uint8)
    labtex = np.full((T, T, 3), 235, np.uint8)
    ok = texmap >= 0
    labtex[ok] = pal[texmap[ok] % len(pal)]
    PM.swap_tex_glb(base, labtex, basel, unlit=True)
    orb_cam = '%.2fdeg %.2fdeg %s' % (st['camera']['az'] % 360, 90 - st['camera']['el'], fit['radius'])
    S = int(fit['frame_px'])
    PM.render_jobs([{'glb': basel, 'out': os.path.join(work, 'm-cam.png'), 'orbit': orb_cam, 'size': S}, {'glb': basel, 'out': os.path.join(work, 'm-top.png'), 'orbit': fit['top_orbit'], 'size': S}], rules, work)
    lm_cam = PM.read_label_frame(np.asarray(Image.open(os.path.join(work, 'm-cam.png')).convert('RGB')), len(names), pal, fit['label_dist'])
    lm_top = PM.read_label_frame(np.asarray(Image.open(os.path.join(work, 'm-top.png')).convert('RGB')), len(names), pal, fit['label_dist'])

    def render_cam(tex: np.ndarray) -> np.ndarray:
        PM.swap_tex_glb(base, tex, os.path.join(work, 'it.glb'), rough=rules['unlit_roughness'])
        PM.render_jobs([{'glb': os.path.join(work, 'it.glb'), 'out': os.path.join(work, 'it-cam.png'), 'orbit': orb_cam, 'size': S}], rules, work)
        return np.asarray(Image.open(os.path.join(work, 'it-cam.png')).convert('RGB'))

    alb, hist = PM.fit_albedo(names, tones, borrowed, keep, texmap, ctl, render_cam, lm_cam, rules)
    tex, painted = PM.compose(ctl, texmap, names, alb, borrowed, keep)
    if not painted.any():
        raise Abstain('нечего красить: у групп нет ни своего тона, ни донора')
    kp0 = os.path.join(d, KEEP['known.png'])                                # известное фото (06): исходник, если шаг уже гонялся, иначе нынешний known.png
    kp0 = kp0 if os.path.exists(kp0) else os.path.join(d, 'known.png')
    kn0 = (np.asarray(Image.open(kp0).convert('L')) > 127) if os.path.exists(kp0) else np.zeros(painted.shape, bool)
    if kn0.shape != painted.shape:
        kn0 = np.zeros(painted.shape, bool)
    tex, det = PM.keep_details(tex, ctl, texmap, painted, kn0, names, keep, rules)       # лицо = тон + мелкие детали фото (щели, кромки, зерно)
    rep['details_texels'] = det
    # итоговые кадры для мерки и ворот «лицо против фото» (кадр до шага — фото 06 на той же геометрии)
    PM.swap_tex_glb(base, tex, os.path.join(work, 'fin.glb'), rough=rules['unlit_roughness'])
    PM.swap_tex_glb(base, ctl, os.path.join(work, 'ctl.glb'), rough=rules['unlit_roughness'])
    PM.render_jobs([{'glb': os.path.join(work, 'fin.glb'), 'out': os.path.join(work, 'fin-cam.png'), 'orbit': orb_cam, 'size': S}, {'glb': os.path.join(work, 'fin.glb'), 'out': os.path.join(work, 'fin-top.png'), 'orbit': fit['top_orbit'], 'size': S},
                    {'glb': os.path.join(work, 'ctl.glb'), 'out': os.path.join(work, 'ctl-cam.png'), 'orbit': orb_cam, 'size': S}], rules, work)
    import cv2
    pgs = [gi for gi, gn in enumerate(names) if gn not in keep and (gn in alb or borrowed.get(gn) in alb)]
    region = np.isin(lm_cam, pgs)
    if fit['erode_px']:
        region = cv2.erode(region.astype(np.uint8), np.ones((2 * int(fit['erode_px']) + 1,) * 2, np.uint8)).astype(bool)
    gate = PM.face_gate(np.asarray(Image.open(os.path.join(work, 'fin-cam.png')).convert('RGB')), np.asarray(Image.open(os.path.join(work, 'ctl-cam.png')).convert('RGB')), region, rules)
    rep['gate'] = gate
    if gate['fail']:
        raise Abstain('ворота «лицо против фото»: ' + '; '.join(gate['fail']))
    met = {}
    for gi, gn in enumerate(names):
        t = tones[gn]
        e = {'своих_px': t['n_all'], 'главный_кластер_доля': t['share'], 'px_главного': t['n_main'], 'свой_тон': t['own'], 'донор': borrowed.get(gn), 'рисунок_фото_оставлено': gn in keep}
        if t['own']:
            e['фото'] = {'L': round(float(t['lab'][0]), 1), 'C': round(PM.chroma(t['lab']), 1), 'h': round(PM.hue_of(t['lab']), 1)}
        for vw, lm in (('cam', lm_cam), ('top', lm_top)):
            if vw == 'top' and gn != 'верх':
                continue
            fr = np.asarray(Image.open(os.path.join(work, 'fin-%s.png' % vw)).convert('RGB'))
            px, _m = PM.part_pixels(fr, lm, [gi], fit['erode_px'])
            if len(px) < fit['min_frame_px']:
                px, _m = PM.part_pixels(fr, lm, [gi], 0)
            if len(px) < 10:
                continue
            lb = np.median(PM.lab_of(px), 0)
            m = {'L': round(float(lb[0]), 1), 'C': round(PM.chroma(lb), 1), 'h': round(PM.hue_of(lb), 1), 'n': int(len(px))}
            if t['own']:
                m['dE2000'] = round(float(PM.de2000(lb[None], t['lab'][None])[0]), 2)
                m['dL'] = round(float(lb[0] - t['lab'][0]), 1)
                m['dh'] = round(PM.hue_diff(PM.hue_of(lb), PM.hue_of(t['lab'])), 1)
            if gn == 'верх':
                L = PM.lab_of(px)
                m['белое'] = round(float(((L[:, 0] > rules['metrics']['white_l']) & (np.hypot(L[:, 1], L[:, 2]) < rules['metrics']['white_c'])).mean()), 3)
            e['кадр_' + vw] = m
        met[gn] = e
    rep['metrics'] = met
    chg = (tex != ctl).any(-1)                              # правило этапа: красим только свою заявленную маску; вне её — байт в байт
    rep['changed_outside_mask_texels'] = int((chg & ~painted).sum())
    pv = os.path.join(d, KEEP['known.png'].replace('known', 'prov'))
    pv0 = os.path.join(d, 'prov.png')
    pvp = pv if os.path.exists(pv) else pv0
    if os.path.exists(pvp):
        pa = np.asarray(Image.open(pvp))
        if pa.shape[:2] == painted.shape:
            ph = (pa >= 1) & (pa <= 3)
            rep['photo_texels_total'] = int(ph.sum())
            rep['photo_texels_replaced_in_mask'] = int((ph & chg).sum())
            rep['photo_texels_changed_outside_mask'] = int((ph & chg & ~painted).sum())
    rep['fit_iters'] = hist
    rep['painted_texel_share'] = round(float(painted.mean()), 4)
    # запись: исходники сохраняем один раз, дальше идём от них
    for name, keepname in KEEP.items():
        p = os.path.join(d, name)
        if os.path.exists(p) and not os.path.exists(os.path.join(d, keepname)):
            shutil.copy2(p, os.path.join(d, keepname))
    PM.swap_tex_glb(src_glb, tex, vis)
    # known/conf НЕ трогаем (фото-правда 06 как была: иначе 07 теряет «перёд/зад» по долям известного и красит поверх своего тона).
    # Покрашенные тексели БЕЗ фото — «тон-только» (tone_only.png, механизм 07 р.8): цвет остаётся как есть, 07 кладёт фактуру поверх, но не перекрашивает.
    kp = os.path.join(d, KEEP['known.png'])
    kn = (np.asarray(Image.open(kp).convert('L')) > 127) if os.path.exists(kp) else np.zeros(painted.shape, bool)
    to_p = os.path.join(d, 'tone_only.png')
    if os.path.exists(to_p) and not os.path.exists(os.path.join(d, 'tone_only.pre-partmaterial.png')):
        shutil.copy2(to_p, os.path.join(d, 'tone_only.pre-partmaterial.png'))
    base_to = os.path.join(d, 'tone_only.pre-partmaterial.png')
    t0m = (np.asarray(Image.open(base_to).convert('L')) > 127) if os.path.exists(base_to) else np.zeros(painted.shape, bool)
    tone_only = t0m | (painted & ~kn)
    Image.fromarray((tone_only * 255).astype(np.uint8)).save(to_p)
    mid = PM.material_ids(names, tones, borrowed, rules)             # материал по граням для мерки «ступени» 07: граница разных материалов — не скачок
    rep['materials'] = {gn: mid[i] for i, gn in enumerate(names)}
    fm = np.array(mid + [-1], np.int32)[np.asarray(flab)]
    np.savez_compressed(os.path.join(d, 'part_material_faces.npz'), face_material=fm)
    gtone = []                                                       # вход для зерна (T-69): карта части по текселям + плоский тон каждой группы (sRGB, как в текстуре) + материал
    for gi, gn in enumerate(names):
        src = gn if gn in alb else borrowed.get(gn)
        gtone.append(np.clip(PM.lin2srgb(alb[src]) + 0.5, 0, 255).astype(np.uint8) if (gn not in keep and src in alb) else np.array([0, 0, 0], np.uint8))
    np.savez_compressed(os.path.join(d, 'part_material_masks.npz'), group_map=np.where(painted, texmap, -1).astype(np.int16), names=np.array(names), tone_srgb=np.array(gtone, np.uint8),
                        roles=np.array([next((r for r, gg in rules['role_group'].items() if gg == gn), '') for gn in names]), texture_size=np.int32(painted.shape[0]), painted_group=np.array([bool(gn not in keep and (gn in alb or borrowed.get(gn) in alb)) for gn in names]), material=np.array(mid, np.int32), face_group=np.asarray(flab, np.int16))
    rep['tone_only_texels'] = int((painted & ~kn).sum())
    rep['known_texels_painted_flat'] = int((painted & kn).sum())
    rep['seconds'] = round(time.time() - t0, 1)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run', required=True)
    ap.add_argument('--sku', required=True)
    ap.add_argument('--glb', required=True, help='подготовленный меш этапа 2 (грани как у частей 03 и у visible.glb)')
    ap.add_argument('--photo', required=True)
    ap.add_argument('--pose-run', required=True)
    ap.add_argument('--product-role', default='')
    ap.add_argument('--roles-dir', default='')
    ap.add_argument('--channels', default='')
    ap.add_argument('--channel-classes', default='')
    ap.add_argument('--rules', default='')
    ap.add_argument('--out-dir', default='', help='папка 06-visible для пробы вместо <run>/<sku>/06-visible')
    ap.add_argument('--keep-work', action='store_true')
    a = ap.parse_args(argv)
    rules = PM.load_rules(a.rules or None)
    if not rules.get('enabled'):
        print('part_material: выключено (rules.enabled=false) — ничего не меняю')
        return 0
    d = a.out_dir or os.path.join(a.run, a.sku, STAGE_DIR)
    os.makedirs(d, exist_ok=True)
    rep = {'version': VERSION, 'rule': 'R-PART-MATERIAL', 'sku': a.sku, 'product_role': a.product_role, 'abstain': None}
    try:
        process(a, rules, d, rep)
    except Abstain as e:
        rep['abstain'] = str(e)
    except Exception as e:  # noqa: BLE001 — шаг не должен ронять конвейер: 06/07 красят как раньше, причина в след
        rep['abstain'] = 'сбой: %s: %s' % (type(e).__name__, e)
        traceback.print_exc()
    if not a.keep_work:
        shutil.rmtree(os.path.join(d, '_partmaterial'), ignore_errors=True)
    with open(os.path.join(d, OUT), 'w', encoding='utf-8') as f:
        json.dump(rep, f, ensure_ascii=False, indent=1, default=float)
    print('part_material:', 'красил %s' % rep.get('groups') if not rep['abstain'] else 'воздержался — ' + rep['abstain'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

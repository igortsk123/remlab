"""Материал части — тон роль-части одним цветом «большинства» (T-20261124-63, Ш4а плана paint-material-01; правила — rules/part-material.json).

ЗАЧЕМ. 06 переносит фото в развёртку тексель за тексель: тон верха берётся с кромки в тени (Крит — «лососевый»), у невидимых сторон — чужой тон (бок шкафа с тоном ниши), у ножек тон разный.
Здесь каждая РОЛЬ-часть (верх, ножки, фасад, бок, зад — роли областей `parts_role_regions`) красится ОДНИМ тоном; тон — «цвет большинства» (главный кластер Lab чистых пикселей фото своей
плоскости, тень/блик/захват соседа отброшены) и подбирается так, чтобы кадр модели под светом сайта с камеры фото совпал с фото (тон без запечённого света).

Чистые функции (тестируются без рендера): цвет, главный кластер, роли → группы, тон группы, донор невидимого, сборка текстуры; рендер подбора — через `render_fn`.
Чисел порогов и ID товаров здесь нет — `rules/part-material.json`. Модуль красит ТОЛЬКО тон; зерно/фактура — отдельный шаг (T-69), рисунок фасада — фото 06 остаётся.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'part-material.json')
sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))


def load_rules(path: str | None = None) -> dict:
    with open(path or RULES, encoding='utf-8') as f:
        return json.load(f)


# ───────────────────────────── цвет ─────────────────────────────

def srgb2lin(c) -> np.ndarray:
    c = np.asarray(c, np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def lin2srgb(x) -> np.ndarray:
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, 12.92 * x, 1.055 * x ** (1 / 2.4) - 0.055) * 255.0


def lab_of(rgb) -> np.ndarray:
    c = srgb2lin(rgb)
    m = np.array([[.4124, .3576, .1805], [.2126, .7152, .0722], [.0193, .1192, .9505]])
    x = c @ m.T / np.array([.9505, 1, 1.089])
    f = np.where(x > .008856, np.cbrt(x), 7.787 * x + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_lin(lin) -> np.ndarray:
    """Lab из линейного RGB (0…1)."""
    return lab_of(lin2srgb(np.asarray(lin, np.float64)))


def de2000(l1: np.ndarray, l2: np.ndarray) -> np.ndarray:
    """CIEDE2000 (Sharma 2005) для массивов Lab (…, 3)."""
    L1, a1, b1 = l1[..., 0], l1[..., 1], l1[..., 2]
    L2, a2, b2 = l2[..., 0], l2[..., 1], l2[..., 2]
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cm = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cm ** 7 / (Cm ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1 = np.degrees(np.arctan2(b1, a1p)) % 360
    h2 = np.degrees(np.arctan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = h2 - h1
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dH = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh) / 2)
    Lm, Cmp = (L1 + L2) / 2, (C1p + C2p) / 2
    hm = np.where(np.abs(h1 - h2) > 180, (h1 + h2 + 360) / 2, (h1 + h2) / 2)
    hm = np.where(C1p * C2p == 0, h1 + h2, hm)
    T = 1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm)) + 0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63))
    dth = 30 * np.exp(-(((hm - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cmp ** 7 / (Cmp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lm - 50) ** 2 / np.sqrt(20 + (Lm - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cmp, 1 + 0.015 * Cmp * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh))


def hue_of(lab: np.ndarray) -> float:
    return float(np.degrees(np.arctan2(lab[2], lab[1])) % 360)


def hue_diff(a: float, b: float) -> float:
    """Подписанная разность углов оттенка a − b в (−180, 180]."""
    return float(((a - b + 180) % 360) - 180)


def chroma(lab: np.ndarray) -> float:
    return float(np.hypot(lab[1], lab[2]))


def med_lin(px: np.ndarray) -> np.ndarray:
    return np.median(srgb2lin(px.reshape(-1, 3)), axis=0)


def main_cluster(px: np.ndarray, k: int = 3, sample: int = 40000) -> tuple[np.ndarray, float]:
    """px (N,3) sRGB → (маска главного кластера по Lab, его доля). k-means, главный — самый многочисленный."""
    import cv2
    lb = lab_of(px).astype(np.float32)
    n = len(lb)
    sub = lb if n <= sample else lb[np.random.RandomState(0).choice(n, sample, replace=False)]
    k = max(1, min(k, len(sub)))
    _, _, cen = cv2.kmeans(sub, k, None, (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1e-3), 3, cv2.KMEANS_PP_CENTERS)
    idx = ((lb[:, None, :] - cen[None]) ** 2).sum(-1).argmin(1)
    cnt = np.bincount(idx, minlength=k)
    mc = int(cnt.argmax())
    return idx == mc, float(cnt[mc] / n)


# ───────────────────────────── роли → группы ─────────────────────────────

def role_groups(face_role, face_conf, rules: dict) -> tuple[np.ndarray, list]:
    """Роль и conf по граням → (метка группы по грани, имена групп). Метка len(names) = «не красим» (роль вне таблицы, unknown, conf ниже min_conf)."""
    table = rules['role_group']
    names: list = []
    for v in table.values():
        if v not in names:
            names.append(v)
    lab = np.full(len(face_role), len(names), np.int16)
    for role, gname in table.items():
        sel = (np.asarray(face_role) == role) & (np.asarray(face_conf, float) >= float(rules['min_conf']))
        lab[sel] = names.index(gname)
    used = [i for i in range(len(names)) if (lab == i).any()]
    remap = {old: new for new, old in enumerate(used)}
    out = np.full(len(lab), len(used), np.int16)
    for old, new in remap.items():
        out[lab == old] = new
    return out, [names[i] for i in used]


# ───────────────────────────── геометрия ─────────────────────────────

def face_geom(V: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    e1, e2 = V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]]
    c = np.cross(e1, e2)
    area = 0.5 * np.linalg.norm(c, axis=1)
    return c / np.maximum(np.linalg.norm(c, axis=1, keepdims=True), 1e-12), area, V[F].mean(1)


def components(V: np.ndarray, F: np.ndarray) -> np.ndarray:
    """Связные куски меша (по сварке вершин) → номер куска у каждой грани."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    ext = V.max(0) - V.min(0)
    q = np.round(V / max(float(ext.max()) * 1e-5, 1e-12)).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    Fw = inv[F]
    nv = int(inv.max()) + 1
    a = coo_matrix((np.ones(len(F) * 3), (np.r_[Fw[:, 0], Fw[:, 1], Fw[:, 2]], np.r_[Fw[:, 1], Fw[:, 2], Fw[:, 0]])), shape=(nv, nv))
    _, lab_v = connected_components(a, directed=False)
    return lab_v[Fw[:, 0]]


def uv_label_map(UV: np.ndarray, F: np.ndarray, flab: np.ndarray, T: int) -> np.ndarray:
    """Метка грани → растр развёртки T×T (строка = (1 − uv_y)·T, как у текстуры 06), пропуски — ближайшей меткой."""
    import cv2
    from scipy.ndimage import distance_transform_edt
    m = np.full((T, T), -1, np.int16)
    uv = np.stack([UV[F][..., 0] * T, (1.0 - UV[F][..., 1]) * T], -1)
    pts = np.round(uv).astype(np.int32)
    for i in np.argsort(flab, kind='stable'):
        cv2.fillConvexPoly(m, pts[i], int(flab[i]))
    miss = m < 0
    if miss.any() and (~miss).any():
        _, (iy, ix) = distance_transform_edt(miss, return_indices=True)
        m = m[iy, ix]
    return m


# ───────────────────────────── тон группы ─────────────────────────────

def part_pixels(img: np.ndarray, pmap: np.ndarray, parts: list, erode: int, extra: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    import cv2
    m = np.isin(pmap, parts)
    if erode:
        m = cv2.erode(m.astype(np.uint8), np.ones((2 * erode + 1, 2 * erode + 1), np.uint8)).astype(bool)
    if extra is not None:
        m &= extra
    return img[m], m


def group_tones(prgb: np.ndarray, pp: np.ndarray, names: list, cosf: np.ndarray, rules: dict, comp_px: np.ndarray | None = None) -> dict:
    """Тон каждой группы по чистым пикселям фото. pp — метка группы на пиксель кадра (−1 — нет), comp_px — номер связного куска меша на пиксель (для «лучшей ножки»).
    → {группа: {n_all, n_main, share, ab_minor, own, lin, lab, best_leg_px?}}."""
    px_r = rules['pixels']
    out = {}
    for gi, gn in enumerate(names):
        info = {'n_all': 0, 'n_main': 0, 'share': None, 'ab_minor': None, 'own': False}
        px = np.zeros((0, 3), np.uint8)
        m = np.zeros(pp.shape, bool)
        for er in px_r['erode_px']:
            px, m = part_pixels(prgb, pp, [gi], er, extra=cosf >= px_r['cos_min'].get(gn, 0.3))
            if len(px) >= px_r['min_px']:
                break
        info['n_all'] = int(len(px))
        if len(px) >= px_r['min_px']:
            mm, share = main_cluster(px, px_r['kmeans_k'], px_r['kmeans_sample'])
            lb = lab_of(px)
            abm = np.median(lb[:, 1:], 0)
            minor = float((np.hypot(*(lb[:, 1:] - abm).T) > rules['pattern']['minor_ab_dist']).mean())
            sel = px[mm]
            info.update(n_main=int(mm.sum()), share=round(share, 3), ab_minor=round(minor, 3), own=True, lin=med_lin(sel), lab=np.median(lab_of(sel), 0))
            if gn in px_r['best_leg_groups'] and comp_px is not None:
                comp = comp_px[m]
                best, bn = None, 0
                for u in np.unique(comp):
                    kk = int(((comp == u) & mm).sum())
                    if kk > bn:
                        best, bn = u, kk
                if best is not None and bn >= px_r['best_leg_min_px']:
                    sel2 = px[(comp == best) & mm]
                    info.update(lin=med_lin(sel2), lab=np.median(lab_of(sel2), 0), best_leg_px=bn)
        out[gn] = info
    return out


def same_material(a: np.ndarray, b: np.ndarray, sm: dict) -> tuple[bool, str]:
    """Две поверхности — один материал? Цветные: угол оттенка и отношение C/L; нейтральные (бело-серо-чёрные): только близкие по светлоте (студийная тень бока темнее фасада на 10–15 L)."""
    ca, cb = chroma(a), chroma(b)
    if ca > sm['c_min'] and cb > sm['c_min']:
        dh = abs(hue_diff(hue_of(a), hue_of(b)))
        ra, rb = ca / max(a[0], 1), cb / max(b[0], 1)
        rc = abs(ra - rb) / max(rb, 1e-3)
        return bool(dh < sm['hue_deg'] and rc < sm['ratio_tol']), 'оттенок %.0f°' % dh
    dl = float(a[0] - b[0])
    return bool(abs(dl) <= sm['neutral_dl'] and max(ca, cb) <= sm['neutral_c']), 'нейтральные, ΔL %.1f' % dl


def pick_sources(tones: dict, rules: dict, area_share: dict | None = None) -> tuple[set, dict, dict]:
    """→ (группы с рисунком: фото 06 остаётся, {группа: донор | None}, {группа: «бок тот же материал, что фасад»}).
    Донор: нет своих пикселей → лесенка из rules.ladder; зад всегда по лесенке (зад = бок без рисунка); бок того же материала, что фасад, = тон фасада (студийная тень)."""
    keep, borrowed, same = set(), {}, {}
    pr = rules['pattern']
    for gn in pr['groups']:
        t = tones.get(gn)
        if t and t['own'] and t['ab_minor'] > pr['minor_share']:
            keep.add(gn)
            t['pattern'] = True
    lad = {k: v for k, v in rules['ladder'].items() if not k.startswith('_')}
    ash = area_share or {}

    def vis(g):                                                  # видимых пикселей на долю площади группы: у «корпуса» комода/шкафа — мизер (его почти не видно)
        return tones[g]['n_all'] / max(float(ash.get(g, 1.0)), 1e-6)
    big = max([vis(g) for g in tones if tones[g]['own']] or [0])
    weak = float(rules['pixels'].get('weak_share', 0))
    for gn, srcs in lad.items():
        if gn not in tones:
            continue
        is_weak = bool(tones[gn]['own'] and srcs and vis(gn) < weak * big and any(s in tones and tones[s]['own'] and vis(s) >= weak * big and s not in keep for s in srcs))
        if is_weak:
            tones[gn]['weak'] = True                              # своих пикселей мизер против главной группы: тон по ним ненадёжен — донор
        if (not tones[gn]['own']) or gn == 'зад' or is_weak:
            for s in srcs:
                if s in tones and tones[s]['own'] and s not in borrowed and s not in keep:
                    borrowed[gn] = s
                    break
    if 'бок' in tones and 'фасад' in tones and tones['бок']['own'] and tones['фасад']['own'] and 'бок' not in borrowed:
        ok, why = same_material(tones['бок']['lab'], tones['фасад']['lab'], rules['same_material'])
        same['бок'] = {'same': ok, 'why': why}
        if ok and 'фасад' not in keep:
            borrowed['бок'] = 'фасад'
    for gn in tones:
        if not tones[gn]['own'] and gn not in borrowed:
            borrowed[gn] = None
    for gn in list(borrowed):                                   # цепочка донора → итоговый тон (зад ← бок ← фасад = фасад)
        s, hops = borrowed[gn], 0
        while s is not None and s in borrowed and hops < 4:
            s, hops = borrowed[s], hops + 1
        borrowed[gn] = s
    gate = rules.get('ladder_gate') or {}
    refs = [g for g in ('фасад', 'верх', 'корпус') if g in tones and tones[g]['own'] and g not in borrowed and g not in keep]
    for gn, s in list(borrowed.items()):                        # ворота: тон донора далеко от лица/верха того же материала → не красим, «не уверен»
        if s is None or not refs or s in refs or 'max_de00' not in gate:
            continue
        de = float(de2000(tones[s]['lab'][None], tones[refs[0]]['lab'][None])[0])
        if de > float(gate['max_de00']) and not same_material(tones[s]['lab'], tones[refs[0]]['lab'], rules['same_material'])[0]:
            same['gate:' + gn] = {'donor': s, 'ref': refs[0], 'dE2000': round(de, 1), 'порог': gate['max_de00']}
            borrowed[gn] = None
    return keep, borrowed, same


# ───────────────────────────── текстура и подбор ─────────────────────────────

def compose(ctl: np.ndarray, texmap: np.ndarray, names: list, alb: dict, borrowed: dict, keep: set) -> tuple[np.ndarray, np.ndarray]:
    """Текстура: группа с тоном (своим или донора) — ровный цвет, остальное — как в 06. → (текстура, маска покрашенных текселей)."""
    tex = ctl.copy()
    painted = np.zeros(texmap.shape, bool)
    for gi, gn in enumerate(names):
        if gn in keep:
            continue
        src = gn if gn in alb else borrowed.get(gn)
        if src is None or src not in alb:
            continue
        col = np.clip(lin2srgb(alb[src]) + 0.5, 0, 255).astype(np.uint8)
        m = texmap == gi
        tex[m] = col
        painted |= m
    return tex, painted


def fit_albedo(names: list, tones: dict, borrowed: dict, keep: set, texmap: np.ndarray, ctl: np.ndarray, render_cam, label_map: np.ndarray, rules: dict) -> tuple[dict, list]:
    """Подбор альбедо по кадру под светом сайта: кадр с камеры фото (`render_cam(tex) → rgb`), метки групп на кадре — label_map (пиксель → группа). Альбедо *= тон фото / тон кадра."""
    fit = rules['fit']
    alb = {gn: tones[gn]['lin'].copy() for gn in names if tones[gn]['own'] and gn not in borrowed and gn not in keep}
    hist = []
    for _ in range(int(fit['iters'])):
        tex, _p = compose(ctl, texmap, names, alb, borrowed, keep)
        fr = render_cam(tex)
        row = {}
        for gn in list(alb):
            gi = names.index(gn)
            px, _m = part_pixels(fr, label_map, [gi], fit['erode_px'])
            if len(px) < fit['min_frame_px']:
                px, _m = part_pixels(fr, label_map, [gi], 0)
            if len(px) == 0:
                continue
            v = med_lin(px)
            row[gn] = round(float(lab_of(lin2srgb(v)[None])[0][0]), 1)
            alb[gn] = alb[gn] * np.clip(tones[gn]['lin'] / np.maximum(v, 1e-4), fit['clip'][0], fit['clip'][1])
        hist.append(row)
    return alb, hist


# ───────────────────────────── рендер (model-viewer) ─────────────────────────────

def node_env(root: str | None = None) -> dict:
    """Окружение для node: playwright рядом или по правилу node_fallback листа сторон (worktree без node_modules)."""
    env = dict(os.environ)
    try:
        sys.path.insert(0, os.path.join(HERE, '..', 'assets'))
        import sides_sheet as SS
        e, _log = SS.node_env(SS.load_rules(), root)
        return e
    except Exception:  # noqa: BLE001 — окружение не нашли: node попробует сам
        return env


def render_jobs(jobs: list, rules: dict, workdir: str, runner=None) -> None:
    """jobs: [{glb, out, orbit, size}] — один Chromium. runner(spec_path) → CompletedProcess (подмена в тестах)."""
    tl = rules['tools']
    spec = {'jobs': jobs, 'tools': {k: tl[k] for k in ('load_timeout_s', 'settle_ms', 'libs_model_viewer', 'light', 'chromium_args')}}
    sp = os.path.join(workdir, 'render-spec.json')
    with open(sp, 'w', encoding='utf-8') as f:
        json.dump(spec, f)
    js = os.path.join(HERE, 'part_material_render.js')
    r = (runner or (lambda s: subprocess.run([shutil.which(tl['node']) or tl['node'], js, s], capture_output=True, text=True, env=node_env(), timeout=3000)))(sp)
    if r.returncode:
        raise RuntimeError('рендер кадров: ' + (r.stdout + r.stderr)[-600:])


def simplify(src: str, dst: str, rules: dict) -> bool:
    gp = os.path.expanduser(rules['tools']['gltfpack'])
    if not os.path.exists(gp):
        return False
    r = subprocess.run([gp, '-i', src, '-o', dst, '-si', str(rules['fit']['simplify']), '-vp', '16', '-vt', '16'], capture_output=True, text=True)
    return os.path.exists(dst) and r.returncode == 0


def swap_tex_glb(src_glb: str, tex: np.ndarray, dst_glb: str, unlit: bool = False, rough: float | None = None) -> None:
    """GLB с той же геометрией, текстура заменена (PNG без потерь); unlit — метки групп без света."""
    import a1_tone as A
    from PIL import Image
    j, b = A.read_glb(src_glb)
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(tex)).save(buf, 'PNG')
    nj, nb = A.swap_texture(j, b, buf.getvalue())
    ii = A.base_color_image(nj)
    nj['images'][ii]['mimeType'] = 'image/png'
    for m in nj.get('materials', []):
        pm = m.setdefault('pbrMetallicRoughness', {})
        if rough is not None:
            pm['metallicFactor'] = 0.0
            pm['roughnessFactor'] = rough
        if unlit:
            m.setdefault('extensions', {})['KHR_materials_unlit'] = {}
    if unlit:
        nj['extensionsUsed'] = sorted(set(nj.get('extensionsUsed', []) + ['KHR_materials_unlit']))
    A.write_glb(dst_glb, nj, nb)


def read_label_frame(img: np.ndarray, n: int, palette: np.ndarray, dist: int) -> np.ndarray:
    """Кадр с цветными метками → номер группы на пиксель (−1 — фон/нет)."""
    a = img.astype(int)
    d = np.stack([np.abs(a - palette[k].astype(int)).sum(-1) for k in range(n)], -1)
    return np.where(d.min(-1) < dist, d.argmin(-1), -1)

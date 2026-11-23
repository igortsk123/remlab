#!/usr/bin/env python3
"""Мерки паспорта типа для товаров НОВОГО конвейера (T-20261123-19/1, П1.154, P-068; план ~/remlab-logs/t219-1123/plan.md).

ЗАЧЕМ. Дефекты «серый верх стола», «цвет ножек затёк на полки», «пустой вид залил плоскость серым» (паспорт `plans/mesh-type-rules-01.md`) ловились только на старых
моделях Hunyuan и только глазом. Здесь — три автомерки на ИТОГОВОМ GLB нового пути (этап 08, иначе 07), для этапа 9 (`paint_check.py`). Старые модели не чиним (TG 2063).

МЕРКИ (пороги — `rules/paint-surface-checks.json`, ID товаров в коде нет):
  top_vs_photo — ΔE2000 между медианой цвета плоского верха меша и медианой цвета того же верха на ФОТО. «Цвет на фото» = тексели верха, которые этап 6 взял с фото
                 (`known.png`: z-буфер камеры 04), у итогового GLB они равны фото. Верх — по ГЕОМЕТРИИ (горизонтальные грани у верхней границы корпуса, нормаль вверх
                 ≤ 10°), класс каталога не решает. Верх не виден на фото (мало известных текселей) → `na` (в знаменатель не идёт).
  group_bleed  — доля текселей группы A (часть этапа 8 `parts08.npz`; иначе части этапа 3; иначе плоские панели по геометрии), чей цвет ближе к медиане другой группы B,
                 чем к своей: пятна дерева ножек на белых полках. Считаем в ЗАЛИТЫХ этапом 7 текселях (known — справочно); без эрозии (пятна сидят у границ островов).
  empty_flat   — плоская область цвета «пустого вида» сети (все каналы 124–134, σ ≤ 2, MR ≈ 0,5/0,5), которая расходится с фото. `_ViewGuard` живёт в Hunyuan-пути
                 (`salad/pipeline.py`); в Trellis-пути этапов 06/07 его нет — эта мерка смотрит на готовый GLB, а не на вид сети.

  paint_surface_checks.py run <glb> [--known known.png] [--parts parts08.npz] [--out surface.json]    разбор одного GLB
  paint_surface_checks.py --selftest                                                                  без trimesh/сети: синтетические атласы
Из кода этапа 9: `classify(glb, known_png, parts_path, rules_all, out_dir)` → словарь статуса как у `classify_palette`.
"""
from __future__ import annotations

import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
RULES = os.path.join(HERE, 'rules', 'paint-surface-checks.json')


def rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


# --------------------------------------------------------------------------------------------- цвет -----------
def _tc():
    """Lab и ΔE2000 — из `tex_coverage` (одна реализация на этап 9), импорт отложен: тяжёлые зависимости только здесь."""
    sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
    import tex_coverage as TC  # noqa: E402
    return TC


def lab_of(rgb) -> np.ndarray:
    return _tc().rgb2lab(np.asarray(rgb, np.uint8).reshape(-1, 3))


def de00(l1, l2) -> float:
    return float(_tc().de2000_v(np.asarray(l1, float).reshape(1, 3), np.asarray(l2, float).reshape(1, 3))[0])


def median_rgb(px: np.ndarray) -> list:
    return [int(v) for v in np.median(px.reshape(-1, 3), axis=0)]


# --------------------------------------------------------------------------------------------- модель ----------
def load_model(glb: str) -> dict:
    """Самая большая геометрия с текстурой и UV: вершины, грани (порядок как в файле — по нему лежат части этапа 8), альбедо, MR (если есть)."""
    import trimesh
    sc = trimesh.load(glb, force='scene', process=False)
    best = None
    for g in sc.geometry.values():
        vis = getattr(g, 'visual', None)
        mat = getattr(vis, 'material', None)
        tex = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
        uv = getattr(vis, 'uv', None)
        if tex is not None and uv is not None and (best is None or len(g.faces) > len(best[0].faces)):
            best = (g, mat, tex, uv)
    if best is None:
        raise ValueError('в GLB нет геометрии с текстурой и развёрткой')
    g, mat, tex, uv = best
    mr = getattr(mat, 'metallicRoughnessTexture', None)
    return {'V': np.asarray(g.vertices, float), 'F': np.asarray(g.faces, int), 'UV': np.asarray(uv, float), 'albedo': np.asarray(tex.convert('RGB'), np.uint8),
            'mr': None if mr is None else np.asarray(mr.convert('RGB'), np.uint8)}


def _scale(img: np.ndarray, work_px: int, nearest: bool = False) -> tuple[np.ndarray, float]:
    from PIL import Image
    h, w = img.shape[:2]
    sc = min(1.0, work_px / max(h, w))
    if sc >= 1.0:
        return img, 1.0
    im = Image.fromarray(img).resize((max(1, int(w * sc)), max(1, int(h * sc))), Image.NEAREST if nearest else Image.BOX)
    return np.asarray(im), sc


def _fit_mask(mask: np.ndarray, shape: tuple) -> np.ndarray:
    """Маска известных текселей этапа 6 — на сетку итоговой текстуры (размеры могут отличаться: ближайший сосед)."""
    from PIL import Image
    if mask.shape[:2] == tuple(shape[:2]):
        return mask
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).resize((shape[1], shape[0]), Image.NEAREST)) > 127


def load_known(path: str | None, thr: int = 127) -> np.ndarray | None:
    if not path or not os.path.exists(path):
        return None
    from PIL import Image
    a = np.asarray(Image.open(path))
    if a.ndim == 3:
        a = a[..., 0]
    return a > thr


def load_parts(path: str | None, n_faces: int) -> tuple[np.ndarray | None, str]:
    """Группа на грань: `parts08.npz` (ключ `part`) или части этапа 3 (`parts.npz`); число граней не сошлось — нет (фолбэк по геометрии)."""
    if path and os.path.exists(path):
        z = np.load(path)
        key = 'part' if 'part' in z.files else z.files[0]
        p = np.asarray(z[key]).astype(int).ravel()
        if len(p) == n_faces:
            return p, os.path.basename(path)
    return None, ''


# ------------------------------------------------------------------------------------------ геометрия ---------
def top_rules(R: dict) -> dict:
    """Правила `mesh_grey_top.top_faces` из наших порогов: нормаль вверх не дальше angle_deg_max от вертикали."""
    t = R['top']
    return {'up_cos': float(np.cos(np.radians(t['angle_deg_max']))), 'band': t['band'], 'side_ny': 0.3}


def face_normals_areas(V: np.ndarray, F: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    cr = np.cross(b - a, c - a)
    ln = np.linalg.norm(cr, axis=1)
    return cr / np.maximum(ln[:, None], 1e-12), ln / 2


def flat_panels(V: np.ndarray, F: np.ndarray, ang_deg: float, min_frac: float) -> list:
    """Плоские панели по геометрии: связные области граней (излом ≤ ang) с согласованной нормалью, площадь ≥ min_frac поверхности. -> [(индексы граней, нормаль)]."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    import trimesh
    n, ar = face_normals_areas(V, F)
    tm = trimesh.Trimesh(V, F, process=False)
    adj, ang = tm.face_adjacency, tm.face_adjacency_angles
    ok = ang < np.radians(ang_deg)
    g = coo_matrix((np.ones(int(ok.sum())), (adj[ok, 0], adj[ok, 1])), shape=(len(F), len(F)))
    nc, comp = connected_components(g, directed=False)
    tot = ar.sum()
    out = []
    for ci in range(nc):
        m = comp == ci
        a = ar[m].sum()
        if a / tot < min_frac:
            continue
        mn = (n[m] * ar[m, None]).sum(axis=0)
        mn /= max(np.linalg.norm(mn), 1e-9)
        if float(((n[m] @ mn) * ar[m]).sum() / a) < 0.95:
            continue
        out.append((np.where(m)[0], mn))
    return out


# --------------------------------------------------------------------------------------- мерка 1: верх ↔ фото
def top_vs_photo(M: dict, known: np.ndarray | None, R: dict) -> dict:
    import mesh_grey_top as G
    c = R['top_vs_photo']
    t = R['top']
    V, F, UV, alb = M['V'], M['F'], M['UV'], M['albedo']
    top, side, ta, foot = G.top_faces(V, F, top_rules(R))
    if not len(top) or foot <= 0 or ta < t['min_top_frac'] * foot:
        return {'status': 'na', 'why': 'нет плоского верха по геометрии'}
    alb_w, sc = _scale(alb, t['work_px'])
    h, w = alb_w.shape[:2]
    other = np.setdiff1d(np.arange(len(F)), top)
    m_top = G._raster(UV, F[top], w, h)
    m_oth = G._raster(UV, F[other], w, h) if len(other) else np.zeros_like(m_top)
    inner = G._erode(m_top & ~m_oth, t['erode_px'])
    n_top = int(inner.sum())
    if n_top < t['min_texels']:
        return {'status': 'na', 'why': 'верх занимает слишком мало текселей', 'texels': n_top}
    mesh_rgb = median_rgb(alb_w[inner])
    out = {'status': 'ok', 'texels': n_top, 'rgb_mesh': mesh_rgb, 'top_area_share_of_foot': round(ta / foot, 3)}
    if known is None:
        return {**out, 'status': 'na', 'why': 'нет known.png этапа 6 — нечем взять цвет верха с фото'}
    kn = _fit_mask(known, (h, w))
    kt = inner & kn
    n_kn = int(kt.sum())
    out.update(known_texels=n_kn, known_share=round(n_kn / n_top, 3))
    if n_kn < c['min_known_texels'] * (sc * sc) or n_kn < c['min_known_share'] * n_top:
        return {**out, 'status': 'na', 'why': 'верх не виден на фото (этап 6 не взял с него тексели)'}
    photo_rgb = median_rgb(alb_w[kt])
    la, lb = lab_of(mesh_rgb)[0], lab_of(photo_rgb)[0]
    out.update(rgb_photo=photo_rgb, dE00=round(de00(la, lb), 2), dL=round(float(la[0] - lb[0]), 2), dab=round(float(np.hypot(la[1] - lb[1], la[2] - lb[2])), 2))
    return out


# ----------------------------------------------------------------------------------- мерка 3: пустой вид (плоскость)
def empty_flat(M: dict, known: np.ndarray | None, R: dict, top_res: dict | None = None) -> dict:
    import mesh_grey_top as G
    c = R['empty_flat']
    t = R['top']
    V, F, UV, alb, mr = M['V'], M['F'], M['UV'], M['albedo'], M['mr']
    panels = flat_panels(V, F, c['flat_angle_deg_max'], c['min_part_frac'])
    if not panels:
        return {'status': 'na', 'why': 'нет крупных плоских областей'}
    alb_w, sc = _scale(alb, t['work_px'])
    mr_w = None if mr is None else _scale(mr, t['work_px'])[0]
    h, w = alb_w.shape[:2]
    masks = [G._raster(UV, F[idx], w, h) for idx, _ in panels]
    all_surface = G._raster(UV, F, w, h)
    kn = None if known is None else _fit_mask(known, (h, w))
    body_med = None
    if kn is not None and (kn & all_surface).sum() > 500:
        body_med = lab_of(median_rgb(alb_w[kn & all_surface]))[0]
    parts, empty_texels = [], 0
    for k, (idx, nrm) in enumerate(panels):
        others = np.zeros_like(masks[k])
        for j, mk in enumerate(masks):
            if j != k:
                others |= mk
        inner = G._erode(masks[k] & ~others, t['erode_px'])
        n = int(inner.sum())
        if n < c['min_part_texels'] * (sc * sc):
            continue
        px = alb_w[inner].astype(int)
        in_grey = ((px >= c['grey_lo']) & (px <= c['grey_hi'])).all(axis=1)
        share = float(in_grey.mean())
        std = float(px[in_grey].std(axis=0).mean()) if in_grey.any() else None
        mr_flat = None
        if mr_w is not None:
            q = mr_w[inner].astype(int)
            mr_flat = float(((q[:, 1] >= c['mr_lo']) & (q[:, 1] <= c['mr_hi']) & (q[:, 2] >= c['mr_lo']) & (q[:, 2] <= c['mr_hi'])).mean())
        row = {'faces': int(len(idx)), 'ny': round(float(nrm[1]), 2), 'texels': n, 'grey_share': round(share, 3), 'grey_std': None if std is None else round(std, 2), 'mr_flat': None if mr_flat is None else round(mr_flat, 3)}
        grey = share >= c['min_share_of_part'] and std is not None and std <= c['std_max'] and (mr_flat is None or mr_flat >= c['min_share_of_part'])
        row['grey_flat'] = bool(grey)
        if grey:
            ref, how = None, ''
            if kn is not None and (inner & kn).sum() >= 300:
                ref, how = lab_of(median_rgb(alb_w[inner & kn]))[0], 'известные тексели этой же области'
            elif body_med is not None:
                ref, how = body_med, 'известные тексели корпуса'
            gl = lab_of([128, 128, 128])[0]
            d = None if ref is None else de00(gl, ref)
            row.update(photo_ref=how or 'нет', dE00_to_photo=None if d is None else round(d, 2))
            row['disagrees'] = bool(d is None or d > c['photo_dE00'])
            if row['disagrees']:
                empty_texels += int(round(n / (sc * sc)))
        parts.append(row)
    if not parts:
        return {'status': 'na', 'why': 'плоские области слишком малы'}
    tot = int(round(all_surface.sum() / (sc * sc)))
    return {'status': 'ok', 'empty_pct': round(100.0 * empty_texels / max(tot, 1), 3), 'empty_parts': sum(1 for p in parts if p.get('disagrees')), 'parts': parts}


# ------------------------------------------------------------------------------- мерка 2: затёк между группами
def _geometry_groups(M: dict, R: dict) -> np.ndarray:
    """Запасные группы, пока нет parts08/этапа 3: крупные плоские панели по геометрии (по одной группе на панель), остальное — группа −1 (не судим)."""
    out = np.full(len(M['F']), -1, int)
    for i, (idx, _) in enumerate(flat_panels(M['V'], M['F'], 15.0, 0.02)):
        out[idx] = i
    return out


def group_bleed(M: dict, known: np.ndarray | None, part: np.ndarray | None, R: dict) -> dict:
    import mesh_grey_top as G
    from scipy import ndimage
    c = R['group_bleed']
    V, F, UV, alb = M['V'], M['F'], M['UV'], M['albedo']
    src = 'parts'
    if part is None:
        part, src = _geometry_groups(M, R), 'geometry'
    ids = [int(g) for g in np.unique(part) if g >= 0]
    if len(ids) < 2:
        return {'status': 'na', 'why': 'меньше двух групп', 'groups_source': src}
    alb_w, sc = _scale(alb, c['work_px'])
    h, w = alb_w.shape[:2]
    kn = None if known is None else _fit_mask(known, (h, w))
    masks = {g: G._raster(UV, F[part == g], w, h) for g in ids}
    solo = {}
    for g in ids:
        others = np.zeros((h, w), bool)
        for j in ids:
            if j != g:
                others |= masks[j]
        solo[g] = G._erode(masks[g] & ~others, c['edge_erode_px'])    # без шва (тексели, куда ложится и чужая группа) и без крайнего пикселя острова (кромка смешана с полем); глубже не стираем: пятна сидят у границ (T-16)
    lab_all = None
    info = {}
    for g in ids:
        n = int(solo[g].sum())
        if n < c['min_group_texels'] * (sc * sc):
            continue
        lab = lab_of(alb_w[solo[g]])
        info[g] = {'n': n, 'med': np.median(lab, axis=0)}
    gids = sorted(info)
    rows = []
    best = 0.0
    for a in gids:
        ys, xs = np.nonzero(solo[a])
        labA = lab_of(alb_w[ys, xs])
        dA = np.linalg.norm(labA - info[a]['med'], axis=1)
        pair_leak = {}
        for b in gids:
            if b == a:
                continue
            if de00(info[a]['med'], info[b]['med']) <= c['pair_min_dE00']:
                continue
            dB = np.linalg.norm(labA - info[b]['med'], axis=1)
            pair_leak[b] = (dB < dA) & (dA > c['t_far_dE76'])
        if not pair_leak:
            continue
        for b, leak in pair_leak.items():
            mask = np.zeros((h, w), bool)
            mask[ys[leak], xs[leak]] = True
            lab_img, nb = ndimage.label(mask)
            if nb:
                sz = ndimage.sum(mask, lab_img, index=np.arange(1, nb + 1))
                keep = np.isin(lab_img, np.where(sz >= c['min_blob'] * (sc * sc))[0] + 1)
                mask = keep
            known_a = np.zeros((h, w), bool) if kn is None else solo[a] & kn
            filled_a = solo[a] & ~known_a
            nf, nk = int(filled_a.sum()), int(known_a.sum())
            leak_f, leak_k = int((mask & filled_a).sum()), int((mask & known_a).sum())
            inner = G._erode(solo[a], c['border_px'])
            near = solo[a] & ~inner
            n_leak = int(mask.sum())
            row = {'A': a, 'B': b, 'dE00_AB': round(de00(info[a]['med'], info[b]['med']), 1), 'texels_A': info[a]['n'], 'filled_A': nf, 'leak_filled': leak_f, 'leak_known': leak_k,
                   'share_filled_pct': round(100.0 * leak_f / nf, 4) if nf >= c['min_blob'] else None, 'share_known_pct': round(100.0 * leak_k / nk, 4) if nk >= c['min_blob'] else None,
                   'near_border_share': round(float((mask & near).sum() / max(n_leak, 1)), 3), 'rgb_A': [int(v) for v in lab_to_rgb(info[a]['med'])], 'rgb_B': [int(v) for v in lab_to_rgb(info[b]['med'])]}
            rows.append(row)
            if row['share_filled_pct'] is not None:
                best = max(best, row['share_filled_pct'])
    rows.sort(key=lambda r: -(r['share_filled_pct'] or 0))
    return {'status': 'ok', 'groups_source': src, 'groups': len(gids), 'value_pct': round(best, 4), 'pairs': rows[:12]}


def lab_to_rgb(lab) -> np.ndarray:
    lab = np.asarray(lab, float).reshape(-1, 3)
    fy = (lab[:, 0] + 16) / 116
    fx, fz = fy + lab[:, 1] / 500, fy - lab[:, 2] / 200
    f3 = lambda t: np.where(t ** 3 > 216 / 24389, t ** 3, (116 * t - 16) / (24389 / 27))  # noqa: E731
    xyz = np.stack([f3(fx) * 0.95047, f3(fy), f3(fz) * 1.08883], 1)
    M = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    lin = np.clip(xyz @ M.T, 0, 1)
    c = np.where(lin <= 0.0031308, 12.92 * lin, 1.055 * lin ** (1 / 2.4) - 0.055)
    return np.clip(np.round(c * 255), 0, 255)[0]


# ------------------------------------------------------------------- мерка 4: пятна «светлее фото» (T-187/1)
def lighter_than_photo(glb: str, photo: str | None, pose_run: str | None, R: dict) -> dict:
    """`tex_fill.lighter_than_photo_share` по ИТОГОВОЙ текстуре и фото в кадре камеры 04 (в check 07 её никто не звал — аудит 23.11, п.3). Пороги «пятна» — paint-fill.json `lighter_than_photo`,
    допустимая доля — paint-fill.json `thresholds.lighter_than_photo_pct`: здесь своих чисел нет. Нет растра камеры (pose_run) или фото → na, не «ок»."""
    if not photo or not os.path.exists(photo):
        return {'status': 'na', 'why': 'нет фото товара'}
    if not pose_run or not os.path.exists(os.path.join(pose_run, 'stage_loss.json')):
        return {'status': 'na', 'why': 'нет растра камеры этапа 4 (pose_run) — кадр итога не собрать'}
    from PIL import Image
    sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
    import tex_fill as TF  # noqa: E402
    import tex_visible as TV  # noqa: E402
    st = TV.load_stage(pose_run)
    geoms = TV.load_shape(glb)
    if sum(len(g['F']) for g in geoms) <= int(st['ids'].max()):
        return {'status': 'na', 'why': 'грани итога не совпадают с растром камеры (другая форма)'}
    prgb, pmask = TV.photo_to_frame(np.asarray(Image.open(photo).convert('RGBA')), st['P'], st['px'])
    after = TV.frame_from_tex(st, geoms, [g['tex'] for g in geoms])
    r = TF.lighter_than_photo_share(after, prgb, st['mask'] & pmask)
    op, thr = TF.THRESHOLDS['lighter_than_photo_pct']
    return {'status': 'ok', 'share_pct': r['share_pct'], 'inner_px': r['inner_px'], 'spot_px': r['spot_px'], 'threshold': [op, thr]}


# ---------------------------------------------------------------------------------------------- всё вместе ---
def role_mismatch(top_res: dict, role: str | None, R: dict) -> dict:
    """Геометрия против класса каталога (директор 23.11): класс — ПОДСКАЗКА, решает геометрия; расхождение — флаг в surface.json, в гейт НЕ идёт.
    has_top — найден плоский верх по геометрии; hint — класс из списка «у таких типов верх важен» (rules `applies_to_hint.top_vs_photo`)."""
    has_top = top_res.get('why') != 'нет плоского верха по геометрии'
    if not role:
        return {'flag': False, 'has_top': has_top, 'role': None, 'why': 'класс каталога не передан'}
    hint = any(h in str(role).lower() for h in R['applies_to_hint']['top_vs_photo'])
    flag = has_top != hint
    why = '' if not flag else ('плоский верх по геометрии есть, а класс не из списка «верх важен»' if has_top else 'класс из списка «верх важен», а плоского верха по геометрии нет')
    return {'flag': flag, 'has_top': has_top, 'hint_class': hint, 'role': role, 'why': why}


def measure(glb: str, known_png: str | None = None, parts_path: str | None = None, R: dict | None = None, photo: str | None = None, pose_run: str | None = None, role: str | None = None) -> dict:
    R = R or rules()
    t0 = time.time()
    tm = {}
    M = load_model(glb)
    known = load_known(known_png, R['top_vs_photo']['known_thr'])
    part, psrc = load_parts(parts_path, len(M['F']))
    tm['load'] = round(time.time() - t0, 2)
    res = {'version': R['version'], 'glb': os.path.basename(glb), 'faces': int(len(M['F']))}
    t1 = time.time()
    res['top_vs_photo'] = top_vs_photo(M, known, R)
    tm['top_vs_photo'] = round(time.time() - t1, 2)
    t1 = time.time()
    res['empty_flat'] = empty_flat(M, known, R, res['top_vs_photo'])
    tm['empty_flat'] = round(time.time() - t1, 2)
    t1 = time.time()
    res['group_bleed'] = group_bleed(M, known, part, R)
    res['group_bleed']['parts_file'] = psrc
    tm['group_bleed'] = round(time.time() - t1, 2)
    t1 = time.time()
    try:
        res['lighter_than_photo'] = lighter_than_photo(glb, photo, pose_run, R)
    except Exception as e:  # noqa: BLE001 — мерка не измерена: так и пишем, остальные идут
        res['lighter_than_photo'] = {'status': 'error', 'why': f'{type(e).__name__}: {str(e)[:120]}'}
    tm['lighter_than_photo'] = round(time.time() - t1, 2)
    res['timing_s'] = tm
    res['role_mismatch'] = role_mismatch(res['top_vs_photo'], role, R)
    res['seconds'] = round(time.time() - t0, 1)
    return res


def judge(m: dict, R: dict) -> dict:
    """Метрики с порогами для `paint_stage.write_check` и итог: status ok | soft | refused | na. `na` — не судим, это не отказ."""
    ms, hard, soft = {}, [], []
    t = m['top_vs_photo']
    if t.get('status') == 'ok' and 'dE00' in t:
        op, thr = R['top_vs_photo']['threshold']
        ok = t['dE00'] <= thr
        ms['top_vs_photo_dE00'] = {'value': t['dE00'], 'threshold': thr, 'op': op, 'ok': ok}
        if not ok:
            (soft if R['top_vs_photo'].get('soft') else hard).append('top_vs_photo')
    e = m['empty_flat']
    if e.get('status') == 'ok':
        op, thr = R['empty_flat']['threshold']
        ok = e['empty_pct'] <= thr
        ms['empty_flat_pct'] = {'value': e['empty_pct'], 'threshold': thr, 'op': op, 'ok': ok}
        if not ok:
            (soft if R['empty_flat'].get('soft') else hard).append('empty_flat')
    g = m['group_bleed']
    if g.get('status') == 'ok':
        op, thr = R['group_bleed']['threshold']
        ok = g['value_pct'] <= thr
        ms['group_bleed_pct'] = {'value': g['value_pct'], 'threshold': thr, 'op': op, 'ok': ok}
        if not ok:
            (soft if R['group_bleed'].get('soft') else hard).append('group_bleed')
    lt = m.get('lighter_than_photo') or {}
    if lt.get('status') == 'ok':
        op, thr = lt['threshold']
        ok = lt['share_pct'] <= thr
        ms['lighter_than_photo_pct'] = {'value': lt['share_pct'], 'threshold': thr, 'op': op, 'ok': ok}
        if not ok:
            (soft if R['lighter_than_photo'].get('soft') else hard).append('lighter_than_photo')
    for key, mk in (('top_vs_photo', 'top_vs_photo_dE00'), ('empty_flat', 'empty_flat_pct'), ('group_bleed', 'group_bleed_pct'), ('lighter_than_photo', 'lighter_than_photo_pct')):
        r = m.get(key) or {}
        if mk not in ms:                                     # не измерено — пишем ПОЧЕМУ: этап 9 различает «не применимо» (na) и «не посчитано» (error/нет данных)
            ms[mk] = {'value': None, 'ok': None, ('na' if r.get('status') == 'na' else 'error'): r.get('why') or 'нет результата мерки'}
    status = 'refused' if hard else 'soft' if soft else 'ok'
    return {'status': status, 'metrics': ms, 'hard_failed': hard, 'soft_failed': soft}


def classify(glb: str | None, known_png: str | None, parts_path: str | None, rules_all: dict | None = None, out_dir: str | None = None, fn=None, photo: str | None = None, pose_run: str | None = None, role: str | None = None) -> dict:
    """Статус для этапа 9 (форма как у `classify_palette`): сторож упал или нет GLB → missing, не «ок»."""
    out = {'stage': 'surface', 'status': 'missing', 'reason': 'нет итогового GLB (этап 08/07 не выдал файл)', 'hard_failed': [], 'soft_failed': [], 'metrics': {}, 'glb': glb}
    R = rules()
    if not R.get('enabled', True):
        out.update(status='ok', reason='')
        return out
    if not glb:
        return out
    try:
        m = (fn or measure)(glb, known_png, parts_path, R, photo, pose_run, role)
    except Exception as e:  # noqa: BLE001 — сторож упал: нет измерения, не «ок»
        out['reason'] = f'мерки поверхности упали: {type(e).__name__}: {str(e)[:120]}'
        return out
    j = judge(m, R)
    out.update(status=j['status'], metrics=j['metrics'], hard_failed=j['hard_failed'], soft_failed=j['soft_failed'], detail=m)
    why = []
    for k in j['hard_failed'] + j['soft_failed']:
        mm = {'top_vs_photo': 'top_vs_photo_dE00', 'empty_flat': 'empty_flat_pct', 'group_bleed': 'group_bleed_pct', 'lighter_than_photo': 'lighter_than_photo_pct'}[k]
        why.append(f"{mm} {j['metrics'][mm]['value']} > {j['metrics'][mm]['threshold']}")
    out['reason'] = '; '.join(why)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, 'surface.json'), 'w', encoding='utf-8') as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
    return out


# ------------------------------------------------------------------------------------------------ selftest ---
def selftest() -> int:
    """Без trimesh/сети: Lab/ΔE и чистая логика судьи на синтетике."""
    R = rules()
    assert abs(de00(lab_of([128, 128, 128])[0], lab_of([128, 128, 128])[0])) < 1e-6
    assert de00(lab_of([128, 128, 128])[0], lab_of([180, 120, 70])[0]) > 15
    rgb = lab_to_rgb(lab_of([200, 150, 100])[0])
    assert all(abs(int(a) - b) <= 1 for a, b in zip(rgb, [200, 150, 100])), rgb
    bad = {'top_vs_photo': {'status': 'ok', 'dE00': 22.0}, 'empty_flat': {'status': 'ok', 'empty_pct': 3.0}, 'group_bleed': {'status': 'ok', 'value_pct': 2.0}}
    j = judge(bad, R)
    assert j['status'] == 'refused' and set(j['hard_failed']) == {'top_vs_photo', 'empty_flat'} and j['soft_failed'] == ['group_bleed'], j
    good = {'top_vs_photo': {'status': 'na'}, 'empty_flat': {'status': 'na'}, 'group_bleed': {'status': 'ok', 'value_pct': 0.0}}
    assert judge(good, R)['status'] == 'ok'
    soft_only = {'top_vs_photo': {'status': 'ok', 'dE00': 3.0}, 'empty_flat': {'status': 'ok', 'empty_pct': 0.0}, 'group_bleed': {'status': 'ok', 'value_pct': 0.5}}
    assert judge(soft_only, R)['status'] == 'soft'
    miss = classify(None, None, None)
    assert miss['status'] == 'missing'
    print('selftest ok')
    return 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return selftest()
    if len(argv) >= 2 and argv[0] == 'run':
        glb = argv[1]
        opt = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1, 2)}
        m = measure(glb, opt.get('--known'), opt.get('--parts'), None, opt.get('--photo'), opt.get('--pose-run'))
        txt = json.dumps(m, ensure_ascii=False, indent=1)
        if opt.get('--out'):
            open(opt['--out'], 'w', encoding='utf-8').write(txt)
        print(json.dumps(judge(m, rules()), ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

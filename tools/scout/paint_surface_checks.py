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
  winding      — обход граней согласован + объём наружу (T-20261123-42): у сетки итогового GLB соседние грани проходят общее ребро в противоположных направлениях, знаковый объём > 0.
                 Вывернутые грани/сетка ломают знаковую нормаль (этап 06 тогда молча отключает свой признак «спиной к камере», этап 08 считает свет наоборот). Считает `mesh_winding.py`, пороги — rules `winding`.
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
    area = np.bincount(comp, weights=ar, minlength=nc)                  # площадь компонент разом; цикл — только по крупным (раньше comp == ci по всем: ~4 с на 500 тыс. граней)
    for ci in np.where(area / tot >= min_frac)[0]:
        m = comp == ci
        a = ar[m].sum()
        mn = (n[m] * ar[m, None]).sum(axis=0)
        mn /= max(np.linalg.norm(mn), 1e-9)
        if float(((n[m] @ mn) * ar[m]).sum() / a) < 0.95:
            continue
        out.append((np.where(m)[0], mn))
    return out


# --------------------------------------------------------------------------------------- мерка 1: верх ↔ фото
def top_vs_photo(M: dict, known: np.ndarray | None, R: dict, viz: dict | None = None) -> dict:
    import mesh_grey_top as G
    c = R['top_vs_photo']
    t = R['top']
    V, F, UV, alb = M['V'], M['F'], M['UV'], M['albedo']
    top, side, ta, foot = G.top_faces(V, F, top_rules(R))
    if viz is not None:
        viz['top_faces'] = top
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
    if viz is not None:
        viz.update(alb_w=alb_w, top=inner)
    out_top_faces = top
    out = {'status': 'ok', 'texels': n_top, 'rgb_mesh': mesh_rgb, 'top_area_share_of_foot': round(ta / foot, 3)}
    if known is None:
        return {**out, 'status': 'na', 'why': 'нет known.png этапа 6 — нечем взять цвет верха с фото'}
    kn = _fit_mask(known, (h, w))
    kt = inner & kn
    if viz is not None:
        viz['top_known'] = kt
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


def group_bleed(M: dict, known: np.ndarray | None, part: np.ndarray | None, R: dict, viz: dict | None = None) -> dict:
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
            if viz is not None:
                viz.setdefault('alb_w', alb_w)
                viz.setdefault('bleed_rows', []).append((row['share_filled_pct'] or 0.0, mask & filled_a, mask & known_a))
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
def top_ref_from_frame(glb: str, photo: str | None, pose_run: str | None, top_faces: np.ndarray, R: dict) -> dict:
    """Запасной эталон верха, когда этап 6 не взял с него тексели (верх виден вскользь): цвет верха прямо на фото — пиксели кадра камеры 04, где виден верх (грани верха по растру), медиана цвета фото.
    Работает только если растр камеры ОТ ЭТОЙ формы (`raster_matches`). → {status ok|na, rgb, n_px, why}."""
    if not photo or not pose_run or not os.path.exists(os.path.join(pose_run, 'stage_loss.json')):
        return {'status': 'na', 'why': 'нет фото или растра камеры этапа 4'}
    from PIL import Image
    from scipy import ndimage
    sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
    import tex_visible as TV  # noqa: E402
    st = TV.load_stage(pose_run)
    geoms = TV.load_shape(glb)
    same, frac = raster_matches(st, geoms)
    if not same:
        return {'status': 'na', 'why': f'растр камеры от другой формы (развёртка совпала у {frac:.0%} пикселей)'}
    prgb, pmask = TV.photo_to_frame(np.asarray(Image.open(photo).convert('RGBA')), st['P'], st['px'])
    c = R['top_vs_photo']
    m = np.isin(st['ids'], top_faces) & st['mask'] & pmask
    m = ndimage.binary_erosion(m, iterations=int(c['frame_erode_px']))
    n = int(m.sum())
    if n < c['frame_min_px']:
        return {'status': 'na', 'why': f'верх на кадре камеры занимает {n} пикселей — мало', 'n_px': n}
    return {'status': 'ok', 'rgb': median_rgb(np.asarray(prgb)[..., :3][m]), 'n_px': n}


def photo_palette_dist(photo: str, rgb_mesh, R: dict) -> dict:
    """Запасной эталон №2, когда верх на фото не виден совсем (камера смотрит спереди, верх — ребро): входит ли цвет верха меша в ПАЛИТРУ фото товара.
    Палитра = центры ячеек Lab (L 4, a 3, b 3) переднего плана фото с долей ≥ palette_min_share; d = min ΔE2000 от цвета верха до центра. Серый «пустой» ≈128 на деревянном столе далеко от палитры."""
    from PIL import Image
    c = R['top_vs_photo']
    im = Image.open(photo).convert('RGBA')
    im.thumbnail((256, 256))
    a = np.asarray(im)
    fg = a[..., 3] > 200
    if int(fg.sum()) < 500:
        return {'status': 'na', 'why': 'на фото слишком мало переднего плана для палитры'}
    lab = lab_of(a[..., :3][fg])
    key = np.floor(lab / np.array([4.0, 3.0, 3.0])).astype(int)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    cnt = np.bincount(inv.ravel())
    keep = np.where(cnt / len(lab) >= c['palette_min_share'])[0]
    if not len(keep):
        return {'status': 'na', 'why': 'палитра фото не набралась'}
    cent = np.array([np.median(lab[inv.ravel() == k], axis=0) for k in keep])
    t = lab_of(rgb_mesh)[0]
    d = _tc().de2000_v(np.repeat(t[None], len(cent), 0), cent)
    return {'status': 'ok', 'dE00': round(float(d.min()), 2), 'colors': int(len(keep)), 'nearest_rgb': [int(v) for v in lab_to_rgb(cent[int(d.argmin())])]}


def raster_matches(st: dict, geoms: list, n: int = 20000, tol: float = 0.01, need: float = 0.98) -> tuple[bool, float]:
    """Растр камеры этапа 4 относится к ЭТОЙ форме? Для случайных пикселей кадра: UV из растра должен лежать внутри UV-треугольника грани с тем же номером в нашем GLB (допуск tol).
    Доля ≥ need → та же форма и развёртка; иначе кадр «по чужому растру» врёт (проверено глазами: пятна и разрывы текстуры)."""
    ids, uv, mask = st['ids'], st['uv'], st['mask']
    ys, xs = np.nonzero((ids >= 0) & mask)
    if len(ys) == 0:
        return False, 0.0
    rng = np.random.default_rng(0)
    sel = rng.choice(len(ys), min(n, len(ys)), replace=False)
    ys, xs = ys[sel], xs[sel]
    F = np.concatenate([g['F'] + 0 for g in geoms]) if len(geoms) == 1 else None
    if F is None:
        return False, 0.0
    UV = np.asarray(geoms[0]['UV'], float)
    fid = ids[ys, xs].astype(np.int64)
    if int(fid.max()) >= len(F):
        return False, 0.0
    tri = UV[F[fid]]                                            # (n,3,2), V вверх
    tri = np.stack([tri[..., 0], 1.0 - tri[..., 1]], -1)        # как в растре камеры: v сверху
    pt = uv[ys, xs].astype(float)
    a, b, c = tri[:, 0], tri[:, 1], tri[:, 2]
    v0, v1, v2 = b - a, c - a, pt - a
    den = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    u = (v2[:, 0] * v1[:, 1] - v1[:, 0] * v2[:, 1]) / den
    w = (v0[:, 0] * v2[:, 1] - v2[:, 0] * v0[:, 1]) / den
    inside = (u >= -tol) & (w >= -tol) & (u + w <= 1 + tol)
    frac = float(inside.mean())
    return frac >= need, frac


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
    same, frac = raster_matches(st, geoms)
    if not same:
        return {'status': 'na', 'why': f'растр камеры от другой формы (развёртка совпала у {frac:.0%} пикселей)', 'uv_match': round(frac, 3)}
    prgb, pmask = TV.photo_to_frame(np.asarray(Image.open(photo).convert('RGBA')), st['P'], st['px'])
    after = TV.frame_from_tex(st, geoms, [g['tex'] for g in geoms])
    r = TF.lighter_than_photo_share(after, prgb, st['mask'] & pmask)
    op, thr = TF.THRESHOLDS['lighter_than_photo_pct']
    return {'status': 'ok', 'share_pct': r['share_pct'], 'inner_px': r['inner_px'], 'spot_px': r['spot_px'], 'threshold': [op, thr]}


def cold_spots(glb: str, photo: str | None, pose_run: str | None, R: dict) -> dict:
    """Холодные (голубо-серые) пятна на БЕЛЫХ поверхностях кадра этапа 6 (T-20261124-57, П1.160; паспорт «Тюлип 60»): в кадре камеры 04 среди пикселей предмета, где на фото белое нейтральное
    (Lab L ≥ white_L_min, |a|,|b| ≤ ab_max; эрозия erode_px), сравниваем b итога (GLB этапа 6 по растру камеры) с b фото. → {status ok|na, db_median, cold_share, white_px, would_flag, thr, why}.
    Только запись: статус этапа не меняет; пороги — rules `cold_spots` (ID товаров в коде нет)."""
    c = R['cold_spots']
    thr = {'db_max': c['db_max'], 'cold_share_max': c['cold_share_max']}
    if not photo or not os.path.exists(photo):
        return {'status': 'na', 'why': 'нет фото товара', 'would_flag': False, 'thr': thr}
    if not pose_run or not os.path.exists(os.path.join(pose_run, 'stage_loss.json')):
        return {'status': 'na', 'why': 'нет растра камеры этапа 4 (pose_run)', 'would_flag': False, 'thr': thr}
    from PIL import Image
    from scipy import ndimage
    sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
    import tex_visible as TV  # noqa: E402
    st = TV.load_stage(pose_run)
    geoms = TV.load_shape(glb)
    same, frac = raster_matches(st, geoms)
    if not same:
        return {'status': 'na', 'why': f'растр камеры от другой формы (развёртка совпала у {frac:.0%} пикселей)', 'would_flag': False, 'thr': thr}
    prgb, pmask = TV.photo_to_frame(np.asarray(Image.open(photo).convert('RGBA')), st['P'], st['px'])
    after = TV.frame_from_tex(st, geoms, [g['tex'] for g in geoms])
    inner = ndimage.binary_erosion(st['mask'] & pmask, iterations=int(c['erode_px']))
    if not inner.any():
        return {'status': 'na', 'why': 'предмет в кадре пуст', 'would_flag': False, 'thr': thr}
    return cold_stats(np.asarray(prgb)[..., :3][inner], np.asarray(after)[inner], c, thr)


def cold_stats(photo_rgb, after_rgb, c: dict, thr: dict) -> dict:
    """Ядро проверки «холодные пятна» на массивах (N,3) uint8 — пиксели предмета в кадре: фото и итог этапа 6. Белое нейтральное на фото (L ≥ white_L_min, |a|,|b| ≤ ab_max) — область проверки;
    на ней медиана Δb (итог − фото) и доля пикселей холоднее фото больше чем на cold_db. Белого мало (< min_px) — na. Метка: |медиана| > db_max ИЛИ доля > cold_share_max."""
    pl = lab_of(photo_rgb)
    white = (pl[:, 0] >= float(c['white_L_min'])) & (np.abs(pl[:, 1]) <= float(c['ab_max'])) & (np.abs(pl[:, 2]) <= float(c['ab_max']))
    n = int(white.sum())
    if n < int(c['min_px']):
        return {'status': 'na', 'why': f'белой нейтральной области на фото {n} px < {int(c["min_px"])}', 'white_px': n, 'would_flag': False, 'thr': thr}
    al = lab_of(after_rgb)
    db = (al[:, 2] - pl[:, 2])[white]
    med = float(np.median(db))
    share = float((db < -float(c['cold_db'])).mean())
    would = abs(med) > float(c['db_max']) or share > float(c['cold_share_max'])
    return {'status': 'ok', 'db_median': round(med, 2), 'cold_share': round(share, 4), 'white_px': n, 'would_flag': bool(would), 'thr': thr, 'why': ''}



def cold_fill_stats(alb, occ, known, c: dict, thr: dict) -> dict:
    """Мерка «холодные пятна» по АТЛАСУ итоговой текстуры (T-20261124-57, вторая мерка директора 25.11: кадр этапа 6 копирует пиксели фото — Δb к фото там ≈ 0 по построению, дефект сидит в ЗАЛИТЫХ текселях).
    alb (H,W,3) uint8, occ (H,W) bool — занятые текселы, known (H,W) bool — текселы, взятые с фото этапом 6. Эталон белого — медиана Lab b у ИЗВЕСТНЫХ белых нейтральных текселов
    (L ≥ white_L_min, |a|,|b| ≤ ab_max; их меньше fill_ref_min_px — na). Область проверки — ЗАЛИТЫЕ (occ & ~known) тексели светлее white_L_min (холодное пятно светлое: L ≈ 89).
    Значение: медиана Δb (залитое − эталон) и доля текселов с Δb < −cold_db. Метка — только ХОЛОДНАЯ сторона (дефект паспорта — голубо-серое): медиана Δb < −db_max ИЛИ доля холодных > cold_share_max; тёплое залитое пишется `warm_share` и не метится. Залитых светлых мало (< fill_min_px) — na."""
    lab = lab_of(np.asarray(alb, np.uint8).reshape(-1, 3)).reshape(np.asarray(alb).shape[:2] + (3,))
    kn = np.asarray(known, bool) & np.asarray(occ, bool)
    ref_m = kn & (lab[..., 0] >= float(c['white_L_min'])) & (np.abs(lab[..., 1]) <= float(c['ab_max'])) & (np.abs(lab[..., 2]) <= float(c['ab_max']))
    n_ref = int(ref_m.sum())
    if n_ref < int(c['fill_ref_min_px']):
        return {'status': 'na', 'why': f'известного белого эталона {n_ref} текселов < {int(c["fill_ref_min_px"])}', 'ref_px': n_ref, 'would_flag': False, 'thr': thr}
    ref_b = float(np.median(lab[..., 2][ref_m]))
    fl = np.asarray(occ, bool) & ~np.asarray(known, bool) & (lab[..., 0] >= float(c['white_L_min']))
    n = int(fl.sum())
    if n < int(c['fill_min_px']):
        return {'status': 'na', 'why': f'светлых залитых текселов {n} < {int(c["fill_min_px"])}', 'fill_px': n, 'ref_px': n_ref, 'would_flag': False, 'thr': thr}
    db = lab[..., 2][fl] - ref_b
    med = float(np.median(db))
    share = float((db < -float(c['cold_db'])).mean())
    warm = float((db > float(c['db_max'])).mean())
    would = med < -float(c['db_max']) or share > float(c['cold_share_max'])            # ТОЛЬКО холодная сторона: тёплое залитое — не «холодное пятно» (бежевая ваза: эталон — блики, залитое теплее на +6,6 — ложная метка по |Δb|); доля тёплого пишется числом
    return {'status': 'ok', 'db_median': round(med, 2), 'cold_share': round(share, 4), 'warm_share': round(warm, 4), 'fill_px': n, 'ref_px': n_ref, 'ref_b': round(ref_b, 2), 'would_flag': bool(would), 'thr': thr, 'why': ''}


def cold_fill(glb: str, known_png: str | None, R: dict) -> dict:
    """Обёртка `cold_fill_stats` по файлам: GLB (залитый этапом 7 / итог) + known.png этапа 6; занятые тексели — растр развёртки. Только запись; пороги — rules `cold_spots`."""
    c = R['cold_spots']
    thr = {'db_max': c['db_max'], 'cold_share_max': c['cold_share_max']}
    if not known_png or not os.path.exists(known_png):
        return {'status': 'na', 'why': 'нет known.png этапа 6', 'would_flag': False, 'thr': thr}
    import mesh_grey_top as G
    M = load_model(glb)
    alb_w, _sc = _scale(M['albedo'], int(c['fill_work_px']))
    h, w = alb_w.shape[:2]
    occ = G._raster(M['UV'], M['F'], w, h)
    known = _fit_mask(load_known(known_png, 127), alb_w.shape)
    return cold_fill_stats(alb_w, occ, known, c, thr)


# ---------------------------------------------------------------------------------------------- всё вместе ---
def frames(glb: str, known_png: str | None, parts_path: str | None, out_dir: str, R: dict | None = None, size: int | None = None) -> dict:
    """Кадры срабатываний (атлас итоговой текстуры с подсветкой): `surface-top.jpg` — верх (красная заливка), взятое с фото (зелёная кромка); `surface-bleed.jpg` — затёк (пурпур — в залитых
    текселях, жёлтый — в известных с фото) поверх атласа. ≤ `frames.max_kb`; пишет только нужные (верх найден / затёк есть). Возвращает {имя: путь}."""
    from PIL import Image
    R = R or rules()
    M = load_model(glb)
    known = load_known(known_png, R['top_vs_photo']['known_thr'])
    part, _ = load_parts(parts_path, len(M['F']))
    vt, vb = {}, {}
    top_vs_photo(M, known, R, vt)
    group_bleed(M, known, part, R, vb)
    size = size or R['frames']['size']
    out = {}

    def save(name, alb, layers):
        im = alb.astype(np.float32).copy()
        for mask, col, a in layers:
            if mask is not None:
                im[mask] = (1 - a) * im[mask] + a * np.array(col, np.float32)
        img = Image.fromarray(np.clip(im, 0, 255).astype(np.uint8))
        img = img.resize((size, size), Image.LANCZOS) if img.size != (size, size) else img
        path = os.path.join(out_dir, name)
        os.makedirs(out_dir, exist_ok=True)
        for q in (85, 70, 55, 40):
            img.save(path.replace('.png', '.jpg'), quality=q)
            if os.path.getsize(path.replace('.png', '.jpg')) <= R['frames']['max_kb'] * 1024:
                break
        out[name.replace('.png', '.jpg')] = path.replace('.png', '.jpg')

    if 'top' in vt:
        from scipy import ndimage
        edge = vt.get('top_known') is not None and (vt['top_known'] & ~ndimage.binary_erosion(vt['top_known'], iterations=2))
        save('surface-top.png', vt['alb_w'], [(vt['top'], (255, 0, 0), 0.35), (edge if edge is not False else None, (0, 255, 0), 1.0)])
    rows = sorted((r for r in vb.get('bleed_rows', []) if r[0] > R['group_bleed']['threshold'][1]), key=lambda r: -r[0])[:3]       # кадр — только где мерка сработала
    if rows:
        lf = np.zeros_like(rows[0][1])
        lk = np.zeros_like(rows[0][2])
        for _, f, k in rows:
            lf |= f
            lk |= k
        save('surface-bleed.png', vb['alb_w'], [(lf, (255, 0, 255), 0.85), (lk, (255, 220, 0), 0.85)])
    return out


# ------------------------------------------------------------------------- мерка 4: «один тон» верха и зада
def palette_cells(photo: str | None, R: dict) -> np.ndarray | None:
    """Центры ячеек Lab переднего плана фото (как в `photo_palette_dist`): эталон «какие цвета у материала товара»; нет фото/мало переднего плана → None (не измерено)."""
    if not photo or not os.path.exists(photo):
        return None
    from PIL import Image
    c = R['top_vs_photo']
    im = Image.open(photo).convert('RGBA')
    im.thumbnail((256, 256))
    a = np.asarray(im)
    fg = a[..., 3] > 200
    if int(fg.sum()) < 500:
        return None
    lab = lab_of(a[..., :3][fg])
    key = np.floor(lab / np.array([4.0, 3.0, 3.0])).astype(int)
    uniq, inv = np.unique(key, axis=0, return_inverse=True)
    cnt = np.bincount(inv.ravel())
    keep = np.where(cnt / len(lab) >= c['palette_min_share'])[0]
    if not len(keep):
        return None
    return np.array([np.median(lab[inv.ravel() == k], axis=0) for k in keep])


def side_faces_back(glb: str, M: dict, known: np.ndarray | None, R: dict) -> dict:
    """Грани ЗАДА: наружная нормаль смотрит к камере заднего вида (азимут «зад» = противоположный фото-стороне по known, `tex_fill.side_azimuths`) в пределах cos ≥ back.cos_min."""
    sys.path.insert(0, os.path.join(HERE, 'salad', 'trellis'))
    import tex_fill as TF  # noqa: E402
    import tex_coverage as TC  # noqa: E402
    geoms = TC.load_geoms(glb)
    az = {'back': 180.0, 'photo': 0.0, 'fallback': True}
    if known is not None:
        az = TF.side_azimuths(geoms, [known])
    V, F = M['V'], M['F']
    n, _ = face_normals_areas(V, F)
    cen = V[F].mean(axis=1)
    n = n * np.where(((cen - V.mean(axis=0)) * n).sum(axis=1) >= 0, 1.0, -1.0)[:, None]          # наружу
    cam = TF.photo_views([az['back']], 0.0)[0][0]
    faces = np.where((n @ cam) >= float(R['tone']['back']['cos_min']))[0]
    return {'faces': faces, 'azimuth_back': az.get('back'), 'azimuth_fallback': bool(az.get('fallback'))}


def side_tone(M: dict, faces: np.ndarray, cells: np.ndarray | None, R: dict, key: str, part: np.ndarray | None = None) -> dict:
    """Один ли тон на стороне (`key` = top | back): «один материал — один тон» (правило владельца TG 1922/1934). Тексели граней стороны (без шва с другими гранями), по ГРУППАМ материала
    (`part` — parts08.npz; нет — вся сторона одна группа): у группы — медиана Lab и НИЗКОЧАСТОТНОЕ отклонение (среднее в окне `lf_px` от медианы группы: зерно/ткань усредняются, лоскуты,
    градиент, чужой тон — нет). dev_share_pct — доля текселей групп с ΔE2000 отклонения > dev_dE00; off_palette_pct — доля текселей дальше palette_dE00 от ближайшего цвета фото товара
    (чёрное на белом шкафу). Статусы: ok | small (сторона ничтожна — нечего мерить, не блок) | na (граней нет) | unmeasured (сторона большая, а измерить не вышло — НЕ «ок»).
    Фото нет → off_palette_pct None (+причина): судья считает это «не измерено», а не «0»."""
    import mesh_grey_top as G
    from scipy import ndimage
    c = R['tone']
    t = R['top']
    ck = c[key]
    F, UV, alb = M['F'], M['UV'], M['albedo']
    if not len(faces):
        return {'status': 'na', 'why': 'нет граней стороны'}
    alb_w, sc = _scale(alb, t['work_px'])
    h, w = alb_w.shape[:2]
    other = np.setdiff1d(np.arange(len(F)), faces)
    mo = G._raster(UV, F[other], w, h) if len(other) else np.zeros((h, w), bool)
    side_m = G._raster(UV, F[faces], w, h)
    min_g = ck['min_texels'] * (sc * sc)
    if int(side_m.sum()) < min_g:
        return {'status': 'small', 'why': 'сторона занимает слишком мало текселей', 'texels': int(side_m.sum())}
    groups = sorted({int(g) for g in part[faces]}) if part is not None else [None]
    gmask = {g: (G._raster(UV, F[faces[part[faces] == g]], w, h) if g is not None else side_m) for g in groups}
    rng = np.random.default_rng(0)
    lf = max(3, int(c['lf_px']))
    rows, tot_n, dev_n, off_n, off_tot = [], 0, 0.0, 0.0, 0
    for exclusive in (True, False):                                   # второй проход — когда шов съел всю сторону (развёртка делит острова с чужими гранями)
        for g in groups:
            m_g = gmask[g].copy()
            if exclusive:
                m_g &= ~mo
                for j in groups:
                    if j != g:
                        m_g &= ~gmask[j]
            inner = G._erode(m_g, t['erode_px'])
            n = int(inner.sum())
            if n < min_g:
                continue
            ys, xs = np.nonzero(inner)
            lab_all = lab_of(alb_w[ys, xs])
            lab_img = np.zeros((h, w, 3), np.float32)
            lab_img[ys, xs] = lab_all
            med = np.median(lab_all, axis=0)
            wgt = inner.astype(np.float32)
            den = ndimage.uniform_filter(wgt, size=lf)
            mean = np.stack([ndimage.uniform_filter(lab_img[..., k] * wgt, size=lf) for k in range(3)], -1) / np.maximum(den[..., None], 1e-6)
            sel = den[ys, xs] >= c['lf_cover_min']
            if int(sel.sum()) < min_g:
                continue
            lf_lab = mean[ys, xs][sel]
            if len(lf_lab) > c['sample']:
                lf_lab = lf_lab[rng.choice(len(lf_lab), c['sample'], replace=False)]
            d = _tc().de2000_v(lf_lab, np.repeat(med[None], len(lf_lab), 0))
            share = float((d > c['dev_dE00']).mean())
            row = {'group': g, 'texels': n, 'rgb': [int(v) for v in lab_to_rgb(med)], 'dev_share_pct': round(100.0 * share, 2), 'p95_dE00': round(float(np.percentile(d, 95)), 2)}
            tot_n += n
            dev_n += share * n
            if cells is not None:
                px_lab = lab_all if len(lab_all) <= c['sample'] else lab_all[rng.choice(len(lab_all), c['sample'], replace=False)]
                dmin = np.full(len(px_lab), 1e9)
                for ce in cells:
                    dmin = np.minimum(dmin, _tc().de2000_v(px_lab, np.repeat(ce[None], len(px_lab), 0)))
                osh = float((dmin > c['palette_dE00']).mean())
                row['off_palette_pct'] = round(100.0 * osh, 2)
                off_n += osh * n
                off_tot += n
            rows.append(row)
        if rows:
            break
    if not rows:
        return {'status': 'unmeasured', 'why': 'сторона большая, но ни одна группа не дала достаточно текселей без шва', 'texels': int(side_m.sum())}
    out = {'status': 'ok', 'texels': tot_n, 'groups': rows, 'dev_share_pct': round(100.0 * dev_n / tot_n, 2), 'worst_group_dev_pct': max(r['dev_share_pct'] for r in rows), 'overlap_pass': not exclusive}
    if cells is None:
        out['off_palette_pct'] = None
        out['off_palette_why'] = 'нет фото товара — палитры нет'
    else:
        out['off_palette_pct'] = round(100.0 * off_n / max(off_tot, 1), 2)
    return out


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


def winding_check(M: dict, R: dict) -> dict:
    """Согласованность обхода граней и знак объёма итоговой сетки (`mesh_winding.analyze`). Не удалось посчитать (не замкнутая сетка, мало граней) → status na/error с причиной, не «прошло»."""
    c = R['winding']
    sys.path.insert(0, HERE)
    import mesh_winding as MW
    try:
        a = MW.analyze(M['V'], M['F'], c['weld_eps'])
    except Exception as e:  # noqa: BLE001
        return {'status': 'error', 'why': f'{type(e).__name__}: {str(e)[:120]}'}
    return a


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
    vt = {}
    res['top_vs_photo'] = top_vs_photo(M, known, R, vt)
    tp = res['top_vs_photo']
    if tp.get('status') == 'na' and 'rgb_mesh' in tp and vt.get('top_faces') is not None and len(vt['top_faces']):
        try:                                                  # этап 6 верх не взял (вскользь) → цвет верха берём с фото через растр камеры
            ref = top_ref_from_frame(glb, photo, pose_run, vt['top_faces'], R)
        except Exception as e:  # noqa: BLE001
            ref = {'status': 'na', 'why': f'{type(e).__name__}: {str(e)[:100]}'}
        if ref['status'] == 'ok':
            la, lb = lab_of(tp['rgb_mesh'])[0], lab_of(ref['rgb'])[0]
            tp.update(status='ok', ref='photo_frame', rgb_photo=ref['rgb'], dE00=round(de00(la, lb), 2), dL=round(float(la[0] - lb[0]), 2),
                      dab=round(float(np.hypot(la[1] - lb[1], la[2] - lb[2])), 2), frame_px=ref['n_px'], why_known_na=tp.pop('why', ''))
        else:
            tp['frame_ref_na'] = ref['why']
        if tp['status'] == 'na' and photo and os.path.exists(photo):
            pp = photo_palette_dist(photo, tp['rgb_mesh'], R)                 # верх на фото не виден совсем → входит ли его цвет в палитру фото
            if pp['status'] == 'ok':
                tp.update(status='ok', ref='photo_palette', dE00=pp['dE00'], palette_colors=pp['colors'], rgb_photo=pp['nearest_rgb'], why_known_na=tp.pop('why', ''))
            else:
                tp['palette_na'] = pp['why']
    else:
        tp.setdefault('ref', 'known')
    tm['top_vs_photo'] = round(time.time() - t1, 2)
    t1 = time.time()
    cells = None
    try:
        cells = palette_cells(photo, R)
    except Exception as e:  # noqa: BLE001
        res['palette_cells_error'] = f'{type(e).__name__}: {str(e)[:100]}'
    res['top_tone'] = side_tone(M, vt['top_faces'], cells, R, 'top', part) if vt.get('top_faces') is not None and len(vt['top_faces']) else {'status': 'na', 'why': 'нет плоского верха по геометрии'}
    try:
        bf = side_faces_back(glb, M, known, R)
        res['back_tone'] = side_tone(M, bf['faces'], cells, R, 'back', part)
        res['back_tone'].update(azimuth_back=bf['azimuth_back'], azimuth_fallback=bf['azimuth_fallback'])
    except Exception as e:  # noqa: BLE001 — зад не измерен: так и пишем
        res['back_tone'] = {'status': 'error', 'why': f'{type(e).__name__}: {str(e)[:120]}'}
    tm['tone'] = round(time.time() - t1, 2)
    t1 = time.time()
    res['empty_flat'] = empty_flat(M, known, R, res['top_vs_photo'])
    tm['empty_flat'] = round(time.time() - t1, 2)
    t1 = time.time()
    res['winding'] = winding_check(M, R)
    tm['winding'] = round(time.time() - t1, 2)
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
    if (R.get('cold_spots') or {}).get('enabled', False):                  # T-20261124-57: холодные пятна на белом — только запись; выключено — мерка не считается и ключа нет
        try:
            res['cold_spots'] = cold_spots(glb, photo, pose_run, R)
        except Exception as e:  # noqa: BLE001 — не измерено: так и пишем
            res['cold_spots'] = {'status': 'error', 'why': f'{type(e).__name__}: {str(e)[:120]}', 'would_flag': False}
        try:                                                              # вторая мерка: залитые тексели (атлас) против известного белого; кадровая выше фото копирует и дефекта не видит
            res['cold_fill'] = cold_fill(glb, known_png, R)
        except Exception as e:  # noqa: BLE001
            res['cold_fill'] = {'status': 'error', 'why': f'{type(e).__name__}: {str(e)[:120]}', 'would_flag': False}
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
    w = m.get('winding') or {}
    if w.get('status') == 'ok':                                                # обход граней и объём (T-20261123-42): два числа, любое вне порога → winding
        wc = R['winding']
        cons_ok = w['consistency'] >= wc['consistency_min']
        vol_ok = w['volume_rel'] > wc['volume_rel_min']
        ms['winding_consistency'] = {'value': w['consistency'], 'threshold': wc['consistency_min'], 'op': '>=', 'ok': cons_ok}
        ms['winding_volume_rel'] = {'value': w['volume_rel'], 'threshold': wc['volume_rel_min'], 'op': '>', 'ok': vol_ok}
        if not (cons_ok and vol_ok):
            (soft if wc.get('soft') else hard).append('winding')
    else:
        for mk in ('winding_consistency', 'winding_volume_rel'):
            ms[mk] = {'value': None, 'ok': None, ('na' if w.get('status') == 'na' else 'error'): w.get('why') or 'мерка обхода не запускалась'}
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
    unmeasured = []
    tc = R.get('tone') or {}
    for side in ('top', 'back'):                                       # «один материал — один тон» на верхе и заде (T-20261123-32): мерится ВСЕГДА, нет данных = «не измерено»
        r = m.get(f'{side}_tone') or {'status': 'unmeasured', 'why': 'мерка стороны не запускалась'}
        k1, k2 = f'{side}_one_tone_pct', f'{side}_off_palette_pct'
        if r.get('status') == 'ok':
            lim = tc[side]
            for k, val, thr in ((k1, r['dev_share_pct'], lim['one_tone_max_pct']), (k2, r.get('off_palette_pct'), lim['off_palette_max_pct'])):
                if val is None:
                    ms[k] = {'value': None, 'ok': None, 'error': r.get('off_palette_why') or 'нет данных'}
                    unmeasured.append(k)
                    continue
                ok = val <= thr
                ms[k] = {'value': val, 'threshold': thr, 'op': '<=', 'ok': ok}
                if not ok:
                    (soft if tc.get('soft') else hard).append(k)
        else:
            why = r.get('why') or 'нет результата мерки'
            for k in (k1, k2):
                if r.get('status') in ('na', 'small'):
                    ms[k] = {'value': None, 'ok': None, 'na': why}
                else:
                    ms[k] = {'value': None, 'ok': None, 'error': why}
                    unmeasured.append(k)
    status = 'refused' if hard else 'soft' if soft else 'ok'
    return {'status': status, 'metrics': ms, 'hard_failed': hard, 'soft_failed': soft, 'unmeasured': unmeasured}


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
    if j["status"] in ("ok", "soft") and j["unmeasured"]:                           # не измерено ≠ прошло: этап 9 не отдаёт «готов» без мерки верха/зада
        out['status'] = 'missing'
    why = []
    for k in j['hard_failed'] + j['soft_failed']:
        if k == 'winding':
            wm = j['metrics']
            why.append(f"обход граней: согласованность {wm['winding_consistency']['value']} (нужно ≥ {wm['winding_consistency']['threshold']}), объём {wm['winding_volume_rel']['value']} (нужно > {wm['winding_volume_rel']['threshold']})")
            continue
        mm = {'top_vs_photo': 'top_vs_photo_dE00', 'empty_flat': 'empty_flat_pct', 'group_bleed': 'group_bleed_pct', 'lighter_than_photo': 'lighter_than_photo_pct'}.get(k, k)
        why.append(f"{mm} {j['metrics'][mm]['value']} > {j['metrics'][mm]['threshold']}")
    why += [f"не измерено {k}: {j['metrics'][k].get('error')}" for k in j['unmeasured']]
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
    if len(argv) >= 2 and argv[0] == 'frames':             # frames <glb> --known K --parts P --out ПАПКА → кадры срабатываний (для проверки глазами)
        opt = {argv[i]: argv[i + 1] for i in range(2, len(argv) - 1, 2)}
        print(json.dumps(frames(argv[1], opt.get('--known'), opt.get('--parts'), opt.get('--out') or '.'), ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

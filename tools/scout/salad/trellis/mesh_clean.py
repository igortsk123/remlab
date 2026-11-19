#!/usr/bin/env python3
"""ОЧИСТКА «ПЛИТЫ У ПОЛА» И ЧИСЛА ПО МЕШУ (T-20261118-91; директор 19.11, комод Модерн): одно правило для ВСЕХ моделей.

ПРАВИЛО. Связные куски меша (по вершинам), у которых толщина по вертикали < 2 % габарита (`--thin`, по умолчанию 0.02) и которые лежат у пола (нижняя точка в нижних 5 % высоты предмета,
`--floor`), — «плоский слой»: у TRELLIS.2 это стопка тонких листов 1×1 с вырезом под предметом (комод: 5 887 кусков, 67 % треугольников). Они отрезаются ОДИНАКОВО у любой модели,
остальное — сам предмет. Сырой GLB не трогается: рядом кладётся `<имя>.clean.glb` (примитивы и материалы те же, НЕ склеиваются), `<имя>.metrics.json` (в т.ч. площадь и габарит удалённого) и `<имя>.audit.glb` (удалённое красным — для проверки глазами).

ЧИСЛА (в metrics.json): ① доля плоского слоя (куски и доля треугольников); ② пропорции предмета БЕЗ слоя — ширина : глубина : высота к большей стороне (вертикаль — Y glTF);
габарит с слоем и без; треугольники до/после; число кусков предмета. Пропорции из фида (`dims_cm`) сравниваются, если переданы `--dims W D H`.

  python3 mesh_clean.py <model.glb> [--dims 93 47 88] [--thin 0.02] [--floor 0.05]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np


def label_components(faces: np.ndarray, n_vertices: int) -> np.ndarray:
    """Номер связного куска для каждой грани (связность по общим вершинам); union-find на numpy-массивах рёбер граней."""
    try:                                           # быстрый путь: scipy (в боевом окружении стенда есть); иначе чистый union-find ниже
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        e = np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]]])
        g = coo_matrix((np.ones(len(e), dtype=np.int8), (e[:, 0], e[:, 1])), shape=(n_vertices, n_vertices))
        _, vlab = connected_components(g, directed=False)
        _, lab = np.unique(vlab[faces[:, 0]], return_inverse=True)
        return lab
    except ImportError:
        pass
    parent = np.arange(n_vertices)

    def find(x):
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root
    for a, b in np.concatenate([faces[:, [0, 1]], faces[:, [1, 2]]]):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(v) for v in faces[:, 0]])
    _, lab = np.unique(roots, return_inverse=True)
    return lab


def analyse(mesh, thin: float = 0.02, floor: float = 0.05) -> dict:
    """Куски, плоский слой, пропорции. Возвращает словарь metrics и маску граней предмета `keep`."""
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    lab = label_components(f, len(v))
    n = lab.max() + 1
    ext_all = v.max(0) - v.min(0)
    mx = float(ext_all.max())
    up = 1                                           # вертикаль glTF — Y
    tris = np.bincount(lab, minlength=n)
    lo = np.full((n, 3), np.inf)
    hi = np.full((n, 3), -np.inf)
    # габарит куска — по вершинам его граней
    for k in range(3):
        c = v[f[:, 0], k], v[f[:, 1], k], v[f[:, 2], k]
        for cc in c:
            np.minimum.at(lo[:, k], lab, cc)
            np.maximum.at(hi[:, k], lab, cc)
    thick = hi[:, up] - lo[:, up]
    # «предмет»: не плоские; границу пола берём по нижней точке самого крупного не плоского куска
    not_thin = thick >= thin * mx
    ref = np.argmax(np.where(not_thin, tris, -1)) if not_thin.any() else int(np.argmax(tris))
    item_lo = lo[not_thin, up].min() if not_thin.any() else lo[ref, up]
    item_h = (hi[not_thin, up].max() - item_lo) if not_thin.any() else float(thick[ref])
    at_floor = lo[:, up] <= item_lo + floor * max(item_h, 1e-9)
    flat = (~not_thin) & at_floor
    keep_c = ~flat
    keep = keep_c[lab]
    out = {'threshold_thin': thin, 'threshold_floor': floor, 'components_total': int(n), 'tris_total': int(len(f)),
           'extent_raw_xyz': [round(float(x), 4) for x in ext_all],
           'flat_layer': {'pieces': int(flat.sum()), 'tris': int(tris[flat].sum()), 'tris_share': round(float(tris[flat].sum() / len(f)), 3)}}
    if keep_c.any():
        klo, khi = lo[keep_c].min(0), hi[keep_c].max(0)
        kext = khi - klo
        # ширина/глубина — две горизонтальные оси (X, Z) по убыванию; высота — Y. Какая из горизонталей «ширина», по фиду не определить: берём большую как ширину.
        w, d = sorted([float(kext[0]), float(kext[2])], reverse=True)
        h = float(kext[up])
        m2 = max(w, d, h)
        out.update({'item_extent_xyz': [round(float(x), 4) for x in kext], 'item_tris': int(tris[keep_c].sum()), 'item_pieces': int(keep_c.sum()),
                    'item_ratio_w_d_h': [round(w / m2, 3), round(d / m2, 3), round(h / m2, 3)],
                    'item_share_of_raw_extent': round(float(max(w, d, h) / mx), 3)})
    return out, keep


def tri_areas(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    return 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)


def footprint_inside(v: np.ndarray, f: np.ndarray, top_from: float = 0.35, grow: float = 0.05) -> np.ndarray:
    """Для каждой грани: центр внутри «следа корпуса» (выпуклая оболочка XZ вершин выше `top_from` высоты меша, раздутая на `grow` габарита)? Пусто → всё «внутри»."""
    ymin, ymax = float(v[:, 1].min()), float(v[:, 1].max())
    up = v[:, 1] > ymin + top_from * max(ymax - ymin, 1e-9)
    if up.sum() < 10:
        return np.ones(len(f), dtype=bool)
    from scipy.spatial import ConvexHull
    pts = v[up][:, [0, 2]]
    hull = ConvexHull(pts)
    ext = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1]))
    c = v[f].mean(1)
    return np.all(c[:, [0, 2]] @ hull.equations[:, :2].T + hull.equations[:, 2] <= grow * ext, axis=1)


def slab_pieces(v: np.ndarray, f: np.ndarray, flat: np.ndarray, min_out: float = 0.2) -> np.ndarray:
    """Куски старого правила («тонкие у пола», маска граней `flat`) → в плиту идёт ЦЕЛИКОМ тот кусок, у которого ≥ `min_out` граней лежит ЗА следом корпуса (выступает из-под предмета);
    кусок целиком внутри следа (основание торшера, пятачки ножек) остаётся. Часть плиты под самим предметом уходит вместе с выступающей, потому что это один кусок."""
    if not flat.any():
        return flat
    lab = label_components(f, len(v))
    out_face = ~footprint_inside(v, f)
    res = np.zeros(len(f), dtype=bool)
    for k in np.unique(lab[flat]):
        m = lab == k
        if out_face[m].mean() >= min_out:
            res |= m
    return res


def slab_dust(v: np.ndarray, f: np.ndarray, removed: np.ndarray, band: float = 0.01, max_area: float = 0.003, horiz: float = 0.8, min_h: float = 0.7) -> np.ndarray:
    """ПРАВКА E («пыль»): после удаления плиты в полосе пола (нижние `band` высоты меша) остаются отдельные мелкие осколки листов. Удаляем отдельные связные куски ОСТАВШЕГОСЯ, которые целиком лежат в этой
    полосе, имеют площадь < `max_area` площади меша, ≥ `min_h` их площади горизонтальна (|нормаль_Y| ≥ `horiz`) и ≥ 50 % граней лежит ЗА следом корпуса (кусочки, разбитые на части поверхности основания
    стола «Тюлип», лежат внутри следа — остаются: проба E v1 19.11 проделала в них дыры). Пятачок ножки и основание объёмные/большие, осколок листа плоский, мелкий и торчит из-под предмета."""
    keep = ~removed
    if not keep.any():
        return np.zeros(len(f), dtype=bool)
    ymin, ymax = float(v[:, 1].min()), float(v[:, 1].max())
    top = ymin + band * max(ymax - ymin, 1e-9)
    area = tri_areas(v, f)
    nrm = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    ny = np.abs(nrm[:, 1]) / np.maximum(2 * area, 1e-12)
    idx = np.nonzero(keep)[0]
    lab = label_components(f[idx], len(v))
    cmax = v[f[idx]].max(axis=1)[:, 1]
    # опора: вершины КРУПНЫХ оставшихся кусков — осколок, лежащий вплотную к ним (по плану и по высоте), — это поверхность самого предмета (верх основания стола), его не трогаем
    from scipy.spatial import cKDTree
    total = float(area.sum())
    ext = max(ymax - ymin, 1e-9)
    big = np.zeros(len(f), dtype=bool)
    for g in np.unique(lab):
        gi = idx[lab == g]
        if float(area[gi].sum()) >= max_area * total:
            big[gi] = True
    bv = np.unique(f[big].ravel()) if big.any() else np.zeros(0, dtype=int)
    tree = cKDTree(v[bv][:, [0, 2]]) if len(bv) else None
    out = np.zeros(len(f), dtype=bool)
    for g in np.unique(lab):
        gi = idx[lab == g]
        if cmax[lab == g].max() > top:
            continue
        a = float(area[gi].sum())
        if a < max_area * total and float(area[gi][ny[gi] >= horiz].sum() / max(a, 1e-12)) >= min_h:
            if tree is not None:
                cen = v[f[gi]].mean(axis=1)
                _, nb = tree.query(cen[:, [0, 2]], k=1)
                near = (np.abs(v[bv[nb]][:, 1] - cen[:, 1]) <= 0.04 * ext) & (np.linalg.norm(v[bv[nb]][:, [0, 2]] - cen[:, [0, 2]], axis=1) <= 0.02 * ext)
                if near.mean() >= 0.5:
                    continue
            out[gi] = True
    return out


def floaters(v: np.ndarray, f: np.ndarray, removed: np.ndarray, small: float = 0.003, gap: float = 0.03, max_faces: int = 20, max_share: float = 0.025, floor_band: float = 0.01) -> np.ndarray:
    """ПРАВИЛО F («осколки в воздухе»; стол Сего-2 19.11: после E оставалось 6780 мелких кусков — 4951 из них висели в воздухе вокруг предмета с зазором, а не на полу).
    Мелкий связный кусок ОСТАВШЕГОСЯ (площадь < `small` площади меша), у которого ни одна вершина не ближе `gap` высоты к ТЕЛУ предмета (вершины и центры граней КРУПНЫХ кусков, ≥ `small`) — это отлетевший
    осколок, он удаляется. Зазор `gap` = 1 % высоты (при 0,2 % проверка кромок 19.11 нашла мелкие вырезы по краю панели консоли: куски самой поверхности лежат у тела в пределах 1 %, у висящей россыпи зазор в медиане 6,9 %) — но только МИКРО-осколок: меньше `max_faces` граней (у россыпи столика Сего-2 медиана 2 грани, p90 12; у болтов и накладок на панели — сотни граней и размер до 46 % высоты — первая версия 19.11 срезала их и 82 % стеклянной
    вазы). Прилегающие к телу (зазор ≈ 0) и любые куски от `max_faces` граней остаются. Нет крупных кусков — ничего не трогаем.
    ВТОРОЕ УСЛОВИЕ («хлопья у подножия», менеджер 19.11; проба на консоли Сего-2: «низ ≤ 1 % высоты и плоский» не снимал ничего — хлопья тонкие вертикальные, а нижняя отметка меша задана ими же): микро-осколок (< `max_faces` граней), который ЦЕЛИКОМ лежит не выше низа ТЕЛА + `floor_band` высоты (низ тела = самая нижняя точка крупных кусков), и центр которого СНАРУЖИ плана тела (выпуклая оболочка нижней полосы крупных кусков), удаляется и при малом зазоре — мусор на полу у подножия. Внутри плана такие куски — осколки самого основания (проба 19.11 на комоде Hunyuan: 172 плоских куска плиты основания, 2 % площади, все внутри плана) — не трогаем. Опоры (ножки, полозья, основание) — крупные куски, их условие не задевает.
    ПРЕДОХРАНИТЕЛЬ: если микро-осколки в сумме больше `max_share` площади меша, меш раздроблен «по природе» (стеклянная ваза, торшер с абажуром из нитей: осколки — часть поверхности, F пробил бы в ней дырки) — F не применяется."""
    from scipy.spatial import cKDTree
    keep = ~removed
    out = np.zeros(len(f), dtype=bool)
    if not keep.any():
        return out
    area = tri_areas(v, f)
    total = float(area.sum())
    ext = max(float(v[:, 1].max() - v[:, 1].min()), 1e-9)
    idx = np.nonzero(keep)[0]
    lab = label_components(f[idx], len(v))
    sm = {}
    big_idx = []
    for g in np.unique(lab):
        gi = idx[lab == g]
        if float(area[gi].sum()) >= small * total:
            big_idx.append(gi)
        else:
            sm[g] = gi
    if not big_idx or not sm:
        return out
    bi = np.concatenate(big_idx)
    pts = np.vstack([v[np.unique(f[bi].ravel())], v[f[bi]].mean(axis=1)])
    tree = cKDTree(pts)
    body_bottom = float(v[f[bi]][:, :, 1].min())
    hull_eq = None                                    # план тела: выпуклая оболочка нижней полосы (3 % высоты) крупных кусков
    try:
        from scipy.spatial import ConvexHull
        bp = v[np.unique(f[bi].ravel())]
        bp = bp[bp[:, 1] <= body_bottom + 0.03 * ext][:, [0, 2]]
        hull_eq = ConvexHull(bp).equations
    except Exception:
        hull_eq = None
    for gi in sm.values():
        if len(gi) >= max_faces:
            continue
        d, _ = tree.query(v[np.unique(f[gi].ravel())], k=1)
        on_floor = False
        if hull_eq is not None and float(v[f[gi]][:, :, 1].max()) <= body_bottom + floor_band * ext:
            c = v[f[gi]].mean(axis=(0, 1))[[0, 2]]
            on_floor = bool(np.any(hull_eq[:, :2] @ c + hull_eq[:, 2] > 0.0))      # центр СНАРУЖИ плана тела
        if float(d.min()) > gap * ext or on_floor:
            out[gi] = True
    if float(area[out].sum()) > max_share * total:
        return np.zeros(len(f), dtype=bool)
    return out


def slab_rule_e(v: np.ndarray, f: np.ndarray, flat_a: np.ndarray, use_f: bool = False) -> np.ndarray:
    """ПРАВИЛО ОЧИСТКИ E = куски A, выступающие из-под предмета (целиком) + B (горизонтальные группы у пола вне следа) + «пыль». Маска граней к удалению."""
    slab, _ = slab_faces(v, f)
    rem = slab_pieces(v, f, flat_a) | slab
    area = tri_areas(v, f)
    if float(area[rem].sum() / max(float(area.sum()), 1e-12)) >= 0.10:         # плита есть — убираем «пыль» её осколков; нет (стол «Тюлип») — «пыли» нет, поверхность предмета не трогаем
        rem = rem | slab_dust(v, f, rem)
    if not use_f:
        return rem
    return rem | floaters(v, f, rem)                                           # F: отлетевшие осколки в воздухе — всегда


def slab_faces(v: np.ndarray, f: np.ndarray, band: float = 0.25, top_from: float = 0.35, grow: float = 0.05, horiz: float = 0.8, min_h_share: float = 0.6) -> tuple[np.ndarray, dict]:
    """ВТОРОЕ ПРАВИЛО ОЧИСТКИ (проба 19.11, директор): «почти горизонтальный слой у пола, выходящий за след корпуса сверху» — ПО НОРМАЛЯМ И ВЫСОТЕ, не по связным кускам и не срезом по высоте.
    След корпуса = выпуклая оболочка (XZ) вершин верхней части (выше `top_from` высоты меша), раздутая на `grow` габарита. Кандидаты — грани с центром ниже `band` высоты меша и ЗА следом.
    Из кандидатов берутся связные группы; плитой считается группа, где ≥ `min_h_share` площади — горизонтальные грани (|нормаль_Y| ≥ `horiz`) И которая НЕ приросла к предмету выше полосы
    (общие вершины с гранями выше `band`): основание торшера/ножки приросли, плита и её обрывки лежат отдельно. Возвращает маску граней плиты и числа."""
    ymin, ymax = float(v[:, 1].min()), float(v[:, 1].max())
    h = max(ymax - ymin, 1e-9)
    up = v[:, 1] > ymin + top_from * h
    info = {'footprint_pts': int(up.sum())}
    if up.sum() < 10:
        return np.zeros(len(f), dtype=bool), info
    from scipy.spatial import ConvexHull
    pts = v[up][:, [0, 2]]
    hull = ConvexHull(pts)
    ext = max(np.ptp(pts[:, 0]), np.ptp(pts[:, 1]))
    eq = hull.equations                                      # n·x + d ≤ 0 внутри
    c = v[f].mean(1)
    inside = np.all(c[:, [0, 2]] @ eq[:, :2].T + eq[:, 2] <= grow * ext, axis=1)
    cand = (c[:, 1] <= ymin + band * h) & ~inside
    info.update({'footprint_area': round(float(hull.volume), 5), 'cand_faces': int(cand.sum())})
    if not cand.any():
        return cand, info
    nrm = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    area = 0.5 * np.linalg.norm(nrm, axis=1)
    ny = np.abs(nrm[:, 1]) / np.maximum(2 * area, 1e-12)
    idx = np.nonzero(cand)[0]
    above = c[:, 1] > ymin + band * h                        # грани выше полосы: к ним должны прирастать основание/ножки
    attached = np.zeros(len(v), dtype=bool)
    attached[np.unique(f[above])] = True
    lab = label_components(f[idx], len(v))
    out = np.zeros(len(f), dtype=bool)
    groups = []
    for g in np.unique(lab):
        gi = idx[lab == g]
        a_all = float(area[gi].sum())
        hs = float(area[gi][ny[gi] >= horiz].sum() / max(a_all, 1e-12))
        take = hs >= min_h_share and not attached[np.unique(f[gi])].any()
        groups.append({'faces': int(len(gi)), 'area': round(a_all, 5), 'h_share': round(hs, 2), 'attached_up': bool(attached[np.unique(f[gi])].any()), 'slab': bool(take)})
        if take:
            out[gi] = True
    info['groups'] = sorted(groups, key=lambda x: -x['area'])[:6]
    return out, info


def floor_contacts(v: np.ndarray, f: np.ndarray, keep: np.ndarray, band: float = 0.04) -> int:
    """Число «пятен опоры» (ножки/основание): связные группы граней с центром в нижних `band` высоты меша — по оставленным граням. Для «ножки до/после»."""
    ymin, ymax = float(v[:, 1].min()), float(v[:, 1].max())
    c = v[f].mean(1)
    sel = keep & (c[:, 1] <= ymin + band * max(ymax - ymin, 1e-9))
    if not sel.any():
        return 0
    return int(label_components(f[sel], len(v)).max() + 1)


def clean_glb(path: str, out_path: str | None = None, dims_cm=None, thin: float = 0.02, floor: float = 0.05, rule: str = 'E', tag: str = '') -> dict:
    """Очистка БЕЗ слияния примитивов: у каждого примитива (материала) свой `submesh`, материалы и текстуры сохраняются (Codex, директор 19.11).
    Связные куски считаются по ВСЕМ примитивам вместе (куски могут пересекать границу материала). Рядом, кроме `.clean.glb` и `.metrics.json`, кладётся `.audit.glb` —
    сохранённое как есть + удалённое одним ярко-красным материалом: по одному кадру на товар глазами проверить, что правило не срезало низкую полку, царгу, стеклянное основание."""
    import trimesh
    sc = trimesh.load(path, force='scene')
    parts = [g for g in sc.dump() if len(g.faces)]               # dump применяет узловые преобразования, материалы остаются у своих примитивов
    offs = np.cumsum([0] + [len(g.vertices) for g in parts])
    v = np.concatenate([np.asarray(g.vertices) for g in parts])
    f = np.concatenate([np.asarray(g.faces) + o for g, o in zip(parts, offs)])
    fo = np.cumsum([0] + [len(g.faces) for g in parts])           # границы граней по примитивам
    joint = trimesh.Trimesh(v, f, process=False)
    metrics, keep = analyse(joint, thin, floor)
    area = tri_areas(v, f)
    if rule in ('E', 'EF'):                          # новое правило (19.11, директор): плита по нормалям/следу + пыль; 'EF' — плюс микро-осколки в воздухе (F); 'A' — прежнее (только куски)
        keep = ~slab_rule_e(v, f, ~keep, use_f=(rule == 'EF'))
    metrics['rule'] = rule
    rem = ~keep
    metrics['primitives'] = len(parts)
    metrics['removed'] = {'tris': int(rem.sum()), 'area': round(float(area[rem].sum()), 5), 'area_share': round(float(area[rem].sum() / max(area.sum(), 1e-12)), 3)}
    if rem.any():
        rv = v[np.unique(f[rem])]
        ext = rv.max(0) - rv.min(0)
        metrics['removed']['bbox_xyz'] = [round(float(x), 4) for x in ext]
        iext = metrics.get('item_extent_xyz')
        if iext:
            metrics['removed']['bbox_volume_share_of_item_bbox'] = round(float(np.prod(ext) / max(np.prod(iext), 1e-12)), 3)       # у листов объёма нет — считаем объём габаритного ящика
    kept, removed = [], []
    for k, g in enumerate(parts):
        m = keep[fo[k]:fo[k + 1]]
        if m.any():
            kept.append(g.submesh([np.nonzero(m)[0]], append=True, repair=False))
        if (~m).any():
            removed.append(g.submesh([np.nonzero(~m)[0]], append=True, repair=False))
    out_path = out_path or path[:-4] + f'.clean{tag}.glb'
    trimesh.Scene(kept).export(out_path)
    metrics['clean_glb'] = os.path.basename(out_path)
    metrics['clean_tris'] = int(sum(len(g.faces) for g in kept))
    if removed:
        red = trimesh.visual.material.PBRMaterial(baseColorFactor=[230, 20, 20, 255], metallicFactor=0.0, roughnessFactor=0.9)
        marked = []
        for g in removed:
            g = g.copy()
            g.visual = trimesh.visual.TextureVisuals(material=red, uv=np.zeros((len(g.vertices), 2)))
            marked.append(g)
        audit = path[:-4] + f'.audit{tag}.glb'
        trimesh.Scene(kept + marked).export(audit)
        metrics['audit_glb'] = os.path.basename(audit)
    if dims_cm and 'item_ratio_w_d_h' in metrics:
        w, d, h = sorted(dims_cm[:2], reverse=True) + [dims_cm[2]]
        m = max(w, d, h)
        want = [round(w / m, 3), round(d / m, 3), round(h / m, 3)]
        metrics['feed_ratio_w_d_h'] = want
        metrics['ratio_error_pct'] = [round((a - b) / b * 100, 1) for a, b in zip(metrics['item_ratio_w_d_h'], want)]
    json.dump(metrics, open(path[:-4] + f'.metrics{tag}.json', 'w'), ensure_ascii=False, indent=1)
    return metrics


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('glb')
    ap.add_argument('--dims', type=float, nargs=3, default=None, help='габариты из фида, см: ширина глубина высота')
    ap.add_argument('--thin', type=float, default=0.02)
    ap.add_argument('--floor', type=float, default=0.05)
    a = ap.parse_args()
    print(json.dumps(clean_glb(a.glb, dims_cm=a.dims, thin=a.thin, floor=a.floor), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    sys.exit(main())

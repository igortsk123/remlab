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


def clean_glb(path: str, out_path: str | None = None, dims_cm=None, thin: float = 0.02, floor: float = 0.05) -> dict:
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
    out_path = out_path or path[:-4] + '.clean.glb'
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
        audit = path[:-4] + '.audit.glb'
        trimesh.Scene(kept + marked).export(audit)
        metrics['audit_glb'] = os.path.basename(audit)
    if dims_cm and 'item_ratio_w_d_h' in metrics:
        w, d, h = sorted(dims_cm[:2], reverse=True) + [dims_cm[2]]
        m = max(w, d, h)
        want = [round(w / m, 3), round(d / m, 3), round(h / m, 3)]
        metrics['feed_ratio_w_d_h'] = want
        metrics['ratio_error_pct'] = [round((a - b) / b * 100, 1) for a, b in zip(metrics['item_ratio_w_d_h'], want)]
    json.dump(metrics, open(path[:-4] + '.metrics.json', 'w'), ensure_ascii=False, indent=1)
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

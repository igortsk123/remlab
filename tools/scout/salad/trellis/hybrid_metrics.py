#!/usr/bin/env python3
"""ЧИСЛА ГИБРИДА «форма TRELLIS.2 + покраска Hunyuan» (T-20261118-91/2): меняет ли покраска форму.

    python hybrid_metrics.py --shape <clean.glb TRELLIS.2> --result <glb после покраски> [--out metrics.json]

Обе сетки приводятся к одной рамке (центр габарита в нуле, наибольший размер = 1; повёрнутых осей нет — обе в glTF Y-вверх, фасад к +Z), дальше:
  • Hausdorff форма↔результат по 30 тыс. точек на поверхности каждой сетки до поверхности другой, доля диагонали габарита: максимум, 99-й и 50-й процентиль, в обе стороны;
  • IoU силуэта спереди (XY), сбоку (ZY) и сверху (XZ) на растре 512² — до/после;
  • треугольники, связные куски (по рёбрам граней; крупных ≥ 0,1 % граней), доля граней в крупных;
  • ножки: куски, дотягивающиеся до пола (нижние 4 % высоты) — число и суммарная площадь сечения на высоте 2 % до/после, высота габарита до/после.
Сырой GLB не меняется. Только чтение."""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np
import trimesh


def load_norm(path: str) -> trimesh.Trimesh:
    m = trimesh.load(path, force='mesh')
    v = m.vertices - (m.bounds[0] + m.bounds[1]) / 2.0
    v = v / float(max(m.extents))
    return trimesh.Trimesh(vertices=v, faces=m.faces, process=False)


def hausdorff(a: trimesh.Trimesh, b: trimesh.Trimesh, n: int = 30_000) -> dict:
    """Точное расстояние от точек на поверхности одной сетки до ПОВЕРХНОСТИ другой (не до точек), доля диагонали габарита."""
    from trimesh.proximity import ProximityQuery
    diag = float(np.linalg.norm(a.extents))
    d_ab = ProximityQuery(b).on_surface(a.sample(n))[1] / diag
    d_ba = ProximityQuery(a).on_surface(b.sample(n))[1] / diag
    f = lambda d: {'max': round(float(d.max()), 4), 'p99': round(float(np.percentile(d, 99)), 4), 'p50': round(float(np.percentile(d, 50)), 5)}
    return {'shape_to_result': f(d_ab), 'result_to_shape': f(d_ba), 'hausdorff_max': round(float(max(d_ab.max(), d_ba.max())), 4)}


def silhouette(m: trimesh.Trimesh, axes: tuple[int, int], res: int = 512) -> np.ndarray:
    """Растр силуэта: заливка проекций треугольников (PIL), рамка [-0,55; 0,55] общая для обеих сеток."""
    from PIL import Image, ImageDraw
    img = Image.new('L', (res, res), 0)
    dr = ImageDraw.Draw(img)
    p = m.vertices[:, list(axes)]
    s = res / 1.1
    xy = np.stack([(p[:, 0] + 0.55) * s, (0.55 - p[:, 1]) * s], 1)
    for f in m.faces:
        dr.polygon([tuple(xy[i]) for i in f], fill=255)
    return np.asarray(img) > 0


def iou(a: np.ndarray, b: np.ndarray) -> float:
    u = np.logical_or(a, b).sum()
    return round(float(np.logical_and(a, b).sum() / u), 4) if u else 1.0


def components(m: trimesh.Trimesh) -> dict:
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    e = m.face_adjacency
    n = len(m.faces)
    g = coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(n, n))
    k, lab = connected_components(g, directed=False)
    sizes = np.bincount(lab, minlength=k)
    big = sizes >= max(1, int(0.001 * n))
    return {'pieces': int(k), 'pieces_big': int(big.sum()), 'faces_share_in_big': round(float(sizes[big].sum() / n), 4), 'label': lab, 'sizes': sizes, 'big': big}


def legs(m: trimesh.Trimesh, comp: dict) -> dict:
    ymin, h = float(m.bounds[0][1]), float(m.extents[1])
    lab = comp['label']
    fy = m.vertices[m.faces][:, :, 1].min(axis=1)                     # низ каждой грани
    touch = np.unique(lab[fy <= ymin + 0.04 * h])                      # куски, дотянувшиеся до пола
    touch = [int(t) for t in touch if comp['sizes'][t] >= 20]
    sl = m.section(plane_origin=[0, ymin + 0.02 * h, 0], plane_normal=[0, 1, 0])
    area = 0.0
    if sl is not None:
        try:
            area = float(sum(p.area for p in sl.to_planar()[0].polygons_full))
        except Exception:                                              # noqa: BLE001
            area = float('nan')
    return {'floor_pieces': len(touch), 'floor_section_area': round(area, 5), 'height_norm': round(h, 4)}


def run(shape: str, result: str) -> dict:
    a, b = load_norm(shape), load_norm(result)
    out = {'shape': shape, 'result': result, 'tris': {'shape': int(len(a.faces)), 'result': int(len(b.faces))},
           'extent_ratio_result_vs_shape': [round(float(x), 4) for x in (b.extents / a.extents)]}
    out['hausdorff'] = hausdorff(a, b)
    out['silhouette_iou'] = {name: iou(silhouette(a, ax), silhouette(b, ax)) for name, ax in (('front', (0, 1)), ('side', (2, 1)), ('top', (0, 2)))}
    ca, cb = components(a), components(b)
    out['components'] = {'shape': {k: v for k, v in ca.items() if k in ('pieces', 'pieces_big', 'faces_share_in_big')},
                         'result': {k: v for k, v in cb.items() if k in ('pieces', 'pieces_big', 'faces_share_in_big')}}
    out['legs'] = {'shape': legs(a, ca), 'result': legs(b, cb)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--shape', required=True)
    ap.add_argument('--result', required=True)
    ap.add_argument('--out')
    a = ap.parse_args()
    r = run(a.shape, a.result)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if a.out:
        json.dump(r, open(a.out, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())

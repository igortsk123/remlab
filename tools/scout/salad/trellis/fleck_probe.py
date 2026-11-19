#!/usr/bin/env python3
"""БЕЛЫЕ КРАПИНКИ ГИБРИДА (T-20261118-91/2): откуда они — из текстуры или из геометрии?
По каждой грани берём цвет текселя в центре грани (UV) и считаем долю «почти белых» (все каналы ≥ порога) среди граней и среди текселей атласа,
плюс — какая доля белых граней лежит у границы острова развёртки (грань, у которой соседа по UV нет). Только чтение.
Запуск: ~/venvs/scout/bin/python fleck_probe.py <гибрид.glb> [порог=235]"""
import json
import sys

import numpy as np
import trimesh


def main() -> int:
    path = sys.argv[1]
    thr = int(sys.argv[2]) if len(sys.argv) > 2 else 235
    sc = trimesh.load(path, force='scene')
    geoms = list(sc.geometry.values())
    out = []
    for g in geoms:
        vis = g.visual
        mat = getattr(vis, 'material', None)
        img = getattr(mat, 'baseColorTexture', None) or getattr(mat, 'image', None)
        if img is None or vis.uv is None:
            continue
        a = np.asarray(img.convert('RGB'))
        h, w = a.shape[:2]
        uv = np.asarray(vis.uv)
        f = g.faces
        c = uv[f].mean(axis=1)
        px = np.clip((c[:, 0] * (w - 1)).round().astype(int), 0, w - 1)
        py = np.clip(((1 - c[:, 1]) * (h - 1)).round().astype(int), 0, h - 1)
        col = a[py, px]
        white = (col >= thr).all(axis=1)
        atlas_white = float(((a >= thr).all(axis=2)).mean())
        # граница острова: у грани есть ребро, которое в UV не склеено (вершины при сшивке по позиции совпадают, по UV — нет)
        pos_edges = {}
        for i, tri in enumerate(f):
            for k in range(3):
                e = tuple(sorted((tuple(np.round(g.vertices[tri[k]], 6)), tuple(np.round(g.vertices[tri[(k + 1) % 3]], 6)))))
                pos_edges.setdefault(e, []).append((i, k))
        uv_edges = {}
        for i, tri in enumerate(f):
            for k in range(3):
                e = tuple(sorted((tuple(np.round(uv[tri[k]], 6)), tuple(np.round(uv[tri[(k + 1) % 3]], 6)))))
                uv_edges.setdefault(e, []).append(i)
        edge_face = np.zeros(len(f), dtype=bool)
        for e, lst in uv_edges.items():
            if len(lst) == 1:
                edge_face[lst[0]] = True
        out.append({'faces': int(len(f)), 'atlas': [w, h], 'white_faces_share': round(float(white.mean()), 4), 'white_faces': int(white.sum()),
                    'white_texels_share_atlas': round(atlas_white, 4), 'island_edge_faces_share': round(float(edge_face.mean()), 4),
                    'white_among_island_edge_faces': round(float(white[edge_face].mean()), 4) if edge_face.any() else None,
                    'white_among_inner_faces': round(float(white[~edge_face].mean()), 4) if (~edge_face).any() else None})
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())

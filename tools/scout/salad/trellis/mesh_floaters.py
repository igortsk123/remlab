#!/usr/bin/env python3
"""ОБЩИЙ ШАГ ПОСЛЕ ГЕНЕРАЦИИ ФОРМЫ — убрать отдельные осколки (T-20261119-94/2, владелец TG 1980: «пробуй артефакты сверху дивана удалять»).

Осколок = связный кусок сетки (общие вершины после склейки одинаковых), площадь которого меньше `frac` площади САМОГО БОЛЬШОГО куска. Правило одно для всех товаров и всех моделей;
порог — параметр (по умолчанию 1 %, строже — 0,1 %). Что приросло к телу (одна связная поверхность) этим шагом не убирается — это задача RemeshMesh (`drop_small_components`,
`drop_enclosed_components`, `drop_inverted_components`) в ComfyUI. Шаг не меняет геометрию оставшегося: вершины и грани те же, только без осколков (удалённые вершины вычищаются).

Запуск: python mesh_floaters.py <in.glb> <out.glb> [--frac 0.01] [--report r.json]  (нужны trimesh, numpy, scipy; без видеокарты, секунды)
Отчёт: сколько кусков было/осталось/убрано, доля площади и граней, крупнейшие убранные (площадь, центр, высота по оси Y — вверх в glTF).
"""
from __future__ import annotations

import argparse
import json
import sys


def component_report(areas: list[float], frac: float) -> dict:
    """Чистая часть без trimesh: какие куски (индексы) уходят при пороге `frac` от площади крупнейшего. `areas` — площади кусков."""
    if not areas:
        raise ValueError('нет кусков')
    if not (0 <= frac < 1):
        raise ValueError(f'frac {frac}: нужно от 0 до 1 (не включая 1)')
    big = max(areas)
    total = sum(areas)
    drop = [i for i, a in enumerate(areas) if a < frac * big]
    return {'parts': len(areas), 'dropped': len(drop), 'kept': len(areas) - len(drop), 'drop_idx': drop,
            'area_total': total, 'area_dropped': sum(areas[i] for i in drop), 'area_share_dropped': (sum(areas[i] for i in drop) / total) if total else 0.0,
            'largest_area': big, 'threshold_area': frac * big}


def remove_floaters(mesh, frac: float = 0.01):
    """trimesh.Trimesh → (новый Trimesh без осколков, отчёт). Исходный не меняется. Без `split()` (он копирует каждый кусок и на сотнях тысяч граней съедает ~18 ГБ): связность — scipy по рёбрам-вершинам, площади — numpy."""
    import numpy as np
    import scipy.sparse as sp
    from scipy.sparse.csgraph import connected_components
    import trimesh
    m = trimesh.Trimesh(vertices=np.asarray(mesh.vertices), faces=np.asarray(mesh.faces), process=False)      # только форма: у текстурного меша вершины раздвоены по швам развёртки — склеиваем ПО ПОЛОЖЕНИЮ, иначе каждый островок развёртки = «осколок»
    m.merge_vertices(merge_tex=True, merge_norm=True)
    f = np.asarray(m.faces)
    v = np.asarray(m.vertices, dtype=np.float64)
    n = len(v)
    g = sp.coo_matrix((np.ones(len(f) * 2, dtype=np.int8), (np.concatenate([f[:, 0], f[:, 1]]), np.concatenate([f[:, 1], f[:, 2]]))), shape=(n, n))
    ncomp, lab = connected_components(g, directed=False)
    fl = lab[f[:, 0]]                                                     # метка куска у каждой грани (по первой вершине)
    farea = 0.5 * np.linalg.norm(np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]]), axis=1)
    used = np.unique(fl)
    areas_arr = np.bincount(fl, weights=farea, minlength=ncomp)
    fcount = np.bincount(fl, minlength=ncomp)
    ids = [int(c) for c in used]
    areas = [float(areas_arr[c]) for c in ids]
    rep = component_report(areas, frac)
    drop_ids = {ids[i] for i in rep['drop_idx']}
    rep['faces_total'] = int(len(f))
    rep['faces_dropped'] = int(sum(fcount[c] for c in drop_ids))
    items = []
    for c in drop_ids:
        fv = f[fl == c]
        pts = v[np.unique(fv)]
        items.append({'area': float(areas_arr[c]), 'area_pct_of_largest': 100 * float(areas_arr[c]) / rep['largest_area'], 'faces': int(fcount[c]),
                      'center': [round(float(x), 5) for x in pts.mean(axis=0)], 'y_max': round(float(pts[:, 1].max()), 5)})
    rep['dropped_list'] = sorted(items, key=lambda d: -d['area'])[:200]       # в отчёт — 200 крупнейших убранных, счётчики — по всем
    keep_mask = ~np.isin(fl, list(drop_ids)) if drop_ids else np.ones(len(f), dtype=bool)
    out = trimesh.Trimesh(vertices=m.vertices, faces=f[keep_mask], process=False)
    out.remove_unreferenced_vertices()
    rep['bounds_before'] = np.round(m.bounds, 5).tolist()
    rep['bounds_after'] = np.round(out.bounds, 5).tolist()
    return out, rep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--frac', type=float, default=0.01)
    ap.add_argument('--report', default=None)
    a = ap.parse_args()
    import trimesh
    sc = trimesh.load(a.src, force='scene')
    geoms = list(sc.geometry.values())
    if len(geoms) != 1:
        print(f'в {a.src} {len(geoms)} мешей, нужен один — стоп', file=sys.stderr)
        return 2
    src = geoms[0]
    out, rep = remove_floaters(src, a.frac)
    if getattr(src.visual, 'kind', None) == 'texture':
        print('предупреждение: у меша текстура — шаг рассчитан на форму без краски, цвета/развёртка не сохраняются', file=sys.stderr)
    out.export(a.dst)
    line = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in rep.items() if k not in ('drop_idx', 'dropped_list', 'bounds_before', 'bounds_after')}
    print(json.dumps(line, ensure_ascii=False))
    if a.report:
        json.dump(rep, open(a.report, 'w'), ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.exit(main())

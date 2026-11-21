#!/usr/bin/env python3
"""Мерки разметки частей на гранях (CPU, без GPU). Ничего в дерево проекта не пишет.
  label_stats.py islands <input.glb> <faces.npy>            → островки: связные куски одной метки; доля граней в островках < N граней (N=10/20/50/200)
  label_stats.py compare <input.glb> <faces_a.npy> <faces_b.npy> → совпадение разметок A (эталон, полная) и B (быстрая): доля граней при лучшем сопоставлении частей (венгерский) + ARI
Метки у разных прогонов — произвольные номера, поэтому сравнение идёт через сопоставление частей, а не «метка == метка»."""
import json, sys
import numpy as np, trimesh
import scipy.sparse as sp
from scipy.sparse.csgraph import connected_components
from scipy.optimize import linear_sum_assignment


def geometry(mesh):
    m = trimesh.Trimesh(vertices=np.asarray(mesh.vertices), faces=np.asarray(mesh.faces), process=False)   # только геометрия, без UV/нормалей
    m.merge_vertices(merge_tex=True, merge_norm=True)     # порядок и число граней не меняются
    assert len(m.faces) == len(mesh.faces)
    return m


def label_components(adj, lab, n):
    same = lab[adj[:, 0]] == lab[adj[:, 1]]
    a = adj[same]
    nc, cc = connected_components(sp.coo_matrix((np.ones(len(a), np.int8), (a[:, 0], a[:, 1])), shape=(n, n)), directed=False)
    nm, mc = connected_components(sp.coo_matrix((np.ones(len(adj), np.int8), (adj[:, 0], adj[:, 1])), shape=(n, n)), directed=False)
    # кусок меша (mc) из одной метки-компоненты — «плавающий обломок» геометрии, не островок разметки
    comp_mesh = np.zeros(nc, np.int64); comp_mesh[cc] = mc
    per_mesh = np.bincount(comp_mesh, minlength=nm)
    lone = per_mesh[comp_mesh] == 1
    return nc, cc, lone


def clean_islands(mesh, lab, min_area_frac=0.001):
    """Общее правило для всех мешей: связный кусок одной метки площадью < min_area_frac площади меша сливается с соседним куском
    по наибольшей общей границе (длина общего ребра); после слияния одноимённые соседи склеиваются. Идём от самого мелкого куска (граф кусков,
    без одновременных обменов). Возвращает (новые метки, отчёт)."""
    import heapq
    m = geometry(mesh)
    lab = lab.astype(np.int64).copy()
    adj = np.asarray(m.face_adjacency)
    ev = np.asarray(m.vertices)
    ed = np.asarray(m.face_adjacency_edges)
    elen = np.linalg.norm(ev[ed[:, 0]] - ev[ed[:, 1]], axis=1)
    area = np.asarray(m.area_faces)
    thr = min_area_frac * area.sum()
    n = len(lab)
    same = lab[adj[:, 0]] == lab[adj[:, 1]]
    a = adj[same]
    nc, cc = connected_components(sp.coo_matrix((np.ones(len(a), np.int8), (a[:, 0], a[:, 1])), shape=(n, n)), directed=False)
    carea = np.bincount(cc, weights=area).astype(float)
    _, _, lone0 = label_components(adj, lab, n)
    clab = np.zeros(nc, np.int64)
    clab[cc] = lab
    rep = {'min_area_frac': min_area_frac, 'islands_before': int(((carea < thr) & ~lone0).sum()), 'components_before': int(nc), 'labels_before': int(len(np.unique(lab)))}
    diff = ~same
    pa, pb, w = cc[adj[diff, 0]], cc[adj[diff, 1]], elen[diff]
    nb = [dict() for _ in range(nc)]
    for x, y, ww in zip(pa.tolist(), pb.tolist(), w.tolist()):
        nb[x][y] = nb[x].get(y, 0.0) + ww
        nb[y][x] = nb[y].get(x, 0.0) + ww
    parent = list(range(nc))
    alive = [True] * nc
    def merge(s_, t_):          # s_ вливается в t_ (метка t_ остаётся)
        parent[s_] = t_
        alive[s_] = False
        carea[t_] += carea[s_]
        for u, ww in nb[s_].items():
            if u == t_:
                continue
            nb[t_][u] = nb[t_].get(u, 0.0) + ww
            nb[u][t_] = nb[u].get(t_, 0.0) + ww
            nb[u].pop(s_, None)
        nb[t_].pop(s_, None)
        nb[s_] = {}
        # одноимённые соседи нового куска склеиваем
        for u in [u for u in nb[t_] if clab[u] == clab[t_]]:
            if alive[u]:
                big, small = (t_, u) if carea[t_] >= carea[u] else (u, t_)
                merge(small, big)
                return
    while True:        # повтор: после слияний площади куска меняются, устаревшие записи кучи пропускаются — пересобираем, пока есть малые куски с соседями
        heap = [(carea[i], i) for i in range(nc) if alive[i] and carea[i] < thr and nb[i]]
        if not heap:
            break
        heapq.heapify(heap)
        while heap:
            ar, i = heapq.heappop(heap)
            if not alive[i] or ar != carea[i] or carea[i] >= thr or not nb[i]:
                continue
            t = max(nb[i], key=lambda u: nb[i][u])
            merge(i, t)
            r = t
            while not alive[r]:
                r = parent[r]
            if carea[r] < thr and nb[r]:
                heapq.heappush(heap, (carea[r], r))
    root = np.arange(nc)
    for i in range(nc):
        r = i
        while not alive[r]:
            r = parent[r]
        root[i] = r
    new = clab[root[cc]]
    # куски без общих рёбер ни с кем (плавающие обломки самой геометрии) — по рёбрам не слить: берём метку ближайшей грани крупного куска
    from scipy.spatial import cKDTree
    rcarea = np.zeros(nc)
    for i in range(nc):
        if alive[i]:
            rcarea[i] = carea[i]
    big_comp = rcarea >= thr
    face_root = root[cc]
    isolated = (rcarea < thr) & np.array(alive)
    iso_faces = isolated[face_root]
    n_floaters = int(isolated.sum())
    if iso_faces.any() and (~iso_faces).any():
        cen = np.asarray(m.triangles_center)
        tree = cKDTree(cen[~iso_faces])
        ref_lab = new[~iso_faces]
        for r_ in np.where(isolated)[0]:         # один обломок — одна метка (метка ближайшей грани к его центру), а не по граням
            fs = np.where(face_root == r_)[0]
            if len(fs) == 0:
                continue
            d, j = tree.query(cen[fs].mean(0))
            new[fs] = ref_lab[j]
    rep['floaters_nearest'] = n_floaters
    same2 = new[adj[:, 0]] == new[adj[:, 1]]
    a2 = adj[same2]
    nc1, cc1, lone1 = label_components(adj, new, n)
    ca1 = np.bincount(cc1, weights=area)
    rep.update({'islands_after': int(((ca1 < thr) & ~lone1).sum()), 'components_after': int(nc1), 'labels_after': int(len(np.unique(new))), 'faces_changed_share': round(float((new != lab).mean()), 4), 'area_changed_share': round(float(area[new != lab].sum() / area.sum()), 4)})
    return new, rep


def adjacency(mesh):
    m = trimesh.Trimesh(vertices=np.asarray(mesh.vertices), faces=np.asarray(mesh.faces), process=False)   # только геометрия, без UV/нормалей (иначе швы текстуры не склеиваются)
    m.merge_vertices(merge_tex=True, merge_norm=True)          # в glb вершины размножены по швам текстуры: без склейки соседство граней рвётся (порядок граней не меняется)
    assert len(m.faces) == len(mesh.faces)
    return np.asarray(m.face_adjacency)


def islands(mesh, lab, Ns=(10, 20, 50, 200)):
    m = geometry(mesh)
    adj = np.asarray(m.face_adjacency)
    n = len(lab)
    nc, cc, lone = label_components(adj, lab, n)
    sizes = np.bincount(cc)
    isl_ok = ~lone[cc]                       # грани, чей кусок разметки — не одинокий обломок
    out = {'n_faces': n, 'n_labels': int(len(np.unique(lab[lab >= 0]))), 'n_components': int(nc), 'floaters_geometry': int(lone.sum()), 'floaters_face_share': round(float((~isl_ok).mean()), 4), 'unlabeled_share': round(float((lab < 0).mean()), 4)}
    for N in Ns:
        small = (sizes[cc] < N) & isl_ok
        out[f'faces_in_islands_lt{N}'] = round(float(small.mean()), 4)
        out[f'n_islands_lt{N}'] = int(((sizes < N) & ~lone).sum())
    big = np.argsort(-sizes)[:5]
    out['largest_components'] = [int(sizes[b]) for b in big]
    return out


def ari(a, b):
    ua, ia = np.unique(a, return_inverse=True)
    ub, ib = np.unique(b, return_inverse=True)
    c = sp.coo_matrix((np.ones(len(a)), (ia, ib)), shape=(len(ua), len(ub))).toarray()
    comb2 = lambda x: x * (x - 1) / 2
    s_ij = comb2(c).sum(); s_a = comb2(c.sum(1)).sum(); s_b = comb2(c.sum(0)).sum(); tot = comb2(len(a))
    exp = s_a * s_b / tot
    mx = (s_a + s_b) / 2
    return float((s_ij - exp) / (mx - exp + 1e-12))


def compare(a, b):
    ua, ia = np.unique(a, return_inverse=True)
    ub, ib = np.unique(b, return_inverse=True)
    c = sp.coo_matrix((np.ones(len(a)), (ia, ib)), shape=(len(ua), len(ub))).toarray()
    r, k = linear_sum_assignment(-c)
    return {'agree_hungarian': round(float(c[r, k].sum() / len(a)), 4), 'ARI': round(ari(a, b), 4), 'parts_A': int(len(ua)), 'parts_B': int(len(ub))}


if __name__ == '__main__':
    mode, glb = sys.argv[1], sys.argv[2]
    mesh = trimesh.load(glb, force='mesh', process=False)
    if mode == 'islands':
        print(json.dumps(islands(mesh, np.load(sys.argv[3])), ensure_ascii=False))
    elif mode == 'clean':      # clean <glb> <faces.npy> <out.npy> [min_area_frac]
        lab, rep = clean_islands(mesh, np.load(sys.argv[3]), float(sys.argv[5]) if len(sys.argv) > 5 else 0.001)
        np.save(sys.argv[4], lab.astype(np.int32))
        rep.update(islands(mesh, lab))
        print(json.dumps(rep, ensure_ascii=False))
    elif mode == 'compare':
        A, B = np.load(sys.argv[3]), np.load(sys.argv[4])
        assert len(A) == len(B) == len(mesh.faces)
        print(json.dumps(compare(A, B), ensure_ascii=False))

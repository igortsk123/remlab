#!/usr/bin/env python3
"""Части меша по кадрам облёта: области SAM2 на каждом кадре → общие части на гранях голосованием (paint-photo-fill-01, этап 3, T-20261120-169).

ЗАЧЕМ. Цвет и материал красим ЧАСТЯМИ (ножки, столешница, каркас, обивка, стекло). Геометрия `material_parts.py` умеет только «ножки / не ножки»;
SAM2 (Apache) обводит области на картинке любого вида — но на одном кадре область не знает граней, а на разных кадрах одна часть получает разные номера.
Здесь — чистая математика без torch и Blender: ей на вход идут готовые карты областей кадров и видимость граней (`parts_orbit_blender.py`).

КАК. 1) `label_map` — маски кадра → карта «номер области на пиксель» (мелкая область перекрывает крупную; слишком малые и слишком крупные — прочь).
2) `view_face_regions` — каждая видимая грань берёт область под своей проекцией. 3) `merge_regions` — области разных кадров, у которых совпали грани
(IoU по граням, видимым в обоих кадрах), сливаются в одну часть (union-find). 4) `vote_faces` — грань получает часть с наибольшим весом (вес — косинус угла к камере);
согласие кадров = доля веса победителя. 5) `fill_unlabeled` — грани, которых не видел ни один кадр, берут часть ближайших граней по сетке (не сквозь пустоту).
6) `small_parts_to_neighbours` — мелкие части (< доли граней) уходят в соседей. 7) `geometry_overlap` — сверка с ножками из `material_parts.py`: часть, которая на ≥ порога лежит на ножках, получает роль `legs`.
Пороги — в `data/flat3d/parts-sam-rules.json`; ID товаров в код не попадают.
"""
from __future__ import annotations

import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RULES_PATH = os.path.join(ROOT, "data", "flat3d", "parts-sam-rules.json")


def load_rules(path: str = RULES_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def label_map(masks: list[np.ndarray], object_mask: np.ndarray, rules: dict) -> np.ndarray:
    """Маски кадра → карта областей (−1 — нет). Крупные рисуются первыми, мелкие поверх; считается только то, что внутри предмета (`object_mask`)."""
    area_obj = max(1, int(object_mask.sum()))
    lo, hi = rules["region"]["min_area_share"], rules["region"]["max_area_share"]
    keep = []
    for m in masks:
        mm = m & object_mask
        share = mm.sum() / area_obj
        if lo <= share <= hi:
            keep.append((int(mm.sum()), mm))
    keep.sort(key=lambda t: -t[0])
    out = np.full(object_mask.shape, -1, dtype=np.int32)
    for i, (_, mm) in enumerate(keep):
        out[mm] = i
    return out


def view_face_regions(lmap: np.ndarray, u: np.ndarray, v: np.ndarray, vis: np.ndarray) -> np.ndarray:
    """Область под проекцией каждой видимой грани (−1 — не видна или вне областей). u, v — пиксельные координаты центров граней."""
    h, w = lmap.shape
    out = np.full(len(u), -1, dtype=np.int32)
    ok = vis & (u >= 0) & (u < w) & (v >= 0) & (v < h)
    iu, iv = u[ok].astype(int), v[ok].astype(int)
    out[ok] = lmap[iv, iu]
    return out


class _DSU:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, a: int) -> int:
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def merge_regions(view_regions: list[np.ndarray], view_vis: list[np.ndarray], rules: dict) -> tuple[list[dict[int, int]], int]:
    """Области кадров → общие части. Возвращает (на кадр: {номер области → номер части}, число частей). Пары с IoU по общим видимым граням ≥ порога сливаются."""
    from scipy import sparse

    nv = len(view_regions)
    nodes = []                                   # (кадр, область)
    rows, cols = [], []
    for i, reg in enumerate(view_regions):
        for r in np.unique(reg[reg >= 0]):
            k = len(nodes)
            nodes.append((i, int(r)))
            idx = np.nonzero(reg == r)[0]
            rows.extend([k] * len(idx))
            cols.extend(idx.tolist())
    n = len(nodes)
    if n == 0:
        return [dict() for _ in range(nv)], 0
    nf = len(view_regions[0])
    m = sparse.csr_matrix((np.ones(len(rows), dtype=np.float32), (rows, cols)), shape=(n, nf))
    vmat = sparse.csr_matrix(np.array(view_vis, dtype=np.float32))          # кадры × грани
    inter = (m @ m.T).tocoo()
    seen = np.asarray((m @ vmat.T).todense())                                # узел × кадр: сколько граней узла видно в кадре j
    dsu = _DSU(n)
    thr, min_f = rules["merge"]["iou"], rules["merge"]["min_faces"]
    for a, b, c in zip(inter.row, inter.col, inter.data):
        if a >= b or nodes[a][0] == nodes[b][0] or c < min_f:
            continue
        ia, ib = nodes[a][0], nodes[b][0]
        union = seen[a, ib] + seen[b, ia] - c
        if union > 0 and c / union >= thr:
            dsu.union(a, b)
    roots = {}
    per_view: list[dict[int, int]] = [dict() for _ in range(nv)]
    for k, (i, r) in enumerate(nodes):
        root = dsu.find(k)
        per_view[i][r] = roots.setdefault(root, len(roots))
    return per_view, len(roots)


def vote_faces(view_regions: list[np.ndarray], mapping: list[dict[int, int]], weights: list[np.ndarray], n_parts: int) -> tuple[np.ndarray, np.ndarray]:
    """Часть на грань по весу кадров. Возвращает (часть −1/0.., согласие 0..1 — доля веса победителя от всего веса грани)."""
    nf = len(view_regions[0])
    acc = np.zeros((nf, max(1, n_parts)), dtype=np.float32)
    for reg, mp, w in zip(view_regions, mapping, weights):
        for r, p in mp.items():
            sel = reg == r
            acc[sel, p] += w[sel]
    tot = acc.sum(axis=1)
    part = np.where(tot > 0, acc.argmax(axis=1), -1).astype(np.int32)
    agree = np.where(tot > 0, acc.max(axis=1) / np.maximum(tot, 1e-9), 0.0).astype(np.float32)
    return part, agree


def weld_adjacency(vertices: np.ndarray, faces: np.ndarray, decimals: int = 5):
    """Соседство граней по общим вершинам с совмещёнными по положению копиями (швы развёртки не рвут соседство). Разреженная матрица граней × граней."""
    from scipy import sparse

    key = np.round(vertices.astype(np.float64), decimals)
    _, inv = np.unique(key, axis=0, return_inverse=True)
    wf = np.asarray(inv).reshape(-1)[faces]                                  # грани в сваренных индексах
    nf = len(faces)
    nvw = int(wf.max()) + 1
    vf = sparse.csr_matrix((np.ones(wf.size, dtype=np.float32), (wf.ravel(), np.repeat(np.arange(nf), 3))), shape=(nvw, nf))
    adj = (vf.T @ vf).tocsr()
    adj.setdiag(0)
    adj.eliminate_zeros()
    return adj


def fill_unlabeled(part: np.ndarray, adj, max_rounds: int = 200) -> np.ndarray:
    """Грани без части берут часть соседей (волной по сетке; несколько раундов, пока есть кому). Остались без соседей с частью — −1."""
    from scipy import sparse

    part = part.copy()
    nf = len(part)
    for _ in range(max_rounds):
        todo = part < 0
        if not todo.any() or not (~todo).any():
            break
        lab = np.nonzero(~todo)[0]
        onehot = sparse.csr_matrix((np.ones(len(lab), dtype=np.float32), (lab, part[lab])), shape=(nf, int(part.max()) + 1))
        votes = (adj @ onehot).tocsr()                                       # грань × часть: голоса соседей
        got = np.asarray(votes.max(axis=1).todense()).ravel() > 0
        sel = todo & got
        if not sel.any():
            break
        part[sel] = np.asarray(votes[sel].argmax(axis=1)).ravel()
    return part


def small_parts_to_neighbours(part: np.ndarray, adj, min_share: float) -> np.ndarray:
    """Часть меньше доли граней отдаётся самому частому соседу (по ребру/вершине); одинокая — остаётся."""
    part = part.copy()
    nf = max(1, int((part >= 0).sum()))
    changed = True
    while changed:
        changed = False
        ids, cnt = np.unique(part[part >= 0], return_counts=True)
        for p, c in sorted(zip(ids, cnt), key=lambda t: t[1]):
            if c / nf >= min_share:
                continue
            fs = np.nonzero(part == p)[0]
            nb = np.concatenate([adj[f].indices for f in fs]) if len(fs) else np.array([], dtype=int)
            lab = part[nb]
            lab = lab[(lab >= 0) & (lab != p)]
            if len(lab):
                part[fs] = np.bincount(lab).argmax()
                changed = True
                break
    return part


def renumber(part: np.ndarray) -> np.ndarray:
    """Номера частей подряд от 0, по убыванию числа граней."""
    ids, cnt = np.unique(part[part >= 0], return_counts=True)
    order = ids[np.argsort(-cnt, kind="stable")]
    out = np.full_like(part, -1)
    for new, old in enumerate(order):
        out[part == old] = new
    return out


def geometry_overlap(part: np.ndarray, legs: np.ndarray, rules: dict) -> dict:
    """Сверка с ножками геометрии: доля части на ножках → роль `legs`; согласие = IoU(объединение ножечных частей, маска геометрии)."""
    thr = rules["geometry"]["legs_overlap"]
    roles, legs_parts = {}, []
    for p in np.unique(part[part >= 0]):
        sel = part == p
        share = float((sel & legs).sum() / max(1, sel.sum()))
        roles[int(p)] = {"legs_share": round(share, 3), "role": "legs" if share >= thr and legs.any() else None}
        if roles[int(p)]["role"]:
            legs_parts.append(p)
    union = np.isin(part, legs_parts) if legs_parts else np.zeros_like(legs)
    iou = float((union & legs).sum() / max(1, (union | legs).sum())) if legs.any() or union.any() else None
    return {"roles": roles, "legs_iou": None if iou is None else round(iou, 3), "geometry_legs_faces": int(legs.sum())}


def colour_verdict(has_texture: bool, texture_std: float | None, rules: dict) -> tuple[bool, str]:
    """Годен ли вход по цвету. SAM2 на форме без цвета («глина») идёт за тенями и рвёт столешницу на клинья, а ножки — на отдельные части (T-169: стол, 16 частей, согласие кадров 0,49),
    поэтому вход без baseColor или с плоской текстурой — отказ этапа, а не «ноль частей»."""
    if not has_texture:
        return False, "вход без цвета (нет baseColor): SAM2 по теням рвёт части — нужен родной цвет TRELLIS.2 или покраска"
    lo = rules["check"]["input_min_texture_std"]
    if texture_std is None or texture_std < lo:
        return False, f"текстура входа плоская (разброс яркости {texture_std if texture_std is None else round(texture_std, 1)} < {lo}): цвета для частей нет"
    return True, "ok"


def quality(part: np.ndarray, agree: np.ndarray, seen_any: np.ndarray, rules: dict) -> dict:
    """Мерки этапа 3 для check.json: доля граней с частью, число частей, согласие кадров, доля граней, увиденных хотя бы одним кадром."""
    nf = len(part)
    lab = part >= 0
    ids, cnt = np.unique(part[lab], return_counts=True)
    seen_n = int(seen_any.sum())
    agree_seen = agree[seen_any & lab] if (seen_any & lab).any() else np.array([0.0])
    m = {
        "faces": nf,
        "faces_with_part_share": round(float(lab.mean()), 4),
        "faces_seen_by_views_share": round(seen_n / max(1, nf), 4),
        "n_parts": int(len(ids)),
        "part_face_shares": [round(float(c) / max(1, lab.sum()), 4) for c in cnt[np.argsort(-cnt)]],
        "frames_agreement_mean": round(float(agree_seen.mean()), 4),
        "frames_agreement_share_ge": round(float((agree_seen >= rules["check"]["agreement_face"]).mean()), 4),
    }
    ck = rules["check"]
    reasons = []
    if m["faces_with_part_share"] < ck["min_faces_with_part"]:
        reasons.append("мало граней с частью")
    if not (ck["min_parts"] <= m["n_parts"] <= ck["max_parts"]):
        reasons.append(f"число частей {m['n_parts']} вне {ck['min_parts']}–{ck['max_parts']}")
    if m["frames_agreement_mean"] < ck["min_agreement"]:
        reasons.append("кадры спорят о частях")
    m["ok"] = not reasons
    m["reason"] = "; ".join(reasons) if reasons else "ok"
    return m


def run_vote(view_regions: list[np.ndarray], view_vis: list[np.ndarray], weights: list[np.ndarray], vertices: np.ndarray, faces: np.ndarray, rules: dict) -> dict:
    """Всё голосование разом: области кадров → части на гранях + мерки."""
    mapping, n_parts = merge_regions(view_regions, view_vis, rules)
    part, agree = vote_faces(view_regions, mapping, weights, n_parts)
    seen_any = part >= 0
    adj = weld_adjacency(vertices, faces)
    part = fill_unlabeled(part, adj)
    part = small_parts_to_neighbours(part, adj, rules["region"]["min_part_face_share"])
    part = renumber(part)
    return {"part": part, "agree": agree, "seen_any": seen_any, "adj": adj, "n_parts_raw": n_parts}

#!/usr/bin/env python3
"""Форма куска поверхности без цвета и без частей этапа 3 (T-20261121-170/4): тонкая стойка/трубка, плоская панель или объёмный комок.

ЗАЧЕМ. Товар без частей этапа 3 (плоская текстура входа, этап 3 не дал частей) раньше целиком шёл «не уверен». Каталог говорит, ИЗ ЧЕГО сделан товар
(корпус — ЛДСП, плафон — стекло, ножки — металл); форма говорит, ГДЕ какая часть: стойка торшера — тонкая линия, корпус шкафа — плоские панели, плафон — шар
в верхней части. Класс берёт этап 08 из каталога, форма только выбирает, к каким граням он относится (`material_stage.geometry_shape_parts`).

КАК. По центрам граней, прореженным сеткой (одна точка на ячейку радиус/`cells_per_radius`), — локальный PCA в радиусе `radius_frac`·L (L — наибольший габарит, значит при любом масштабе модели): σ1≥σ2≥σ3 — разброс точек
вдоль главных осей. linear: σ2/σ1 ≤ `linear_ratio` (точки вытянуты в линию — трубка, стойка); planar: σ3/σ2 ≤ `planar_ratio` (плоская панель);
иначе blob (комок, шар). Мало соседей (`min_neighbors`) — blob. Пороги — `data/flat3d/material-recipes.json` → `geometry`, не здесь. ID товаров нет.
Вертикаль модели — ось Y (glTF); `up_frac` — высота центра грани в долях габарита по Y (0 низ, 1 верх).
"""
from __future__ import annotations

import numpy as np

PLANAR, LINEAR, BLOB = 0, 1, 2
NAMES = {PLANAR: "planar", LINEAR: "linear", BLOB: "blob"}


def face_shapes(vertices: np.ndarray, faces: np.ndarray, g: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    """→ (вид на грань: 0 planar / 1 linear / 2 blob, up_frac на грань, отчёт). `g` — блок `geometry` из material-recipes.json."""
    from scipy.spatial import cKDTree

    v = np.asarray(vertices, dtype=np.float64)
    f = np.asarray(faces)
    c = v[f].mean(axis=1)
    n = len(c)
    ext = c.max(axis=0) - c.min(axis=0)
    ll = float(max(ext.max(), 1e-9))
    lo, hi = float(v[:, 1].min()), float(v[:, 1].max())
    up = np.clip((c[:, 1] - lo) / max(hi - lo, 1e-9), 0.0, 1.0)
    k = int(g["k"])
    radius = float(g["radius_frac"]) * ll
    cell = radius / float(g["cells_per_radius"])               # опорные точки — по одной на ячейку сетки: густота не зависит от числа граней и площади, радиус задаёт масштаб
    key = np.floor((c - c.min(axis=0)) / cell).astype(np.int64)
    _, first = np.unique(key, axis=0, return_index=True)
    pts = c[first]
    ns = len(pts)
    tree = cKDTree(pts)
    d, idx = tree.query(c, k=min(k, ns), distance_upper_bound=radius)
    ok = np.isfinite(d)
    idx = np.where(ok, idx, 0)
    cnt = ok.sum(axis=1)
    w = ok[..., None].astype(np.float64)
    q = pts[idx]
    mean = (q * w).sum(axis=1) / np.maximum(cnt, 1)[:, None]
    dev = (q - mean[:, None, :]) * w
    cov = np.einsum("nki,nkj->nij", dev, dev) / np.maximum(cnt, 1)[:, None, None]
    ev = np.linalg.eigvalsh(cov)                     # по возрастанию
    s = np.sqrt(np.maximum(ev, 0.0))
    s3, s2, s1 = s[:, 0], s[:, 1], s[:, 2]
    kind = np.full(n, BLOB, dtype=np.int8)
    enough = cnt >= int(g["min_neighbors"])
    lin = enough & (s2 <= g["linear_ratio"] * np.maximum(s1, 1e-12))
    pla = enough & ~lin & (s3 <= g["planar_ratio"] * np.maximum(s2, 1e-12))
    kind[pla] = PLANAR
    kind[lin] = LINEAR
    rep = {"faces": n, "L": round(ll, 4), "radius": round(radius, 4), "share": {NAMES[i]: round(float((kind == i).mean()), 4) for i in (PLANAR, LINEAR, BLOB)},
           "few_neighbours_share": round(float((~enough).mean()), 4)}
    return kind, up, rep

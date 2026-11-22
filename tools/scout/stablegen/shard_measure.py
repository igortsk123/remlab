#!/usr/bin/env python3
"""Мерка осколков (T-20261121-175/3д): сколько граней результата смотрят резко не туда, куда их соседи.

Гряда плоскости осколков не видит: шкаф с щепками по фасаду имел гряду 0,05 против 0,13 % у C0 (диагонали). Здесь — по граням, на самой форме, без эталона:
для каждой грани берётся нормаль «окружения» — сумма площадных нормалей граней, делящих с ней хотя бы одну вершину (сама грань вычтена); угол между нормалью грани и окружением.
«Резко» — больше 60°, «перевёрнута» — больше 90° (острая щепка, лежащая на плоскости, или грань, вывернутая наизнанку). Доли — от площади всех граней и числом граней.
Сравнение (читать): один товар, варианты рядом — доля у варианта МИНУС доля у C0; «хуже C0» = больше. Прямое сравнение граней с C0 по ближайшей точке не годится:
родная TRELLIS и после упрощения шумная, и сам C0 против C0 по ближайшей выборке показывал 8–40 % «отклонений» (проверено на комоде и шкафу).
Запуск: python3 shard_measure.py эталон-C0.glb вариант1.glb [вариант2.glb …]  (первый — C0 для дельты; нужны numpy, trimesh)."""
from __future__ import annotations

import json
import sys

import numpy as np


def local_shards(V, F, deg=(60.0, 90.0)) -> dict:
    """→ {faces, dev60_faces, dev60_area_pct, dev90_faces, dev90_area_pct}; грани без площади не считаются."""
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    key = np.round(V / (np.ptp(V, axis=0).max() * 1e-6)).astype(np.int64)   # glTF режет вершины по швам развёртки: соседство — по положению, не по номеру
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    V, F = V[first], inv.reshape(-1)[F]
    c = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])          # длина = 2·площадь: площадная нормаль
    area = np.linalg.norm(c, axis=1) / 2
    ok = area > 0
    n = c / np.maximum(2 * area, 1e-30)[:, None]
    vn = np.zeros((len(V), 3))
    for k in range(3):
        for d in range(3):
            vn[:, d] += np.bincount(F[:, k], weights=c[:, d], minlength=len(V))
    nb = vn[F[:, 0]] + vn[F[:, 1]] + vn[F[:, 2]] - 3 * c                       # соседи, без себя (сама грань входит в три вершины)
    nbl = np.linalg.norm(nb, axis=1)
    has = ok & (nbl > 1e-12)
    cos = np.ones(len(F))
    cos[has] = (n[has] * nb[has]).sum(axis=1) / nbl[has]
    ang = np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))
    tot = float(area[ok].sum()) or 1.0
    out = {"faces": int(ok.sum())}
    for t in deg:
        bad = has & (ang > t)
        out[f"dev{int(t)}_faces"] = int(bad.sum())
        out[f"dev{int(t)}_area_pct"] = round(100 * float(area[bad].sum()) / tot, 3)
    return out


def load_glb(path: str):
    import trimesh
    m = trimesh.load(path, force="mesh", process=False)
    return np.asarray(m.vertices, np.float64), np.asarray(m.faces, np.int64)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    base = None
    for p in sys.argv[1:]:
        m = local_shards(*load_glb(p))
        if base is None:
            base = m
        print(json.dumps({"file": p, **m, "d60_faces_vs_first": m["dev60_faces"] - base["dev60_faces"], "d90_faces_vs_first": m["dev90_faces"] - base["dev90_faces"]}, ensure_ascii=False))

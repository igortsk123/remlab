#!/usr/bin/env python3
"""Мерка «рельеф зада» (T-20261123-43/5; правило R-BACKPANEL-06) — по ГЕОМЕТРИИ меша, не по картинке.

ЗАЧЕМ. «Призрак» листьев на заду корпусной мебели — рельеф формы (TRELLIS дорисовал зад по лицу; разбор T-39/3 на глине: есть с этапа 01, не меняется до 07). Мерка `back_speckle` смотрит на лист (крапинки),
а сам рельеф числом не мерился. Здесь: у конца зада по оси глубины берутся грани, смотрящие от камеры (в конусе `cone_deg`), к ним по площади подгоняется плоскость; результат —
σ остатка (выбросы глубже `clip_frac` глубины обрезаны) в процентах глубины предмета и доля площади, где |остаток| больше `tol_frac` глубины. Сторож: после выравнивания σ и доля — не выше порогов; у ровного зада мерка почти ноль.

Все числа — rules/edge-sharpen.json (back_panel.relief, помечены «гипотеза»: берутся из замера комода 13224 — оригинал σ 1,7 % на 01/02 и 2,3 % на 06, лицо на 06 0,3 %); ID товаров в коде нет.

  python tools/scout/back_relief.py ФОРМА.glb [ФОРМА2.glb ...]  --az AZ --el EL  → строка JSON на форму; код возврата 1, если σ или доля выше порога (нужна камера: азимут/высота этапа 4)
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import edge_sharpen as ES  # noqa: E402


def back_relief(V, F, front_dir, rules: dict | None = None, ctx: dict | None = None) -> dict:
    """Рельеф зада формы (V, F) при камере `front_dir`. → {ok, reason, sigma_pct, share_pct, depth, faces, tilt_deg, passed}; ok=False — зад не найден (мерка не определена, passed=None).
    Ось глубины — `edge_sharpen._axis_frame` (лицо к камере); конец зада — крайние `end_frac` глубины со стороны от камеры; грани — нормаль в конусе `cone_deg` от «от камеры»; контур следа (скругление зад→бок, ножки) отступом `edge_cells` клеток не считается."""
    rules = rules or ES.load_rules()
    br = rules["back_panel"]
    rl = br["relief"]
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    ctx = ctx or ES.context(V, F, rules)
    fr = ES._axis_frame(V, ctx["vn"], ctx["va"], front_dir, br)
    if fr is None:
        return {"ok": False, "reason": "лицо к камере не найдено", "passed": None}
    a, u, v = fr
    P = V[F]
    n3 = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
    ar = np.linalg.norm(n3, axis=1) / 2
    nrm = n3 / np.maximum(2 * ar, 1e-12)[:, None]
    C = P.mean(1)
    t = C @ a
    depth = float(t.max() - t.min())
    if depth <= 0:
        return {"ok": False, "reason": "нулевая глубина", "passed": None}
    sel = (t < t.min() + rl["end_frac"] * depth) & ((nrm @ a) < -np.cos(np.radians(rl["cone_deg"]))) & (ar > 0)
    # внешняя кожа: двойная оболочка и внутренние стенки (нормаль тоже «от камеры», но глубже) зад не образуют — берём в клетке кадра только то, что не глубже самой внешней на skin_frac глубины
    Pf = np.stack([V @ u, V @ v], 1)
    lo, hi = Pf.min(0), Pf.max(0)
    G = int(br["grid"])
    cell = ES._cells(C, u, v, lo, hi, G)
    ext = np.full(G * G, np.inf)
    np.minimum.at(ext, cell[sel], t[sel])
    sel = sel & (t <= ext[cell] + rl["skin_frac"] * depth)
    # край следа (скругление зад→бок, ножки) рельефом зада не считается: берём только внутренность следа, отступив `edge_cells` клеток от внешнего контура (дырки следа — не контур)
    from scipy.ndimage import binary_closing, binary_erosion, binary_fill_holes
    fm = np.zeros(G * G, bool)
    fm[cell[sel]] = True
    fm = binary_fill_holes(binary_closing(fm.reshape(G, G), iterations=2))
    fm = binary_erosion(fm, iterations=int(rl["edge_cells"]), border_value=0).reshape(-1)
    sel = sel & fm[cell]
    if sel.sum() < int(rl["min_faces"]):
        return {"ok": False, "reason": "на конце зада мало граней (%d)" % int(sel.sum()), "passed": None}
    w = ar[sel]
    X = np.stack([C[sel] @ u, C[sel] @ v, np.ones(sel.sum())], 1)
    sw = np.sqrt(w)
    co, *_ = np.linalg.lstsq(X * sw[:, None], t[sel] * sw, rcond=None)
    res = t[sel] - X @ co
    res = np.clip(res, -rl["clip_frac"] * depth, rl["clip_frac"] * depth)                      # редкие выбросы (ножки, выступ) σ не раздувают: они не рельеф зада
    sigma = float(np.sqrt((w * res ** 2).sum() / w.sum()) / depth * 100)
    share = float(w[np.abs(res) > rl["tol_frac"] * depth].sum() / w.sum() * 100)
    npl = a - co[0] * u - co[1] * v                   # нормаль подогнанной плоскости (в сторону от камеры — минус)
    npl = npl / np.linalg.norm(npl)
    cosp = np.clip(-(nrm[sel] @ npl), -1.0, 1.0)
    steep = float(w[cosp < np.cos(np.radians(rl["steep_deg"]))].sum() / w.sum() * 100)           # МЕЛКИЙ масштаб: доля площади граней, наклонённых к плоскости круче steep_deg (σ мелкую рябь не видит); порог steep_share_max_pct (гипотеза: 0,5 % — между 10887/18370 «после» 0,3–0,45 и видимой рябью 13224/15195 1,9/0,57)
    return {"ok": True, "reason": "", "sigma_pct": round(sigma, 3), "share_pct": round(share, 2), "steep_pct": round(steep, 2), "depth": round(depth, 4), "faces": int(sel.sum()),
            "tilt_deg": round(float(np.degrees(np.arctan(np.hypot(co[0], co[1])))), 2),
            "passed": bool(sigma <= rl["sigma_max_pct"] and share <= rl["share_max_pct"] and steep <= rl["steep_share_max_pct"])}


def load_glb(path: str):
    """GLB → (V, F), все геометрии склеены (нужен trimesh)."""
    import trimesh
    ms = [g for g in trimesh.load(path, force="scene").dump() if len(g.faces)]
    off, Vs, Fs = 0, [], []
    for g in ms:
        Vs.append(np.asarray(g.vertices))
        Fs.append(np.asarray(g.faces) + off)
        off += len(g.vertices)
    return np.concatenate(Vs), np.concatenate(Fs)


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("glb", nargs="+")
    ap.add_argument("--az", type=float, required=True)
    ap.add_argument("--el", type=float, default=0.0)
    a = ap.parse_args(argv)
    bad = 0
    for p in a.glb:
        V, F = load_glb(p)
        r = back_relief(V, F, ES.camera_dir(a.az, a.el))
        print(json.dumps({"glb": p, **r}, ensure_ascii=False))
        bad += 0 if r.get("passed") else 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

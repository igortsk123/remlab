#!/usr/bin/env python3
"""Какая из двух противоположных больших граней корпусной формы — ФАСАД, по форме (T-20261125-80, п.5б; правило R-BACKPANEL-06). ОДИН источник истины.

ЗАЧЕМ. Азимут камеры этапа 4 определён по силуэту, а по силуэту перед и зад корпусной мебели не различить: у части шкафов/комодов камера смотрит на гладкую плиту, а настоящий фасад
(двери, ящики, листья) лежит на противоположной стороне (замер 25.11 на круге 29: на 5 из 11 корпусных; `edge_agree` это НЕ ловит — у ящиков 0,81 при перевёрнутой позе). Выравнивание «зада»
на такой форме стёрло бы настоящий фасад. Здесь — вердикт по форме: с какой стороны больше рельефа (доля круто наклонённых граней, `back_relief.steep_pct`), там и фасад.

Что делает: `front_by_relief(V, F, cam_dir)` меряет рельеф обеих больших граней (`back_relief` со стороны, противоположной камере, и со стороны камеры) и сравнивает.
 · `camera`   — фасад на стороне камеры: поза верна (зад — противоположная сторона);
 · `opposite` — фасад на стороне, противоположной камере: азимут камеры перевёрнут на 180° (этап 04 должен его перевернуть; выравнивать «зад» по такой камере нельзя);
 · `ambiguous` — разница не явная (отношение < ratio_min) или обе стороны гладкие (< steep_min_pct): воздерживаться, решает прежний гейт (согласие кромок).
Числа — rules/edge-sharpen.json (back_panel.front_by_relief, помечены «гипотеза»: подобраны на круге 29 по замеру T-80); ID товаров в коде нет. Нужны numpy, scipy (+ trimesh для CLI).

  python tools/scout/front_by_relief.py ФОРМА.glb [...] --az AZ --el EL   → строка JSON на форму
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import back_relief as BR  # noqa: E402
import edge_sharpen as ES  # noqa: E402


def front_by_relief(V, F, cam_dir, rules: dict | None = None, ctx: dict | None = None) -> dict:
    """Вердикт по форме. → {verdict: camera|opposite|ambiguous, reason, steep_camera_side, steep_opposite_side, ratio}.
    `cam_dir` — направление на камеру (от предмета к камере), как в `edge_sharpen.camera_dir`."""
    rules = rules or ES.load_rules()
    fb = rules["back_panel"]["front_by_relief"]
    V = np.asarray(V, np.float64)
    F = np.asarray(F, np.int64)
    ctx = ctx or ES.context(V, F, rules)
    cam = np.asarray(cam_dir, np.float64)
    cam = cam / max(float(np.linalg.norm(cam)), 1e-12)
    r_opp = BR.back_relief(V, F, cam, rules, ctx)          # грань «зад по камере» — противоположная камере
    r_cam = BR.back_relief(V, F, -cam, rules, ctx)         # грань со стороны камеры
    out = {"verdict": "ambiguous", "reason": "", "steep_camera_side": None, "steep_opposite_side": None, "ratio": None}
    if not (r_opp.get("ok") and r_cam.get("ok")):
        out["reason"] = "рельеф одной из сторон не измерен: %s" % (r_opp.get("reason") or r_cam.get("reason"))
        return out
    sc, so = float(r_cam["steep_pct"]), float(r_opp["steep_pct"])
    hi, lo = max(sc, so), min(sc, so)
    ratio = hi / max(lo, float(fb["floor_pct"]))
    out.update(steep_camera_side=sc, steep_opposite_side=so, ratio=round(ratio, 2))
    if hi < float(fb["steep_min_pct"]):
        out["reason"] = "обе стороны гладкие (круто наклонённых граней %.2f %% и %.2f %% < %s %%)" % (sc, so, fb["steep_min_pct"])
    elif ratio < float(fb["ratio_min"]):
        out["reason"] = "разница не явная: %.2f %% со стороны камеры и %.2f %% с противоположной (отношение %.1f < %s)" % (sc, so, ratio, fb["ratio_min"])
    elif sc > so:
        out.update(verdict="camera", reason="фасад на стороне камеры (%.2f %% против %.2f %%): поза верна" % (sc, so))
    else:
        out.update(verdict="opposite", reason="фасад на стороне, противоположной камере (%.2f %% против %.2f %% со стороны камеры): азимут камеры перевёрнут на 180°" % (so, sc))
    return out


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("glb", nargs="+")
    ap.add_argument("--az", type=float, required=True)
    ap.add_argument("--el", type=float, default=0.0)
    a = ap.parse_args(argv)
    for p in a.glb:
        V, F = BR.load_glb(p)
        print(json.dumps({"glb": p, **front_by_relief(V, F, ES.camera_dir(a.az, a.el))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

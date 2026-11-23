"""Ворота кадра страницы для шага 08 (T-20261123-14, директор 23.11): «с материалом» не должен уходить от «как сейчас» по среднему цвету предмета.
Вход — два кадра просмотрщика страницы (RGB, одинаковый размер, один свет, белый фон) и маска предмета (bool, из силуэта на прозрачном фоне);
число — ΔE76 между средними Lab и разница хромы C* (08 − «как сейчас»). Пороги — `frame_gate` в `data/flat3d/material-recipes.json` (в коде чисел нет).
→ {dE, dC, dL, ok, why}; страница с `ok False` не публикуется. Кадры снимает `frame_gate_cli` вызывающей стороны (Playwright, model-viewer 3.5.0, neutral, exposure 1)."""
from __future__ import annotations

import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import material_stage as ms  # noqa: E402


def mean_lab(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    return ms.rgb_to_lab(np.asarray(rgb)[..., :3][mask].astype(np.float64)).mean(axis=0)


def gate(now_rgb: np.ndarray, mat_rgb: np.ndarray, mask: np.ndarray, rules: dict | None = None) -> dict:
    """Сравнить средний цвет предмета «как сейчас» и «с материалом» по маске; пороги — `rules` (по умолчанию `frame_gate` из рецептов)."""
    fg = rules if rules is not None else ms.load_recipes()["frame_gate"]
    if int(np.count_nonzero(mask)) < 50:
        return {"ok": False, "why": "в маске меньше 50 пикселей — сравнивать нечего", "dE": None, "dC": None, "dL": None}
    a, b = mean_lab(now_rgb, mask), mean_lab(mat_rgb, mask)
    dE = float(np.linalg.norm(b - a))
    dC = float(np.hypot(b[1], b[2]) - np.hypot(a[1], a[2]))
    why = []
    if dE > fg["dE_max"]:
        why.append(f"ΔE {dE:.1f} > {fg['dE_max']}")
    if dC < fg["dC_min"]:
        why.append(f"ΔC {dC:.1f} < {fg['dC_min']}")
    return {"ok": not why, "why": "; ".join(why), "dE": round(dE, 2), "dC": round(dC, 2), "dL": round(float(b[0] - a[0]), 2)}


def main(argv: list[str]) -> int:
    """frame_gate.py <now.png> <mat.png> <mask.png (alpha предмета)> — печатает JSON, код возврата 1, если не прошло."""
    from PIL import Image
    now = np.asarray(Image.open(argv[0]).convert("RGB"))
    mat = np.asarray(Image.open(argv[1]).convert("RGB"))
    mask = np.asarray(Image.open(argv[2]).convert("RGBA"))[..., 3] >= 230
    r = gate(now, mat, mask)
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

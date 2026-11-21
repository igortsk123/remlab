"""Цвет частей меша по текстуре входа (paint-photo-fill-01, этап 3, T-20261120-169): медиана Lab, насыщенность и разброс по граням каждой части.

ЗАЧЕМ. Этап 3 делит меш на части, но не знает, дерево это или ткань (имя/класс — отдельный шаг Qwen3-VL с потолком). Заливка невидимого (этап 7) берёт цвет части; если дерево
(стойки подлокотников, царга, ножки) попало в часть обивки — зад станет розовым (находка директора по креслу с цветочной обивкой). Числа цвета части — бесплатная сверка:
в одной части не должно быть двух разных цветов (разброс L*, a*, b*), а соседние части с разным цветом — не одна. Чистая математика на numpy (без torch), без Blender.

Выход `part_colours(...)`: на часть — {lab_median, chroma_median, hue_deg, spread (p90 расстояния ΔE76 до медианы), faces_sampled}; `mixed_parts(...)` — части, где разброс выше порога правил.
"""
from __future__ import annotations

import numpy as np


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0..255 (N×3) → CIE Lab (D65)."""
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[:, 1] - 16, 500 * (f[:, 0] - f[:, 1]), 200 * (f[:, 1] - f[:, 2])], axis=1)


def face_rgb(uv: np.ndarray, faces: np.ndarray, tex: np.ndarray) -> np.ndarray:
    """Цвет текстуры в центре каждой грани (UV центра, ближайший тексель; V вверх, как в glTF после trimesh)."""
    h, w = tex.shape[:2]
    c = uv[faces].mean(axis=1)
    x = np.clip((c[:, 0] * (w - 1)).round().astype(int), 0, w - 1)
    y = np.clip(((1 - c[:, 1]) * (h - 1)).round().astype(int), 0, h - 1)
    return tex[y, x, :3]


def part_colours(part: np.ndarray, rgb: np.ndarray, min_faces: int = 30) -> dict[int, dict]:
    """Цвет каждой части: медиана Lab, хрома, тон, разброс (p90 ΔE76 до медианы)."""
    lab = rgb_to_lab(rgb)
    out = {}
    for p in np.unique(part[part >= 0]):
        sel = part == p
        if sel.sum() < min_faces:
            continue
        L = lab[sel]
        med = np.median(L, axis=0)
        de = np.linalg.norm(L - med, axis=1)
        out[int(p)] = {
            "lab_median": [round(float(v), 1) for v in med],
            "chroma_median": round(float(np.hypot(med[1], med[2])), 1),
            "hue_deg": round(float(np.degrees(np.arctan2(med[2], med[1])) % 360), 0),
            "spread_p90": round(float(np.percentile(de, 90)), 1),
            "faces_sampled": int(sel.sum()),
        }
    return out


def mixed_parts(colours: dict[int, dict], rules: dict) -> list[int]:
    """Части, внутри которых цвета слишком разные (p90 ΔE до медианы выше порога `check.part_spread_max`) — кандидат на «две части слиты»."""
    thr = rules["check"]["part_spread_max"]
    return sorted(p for p, c in colours.items() if c["spread_p90"] > thr)

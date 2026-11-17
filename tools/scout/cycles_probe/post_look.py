#!/usr/bin/env python3
"""Лёгкая «камерная» обработка готового кадра Cycles (Codex 17.11): свечение ярких мест (окно, лампы), виньетка, зерно.

    post_look.py <вход.png> <выход.png> [--glow 0.25] [--vig 0.15] [--grain 0.005]

--glow  — доля свечения яркого (порог 0.85 по яркости, радиус ≈1.2 % ширины); 0 — нет.
--vig   — затемнение углов в EV (≤0.15 по совету Codex); 0 — нет.
--grain — размах зерна (стандартное отклонение, доля 0..1; ≈0.005 = 0.5 %); 0 — нет. Зерно фиксировано (seed), кадр воспроизводим.
Хроматическую аберрацию не делаем: совет Codex — она на «чистом» кадре делает его менее убедительным.
"""
import argparse

import numpy as np
from PIL import Image, ImageFilter

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("dst")
ap.add_argument("--glow", type=float, default=0.0)
ap.add_argument("--vig", type=float, default=0.0)
ap.add_argument("--grain", type=float, default=0.0)
a = ap.parse_args()

im = Image.open(a.src).convert("RGB")
x = np.asarray(im, np.float32) / 255.0
h, w, _ = x.shape
if a.glow > 0:
    lum = x @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    bright = np.clip((lum - 0.85) / 0.15, 0, 1)[..., None] * x
    b = Image.fromarray((np.clip(bright, 0, 1) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(radius=max(2.0, w * 0.012)))
    x = 1.0 - (1.0 - x) * (1.0 - a.glow * np.asarray(b, np.float32) / 255.0)       # экранное сложение: не пересвечивает выше 1
if a.vig > 0:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
    x = x * (2.0 ** (-a.vig * r2 / 2.0))[..., None]
if a.grain > 0:
    rng = np.random.default_rng(7)
    n = rng.normal(0.0, a.grain, (h, w, 1)).astype(np.float32)
    x = x + n * (0.5 + 0.5 * (1.0 - np.abs(x - 0.5) * 2))      # зерно заметнее в полутонах, чем в чёрном и белом
Image.fromarray((np.clip(x, 0, 1) * 255 + 0.5).astype(np.uint8)).save(a.dst)
print("post", a.dst)

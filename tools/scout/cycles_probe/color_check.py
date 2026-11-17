#!/usr/bin/env python3
"""Цвет товара на рендере против фото магазина (T-20261117-06/1, критерий директора): средний цвет ткани в sRGB 0–255.

    color_check.py <cutout.png фото товара> <текстура меша.png> <кадр.png:x0,y0,x1,y1> ...

Фото — среднее по непрозрачным пикселям вырезки; текстура меша — среднее по её кадру (то, что кладётся на меш до освещения); кадр — среднее в
прямоугольнике на ткани (кадр уже освещён и пропущен через тонмап: разница с текстурой = влияние света/баланса белого/тонмапа).
Среднее считается в линейном свете и переводится обратно в sRGB (так складывается свет); в скобках — тон: R/G и B/G.
"""
import sys

import numpy as np
from PIL import Image


def lin(a):
    a = a / 255.0
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def srgb(a):
    a = np.clip(a, 0, 1)
    return 255.0 * np.where(a <= 0.0031308, a * 12.92, 1.055 * a ** (1 / 2.4) - 0.055)


def mean_rgb(px):
    m = srgb(lin(px.reshape(-1, 3).astype(float)).mean(axis=0))
    return m


def show(name, m):
    print(f"{name:34s} RGB {m[0]:5.0f} {m[1]:5.0f} {m[2]:5.0f}   (R/G {m[0] / m[1]:.2f}, B/G {m[2] / m[1]:.2f})  #{int(round(m[0])):02x}{int(round(m[1])):02x}{int(round(m[2])):02x}")


im = Image.open(sys.argv[1]).convert("RGBA")
a = np.asarray(im)
mask = a[..., 3] > 200
show("фото магазина (вырезка)", mean_rgb(a[..., :3][mask]))
t = np.asarray(Image.open(sys.argv[2]).convert("RGBA"))
tm = t[..., 3] > 200
show("текстура меша (до света)", mean_rgb(t[..., :3][tm]))
for arg in sys.argv[3:]:
    f, box = arg.rsplit(":", 1)
    x0, y0, x1, y1 = [int(v) for v in box.split(",")]
    r = np.asarray(Image.open(f).convert("RGB"))[y0:y1, x0:x1]
    show("кадр " + f.rsplit("/", 1)[-1].replace("living-scandi-C1-", "").replace(".png", ""), mean_rgb(r))

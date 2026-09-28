#!/usr/bin/env python3
"""Материалы покрытий для 3D-конфигуратора: фото образца → бесшовная runtime-текстура.

ЗАЧЕМ. Застройщик даёт фото образца (ковролин, LVT, плитка, столешница). В сцене нужен
БЕСШОВНЫЙ материал с честным физическим размером (сколько сантиметров в одном повторе),
иначе доска пола будет шириной с диван. Инструмент делает это полуавтоматически:

    photo   фото → выравнивание перспективы (4 точки) → вырезка → бесшовность →
            нормализация цвета → карты (normal/roughness/AO) → WebP + preview + material.json
    make    процедурный образец того же формата (когда фото ещё нет) — тот же выход,
            тот же манифест, чтобы сцена не знала разницы и конвейер был один

Запуск (venv проекта):
    ~/venvs/scout/bin/python tools/assets/material_pipeline.py make --preset oak-light --out public/flat3d/materials
    ~/venvs/scout/bin/python tools/assets/material_pipeline.py photo --src sample.jpg \
        --corners 120,80 980,60 1010,760 90,790 --real-cm 60x60 --id lvt-grey --out public/flat3d/materials

Решения (ADR-0213): выход — WebP (нет toktx/basisu на машине; KTX2 включается флагом --ktx2,
когда бинарь появится), размер тайла 1024², превью 256². Физический размер обязателен.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

TILE = 1024
PREVIEW = 256


# ─────────────────────────────── общие операции ───────────────────────────────


def _rng(seed: int) -> np.random.Generator:
    return np.random.default_rng(seed)


def _fbm(shape: tuple[int, int], seed: int, octaves: int = 5, persistence: float = 0.5) -> np.ndarray:
    """Тайлящийся фрактальный шум: каждая октава — случайная сетка, растянутая с заворотом."""
    rng = _rng(seed)
    out = np.zeros(shape, np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        n = 2 ** (o + 2)
        grid = rng.random((n, n)).astype(np.float32)
        grid = np.vstack([grid, grid[:1]])
        grid = np.hstack([grid, grid[:, :1]])
        img = Image.fromarray((grid * 255).astype(np.uint8)).resize(
            (shape[1] + 1, shape[0] + 1), Image.BICUBIC
        )
        layer = np.asarray(img, np.float32)[: shape[0], : shape[1]] / 255.0
        out += layer * amp
        total += amp
        amp *= persistence
    return out / max(total, 1e-6)


def make_seamless(img: np.ndarray, blend: float = 0.15) -> np.ndarray:
    """Бесшовность сдвигом на половину и перекрёстным сведением швов (offset + blend).

    Классический приём: сдвигаем на пол-тайла — швы уезжают в середину — и заливаем их
    зеркальной копией с мягкой маской. Дешевле и предсказуемее, чем inpainting моделью.
    """
    h, w = img.shape[:2]
    rolled = np.roll(np.roll(img, h // 2, axis=0), w // 2, axis=1)
    bw = max(2, int(w * blend))
    bh = max(2, int(h * blend))
    ramp_x = np.linspace(0, 1, bw, dtype=np.float32)
    ramp_y = np.linspace(0, 1, bh, dtype=np.float32)

    out = rolled.astype(np.float32).copy()
    # вертикальный шов в центре
    cx = w // 2
    left = out[:, cx - bw : cx]
    right = np.flip(out[:, cx : cx + bw], axis=1)
    mix = left * (1 - ramp_x)[None, :, None] + right * ramp_x[None, :, None]
    out[:, cx - bw : cx] = mix
    # горизонтальный шов
    cy = h // 2
    top = out[cy - bh : cy, :]
    bottom = np.flip(out[cy : cy + bh, :], axis=0)
    mix2 = top * (1 - ramp_y)[:, None, None] + bottom * ramp_y[:, None, None]
    out[cy - bh : cy, :] = mix2
    return np.clip(out, 0, 255).astype(np.uint8)


def normalize_colour(img: np.ndarray, target_mean: float = 128.0, keep_hue: bool = True) -> np.ndarray:
    """Приводим яркость к общему уровню: образцы сняты при разном свете, иначе полы «разного цвета»."""
    f = img.astype(np.float32)
    lum = f @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    mean = float(lum.mean()) or 1.0
    scale = target_mean / mean
    scale = float(np.clip(scale, 0.6, 1.8))
    out = f * scale if keep_hue else np.clip(f * scale, 0, 255)
    return np.clip(out, 0, 255).astype(np.uint8)


def normal_from_height(height: np.ndarray, strength: float = 2.0) -> np.ndarray:
    """Карта нормалей из яркости: свету нужен рельеф, а фотография его не несёт."""
    h = height.astype(np.float32) / 255.0
    dx = np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)
    dy = np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)
    nx = -dx * strength
    ny = -dy * strength
    nz = np.ones_like(h)
    norm = np.sqrt(nx**2 + ny**2 + nz**2)
    rgb = np.stack([(nx / norm + 1) / 2, (ny / norm + 1) / 2, (nz / norm + 1) / 2], -1)
    return (rgb * 255).astype(np.uint8)


def roughness_from_height(height: np.ndarray, base: float, spread: float) -> np.ndarray:
    h = height.astype(np.float32) / 255.0
    r = np.clip(base + (h - 0.5) * spread, 0.02, 1.0)
    return (r * 255).astype(np.uint8)


def ao_from_height(height: np.ndarray, radius: int = 12) -> np.ndarray:
    """Грубый AO: где яркость ниже локального среднего — там впадина, там темнее."""
    img = Image.fromarray(height)
    blur = np.asarray(img.filter(ImageFilter.GaussianBlur(radius)), np.float32)
    diff = height.astype(np.float32) - blur
    ao = np.clip(1.0 + diff / 255.0 * 1.6, 0.35, 1.0)
    return (ao * 255).astype(np.uint8)


def warp_perspective(img: np.ndarray, corners: list[tuple[float, float]], size: int = TILE) -> np.ndarray:
    """Выравнивание перспективы по четырём углам образца (ЛВ, ПВ, ПН, ЛН) без OpenCV."""
    src = np.array(corners, np.float32)
    dst = np.array([[0, 0], [size, 0], [size, size], [0, size]], np.float32)
    a = []
    b = []
    for (x, y), (u, v) in zip(dst, src):
        a.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        a.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    coeffs = np.linalg.solve(np.array(a, np.float64), np.array(b, np.float64))
    return np.asarray(
        Image.fromarray(img).transform((size, size), Image.PERSPECTIVE, tuple(coeffs), Image.BICUBIC)
    )


# ─────────────────────────── процедурные образцы ───────────────────────────


def _wood_grain(seed: int, stretch: int = 14) -> np.ndarray:
    """Древесное волокно: шум, вытянутый вдоль доски, плюс тонкие тёмные жилы."""
    base = _fbm((TILE, TILE), seed, octaves=6, persistence=0.55)
    stretched = np.asarray(
        Image.fromarray((base * 255).astype(np.uint8))
        .resize((TILE, max(8, TILE // stretch)), Image.BILINEAR)
        .resize((TILE, TILE), Image.BILINEAR),
        np.float32,
    ) / 255.0
    fine = _fbm((TILE, TILE), seed + 91, octaves=7, persistence=0.68)
    # жилы: узкие тёмные линии там, где растянутый шум проходит через уровни
    rings = np.abs(np.sin(stretched * math.pi * 9.0))
    veins = np.clip(1.0 - rings, 0, 1) ** 8
    return np.clip(stretched * 0.72 + fine * 0.28 - veins * 0.30, 0, 1)


def gen_planks(seed: int, base_rgb: tuple[int, int, int], plank_cm: float, tile_cm: float,
               contrast: float = 0.20, gap: float = 0.9) -> tuple[np.ndarray, np.ndarray]:
    """Доска (ламинат/паркет/LVT): ряды со смещением, продольное волокно, тёмный шов.

    Тайлится ПО ПОСТРОЕНИЮ: высота доски — делитель TILE, смещение рядов кратно ширине,
    шум `_fbm` сам по себе бесшовный. Поэтому `make_seamless` к процедурным образцам не
    применяется — он давал светлую полосу поперёк пола (замер 28.09).
    """
    px_per_cm = TILE / tile_cm
    pw = max(8, int(round(plank_cm * px_per_cm)))
    while TILE % pw:  # ряд обязан укладываться целое число раз, иначе шов внизу
        pw -= 1
    rng = _rng(seed)
    col = np.zeros((TILE, TILE, 3), np.float32)
    height = np.zeros((TILE, TILE), np.float32)
    grain = _wood_grain(seed + 7)
    g = max(1, int(round(gap * px_per_cm)))
    # ДЛИНА ДОСКИ = длина тайла (на замере 28.09 четыре торцевых шва на тайл давали «кирпичики»,
    # а не половую доску: при tile_cm=120 доска выходила 30 см). Один торцевой шов на ряд,
    # смещение по рядам — треть тайла, узор не повторяется построчно.
    step_x = TILE

    for row, y0 in enumerate(range(0, TILE, pw)):
        y1 = y0 + pw
        shift = (row * (TILE // 3)) % TILE
        band = np.roll(grain[y0:y1, :], shift, axis=1)
        tone = 1.0 + float(rng.normal(0, contrast * 0.30))
        v = np.clip(tone * (1.0 + (band - 0.5) * contrast), 0.6, 1.4)
        for c in range(3):
            col[y0:y1, :, c] = base_rgb[c] * v
        height[y0:y1, :] = np.clip(band, 0, 1) * 255
        if pw < TILE:  # цельная плита (столешница) швов не имеет
            col[y0 : y0 + g, :, :] *= 0.45          # продольный шов
            height[y0 : y0 + g, :] *= 0.3
            for x in range(shift % step_x, TILE, step_x):  # торцевые швы
                col[y0:y1, x : x + g, :] *= 0.5
                height[y0:y1, x : x + g] *= 0.35
    return np.clip(col, 0, 255).astype(np.uint8), height.astype(np.uint8)


def gen_herringbone(seed: int, base_rgb: tuple[int, int, int], plank_cm: float, tile_cm: float,
                    contrast: float = 0.22) -> tuple[np.ndarray, np.ndarray]:
    """Настоящая ёлочка: планки 1:4, попеременно ±45°, укладка блоками.

    Рисуем в координатах, повёрнутых на 45°: ёлочка — это шахматка из квадратных блоков,
    внутри которых полосы идут либо по X, либо по Y. Так узор честно замыкается по краям.
    """
    px_per_cm = TILE / tile_cm
    pw = max(6, int(round(plank_cm * px_per_cm)))
    block = pw * 4
    while TILE % block:
        pw -= 1
        block = pw * 4
        if pw < 4:
            pw, block = 4, 16
            break
    rng = _rng(seed)
    grain = _wood_grain(seed + 13)
    col = np.zeros((TILE, TILE, 3), np.float32)
    height = np.zeros((TILE, TILE), np.float32)
    g = max(1, int(round(0.35 * px_per_cm)))

    for by in range(0, TILE, block):
        for bx in range(0, TILE, block):
            horizontal = ((bx // block) + (by // block)) % 2 == 0
            tone = 1.0 + float(rng.normal(0, contrast * 0.35))
            sub = np.roll(grain[by : by + block, bx : bx + block], bx + by, axis=1)
            if not horizontal:
                sub = sub.T
            v = np.clip(tone * (1.0 + (sub - 0.5) * contrast), 0.6, 1.4)
            for c in range(3):
                col[by : by + block, bx : bx + block, c] = base_rgb[c] * v
            height[by : by + block, bx : bx + block] = np.clip(sub, 0, 1) * 255
            for k in range(0, block, pw):  # швы между планками внутри блока
                if horizontal:
                    col[by + k : by + k + g, bx : bx + block, :] *= 0.45
                    height[by + k : by + k + g, bx : bx + block] *= 0.3
                else:
                    col[by : by + block, bx + k : bx + k + g, :] *= 0.45
                    height[by : by + block, bx + k : bx + k + g] *= 0.3
            col[by : by + block, bx : bx + g, :] *= 0.5   # граница блока
            col[by : by + g, bx : bx + block, :] *= 0.5
    return np.clip(col, 0, 255).astype(np.uint8), height.astype(np.uint8)


def gen_tiles(seed: int, base_rgb: tuple[int, int, int], tile_size_cm: float, tile_cm: float,
              grout_cm: float = 0.4, grout_rgb: tuple[int, int, int] = (198, 194, 188),
              veining: float = 0.0, bond: str = "grid", aspect: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Плитка: сетка или перевязка «кабанчиком», шов, разнотонность, прожилки мрамора.

    Шов рисуем ЗАМЕТНЫМ (темнее плитки на ~20 %) — на замере 28.09 светлый шов в 3 пикселя
    просто исчезал, и пол выглядел сплошной заливкой.
    """
    px_per_cm = TILE / tile_cm
    stepx = max(16, int(round(tile_size_cm * px_per_cm)))
    while TILE % stepx:
        stepx -= 1
    stepy = max(8, int(round(stepx * aspect)))
    while TILE % stepy:
        stepy -= 1
    grout = max(2, int(round(grout_cm * px_per_cm)))
    rng = _rng(seed)
    noise = _fbm((TILE, TILE), seed + 3, octaves=6, persistence=0.55)
    col = np.array(base_rgb, np.float32) * (0.97 + noise[..., None] * 0.06)

    if veining > 0:
        warp = _fbm((TILE, TILE), seed + 31, octaves=3, persistence=0.6)
        yy = np.linspace(0, 1, TILE, dtype=np.float32)[:, None]
        xx = np.linspace(0, 1, TILE, dtype=np.float32)[None, :]
        field = np.sin((xx * 2.0 + yy * 1.0 + warp * 1.8) * math.pi * 2)
        mask = np.clip(1.0 - np.abs(field), 0, 1) ** 12 * veining
        light = np.array([252, 250, 246], np.float32)
        dark = np.array([176, 172, 166], np.float32)
        col = col * (1 - mask[..., None]) + (light * 0.6 + dark * 0.4) * mask[..., None]

    height = np.full((TILE, TILE), 210, np.float32)
    for y in range(0, TILE, stepy):
        row = y // stepy
        offset = (stepx // 2) * (row % 2) if bond == "brick" else 0
        tone = 1.0 + float(rng.normal(0, 0.015))
        col[y : y + stepy, :, :] *= tone
        for x in range(0, TILE + stepx, stepx):
            xx0 = (x + offset) % TILE
            col[y : y + stepy, xx0 : xx0 + grout, :] = np.array(grout_rgb, np.float32)
            height[y : y + stepy, xx0 : xx0 + grout] = 60
        col[y : y + grout, :, :] = np.array(grout_rgb, np.float32)
        height[y : y + grout, :] = 60
    return np.clip(col, 0, 255).astype(np.uint8), height.astype(np.uint8)


def gen_carpet(seed: int, base_rgb: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """Ковролин: ворс — это ВЫСОКОЧАСТОТНОЕ зерно, а не облака.

    Первая версия брала только `_fbm` — получались дымные пятна. Теперь основа — попиксельный
    шум с лёгким вертикальным «причёсыванием» (петля ворса) и слабой крупной неравномерностью.
    """
    rng = _rng(seed)
    grain = rng.random((TILE, TILE)).astype(np.float32)
    combed = np.asarray(
        Image.fromarray((grain * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6)), np.float32
    ) / 255.0
    streak = np.asarray(
        Image.fromarray((rng.random((TILE, TILE)) * 255).astype(np.uint8))
        .resize((TILE, TILE // 3), Image.BILINEAR)
        .resize((TILE, TILE), Image.BILINEAR),
        np.float32,
    ) / 255.0
    broad = _fbm((TILE, TILE), seed + 5, octaves=3, persistence=0.45)
    # амплитуда зерна: на замере 28.09 ковролин читался плоским фетром — подняли вклад ворса
    v = np.clip(0.80 + (combed - 0.5) * 0.62 + (streak - 0.5) * 0.16 + (broad - 0.5) * 0.08, 0.5, 1.4)
    col = np.stack([np.array(base_rgb, np.float32)[c] * v for c in range(3)], -1)
    height = (np.clip(combed * 0.8 + streak * 0.2, 0, 1) * 255).astype(np.uint8)
    return np.clip(col, 0, 255).astype(np.uint8), height


def gen_stone(seed: int, base_rgb: tuple[int, int, int], veining: float = 0.5) -> tuple[np.ndarray, np.ndarray]:
    """Камень/кварц: мелкая крапинка + прожилки по искажённому полю.

    Прежняя версия брала `sin(fbm)` напрямую и давала муар «горизонталями» (видно на замере
    28.09). Теперь поле деформируем вторым шумом — линии идут неровно, как в камне.
    """
    rng = _rng(seed)
    speck = rng.random((TILE, TILE)).astype(np.float32)
    speck = np.asarray(
        Image.fromarray((speck * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8)), np.float32
    ) / 255.0
    v = np.clip(0.95 + (speck - 0.5) * 0.14, 0.75, 1.2)
    col = np.stack([np.array(base_rgb, np.float32)[c] * v for c in range(3)], -1)
    if veining > 0:
        warp = _fbm((TILE, TILE), seed + 17, octaves=4, persistence=0.6)
        warp2 = _fbm((TILE, TILE), seed + 29, octaves=2, persistence=0.5)
        yy = np.linspace(0, 1, TILE, dtype=np.float32)[:, None]
        xx = np.linspace(0, 1, TILE, dtype=np.float32)[None, :]
        field = np.sin((xx * 1.0 + yy * 2.0 + warp * 2.4 + warp2) * math.pi * 2)
        mask = np.clip(1.0 - np.abs(field), 0, 1) ** 10 * veining
        col = col * (1 - mask[..., None] * 0.5) + np.array([170, 168, 162], np.float32) * mask[..., None] * 0.5
    return np.clip(col, 0, 255).astype(np.uint8), (speck * 255).astype(np.uint8)


# ─────────────────────────────── запись ───────────────────────────────


def write_material(out_dir: str, mid: str, colour: np.ndarray, height: np.ndarray, *,
                   tile_cm: tuple[float, float], title_ru: str, title_en: str,
                   roughness_base: float, roughness_spread: float, metalness: float,
                   normal_strength: float, quality: int = 82, make_maps: bool = True,
                   seamless: bool = True) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    if seamless:
        # только для фото: процедурные образцы тайлятся по построению, а сшивка добавляла
        # им светлую полосу поперёк (замер 28.09)
        colour = make_seamless(colour)
        height = make_seamless(np.stack([height] * 3, -1))[..., 0]

    paths: dict[str, str] = {}
    Image.fromarray(colour).save(os.path.join(out_dir, f"{mid}.webp"), quality=quality, method=6)
    paths["baseColorUrl"] = f"{mid}.webp"

    if make_maps:
        nrm = normal_from_height(height, normal_strength)
        Image.fromarray(nrm).resize((512, 512), Image.LANCZOS).save(
            os.path.join(out_dir, f"{mid}-n.webp"), quality=78, method=6
        )
        paths["normalUrl"] = f"{mid}-n.webp"
        rgh = roughness_from_height(height, roughness_base, roughness_spread)
        Image.fromarray(rgh).resize((512, 512), Image.LANCZOS).save(
            os.path.join(out_dir, f"{mid}-r.webp"), quality=70, method=6
        )
        paths["roughnessUrl"] = f"{mid}-r.webp"
        ao = ao_from_height(height)
        Image.fromarray(ao).resize((512, 512), Image.LANCZOS).save(
            os.path.join(out_dir, f"{mid}-ao.webp"), quality=70, method=6
        )
        paths["aoUrl"] = f"{mid}-ao.webp"

    Image.fromarray(colour).resize((PREVIEW, PREVIEW), Image.LANCZOS).save(
        os.path.join(out_dir, f"{mid}-preview.webp"), quality=80, method=6
    )
    paths["previewUrl"] = f"{mid}-preview.webp"

    mean = colour.reshape(-1, 3).mean(0).astype(int)
    return {
        "id": mid,
        "titleRu": title_ru,
        "titleEn": title_en,
        "colorHex": "#%02x%02x%02x" % tuple(int(v) for v in mean),
        "roughness": roughness_base,
        "metalness": metalness,
        "tileCm": [tile_cm[0], tile_cm[1]],
        **paths,
    }


# ─────────────────────────────── пресеты ───────────────────────────────

PRESETS: dict[str, dict] = {
    # полы
    "oak-light": dict(gen="planks", rgb=(196, 166, 129), plank=19, tile=120, contrast=0.22,
                      ru="Дуб светлый (LVT)", en="Light oak LVT", rough=0.58, spread=0.18, nrm=2.2),
    "oak-natural": dict(gen="planks", rgb=(170, 132, 92), plank=19, tile=120, contrast=0.26,
                        ru="Дуб натуральный", en="Natural oak", rough=0.52, spread=0.20, nrm=2.4),
    "walnut-dark": dict(gen="planks", rgb=(108, 76, 54), plank=17, tile=110, contrast=0.30,
                        ru="Орех тёмный", en="Dark walnut", rough=0.45, spread=0.22, nrm=2.6),
    "parquet-blocks": dict(gen="herringbone", rgb=(182, 148, 110), plank=12, tile=96, contrast=0.24,
                           ru="Паркет модульный", en="Parquet blocks", rough=0.50, spread=0.20, nrm=2.6),
    "carpet-grey": dict(gen="carpet", rgb=(136, 134, 130), ru="Ковролин серый", en="Grey carpet",
                        rough=0.95, spread=0.08, nrm=1.4, tile=60),
    "carpet-beige": dict(gen="carpet", rgb=(186, 172, 150), ru="Ковролин бежевый", en="Beige carpet",
                         rough=0.95, spread=0.08, nrm=1.4, tile=60),
    # плитка
    "tile-stone-grey": dict(gen="tiles", rgb=(178, 176, 172), size=60, tile=120, grout=0.4,
                            ru="Керамогранит серый 60×60", en="Grey porcelain 60×60",
                            rough=0.35, spread=0.14, nrm=1.6),
    "tile-marble": dict(gen="tiles", rgb=(236, 233, 227), size=60, tile=120, grout=0.3, vein=0.8,
                        ru="Мрамор светлый", en="Light marble", rough=0.22, spread=0.10, nrm=1.4),
    "tile-metro": dict(gen="tiles", rgb=(242, 240, 236), size=20, tile=60, grout=0.5, bond="brick",
                       aspect=0.5, grout_rgb=(188, 184, 178),
                       ru="Кабанчик белый", en="White metro tile", rough=0.18, spread=0.10, nrm=1.8),
    "tile-sand": dict(gen="tiles", rgb=(206, 192, 172), size=30, tile=90, grout=0.4,
                      ru="Керамика песочная 30×30", en="Sand ceramic 30×30", rough=0.40, spread=0.14, nrm=1.7),
    "tile-graphite": dict(gen="tiles", rgb=(88, 90, 94), size=60, tile=120, grout=0.4,
                          grout_rgb=(70, 72, 76), ru="Керамогранит графит 60×60",
                          en="Graphite porcelain 60×60", rough=0.32, spread=0.12, nrm=1.6),
    # столешницы и фартук
    "quartz-white": dict(gen="stone", rgb=(238, 236, 230), vein=0.55, tile=120,
                         ru="Кварц белый", en="White quartz", rough=0.20, spread=0.08, nrm=1.2),
    "stone-grey": dict(gen="stone", rgb=(150, 150, 152), vein=0.85, tile=120,
                       ru="Камень серый", en="Grey stone", rough=0.30, spread=0.10, nrm=1.3),
    # столешница — цельная плита: доска во всю длину тайла, видно только волокно
    "laminate-oak-top": dict(gen="planks", rgb=(186, 152, 112), plank=128, tile=128, contrast=0.14,
                             ru="Столешница дуб", en="Oak worktop", rough=0.38, spread=0.14, nrm=1.4),
    "splashback-glass": dict(gen="stone", rgb=(228, 232, 230), vein=0.0, tile=120,
                             ru="Стекло фартук", en="Glass splashback", rough=0.10, spread=0.05, nrm=0.6),
}


def build_preset(name: str, out_dir: str) -> dict:
    p = PRESETS[name]
    seed = abs(hash(name)) % 10_000
    tile_cm = float(p.get("tile", 120))
    if p["gen"] == "planks":
        colour, height = gen_planks(seed, p["rgb"], float(p["plank"]), tile_cm, float(p.get("contrast", 0.2)))
    elif p["gen"] == "herringbone":
        colour, height = gen_herringbone(seed, p["rgb"], float(p["plank"]), tile_cm, float(p.get("contrast", 0.22)))
    elif p["gen"] == "tiles":
        colour, height = gen_tiles(seed, p["rgb"], float(p["size"]), tile_cm, float(p.get("grout", 0.4)),
                                   grout_rgb=tuple(p.get("grout_rgb", (198, 194, 188))),
                                   veining=float(p.get("vein", 0.0)), bond=str(p.get("bond", "grid")),
                                   aspect=float(p.get("aspect", 1.0)))
    elif p["gen"] == "carpet":
        colour, height = gen_carpet(seed, p["rgb"])
    else:
        colour, height = gen_stone(seed, p["rgb"], float(p.get("vein", 0.4)))
    return write_material(
        out_dir, name, colour, height,
        tile_cm=(tile_cm, tile_cm), title_ru=p["ru"], title_en=p["en"],
        roughness_base=float(p["rough"]), roughness_spread=float(p["spread"]),
        metalness=0.0, normal_strength=float(p["nrm"]), seamless=False,
    )


def from_photo(src: str, corners: list[tuple[float, float]] | None, real_cm: tuple[float, float],
               mid: str, out_dir: str, title_ru: str, title_en: str,
               rough: float, spread: float, nrm: float) -> dict:
    img = np.asarray(Image.open(src).convert("RGB"))
    if corners:
        img = warp_perspective(img, corners, TILE)
    else:
        side = min(img.shape[:2])
        y0 = (img.shape[0] - side) // 2
        x0 = (img.shape[1] - side) // 2
        img = np.asarray(Image.fromarray(img[y0 : y0 + side, x0 : x0 + side]).resize((TILE, TILE), Image.LANCZOS))
    img = normalize_colour(img)
    height = np.asarray(Image.fromarray(img).convert("L").filter(ImageFilter.GaussianBlur(1.0)))
    return write_material(
        out_dir, mid, img, height, tile_cm=real_cm, title_ru=title_ru, title_en=title_en,
        roughness_base=rough, roughness_spread=spread, metalness=0.0, normal_strength=nrm,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="материалы покрытий для конфигуратора")
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("make", help="процедурный образец по пресету")
    m.add_argument("--preset", required=True, choices=sorted(PRESETS) + ["all"])
    m.add_argument("--out", default="public/flat3d/materials")
    m.add_argument("--manifest", default="data/flat3d/materials.json")

    p = sub.add_parser("photo", help="материал из фото образца")
    p.add_argument("--src", required=True)
    p.add_argument("--id", required=True)
    p.add_argument("--corners", nargs=4, help="x,y четырёх углов: ЛВ ПВ ПН ЛН")
    p.add_argument("--real-cm", required=True, help="физический размер образца, напр. 60x60")
    p.add_argument("--title-ru", default="")
    p.add_argument("--title-en", default="")
    p.add_argument("--roughness", type=float, default=0.55)
    p.add_argument("--spread", type=float, default=0.15)
    p.add_argument("--normal", type=float, default=2.0)
    p.add_argument("--out", default="public/flat3d/materials")
    p.add_argument("--manifest", default="data/flat3d/materials.json")

    a = ap.parse_args()
    out_dir = os.path.abspath(a.out)
    entries: list[dict] = []

    if a.cmd == "make":
        names = sorted(PRESETS) if a.preset == "all" else [a.preset]
        for n in names:
            entries.append(build_preset(n, out_dir))
            print(f"материал готов: {n}")
    else:
        corners = None
        if a.corners:
            corners = [tuple(float(v) for v in c.split(",")) for c in a.corners]  # type: ignore[misc]
        w_cm, h_cm = (float(v) for v in a.real_cm.lower().split("x"))
        entries.append(
            from_photo(a.src, corners, (w_cm, h_cm), a.id, out_dir,
                       a.title_ru or a.id, a.title_en or a.id, a.roughness, a.spread, a.normal)
        )
        print(f"материал из фото готов: {a.id}")

    # манифест обновляем слиянием: материалы добавляются по одному, старые не теряются
    man_path = os.path.abspath(a.manifest)
    os.makedirs(os.path.dirname(man_path), exist_ok=True)
    existing: dict[str, dict] = {}
    if os.path.exists(man_path):
        try:
            for e in json.load(open(man_path, encoding="utf-8")).get("materials", []):
                existing[e["id"]] = e
        except Exception as exc:  # noqa: BLE001 — битый манифест не должен терять новую работу
            print(f"внимание: манифест не прочитан ({exc}), пересобираю", file=sys.stderr)
    for e in entries:
        existing[e["id"]] = e
    payload = {
        "_about": "Материалы покрытий. Собрано tools/assets/material_pipeline.py — руками не править.",
        "baseUrl": "/flat3d/materials/",
        "materials": [existing[k] for k in sorted(existing)],
    }
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"манифест: {man_path} ({len(existing)} материалов)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

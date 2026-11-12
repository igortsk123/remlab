#!/usr/bin/env python3
"""Превью загруженного чертежа для вкладки «План квартиры» тура (T-20261112-52, владелец TG 855/1000/1002): агент видит свой чертёж
рядом с нашей планировкой и сравнивает их один в один.

Вход — лист разбора `sheet.png` (`pipeline.prepare`: PDF — первые листы рядом, картинка — как есть, длинная сторона ≤ MAX_SIDE) и
результат с рамкой каждой панели в пикселях листа (`panels[].sheet` = {x0, y0, pxPerCm}: точка листа = (x0, y0) + см × pxPerCm,
`pipeline.to_result`). По каждой панели (этажу) — вырез по контурам её комнат с отступом PAD_CM; вырезы — в одну картинку WEBP
(≤ MAX_SIDE_PX по длинной стороне, без EXIF). Страница кладёт вырез панели в ту же раскладку, что наш план (см панели → метры
схемы), поэтому масштаб у колонок одинаковый и комнаты совпадают.

Выпрямления наклона/перспективы здесь нет: в разборе его нет (лист идёт в стенд как есть, `pipeline.prepare`), а контуры наших
комнат лежат в тех же пикселях листа — наклон чертежа повторяет и наша схема, поэтому вырез + масштаб совмещают их точно.

→ meta {'w', 'h', 'crops': [{'panel', 'sheet': [X, Y, W, H] пиксели листа, 'at': [x, y, w, h] пиксели картинки]}} или None.
"""
from __future__ import annotations

import math
from pathlib import Path

PAD_CM = 40          # отступ выреза вокруг контуров комнат: наружные стены (10–40 см) видны, соседняя панель — нет
GAP_PX = 6           # между вырезами в картинке
MAX_SIDE_PX = 1600   # длинная сторона картинки
QUALITY = 82


def _crop(panel: dict, W: int, H: int) -> list[int] | None:
    """Рамка панели в пикселях листа: охват контуров её комнат + PAD_CM, в пределах листа. Нет рамки/комнат — None."""
    f = panel.get('sheet') or {}
    try:
        x0, y0, k = float(f['x0']), float(f['y0']), float(f['pxPerCm'])
    except (KeyError, TypeError, ValueError):
        return None
    pts = [p for r in panel.get('rooms') or [] for p in r.get('contour') or []]
    if not pts or not (k > 0) or not all(math.isfinite(v) for v in (x0, y0, k)):
        return None
    xs, ys = [x0 + p[0] * k for p in pts], [y0 + p[1] * k for p in pts]
    pad = PAD_CM * k
    a, b = max(0, math.floor(min(xs) - pad)), max(0, math.floor(min(ys) - pad))
    c, d = min(W, math.ceil(max(xs) + pad)), min(H, math.ceil(max(ys) + pad))
    return [a, b, c - a, d - b] if c - a >= 8 and d - b >= 8 else None


def _layout(sizes: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], int, int]:
    """Вырезы рядом (в строку) или стопкой — где длинная сторона картинки меньше. → (точки вырезов, ширина, высота)."""
    row_w, row_h = sum(w for w, _ in sizes) + GAP_PX * (len(sizes) - 1), max(h for _, h in sizes)
    col_w, col_h = max(w for w, _ in sizes), sum(h for _, h in sizes) + GAP_PX * (len(sizes) - 1)
    out, x, y = [], 0, 0
    if max(row_w, row_h) <= max(col_w, col_h):
        for w, _ in sizes:
            out.append((x, 0))
            x += w + GAP_PX
        return out, row_w, row_h
    for _, h in sizes:
        out.append((0, y))
        y += h + GAP_PX
    return out, col_w, col_h


def make(sheet: Path, result: dict, out: Path) -> dict | None:
    """Лист + результат → `out` (WEBP) и meta (см. модуль). Ни у одной панели нет рамки — None, файл не пишется."""
    from PIL import Image
    with Image.open(sheet) as im0:
        im = im0.convert('RGB')
    W, H = im.size
    crops = [(p['id'], c) for p in result.get('panels') or [] if (c := _crop(p, W, H))]
    if not crops:
        return None
    s = 1.0
    pos, cw, ch = _layout([(c[2], c[3]) for _, c in crops])
    if max(cw, ch) > MAX_SIDE_PX:                       # уменьшаем вырезы, не раскладку: зазор остаётся GAP_PX
        s = (MAX_SIDE_PX - GAP_PX * (len(crops) - 1)) / (max(cw, ch) - GAP_PX * (len(crops) - 1))
    sizes = [(max(1, math.floor(c[2] * s)), max(1, math.floor(c[3] * s))) for _, c in crops]
    pos, cw, ch = _layout(sizes)
    canvas = Image.new('RGB', (cw, ch), (255, 255, 255))
    meta = []
    for (pid, c), (px, py), (w, h) in zip(crops, pos, sizes):
        part = im.crop((c[0], c[1], c[0] + c[2], c[1] + c[3]))
        if (w, h) != part.size:
            part = part.resize((w, h), Image.LANCZOS)
        canvas.paste(part, (px, py))
        meta.append({'panel': str(pid), 'sheet': c, 'at': [px, py, w, h]})
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name('.' + out.name + '.tmp')
    canvas.save(tmp, 'WEBP', quality=QUALITY, method=4)   # без exif/icc: только пиксели
    tmp.replace(out)
    return {'w': cw, 'h': ch, 'crops': meta}

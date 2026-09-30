#!/usr/bin/env python3
"""Текстура из ФОТОГРАФИИ МАТЕРИАЛА (вопрос владельца 30.09: «застройщик даст фото ламината»).

ЗАЧЕМ. Застройщик присылает фото своего материала — ламината, плитки, обоев. Покупатель должен
увидеть на полу ИМЕННО ЭТОТ материал, а не похожий. `material_from_product.py` умеет брать фактуру
с карточки ТОВАРА (фасад шкафа на белом фоне); здесь вход другой — обычный снимок поверхности:
снят под углом, с бликом, виньеткой и размытием по краям.

ЧТО ДЕЛАЕМ (по шагам, каждый проверяемый):
1. Ищем на фото самый РЕЗКИЙ и ровно освещённый квадрат — у снимка пола дальний край размыт.
2. Определяем, куда идут доски (преобладающее направление длинных линий), и поворачиваем так,
   чтобы доски шли вертикально: иначе на полу они лягут поперёк комнаты.
3. Баланс белого по серому миру + выравнивание ЯРКОСТИ (не по каналам: иначе дерево сереет).
4. Делаем бесшовный тайл и меряем шов; считаем «инородные» пятна (ножка стула, провод, блик).
5. Масштаб: зная ширину доски в сантиметрах (из спецификации застройщика), переводим пиксели в
   сантиметры — без этого доска на полу растягивается на всю комнату.
6. Пишем карты (цвет, рельеф, шероховатость, затенение) и провенанс: откуда фото, какие оценки.

Запуск:
  ~/venvs/scout/bin/python tools/assets/material_from_photo.py \
      --src ~/photos/laminate.jpg --id floor-dev-oak --title "Ламинат «Дуб»" \
      --surfaces floor --plank-cm 19 --source-url https://... --licence CC0
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from material_from_product import (  # noqa: E402
    MAX_BLOB,
    MAX_QUAD,
    MAX_SEAM,
    blob_ratio,
    flatten_light,
    peak_dev,
    quadrant_spread,
    seam_error,
)
from material_pipeline import TILE, write_material  # noqa: E402

WORK = 1800  # рабочий размер длинной стороны: больше — дольше и без пользы


def load(src: str) -> Image.Image:
    img = Image.open(src).convert("RGB")
    if max(img.size) > WORK:
        k = WORK / max(img.size)
        img = img.resize((int(img.width * k), int(img.height * k)), Image.LANCZOS)
    return img


def grey_world(img: Image.Image) -> Image.Image:
    """Баланс белого «серым миром» — ТОЛЬКО по явной просьбе.

    По умолчанию цвет фото НЕ трогаем: материал застройщика — это и есть его цвет. «Серый мир»
    считает, что средний цвет кадра нейтрален, и у тёплого дерева уводит тон в зелень
    (проба 30.09: дубовый пол получился оливковым `#899c7a`).
    """
    a = np.asarray(img, np.float32)
    mean = a.reshape(-1, 3).mean(0)
    gain = float(mean.mean()) / np.maximum(mean, 1.0)
    gain = np.clip(gain, 0.85, 1.2)
    return Image.fromarray(np.clip(a * gain, 0, 255).astype(np.uint8))


def seamless_wrap(img: np.ndarray, period_px: float | None, blend: float = 0.12) -> np.ndarray:
    """Бесшовность БЕЗ зеркала: шов закрываем перекрёстным сведением соседних полос.

    Зеркальная склейка (как у процедурных образцов) на фото даёт симметричного «призрака» —
    узнаваемое пятно-бабочку в середине тайла (проба 30.09). Здесь: сдвиг на половину, затем
    мягкое сведение двух РАЗНЫХ полос. По ширине, если известен шаг досок, подрезаем тайл до
    целого числа досок — тогда левый и правый край совпадают по фазе сами.
    """
    h, w = img.shape[:2]
    if period_px and period_px > 8:
        k = max(1, int(w // period_px))
        cut = int(round(k * period_px))
        if 32 <= cut <= w:
            img = img[:, :cut]
            w = cut
    rolled = np.roll(np.roll(img, h // 2, axis=0), w // 2, axis=1).astype(np.float32)
    bw = max(2, int(w * blend))
    bh = max(2, int(h * blend))
    cx, cy = w // 2, h // 2
    rx = np.linspace(0, 1, 2 * bw, dtype=np.float32)[None, :, None]
    strip = rolled[:, cx - bw : cx + bw]
    rolled[:, cx - bw : cx + bw] = strip * (1 - rx) + np.roll(strip, bw, axis=1) * rx
    ry = np.linspace(0, 1, 2 * bh, dtype=np.float32)[:, None, None]
    strip = rolled[cy - bh : cy + bh, :]
    rolled[cy - bh : cy + bh, :] = strip * (1 - ry) + np.roll(strip, bh, axis=0) * ry
    return np.clip(rolled, 0, 255).astype(np.uint8)


def sharpness_map(grey: np.ndarray, win: int) -> np.ndarray:
    """Насколько резок каждый квадрат: дисперсия лапласиана в окне (дальний край пола размыт)."""
    lap = np.abs(np.gradient(np.gradient(grey, axis=0), axis=0)) + np.abs(
        np.gradient(np.gradient(grey, axis=1), axis=1)
    )
    ii = np.cumsum(np.cumsum(lap, 0), 1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    h, w = grey.shape
    out = np.zeros((h, w), np.float32)
    ys = np.arange(0, h - win)
    xs = np.arange(0, w - win)
    for y in ys[::4]:
        s = ii[y + win, xs + win] - ii[y, xs + win] - ii[y + win, xs] + ii[y, xs]
        out[y, xs] = s / (win * win)
    return out


def plank_angle(grey: np.ndarray) -> float:
    """Куда идут доски: направление, в котором изображение МЕНЬШЕ всего меняется.

    Швы между досками — длинные прямые: вдоль доски яркость почти постоянна, поперёк — скачет.
    Проверяем повороты через 2° и берём тот, где сумма перепадов ПО ВЕРТИКАЛИ минимальна.
    """
    im = Image.fromarray(grey.astype(np.uint8))
    side = min(im.size)
    im = im.crop((
        (im.width - side) // 2, (im.height - side) // 2,
        (im.width - side) // 2 + side, (im.height - side) // 2 + side,
    )).resize((320, 320), Image.LANCZOS)
    best, best_score = 0.0, None
    for ang in range(0, 180, 2):
        r = np.asarray(im.rotate(ang, resample=Image.BILINEAR, expand=False), np.float32)
        c = r[60:260, 60:260]
        vert = float(np.abs(np.diff(c, axis=0)).mean())
        if best_score is None or vert < best_score:
            best_score, best = vert, float(ang)
    return best


def plank_width_px(tile: np.ndarray) -> float | None:
    """Ширина доски в пикселях — по ТЁМНЫМ ЛИНИЯМ ШВОВ, а не по автокорреляции.

    Автокорреляция профиля перепадов цеплялась за рисунок древесины и давала 26 или 102 px там,
    где доска ~420 px (замеры 30.09), а от этого числа зависит масштаб доски на полу. Швы между
    досками — это узкие тёмные вертикальные линии: находим их как провалы яркости и берём
    медианное расстояние между соседними.
    """
    grey = np.asarray(Image.fromarray(tile).convert("L"), np.float32)
    col = grey.mean(0)
    # сглаживаем, чтобы не ловить отдельные тёмные волокна
    k = max(3, len(col) // 200)
    sm = np.convolve(col, np.ones(k) / k, mode="same")
    thr = sm.mean() - 0.8 * sm.std()
    dark = sm < thr
    # центры провалов
    seams: list[int] = []
    i = 0
    while i < len(dark):
        if dark[i]:
            j = i
            while j + 1 < len(dark) and dark[j + 1]:
                j += 1
            if j - i < len(col) // 12:        # широкая тёмная область — это не шов, а тень
                seams.append((i + j) // 2)
            i = j + 1
        else:
            i += 1
    if len(seams) >= 2:
        gaps = np.diff(seams)
        gaps = gaps[gaps > len(col) // 20]     # соседние линии одного шва не считаем
        if gaps.size:
            return float(np.median(gaps))
    return None


def best_patch(img: Image.Image, top: int = 12) -> list[tuple[Image.Image, dict]]:
    """Кандидаты-квадраты: резкие, ровно освещённые, без инородных пятен."""
    grey = np.asarray(img.convert("L"), np.float32)
    win = max(260, min(img.size) // 2)
    sharp = sharpness_map(grey, win)
    ii = np.cumsum(np.cumsum(grey, 0), 1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    h, w = grey.shape
    cands: list[tuple[float, int, int, dict]] = []
    for y in range(0, h - win, max(24, win // 6)):
        for x in range(0, w - win, max(24, win // 6)):
            s = ii[y + win, x + win] - ii[y, x + win] - ii[y + win, x] + ii[y, x]
            luma = s / (win * win)
            if luma < 30 or luma > 235:       # тень и пересвет не годятся
                continue
            sh = float(sharp[y, x])
            # центр кадра обычно резче и без виньетки — лёгкое предпочтение
            cx, cy = (x + win / 2) / w - 0.5, (y + win / 2) / h - 0.5
            centre = 1.0 - min(1.0, (cx * cx + cy * cy) * 2.2)
            cands.append((sh * (0.6 + 0.4 * centre), y, x, {"luma": round(float(luma), 1),
                                                            "sharp": round(float(sh), 2)}))
    cands.sort(key=lambda t: -t[0])
    out = []
    for _, y, x, diag in cands[: top * 3]:
        if any(abs(y - py) < win // 2 and abs(x - px) < win // 2 for py, px in
               [(d["at"][1], d["at"][0]) for _, d in out]):
            continue  # не берём почти тот же квадрат ещё раз
        diag = {**diag, "at": [x, y], "win": win}
        out.append((img.crop((x, y, x + win, y + win)), diag))
        if len(out) >= top:
            break
    return out


def prepare(patch: Image.Image) -> tuple[np.ndarray, float, float, float]:
    arr = flatten_light(np.asarray(patch.resize((TILE, TILE), Image.LANCZOS), np.float32))
    period = plank_width_px(arr.astype(np.uint8))
    tile = seamless_wrap(arr.astype(np.uint8), period)
    if tile.shape[0] != TILE or tile.shape[1] != TILE:
        tile = np.asarray(Image.fromarray(tile).resize((TILE, TILE), Image.LANCZOS))
    err = seam_error(np.asarray(Image.fromarray(tile).convert("L")))
    blob = max(blob_ratio(tile), peak_dev(tile) / 2.6)
    return tile, err, blob, quadrant_spread(tile)


def main() -> int:
    ap = argparse.ArgumentParser(description="текстура из фотографии материала")
    ap.add_argument("--src", required=True, help="файл фотографии")
    ap.add_argument("--id", required=True, help="идентификатор материала (латиницей)")
    ap.add_argument("--title", required=True)
    ap.add_argument("--surfaces", default="floor", help="через запятую: floor, wall, front, worktop…")
    ap.add_argument("--plank-cm", type=float, default=0.0,
                    help="ширина доски/плитки в см из спецификации — задаёт масштаб")
    ap.add_argument("--tile-cm", type=float, default=0.0, help="задать размер повтора напрямую")
    ap.add_argument("--roughness", type=float, default=0.5)
    ap.add_argument("--no-rotate", action="store_true", help="не выравнивать направление досок")
    ap.add_argument("--white-balance", action="store_true",
                    help="снять цветовой увод «серым миром» (по умолчанию цвет фото не трогаем)")
    ap.add_argument("--out", default="public/flat3d/materials")
    ap.add_argument("--source-url", default="")
    ap.add_argument("--licence", default="")
    ap.add_argument("--report", default="", help="куда положить json-отчёт о прогоне")
    a = ap.parse_args()

    img = load(a.src)
    if a.white_balance:
        img = grey_world(img)
    angle = 0.0
    if not a.no_rotate:
        angle = plank_angle(np.asarray(img.convert("L"), np.float32))
        if angle:
            img = img.rotate(angle, resample=Image.BICUBIC, expand=False)
            # после поворота края пустые — обрезаем с запасом
            m = int(min(img.size) * 0.12)
            img = img.crop((m, m, img.width - m, img.height - m))

    chosen = None
    tried = 0
    scored = []
    for patch, diag in best_patch(img):
        tried += 1
        tile, err, blob, quad = prepare(patch)
        scored.append((err + blob * 20 + quad * 6, tile, err, blob, quad, diag))
        if err <= MAX_SEAM and blob <= MAX_BLOB and quad <= MAX_QUAD:
            chosen = (tile, err, blob, quad, diag)
            break
    if chosen is None:
        if not scored:
            print("не нашёл ни одного пригодного участка на фото", file=sys.stderr)
            return 2
        scored.sort(key=lambda t: t[0])
        _, tile, err, blob, quad, diag = scored[0]
        chosen = (tile, err, blob, quad, diag)
    tile, err, blob, quad, diag = chosen
    gate = err <= MAX_SEAM and blob <= MAX_BLOB and quad <= MAX_QUAD

    # масштаб: ширина доски в пикселях → сантиметры на тайл
    px = plank_width_px(tile)
    if a.tile_cm > 0:
        tile_cm = a.tile_cm
    elif a.plank_cm > 0 and px:
        tile_cm = round(TILE / px * a.plank_cm, 1)
    else:
        tile_cm = 60.0
    tile_cm = float(min(400.0, max(15.0, tile_cm)))

    # карты рельефа строятся по 8-битной серой копии: функции конвейера ждут именно её
    height = np.asarray(Image.fromarray(tile).convert("L").filter(ImageFilter.GaussianBlur(1.1)))
    mat = write_material(
        a.out, a.id, tile, height,
        tile_cm=(tile_cm, tile_cm), title_ru=a.title, title_en=a.title,
        roughness_base=a.roughness, roughness_spread=0.12, metalness=0.0,
        normal_strength=1.2, seamless=False,   # тайл уже сшит в prepare()
    )
    mat["surfaces"] = [s.strip() for s in a.surfaces.split(",") if s.strip()]
    mat["source"] = {
        "kind": "photo-material",
        "src": os.path.basename(a.src),
        "sourceUrl": a.source_url,
        "licence": a.licence,
        "plankPx": round(px, 1) if px else None,
        "plankCm": a.plank_cm or None,
        "rotatedDeg": round(angle, 1),
        "patch": diag,
        "seamError": round(err, 2),
        "blob": round(blob, 3),
        "quad": round(quad, 3),
        "gate": gate,
        "tried": tried,
    }
    print(json.dumps(mat, ensure_ascii=False, indent=1))
    if a.report:
        json.dump(mat, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n{'ГЕЙТ ПРОЙДЕН' if gate else 'ГЕЙТ НЕ ПРОЙДЕН'}: шов {err:.2f} (норма ≤{MAX_SEAM}), "
          f"пятна {blob:.3f} (≤{MAX_BLOB}), половинки {quad:.3f} (≤{MAX_QUAD}); "
          f"повтор {tile_cm:.0f} см, поворот {angle:.0f}°", file=sys.stderr)
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())

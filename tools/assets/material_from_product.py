#!/usr/bin/env python3
"""Текстура фасада ИЗ ФОТО реального товара нашего каталога (владелец 29.09).

ЗАЧЕМ. Материалы фасадов нельзя брать «откуда-нибудь»: покупатель выбирает то, что реально
продаётся, и фактура должна быть от этого самого товара. Берём фото из нашего каталога
(divan.ru и др. через Гдеслон), вырезаем ровный участок дверцы/боковины и делаем из него
бесшовный материал.

КАК РАБОТАЕТ (и почему именно так):
 1. фото товара снято на белом фоне → отделяем предмет от фона по «непохожести на белый»;
 2. ищем самый РОВНЫЙ участок предмета: скользящим окном считаем «занятость» (модуль градиента)
    и берём окно с минимумом рёбер и максимумом площади самого предмета — это и есть фасад,
    а не ручка, стык или тень;
 3. ВЫРАВНИВАЕМ СВЕТ: делим картинку на сильно размытую версию себя. Без этого в текстуру
    впечатывается студийный градиент, и стена из такой «плитки» выглядит полосатой;
 4. делаем бесшовность (сдвиг на половину + сведение швов) и нормализуем яркость;
 5. рельеф (normal/roughness) считаем СЛАБЫМ: фотография уже несёт свет, сильный рельеф
    запечёт его второй раз (замечание рецензента 28.09).

Запуск:
    ~/venvs/scout/bin/python tools/assets/material_from_product.py --role шкаф --take 4
    ~/venvs/scout/bin/python tools/assets/material_from_product.py --sid 112923_1694725820385140752 --id front-oak

Выход: `public/flat3d/materials/<id>.webp` (+карты и превью) и запись в `data/flat3d/materials.json`
с провенансом: из какого товара, какого магазина и по какой ссылке взята фактура.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import urllib.request

import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from material_pipeline import (  # noqa: E402
    PREVIEW,
    TILE,
    make_seamless,
    normal_from_height,
    normalize_colour,
    roughness_from_height,
)

PSQL = ["docker", "exec", "-i", "remlab-devdb", "psql", "-U", "remlab", "-d", "remlab",
        "-q", "-t", "-A", "-F", "\x1f", "-v", "ON_ERROR_STOP=1"]
UA = {"User-Agent": "Mozilla/5.0 (compatible; remlab-material/1.0)"}


def q(sql: str) -> list[list[str]]:
    out = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip()[:300])
    return [line.split("\x1f") for line in out.stdout.strip().splitlines() if line.strip()]


def fetch_image(url: str) -> Image.Image:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 — CDN магазина из нашего каталога
        return Image.open(io.BytesIO(r.read())).convert("RGB")


def white_balance(img: Image.Image) -> Image.Image:
    """Баланс белого по фону товарного фото.

    Фон у карточки товара — заведомо белый, значит он сам работает эталоном: приводим его к
    нейтрали и убираем цветовой увод студийного света. Раньше вместо этого яркость насильно
    тянулась к среднему — и белый фасад приезжал в сцену СЕРЫМ (замер 29.09).
    """
    arr = np.asarray(img, np.float32)
    mx, mn = arr.max(axis=2), arr.min(axis=2)
    bg = (mn > 232) & ((mx - mn) < 14)
    if bg.sum() < 500:
        return img
    ref = arr[bg].mean(axis=0)
    gain = float(ref.mean()) / np.maximum(ref, 1.0)
    gain = np.clip(gain, 0.85, 1.18)
    return Image.fromarray(np.clip(arr * gain, 0, 255).astype(np.uint8))


def quadrant_spread(tile: np.ndarray) -> float:
    """Однородность вырезки: если половинки разной яркости — это стык двух деталей, не фактура."""
    g = np.asarray(Image.fromarray(tile).convert("L"), np.float32)
    h, w = g.shape
    quads = [g[: h // 2, : w // 2], g[: h // 2, w // 2 :], g[h // 2 :, : w // 2], g[h // 2 :, w // 2 :]]
    means = [float(q_.mean()) for q_ in quads]
    return (max(means) - min(means)) / max(float(g.mean()), 1.0)


def object_mask(arr: np.ndarray) -> np.ndarray:
    """Пиксели предмета: фото товара снято на белом, поэтому фон — «почти белый и без цвета»."""
    mx = arr.max(axis=2)
    mn = arr.min(axis=2)
    near_white = (mn > 232) & ((mx - mn) < 14)
    return ~near_white


def busyness(grey: np.ndarray) -> np.ndarray:
    """Модуль градиента: где много рёбер — там ручки, стыки, декор, а не ровный фасад."""
    gx = np.abs(np.diff(grey, axis=1, prepend=grey[:, :1]))
    gy = np.abs(np.diff(grey, axis=0, prepend=grey[:1, :]))
    g = gx + gy
    return np.asarray(Image.fromarray(g.astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)), np.float32)


def integral(a: np.ndarray) -> np.ndarray:
    return np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)


def rect_mean(ii: np.ndarray, y: int, x: int, s: int) -> float:
    total = ii[y + s, x + s] - ii[y, x + s] - ii[y + s, x] + ii[y, x]
    return float(total) / (s * s)


def patch_candidates(img: Image.Image, top: int = 14) -> list[tuple[Image.Image, dict]]:
    """Кандидаты на фактуру: несколько самых ровных участков предмета, лучший — первым.

    Один «самый ровный» участок брать нельзя: на фасаде шкафа ровно почти везде, и в вырезку
    попадают ручка или стык дверей (замер 29.09: шов 6.9 и повторяющиеся ручки в тайле).
    Поэтому собираем список и отбраковываем его уже ПО РЕЗУЛЬТАТУ (`pick_patch`).
    """
    arr = np.asarray(img, np.float32)
    grey = arr.mean(axis=2)
    mask = object_mask(arr).astype(np.float32)
    busy = busyness(grey)

    ii_mask = integral(mask)
    ii_busy = integral(busy)
    ii_grey = integral(grey)
    h, w = grey.shape

    found: list[tuple[float, int, int, int, float, float]] = []
    for s in (int(min(h, w) * 0.34), int(min(h, w) * 0.26), int(min(h, w) * 0.19), int(min(h, w) * 0.14)):
        if s < 40:
            continue
        step = max(6, s // 10)
        for y in range(0, h - s, step):
            for x in range(0, w - s, step):
                if rect_mean(ii_mask, y, x, s) < 0.995:   # окно целиком на предмете
                    continue
                b = rect_mean(ii_busy, y, x, s)
                lum = rect_mean(ii_grey, y, x, s)
                if lum < 32 or lum > 242:                  # тень или пересвет — фактуры нет
                    continue
                # РОВНОСТЬ ВАЖНЕЕ РАЗМЕРА: крупное окно почти всегда захватывает ручку или стык
                # ровность важнее размера, НО совсем гладкий участок — это не фактура, а заливка:
                # такие штрафуем (замер 29.09: у дуба выбиралось поле без единого волокна)
                flat_penalty = 12.0 if b < 1.2 else 0.0
                score = (s / min(h, w)) * 22 - b * 3.4 - abs(lum - 150) * 0.05 - flat_penalty
                found.append((score, y, x, s, b, lum))
    if not found:
        side = int(min(h, w) * 0.4)
        found = [(0.0, (h - side) // 2, (w - side) // 2, side, float(busy.mean()), float(grey.mean()))]
    found.sort(key=lambda t: -t[0])

    picked: list[tuple[Image.Image, dict]] = []
    used: list[tuple[int, int, int]] = []
    for _score, y, x, s, b, lum in found:
        # не берём почти одно и то же окно дважды
        if any(abs(y - uy) < s * 0.6 and abs(x - ux) < s * 0.6 and abs(s - us) < s * 0.4 for uy, ux, us in used):
            continue
        used.append((y, x, s))
        picked.append((img.crop((x, y, x + s, y + s)),
                       {"patch_px": s, "busyness": round(b, 2), "luma": round(lum, 1), "at": [int(x), int(y)]}))
        if len(picked) >= top:
            break
    return picked


def chroma(tile: np.ndarray) -> float:
    """Насыщенность фактуры: по ней видно, не вырезали ли блик вместо материала."""
    a = tile.astype(np.float32)
    return float((a.max(axis=2) - a.min(axis=2)).mean())


def blob_ratio(tile: np.ndarray) -> float:
    """Доля пикселей, резко выбивающихся из фактуры: ручки, стыки, петли, блики."""
    g = np.asarray(Image.fromarray(tile).convert("L"), np.float32)
    med = float(np.median(g))
    dev = np.abs(g - med) / max(med, 1.0)
    return float((dev > 0.28).mean())


def peak_dev(tile: np.ndarray) -> float:
    """Самое заметное пятно (99-й процентиль отклонения).

    Долей пикселей ручку не поймать: тень от ручки занимает 0,3 % площади и гейт проходит,
    а в тайле она повторяется в каждом «кирпичике» и сразу бросается в глаза (кадр 29.09).
    Поэтому смотрим ещё и на СИЛУ самого заметного отклонения.
    """
    g = np.asarray(
        Image.fromarray(tile).convert("L").filter(ImageFilter.GaussianBlur(3)), np.float32
    )
    med = float(np.median(g))
    dev = np.abs(g - med) / max(med, 1.0)
    return float(np.percentile(dev, 99))


def flatten_light(arr: np.ndarray, sigma: int = 60) -> np.ndarray:
    """Снять студийный градиент, СОХРАНИВ цвет.

    Грабля 29.09: первая версия делила каждый канал на его же размытие. Для однотонного фасада
    размытие почти равно самой картинке, и на выходе получался РОВНЫЙ СЕРЫЙ — цвет дуба и графита
    исчезал (все четыре фактуры вышли серыми). Правильно: считать поправку по ЯРКОСТИ и умножать
    на неё все каналы — тогда уходит только неравномерность света, а цвет остаётся.
    """
    grey = arr.mean(axis=2)
    blur = np.asarray(
        Image.fromarray(grey.astype(np.uint8)).filter(ImageFilter.GaussianBlur(sigma)), np.float32
    )
    gain = float(blur.mean()) / np.maximum(blur, 6.0)
    gain = np.clip(gain, 0.65, 1.55)[..., None]
    return np.clip(arr * gain, 0, 255)


def seam_error(tile: np.ndarray) -> float:
    """Проверка бесшовности числом: насколько левый край расходится с правым (и верх с низом)."""
    a = tile.astype(np.float32)
    dx = np.abs(a[:, 0] - a[:, -1]).mean()
    dy = np.abs(a[0, :] - a[-1, :]).mean()
    inner = (np.abs(a[:, 1:] - a[:, :-1]).mean() + np.abs(a[1:, :] - a[:-1, :]).mean()) / 2
    return float((dx + dy) / 2 / max(inner, 1e-3))


MAX_SEAM = 2.0      # шов не должен быть заметнее внутренней фактуры больше чем вдвое
MAX_BLOB = 0.05     # не больше 5 % «инородных» пикселей (ручки, стыки)
MAX_QUAD = 0.16     # половинки вырезки не должны отличаться по яркости больше чем на 16 %
MAX_PEAK = 0.13     # самое заметное пятно (ручка, петля, блик) — не больше 13 % от тона


def prepare(patch: Image.Image) -> tuple[np.ndarray, float, float, float]:
    """Вырезка → ровный свет → бесшовный тайл + три оценки качества.

    Яркость НЕ подгоняем под общий уровень: светлота — это и есть материал (белый фасад обязан
    остаться белым, графит — тёмным). Цветовой увод уже снят балансом белого по фону.
    """
    arr = flatten_light(np.asarray(patch.resize((TILE, TILE), Image.LANCZOS), np.float32))
    tile = make_seamless(arr.astype(np.uint8), blend=0.18)
    err = seam_error(np.asarray(Image.fromarray(tile).convert("L")))
    return tile, err, max(blob_ratio(tile), peak_dev(tile) / (MAX_PEAK / MAX_BLOB)), quadrant_spread(tile)


def build(sid: str, name: str, shop: str, url: str, image_url: str, mid: str,
          title_ru: str, tile_cm: float, out_dir: str) -> dict:
    img = white_balance(fetch_image(image_url))
    candidates = patch_candidates(img)
    chosen = None
    tried = 0
    for patch, diag in candidates:
        tried += 1
        tile, err, blob, quad = prepare(patch)
        if err <= MAX_SEAM and blob <= MAX_BLOB and quad <= MAX_QUAD:
            chosen = (tile, err, blob, quad, diag)
            break
    if chosen is None:
        # ничего не прошло гейт — берём наименее плохой и честно пишем это в провенанс
        scored = []
        for patch, diag in candidates:
            tile, err, blob, quad = prepare(patch)
            scored.append((err + blob * 20 + quad * 6, tile, err, blob, quad, diag))
        scored.sort(key=lambda t: t[0])
        _, tile, err, blob, quad, diag = scored[0]
        chosen = (tile, err, blob, quad, diag)
    tile, err, blob, quad, diag = chosen
    diag = {**diag, "tried": tried, "blob": round(blob, 3), "quad": round(quad, 3),
            "chroma": round(chroma(tile), 1),
            "gate": err <= MAX_SEAM and blob <= MAX_BLOB and quad <= MAX_QUAD}

    height = np.asarray(Image.fromarray(tile).convert("L").filter(ImageFilter.GaussianBlur(1.2)))
    os.makedirs(out_dir, exist_ok=True)
    Image.fromarray(tile).save(os.path.join(out_dir, f"{mid}.webp"), quality=86, method=6)
    Image.fromarray(normal_from_height(height, 0.8)).resize((512, 512), Image.LANCZOS).save(
        os.path.join(out_dir, f"{mid}-n.webp"), quality=76, method=6)
    Image.fromarray(roughness_from_height(height, 0.45, 0.10)).resize((512, 512), Image.LANCZOS).save(
        os.path.join(out_dir, f"{mid}-r.webp"), quality=70, method=6)
    Image.fromarray(tile).resize((PREVIEW, PREVIEW), Image.LANCZOS).save(
        os.path.join(out_dir, f"{mid}-preview.webp"), quality=80, method=6)

    mean = np.asarray(tile).reshape(-1, 3).mean(0).astype(int)
    return {
        "id": mid,
        "titleRu": title_ru,
        "titleEn": title_ru,
        "colorHex": "#%02x%02x%02x" % tuple(int(v) for v in mean),
        "roughness": 0.45,
        "metalness": 0.0,
        "tileCm": [tile_cm, tile_cm],
        "surfaces": ["front"],
        "baseColorUrl": f"{mid}.webp",
        "normalUrl": f"{mid}-n.webp",
        "roughnessUrl": f"{mid}-r.webp",
        "previewUrl": f"{mid}-preview.webp",
        "source": {
            "kind": "photo",
            "productSid": sid,
            "productName": name,
            "shop": shop,
            "productUrl": url,
            "imageUrl": image_url,
            "patch": diag,
            "seamError": round(err, 2),
        },
    }


def slugify(text: str) -> str:
    table = str.maketrans("абвгдеёжзийклмнопрстуфхцчшщъыьэюя", "abvgdeejziiklmnoprstufhccss_y_eua")
    t = text.lower().translate(table)
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:28] or "front"


def main() -> int:
    ap = argparse.ArgumentParser(description="материал фасада из фото товара каталога")
    ap.add_argument("--role", default="шкаф", help="роль каталога: шкаф | комод | витрина | стеллаж")
    ap.add_argument("--like", default="", help="фильтр по названию, напр. дуб")
    ap.add_argument("--sid", default="", help="конкретный товар вместо поиска по роли")
    ap.add_argument("--id", default="", help="id материала (иначе из названия товара)")
    ap.add_argument("--take", type=int, default=3)
    ap.add_argument("--tile-cm", type=float, default=60.0, help="сколько см в одном повторе")
    ap.add_argument("--out", default="public/flat3d/materials")
    ap.add_argument("--manifest", default="data/flat3d/materials.json")
    a = ap.parse_args()

    where = ["status = 'active'", "coalesce(image_url_hd, image_url) is not null"]
    if a.sid:
        mid_, eid_ = a.sid.split("_", 1)
        where.append(f"shop_mid = {int(mid_)} and external_id = '{eid_}'")
    else:
        where.append(f"cat_role = '{a.role}'")
        if a.like:
            where.append(f"name ilike '%{a.like}%'")
    rows = q(
        "select shop_mid||'_'||external_id, name, shop, coalesce(direct_url, url), "
        "coalesce(image_url_hd, image_url) from products where "
        + " and ".join(where)
        + f" order by coalesce(price_rub, 0) desc limit {max(1, a.take)}"
    )
    if not rows:
        print("подходящих товаров не нашлось", file=sys.stderr)
        return 1

    out_dir = os.path.abspath(a.out)
    entries = []
    fails = 0
    for i, r in enumerate(rows, 1):
        sid, name, shop, url, image_url = (r + [""] * 5)[:5]
        mid = a.id or f"front-{slugify(name.split()[-1] if name else 'panel')}-{i}"
        try:
            e = build(sid, name, shop, url, image_url, mid, f"Фасад «{name[:38]}»", a.tile_cm, out_dir)
            entries.append(e)
            print(f"[{i}/{len(rows)}] {mid}: из {shop} · {name[:44]} · шов {e['source']['seamError']}")
        except Exception as exc:  # noqa: BLE001 — счётчик отказов обязателен
            fails += 1
            print(f"[{i}/{len(rows)}] ОШИБКА {name[:40]}: {exc}", file=sys.stderr)

    man_path = os.path.abspath(a.manifest)
    payload = {"_about": "", "baseUrl": "/flat3d/materials/", "materials": []}
    if os.path.exists(man_path):
        payload = json.load(open(man_path, encoding="utf-8"))
    by_id = {m["id"]: m for m in payload.get("materials", [])}
    for e in entries:
        by_id[e["id"]] = e
    payload["materials"] = [by_id[k] for k in sorted(by_id)]
    payload["_about"] = ("Материалы покрытий. Процедурные — tools/assets/material_pipeline.py, "
                         "фактуры фасадов из фото товаров — tools/assets/material_from_product.py.")
    with open(man_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"\nготово: {len(entries)}, отказов: {fails}; манифест — {len(by_id)} материалов")
    return 1 if fails and not entries else 0


if __name__ == "__main__":
    raise SystemExit(main())

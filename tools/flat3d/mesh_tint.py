#!/usr/bin/env python3
"""Подкраска модели под РЕАЛЬНЫЙ цвет товара (владелец 29.09: «цвет пропал — реши»).

ОТКУДА БЕДА. Цвет теряется НЕ в конфигураторе: у части моделей нашего конвейера текстура сама
по себе почти серая. Замер 29.09: у кресла «Роттердам Вельвет Жёлтый» насыщенность исходной
текстуры 21 из 255 — жёлтого там нет вовсе.

ЧТО ДЕЛАЕМ. Берём фото товара (карточка магазина, фон белый), считаем его собственный цвет,
берём средний цвет текстуры меша и записываем в каталог множитель на канал. В сцене модель
умножается на этот множитель: светотень и фактура меша остаются, а тон становится товарным.

ПРОСТРАНСТВО ЦВЕТА (важно). Множитель считается и применяется В ЛИНЕЙНОМ свете: `THREE.Color`
трактует числа как значения рабочего (линейного) пространства. Отношение средних sRGB-значений —
другое число: замер 29.09 показал, что жёлтый диван при таком счёте выходил вдвое бледнее
(насыщенность 74 из 255 при цели 151).

Ограничения (осознанные): множитель зажат, чтобы не превращать модель в кислотную; если у меша
и так верный тон, поправка близка к единице и ничего не портит. Это не замена честной текстуры —
это способ показать покупателю ТОТ цвет, который он выбрал, пока конвейер мешей не научится
переносить цвет сам ([[mesh-color]]).

Запуск: ~/venvs/scout/bin/python tools/flat3d/mesh_tint.py
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "assets"))

from runtime_mesh import image_bytes, parse_glb  # noqa: E402

MESH_BASE = "https://remont-lab.online/test/mesh-pilot10/"
UA = {"User-Agent": "Mozilla/5.0 (compatible; remlab-tint/1.0)"}
# Зажим В ЛИНЕЙНОМ пространстве: прежние 0,55…1,9 были зажимом sRGB-отношения, в линейном это
# примерно 0,26…3,9. Шире — модель уходит в кислотный цвет, у́же — жёлтый диван остаётся серым.
MIN_GAIN, MAX_GAIN = 0.26, 3.9


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as r:  # noqa: S310 — наш прод и CDN магазина
        return r.read()


def to_linear(a: np.ndarray) -> np.ndarray:
    """sRGB 0…255 → линейный свет 0…1 (точная формула, не гамма 2.2)."""
    c = np.asarray(a, np.float64) / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def to_srgb(a: np.ndarray) -> np.ndarray:
    """Линейный свет 0…1 → sRGB 0…255 (для читаемых пометок в каталоге)."""
    c = np.clip(np.asarray(a, np.float64), 0.0, 1.0)
    s = np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)
    return s * 255.0


def product_colour(photo: bytes) -> tuple[np.ndarray, float]:
    """Собственный цвет товара на фото: без белого фона, без глубоких теней и бликов."""
    im = Image.open(io.BytesIO(photo)).convert("RGB")
    im.thumbnail((420, 420))
    a = np.asarray(im, np.float32)
    mx, mn = a.max(2), a.min(2)
    lum = a.mean(2)
    body = (~((mn > 232) & ((mx - mn) < 14))) & (lum > 42) & (lum < 246)
    if body.sum() < 300:
        return np.array([1.0, 1.0, 1.0], np.float32), 0.0
    px = a[body]
    # взвешиваем по насыщенности: обивку видно лучше, чем ножки и тени
    sat = (px.max(1) - px.min(1)) + 6.0
    # УСРЕДНЯЕМ В ЛИНЕЙНОМ СВЕТЕ: движок умножает цвета в линейном пространстве, и среднее
    # sRGB-значений даёт другое число (замер 29.09: подкраска выходила вдвое слабее задуманной)
    lin = to_linear(px)
    colour = (lin * sat[:, None]).sum(0) / sat.sum()
    return colour, float((px.max(1) - px.min(1)).mean())


def mesh_colour(glb: bytes) -> np.ndarray | None:
    """Средний цвет базовой текстуры меша."""
    js, bin_ = parse_glb(glb)
    mats = js.get("materials") or []
    if not mats:
        return None
    pbr = mats[0].get("pbrMetallicRoughness", {})
    ti = pbr.get("baseColorTexture", {}).get("index")
    if ti is None or ti >= len(js.get("textures", [])):
        return None
    src = js["textures"][ti].get("source")
    if src is None or src >= len(js.get("images", [])):
        return None
    raw = image_bytes(js["images"][src], js, bin_)
    if not raw:
        return None
    im = Image.open(io.BytesIO(raw)).convert("RGB")
    im.thumbnail((256, 256))
    a = np.asarray(im, np.float32).reshape(-1, 3)
    lum = a.mean(1)
    keep = (lum > 25) & (lum < 250)
    px = a[keep] if keep.sum() > 100 else a
    return to_linear(px).mean(0)


def main() -> int:
    ap = argparse.ArgumentParser(description="подкраска мешей под цвет товара")
    ap.add_argument("--catalogue", default="data/flat3d/furniture.json")
    ap.add_argument("--min-sat", type=float, default=12.0,
                    help="ниже этой насыщенности фото товар считаем нейтральным и не красим")
    a = ap.parse_args()

    path = os.path.abspath(a.catalogue)
    data = json.load(open(path, encoding="utf-8"))
    ok = skip = fail = 0
    for o in data.get("options", []):
        asset = o.get("asset") or {}
        if asset.get("kind") != "mesh" or not o.get("previewUrl"):
            continue
        try:
            photo = fetch(o["previewUrl"])
            target, sat = product_colour(photo)
            glb = fetch(f"{MESH_BASE}{asset['meshId']}/model.glb")
            have = mesh_colour(glb)
            if have is None:
                fail += 1
                print(f"нет текстуры у меша: {o['id']}", file=sys.stderr)
                continue
            # ПОЛ у знаменателя: у части мешей канал почти нулевой (напр. синий у терракоты),
            # без него поправка улетала бы в потолок и держалась только зажимом
            gain = np.clip(target / np.maximum(have, 0.012), MIN_GAIN, MAX_GAIN)
            # нормируем по СВЕТЛОТЕ (Rec.709 в линейном): правим ТОН, а не общую яркость —
            # яркость задаёт свет сцены
            weights = np.array([0.2126, 0.7152, 0.0722])
            gain = gain / max(float((gain * weights).sum()), 1e-3)
            gain = np.clip(gain, MIN_GAIN, MAX_GAIN)
            drift = float(np.abs(gain - 1.0).max())
            if sat < a.min_sat and drift < 0.12:
                skip += 1
                asset.pop("tintRgb", None)
                continue
            asset["tintRgb"] = [round(float(v), 3) for v in gain]
            asset["tintFrom"] = {
                "photoColor": "#%02x%02x%02x" % tuple(int(v) for v in np.clip(to_srgb(target), 0, 255)),
                "meshColor": "#%02x%02x%02x" % tuple(int(v) for v in np.clip(to_srgb(have), 0, 255)),
                "photoSat": round(sat, 1),
                "space": "linear",
            }
            ok += 1
            print(f"{o['id']:16s} {asset['tintFrom']['meshColor']} → {asset['tintFrom']['photoColor']}  ×{asset['tintRgb']}")
        except Exception as exc:  # noqa: BLE001 — счётчик отказов обязателен
            fail += 1
            print(f"ОШИБКА {o.get('id')}: {exc}", file=sys.stderr)

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"\nподкрашено: {ok}, без правки: {skip}, отказов: {fail}")
    return 1 if fail and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())

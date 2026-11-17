#!/usr/bin/env python3
"""Фактура стен и пола паспорта отделки из CC0-карт ambientCG (render-3d-01 шаг 1, T-20261117-06/1).

ЗАЧЕМ. Стены и пол комнаты в /demo были одной краской без рельефа — главный «картонный» признак кадра. Карты ambientCG
(лицензия CC0 — без условий и платы) дают настоящую фактуру. Цвет — по-прежнему ЦВЕТ ПАСПОРТА комнаты (`finish`): карта делается
НЕЙТРАЛЬНОЙ (серой), а цвет паспорта умножается на неё в сцене (`lib/viewer3d/finish-passport.ts:tintHex`) — одна и та же
карта красится под любую квартиру, и /demo с Blender берут один файл и один расчёт.

    поверхность паспорта (wall / floor) → скан ambientCG (`data/flat3d/scans/<asset>/`) → нейтральная карта + нормали +
    шероховатость → материал `finish-<поверхность>` в `data/flat3d/materials.json` (с `tintMean`, `tileCm`, `source`).

Правила и версия — `data/flat3d/finish-cc0.json`. Источник, лицензия, авторы, размер и sha256 — `scans/<asset>/source.json`.
Скачанное — данные: файлы проверяются как картинки, код из архива не исполняется.

Запуск (venv проекта, из корня репо):
    ~/venvs/scout/bin/python tools/assets/material_from_cc0.py fetch --asset Plaster002
    ~/venvs/scout/bin/python tools/assets/material_from_cc0.py build
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import io
import json
import os
import re
import sys
import urllib.request
import zipfile

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import material_from_scan as MS  # noqa: E402 — обработка карт (нормали, шероховатость, поворот) общая с полом из сканов
from conveyor_seal import dump_sealed  # noqa: E402 — путь к tools/ops добавил material_pipeline через material_from_scan

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CONFIG = os.path.join(ROOT, "data", "flat3d", "finish-cc0.json")
SCANS = os.path.join(ROOT, "data", "flat3d", "scans")
MANIFEST = os.path.join(ROOT, "data", "flat3d", "materials.json")
OUT = os.path.join(ROOT, "public", "flat3d", "materials")
ZIP_URL = "https://ambientcg.com/get?file={a}_1K-JPG.zip"
API_URL = "https://ambientcg.com/api/v2/full_json?id={a}"
PICK = {"diff": "_Color.jpg", "nor_gl": "_NormalGL.jpg", "rough": "_Roughness.jpg"}   # → имена как у сканов Poly Haven
FULL, LITE, PREVIEW = MS.FULL, MS.LITE, MS.PREVIEW


def lin(c: np.ndarray) -> np.ndarray:
    c = c / 255.0
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def neutral(diff: np.ndarray, *, gray: float, contrast: float, chroma: float, flatten: float) -> np.ndarray:
    """Нейтральная карта цвета: рисунок скана без его оттенка, средняя яркость `gray` (sRGB 0..1).

    Яркость: крупные пятна света съёмки сняты (`flatten`), разброс вокруг среднего — `contrast`; `chroma` — доля собственных
    оттенков скана (0 — чисто серая карта). Средний цвет карты — серый: оттенок даёт только цвет паспорта."""
    d = diff.astype(np.float64)
    lum = np.maximum(d @ MS.LUM, 1.0)
    low = np.maximum(MS.wrap_blur(lum, diff.shape[0] / 8.0), 1.0)
    lum_f = lum * (float(lum.mean()) / low) ** flatten
    rel = 1.0 + (lum_f / float(lum_f.mean()) - 1.0) * contrast
    c = d / lum[..., None]
    c_rel = c / c.reshape(-1, 3).mean(0)
    c_rel = 1.0 + (c_rel - 1.0) * chroma
    c_rel /= c_rel.reshape(-1, 3).mean(0)          # оттенки скана — отклонения вокруг серого, среднее не красит
    out = gray * 255.0 * rel[..., None] * c_rel
    return np.clip(out, 0, 255).astype(np.uint8)


def tint_mean(col: np.ndarray) -> float:
    """Средняя яркость карты в ЛИНЕЙНОМ свете (после отсечки): `tintHex` делит цвет паспорта на неё."""
    return round(float(lin(col.astype(np.float64)).mean()), 3)


def _get(url: str, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "remlab-material-from-cc0/1.0 (+https://remont-lab.online)"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch(asset: str, scans_dir: str = SCANS) -> dict:
    """Скан ambientCG → `data/flat3d/scans/<asset>/` (цвет, нормали OpenGL, шероховатость 1K + source.json)."""
    if not re.fullmatch(r"[A-Za-z0-9]{3,30}", asset):
        raise SystemExit(f"странное имя скана: {asset}")
    info = json.loads(_get(API_URL.format(a=asset), 30))["foundAssets"][0]
    zf = zipfile.ZipFile(io.BytesIO(_get(ZIP_URL.format(a=asset))))
    dst = os.path.join(scans_dir, asset)
    os.makedirs(dst, exist_ok=True)
    sha = {}
    for kind, suffix in PICK.items():
        names = [n for n in zf.namelist() if n.endswith(suffix) and "/" not in n]
        if len(names) != 1:
            raise SystemExit(f"{asset}: в архиве нет {suffix}")
        data = zf.read(names[0])
        Image.open(io.BytesIO(data)).verify()          # только картинка: иначе отказ, файл не пишем
        name = {"diff": "diff.jpg", "nor_gl": "nor_gl.jpg", "rough": "rough.jpg"}[kind]
        open(os.path.join(dst, name), "wb").write(data)
        sha[name] = hashlib.sha256(data).hexdigest()
    dx, dy = float(info.get("dimensionX") or 0), float(info.get("dimensionY") or 0)
    rec = {
        "asset": asset, "title": str(info.get("displayName", asset)), "site": "ambientCG",
        "pageUrl": str(info.get("shortLink", f"https://ambientcg.com/a/{asset}")),
        "files": {k: ZIP_URL.format(a=asset) + f" ({PICK[k]})" for k in PICK},
        "licence": "CC0-1.0", "licenceUrl": "https://docs.ambientcg.com/license/",
        "authors": {"ambientCG": "Processing"}, "released": str(info.get("releaseDate", ""))[:10],
        "realMm": [round(dx * 10, 1), round(dy * 10, 1)],   # 0×0 — источник размер не задаёт, тайл берётся из правила
        "downloaded": _dt.date.today().isoformat(), "sha256": sha,
    }
    with open(os.path.join(dst, "source.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return rec


def files_of(ver: int, mid: str) -> dict[str, str]:
    stem = f"{mid}-v{ver}"
    return {"baseColorUrl": f"{stem}.webp", "baseColorLiteUrl": f"{stem}-lite.webp", "normalUrl": f"{stem}-n.webp",
            "roughnessUrl": f"{stem}-r.webp", "previewUrl": f"{stem}-preview.webp"}


def build_one(surface: str, rule: dict, ver: int, *, scans_dir: str = SCANS, out_dir: str = OUT) -> dict:
    sdir = os.path.join(scans_dir, rule["asset"])
    src = json.load(open(os.path.join(sdir, "source.json"), encoding="utf-8"))
    diff = MS._load(os.path.join(sdir, "diff.jpg"), FULL)
    # mode "photo" — своя расцветка скана (кирпич: красный кирпич и серый шов — сам рисунок): карта цветная, тонировки паспортом нет
    # (`tintMean` в записи не пишется → `finish-passport.ts:tintHex` даёт белый), `colorHex` — средний цвет скана для плоского запасного
    photo = rule.get("mode") == "photo"
    col = np.asarray(diff, dtype=np.uint8) if photo else neutral(diff, gray=float(rule["gray"]), contrast=float(rule["contrast"]),
                                                                 chroma=float(rule["chroma"]), flatten=float(rule["flatten"]))
    # нормали шумной штукатурки в 1024 весят ~200 КБ: для стены хватает 512 (≈4 точки на см при тайле 120 см)
    nrm = MS.normal_strength(MS._load(os.path.join(sdir, "nor_gl.jpg"), int(rule.get("normalSize", FULL))), float(rule["normal"]))
    rgh = MS.roughness_map(MS._load(os.path.join(sdir, "rough.jpg"), LITE, "L"), float(rule["roughSpread"]))
    files = files_of(ver, rule["id"])
    os.makedirs(out_dir, exist_ok=True)
    w = lambda arr, name, q: Image.fromarray(arr).save(os.path.join(out_dir, name), quality=q, method=6)  # noqa: E731
    small = lambda n: np.asarray(Image.fromarray(col).resize((n, n), Image.LANCZOS))  # noqa: E731
    w(col, files["baseColorUrl"], 86)
    w(small(LITE), files["baseColorLiteUrl"], 84)
    w(nrm, files["normalUrl"], 86)
    w(rgh, files["roughnessUrl"], 80)
    w(small(PREVIEW), files["previewUrl"], 82)
    mean_lin = tint_mean(col)                           # тонировка одна на полный и лёгкий размер: среднее у них совпадает до тысячных
    tile = [float(x) for x in rule["tileCm"]]
    # отпечаток байтов всех карт: материалы лежат в бандле движка, и смена карты под тем же именем меняет бандл → версию витрины →
    # перевыпуск туров (`tools/ops/demo-release-hash.mjs` считает файлы сборки, внешние карты в него не входят — Codex 17.11)
    h = hashlib.sha256()
    for k in sorted(files):
        h.update(open(os.path.join(out_dir, files[k]), "rb").read())
    return {
        "mapsSha": h.hexdigest()[:16],
        "id": rule["id"], "titleRu": rule["titleRu"], "titleEn": rule["titleEn"], "colorHex": rule["colorHex"],
        "roughness": round(min(1.0, float(rule["roughness"]) / MS.ROUGH_MEAN), 3), "metalness": 0.0,
        "tileCm": tile, **({} if photo else {"tintMean": mean_lin}), **files, "surfaces": rule.get("surfacesOut", [surface]),
        "source": {
            "kind": "photo-material", "sourceUrl": src["pageUrl"], "licence": src["licence"],
            "method": f"cc0:{rule['asset']}@v{ver} " + ("photo (собственные цвета скана)" if photo else f"neutral gray={rule['gray']} contrast={rule['contrast']}"),
            "note": f"{src['site']}: {src['title']} ({', '.join(src.get('authors', {}))}), выпуск {src.get('released', '')}; "
                    + ("карта цветная — расцветка скана, паспорт её не красит" if photo else "карта нейтральная — цвет даёт паспорта отделки")
                    + (f"; {rule['tileNote']}" if rule.get("tileNote") else ""),
            "realCm": tile,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="фактура стен и пола паспорта из CC0-карт ambientCG")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="скачать скан ambientCG в data/flat3d/scans/<asset>/")
    f.add_argument("--asset", required=True)
    sub.add_parser("build", help="пересобрать материалы finish-* по data/flat3d/finish-cc0.json")
    a = ap.parse_args()
    if a.cmd == "fetch":
        rec = fetch(a.asset)
        print(f"скан {rec['asset']}: {rec['realMm']} мм, {rec['licence']}, выпуск {rec['released']}")
        return 0
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    ver = int(cfg.get("version", 1))
    built, fails = [], 0
    for surface, rule in cfg["surfaces"].items():
        try:
            e = build_one(surface, rule, ver)
            built.append(e)
            size = sum(os.path.getsize(os.path.join(OUT, e[k])) for k in files_of(ver, e["id"]))
            print(f"{e['id']}: {rule['asset']}, тайл {e['tileCm']} см, tintMean {e.get('tintMean', '—')}, {size // 1024} КБ")
        except Exception as exc:  # noqa: BLE001 — счётчик отказов обязателен, молча не глотаем
            fails += 1
            print(f"ОШИБКА {surface}: {exc}", file=sys.stderr)
    n = MS.write_manifest(built) if built else 0
    print(f"готово: {len(built)}, отказов: {fails}; манифест — {n} материалов")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

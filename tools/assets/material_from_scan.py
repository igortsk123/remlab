#!/usr/bin/env python3
"""Пол из CC0-сканов (T-20261111-24/2, владелец TG 1643/1655): настоящая фактура дерева и камня вместо нарисованной.

ЗАЧЕМ. Процедурный пол читался рисунком («жилы», чёрная решётка швов). Сканы Poly Haven (лицензия CC0 — без условий и
без оплаты) дают настоящий рельеф и волокно. Сопоставление — НЕ под варианты демо, а по ТИПУ покрытия:

    тип покрытия (генератор пресета `material_pipeline.PRESETS[id].gen`: planks / herringbone45 / tiles)
      → скан этого типа (`data/flat3d/floor-scans.json` → `types`)
      → физический размер тайла (`tileCm` = размер скана в мм из источника, не на глаз)
      → оттенок под цвет варианта (среднее карты = `colorHex` процедурного материала того же id)

Тип без скана (модульный паркет `herringbone`, ковролин) остаётся процедурным; плитку и камень дубом не подменяем.
Материал со сканом — отдельная запись `scan-<id>` в `data/flat3d/materials.json`; включает её флаг `enabled` в
`data/flat3d/floor-scans.json` (`lib/partners/registry.ts:materialOf`), выключенный флаг = прежний процедурный пол.

Сканы лежат в `data/flat3d/scans/<asset>/` — оригиналы 1k (цвет, нормали OpenGL, шероховатость) и `source.json`:
источник, адреса файлов, авторы, лицензия CC0, дата загрузки, sha256. Скачанное — данные, код из него не исполняется.

Карты (`public/flat3d/materials/scan-<id>-v<версия>*.webp`):
    цвет 1024 (полный режим) · цвет 512 `-lite` (телефон и Lite: только она, `lib/viewer3d/materials.ts:baseMaterial`)
    нормали 1024 `-n` и шероховатость 512 `-r` — только полному режиму · превью 256.
Версия в имени файла — для кэша сервиса кадров (`tools/scout/draft_render.py:_floor_image` ключует карту именем файла).

Запуск (venv проекта, из корня репо):
    ~/venvs/scout/bin/python tools/assets/material_from_scan.py fetch --asset laminate_floor_02
    ~/venvs/scout/bin/python tools/assets/material_from_scan.py build            # все полы, у типа которых есть скан
    ~/venvs/scout/bin/python tools/assets/material_from_scan.py build --id oak-grey
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import sys
import urllib.request

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import material_pipeline as MP  # noqa: E402

ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CONFIG = os.path.join(ROOT, "data", "flat3d", "floor-scans.json")
SCANS = os.path.join(ROOT, "data", "flat3d", "scans")
MANIFEST = os.path.join(ROOT, "data", "flat3d", "materials.json")
OUT = os.path.join(ROOT, "public", "flat3d", "materials")

FULL = 1024           # цвет и нормали полного режима
LITE = 512            # цвет телефона/Lite и шероховатость (урок 416: телефон упирается в видеопамять текстур)
PREVIEW = 256
ROUGH_MEAN = 0.85     # среднее карты шероховатости: three умножает `roughness` материала на карту
LUM = np.array([0.2126, 0.7152, 0.0722], np.float64)
PH_FILE = "https://dl.polyhaven.org/file/ph-assets/Textures/jpg/1k/{a}/{a}_{k}_1k.jpg"
PH_INFO = "https://api.polyhaven.com/info/{a}"
KINDS = {"diff": "diff.jpg", "nor_gl": "nor_gl.jpg", "rough": "rough.jpg"}


# ─────────────────────────────── обработка карт ───────────────────────────────


def wrap_blur(a: np.ndarray, sigma_px: float) -> np.ndarray:
    """Гаусс по тору (через БПФ): тайл бесшовный, и размытие обязано «заворачивать» края, иначе появится шов."""
    fy = np.fft.fftfreq(a.shape[0])[:, None]
    fx = np.fft.fftfreq(a.shape[1])[None, :]
    g = np.exp(-2.0 * (np.pi * sigma_px) ** 2 * (fx ** 2 + fy ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * g))


def tint(diff: np.ndarray, target_rgb: tuple[float, float, float], *, contrast: float, chroma: float,
         flatten: float) -> np.ndarray:
    """Перекраска скана под цвет варианта: среднее → `target_rgb`, рисунок волокна сохраняется.

    `flatten` 0..1 — снять крупные пятна света съёмки (иначе тайл повторяется «полосами»); `contrast` — разброс яркости
    вокруг среднего (светлый ламинат спокойнее скана); `chroma` — доля собственных оттенков скана (0 = только цвет варианта).
    """
    d = diff.astype(np.float64)
    lum = np.maximum(d @ LUM, 1.0)
    mean = float(lum.mean())
    low = np.maximum(wrap_blur(lum, diff.shape[0] / 8.0), 1.0)
    lum_f = lum * (mean / low) ** flatten
    rel = lum_f / float(lum_f.mean())
    rel = 1.0 + (rel - 1.0) * contrast
    c = d / lum[..., None]
    c_rel = c / c.reshape(-1, 3).mean(0)
    c_rel = 1.0 + (c_rel - 1.0) * chroma
    out = np.asarray(target_rgb, np.float64)[None, None, :] * rel[..., None] * c_rel
    out *= np.asarray(target_rgb, np.float64) / out.reshape(-1, 3).mean(0)   # среднее — ровно цвет варианта
    return np.clip(out, 0, 255).astype(np.uint8)


def rotate(img: np.ndarray, deg: int, normal: bool = False) -> np.ndarray:
    """Поворот на 0/90/180/270 против часовой. У карты нормалей поворачиваются и сами векторы (иначе свет «съедет»):
    в соглашении OpenGL (зелёный = вверх) поворот на 90° даёт x' = −y, y' = x."""
    k = (deg // 90) % 4
    out = np.rot90(img, k).copy()
    if normal and k:
        x = out[..., 0].astype(np.int32) - 128
        y = out[..., 1].astype(np.int32) - 128
        for _ in range(k):
            x, y = -y, x
        out[..., 0] = np.clip(x + 128, 0, 255)
        out[..., 1] = np.clip(y + 128, 0, 255)
    return out


def normal_strength(nrm: np.ndarray, k: float) -> np.ndarray:
    """Сила рельефа: наклон нормали ×k с перенормировкой (k<1 — спокойнее)."""
    v = nrm.astype(np.float64) / 127.5 - 1.0
    v[..., :2] *= k
    v /= np.maximum(np.linalg.norm(v, axis=-1, keepdims=True), 1e-6)
    return np.clip((v + 1.0) * 127.5, 0, 255).astype(np.uint8)


def roughness_map(rough: np.ndarray, spread: float) -> np.ndarray:
    """Шероховатость скана к среднему `ROUGH_MEAN` с разбросом ×spread (оттенки серого → три канала, three берёт зелёный)."""
    r = rough.astype(np.float64)
    if r.ndim == 3:
        r = r.mean(-1)
    rel = r / max(1.0, float(r.mean()))
    v = np.clip(ROUGH_MEAN * (1.0 + (rel - 1.0) * spread), 0.05, 1.0)
    g = (v * 255).astype(np.uint8)
    return np.stack([g, g, g], -1)


def _hex(rgb: np.ndarray) -> str:
    return "#%02x%02x%02x" % tuple(int(round(float(x))) for x in rgb)


def _rgb(hx: str) -> tuple[float, float, float]:
    return tuple(float(int(hx[i:i + 2], 16)) for i in (1, 3, 5))  # type: ignore[return-value]


def _load(path: str, size: int, mode: str = "RGB") -> np.ndarray:
    im = Image.open(path).convert(mode)
    if im.size != (size, size):
        im = im.resize((size, size), Image.LANCZOS)
    return np.asarray(im)


# ─────────────────────────────── выбор скана ───────────────────────────────


def load_config(path: str = CONFIG) -> dict:
    return json.load(open(path, encoding="utf-8"))


def floor_type(entry: dict) -> str | None:
    """Тип покрытия материала каталога: генератор его пресета. Только полы: материал, который бывает и на стене
    (плитка «пол + стена + фартук»), сканом пола не подменяем — на стене скан пола неуместен."""
    if entry["id"].startswith("scan-"):
        return None
    p = MP.PRESETS.get(entry["id"])
    if not p:
        return None                      # фото товара или застройщика — уже настоящая фактура
    surf = set(entry.get("surfaces") or p.get("surf") or [])
    if surf and surf != {"floor"}:
        return None
    return str(p["gen"])


def scan_plan(materials: list[dict], cfg: dict) -> list[tuple[dict, str, dict]]:
    """[(материал, тип, правило скана)] — что пересобрать. Тип без правила — процедурный запасной путь."""
    out = []
    for e in materials:
        t = floor_type(e)
        if t and t in cfg.get("types", {}):
            out.append((e, t, cfg["types"][t]))
    return out


def scan_files(ver: int, mid: str) -> dict[str, str]:
    stem = f"scan-{mid}-v{ver}"
    return {"baseColorUrl": f"{stem}.webp", "baseColorLiteUrl": f"{stem}-lite.webp", "normalUrl": f"{stem}-n.webp",
            "roughnessUrl": f"{stem}-r.webp", "previewUrl": f"{stem}-preview.webp"}


# ─────────────────────────────── команды ───────────────────────────────


def _get(url: str, timeout: int = 60) -> bytes:
    # API Poly Haven отвечает 403 запросу без имени клиента (urllib по умолчанию «Python-urllib»)
    req = urllib.request.Request(url, headers={"User-Agent": "remlab-material-from-scan/1.0 (+https://remont-lab.online)"})
    return urllib.request.urlopen(req, timeout=timeout).read()


def fetch(asset: str, scans_dir: str = SCANS) -> dict:
    """Скан Poly Haven → `data/flat3d/scans/<asset>/` (оригиналы 1k + source.json). Размер и авторы — из API источника."""
    if not asset.replace("_", "").isalnum():
        raise SystemExit(f"странное имя скана: {asset}")
    info = json.loads(_get(PH_INFO.format(a=asset), 30))
    dst = os.path.join(scans_dir, asset)
    os.makedirs(dst, exist_ok=True)
    files, sha = {}, {}
    for kind, name in KINDS.items():
        url = PH_FILE.format(a=asset, k=kind)
        data = _get(url)
        Image.open(__import__("io").BytesIO(data)).verify()   # только картинка: иначе отказ, файл не пишем
        open(os.path.join(dst, name), "wb").write(data)
        files[kind] = url
        sha[name] = hashlib.sha256(data).hexdigest()
    dims = [float(x) for x in info.get("dimensions", [])][:2]
    if len(dims) != 2 or min(dims) <= 0:
        raise SystemExit(f"{asset}: у источника нет физического размера — без него тайл «поплывёт»")
    rec = {
        "asset": asset,
        "title": str(info.get("name", asset)),
        "site": "Poly Haven",
        "pageUrl": f"https://polyhaven.com/a/{asset}",
        "files": files,
        "licence": "CC0-1.0",
        "licenceUrl": "https://polyhaven.com/license",
        "authors": {str(k): str(v) for k, v in (info.get("authors") or {}).items()},
        "realMm": [round(d, 1) for d in dims],
        "downloaded": _dt.date.today().isoformat(),
        "sha256": sha,
    }
    with open(os.path.join(dst, "source.json"), "w", encoding="utf-8") as fh:
        json.dump(rec, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return rec


def build_one(entry: dict, rule: dict, ver: int, *, scans_dir: str = SCANS, out_dir: str = OUT) -> dict:
    """Материал `scan-<id>`: скан типа, перекрашенный под цвет материала `id`, с физическим размером скана."""
    sdir = os.path.join(scans_dir, rule["scan"])
    src = json.load(open(os.path.join(sdir, "source.json"), encoding="utf-8"))
    deg = int(rule.get("rotate", 0))
    target = _rgb(entry["colorHex"])
    diff = rotate(_load(os.path.join(sdir, KINDS["diff"]), FULL), deg)
    col = tint(diff, target, contrast=float(rule.get("contrast", 0.8)), chroma=float(rule.get("chroma", 0.5)),
               flatten=float(rule.get("flatten", 0.8)))
    nrm = rotate(_load(os.path.join(sdir, KINDS["nor_gl"]), FULL), deg, normal=True)
    nrm = normal_strength(nrm, float(rule.get("normal", 1.0)))
    rgh = rotate(_load(os.path.join(sdir, KINDS["rough"]), LITE, "L"), deg)
    rgh = roughness_map(rgh, float(rule.get("roughSpread", 0.6)))

    files = scan_files(ver, entry["id"])
    os.makedirs(out_dir, exist_ok=True)
    w = lambda arr, name, q: Image.fromarray(arr).save(os.path.join(out_dir, name), quality=q, method=6)  # noqa: E731
    w(col, files["baseColorUrl"], 86)
    w(np.asarray(Image.fromarray(col).resize((LITE, LITE), Image.LANCZOS)), files["baseColorLiteUrl"], 84)
    w(nrm, files["normalUrl"], 86)
    w(rgh, files["roughnessUrl"], 80)
    w(np.asarray(Image.fromarray(col).resize((PREVIEW, PREVIEW), Image.LANCZOS)), files["previewUrl"], 82)

    mm = src["realMm"] if deg % 180 == 0 else src["realMm"][::-1]
    base_rough = float(entry.get("roughness", 0.55))
    authors = ", ".join(src.get("authors", {}))
    return {
        "id": f"scan-{entry['id']}",
        "titleRu": entry["titleRu"],
        "titleEn": entry["titleEn"],
        "colorHex": _hex(col.reshape(-1, 3).mean(0)),
        # карта шероховатости в среднем ROUGH_MEAN: так блеск в полном режиме тот же, что у процедурного образца
        "roughness": round(min(1.0, base_rough / ROUGH_MEAN), 3),
        "metalness": 0.0,
        "tileCm": [round(mm[0] / 10.0, 1), round(mm[1] / 10.0, 1)],
        **files,
        "surfaces": ["floor"],
        "source": {
            "kind": "photo-material",
            "sourceUrl": src["pageUrl"],
            "licence": src["licence"],
            "method": f"scan:{rule['scan']}@v{ver} tint→{entry['id']}",
            "note": f"{src['site']}: {src['title']} ({authors}); оттенок — под «{entry['titleRu']}»",
            "realCm": [round(mm[0] / 10.0, 1), round(mm[1] / 10.0, 1)],
        },
    }


def write_manifest(entries: list[dict], path: str = MANIFEST) -> int:
    payload = json.load(open(path, encoding="utf-8"))
    by_id = {m["id"]: m for m in payload.get("materials", [])}
    for e in entries:
        by_id[e["id"]] = e
    payload["materials"] = [by_id[k] for k in sorted(by_id)]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    return len(by_id)


def main() -> int:
    ap = argparse.ArgumentParser(description="пол из CC0-сканов (тип покрытия → скан → размер → оттенок)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="скачать скан Poly Haven в data/flat3d/scans/<asset>/")
    f.add_argument("--asset", required=True)
    b = sub.add_parser("build", help="пересобрать материалы scan-<id> по типам из data/flat3d/floor-scans.json")
    b.add_argument("--id", action="append", help="только эти материалы (можно несколько)")
    a = ap.parse_args()

    if a.cmd == "fetch":
        rec = fetch(a.asset)
        print(f"скан {rec['asset']}: {rec['realMm']} мм, {rec['licence']}, авторы {', '.join(rec['authors'])}")
        return 0

    cfg = load_config()
    ver = int(cfg.get("version", 1))
    mats = json.load(open(MANIFEST, encoding="utf-8"))["materials"]
    plan = [x for x in scan_plan(mats, cfg) if not a.id or x[0]["id"] in a.id]
    built, fails = [], 0
    for entry, t, rule in plan:
        try:
            e = build_one(entry, rule, ver)
            size = sum(os.path.getsize(os.path.join(OUT, e[k])) for k in scan_files(ver, entry["id"]))
            built.append(e)
            print(f"{e['id']}: тип {t} → {rule['scan']}, тайл {e['tileCm']} см, цвет {entry['colorHex']}→{e['colorHex']}, "
                  f"{size // 1024} КБ")
        except Exception as exc:  # noqa: BLE001 — счётчик отказов обязателен, молча не глотаем
            fails += 1
            print(f"ОШИБКА {entry['id']}: {exc}", file=sys.stderr)
    n = write_manifest(built) if built else 0
    print(f"готово: {len(built)}, отказов: {fails}; манифест — {n} материалов")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())

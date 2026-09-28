#!/usr/bin/env python3
"""Исходный GLB товара → лёгкая runtime-модель для браузера (план apartment-3d-configurator).

ЧТО ЛЕЧИМ (замер 28.09 по 330 моделям галереи):
  * текстуры 2048² лежат base64 ВНУТРИ JSON-чанка → +18 % веса и разбор мегабайтного JSON
    до первой геометрии; переносим в бинарный чанк;
  * две карты на модель, из них metallicRoughness (PNG) = 41 % веса галереи, а на сцене
    даёт почти ничего → выкидываем, ставим скалярные roughness/metalness по роли;
  * 2048² albedo = ~16 МБ видеопамяти на модель после распаковки (у 15 моделей — сотни
    мегабайт, телефон не переживёт) → 1024 для десктопа, 512 для мобильной версии.
Геометрию (40k треугольников) НЕ трогаем: она в GLB весит ~1 МБ и не является узким местом —
и это же защищает силуэт товара, ради которого модель и делалась.

Запуск:
    ~/venvs/scout/bin/python tools/assets/runtime_mesh.py --ids-from data/flat3d/furniture.json \
        --out ~/scout-scenes/flat3d-rt --size 1024 --quality 82
    (--size 512 --suffix -lite  — облегчённый набор для телефона)

Идемпотентно: готовая модель того же размера пропускается (--force для пересборки).
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import time
import urllib.request

from PIL import Image

SRC_BASE = "https://remont-lab.online/test/mesh-pilot10/"
CACHE = os.path.expanduser("~/scout-scenes/flat3d-src")
# gltfpack (meshoptimizer): квантование + сжатие геометрии и KTX2/BasisU для текстур.
# ВАЖНО: npm-сборка собрана БЕЗ BasisU — нужен НАТИВНЫЙ бинарь
# (github.com/zeux/meshoptimizer/releases, gltfpack-ubuntu.zip → ~/.local/bin/gltfpack).
GLTFPACK = os.environ.get("GLTFPACK", os.path.expanduser("~/.local/bin/gltfpack"))


def fetch_source(mesh_id: str) -> bytes:
    """Исходник берём из локальной галереи, иначе качаем с прода (и кэшируем)."""
    local = os.path.expanduser(f"~/scout-scenes/mesh-pilot-gallery/{mesh_id}/model.glb")
    if os.path.exists(local):
        return open(local, "rb").read()
    os.makedirs(CACHE, exist_ok=True)
    cached = os.path.join(CACHE, f"{mesh_id}.glb")
    if os.path.exists(cached) and os.path.getsize(cached) > 1024:
        return open(cached, "rb").read()
    url = f"{SRC_BASE}{mesh_id}/model.glb"
    with urllib.request.urlopen(url, timeout=120) as r:  # noqa: S310 — свой же прод
        data = r.read()
    with open(cached, "wb") as fh:
        fh.write(data)
    return data


def parse_glb(data: bytes) -> tuple[dict, bytes]:
    magic, _version, _length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError("не GLB")
    offset = 12
    js: dict | None = None
    bin_chunk = b""
    while offset < len(data):
        clen, ctype = struct.unpack_from("<II", data, offset)
        body = data[offset + 8 : offset + 8 + clen]
        if ctype == 0x4E4F534A:
            js = json.loads(body.decode("utf-8"))
        elif ctype == 0x004E4942:
            bin_chunk = body
        offset += 8 + clen + ((4 - clen % 4) % 4)
    if js is None:
        raise ValueError("в GLB нет JSON-чанка")
    return js, bin_chunk


def write_glb(js: dict, bin_chunk: bytes) -> bytes:
    js_bytes = json.dumps(js, separators=(",", ":")).encode("utf-8")
    js_pad = (4 - len(js_bytes) % 4) % 4
    js_bytes += b" " * js_pad
    bin_pad = (4 - len(bin_chunk) % 4) % 4
    bin_chunk = bin_chunk + b"\x00" * bin_pad
    total = 12 + 8 + len(js_bytes) + (8 + len(bin_chunk) if bin_chunk else 0)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, total)
    out += struct.pack("<II", len(js_bytes), 0x4E4F534A) + js_bytes
    if bin_chunk:
        out += struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk
    return bytes(out)


def image_bytes(img: dict, js: dict, bin_chunk: bytes) -> bytes | None:
    uri = img.get("uri")
    if uri and uri.startswith("data:"):
        return base64.b64decode(uri.split(",", 1)[1])
    if "bufferView" in img:
        bv = js["bufferViews"][img["bufferView"]]
        start = bv.get("byteOffset", 0)
        return bin_chunk[start : start + bv["byteLength"]]
    return None


def optimise(data: bytes, size: int, quality: int, drop_mr: bool = True) -> tuple[bytes, dict]:
    js, bin_chunk = parse_glb(data)
    images = js.get("images", [])
    materials = js.get("materials", [])

    keep_texture: set[int] = set()
    for m in materials:
        pbr = m.get("pbrMetallicRoughness", {})
        base = pbr.get("baseColorTexture")
        if base is not None:
            keep_texture.add(base["index"])
        if drop_mr and "metallicRoughnessTexture" in pbr:
            pbr.pop("metallicRoughnessTexture")
            # скалярные значения вместо карты: мебель почти никогда не металл
            pbr["metallicFactor"] = 0.0
            pbr.setdefault("roughnessFactor", 0.75)
        if drop_mr and "occlusionTexture" in m:
            m.pop("occlusionTexture")

    textures = js.get("textures", [])
    keep_images: set[int] = set()
    for ti in keep_texture:
        if ti < len(textures):
            src = textures[ti].get("source")
            if src is not None:
                keep_images.add(src)

    new_bin = bytearray(bin_chunk)
    stats = {"images_in": len(images), "images_out": 0, "px": 0}
    for idx, img in enumerate(images):
        if idx not in keep_images:
            img["uri"] = None
            continue
        raw = image_bytes(img, js, bin_chunk)
        if raw is None:
            continue
        pil = Image.open(io.BytesIO(raw)).convert("RGB")
        if max(pil.size) > size:
            pil = pil.resize((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=quality, optimize=True)
        payload = buf.getvalue()
        # кладём в бинарный чанк: base64 в JSON — это +33 % и разбор всего JSON до геометрии
        offset = len(new_bin)
        pad = (4 - offset % 4) % 4
        new_bin += b"\x00" * pad
        offset += pad
        new_bin += payload
        js.setdefault("bufferViews", []).append(
            {"buffer": 0, "byteOffset": offset, "byteLength": len(payload)}
        )
        img.pop("uri", None)
        img["bufferView"] = len(js["bufferViews"]) - 1
        img["mimeType"] = "image/jpeg"
        stats["images_out"] += 1
        stats["px"] = max(stats["px"], pil.size[0])

    # выкидываем изображения, на которые больше никто не смотрит
    if images:
        js["images"] = [im for i, im in enumerate(images) if i in keep_images]
        remap = {old: new for new, old in enumerate(sorted(keep_images))}
        for t in textures:
            if t.get("source") in remap:
                t["source"] = remap[t["source"]]
        js["textures"] = [t for t in textures if t.get("source") in remap.values()]

    if js.get("buffers"):
        js["buffers"][0]["byteLength"] = len(new_bin)
        js["buffers"][0].pop("uri", None)
    accessors = js.get("accessors", [])
    tri = 0
    for mesh in js.get("meshes", []):
        for prim in mesh.get("primitives", []):
            acc = prim.get("indices")
            if isinstance(acc, int) and acc < len(accessors):
                tri += int(accessors[acc].get("count", 0)) // 3
    stats["triangles"] = tri
    return write_glb(js, bytes(new_bin)), stats


def pack(src_path: str, dst_path: str, simplify: float = 0.0, ktx2: bool = True) -> tuple[bool, str]:
    """Сжатие геометрии (meshopt) и текстур (KTX2). Нет бинаря — честно говорим и не падаем."""
    exe = GLTFPACK if os.path.exists(GLTFPACK) else shutil.which("gltfpack")
    if not exe:
        return False, "gltfpack не найден — модель осталась без сжатия геометрии"
    cmd = [exe, "-i", src_path, "-o", dst_path, "-cc"]
    if ktx2:
        cmd.append("-tc")
    if simplify > 0:
        cmd += ["-si", str(simplify)]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return False, "gltfpack не уложился в 600 с"
    if res.returncode != 0 or not os.path.exists(dst_path):
        msg = (res.stderr or res.stdout or "").strip().splitlines()
        return False, msg[-1] if msg else f"gltfpack вернул {res.returncode}"
    return True, ""


def mesh_ids_from(path: str) -> list[str]:
    payload = json.load(open(path, encoding="utf-8"))
    ids: list[str] = []
    for o in payload.get("options", []):
        asset = o.get("asset") or {}
        if asset.get("kind") == "mesh" and asset.get("meshId"):
            ids.append(asset["meshId"])
    return sorted(set(ids))


def main() -> int:
    ap = argparse.ArgumentParser(description="лёгкие runtime-модели для 3D-конфигуратора")
    ap.add_argument("--ids-from", default="data/flat3d/furniture.json")
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--out", default=os.path.expanduser("~/scout-scenes/flat3d-rt"))
    ap.add_argument("--size", type=int, default=1024)
    ap.add_argument("--quality", type=int, default=82)
    ap.add_argument("--suffix", default="")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--manifest", default="data/flat3d/runtime-meshes.json")
    ap.add_argument("--simplify", type=float, default=0.0, help="доля оставляемых треугольников, напр. 0.6")
    ap.add_argument("--no-ktx2", action="store_true", help="оставить JPEG вместо KTX2")
    a = ap.parse_args()

    ids = a.id or mesh_ids_from(a.ids_from)
    os.makedirs(a.out, exist_ok=True)
    manifest: dict[str, dict] = {}
    if os.path.exists(a.manifest):
        try:
            manifest = json.load(open(a.manifest, encoding="utf-8")).get("meshes", {})
        except Exception:  # noqa: BLE001
            manifest = {}

    ok = fail = skip = 0
    t0 = time.time()
    for i, mid in enumerate(ids, 1):
        dst = os.path.join(a.out, f"{mid}{a.suffix}.glb")
        if os.path.exists(dst) and not a.force:
            skip += 1
            continue
        try:
            src = fetch_source(mid)
            out, stats = optimise(src, a.size, a.quality)
            # gltfpack узнаёт формат ПО РАСШИРЕНИЮ, поэтому промежуточный файл тоже .glb
            tmp = dst[:-4] + ".src.glb"
            with open(tmp, "wb") as fh:
                fh.write(out)
            packed, why = pack(tmp, dst, a.simplify, not a.no_ktx2)
            if not packed:
                os.replace(tmp, dst)  # без сжатия геометрии, но рабочая модель
                if i == 1:
                    print(f"внимание: {why}", file=sys.stderr)
            else:
                os.remove(tmp)
            size = os.path.getsize(dst)
            entry = manifest.get(mid, {})
            entry[f"size{a.suffix or ''}"] = size
            entry["source_bytes"] = len(src)
            entry[f"texture_px{a.suffix or ''}"] = stats["px"]
            entry["triangles"] = stats["triangles"]
            entry["packed"] = packed
            manifest[mid] = entry
            ok += 1
            print(f"[{i}/{len(ids)}] {mid}: {len(src)/1e6:.2f} → {size/1e6:.2f} МБ")
        except Exception as exc:  # noqa: BLE001 — счётчик отказов обязателен, молчать нельзя
            fail += 1
            print(f"[{i}/{len(ids)}] {mid}: ОШИБКА {exc}", file=sys.stderr)

    os.makedirs(os.path.dirname(os.path.abspath(a.manifest)), exist_ok=True)
    with open(a.manifest, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "_about": "Вес runtime-моделей. Собрано tools/assets/runtime_mesh.py.",
                "baseUrl": "/rt/",
                "meshes": manifest,
            },
            fh,
            ensure_ascii=False,
            indent=1,
        )
        fh.write("\n")
    total_src = sum(m.get("source_bytes", 0) for m in manifest.values())
    total_out = sum(m.get("size", 0) for m in manifest.values())
    print(
        f"\nготово: {ok}, пропущено: {skip}, отказов: {fail}, {time.time()-t0:.0f} с\n"
        f"вес: {total_src/1e6:.0f} → {total_out/1e6:.0f} МБ"
    )
    return 1 if fail and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())

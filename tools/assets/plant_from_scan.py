#!/usr/bin/env python3
"""Растения-декор из CC0-сканов Poly Haven для кашпо и ваз 3D /demo (T-20261117-07, владелец TG 1307).

ЗАЧЕМ. Кашпо и вазы в /demo — модели товаров, и стоят пустыми. Универсальное растение в горле носителя делает комнату живой, не
превращаясь в товар (нет цены, строки списка, замены). Сопоставление — по ТИПУ носителя и размеру горла, не по номерам товаров
(`data/flat3d/plants.json`: `hosts`, `fit`).

Что делает:
    fetch  — скачать пакеты glTF 1k (лицензия CC0) в `~/scout-scenes/plants-src/<asset>/` и записать реестр источника
             `data/flat3d/plants/<asset>/source.json` (сайт, ссылка, авторы, лицензия, дата, sha256) — как у сканов пола;
    build  — из пакета взять ОДНО растение (`part` — имя геометрии; пакеты Poly Haven — «сцены» из нескольких растений), поставить
             прямо (по главной оси: ветки лежат), низ — в ноль, центр основания — на ось; цвет 512² (JPEG), без карт нормалей и
             шероховатости (скаляр) — телефону; упаковать gltfpack (-cc); проверить бюджет (`limits`: треугольники, байты);
             положить `public/flat3d/plants/<id>.glb` и список `public/flat3d/plants/manifest.json`.

Запуск (venv проекта, из корня репо):
    ~/venvs/scout/bin/python tools/assets/plant_from_scan.py fetch
    ~/venvs/scout/bin/python tools/assets/plant_from_scan.py build [--id calathea]
Скачанное — данные, код из него не исполняется.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import hashlib
import io
import json
import re
import os
import subprocess
import sys
import urllib.request

import numpy as np
import trimesh
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
CONFIG = os.path.join(ROOT, "data", "flat3d", "plants.json")
SOURCES = os.path.join(ROOT, "data", "flat3d", "plants")
OUT = os.path.join(ROOT, "public", "flat3d", "plants")
CACHE = os.path.expanduser("~/scout-scenes/plants-src")
GLTFPACK = os.environ.get("GLTFPACK", os.path.expanduser("~/.local/bin/gltfpack"))
TEX = 512


def load_config() -> dict:
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "remlab-plants"})
    return urllib.request.urlopen(req, timeout=120).read()


def fetch(asset: str) -> None:
    """Пакет glTF 1k модели Poly Haven → кэш и реестр источника."""
    info = json.loads(_get(f"https://api.polyhaven.com/info/{asset}"))
    files = json.loads(_get(f"https://api.polyhaven.com/files/{asset}"))["gltf"]["1k"]["gltf"]
    d = os.path.join(CACHE, asset)
    os.makedirs(d, exist_ok=True)
    sha: dict[str, str] = {}
    main = os.path.join(d, os.path.basename(files["url"]))
    blobs = [(main, files["url"])] + [(os.path.join(d, rel), inc["url"]) for rel, inc in files.get("include", {}).items()]
    for path, url in blobs:
        data = _get(url)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        sha[os.path.relpath(path, d)] = hashlib.sha256(data).hexdigest()
    os.makedirs(os.path.join(SOURCES, asset), exist_ok=True)
    with open(os.path.join(SOURCES, asset, "source.json"), "w", encoding="utf-8") as f:
        json.dump({"asset": asset, "title": info.get("name"), "site": "Poly Haven", "pageUrl": f"https://polyhaven.com/a/{asset}",
                   "licence": "CC0-1.0", "licenceUrl": "https://polyhaven.com/license", "authors": info.get("authors"),
                   "realMm": info.get("dimensions"), "downloaded": _dt.date.today().isoformat(), "sha256": sha},
                  f, ensure_ascii=False, indent=1)
        f.write("\n")
    print(f"fetch {asset}: {len(blobs)} файлов, {sum(os.path.getsize(p) for p, _ in blobs) // 1024} КБ")


def _part(asset: str, part: str):
    """Геометрия `part` пакета с применёнными преобразованиями узла (метры, Y вверх) и её цветовая карта (PIL)."""
    gltf = glob.glob(os.path.join(CACHE, asset, "*.gltf"))[0]
    sc = trimesh.load(gltf, force="scene")
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        if gname == part:
            g = sc.geometry[gname].copy()
            g.apply_transform(T)
            mat = g.visual.material
            tex = getattr(mat, "baseColorTexture", None)
            if tex is None:
                raise SystemExit(f"{asset}/{part}: нет цветовой карты")
            return g, tex.convert("RGB"), g.visual.uv.copy()
    raise SystemExit(f"{asset}: нет геометрии «{part}» (есть: {', '.join(sc.geometry)})")


def stand_up(v: np.ndarray) -> np.ndarray:
    """Вершины (N,3), Y вверх → растение стоит: главная ось вытянутой формы — вертикаль (ветка лежала), низ — тот конец, где площадь
    сечения меньше (стебель; крона — шире); низ в ноль, центр основания (нижние 8 %) — на ось. Приземистая форма (листва) — как есть."""
    c = v - v.mean(axis=0)
    w, vec = np.linalg.eigh(np.cov(c.T))
    axis = vec[:, -1]
    if w[-1] > 2.2 * w[-2]:                       # вытянутая: PCA-ось → вертикаль
        up = axis if axis[1] >= 0 else -axis
        helper = np.array([1.0, 0, 0]) if abs(up[0]) < 0.9 else np.array([0, 0, 1.0])
        x = np.cross(helper, up); x /= np.linalg.norm(x)
        z = np.cross(up, x)
        v = np.stack([c @ x, c @ up, c @ z], axis=1)
        t = (v[:, 1] - v[:, 1].min()) / max(float(np.ptp(v[:, 1])), 1e-9)
        lo, hi = v[t < 0.15], v[t > 0.85]
        spread = lambda a: float(np.ptp(a[:, 0]) * np.ptp(a[:, 2])) if len(a) > 3 else 0.0   # noqa: E731
        if spread(lo) > spread(hi):               # шире внизу → перевернуть: низ — тонкий конец
            v[:, 1] = -v[:, 1]
            v[:, 0] = -v[:, 0]
    else:
        v = v.copy()
    v[:, 1] -= v[:, 1].min()
    base = v[v[:, 1] <= max(0.08 * float(v[:, 1].max()), 1e-4)]
    v[:, 0] -= float(base[:, 0].mean())
    v[:, 2] -= float(base[:, 2].mean())
    return v


def build_one(p: dict, limits: dict) -> dict:
    """Растение = одна геометрия (`part`) или несколько (`parts`: листья + стебли/ствол; у каждой своя цветовая карта).
    `stand: false` — модель уже стоит прямо (не выпрямлять по главной оси; низ в ноль и основание на ось — всегда);
    `decimate: R` — оставить долю R треугольников (gltfpack -si, с учётом разверток; листья Poly Haven бывают по 100 тыс.)."""
    names = p.get("parts") or [p["part"]]
    loaded = [_part(p["asset"], n) for n in names]
    allv = np.concatenate([np.asarray(g.vertices, dtype=np.float64) for g, _, _ in loaded])
    if p.get("stand", True):
        allv = stand_up(allv)
    else:
        allv = allv.copy()
        allv[:, 1] -= allv[:, 1].min()
        base = allv[allv[:, 1] <= max(0.08 * float(allv[:, 1].max()), 1e-4)]
        allv[:, 0] -= float(base[:, 0].mean())
        allv[:, 2] -= float(base[:, 2].mean())
    scene = trimesh.Scene()
    mats: dict[int, trimesh.visual.material.PBRMaterial] = {}
    at = 0
    for i, (g, tex, uv) in enumerate(loaded):
        n = len(g.vertices)
        if id(tex) not in mats:
            img = tex.resize((TEX, TEX), Image.LANCZOS)
            mats[id(tex)] = trimesh.visual.material.PBRMaterial(baseColorTexture=img, metallicFactor=0.0, roughnessFactor=0.85,
                                                               doubleSided=True, alphaMode="OPAQUE")
        scene.add_geometry(trimesh.Trimesh(vertices=allv[at:at + n], faces=g.faces,
                                           visual=trimesh.visual.TextureVisuals(uv=uv, material=mats[id(tex)]), process=False),
                           geom_name=f"p{i}")
        at += n
    v = allv
    tmp = os.path.join(CACHE, f"_build-{p['id']}.glb")
    scene.export(tmp, file_type="glb")
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"{p['id']}.glb")
    cmd = [GLTFPACK, "-i", tmp, "-o", dst, "-cc", "-v"]
    if p.get("decimate"):
        cmd += ["-si", str(p["decimate"]), "-sv", "-se", "0.05"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if res.returncode:
        raise SystemExit(f"{p['id']}: gltfpack: {(res.stderr or res.stdout).strip()[-200:]}")
    os.unlink(tmp)
    size = os.path.getsize(dst)
    m = re.search(r"output: \d+ mesh primitives \((\d+) triangles", res.stdout + res.stderr)
    tris = int(m.group(1)) if m else sum(len(g.faces) for g, _, _ in loaded)
    if tris > limits["maxTris"] or size > limits["maxBytes"]:
        raise SystemExit(f"{p['id']}: бюджет превышен — {tris} треугольников (≤ {limits['maxTris']}), {size} байт (≤ {limits['maxBytes']})")
    ext = (v.max(axis=0) - v.min(axis=0)) * 100
    return {"id": p["id"], "asset": p["asset"], "part": p.get("part") or ",".join(names), "kind": p["kind"], "tris": tris, "bytes": size,
            "sha256": hashlib.sha256(open(dst, "rb").read()).hexdigest(), "sizeCm": [round(float(x), 1) for x in ext]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["fetch", "build"])
    ap.add_argument("--id", help="только это растение")
    a = ap.parse_args()
    cfg = load_config()
    plants = [p for p in cfg["plants"] if not a.id or p["id"] == a.id]
    if not plants:
        raise SystemExit(f"нет растения {a.id}")
    if a.cmd == "fetch":
        for asset in sorted({p["asset"] for p in plants if p.get("builder") != "procedural"}):
            fetch(asset)
        return 0
    import plant_procedural as PP                 # букеты, собранные кодом (эвкалипт, олива, пампас, лаванда) — тот же список и бюджет

    rows = [(PP.build_one if p.get("builder") == "procedural" else build_one)(p, cfg["limits"]) for p in plants]
    for r in rows:
        print(f"{r['id']:16s} {r['kind']:5s} {r['tris']:6d} треуг. {r['bytes'] // 1024:5d} КБ  {r['sizeCm']} см")
    if not a.id:
        with open(os.path.join(OUT, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({"rev": cfg["rev"], "plants": rows}, f, ensure_ascii=False, indent=1)
            f.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

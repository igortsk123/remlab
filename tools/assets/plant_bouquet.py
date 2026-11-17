#!/usr/bin/env python3
"""Букет в вазу из НАСТОЯЩИХ листьев CC0-скана Poly Haven на стеблях (T-20261117-15, владелец: процедурный эвкалипт «нереалистичный»).

ЗАЧЕМ. Процедурные букеты (`plant_procedural.py`) читались искусственно: листья — плоская палитра, а не фото. Срезанных веток-сканов
в CC0 нет (Poly Haven, ambientCG, Smithsonian — проверено 17.11), но у сканов комнатных растений каждый лист — отдельный остров
геометрии со своей развёрткой по фото. Берём такие листья как есть (форма и текстура — скан), стебли — тонкие трубки нашего кода
(CC0-1.0, автор remlab); листья расставляются веером из горла вазы по правилам из `data/flat3d/plants.json` (`bouquet`), без ручной правки меша.

КАК. Остров геометрии `part` (связная область граней) → лист; его конец «низ» — самая низкая точка острова (черешок). Лист
поворачивается так, чтобы ось «черешок → кончик» продолжала стебель с провисом наружу; масштаб листа — из правил. Стебель — дуга
из горла (0,0,0) к черешку. Два материала: лист (цветовая карта скана 512², JPEG) и стебель (цвет-скаляр). Бюджет — `limits` плана.

Запуск (проверка одного букета, венв проекта): `~/venvs/scout/bin/python tools/assets/plant_bouquet.py <id>`.
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

import numpy as np
import trimesh
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.path.join(ROOT, "public", "flat3d", "plants")
GLTFPACK = os.environ.get("GLTFPACK", os.path.expanduser("~/.local/bin/gltfpack"))
TEX = 512
UP = np.array([0.0, 1.0, 0.0])


def leaf_islands(asset: str, part: str):
    """Острова геометрии `part` (по убыванию числа граней): [(вершины (N,3) м, грани (M,3), uv (N,2))] и цветовая карта (PIL)."""
    import plant_from_scan as PS
    g, tex, uv = PS._part(asset, part)
    comps = trimesh.graph.connected_components(g.face_adjacency, nodes=np.arange(len(g.faces)))
    comps = sorted((np.array(sorted(c)) for c in comps), key=lambda c: -len(c))
    out = []
    for fi in comps:
        f = g.faces[fi]
        ids = np.unique(f)
        remap = np.full(len(g.vertices), -1)
        remap[ids] = np.arange(len(ids))
        out.append((np.asarray(g.vertices)[ids].astype(np.float64), remap[f], np.asarray(uv)[ids]))
    return out, tex


def rot_to(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Поворот 3×3, переводящий единичный вектор a в b (Родриг; зеркальный случай — вокруг любой перпендикулярной оси)."""
    a, b = a / np.linalg.norm(a), b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        ax = np.cross(a, [1.0, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 0, 1.0])
        ax /= np.linalg.norm(ax)
        return 2 * np.outer(ax, ax) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k * (1.0 / (1.0 + c))


def tube(path: np.ndarray, radii: np.ndarray, sides: int = 6):
    """Трубка по дуге: кольца вершин вокруг каждой точки пути, боковые грани; торцы закрыты веером (стебель виден только сбоку)."""
    n = len(path)
    ring = np.stack([np.cos(np.linspace(0, 2 * np.pi, sides, endpoint=False)), np.sin(np.linspace(0, 2 * np.pi, sides, endpoint=False))], 1)
    verts, faces = [], []
    prev = np.array([1.0, 0, 0])
    for i in range(n):
        t = path[min(i + 1, n - 1)] - path[max(i - 1, 0)]
        t /= np.linalg.norm(t)
        x = np.cross(prev, t)
        x = np.cross(t, x) if np.linalg.norm(x) > 1e-9 else np.cross(t, [0, 0, 1.0])
        x /= np.linalg.norm(x)
        z = np.cross(t, x)
        prev = x
        for r in ring:
            verts.append(path[i] + radii[i] * (r[0] * x + r[1] * z))
    for i in range(n - 1):
        for j in range(sides):
            a, b = i * sides + j, i * sides + (j + 1) % sides
            c, d = (i + 1) * sides + j, (i + 1) * sides + (j + 1) % sides
            faces += [[a, c, b], [b, c, d]]
    return np.array(verts), np.array(faces)


def build_one(p: dict, limits: dict) -> dict:
    """Букет из листьев скана: `p['bouquet']` — правила веера (`leaves` — номера островов по убыванию размера, `stemCm`, `leanDeg`,
    `scale`, `droopDeg`, `stemRadiusCm`, `stemRgb`, `seed`); результат — `public/flat3d/plants/<id>.glb` (метры, Y вверх, горло — в нуле)."""
    b = p["bouquet"]
    isl, tex = leaf_islands(p["asset"], p["part"])
    rng = np.random.default_rng(int(b.get("seed", 1)))
    n = len(b["leaves"])
    leaf_v, leaf_f, leaf_uv, stem_v, stem_f = [], [], [], [], []
    for k, idx in enumerate(b["leaves"]):
        v, f, uv = (a.copy() if isinstance(a, np.ndarray) else a for a in isl[idx])
        low = v[np.argmin(v[:, 1])]                                    # черешок — низ острова
        v = v - low
        tip = v[np.argmax(np.linalg.norm(v, axis=1))]                  # кончик — дальняя точка от черешка
        az = (k * 137.5 + float(b.get("azimuthDeg", 0))) % 360 * np.pi / 180
        lean = np.radians(float(b["leanDeg"][k % len(b["leanDeg"])]) + rng.uniform(-3, 3))
        L = float(b["stemCm"][k % len(b["stemCm"])]) / 100
        d = np.array([np.sin(lean) * np.cos(az), np.cos(lean), np.sin(lean) * np.sin(az)])        # куда смотрит стебель
        top = d * L
        # лист продолжает стебель, но провисает наружу (droop): направление листа — стебель, повёрнутый к горизонтали
        out = np.array([np.cos(az), 0.0, np.sin(az)])
        droop = np.radians(float(b.get("droopDeg", 20)) * rng.uniform(0.6, 1.2))
        ld = d * np.cos(droop) + out * np.sin(droop)
        v = (rot_to(tip / np.linalg.norm(tip), ld) @ v.T).T * float(b["scale"][k % len(b["scale"])])
        # поворот листа вокруг его оси — чтобы лицо листа смотрело наружу веера, а не в бок
        spin = rng.uniform(-0.5, 0.5)
        ax = ld / np.linalg.norm(ld)
        K = np.array([[0, -ax[2], ax[1]], [ax[2], 0, -ax[0]], [-ax[1], ax[0], 0]])
        v = (np.eye(3) + np.sin(spin) * K + (1 - np.cos(spin)) * K @ K) @ v.T
        v = v.T + top
        leaf_v.append(v), leaf_f.append(f), leaf_uv.append(uv)
        # стебель: дуга от горла к черешку с лёгким изгибом наружу
        t = np.linspace(0, 1, 9)[:, None]
        bow = out * float(b.get("bowCm", 3)) / 100 * np.sin(np.pi * t)
        path = top[None, :] * t + bow
        path[-1] = top + ld * 0.01                                     # заходит в черешок на 1 см
        r0 = float(b.get("stemRadiusCm", 0.45)) / 100
        sv, sf = tube(path, np.linspace(r0, r0 * 0.7, len(path)))
        stem_v.append(sv), stem_f.append(sf)
    scene = trimesh.Scene()
    img = tex.resize((TEX, TEX), Image.LANCZOS)
    lm = trimesh.visual.material.PBRMaterial(baseColorTexture=img, metallicFactor=0.0, roughnessFactor=0.7, doubleSided=True)
    off = np.cumsum([0] + [len(x) for x in leaf_v])
    scene.add_geometry(trimesh.Trimesh(vertices=np.concatenate(leaf_v), faces=np.concatenate([f + o for f, o in zip(leaf_f, off)]),
                                       visual=trimesh.visual.TextureVisuals(uv=np.concatenate(leaf_uv), material=lm), process=False),
                       geom_name="leaves")
    so = np.cumsum([0] + [len(x) for x in stem_v])
    rgb = b.get("stemRgb", [58, 74, 40])
    sm = trimesh.visual.material.PBRMaterial(baseColorFactor=[*rgb, 255], metallicFactor=0.0, roughnessFactor=0.8, doubleSided=False)
    sv_all = np.concatenate(stem_v)
    scene.add_geometry(trimesh.Trimesh(vertices=sv_all, faces=np.concatenate([f + o for f, o in zip(stem_f, so)]),
                                       visual=trimesh.visual.TextureVisuals(uv=np.zeros((len(sv_all), 2)), material=sm), process=False),
                       geom_name="stems")
    tmp = os.path.join(os.path.expanduser("~/scout-scenes/plants-src"), f"_build-{p['id']}.glb")
    scene.export(tmp, file_type="glb")
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"{p['id']}.glb")
    res = subprocess.run([GLTFPACK, "-i", tmp, "-o", dst, "-cc", "-v"], capture_output=True, text=True, timeout=600)
    if res.returncode:
        raise SystemExit(f"{p['id']}: gltfpack: {(res.stderr or res.stdout).strip()[-200:]}")
    os.unlink(tmp)
    size = os.path.getsize(dst)
    m = re.search(r"output: \d+ mesh primitives \((\d+) triangles", res.stdout + res.stderr)
    tris = int(m.group(1)) if m else sum(len(f) for f in leaf_f) + sum(len(f) for f in stem_f)
    if tris > limits["maxTris"] or size > limits["maxBytes"]:
        raise SystemExit(f"{p['id']}: бюджет превышен — {tris} треугольников (≤ {limits['maxTris']}), {size} байт (≤ {limits['maxBytes']})")
    allv = np.concatenate(leaf_v + stem_v)
    ext = (allv.max(axis=0) - allv.min(axis=0)) * 100
    return {"id": p["id"], "asset": p["asset"], "part": p["part"], "kind": p["kind"], "tris": tris, "bytes": size,
            "sha256": hashlib.sha256(open(dst, "rb").read()).hexdigest(), "sizeCm": [round(float(x), 1) for x in ext]}


if __name__ == "__main__":
    import json
    sys.path.insert(0, HERE)
    cfg = json.load(open(os.path.join(ROOT, "data", "flat3d", "plants.json"), encoding="utf-8"))
    row = build_one(next(x for x in cfg["plants"] if x["id"] == sys.argv[1]), cfg["limits"])
    print(row)

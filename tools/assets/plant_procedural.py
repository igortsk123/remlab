#!/usr/bin/env python3
"""Букеты для ваз 3D /demo, собранные кодом (T-20261117-07/2): эвкалипт, оливковая ветка, пампасная трава, лаванда.

ЗАЧЕМ. В Poly Haven (CC0) нет ни эвкалипта, ни пампасной травы, ни лаванды, а у других CC0-источников (Quaternius, Kenney) нет
комнатных сухоцветов; CC-BY брать нельзя без «да» владельца. Поэтому эти четыре модели — НАШИ: листья, стебли и метёлки строит код
(`build()` ниже), автор — remlab, лицензия CC0-1.0 (автор отдаёт в общественное достояние). Сторонних файлов нет → атрибуции нет.

КАК. Всё в метрах, Y вверх, основание букета — в нуле на оси. Цвет — не фото: лента-палитра 256×128 (по строке на материал: стебель,
лист, цветок …), у каждой вершины развёртка указывает в нужную строку и точку градиента (темнее у основания, светлее к краю) — файл
весит несколько КБ. Листья — настоящая геометрия (форма листа, складка по жилке, провис), а не прозрачные карточки: тень и свет
считает движок как у остальных растений. Случайность — от зерна (`seed`): сборка воспроизводима, файл тот же при каждом запуске.
Бюджет — `limits` из `data/flat3d/plants.json` (проверяет `plant_from_scan.py`, куда `build_one` и подключён).

Запуск напрямую (проверка одного букета): `~/venvs/scout/bin/python tools/assets/plant_procedural.py euc`.
"""
from __future__ import annotations

import hashlib
import io
import json
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
SOURCES = os.path.join(ROOT, "data", "flat3d", "plants")
GLTFPACK = os.environ.get("GLTFPACK", os.path.expanduser("~/.local/bin/gltfpack"))

UP = np.array([0.0, 1.0, 0.0])

# Палитра: (темный конец, светлый конец) по строкам
ROWS = {
    "stem": ((62, 52, 34), (150, 128, 88)),
    "euc": ((78, 108, 98), (178, 202, 188)),
    "olive": ((84, 104, 66), (170, 186, 142)),
    "plume": ((196, 176, 146), (248, 238, 218)),
    "blade": ((176, 162, 112), (226, 212, 164)),
    "lav": ((96, 70, 142), (178, 148, 198)),
    "lavleaf": ((108, 124, 92), (164, 178, 138)),
}
ROW_NAMES = list(ROWS)
RAMP_W, ROW_H = 256, 16


def ramp_image() -> Image.Image:
    img = np.zeros((ROW_H * len(ROW_NAMES), RAMP_W, 3), dtype=np.uint8)
    for r, name in enumerate(ROW_NAMES):
        a, b = (np.array(c, dtype=float) for c in ROWS[name])
        t = np.linspace(0, 1, RAMP_W)[:, None]
        img[r * ROW_H:(r + 1) * ROW_H, :, :] = (a + (b - a) * t).astype(np.uint8)[None, :, :]
    return Image.fromarray(img, "RGB")


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def basis(d: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    d = unit(d)
    h = np.array([0.0, 0.0, 1.0]) if abs(d[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    a = unit(np.cross(h, d))
    return d, a, np.cross(d, a)


class Mesh:
    def __init__(self) -> None:
        self.v: list[np.ndarray] = []
        self.uv: list[tuple[float, float]] = []
        self.n: list[np.ndarray] = []
        self.f: list[tuple[int, int, int]] = []

    def vert(self, p: np.ndarray, row: str, u: float, n: np.ndarray | None = None) -> int:
        r = ROW_NAMES.index(row)
        self.v.append(np.asarray(p, dtype=float))
        self.n.append(unit(np.asarray(UP if n is None else n, dtype=float)))
        # трименш хранит развёртку «снизу вверх» и сам переворачивает при записи: v_файла = 1 − v
        self.uv.append((float(np.clip(u, 0.03, 0.97)), 1.0 - (r * ROW_H + ROW_H / 2) / (ROW_H * len(ROW_NAMES))))
        return len(self.v) - 1

    def tri(self, a: int, b: int, c: int) -> None:
        self.f.append((a, b, c))

    def orient(self) -> None:
        """Лицевая сторона каждого треугольника — та, куда смотрят нормали его вершин (двусторонний материал: с изнанки свет обратный)."""
        v, n = np.array(self.v), np.array(self.n)
        for k, (a, b, c) in enumerate(self.f):
            g = np.cross(v[b] - v[a], v[c] - v[a])
            if float(np.dot(g, n[a] + n[b] + n[c])) < 0:
                self.f[k] = (a, c, b)


def strip(m: Mesh, centre: list[np.ndarray], half: list[float], side: np.ndarray, row: str, u: list[float], lift: list[float] | None = None,
          soft: float = 0.5, tilt: float = 0.7) -> None:
    """Лента вдоль ломаной `centre`: на каждом шаге — левая/правая точки (± half по `side`), последний шаг может сужаться в точку.
    Нормали мягкие: смесь настоящей нормали ленты и «вверх» (`soft`) + наклон краёв наружу (`tilt`) — крона читается объёмом, не бумагой."""
    rows: list[tuple[int, ...]] = []
    for i, (p, h) in enumerate(zip(centre, half)):
        d = centre[min(i + 1, len(centre) - 1)] - centre[max(i - 1, 0)]
        n0 = unit(np.cross(d, side))
        if float(np.dot(n0, UP)) < 0:
            n0 = -n0
        nm = unit(n0 * (1 - soft) + UP * soft)
        if h < 1e-6:
            rows.append((m.vert(p, row, u[i], nm),))
        else:
            up_off = (lift[i] if lift else 0.0) * UP
            rows.append((m.vert(p - side * h + up_off, row, u[i] + 0.06, nm + side * tilt * 0.5),
                         m.vert(p, row, u[i] - 0.04, nm),
                         m.vert(p + side * h + up_off, row, u[i] + 0.06, nm - side * tilt * 0.5)))
    for a, b in zip(rows[:-1], rows[1:]):
        if len(a) == 3 and len(b) == 3:
            for k in range(2):
                m.tri(a[k], b[k], a[k + 1]); m.tri(a[k + 1], b[k], b[k + 1])
        elif len(a) == 3 and len(b) == 1:
            m.tri(a[0], b[0], a[1]); m.tri(a[1], b[0], a[2])
        elif len(a) == 1 and len(b) == 3:
            m.tri(a[0], b[1], b[0]); m.tri(a[0], b[2], b[1])


def leaf(m: Mesh, base: np.ndarray, fwd: np.ndarray, side: np.ndarray, length: float, width: float, row: str, *, round_: bool = False,
         fold: float = 0.3, droop: float = 0.25, tone: float = 0.5, nseg: int = 4) -> None:
    """Лист: настоящая форма (круглый или заострённый), складка вдоль жилки (`fold`), провис к кончику (`droop`)."""
    fwd = unit(fwd)
    side = unit(side - fwd * float(np.dot(side, fwd)))
    centre, half, u, lift = [], [], [], []
    for i in range(nseg + 1):
        t = i / nseg
        c = base + fwd * length * t - UP * droop * length * t * t
        if i == 0:
            hw = 0.0
        elif i == nseg:
            hw = 0.0
        elif round_:
            hw = 0.5 * width * float(np.sin(np.pi * t)) ** 0.5
        else:
            hw = 0.5 * width * float(np.sin(np.pi * t ** 0.8))
        centre.append(c); half.append(hw)
        u.append(tone - 0.2 + 0.4 * t)
        lift.append(fold * hw)
    strip(m, centre, half, side, row, u, lift)


def tube(m: Mesh, path: list[np.ndarray], radii: list[float], row: str, sides: int = 4, u0: float = 0.15, u1: float = 0.55) -> None:
    rings: list[list[int]] = []
    for i, (p, r) in enumerate(zip(path, radii)):
        t = path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]
        d, a, b = basis(t)
        u = u0 + (u1 - u0) * i / max(len(path) - 1, 1)
        rings.append([m.vert(p + (a * np.cos(2 * np.pi * k / sides) + b * np.sin(2 * np.pi * k / sides)) * r, row, u, a * np.cos(2 * np.pi * k / sides) + b * np.sin(2 * np.pi * k / sides)) for k in range(sides)])
    for r0, r1 in zip(rings[:-1], rings[1:]):
        for k in range(sides):
            k2 = (k + 1) % sides
            m.tri(r0[k], r1[k], r0[k2]); m.tri(r0[k2], r1[k], r1[k2])


def stem_path(rng: np.random.Generator, length: float, lean_deg: float, azimuth: float, bow: float, base: np.ndarray, n: int = 8) -> list[np.ndarray]:
    """Стебель: из основания вверх, с наклоном `lean_deg` к `azimuth` и мягким изгибом (`bow` — прогиб кончика в долях длины)."""
    lean = np.radians(lean_deg)
    d = np.array([np.sin(lean) * np.cos(azimuth), np.cos(lean), np.sin(lean) * np.sin(azimuth)])
    out_dir = unit(np.array([d[0], 0.0, d[2]]) + 1e-9)
    pts = []
    for i in range(n + 1):
        t = i / n
        pts.append(base + d * length * t + out_dir * bow * length * t * t)
    return pts


def at(path: list[np.ndarray], t: float) -> tuple[np.ndarray, np.ndarray]:
    """Точка и направление на ломаной по доле длины."""
    x = t * (len(path) - 1)
    i = min(int(x), len(path) - 2)
    f = x - i
    return path[i] + (path[i + 1] - path[i]) * f, unit(path[i + 1] - path[i])


def eucalyptus(rng: np.random.Generator) -> Mesh:
    """Эвкалипт «серебряный доллар»: пучок стеблей, пары круглых серо-зелёных листьев (пара поворачивается на 90°), к кончику мельче."""
    m = Mesh()
    for k in range(8):
        az = rng.uniform(0, 2 * np.pi)
        base = np.array([rng.uniform(-0.012, 0.012), 0.0, rng.uniform(-0.012, 0.012)])
        length = rng.uniform(0.55, 0.78)
        path = stem_path(rng, length, rng.uniform(4, 22), az, rng.uniform(0.04, 0.12), base)
        tube(m, path, [0.0032 - 0.0022 * i / 8 for i in range(9)], "stem")
        nodes = 21
        for j in range(nodes):
            t = 0.2 + 0.8 * j / (nodes - 1)
            p, d = at(path, t)
            size = 0.072 - 0.040 * ((t - 0.2) / 0.8) ** 0.9
            ang = j * np.pi / 2 + rng.uniform(-0.2, 0.2)
            _, a, b = basis(d)
            for s in (1, -1):
                radial = (a * np.cos(ang) + b * np.sin(ang)) * s
                fwd = unit(radial * np.cos(np.radians(28)) + d * np.sin(np.radians(28)))
                side = np.cross(fwd, d)
                leaf(m, p, fwd, side, size * rng.uniform(0.9, 1.1), size * rng.uniform(0.92, 1.05), "euc", round_=True, fold=0.5, droop=0.22, nseg=6,
                     tone=rng.uniform(0.15, 0.85))
        # верхушка — пара мелких листьев
        p, d = at(path, 1.0)
        for s in (1, -1):
            fwd = unit(d + s * 0.55 * basis(d)[1])
            leaf(m, p, fwd, np.cross(fwd, d), 0.02, 0.02, "euc", round_=True, fold=0.3, droop=0.1, tone=0.8, nseg=3)
    return m


def olive(rng: np.random.Generator) -> Mesh:
    """Оливковая ветка: тонкие стебли, узкие заострённые серо-оливковые листья парами, чуть вверх от стебля."""
    m = Mesh()
    for k in range(6):
        az = rng.uniform(0, 2 * np.pi)
        base = np.array([rng.uniform(-0.01, 0.01), 0.0, rng.uniform(-0.01, 0.01)])
        length = rng.uniform(0.6, 0.85)
        path = stem_path(rng, length, rng.uniform(4, 20), az, rng.uniform(0.05, 0.14), base)
        tube(m, path, [0.0028 - 0.0019 * i / 8 for i in range(9)], "stem")
        nodes = 30
        for j in range(nodes):
            t = 0.16 + 0.84 * j / (nodes - 1)
            p, d = at(path, t)
            size = 0.080 - 0.032 * ((t - 0.16) / 0.84)
            ang = j * np.pi / 2 + rng.uniform(-0.25, 0.25)
            _, a, b = basis(d)
            for s in (1, -1):
                radial = (a * np.cos(ang) + b * np.sin(ang)) * s
                fwd = unit(radial * np.cos(np.radians(38)) + d * np.sin(np.radians(38)))
                side = np.cross(fwd, d)
                leaf(m, p, fwd, side, size * rng.uniform(0.9, 1.15), size * 0.26, "olive", fold=0.4, droop=0.22, tone=rng.uniform(0.3, 0.75), nseg=5)
        p, d = at(path, 1.0)
        leaf(m, p, d, basis(d)[1], 0.03, 0.006, "olive", fold=0.3, droop=0.1, tone=0.8, nseg=3)
    return m


def pampas(rng: np.random.Generator) -> Mesh:
    """Пампасная трава: сухие дуги-листья пучком и 7 метёлок на тонких стеблях (кремовые перья расходятся от оси и чуть поникают)."""
    m = Mesh()
    for _ in range(22):                                        # листья-ленты
        az = rng.uniform(0, 2 * np.pi)
        length = rng.uniform(0.5, 0.8)
        base = np.array([rng.uniform(-0.01, 0.01), 0.0, rng.uniform(-0.01, 0.01)])
        path = stem_path(rng, length, rng.uniform(2, 11), az, rng.uniform(0.08, 0.2), base, n=7)
        d0, side, _ = basis(path[-1] - path[0])
        hw = [0.010 * (1 - 0.82 * (i / 7) ** 1.3) for i in range(8)]
        hw[-1] = 0.0
        strip(m, path, hw, unit(np.cross(path[-1] - path[0], UP)), "blade", [0.2 + 0.5 * i / 7 + rng.uniform(-0.05, 0.05) for i in range(8)], soft=0.2)
    for k in range(7):                                         # метёлки
        az = rng.uniform(0, 2 * np.pi)
        length = rng.uniform(0.62, 0.92)
        base = np.array([rng.uniform(-0.012, 0.012), 0.0, rng.uniform(-0.012, 0.012)])
        path = stem_path(rng, length, rng.uniform(2, 13), az, rng.uniform(0.04, 0.1), base, n=8)
        tube(m, path, [0.0022 - 0.0010 * i / 8 for i in range(9)], "stem", sides=3)
        plume_len = rng.uniform(0.26, 0.34)
        # тело метёлки — пушистое «веретено» (кольца вдоль стебля, радиус бочкой, шероховатость ±30 %): держит силуэт и мягкий свет;
        # перья ниже — лёгкая бахрома по краю
        rings: list[list[int]] = []
        for q in range(9):
            tq = 1.0 - plume_len / length * (1.0 - q / 8)
            p, d = at(path, tq)
            _, a, b = basis(d)
            rad = 0.0105 * float(np.sin(np.pi * min(max((q + 0.6) / 9.6, 0), 1))) ** 0.8 + 0.002
            rings.append([m.vert(p + (a * np.cos(2 * np.pi * k / 7) + b * np.sin(2 * np.pi * k / 7)) * rad * rng.uniform(0.75, 1.25), "plume",
                                 0.55 + 0.4 * float(np.sin(np.pi * q / 8)) + rng.uniform(-0.08, 0.08),
                                 a * np.cos(2 * np.pi * k / 7) + b * np.sin(2 * np.pi * k / 7) + 0.4 * UP) for k in range(7)])
        for r0, r1 in zip(rings[:-1], rings[1:]):
            for k in range(7):
                k2 = (k + 1) % 7
                m.tri(r0[k], r1[k], r0[k2]); m.tri(r0[k2], r1[k], r1[k2])
        for j in range(135):
            t = 1.0 - plume_len / length * rng.uniform(0.0, 1.0) ** 0.85
            p, d = at(path, t)
            frac = (1.0 - t) / (plume_len / length)               # 0 у кончика → 1 у нижнего края метёлки
            reach = 0.075 * np.sin(np.pi * min(max(0.25 + 0.7 * frac, 0), 1)) + 0.012   # бочкой: шире в середине
            ang = rng.uniform(0, 2 * np.pi)
            _, a, b = basis(d)
            radial = a * np.cos(ang) + b * np.sin(ang)
            pitch = np.radians(rng.uniform(14, 34))
            fwd = unit(radial * np.cos(pitch) + d * np.sin(pitch))
            n = 4
            pts = [p + fwd * (reach * 1.35) * (i / n) - UP * 0.35 * reach * (i / n) ** 2 for i in range(n + 1)]
            hw = [0.0085 * (1 - (i / n) ** 0.9) for i in range(n + 1)]
            hw[-1] = 0.0
            strip(m, pts, hw, unit(np.cross(fwd, UP) + 1e-9), "plume", [0.35 + 0.55 * (i / n) + rng.uniform(-0.1, 0.1) for i in range(n + 1)], soft=0.3, tilt=0.2)
    return m


def lavender(rng: np.random.Generator) -> Mesh:
    """Лаванда: пучок тонких стеблей с колосом из мелких пурпурных бутонов на верхней пятой; у основания — пара узких листьев."""
    m = Mesh()
    for k in range(24):
        az = rng.uniform(0, 2 * np.pi)
        base = np.array([rng.uniform(-0.012, 0.012), 0.0, rng.uniform(-0.012, 0.012)])
        length = rng.uniform(0.42, 0.58)
        path = stem_path(rng, length, rng.uniform(2, 11), az, rng.uniform(0.03, 0.09), base, n=6)
        tube(m, path, [0.0013 - 0.0004 * i / 6 for i in range(7)], "lavleaf", sides=3)
        for j in range(2):
            lf_az = rng.uniform(0, 2 * np.pi)
            fwd = unit(np.array([np.cos(lf_az) * 0.5, 0.65, np.sin(lf_az) * 0.5]))
            leaf(m, base + np.array([0, 0.01, 0]), fwd, unit(np.cross(fwd, UP) + 1e-9), rng.uniform(0.08, 0.14), 0.004, "lavleaf", fold=0.3, droop=0.3, tone=0.5, nseg=3)
        spike0 = 0.78
        for j in range(11):
            t = spike0 + (1.0 - spike0) * j / 10
            p, d = at(path, t)
            _, a, b = basis(d)
            size = 0.0052 * (1.0 - 0.45 * (j / 10) ** 2)
            for q in range(5):
                ang = 2 * np.pi * q / 5 + j * 0.62 + rng.uniform(-0.15, 0.15)
                c = p + (a * np.cos(ang) + b * np.sin(ang)) * 0.0038 + d * 0.003
                u = 0.35 + 0.5 * (j / 10) + rng.uniform(-0.08, 0.08)
                top, bot = c + d * size * 1.5, c - d * size * 1.1
                ring = [c + (a * np.cos(2 * np.pi * i / 4) + b * np.sin(2 * np.pi * i / 4)) * size for i in range(4)]
                it, ib = m.vert(top, "lav", u + 0.1, d), m.vert(bot, "lav", u - 0.1, -d)
                ir = [m.vert(r, "lav", u, r - c) for r in ring]
                for i in range(4):
                    m.tri(it, ir[i], ir[(i + 1) % 4]); m.tri(ib, ir[(i + 1) % 4], ir[i])
    return m


MAKERS = {"euc": eucalyptus, "olive": olive, "pampas": pampas, "lavender": lavender}


def build_one(p: dict, limits: dict) -> dict:
    """Букет `p` (запись из plants.json с `builder: "procedural"`, `maker` — имя) → `public/flat3d/plants/<id>.glb`; строка списка как у `plant_from_scan.build_one`."""
    seed = int.from_bytes(hashlib.sha256(p["id"].encode()).digest()[:4], "little")
    m = MAKERS[p["maker"]](np.random.default_rng(seed))
    m.orient()
    mesh = trimesh.Trimesh(vertices=np.array(m.v), faces=np.array(m.f), vertex_normals=np.array(m.n),
                           visual=trimesh.visual.TextureVisuals(uv=np.array(m.uv), material=trimesh.visual.material.PBRMaterial(
                               baseColorTexture=ramp_image(), metallicFactor=0.0, roughnessFactor=0.85, doubleSided=True, alphaMode="OPAQUE")),
                           process=False)
    tmp = os.path.join(os.path.expanduser("~"), f"_build-{p['id']}.glb")
    mesh.export(tmp, file_type="glb")
    os.makedirs(OUT, exist_ok=True)
    dst = os.path.join(OUT, f"{p['id']}.glb")
    res = subprocess.run([GLTFPACK, "-i", tmp, "-o", dst, "-cc", "-v"], capture_output=True, text=True, timeout=300)
    if res.returncode:
        raise SystemExit(f"{p['id']}: gltfpack: {(res.stderr or res.stdout).strip()[-200:]}")
    os.unlink(tmp)
    size = os.path.getsize(dst)
    mt = re.search(r"output: \d+ mesh primitives \((\d+) triangles", res.stdout + res.stderr)
    tris = int(mt.group(1)) if mt else len(m.f)
    if tris > limits["maxTris"] or size > limits["maxBytes"]:
        raise SystemExit(f"{p['id']}: бюджет превышен — {tris} треугольников, {size} байт")
    ext = (mesh.vertices.max(axis=0) - mesh.vertices.min(axis=0)) * 100
    write_source(p["asset"], p["maker"])
    return {"id": p["id"], "asset": p["asset"], "part": p["maker"], "kind": p["kind"], "tris": tris, "bytes": size,
            "sha256": hashlib.sha256(open(dst, "rb").read()).hexdigest(), "sizeCm": [round(float(x), 1) for x in ext]}


def write_source(asset: str, maker: str) -> None:
    """Реестр источника: свой код, CC0-1.0 (как `source.json` у Poly Haven, чтобы тест видел единый формат)."""
    d = os.path.join(SOURCES, asset)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "source.json"), "w", encoding="utf-8") as f:
        json.dump({"asset": asset, "title": f"Букет «{maker}» — собран кодом", "site": "own", "pageUrl": "tools/assets/plant_procedural.py",
                   "licence": "CC0-1.0", "licenceUrl": "https://creativecommons.org/publicdomain/zero/1.0/", "authors": {"remlab": "code"},
                   "generator": f"tools/assets/plant_procedural.py:{maker}", "sha256": {"tools/assets/plant_procedural.py":
                   hashlib.sha256(open(os.path.abspath(__file__), "rb").read()).hexdigest()}}, f, ensure_ascii=False, indent=1)
        f.write("\n")


if __name__ == "__main__":
    cfg = json.load(open(os.path.join(ROOT, "data", "flat3d", "plants.json"), encoding="utf-8"))
    for q in cfg["plants"]:
        if q.get("builder") == "procedural" and (len(sys.argv) < 2 or sys.argv[1] in (q["id"], q["maker"])):
            r = build_one(q, cfg["limits"])
            print(f"{r['id']:12s} {r['tris']:6d} треуг. {r['bytes'] // 1024:4d} КБ {r['sizeCm']} см")

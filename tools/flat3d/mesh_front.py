#!/usr/bin/env python3
"""Куда «смотрит» модель: калибровка разворота для замены мебели (владелец 29.09).

ЗАЧЕМ. При замене предмета место и поворот берутся у слота, но у КАЖДОЙ модели свой
«перёд» — он записан в `orient.json` конвейера мешей. У 21 модели из 40 такой записи нет, и
они вставали как придётся: диван спинкой в комнату, кресло лицом к стене.

КАК ОПРЕДЕЛЯЕМ. У мягкой мебели и шкафов спинка — это ВЫСОКАЯ и ПЛОСКАЯ сторона: сзади масса
поднимается, спереди (сиденье, фасад) — ниже. Считаем по вершинам меша распределение высоты по
четырём сторонам и выбираем разворот, при котором «высокая» сторона оказывается сзади (−Z).
Для симметричных вещей (стол, пуф, торшер) разницы нет — оставляем 0 и помечаем `front: weak`.

Запуск: ~/venvs/scout/bin/python tools/flat3d/mesh_front.py [--force]
Поле пишется в data/flat3d/furniture.json: asset.yawDeg + asset.frontSource (orient | geometry).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MESH_BASE = "https://remont-lab.online/test/mesh-pilot10/"
CACHE = os.path.expanduser("~/scout-scenes/flat3d-src")
# у чего есть выраженная спинка/фасад — там калибровка имеет смысл
BACKED = {"sofa", "armchair", "dining-chair", "tv-unit", "dresser", "shelf"}


def load_vertices(mesh_id: str) -> np.ndarray | None:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, f"{mesh_id}.glb")
    if not os.path.exists(path):
        local = os.path.expanduser(f"~/scout-scenes/mesh-pilot-gallery/{mesh_id}/model.glb")
        if os.path.exists(local):
            path = local
        else:
            try:
                with urllib.request.urlopen(f"{MESH_BASE}{mesh_id}/model.glb", timeout=120) as r:  # noqa: S310
                    data = r.read()
                with open(path, "wb") as fh:
                    fh.write(data)
            except Exception:  # noqa: BLE001
                return None
    try:
        import trimesh

        scene = trimesh.load(path, force="scene")
        parts = [g for g in scene.geometry.values() if hasattr(g, "vertices")]
        if not parts:
            return None
        return np.vstack([np.asarray(p.vertices, np.float64) for p in parts])
    except Exception:  # noqa: BLE001
        return None


def front_yaw(v: np.ndarray) -> tuple[int, float]:
    """Разворот (0/90/180/270) и уверенность: где у предмета «спинка»."""
    v = v - v.mean(0)
    x, y, z = v[:, 0], v[:, 1], v[:, 2]
    hi = y > (y.min() + (y.max() - y.min()) * 0.62)   # верхняя треть по высоте
    if hi.sum() < 40:
        return 0, 0.0
    # центр тяжести верхней части по горизонтали: он смещён в сторону спинки
    cx = float(x[hi].mean()) / max(float(np.abs(x).max()), 1e-6)
    cz = float(z[hi].mean()) / max(float(np.abs(z).max()), 1e-6)
    # ось, по которой смещение заметнее, и есть направление «назад»
    if abs(cz) >= abs(cx):
        yaw = 0 if cz < 0 else 180       # спинка сзади (−Z) — модель уже смотрит в +Z
        conf = abs(cz)
    else:
        yaw = 90 if cx < 0 else 270
        conf = abs(cx)
    return yaw, round(conf, 3)


def main() -> int:
    ap = argparse.ArgumentParser(description="калибровка разворота моделей мебели")
    ap.add_argument("--catalogue", default="data/flat3d/furniture.json")
    ap.add_argument("--orient", default=f"{MESH_BASE}orient.json")
    ap.add_argument("--min-conf", type=float, default=0.12)
    ap.add_argument("--force", action="store_true", help="пересчитать даже там, где есть orient.json")
    a = ap.parse_args()

    try:
        with urllib.request.urlopen(a.orient, timeout=60) as r:  # noqa: S310
            orient = json.load(r)
    except Exception as exc:  # noqa: BLE001
        print(f"orient.json недоступен ({exc}) — считаем всё по геометрии", file=sys.stderr)
        orient = {}

    path = os.path.abspath(a.catalogue)
    data = json.load(open(path, encoding="utf-8"))
    from_orient = from_geom = weak = 0
    for o in data.get("options", []):
        asset = o.get("asset") or {}
        if asset.get("kind") != "mesh":
            continue
        mid = asset["meshId"]
        known = orient.get(mid, {}).get("yaw")
        if known is not None and not a.force:
            asset["yawDeg"] = float(known)
            asset["frontSource"] = "orient"
            from_orient += 1
            continue
        if o.get("slotKey") not in BACKED:
            asset.setdefault("yawDeg", 0)
            asset["frontSource"] = "symmetric"
            weak += 1
            continue
        v = load_vertices(mid)
        if v is None:
            asset.setdefault("yawDeg", 0)
            asset["frontSource"] = "unknown"
            weak += 1
            continue
        yaw, conf = front_yaw(v)
        if conf < a.min_conf:
            asset.setdefault("yawDeg", 0)
            asset["frontSource"] = "weak"
            weak += 1
            continue
        asset["yawDeg"] = float(yaw)
        asset["frontSource"] = "geometry"
        asset["frontConf"] = conf
        from_geom += 1
        print(f"{o['id']:16s} {o.get('slotKey'):14s} разворот {yaw:3d}°  уверенность {conf}")

    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"\nиз orient.json: {from_orient}, по геометрии: {from_geom}, без калибровки: {weak}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

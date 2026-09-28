#!/usr/bin/env python3
"""Эталон трансформа предмета: считаем ТЕМ ЖЕ кодом, что и серверный рендер фото.

Зачем: 3D-конфигуратор и фото-конвейер обязаны ставить предмет в одно и то же место. Разъезд
здесь не виден глазом сразу, но кадр перестаёт соответствовать сцене (грабли 28.09: в отладочной
3D-сцене демо предмет смещён на пол-габарита, потому что x/y приняли за угол, а не за центр).

Скрипт берёт `tools/scout/scene_mesh.world_vertices` — то, по чему реально рисуется фото —
и сохраняет мировые вершины канонического куба для набора расстановок. TS-тест
(`tests/unit/configurator-transform.test.ts`) обязан совпасть с точностью 1e-4 м.

Запуск: ~/venvs/scout/bin/python tools/assets/transform_golden.py
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "scout"))
sys.path.insert(0, os.path.join(ROOT, "services", "planner-solver"))

import scene_mesh as SM  # noqa: E402

# Канонический «меш»: куб со стороной 2, смещённый — чтобы поймать и центрирование, и масштаб.
CUBE = np.array(
    [
        [-1.0, -1.0, -1.0],
        [1.0, -1.0, -1.0],
        [1.0, 1.0, -1.0],
        [-1.0, 1.0, -1.0],
        [-1.0, -1.0, 1.0],
        [1.0, -1.0, 1.0],
        [1.0, 1.0, 1.0],
        [-1.0, 1.0, 1.0],
    ],
    np.float32,
) * np.array([1.0, 0.6, 0.8], np.float32) + np.array([0.3, -0.2, 0.15], np.float32)

CASES = [
    {"name": "диван у южной стены", "x": 200, "y": 52, "rot": 0, "w": 210, "d": 95, "h": 85, "yaw": 0, "elev": 0},
    {"name": "стол повёрнут на 90", "x": 400, "y": 300, "rot": 90, "w": 140, "d": 80, "h": 75, "yaw": 0, "elev": 0},
    {"name": "тумба на 180 с калибровкой", "x": 120, "y": 640, "rot": 180, "w": 140, "d": 40, "h": 45, "yaw": 90, "elev": 0},
    {"name": "шкаф на 270", "x": 30, "y": 300, "rot": 270, "w": 180, "d": 60, "h": 230, "yaw": 270, "elev": 0},
    {"name": "навесное с высотой", "x": 700, "y": 250, "rot": 0, "w": 60, "d": 35, "h": 70, "yaw": 0, "elev": 148},
    {"name": "нецелый угол 37", "x": 500, "y": 400, "rot": 37, "w": 100, "d": 60, "h": 42, "yaw": 45, "elev": 0},
]


def main() -> int:
    out = []
    for c in CASES:
        part = SimpleNamespace(vertices=CUBE)
        place = SimpleNamespace(
            item=SimpleNamespace(w_cm=c["w"], d_cm=c["d"], h_cm=c["h"], h_cm_measured=c["h"], name="", role=""),
            rot=c["rot"],
            x=c["x"],
            y=c["y"],
            elev_cm=c["elev"],
        )
        place.item.h_cm = c["h"]
        worlds, _Ra, _R, _hsrc, _aniso, _scale = SM.world_vertices([part], place, float(c["yaw"]))
        verts = np.round(np.asarray(worlds[0], np.float64), 4).tolist()
        out.append({**c, "vertices": verts})

    dst = os.path.join(ROOT, "tests", "fixtures", "transform-golden.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "_about": "Эталон из scene_mesh.world_vertices (конвейер фото). Пересобрать: "
                "~/venvs/scout/bin/python tools/assets/transform_golden.py",
                "cube": CUBE.tolist(),
                "cases": out,
            },
            fh,
            ensure_ascii=False,
            indent=1,
        )
        fh.write("\n")
    print(f"эталон записан: {dst} ({len(out)} случаев)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

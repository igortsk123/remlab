#!/usr/bin/env python3
"""Эталон фото-камеры: где на кадре 1344×896 окажутся точки комнаты — считаем ТЕМ ЖЕ кодом, что серверный кадр.

Зачем (план demo-01 п.3, урок 414): браузерный движок сцены ставит фото-позу по точке съёмки плана; у прогулки и у
серверного кадра противоположные конвенции угла, и «на глаз похоже» уже раз приводило к зеркальным кадрам. Скрипт берёт
`draft_render.cams_from_request` (ракурс точки съёмки) и `scene_mesh.project_pts` (проекция фото) и сохраняет пиксели
8 углов комнаты и нескольких точек внутри для набора поз. TS-тест (`tests/unit/photo-pose.test.ts`) ставит камеру
three.js через `photoRay`/`verticalFov` движка и обязан совпасть с точностью до 1,5 px.

Запуск: ~/venvs/scout/bin/python tools/assets/camera_golden.py
"""
from __future__ import annotations

import json
import os
import sys
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "scout"))
sys.path.insert(0, os.path.join(ROOT, "services", "planner-solver"))

import draft_render as DR  # noqa: E402
import scene_mesh as SM  # noqa: E402

W, D, H = 439.0, 325.0, 270.0
ROOM_PTS = [[x, y, z] for x in (0.0, W) for y in (0.0, H) for z in (0.0, D)]
INNER_PTS = [[W / 2, 0.0, D / 2], [W / 2, 105.0, D / 2], [100.0, 40.0, 80.0], [330.0, 90.0, 250.0], [220.0, 200.0, 40.0], [60.0, 10.0, 300.0]]
POSES = [
    {"name": "C1 правый нижний угол → центр", "x": 436, "y": 322, "rot": -54, "fov": 72},
    {"name": "C2 левый верхний угол → центр", "x": 3, "y": 3, "rot": 126, "fov": 72},
    {"name": "C2 сдвинут вдоль стены (camFit)", "x": 3, "y": 43, "rot": 119, "fov": 72},
    {"name": "смотрит строго на север", "x": 220, "y": 300, "rot": 0, "fov": 72},
    {"name": "смотрит на восток, узкий объектив", "x": 40, "y": 160, "rot": 90, "fov": 55},
    {"name": "отвернут от центра", "x": 300, "y": 60, "rot": 200, "fov": 72},
    # поза v2 (demo-02, 14.10): глаз 135, горизонтально, сдвиг объектива −0.10 — `draft_render.photo_pose_heights`
    {"name": "v2: C1 угол → центр", "x": 436, "y": 322, "rot": -54, "fov": 72, "pose": 2},
    {"name": "v2: C2 у стены", "x": 3, "y": 63, "rot": 115, "fov": 72, "pose": 2},
    {"name": "v2: на восток, узкий объектив", "x": 40, "y": 160, "rot": 90, "fov": 55, "pose": 2},
]


def main() -> int:
    room = SimpleNamespace(width_cm=W, depth_cm=D)
    out = []
    for p in POSES:
        cam = DR.cams_from_request(room, [], {"cams": [{"name": "C", "x": p["x"], "y": p["y"], "rot": p["rot"], "fov": p["fov"],
                                                         "pose": p.get("pose")}]})[0]
        pts = []
        for q in ROOM_PTS + INNER_PTS:
            pr = SM.project_pts(cam, [q], cam.width, cam.height)   # по точке: соседняя точка за спиной не обнуляет кадр
            pts.append({"p": q, "px": [round(pr[0][0], 3), round(pr[0][1], 3)] if pr else None})
        out.append({**p, "eye": list(cam.eye), "target": list(cam.target), "shift_y": cam.shift_y, "width": cam.width,
                    "height": cam.height, "points": pts})
    dst = os.path.join(ROOT, "tests", "fixtures", "camera-golden.json")
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump({"_about": "Эталон фото-камеры из draft_render.cams_from_request + scene_mesh.project_pts. Пересобрать: "
                             "~/venvs/scout/bin/python tools/assets/camera_golden.py", "poses": out}, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print(f"эталон записан: {dst} ({len(out)} поз)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

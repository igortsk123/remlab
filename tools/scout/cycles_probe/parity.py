#!/usr/bin/env python3
"""Сверка двух описаний одной сцены (render-3d-01 шаг 0): scene-export.json (то, что строит /demo в браузере) и scene.json + m*.npz
(то, что собирает серверный кадр для Blender, `export_scene.py`). Мебель: по роли берём предмет в обоих, сравниваем центр основания
(см, план квартиры) и размеры; расхождение больше допуска — строка «РАЗНИЦА». Комната: размеры и отделка (цвет).

    parity.py <export2/<сцена>> <scene-export.json> [допуск_см=20]
"""
import json
import os
import sys

import numpy as np

sd, ej = sys.argv[1], sys.argv[2]
tol = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
M = json.load(open(os.path.join(sd, "scene.json"), encoding="utf-8"))
E = json.load(open(ej, encoding="utf-8"))
room = E["rooms"][0]["rectCm"]
bad = 0
print(f"комната: сервер {M['W']:.0f}×{M['D']:.0f}×{M['H']:.0f} | /demo {room['w']:.0f}×{room['d']:.0f}×{E['rooms'][0]['heightCm']:.0f}")
if abs(M["W"] - room["w"]) > 1 or abs(M["D"] - room["d"]) > 1:
    bad += 1
    print("  РАЗНИЦА: размеры комнаты")
fin_s = M["finish"]["wall"]["colorHex"].lower()
fin_e = E["rooms"][0]["wall"]["colorHex"].lower()
print(f"цвет стен: сервер {fin_s} | /demo {fin_e}", "" if fin_s == fin_e else "  РАЗНИЦА")
bad += fin_s != fin_e
# предметы сервера: роль → центр основания по вершинам (мир Blender: x, y = −план_y, z вверх; метры)
srv = {}
for o in M["objs"]:
    if not o.get("tex"):
        continue                                   # коробки окон и плинтус — не мебель
    z = np.load(os.path.join(sd, o["file"]))
    v = z["v"]
    lo, hi = v.min(0), v.max(0)
    srv.setdefault(o["role"], []).append({"cx": float((lo[0] + hi[0]) / 2 * 100), "cy": float(-(lo[1] + hi[1]) / 2 * 100),
                                          "w": float((hi[0] - lo[0]) * 100), "d": float((hi[1] - lo[1]) * 100)})
n_ok = 0
for m in E["meshes"]:
    role = m["role"]
    cand = srv.get(role) or []
    p = m["placement"]
    if not cand:
        print(f"  нет на сервере: {role} ({m['meshId']})")
        continue
    d = min(np.hypot(c["cx"] - p["x"], c["cy"] - p["y"]) for c in cand)
    ok = d <= tol
    n_ok += ok
    bad += not ok
    print(f"  {'ок ' if ok else 'РАЗНИЦА'} {role:22s} расстояние центров {d:5.1f} см  (/demo {p['x']:.0f},{p['y']:.0f}; {p['wCm']:.0f}×{p['dCm']:.0f})")
print(f"мебель: совпало {n_ok} из {len(E['meshes'])}; лёгкой копии нет у {len(E['liteMissing'])}")
sys.exit(1 if bad else 0)

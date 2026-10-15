#!/usr/bin/env python3
"""Эталон авто-ТВ и настольного декора: считаем ТЕМ ЖЕ кодом, что серверный кадр (план demo-05 п.9).

Живая сцена и /flat рисуют телевизор и вазу портом `lib/viewer3d/scene-extras.ts`; чтобы правило не разъехалось с
`draft_render.py` (`tv_spec`, авто-ТВ в `scene_from_request`, `decor_layout`), скрипт прогоняет набор случаев серверным
кодом и сохраняет ответы; TS-тест (`tests/unit/scene-extras.test.ts`) обязан совпасть.

  ~/venvs/scout/bin/python tools/assets/scene_extras_golden.py           # пересобрать эталон
  ~/venvs/scout/bin/python tools/assets/scene_extras_golden.py --check   # серверный код совпадает с эталоном?
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "scout"))
sys.path.insert(0, os.path.join(ROOT, "services", "planner-solver"))

import draft_render as DR  # noqa: E402

DST = os.path.join(ROOT, "tests", "fixtures", "scene-extras-golden.json")

TV_CASES = [
    # (расстояние, ширина тумбы, высота тумбы, подвесная)
    (120, 200, 45, False), (180, 200, 45, False), (230, 200, 45, False), (280, 200, 45, False),
    (330, 200, 45, False), (400, 230, 45, False), (400, 200, 45, False), (400, 120, 45, False),
    (280, 139, 90, False), (280, 139, 62, False), (250, 148, 55, False), (149.9, 80, 30, False),
    (300, 140, 41, True), (200, 160, 30, True), (500, 260, 50, False),
]

ROOM = {"w": 439, "d": 325, "openings": []}
SOFA = {"role": "диван", "x": 220, "y": 270, "rot": 180, "w": 220, "d": 95, "h": 85}
CHAIR = {"role": "кресло", "x": 100, "y": 200, "rot": 90, "w": 80, "d": 80, "h": 80}
STAND = {"role": "тв-тумба", "x": 220, "y": 25, "rot": 0, "w": 139, "d": 41, "h": 62, "name": "ТВ-тумба Теджонс 139x62"}
HUNG = {**STAND, "w": 160, "h": 30, "name": "ТВ-тумба подвесная Харис 160x30"}
TV_SCENES = [
    {"name": "тумба и диван", "items": [SOFA, STAND]},
    {"name": "подвесная тумба", "items": [SOFA, HUNG]},
    {"name": "нет дивана — кресло", "items": [CHAIR, {**STAND, "x": 60, "y": 160, "rot": 90}]},
    {"name": "ни дивана, ни кресла — 300 см", "items": [{**STAND, "rot": 270, "x": 410, "y": 160}]},
    {"name": "свой ТВ есть — авто не ставится", "items": [SOFA, STAND, {"role": "тв", "x": 220, "y": 20, "w": 120, "d": 8, "h": 70}]},
    {"name": "тумбы нет", "items": [SOFA]},
]

TABLE = {"role": "столик", "x": 220, "y": 160, "rot": 0, "w": 100, "d": 60, "h": 40}
DINING = {"role": "стол обеденный", "x": 360, "y": 80, "rot": 90, "w": 120, "d": 80, "h": 75}
VASE = {"role": "ваза", "sku": {"w": 19.5, "d": 19.5, "h": 30, "name": "Ваза Фьюжн"}}
BOWL = {"role": "декор", "sku": {"w": 31, "d": 31, "h": 12, "name": "Чаша"}}
DECOR_CASES = [
    {"name": "ваза на столике", "items": [SOFA, TABLE], "decor": [VASE]},
    {"name": "два предмета в ряд", "items": [SOFA, TABLE], "decor": [VASE, BOWL]},
    {"name": "столика нет — обеденный стол (повёрнут)", "items": [SOFA, DINING], "decor": [VASE, BOWL]},
    {"name": "не влезает на столик — на обеденный", "items": [{**TABLE, "w": 50}, DINING], "decor": [VASE, BOWL]},
    {"name": "без размеров — не в сцене", "items": [TABLE], "decor": [{"role": "ваза", "sku": {"w": 20, "name": "?"}}]},
    {"name": "опоры нет", "items": [SOFA], "decor": [VASE]},
    {"name": "столик повёрнут и приподнят", "items": [{**TABLE, "rot": 35, "elev": 5}], "decor": [VASE, BOWL]},
]


def build() -> dict:
    tv = []
    for dist, sw, sh, hung in TV_CASES:
        inch, w, h, elev, how = DR.tv_spec(dist, sw, sh, hung=hung)
        tv.append({"in": [dist, sw, sh, hung], "out": {"inch": inch, "wCm": w, "hCm": h, "elevCm": elev, "how": how}})
    scenes = []
    for sc in TV_SCENES:
        _room, placements, _ph = DR.scene_from_request({"room": ROOM, "items": sc["items"]})
        auto = [p for p in placements if p.role == "тв" and not any(it["role"] == "тв" for it in sc["items"])]
        stand = next((p for p in placements if p.role == "тв-тумба"), None)
        out = None
        if auto:
            t = auto[0]
            out = {"x": t.x, "y": t.y, "rot": t.rot, "wCm": t.item.w_cm, "dCm": t.item.d_cm, "hCm": t.item.h_cm,
                   "elevCm": t.elev_cm, "standElevCm": stand.elev_cm if stand is not None and stand.elev_cm else None}
        scenes.append({"name": sc["name"], "items": sc["items"], "tv": out})
    decor = []
    for dc in DECOR_CASES:
        placed, rest = DR.decor_layout({"items": dc["items"], "decor": dc["decor"]})
        decor.append({"name": dc["name"], "items": dc["items"], "decor": dc["decor"],
                      "placed": [{"i": dc["decor"].index(p["decor"]), **{k: round(float(p[k]), 4) for k in ("x", "y", "rot", "elev", "w", "d", "h")}}
                                 for p in placed],
                      "rest": [dc["decor"].index(r) for r in rest]})
    return {"_about": "Эталон авто-ТВ и декора из draft_render (tv_spec, scene_from_request, decor_layout). Пересобрать: "
                      "~/venvs/scout/bin/python tools/assets/scene_extras_golden.py", "tv": tv, "scenes": scenes, "decor": decor}


if __name__ == "__main__":
    data = build()
    if "--check" in sys.argv:
        with open(DST, encoding="utf-8") as fh:
            old = json.load(fh)
        same = json.dumps(old, sort_keys=True) == json.dumps(data, sort_keys=True)
        print("эталон авто-ТВ и декора:", "совпадает с draft_render" if same else "РАЗОШЁЛСЯ — пересобери и проверь scene-extras.ts")
        sys.exit(0 if same else 1)
    with open(DST, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    print("записан", DST)

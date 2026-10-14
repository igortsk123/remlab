#!/usr/bin/env python3
"""Эталон проёмов: где серверный кадр ставит каждую деталь окна и двери (план demo-04, критерий «один IR»).

Описание проёма (IR) строит ОДНА функция — `lib/viewer3d/opening-ir.ts`; сервер получает его через
`tools/flat3d/opening-ir.mjs` и ставит коробки в комнату своим кодом (`tools/scout/opening_ir.py:world_boxes`), браузер —
своим (`lib/viewer3d/rooms.ts:joineryOf`). Если два «поставщика» места разойдутся, окно на кадре и в 3D окажется в разных
местах — особенно на north/west, где отступ зеркалится. Скрипт для набора комнат (все четыре стены, все виды проёмов,
петли с обеих сторон, дверь наружу, закрытые и распахнутые полотна) сохраняет габарит каждой детали в см так, как его
ставит СЕРВЕР; TS-тест (`tests/unit/opening-ir.test.ts`) строит браузерные меши и сверяет с допуском 0,01 см.

Запуск: ~/venvs/scout/bin/python tools/assets/opening_golden.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "scout"))

import opening_ir as OIR  # noqa: E402

# комнаты в соглашении данных витрины (`demo-data.json`: offset_cm от запада/юга, hinge start|end, into)
ROOMS = [
    {"name": "south", "w": 400, "d": 300, "height_cm": 270, "openings": [
        {"kind": "window", "wall": "south", "offset_cm": 50, "width_cm": 120, "sill_cm": 85, "height_cm": 140},
        {"kind": "door", "wall": "south", "offset_cm": 250, "width_cm": 90, "hinge": "start"}]},
    {"name": "north", "w": 400, "d": 300, "height_cm": 270, "openings": [
        {"kind": "window", "wall": "north", "offset_cm": 40, "width_cm": 150, "sill_cm": 90},
        {"kind": "door", "wall": "north", "offset_cm": 260, "width_cm": 80, "hinge": "end"}]},
    {"name": "west", "w": 400, "d": 300, "height_cm": 260, "openings": [
        {"kind": "balcony", "wall": "west", "offset_cm": 30, "width_cm": 90},
        {"kind": "door", "wall": "west", "offset_cm": 180, "width_cm": 80, "into": False}]},
    {"name": "east", "w": 439, "d": 325, "height_cm": 270, "openings": [
        {"kind": "opening", "wall": "east", "offset_cm": 40, "width_cm": 100},
        {"kind": "door", "wall": "east", "offset_cm": 205, "width_cm": 90, "swing_cm": 90}]},
]


def ir_of(room: dict, open_doors: bool) -> list:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(room, f)
    try:
        cmd = ["node", os.path.join(ROOT, "tools", "flat3d", "opening-ir.mjs"), f.name] + (["--open"] if open_doors else [])
        return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=ROOT).stdout)
    finally:
        os.unlink(f.name)


def main() -> None:
    cases = []
    for room in ROOMS:
        for open_doors in (False, True):
            entries = ir_of(room, open_doors)
            boxes = []
            for e in entries:
                per = []
                for role, _mat, c in OIR.world_boxes(e, float(room["w"]), float(room["d"])):
                    per.append({"role": role, "min": [round(float(v), 4) for v in c.min(axis=0)],
                                "max": [round(float(v), 4) for v in c.max(axis=0)]})
                boxes.append({"wall": e["wall"], "kind": e["ir"]["kind"], "cut": e["ir"]["cut"], "boxes": per})
            cases.append({"name": f"{room['name']}{'-open' if open_doors else ''}", "open": open_doors,
                          "room": {k: room[k] for k in ("w", "d", "height_cm", "openings")}, "openings": boxes})
    out = os.path.join(ROOT, "tests", "fixtures", "opening-golden.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"note": "генерируется tools/assets/opening_golden.py — руками не править", "cases": cases}, f,
                  ensure_ascii=False, indent=1)
    print(f"эталон: {out} — {len(cases)} комнат, {sum(len(c['openings']) for c in cases)} проёмов")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Мост «замер комнаты по фото → сцена солвера» — T3 truth-first (главный product gap).

Вход:  plan.json сервиса замера (`services/room-measure/run_plan.py`):
       {"room_poly": [[x,y],...], ...} — вершины видимой комнаты в см (пол, произвольный угол).
Выход: tools/scout/real-plans/<имя>.json — сцена солвера:
       {"contour": [[x,y],...], "w": W, "d": D, "openings": [...], "source": "room-measure",
        "note": "..."}
       contour — ОСЕВОЙ (солвер работает только с осевыми рёбрами): полигон замера
       поворачивается к доминантной оси и ортогонализуется (рёбра прижимаются к 0°/90°,
       почти-коллинеарные вершины схлопываются). Потерянная при ортогонализации площадь
       печатается — это честная цена аппроксимации, а не молчаливое искажение.

Проёмы замер пока не отдаёт (окна/двери — в очереди сервиса замера) — в сцене остаётся
пустой список и note: дверь надо дописать руками до прогона (солвер без двери откажется).

  ~/venvs/scout/bin/python room_bridge.py /tmp/room-measure/plan-room1/plan.json [имя]
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, 'real-plans')
SNAP_DEG = 20      # рёбра в пределах ±20° от оси прижимаются к оси
MERGE_CM = 12      # вершины ближе 12 см схлопываются


def dominant_angle(poly) -> float:
    """Угол доминантной оси: взвешенная по длине мода направлений рёбер (mod 90°)."""
    sx = sy = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        ln = math.hypot(x2 - x1, y2 - y1)
        a = math.atan2(y2 - y1, x2 - x1) % (math.pi / 2)
        sx += ln * math.cos(4 * a)
        sy += ln * math.sin(4 * a)
    return math.atan2(sy, sx) / 4


def orthogonalize(poly):
    """Поворот к оси + прижатие рёбер к 0°/90° последовательным проходом."""
    ang = dominant_angle(poly)
    ca, sa = math.cos(-ang), math.sin(-ang)
    pts = [(x * ca - y * sa, x * sa + y * ca) for x, y in poly]
    out = [list(pts[0])]
    for x, y in pts[1:]:
        px, py = out[-1]
        dx, dy = x - px, y - py
        if math.hypot(dx, dy) < MERGE_CM:
            continue
        a = abs(math.degrees(math.atan2(dy, dx))) % 90
        if min(a, 90 - a) <= SNAP_DEG:
            if abs(dx) >= abs(dy):
                out.append([x, py])      # горизонтальное ребро
            else:
                out.append([px, y])      # вертикальное
        else:
            # косое ребро вне допуска — осевая лесенка из двух рёбер (честная аппроксимация)
            out.append([x, py])
            out.append([x, y])
    # замыкание прямым углом
    if abs(out[-1][0] - out[0][0]) > MERGE_CM and abs(out[-1][1] - out[0][1]) > MERGE_CM:
        out.append([out[0][0], out[-1][1]])
    # нормировка в положительный квадрант, округление до см
    minx = min(p[0] for p in out)
    miny = min(p[1] for p in out)
    out = [[round(x - minx), round(y - miny)] for x, y in out]
    ded = [out[0]]
    for p in out[1:]:
        if p != ded[-1]:
            ded.append(p)
    if ded[-1] == ded[0]:
        ded.pop()
    return ded


def area(poly) -> float:
    s = 0.0
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    src = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else \
        os.path.basename(os.path.dirname(src)).replace('plan-', '') or 'room'
    plan = json.load(open(src))
    poly = plan.get('room_poly') or plan.get('poly')
    if not poly or len(poly) < 3:
        print('room_poly не найден/мал — мост не построен')
        sys.exit(1)
    ortho = orthogonalize(poly)
    a0, a1 = area(poly), area(ortho)
    w = max(p[0] for p in ortho)
    d = max(p[1] for p in ortho)
    os.makedirs(OUT_DIR, exist_ok=True)
    scene = {'contour': ortho, 'w': w, 'd': d, 'openings': [],
             'source': f'room-measure:{src}',
             'note': 'проёмы замер не отдаёт — дверь дописать руками до прогона',
             'area_measured_m2': round(a0 / 1e4, 2), 'area_ortho_m2': round(a1 / 1e4, 2)}
    out = os.path.join(OUT_DIR, f'{name}.json')
    json.dump(scene, open(out, 'w'), ensure_ascii=False, indent=1)
    print(f'{out}: {w}x{d} см, вершин {len(poly)}→{len(ortho)}, '
          f'площадь {a0/1e4:.2f}→{a1/1e4:.2f} м² (потеря {abs(a0-a1)/max(a0,1)*100:.1f}%)')


if __name__ == '__main__':
    main()

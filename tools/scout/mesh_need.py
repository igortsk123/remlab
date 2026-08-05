#!/usr/bin/env python3
"""Кому из предметов сцены плоское фото ВРЁТ — то есть кому нужна 3D-модель.

Считается по геометрии, а не на глаз: у нас есть план (где предмет стоит и куда развёрнут) и
камеры. Три причины, по которым фотография товара не годится:

  БОКОМ    — предмет с лицевой стороной (диван, комод, тумба) повёрнут к камере боком; вырезка
             всегда смотрит в объектив, поэтому в кадре он «разворачивается» во всю ширину.
  СВЕРХУ   — камера смотрит на предмет сверху под заметным углом: видна крышка/столешница,
             а на карточке товара её нет. Считается по геометрии (высота камеры, высота
             предмета, расстояние), а не по списку ролей.
  РАЗНЫЕ   — предмет виден в ОБОИХ кадрах под сильно разными углами: одна и та же вырезка не
             может быть правдой в двух видах сразу.

Порог «боком» — тот же, что и во вклейке (`PASTE_MIN_ANGLE`, 38°), чтобы список совпадал с тем,
что реально не вклеилось. Правила «боком» и «разные» применяются ТОЛЬКО к предметам с лицевой
стороной: у круглого кашпо разворота нет, и 3D ему не нужно (урок 133).

  ~/venvs/scout/bin/python mesh_need.py 21 --cams C1,C2
"""
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))

from viz_paste import FLOOR, FRONTED, SKIP, SOFT  # noqa: E402
from scene_build import load_scene  # noqa: E402
from viz_objects import product  # noqa: E402
from planner.scene import cameras_for  # noqa: E402

MIN_ANGLE = float(os.environ.get('PASTE_MIN_ANGLE', 38))
TOP_ANGLE = float(os.environ.get('MESH_TOP_ANGLE', 20))   # выше — крышка предмета видна
FACE_N = {0: (0.0, 1.0), 90: (1.0, 0.0), 180: (0.0, -1.0), 270: (-1.0, 0.0)}


def face_angle(p, cam) -> float | None:
    """Угол между лучом камеры и лицевой стороной предмета: 90° — смотрим в лицо, 0° — в торец."""
    n = FACE_N.get(int(round(p.rot)) % 360)
    if n is None:
        return None
    eye = cam.eye
    look = np.array([p.x - eye[0], p.y - eye[2]], float)
    ln = float(np.linalg.norm(look))
    if ln < 1e-6:
        return None
    look /= ln
    cos = abs(float(look[0] * n[0] + look[1] * n[1]))
    return math.degrees(math.asin(min(1.0, max(0.0, cos))))


def top_angle(p, it, cam) -> float:
    """Насколько сверху камера смотрит на верх предмета, градусы (0 — точно в лоб)."""
    eye = cam.eye
    dist = math.hypot(p.x - eye[0], p.y - eye[2])
    h = float(getattr(it, 'h_cm', 0) or 0) + float(getattr(p, 'elev_cm', 0.0))
    return math.degrees(math.atan2(max(float(eye[1]) - h, 0.0), max(dist, 1.0)))


def analyse(n: int, cams: list[str]) -> list[dict]:
    room, placements = load_scene(n)
    all_cams = {c.name: c for c in cameras_for(room, placements)}
    by = {p.role: p for p in placements}
    seen = {}
    for cam_name in cams:
        cam = all_cams[cam_name]
        fr = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}-frame.json')
        visible = set(json.load(open(fr))['visible']) if os.path.exists(fr) else set(by)
        for role, p in by.items():
            if role in SKIP or role in SOFT or role in FLOOR or role not in visible:
                continue
            if float(getattr(p, 'elev_cm', 0.0)) > 1.0:      # декор на мебели — рисует модель
                continue
            rec = seen.setdefault(role, {'role': role, 'angles': {}, 'top': {}, 'why': set()})
            rec['top'][cam_name] = round(top_angle(p, p.item, cam))
            if top_angle(p, p.item, cam) > TOP_ANGLE:
                rec['why'].add('сверху')
            if role not in FRONTED:            # у предмета без лица разворота нет (урок 133)
                continue
            a = face_angle(p, cam)
            if a is not None:
                rec['angles'][cam_name] = round(a)
                if a < MIN_ANGLE:
                    rec['why'].add('боком')
    for role, rec in seen.items():
        p = by[role]
        rec['h_cm'] = round(float(getattr(p.item, 'h_cm', 0) or 0))
        vals = list(rec['angles'].values())
        if len(vals) > 1 and max(vals) - min(vals) >= 30:
            rec['why'].add('разные')
        try:
            rec['name'] = (product(n, role)[0].get('name') or '')[:60]
            rec['photo'] = product(n, role)[1]
        except (KeyError, AttributeError):
            rec['name'], rec['photo'] = '', ''
        rec['why'] = sorted(rec['why'])
    out = sorted(seen.values(), key=lambda r: (not r['why'], r['role']))
    return out


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    rows = analyse(n, cams)
    need = [r for r in rows if r['why']]
    print(f'комплект {n}, виды {"+".join(cams)} · порог «боком» {MIN_ANGLE:.0f}°\n')
    head = '  '.join(f'лицо {c:>3s}' for c in cams) + '  ' + '  '.join(f'сверху {c:>3s}' for c in cams)
    print(f'{"предмет":14s} {"h,см":>5s}  {head}   причина')
    for r in rows:
        ang = '  '.join(f'{str(r["angles"].get(c, "—")):>8s}' for c in cams)
        top = '  '.join(f'{str(r["top"].get(c, "—")):>10s}' for c in cams)
        print(f'{r["role"]:14s} {r["h_cm"]:5d}  {ang}  {top}   {", ".join(r["why"]) or "фото годится"}')
    print(f'\nнужна 3D-модель: {len(need)} из {len(rows)} — {", ".join(r["role"] for r in need)}')
    print(f'разово ≈ ${0.02 * len(need):.2f} (≈{0.02 * len(need) * 80:.0f} ₽), '
          f'дальше ракурсы бесплатны')
    dst = os.path.join(SCENE_DIR, f'scene{n}-mesh-need.json')
    json.dump(rows, open(dst, 'w'), ensure_ascii=False, indent=1)
    print(dst)


if __name__ == '__main__':
    main()

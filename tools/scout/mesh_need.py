#!/usr/bin/env python3
"""Кому нужна 3D-модель: считается ЛОКАЛЬНО и ЗАРАНЕЕ, до единого запроса и рубля.

Правило владельца (2026-08-05): смотрим, насколько сильно предмет развёрнут относительно того
ракурса, в котором снята карточка. Сильно — от 45° — значит камера видит его со стороны,
которой на фото просто нет, и вклеивать фото бессмысленно: нужна модель. Всё остальное вставляем
КАК ЕСТЬ: фотография товара — это настоящий вид вещи, и подменять её рендером незачем.

Два уточнения, без которых правило врёт:
  * Подвесное под потолком (люстра, бра) не моделим НИКОГДА. Оно высоко, разворот с пола не
    читается, а тонкие рожки и стекло генератор не восстанавливает — выходит мятая железка
    (проверено на люстре комплекта 21).
  * У предмета без лица (пуф, столик, ваза, кашпо) перёд и зад неразличимы, поэтому угол
    складывается в диапазон 0–90°: развернуть симметричную вещь «спиной» нельзя.

Считается по плану и камере — ни сети, ни нейросети. Поэтому список моделей известен ДО сборки
кадра, и деньги тратятся только на то, что действительно понадобится.

  ~/venvs/scout/bin/python mesh_need.py 21 --cams C1,C2
"""
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))

from viz_paste import FLOOR, FRONTED, HANG_MIN_ELEV, SKIP, SOFT, mesh_yaw_pitch  # noqa: E402
from scene_build import load_scene  # noqa: E402
from viz_objects import product  # noqa: E402
from planner.scene import cameras_for  # noqa: E402

MIN_YAW = float(os.environ.get('MESH_MIN_YAW', 45))   # сильный разворот — от этого угла
                                                      # (решение владельца 2026-08-05)


def on_floor(p) -> bool:
    """Моделим только то, что СТОИТ НА ПОЛУ (владелец, 2026-08-05).

    Ваза и лампа стоят на комоде, люстра висит под потолком: мелочь на мебели зритель видит
    издали и мелко, а подвесное генератор превращает в мятую железку. Им — фотография.
    """
    return float(getattr(p, 'elev_cm', 0.0)) <= 1.0


def turn_deg(p, it, cam) -> float:
    """На сколько градусов предмет развёрнут относительно ракурса своей карточки."""
    yaw = abs(mesh_yaw_pitch(p, it, cam)[0])
    if p.role not in FRONTED:            # без лица: перёд и зад неразличимы, складываем в 0–90°
        yaw = yaw % 180.0
        yaw = min(yaw, 180.0 - yaw)
    return yaw


def needs_mesh(p, it, cam) -> bool:
    """Нужна ли этому предмету 3D-модель в этом кадре. Только для НАПОЛЬНЫХ предметов."""
    if p.role in SKIP or p.role in SOFT or p.role in FLOOR:
        return False
    if not on_floor(p):
        return False
    return turn_deg(p, it, cam) >= MIN_YAW


def analyse(n: int, cams: list[str]) -> list[dict]:
    room, placements = load_scene(n)
    all_cams = {c.name: c for c in cameras_for(room, placements)}
    by = {p.role: p for p in placements}
    seen: dict[str, dict] = {}
    for cam_name in cams:
        cam = all_cams[cam_name]
        fr = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}-frame.json')
        visible = set(json.load(open(fr))['visible']) if os.path.exists(fr) else set(by)
        for role, p in by.items():
            if role in SKIP or role in SOFT or role in FLOOR or role not in visible:
                continue
            rec = seen.setdefault(role, {'role': role, 'turn': {}, 'need': [], 'why': ''})
            if not on_floor(p):
                rec['why'] = ('подвесное — не моделим'
                              if float(getattr(p, 'elev_cm', 0.0)) >= HANG_MIN_ELEV
                              else 'стоит на мебели — не моделим')
                continue
            rec['turn'][cam_name] = round(turn_deg(p, p.item, cam))
            if needs_mesh(p, p.item, cam):
                rec['need'].append(cam_name)
    for role, rec in seen.items():
        try:
            rec['name'] = (product(n, role)[0].get('name') or '')[:60]
        except (KeyError, AttributeError):
            rec['name'] = ''
        if not rec['why']:
            rec['why'] = ('сильный разворот в ' + ', '.join(rec['need'])) if rec['need'] else ''
    return sorted(seen.values(), key=lambda r: (not r['need'], r['role']))


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    rows = analyse(n, cams)
    need = [r for r in rows if r['need']]
    print(f'комплект {n}, виды {"+".join(cams)} · модель нужна от {MIN_YAW:.0f}° разворота\n')
    print(f'{"предмет":14s} ' + '  '.join(f'разворот {c:>3s}' for c in cams) + '   решение')
    for r in rows:
        turns = '  '.join(f'{str(r["turn"].get(c, "—")):>12s}' for c in cams)
        print(f'{r["role"]:14s} {turns}   {r["why"] or "фото как есть"}')
    print(f'\nмоделей нужно: {len(need)} из {len(rows)} — {", ".join(r["role"] for r in need) or "ни одной"}')
    print(f'разово ≈ ${0.02 * len(need):.2f} (≈{0.02 * len(need) * 80:.0f} ₽), '
          f'дальше ракурсы бесплатны')
    dst = os.path.join(SCENE_DIR, f'scene{n}-mesh-need.json')
    json.dump(rows, open(dst, 'w'), ensure_ascii=False, indent=1)
    print(dst)


if __name__ == '__main__':
    main()

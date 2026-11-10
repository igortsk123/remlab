"""T-20261110-12: подпись-выноска — рамка с текстом СНАРУЖИ дома, тонкая линия от рамки сквозь стену к точке в комнате (Berrys,
Giraffe360: Bathroom и Walk-in Wardrobe над планом, Wardrobe — под ним). VLM даёт центр текста — над домом; подпись переносим
в конец линии, только если линия видна в просвете рамка → дом. Подпись снаружи без линии (сад, терраса) — остаётся, где была.
Синтетика: дом 12×7 м (ppm 40, стена 8 px), внутренняя стена делит его на две комнаты."""
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import bench  # noqa: E402
import fpcore as fc  # noqa: E402

PPM, T = 40.0, 8
TOP, BOT = 140, 420           # наружные стены дома: строки 140..147 и 412..419


def sheet(leader_top=True, leader_bottom=True):
    """→ (серое, маска стен). Над домом рамка «Bathroom» с линией к точке в левой комнате, под домом — рамка с линией вверх
    в правую; правее верхней — подпись «Garden» без линии."""
    g = np.full((560, 560), 255, np.uint8)
    cv2.rectangle(g, (20, TOP), (500, BOT - 1), 244, -1)
    wall = np.zeros_like(g)
    wall[TOP:TOP + 8, 20:500] = 1; wall[BOT - 8:BOT, 20:500] = 1; wall[TOP:BOT, 20:28] = 1; wall[TOP:BOT, 492:500] = 1
    wall[TOP:BOT, 250:258] = 1                                       # внутренняя стена: левая и правая комнаты
    g[wall > 0] = 30
    cv2.rectangle(g, (80, 40), (200, 100), 150, 1)                   # рамка выноски сверху, текст внутри
    cv2.putText(g, 'Bath', (100, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 40, 1)
    if leader_top:
        cv2.line(g, (140, 101), (140, 200), 185, 2)                  # линия: просвет, стена, внутрь комнаты
        cv2.circle(g, (140, 205), 5, 30, -1)                         # точка на конце
    cv2.rectangle(g, (330, 470), (450, 530), 150, 1)                 # рамка снизу
    if leader_bottom:
        cv2.line(g, (390, 469), (390, 360), 185, 2)
        cv2.circle(g, (390, 355), 5, 30, -1)
    cv2.putText(g, 'Garden', (300, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, 40, 1)
    return g, wall


def analyze(g, wall):
    fams = fc.angle_families(wall)
    return bench.analyze(cv2.cvtColor(g, cv2.COLOR_GRAY2BGR), g, wall, PPM, fams, T)


def test_callout_label_moves_along_leader_into_its_room():
    g, wall = sheet()
    r = analyze(g, wall)
    left, right = r['lab'][300, 100], r['lab'][300, 400]
    assert left in r['rooms'] and right in r['rooms'] and left != right
    labels = [{'name': 'Bathroom', 'pt': (140.4, 70.2)}, {'name': 'Wardrobe', 'pt': (391.0, 500.0)},
              {'name': 'Garden', 'pt': (330.0, 55.0)}, {'name': 'Bedroom', 'pt': [400, 300]}]
    log = bench.callouts_to_rooms(labels, g, r, T)
    assert [c['name'] for c in log] == ['Bathroom', 'Wardrobe']
    by = {q['name']: q['pt'] for q in labels}
    assert bench.room_at(r['lab'], r['rooms'], tuple(by['Bathroom']), 2) == left
    assert abs(by['Bathroom'][0] - 140) <= 2 and 195 <= by['Bathroom'][1] <= 212            # точка на конце линии
    assert bench.room_at(r['lab'], r['rooms'], tuple(by['Wardrobe']), 2) == right
    assert by['Garden'] == (330.0, 55.0) and by['Bedroom'] == [400, 300]                   # без линии / уже в комнате — как было


def test_label_in_room_open_to_outside_stays():
    """C, «Store» в гараже: у комнаты ворота наружу — на листе она сливается с улицей, а у стены рядом короткий штрих. Подпись —
    внутри постройки (выпуклая оболочка стен), это не выноска: точку не трогаем (раньше уезжала по штриху за стену)."""
    g, wall = sheet(leader_top=False, leader_bottom=False)
    wall[BOT - 8:BOT, 300:480] = 0                                    # ворота 4,5 м в нижней стене правой комнаты
    g[BOT - 8:BOT, 300:480] = 244
    cv2.line(g, (258, 250), (330, 250), 185, 2)                       # штрих от внутренней стены к подписи
    r = analyze(g, wall)
    assert r['outside'][250, 400]                                     # комната слилась с улицей
    labels = [{'name': 'Store', 'pt': (400.0, 250.0)}]
    assert bench.callouts_to_rooms(labels, g, r, T) == [] and labels[0]['pt'] == (400.0, 250.0)


def test_outside_label_without_leader_stays():
    """Рамка без линии (подпись сада или стороны света у края листа) — не выноска: точка остаётся снаружи, подпись «не найдена»."""
    g, wall = sheet(leader_top=False, leader_bottom=False)
    r = analyze(g, wall)
    labels = [{'name': 'Bathroom', 'pt': (140.0, 70.0)}, {'name': 'Wardrobe', 'pt': (390.0, 500.0)}]
    assert bench.callouts_to_rooms(labels, g, r, T) == []
    assert labels[0]['pt'] == (140.0, 70.0)

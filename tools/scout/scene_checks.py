#!/usr/bin/env python3
"""ВОРОТА АРТЕФАКТОВ СЦЕНЫ (план demo-05 п.1): каждый опубликованный вариант демо проверяется до публикации.

(а) НАЕЗД — следы предметов пересекаются глубже 2 см. След — тот же, что у расстановщика (`planner/geometry.py:footprint`,
    Г-диван — 6 точек со стороной оттоманки `corner_left`), а не прямоугольный габарит (иначе ложный наезд 59×14 см в лофте).
    Не наезд: ковёр (по нему стоят), стулья под обеденным столом, декор на столешнице.
(б) ТЁМНАЯ МОДЕЛЬ — модель намного темнее товара (`mesh_dark.py`, пороги — `rules/mesh-quarantine.json → dark`).

Красный вариант не публикуется (`flat215_demo.py`), в дайджест — `WARN:scene_checks`. Ворота честны к себе: если красными
вышло больше половины вариантов, это скорее поломка проверки, чем данных — публикуется всё, а тревога громче.

  ~/venvs/scout/bin/python scene_checks.py ~/scout-scenes/flat215-demo/demo-data.json
  ~/venvs/scout/bin/python scene_checks.py --selftest
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..', 'services', 'planner-solver'))

OVERLAP_CM = 2.0
GALLERY = os.path.expanduser('~/scout-scenes/mesh-pilot-gallery')
_EXEMPT = ({'стол обеденный', 'стул'}, {'стол обеденный', 'табурет'})


def _base(role: str) -> str:
    """Роль без номера экземпляра: «стул 2» → «стул», «стол обеденный» остаётся целым."""
    import re
    return re.sub(r'\s+\d+$', '', str(role or ''))


def overlaps(items: list[dict]) -> list[str]:
    """Наезды предметов глубже OVERLAP_CM (по ширине пересечения). Чистая функция поверх `planner.geometry.footprint`."""
    from planner.geometry import footprint
    from planner.models import Item, Placement
    fps = []
    for it in items:
        if _base(it.get('role')) == 'ковёр' or not it.get('w') or not it.get('d'):
            continue
        item = Item(role=it['role'], w_cm=float(it['w']), d_cm=float(it['d']), h_cm=float(it.get('h') or 80),
                    corner=bool(it.get('corner')), corner_left=bool(it.get('corner_left')),
                    **({'corner_section_cm': float(it['section'])} if it.get('section') else {}))
        fps.append((it['role'], footprint(Placement(role=it['role'], x=float(it['x']), y=float(it['y']),
                                                    rot=float(it.get('rot') or 0), item=item))))
    out = []
    for i in range(len(fps)):
        for j in range(i + 1, len(fps)):
            (ra, fa), (rb, fb) = fps[i], fps[j]
            if {_base(ra), _base(rb)} in _EXEMPT:
                continue
            inter = fa.intersection(fb)
            if inter.is_empty or inter.area <= 0:
                continue
            mrr = inter.minimum_rotated_rectangle
            xs, ys = mrr.exterior.coords.xy
            sides = [((xs[k + 1] - xs[k]) ** 2 + (ys[k + 1] - ys[k]) ** 2) ** 0.5 for k in range(2)]
            if min(sides) > OVERLAP_CM:
                out.append(f'наезд {ra} × {rb}: {max(sides):.0f}×{min(sides):.0f} см')
    return out


def dark_models(items: list[dict], cache: dict) -> list[str]:
    """Модели вариантов, которые намного темнее товара. Кэш — по пути и времени файла модели."""
    import mesh_dark as MDK
    out = []
    for it in items:
        s = it.get('sku') or {}
        mid = s.get('msid')
        glb = os.path.join(GALLERY, str(mid), 'model.glb') if mid else ''
        if not mid or not os.path.exists(glb):
            continue
        key = f'{mid}:{int(os.path.getmtime(glb))}'
        if key not in cache:
            try:
                cache[key] = MDK.measure(glb, s.get('name') or '')
            except Exception as e:  # noqa: BLE001 — модель не открылась: громко, но вариант этим не валим
                print(f'  scene_checks: {mid} не замерена ({str(e)[:60]})', flush=True)
                cache[key] = None
        if cache[key] is not None:
            out.append(f'тёмная модель {it["role"]}: «{(s.get("name") or "")[:40]}» ({cache[key]:.0f}/255)')
    return out


def check(data: dict, cache: dict | None = None) -> dict:
    """→ {id варианта: [причины]} — только красные."""
    cache = {} if cache is None else cache
    red = {}
    for v in data.get('variants') or []:
        why = overlaps(v.get('items') or []) + dark_models(v.get('items') or [], cache)
        if why:
            red[v.get('id')] = why
    return red


def _selftest() -> int:
    fails = 0

    def ok(c, n):
        nonlocal fails
        print(('ok   ' if c else 'FAIL ') + n)
        fails += 0 if c else 1

    sofa = {'role': 'диван', 'x': 200, 'y': 250, 'rot': 180, 'w': 200, 'd': 90, 'h': 85}
    ok(overlaps([sofa, {'role': 'столик', 'x': 200, 'y': 150, 'rot': 0, 'w': 100, 'd': 50, 'h': 40}]) == [], 'столик перед диваном — не наезд')
    ok(len(overlaps([sofa, {'role': 'столик', 'x': 200, 'y': 200, 'rot': 0, 'w': 100, 'd': 50, 'h': 40}])) == 1, 'столик въехал в диван на 20 см — наезд')
    ok(overlaps([sofa, {'role': 'кресло', 'x': 301.5, 'y': 250, 'rot': 0, 'w': 5, 'd': 80, 'h': 80}]) == [], 'касание 1 см — не наезд (порог 2 см)')
    ok(overlaps([{'role': 'стол обеденный', 'x': 100, 'y': 100, 'rot': 0, 'w': 90, 'd': 90, 'h': 75},
                 {'role': 'стул 2', 'x': 100, 'y': 130, 'rot': 0, 'w': 45, 'd': 50, 'h': 85}]) == [], 'стул под обеденным столом — не наезд')
    ok(overlaps([sofa, {'role': 'ковёр', 'x': 200, 'y': 200, 'rot': 0, 'w': 230, 'd': 160}]) == [], 'ковёр под диваном — не наезд')
    corner = {'role': 'диван', 'x': 200, 'y': 230, 'rot': 180, 'w': 240, 'd': 160, 'h': 85, 'corner': True, 'corner_left': True, 'section': 95}
    t_free = {'role': 'столик', 'x': 160, 'y': 120, 'rot': 0, 'w': 60, 'd': 40, 'h': 40}
    ok(overlaps([corner, t_free]) == [], 'Г-диван: столик в выемке Г — не наезд (прямоугольник дал бы ложный)')
    print('итог:', 'чисто' if not fails else f'{fails} провал(ов)')
    return 1 if fails else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    data = json.load(open(sys.argv[1], encoding='utf-8'))
    red = check(data)
    for vid, why in red.items():
        print(f'WARN:scene_checks: {vid} — ' + '; '.join(why))
    print(f'ворота сцены: вариантов {len(data.get("variants") or [])}, красных {len(red)}')

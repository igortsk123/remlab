"""Вектор качества сцены — гейт «не ставим то, что ухудшает достигнутое».

Свод владельца (12.08, по его ресёрчу): дизайнер работает не «впихнуть как можно
больше», а «сначала главная функция → проходы → композиция → вторичное, и только если
качество не падает». Этот модуль даёт числа, по которым решается «стало хуже?».

ВАЖНО: сам гейт ничего не двигает и ничего не разбирает. Ставим по-прежнему ТОЛЬКО
шаблоны целиком (`template.py`), а гейт решает, принять поставленный шаблон или
откатить его целиком.

Компоненты (лексикографически, сверху вниз):
  hard         — жёстких нарушений нет (проверяет validate, здесь не дублируется)
  circulation  — ширина главного маршрута от двери, см (порог 75)
  focus        — фокус-стена не пуста и носитель в оси взгляда (смещение, см)
  cohesion     — связность посадки (ножки на ковре, столик в досягаемости)
  breathing    — площадь «щелей» уже 45 см, м² (чем меньше, тем лучше)
  coverage     — сколько предметов вошло (последний по важности — следствие, не цель)

Пороги и пруфы — `rules/zones.json` → `quality_gate`.
"""
from __future__ import annotations

import json
import os

from shapely.geometry import Point
from shapely.ops import unary_union

from .geometry import footprint, opening_polygon, room_polygon
from .models import Placement, Room

_RULES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'rules', 'zones.json')
with open(_RULES, encoding='utf-8') as _f:
    _CFG = (json.load(_f).get('quality_gate') or {})

ROUTE_MIN_CM = float(_CFG.get('route_min_cm', 75))
SLIVER_CM = float(_CFG.get('sliver_cm', 45))
FOCUS_OFFSET_MAX_CM = float(_CFG.get('focus_offset_max_cm', 40))
_FLAT = ('ковёр',)


def _free_space(room: Room, ps: list[Placement]):
    """Свободный пол: комната минус мебель (ковёр — подложка, по нему ходят)."""
    # ПОЛ, ПО КОТОРОМУ ХОДЯТ: контур комнаты минус мебель. Ковёр — подложка (по нему
    # ходят), дуга двери — тоже проходима (там просто нельзя ставить мебель), поэтому
    # берём room_polygon, а не usable_polygon: иначе зона у двери «вырезалась», и
    # маршрут не находился даже в пустой комнате.
    occ = [footprint(p) for p in ps if p.role.split(' ')[0] not in _FLAT]
    free = room_polygon(room)
    return free.difference(unary_union(occ)) if occ else free


def route_width_cm(room: Room, ps: list[Placement]) -> float:
    """Ширина главного маршрута от двери вглубь комнаты.

    Метод: сужаем свободный пол на r/2 (морфологическая эрозия) — остаётся «скелет»
    коридоров шириной ≥ r. Берём наибольшее r, при котором от точки ПЕРЕД ДВЕРЬЮ
    (отступ внутрь на r/2) ещё есть связная область, покрывающая заметную часть пола.
    Проверено на пустой комнате: даёт верхнюю ступень, а не заниженное число.
    """
    free = _free_space(room, ps)
    if free.is_empty:
        return 0.0
    door = next((o for o in room.openings if o.kind == 'door'), None)
    dc = (opening_polygon(room, door).centroid if door is not None
          else room_polygon(room).centroid)
    cc = room_polygon(room).centroid
    vx, vy = cc.x - dc.x, cc.y - dc.y
    n = (vx * vx + vy * vy) ** 0.5 or 1.0
    vx, vy = vx / n, vy / n              # единичный вектор «внутрь комнаты»
    best = 0.0
    for r in (60.0, 70.0, 75.0, 80.0, 90.0, 100.0, 120.0):
        core = free.buffer(-r / 2, resolution=4)
        if core.is_empty:
            break
        probe = Point(dc.x + vx * (r / 2 + 5), dc.y + vy * (r / 2 + 5))
        parts = list(getattr(core, 'geoms', [core]))
        comp = min(parts, key=lambda g: g.distance(probe))
        if comp.distance(probe) > r / 2:      # от двери в коридор такой ширины не войти
            break
        if comp.area < free.area * 0.10:      # «коридор» ведёт в тупик
            break
        best = r
    return best


def _dead_side_mask(room: Room, ps: list[Placement]):
    """M-B (свод №5): DEAD_SIDE — узкие полосы МЕЖДУ мебелью и ближайшей стеной,
    куда человек не должен проходить. Они не «щели»-дефекты и не маршруты."""
    from shapely.ops import unary_union
    strips = []
    for p in ps:
        if p.role.split(' ')[0] in _FLAT:
            continue
        strips.append(footprint(p).buffer(28.0, resolution=4))
    if not strips:
        return None
    ring = room_polygon(room).boundary.buffer(30.0)
    return unary_union(strips).intersection(ring)


def sliver_area_m2(room: Room, ps: list[Placement]) -> float:
    """Площадь «щелей» уже SLIVER_CM — места, куда нельзя ни встать, ни пройти.

    Свод владельца: «щель 45 см — не повод ставить туда кашпо». Считаем то, что
    исчезает при морфологическом открытии свободного пола.
    """
    free = _free_space(room, ps)
    if free.is_empty:
        return 0.0
    opened = free.buffer(-SLIVER_CM / 2, resolution=4).buffer(SLIVER_CM / 2, resolution=4)
    slivers = free.difference(opened.intersection(free))
    dead = _dead_side_mask(room, ps)
    if dead is not None:
        slivers = slivers.difference(dead)     # бок дивана у стены — не дефект (M-B)
    return max(0.0, slivers.area) / 10_000


def focus_offset_cm(ps: list[Placement]) -> float | None:
    """Смещение носителя ТВ от оси взгляда с дивана (см). None — фокуса нет."""
    import math
    seat = next((p for p in ps if p.role.split(' ')[0] == 'диван'), None) or \
        next((p for p in ps if p.role.split(' ')[0] == 'кресло'), None)
    bearer = next((p for p in ps if p.role.split(' ')[0] in ('тв-тумба', 'стенка', 'камин')), None)
    if seat is None or bearer is None:
        return None
    r = math.radians(seat.rot)
    vx, vy = bearer.x - seat.x, bearer.y - seat.y
    return abs(math.cos(r) * vx - math.sin(r) * vy)


def scene_quality(room: Room, ps: list[Placement]) -> dict:
    """Вектор качества сцены (чем «лучше», тем предпочтительнее)."""
    return {
        'circulation': route_width_cm(room, ps),
        'focus': focus_offset_cm(ps),
        'sliver_m2': sliver_area_m2(room, ps),
        'items': len(ps),
    }


def not_worse(before: dict, after: dict) -> bool:
    """Стало ли НЕ хуже по защищённым компонентам (порядок важен).

    Защищаем: маршрут (не сузился ниже порога и не стал уже прежнего) и «щели»
    (не выросли заметно). Число предметов защищённым НЕ является — оно следствие.
    """
    b_route, a_route = before.get('circulation', 0.0), after.get('circulation', 0.0)
    if a_route < min(b_route, ROUTE_MIN_CM):
        return False
    b_sl, a_sl = before.get('sliver_m2', 0.0), after.get('sliver_m2', 0.0)
    if a_sl > b_sl + 0.35:          # +0.35 м² новых щелей — предмет «затыкает дыру»
        return False
    b_f, a_f = before.get('focus'), after.get('focus')
    if b_f is not None and a_f is not None and a_f > max(b_f, FOCUS_OFFSET_MAX_CM):
        return False
    return True

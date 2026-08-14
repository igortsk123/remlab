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
    # свод №6 N3а: у Г-дивана ось меряется от центра ГЛАВНОЙ секции, не bbox
    from .geometry import seat_axis_origin
    sx, sy = seat_axis_origin(seat)
    vx, vy = bearer.x - sx, bearer.y - sy
    return abs(math.cos(r) * vx - math.sin(r) * vy)


def residual_depth_cm(room: Room, ps: list[Placement]) -> float:
    """E3-диагностика (свод №4): глубина ПУСТОЙ связной полосы за спинкой
    floating-дивана (спинка дальше 40 см от стены). 0 — дивана-границы нет или
    за спинкой есть функция. НЕ гейт: пороги решений — residual_bands (паспорт)."""
    import math as _m
    sofa = next((p for p in ps if p.role == 'диван'), None)
    if sofa is None:
        return 0.0
    rot = int(sofa.rot) % 360
    sd = (sofa.item.d_cm if sofa.item else 95.0)
    back = {0: sofa.y - sd / 2, 180: room.depth_cm - (sofa.y + sd / 2),
            90: sofa.x - sd / 2, 270: room.width_cm - (sofa.x + sd / 2)}.get(rot, 0.0)
    if back <= 40.0:
        return 0.0
    def _behind(p) -> bool:
        if rot == 0:
            return p.y < sofa.y - sd / 2
        if rot == 180:
            return p.y > sofa.y + sd / 2
        if rot == 90:
            return p.x < sofa.x - sd / 2
        return p.x > sofa.x + sd / 2
    if any(_behind(p) for p in ps if p.role not in ('диван', 'ковёр')):
        return 0.0
    # свод №4 §1: пустота у двери (створ + подход) — ЗАКОННАЯ, не residual.
    # Дверь на стене за спинкой → полоса является входом, остатка нет
    back_wall = {0: 'south', 180: 'north', 90: 'west', 270: 'east'}.get(rot)
    if any(op.kind in ('door', 'balcony') and op.wall == back_wall
           for op in room.openings):
        return 0.0
    return back


def scene_quality(room: Room, ps: list[Placement]) -> dict:
    """Вектор качества сцены (чем «лучше», тем предпочтительнее)."""
    return {
        'circulation': route_width_cm(room, ps),
        'focus': focus_offset_cm(ps),
        'sliver_m2': sliver_area_m2(room, ps),
        'residual_cm': residual_depth_cm(room, ps),
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


# --- Пакет G свода №8 (v2 §6.3-6.4, §8): НОВЫЕ ОСИ — ТОЛЬКО ИЗМЕРЕНИЕ. ---
# Порогов и весов НЕТ сознательно: сначала распределение по 252 планам,
# порог — отдельным ADR в rules/*.json (урок 161: геометрию не чинить весом).

def residual_fragmentation(room, ps) -> dict:
    """Фрагментация остаточного пола: сколько связных кусков и их площади (м²).
    «Плохие бессмысленные карманы» станут видимыми в данных до любых штрафов."""
    free = _free_space(room, ps)
    geoms = list(getattr(free, 'geoms', [free])) if not free.is_empty else []
    areas = sorted((g.area / 10_000 for g in geoms), reverse=True)
    return {'components': len(areas), 'areas_m2': [round(a, 2) for a in areas[:6]]}


def visual_balance(room, ps) -> dict:
    """Баланс масс: смещение центроида мебели от центра комнаты (% полудиагонали)
    и доли футпринта мебели по половинам (запад/восток, юг/север)."""
    import math
    from .geometry import footprint as _fp
    fps = [(_fp(p), p) for p in ps if p.role != 'ковёр']
    if not fps:
        return {'centroid_offset_pct': 0.0, 'west_share': 0.5, 'south_share': 0.5}
    ax = sum(f.area * f.centroid.x for f, _ in fps) / max(sum(f.area for f, _ in fps), 1e-6)
    ay = sum(f.area * f.centroid.y for f, _ in fps) / max(sum(f.area for f, _ in fps), 1e-6)
    cx, cy = room.width_cm / 2, room.depth_cm / 2
    half_diag = math.hypot(cx, cy)
    total = sum(f.area for f, _ in fps)
    west = sum(min(f.area, f.intersection(_box_half(room, 'west')).area) for f, _ in fps)
    south = sum(min(f.area, f.intersection(_box_half(room, 'south')).area) for f, _ in fps)
    return {'centroid_offset_pct': round(math.hypot(ax - cx, ay - cy) / half_diag * 100, 1),
            'west_share': round(west / max(total, 1e-6), 2),
            'south_share': round(south / max(total, 1e-6), 2)}


def _box_half(room, side: str):
    from shapely.geometry import box as _bx
    if side == 'west':
        return _bx(0, 0, room.width_cm / 2, room.depth_cm)
    return _bx(0, 0, room.width_cm, room.depth_cm / 2)


def route_active_dining_cm(room, ps) -> float | None:
    """Маршрут в «активном» состоянии столовой (v2 §8): стулья отодвинуты —
    их pullout-зоны (существующий клиренс, clearances.py) временно препятствия.
    Возвращает ширину маршрута или None, если столовой нет. Только замер."""
    din = [p for p in ps if p.role.split(' ')[0] in ('стол обеденный', 'стул')]
    if not din:
        return None
    from .clearances import clearance_for
    from .geometry import access_zone
    pseudo = list(ps)
    extra = []
    for p in din:
        spec = clearance_for(p.role)
        if spec.front_cm > 0:
            extra.append(access_zone(p, spec=spec))
    # временные препятствия учитываем прямым вычитанием из свободного пола
    from shapely.ops import unary_union
    from shapely.geometry import Point
    free = _free_space(room, pseudo)
    if extra:
        free = free.difference(unary_union(extra))
    # та же ступенчатая эрозия, что в route_width_cm, но на суженном полу
    best = 0.0
    door = next((o for o in room.openings if o.kind == 'door'), None)
    from .geometry import opening_polygon
    probe = (opening_polygon(room, door).buffer(30).centroid if door is not None
             else free.centroid)
    floor_area = room.width_cm * room.depth_cm
    for r in (60, 70, 75, 80, 90, 100, 120):
        er = free.buffer(-r / 2)
        if er.is_empty:
            break
        comps = list(getattr(er, 'geoms', [er]))
        near = [c for c in comps if c.distance(probe) < r]
        if not near:
            break
        if max(c.area for c in near) < floor_area * 0.10:
            break
        best = float(r)
    return best

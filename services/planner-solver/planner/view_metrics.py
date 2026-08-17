"""Q0 свода №13 (MASTER-zones-v7): диагностические метрики «как видит владелец».

Источник — слепая оценка раунд 1 (10 пар) + аудит Кодекса с замерами: владелец ранжирует
планы по (1) маршруту от двери, не пересекающему коридор диван→ТВ; (2) медиапригодности
кресла (≤45° к ТВ); (3) отсутствию столовой во фронтальном конусе взгляда; (4) наполнению
ТВ-стены компаньонами; (5) дальности кресла до ТВ; (6) фактической посадке (кресла/пуф).

Здесь ТОЛЬКО измерение (артефакт `_view`), выбор плана не трогаем (Q4 — отдельно, после
Q3 и сертификатов). Пороги для интерпретации — rules/zones.json → view_contracts (Q2);
функции возвращают сырые величины, а «нарушение/нет» считает вызывающий по данным.
"""
from __future__ import annotations

import math

from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

from .geometry import base_role, footprint, opening_polygon, seat_axis_origin
from .models import Placement, Room

CARRIER = ('тв-тумба', 'стенка')
FRONTAL_COMPANIONS = ('стеллаж', 'витрина', 'комод', 'кашпо', 'полка')
DINING = ('стол обеденный', 'стул')


def _find(ps: list[Placement], roles: tuple[str, ...]) -> Placement | None:
    return next((p for p in ps if base_role(p.role) in roles), None)


def _sofa(ps: list[Placement]) -> Placement | None:
    return next((p for p in ps if base_role(p.role) == 'диван'), None) or \
        next((p for p in ps if base_role(p.role) == 'кресло'), None)


def sight_corridor(room: Room, ps: list[Placement], half_width_cm: float | None = None) -> Polygon | None:
    """Коридор взгляда диван→ТВ: полоса от оси посадки до носителя шириной = ширина
    носителя (+ запас), обрезанная комнатой. None — нет пары."""
    sofa, tv = _sofa(ps), _find(ps, CARRIER)
    if sofa is None or tv is None:
        return None
    sx, sy = seat_axis_origin(sofa)
    hw = half_width_cm if half_width_cm is not None else max(40.0, (tv.item.w_cm if tv.item else 120.0) / 2)
    line = LineString([(sx, sy), (tv.x, tv.y)])
    if line.length < 1:
        return None
    return line.buffer(hw, cap_style=2)


def entry_sightline_gap_cm(room: Room, ps: list[Placement]) -> float | None:
    """Мин. зазор между дверными проёмами (+дуга) и коридором взгляда диван→ТВ.
    0 = дверь/дуга режет коридор (человек от двери проходит перед экраном — pair01)."""
    cor = sight_corridor(room, ps)
    if cor is None:
        return None
    from .geometry import swing_polygon
    doors = [op for op in room.openings if op.kind in ('door', 'balcony')]
    if not doors:
        return None
    best = None
    for op in doors:
        g = opening_polygon(room, op)
        try:
            g = unary_union([g, swing_polygon(room, op)])
        except Exception:
            pass
        d = g.distance(cor)
        best = d if best is None else min(best, d)
    return round(float(best), 1) if best is not None else None


def _angle_to(p: Placement, tx: float, ty: float) -> float:
    r = math.radians(p.rot)
    fx, fy = math.sin(r), math.cos(r)
    dx, dy = tx - p.x, ty - p.y
    n = math.hypot(dx, dy) or 1.0
    c = max(-1.0, min(1.0, (fx * dx + fy * dy) / n))
    return math.degrees(math.acos(c))


def armchair_tv_angles(ps: list[Placement]) -> list[float]:
    """Углы (°) между фасадом каждого кресла и направлением на носитель ТВ."""
    tv = _find(ps, CARRIER)
    if tv is None:
        return []
    return [round(_angle_to(p, tv.x, tv.y), 1) for p in ps if base_role(p.role) == 'кресло']


def armchair_tv_dist_cm(ps: list[Placement]) -> list[float]:
    tv = _find(ps, CARRIER)
    if tv is None:
        return []
    return [round(footprint(p).distance(footprint(tv)), 1) for p in ps if base_role(p.role) == 'кресло']


def sofa_tv_dist_cm(ps: list[Placement]) -> float | None:
    sofa, tv = _sofa(ps), _find(ps, CARRIER)
    if sofa is None or tv is None:
        return None
    return round(footprint(sofa).distance(footprint(tv)), 1)


def view_cone(room: Room, ps: list[Placement], half_deg: float = 45.0) -> Polygon | None:
    """Конус взгляда с оси посадки в сторону ТВ (полуугол half_deg), до дальней стены."""
    sofa, tv = _sofa(ps), _find(ps, CARRIER)
    if sofa is None or tv is None:
        return None
    sx, sy = seat_axis_origin(sofa)
    ang = math.atan2(tv.x - sx, tv.y - sy)      # 0 = север (+y), как rot
    R = math.hypot(room.width_cm, room.depth_cm)
    a1, a2 = ang - math.radians(half_deg), ang + math.radians(half_deg)
    pts = [(sx, sy)]
    steps = 12
    for i in range(steps + 1):
        a = a1 + (a2 - a1) * i / steps
        pts.append((sx + R * math.sin(a), sy + R * math.cos(a)))
    from .geometry import room_polygon
    return Polygon(pts).intersection(room_polygon(room))


def dining_view_cone_overlap_pct(room: Room, ps: list[Placement], half_deg: float = 45.0) -> float | None:
    """Доля footprint обеденной группы внутри конуса взгляда диван→ТВ (0–100). None — нет
    столовой или нет пары диван/ТВ."""
    din = [p for p in ps if base_role(p.role) in DINING]
    if not din:
        return None
    cone = view_cone(room, ps, half_deg)
    if cone is None:
        return None
    g = unary_union([footprint(p) for p in din])
    if g.area <= 0:
        return None
    return round(100.0 * g.intersection(cone).area / g.area, 1)


def frontal_companions(room: Room, ps: list[Placement], along_tol_cm: float = 40.0) -> list[str]:
    """Компаньоны на стене носителя ТВ (сам носитель не считается): предметы хранения/
    декора, чей центр лежит на той же стене (в пределах along_tol от линии стены)."""
    tv = _find(ps, CARRIER)
    if tv is None:
        return []
    rot = int(round(tv.rot)) % 360
    out = []
    for p in ps:
        if p is tv or base_role(p.role) not in FRONTAL_COMPANIONS:
            continue
        same_wall = (abs(p.y - tv.y) <= along_tol_cm) if rot in (0, 180) else (abs(p.x - tv.x) <= along_tol_cm)
        if same_wall and int(round(p.rot)) % 360 == rot:
            out.append(p.role)
    return out


def realized_seating(ps: list[Placement]) -> dict:
    """Фактическая посадка: кресла, пуфы; footrest — пуф в зоне ног (≤110 см до посадки),
    иначе flex-seat. Не любой пуф — footrest (Кодекс)."""
    seats = [p for p in ps if base_role(p.role) in ('диван', 'кресло')]
    arm = sum(1 for p in ps if base_role(p.role) == 'кресло')
    footrest = 0
    flex = 0
    for p in ps:
        if base_role(p.role) != 'пуф':
            continue
        d = min((footprint(p).distance(footprint(s)) for s in seats), default=1e9)
        if d <= 110:
            footrest += 1
        else:
            flex += 1
    return {'armchairs': arm, 'footrest': footrest, 'flex_seats': flex,
            'sofas': sum(1 for p in ps if base_role(p.role) == 'диван')}


def valid_connected_armchairs(room: Room, ps: list[Placement], media_angle_max: float = 45.0) -> dict:
    """Q5 свода №13 (Codex): считать не «сырые» кресла, а кресла с ВАЛИДНЫМ intent в связном
    шаблоне: входит в атомарную зону (tpl_id seating|quiet|reading|bay), intent по форме:
    media_* — фактический угол к ТВ ≤ порога; conversation/quiet/reading — членство в зоне
    (целостность группы держит шаблон). Экспорт по каждому креслу: role/zone/shape/valid."""
    tv = _find(ps, CARRIER)
    out = []
    for p in ps:
        if base_role(p.role) != 'кресло':
            continue
        zone = (getattr(p, 'tpl_id', '') or '')
        shape = (getattr(p, 'tpl_variant', '') or '').split('+')[0]
        in_zone = bool(zone)
        if shape.startswith('media_'):
            ok = in_zone and tv is not None and _angle_to(p, tv.x, tv.y) <= media_angle_max
            intent = 'media'
        else:
            ok = in_zone
            intent = 'quiet' if zone in ('quiet', 'reading', 'bay_armchair') else 'conversation'
        out.append({'role': p.role, 'zone': zone or None, 'shape': shape or None, 'intent': intent, 'valid': bool(ok)})
    return {'armchairs': out, 'valid_count': sum(1 for a in out if a['valid']), 'total': len(out)}


def view_metrics(room: Room, ps: list[Placement]) -> dict:
    """Все метрики Q0 одним словарём — для артефакта `_view`."""
    return {
        'entry_sightline_gap_cm': entry_sightline_gap_cm(room, ps),
        'armchair_tv_angles': armchair_tv_angles(ps),
        'armchair_tv_dist_cm': armchair_tv_dist_cm(ps),
        'sofa_tv_dist_cm': sofa_tv_dist_cm(ps),
        'dining_view_cone_overlap_pct': dining_view_cone_overlap_pct(room, ps),
        'frontal_companions': frontal_companions(room, ps),
        'seating': realized_seating(ps),
        'seat_intents': valid_connected_armchairs(room, ps),
    }

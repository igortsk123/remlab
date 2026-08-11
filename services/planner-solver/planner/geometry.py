"""Геометрия ядра: footprint-полигоны, зоны исключения, свободный полигон.

Ключевая механика — из ProcTHOR (Apache-2.0, идея; код не копировался):
клиренс НЕ проверяется постфактум, а ВЫЧИТАЕТСЯ из свободного полигона вместе с самим
предметом. Тогда «перед диваном» физически некуда поставить кресло — ошибка не возникает,
а не отлавливается. См. `.memory_bank/guides/layout-mined-rules.md`, п. 2 раздела «Чем дополняем».
"""
from __future__ import annotations

import math

from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .clearances import ClearanceSpec, clearance_for
from .models import Item, Opening, Placement, Radiator, Room

SAFE_GAP_CM = 3.0   # запас у статических блокеров (дверь/радиатор): касание = нарушение


# «Лицо» предмета по повороту (см. models: rot 0 → +y, 90 → +x, 180 → −y, 270 → −x)
def facing_vector(rot: float) -> tuple[float, float]:
    r = math.radians(rot)
    return (math.sin(r), math.cos(r))


def quantize_rot(rot: float) -> int:
    """Квантование к осевым 0/90/180/270 (инвариант «параллельно стенам»: PT, Holodeck-MILP)."""
    return int(round((rot % 360) / 90) % 4) * 90


_FP_CACHE: dict[tuple, Polygon] = {}   # beam гоняет одни и те же footprint'ы тысячи раз
_AZ_CACHE: dict[tuple, Polygon] = {}   # то же для зон доступа (профиль 11.08: 100k вызовов,
                                       # 16 с из 94 — вторая по весу статья после validate)


def base_role(role: str) -> str:
    """«кресло 2»/«диван 2» → базовая роль: правила и кандидаты экземпляра те же, что у первого
    (Z4: составы содержат пары — солвер обязан их понимать, а не терять)."""
    parts = role.rsplit(" ", 1)
    return parts[0] if len(parts) == 2 and parts[1].isdigit() else role


def footprint(p: Placement, item: Item | None = None) -> Polygon:
    """Полигон следа предмета на полу с учётом поворота (Г-диван — 6 точек)."""
    it = item or p.item
    if it is None:
        raise ValueError(f"footprint({p.role}): нет габаритов (item=None)")
    key = (it.role, it.w_cm, it.d_cm, it.corner, it.corner_section_cm, it.corner_left,
           round(p.x, 2), round(p.y, 2), round(p.rot, 2))
    hit = _FP_CACHE.get(key)
    if hit is not None:
        return hit
    if it.corner:
        poly = _corner_polygon(it)
    else:
        poly = box(-it.w_cm / 2, -it.d_cm / 2, it.w_cm / 2, it.d_cm / 2)
    poly = rotate(poly, -p.rot, origin=(0, 0), use_radians=False)
    poly = translate(poly, p.x, p.y)
    if len(_FP_CACHE) > 200_000:
        _FP_CACHE.clear()
    _FP_CACHE[key] = poly
    return poly


def _corner_polygon(it: Item) -> Polygon:
    """Г-образный диван: длинная секция (w × section) + короткое плечо на стороне +x.

    Локальные координаты: спинка длинной секции — на −y (сторона стены), лицо — на +y
    (совпадает с направлением facing при rot 0).
    """
    w, d, s = it.w_cm, max(it.d_cm, it.corner_section_cm + 1), it.corner_section_cm
    pts = [
        (-w / 2, -d / 2),
        (w / 2, -d / 2),
        (w / 2, d / 2),
        (w / 2 - s, d / 2),
        (w / 2 - s, -d / 2 + s),
        (-w / 2, -d / 2 + s),
    ]
    if it.corner_left:            # плечо на другой стороне — зеркалим по X (иначе след выходит
        pts = [(-x, y) for x, y in pts]   # зеркальным и мебель врезается друг в друга)
    return Polygon(pts)


def access_zone(p: Placement, item: Item | None = None, spec: ClearanceSpec | None = None) -> Polygon:
    """Функциональная зона доступа: полоса перед лицом + боковые/тыловые отступы.

    Возвращает ТОЛЬКО зону (без самого footprint) — для проверок «зона свободна».
    """
    it = item or p.item
    sp = spec or clearance_for(p.role)
    if it is None:
        raise ValueError(f"access_zone({p.role}): нет габаритов")
    key = (p.role, it.w_cm, it.d_cm, sp.front_cm, sp.side_cm, sp.back_cm,
           round(p.x, 2), round(p.y, 2), round(p.rot, 2))
    hit = _AZ_CACHE.get(key)
    if hit is not None:
        return hit
    w, d = it.w_cm, it.d_cm
    parts = []
    if sp.front_cm > 0:  # перед лицом (+y в локальных координатах, см. facing_vector)
        parts.append(box(-w / 2, d / 2, w / 2, d / 2 + sp.front_cm))
    if sp.side_cm > 0:
        parts.append(box(-w / 2 - sp.side_cm, -d / 2, -w / 2, d / 2))
        parts.append(box(w / 2, -d / 2, w / 2 + sp.side_cm, d / 2))
    if sp.back_cm > 0:   # за спинкой (−y): вентзазор/проход
        parts.append(box(-w / 2, -d / 2 - sp.back_cm, w / 2, -d / 2))
    if not parts:
        _AZ_CACHE[key] = Polygon()
        return _AZ_CACHE[key]
    zone = unary_union(parts)
    zone = rotate(zone, -p.rot, origin=(0, 0), use_radians=False)
    zone = translate(zone, p.x, p.y)
    if len(_AZ_CACHE) > 200_000:
        _AZ_CACHE.clear()
    _AZ_CACHE[key] = zone
    return zone


def seating_front_offset(item: Item) -> float:
    """Расстояние от центра предмета до его ФРОНТА вдоль оси «лица» (см).

    Для Г-дивана фронт — передняя грань длинной секции, а не край короткого плеча:
    иначе столик и ТВ отмеряются от плеча и уезжают на 60+ см от места, где сидят.
    """
    if not item.corner:
        return item.d_cm / 2
    d = max(item.d_cm, item.corner_section_cm + 1)
    return item.corner_section_cm - d / 2


def front_gap(anchor: Placement, target: Placement) -> float:
    """Зазор от фронта якоря до ближней грани цели вдоль оси «лица» якоря (см)."""
    if anchor.item is None or target.item is None:
        return footprint(anchor).distance(footprint(target))
    fwd, _lat = relative_position(anchor, target)
    tw, td = (target.item.d_cm, target.item.w_cm) if int(target.rot) % 180 == 90 else (target.item.w_cm, target.item.d_cm)
    near = abs(fwd) - td / 2
    return near - seating_front_offset(anchor.item)


def relative_position(anchor: Placement, target: Placement) -> tuple[float, float]:
    """Позиция target в ЛОКАЛЬНОЙ системе anchor: (вперёд вдоль лица, вбок).

    Формализует Holodeck-MILP «in front of / side of»: боковой разброс ограничивается
    полушириной якоря, иначе «перед диваном» превращается в «где-то сбоку».
    """
    fx, fy = facing_vector(anchor.rot)
    dx, dy = target.x - anchor.x, target.y - anchor.y
    forward = dx * fx + dy * fy
    lateral = dx * (-fy) + dy * fx
    return forward, lateral


def blocked_footprint(p: Placement, item: Item | None = None) -> Polygon:
    """След + зона доступа одним полигоном — то, что вычитается из свободного места."""
    it = item or p.item
    return unary_union([footprint(p, it), access_zone(p, it)])


def room_polygon(room: Room) -> Polygon:
    if room.contour:
        p = Polygon(room.contour)
        return p if p.exterior.is_ccw else Polygon(room.contour[::-1])
    return box(0, 0, room.width_cm, room.depth_cm)


def room_edges(room: Room) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    """Рёбра контура (CCW): внутренняя нормаль каждого — слева от направления ребра (Э8)."""
    coords = list(room_polygon(room).exterior.coords)
    return [(coords[i], coords[i + 1]) for i in range(len(coords) - 1)]


def opening_polygon(room: Room, op: Opening) -> Polygon:
    """Проём как полоса на стене (толщина 1 см) — для проверки «мебель не перекрывает окно»."""
    return _wall_strip(room, op.wall, op.offset_cm, op.width_cm, 1.0)


def swing_polygon(room: Room, op: Opening) -> Polygon:
    """Зона открывания двери внутрь комнаты (Holodeck: блокер с обеих сторон проёма).

    Полукруг радиуса swing_cm от проёма — консервативно берём прямоугольную полосу
    (по нашему occupancy: clear_radius_before_door_cm = 100).
    """
    if op.kind == "window" or op.swing_cm <= 0:
        return Polygon()
    # +SAFE_GAP: предмет ВПЛОТНУЮ к дуге у соседней проверки (intersects) уже считается
    # нарушением — держим зазор (прямоугольником, БЕЗ buffer: круглые углы плодят вершины,
    # а перебор свободных прямоугольников квадратично чувствителен к их числу)
    return _wall_strip(room, op.wall, op.offset_cm - SAFE_GAP_CM, op.width_cm + 2 * SAFE_GAP_CM,
                       op.swing_cm + SAFE_GAP_CM)


def radiator_polygon(room: Room, rad: Radiator) -> Polygon:
    return _wall_strip(room, rad.wall, rad.offset_cm, rad.width_cm, rad.depth_cm)


def _wall_strip(room: Room, wall: str, offset: float, width: float, depth: float) -> Polygon:
    W, D = room.width_cm, room.depth_cm
    if wall == "south":
        return box(offset, 0, offset + width, depth)
    if wall == "north":
        return box(offset, D - depth, offset + width, D)
    if wall == "west":
        return box(0, offset, depth, offset + width)
    if wall == "east":
        return box(W - depth, offset, W, offset + width)
    raise ValueError(f"неизвестная стена: {wall}")


def static_blockers(room: Room) -> list[Polygon]:
    """Зоны, занятые ДО расстановки: дуги дверей + радиаторы (окна не блокируют пол)."""
    out: list[Polygon] = []
    for op in room.openings:
        sw = swing_polygon(room, op)
        if not sw.is_empty:
            out.append(sw)
    for rad in room.radiators:
        out.append(radiator_polygon(room, rad))
    return out


def free_space(room: Room, placements: list[Placement], *, with_clearance: bool = True,
               ignore_access_of: frozenset[str] | set[str] = frozenset()) -> Polygon:
    """«Открытый полигон» комнаты: комната − двери/радиаторы − (следы [+ клиренсы]).

    `ignore_access_of` — роли, чьи зоны подхода не блокируют (предметы ОДНОЙ зоны: кресло
    легитимно стоит у фронта дивана сбоку — ProcTHOR внутри ассет-группы margin не применяет).
    """
    poly = room_polygon(room)
    blockers = static_blockers(room)
    for p in placements:
        # L6 (set112/121: столик не вставал, пуф 0%, стулья на ковре гибли): ковёр — ПОДЛОЖКА,
        # мебель на нём СТОИТ (front-legs канон). check_collisions его пропускает — free_space
        # обязан быть симметричен, иначе ковёр, встав раньше (шов двухпрохода), выедал зону
        # столика/пуфа/стульев и роли терялись без следа.
        if base_role(p.role) == "ковёр":
            continue
        # экземпляры («стул 2») — члены той же группы, что и базовая роль
        skip_access = p.role in ignore_access_of or base_role(p.role) in ignore_access_of
        blockers.append(footprint(p) if (not with_clearance or skip_access) else blocked_footprint(p))
    if blockers:
        poly = poly.difference(unary_union(blockers))
    return poly


def floor_used_pct(room: Room, placements: list[Placement]) -> float:
    """Доля пола под мебелью (без клиренсов) — сверяется с динамическим капом occupancy."""
    if not placements:
        return 0.0
    used = unary_union([footprint(p) for p in placements]).area
    return 100.0 * used / (room.width_cm * room.depth_cm)


def largest_free_rectangles(poly: Polygon, min_side_cm: float = 50.0, limit: int = 24) -> list[Polygon]:
    """Максимальные осевые прямоугольники внутри свободного полигона (кандидат-ген Э2).

    Приближение решётками: координаты рёбер полигона задают сетку; для каждой пары
    вертикальных линий берём максимальную непрерывную полосу по вертикали. Достаточно
    для прямоугольных комнат с прямоугольными вырезами (наш случай Э1/Э2).
    """
    if poly.is_empty:
        return []
    geoms = [poly] if poly.geom_type == "Polygon" else list(poly.geoms)
    xs, ys = set(), set()
    for g in geoms:
        for x, y in g.exterior.coords:
            xs.add(round(x, 3))
            ys.add(round(y, 3))
        for ring in g.interiors:
            for x, y in ring.coords:
                xs.add(round(x, 3))
                ys.add(round(y, 3))
    # квантуем координаты: перебор пар по обеим осям квартичен, лишние вершины его убивают
    xs = sorted({round(v / 5) * 5 for v in xs})
    ys = sorted({round(v / 5) * 5 for v in ys})
    rects: list[Polygon] = []
    for i in range(len(xs) - 1):
        for j in range(i + 1, len(xs)):
            if xs[j] - xs[i] < min_side_cm:
                continue
            for a in range(len(ys) - 1):
                for b in range(a + 1, len(ys)):
                    if ys[b] - ys[a] < min_side_cm:
                        continue
                    r = box(xs[i], ys[a], xs[j], ys[b])
                    if poly.contains(r.buffer(-0.5)):
                        rects.append(r)
    rects.sort(key=lambda r: -r.area)
    out: list[Polygon] = []
    for r in rects:  # выкидываем прямоугольники, вложенные в уже взятые (оставляем максимальные)
        if not any(o.contains(r.buffer(-0.5)) for o in out):
            out.append(r)
        if len(out) >= limit:
            break
    return out

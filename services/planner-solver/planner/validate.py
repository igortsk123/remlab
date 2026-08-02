"""Hard-валидация раскладки: объяснимые нарушения вместо «да/нет».

Каждая проверка возвращает Violation с кодом, ролями и фактическим числом — это вход
для объяснений top-K (Э5) и для регресс-метрик (Collision-Free / In-Boundary, LayoutVLM).
"""
from __future__ import annotations

from shapely.geometry import Polygon
from shapely.ops import unary_union

from .clearances import (LOW_ITEM_MAX_H_CM, NEVER_BLOCKING_ROLES, band_scale, distances,
                         passage_min_cm)
from .geometry import (
    access_zone,
    footprint,
    free_space,
    opening_polygon,
    radiator_polygon,
    room_polygon,
    static_blockers,
    swing_polygon,
)
from .models import Layout, Placement, Room, Severity, Violation

EPS = 1.0  # см: допуск на округления (Holodeck EPSILON=1 см в наших единицах)


def _v(code: str, msg: str, roles: list[str], value: float | None = None, expected: str | None = None,
       severity: Severity = Severity.HARD) -> Violation:
    return Violation(code=code, severity=severity, message=msg, roles=roles, value=value, expected=expected)


def check_boundary(room: Room, ps: list[Placement]) -> list[Violation]:
    rp = room_polygon(room).buffer(EPS)
    out = []
    for p in ps:
        fp = footprint(p)
        if not rp.contains(fp):
            out.append(_v("OUT_OF_ROOM", f"«{p.role}» выходит за пределы комнаты", [p.role],
                          round(fp.difference(rp).area / 100, 1), "0 м² вне комнаты"))
    return out


def check_collisions(ps: list[Placement]) -> list[Violation]:
    out = []
    for i, a in enumerate(ps):
        fa = footprint(a)
        for b in ps[i + 1:]:
            inter = fa.intersection(footprint(b)).area
            if inter > EPS * EPS:
                out.append(_v("COLLISION", f"«{a.role}» пересекается с «{b.role}»", [a.role, b.role],
                              round(inter / 100, 1), "0 м² пересечения"))
    return out


def check_openings(room: Room, ps: list[Placement]) -> list[Violation]:
    out = []
    for op in room.openings:
        swing = swing_polygon(room, op)
        if swing.is_empty:
            continue
        for p in ps:
            if footprint(p).intersects(swing.buffer(-EPS)):
                out.append(_v("DOOR_SWING", f"«{p.role}» стоит в зоне открывания двери", [p.role],
                              None, f"дуга {op.swing_cm:.0f} см свободна"))
        # окно не перекрываем высокой мебелью — проверка по высоте (h выше подоконника)
    for op in room.openings:
        if op.kind != "window":
            continue
        win = opening_polygon(room, op)
        for p in ps:
            h = (p.item.h_cm if p.item else None) or 0
            if h > max(op.sill_cm, 80) and footprint(p).distance(win) < 10:
                out.append(_v("WINDOW_BLOCKED", f"«{p.role}» ({h:.0f} см) перекрывает окно", [p.role],
                              h, f"ниже подоконника {op.sill_cm:.0f} см"))
    return out


def check_radiators(room: Room, ps: list[Placement]) -> list[Violation]:
    hard = distances().get("sofa_to_radiator_wall", [15, 20])[0]
    out = []
    for rad in room.radiators:
        zone = radiator_polygon(room, rad).buffer(hard)
        for p in ps:
            if footprint(p).intersects(zone.buffer(-EPS)):
                out.append(_v("RADIATOR", f"«{p.role}» ближе {hard:.0f} см к радиатору", [p.role],
                              hard, f"≥{hard:.0f} см"))
    return out


def check_access(ps: list[Placement]) -> list[Violation]:
    """Функциональная зона (подход/ноги/фасады) не должна быть занята другим предметом."""
    out = []
    for a in ps:
        zone = access_zone(a)
        if zone.is_empty:
            continue
        for b in ps:
            if b is a or b.role in NEVER_BLOCKING_ROLES:
                continue
            bh = (b.item.h_cm if b.item else None)
            if bh is not None and bh <= LOW_ITEM_MAX_H_CM:
                continue   # низкий предмет (столик/пуф) подход не перекрывает
            inter = zone.intersection(footprint(b)).area
            if inter > 100:  # >0.01 м² — не округление
                out.append(_v("ACCESS_BLOCKED",
                              f"«{b.role}» перекрывает подход к «{a.role}»", [a.role, b.role],
                              round(inter / 100, 1), "зона подхода свободна"))
    return out


def check_passages(room: Room, ps: list[Placement], kind: str = "secondary") -> list[Violation]:
    """Связность: от двери можно дойти до каждого предмета проходом нужной ширины."""
    need = passage_min_cm(kind)
    free = free_space(room, ps, with_clearance=False)
    for b in static_blockers(room):
        free = free.difference(b)
    core = free.buffer(-need / 2)  # эрозия: остаётся то, где проходит человек
    if core.is_empty:
        return [_v("NO_PASSAGE", f"в комнате не осталось прохода {need:.0f} см", [], 0, f"≥{need:.0f} см")]
    parts = [core] if core.geom_type == "Polygon" else list(core.geoms)
    doors = [swing_polygon(room, op) for op in room.openings if op.kind in ("door", "balcony")]
    entry = unary_union([d for d in doors if not d.is_empty]) if doors else None
    if entry is None or entry.is_empty:
        main = max(parts, key=lambda g: g.area)
    else:
        touching = [g for g in parts if g.buffer(need).intersects(entry)]
        if not touching:
            return [_v("DOOR_UNREACHABLE", "от двери нет прохода в комнату", [], None, f"≥{need:.0f} см")]
        main = max(touching, key=lambda g: g.area)
    out = []
    for p in ps:
        reach = footprint(p).buffer(need / 2 + EPS)
        if not reach.intersects(main):
            out.append(_v("UNREACHABLE", f"к «{p.role}» нет прохода {need:.0f} см", [p.role],
                          need, f"≥{need:.0f} см"))
    return out


def check_distances(room: Room, ps: list[Placement]) -> list[Violation]:
    """Шкалы проекта от площади: диван↔ТВ, диван↔столик (решения владельца)."""
    by = {p.role: p for p in ps}
    out = []
    tv = band_scale("sofa_tv_cm", room.band, distances().get("sofa_tv_cm", [180, 300]))
    tbl = band_scale("sofa_table_cm", room.band, distances().get("sofa_coffee_table", [36, 50]))
    if "диван" in by and "тв-тумба" in by:
        g = footprint(by["диван"]).distance(footprint(by["тв-тумба"]))
        if not (tv[0] - EPS <= g <= tv[1] + EPS):
            out.append(_v("SOFA_TV_DIST", f"диван↔ТВ {g:.0f} см вне шкалы", ["диван", "тв-тумба"],
                          round(g), f"{tv[0]:.0f}–{tv[1]:.0f} см"))
    if "диван" in by and "столик" in by:
        g = footprint(by["диван"]).distance(footprint(by["столик"]))
        if not (tbl[0] - EPS <= g <= tbl[1] + EPS):
            out.append(_v("SOFA_TABLE_DIST", f"диван↔столик {g:.0f} см вне шкалы", ["диван", "столик"],
                          round(g), f"{tbl[0]:.0f}–{tbl[1]:.0f} см"))
    if "диван" in by and "кресло" in by:
        g = footprint(by["диван"]).distance(footprint(by["кресло"]))
        lim = distances().get("facing_seats", [110, 240])[1]
        if g > lim + EPS:
            out.append(_v("SEATS_TOO_FAR", f"диван↔кресло {g:.0f} см — зона разорвана", ["диван", "кресло"],
                          round(g), f"≤{lim:.0f} см"))
    return out


def check_floor_cap(room: Room, ps: list[Placement]) -> list[Violation]:
    from .geometry import floor_used_pct

    cap = band_scale("floor_cap_pct", room.band, [26, 50])
    used = floor_used_pct(room, ps)
    if used > cap[1] + 0.5:
        return [_v("FLOOR_OVERFILL", f"мебель занимает {used:.0f}% пола", [], round(used, 1),
                   f"≤{cap[1]:.0f}%")]
    return []


def validate(room: Room, placements: list[Placement], *, passage: str = "secondary") -> Layout:
    vs: list[Violation] = []
    vs += check_boundary(room, placements)
    vs += check_collisions(placements)
    vs += check_openings(room, placements)
    vs += check_radiators(room, placements)
    vs += check_access(placements)
    vs += check_passages(room, placements, passage)
    vs += check_distances(room, placements)
    vs += check_floor_cap(room, placements)
    from .geometry import floor_used_pct

    return Layout(room=room, placements=placements, violations=vs,
                  floor_used_pct=round(floor_used_pct(room, placements), 1))

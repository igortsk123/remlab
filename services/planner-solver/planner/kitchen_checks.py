"""ПРОВЕРКИ КУХНИ — плагин типа комнаты `kitchen` (реестр `planner/room_registry.py:PLAGINY`, T-20261105-37; план
room-pipeline-01, onb-09 Т2). Общие физические — из `validate` (вне комнаты, пересечения, двери, радиаторы, у стены),
свои — по нормам `rules/kitchen.json`: высокое (колонны, холодильник) не у откоса окна, нижний ряд под окном только при
высоком подоконнике, рабочий проход перед рядом свободен. Предметы — роли `planner/kitchen.py` (`kitchen_placements`:
посадка → предметы); та же геометрия, что держит посадка, — вторая, независимая проверка её ответа.
"""
from __future__ import annotations

from shapely.geometry import box

from .geometry import facing_vector, floor_used_pct, footprint
from .kitchen import H_CM, ROLE_FRIDGE, ROLE_RUN, ROLE_TABLE, ROLE_TALL, _Statics, rule
from .models import Layout, Placement, Room, Severity, Violation
from .validate import _v, check_boundary, check_collisions, check_openings, check_radiators, check_wall_only

TALL_ROLES = (ROLE_TALL, ROLE_FRIDGE)


def check_kitchen_windows(room: Room, ps: list[Placement]) -> list[Violation]:
    """Колонна и холодильник — не ближе `window_clear_cm` к откосу; нижний ряд под окном — только при подоконнике
    не ниже `base_under_window_min_sill_cm` (`rules/kitchen.json` openings)."""
    st = _Statics(room)
    out = []
    for p in ps:
        fp = footprint(p)
        if p.role in TALL_ROLES and any(fp.intersection(ob).area > 0.5 for _, ob in st.tall):
            out.append(_v("KITCHEN_WINDOW_TALL", f"«{p.role}» у окна: закрывает откос и свет", [p.role],
                          rule("openings", "window_clear_cm"), "≥ 10 см от откоса"))
        if p.role == ROLE_RUN and any(fp.intersection(ob).area > 0.5 for _, ob in st.base):
            out.append(_v("KITCHEN_WINDOW_SILL", f"«{p.role}» под окном с низким подоконником", [p.role],
                          None, f"подоконник ≥ {rule('openings', 'base_under_window_min_sill_cm'):.0f} см"))
    return out


def check_kitchen_aisle(room: Room, ps: list[Placement], cooks: int = 1) -> list[Violation]:
    """Перед рядом — рабочий проход нормы (107, вдвоём 122): в комнате и без других предметов на полу."""
    work = rule("aisle", "work_two_cooks_cm" if cooks == 2 else "work_one_cook_cm")
    rp = box(0, 0, room.width_cm, room.depth_cm)
    out = []
    for p in ps:
        if p.role != ROLE_RUN:
            continue
        x0, y0, x1, y1 = footprint(p).bounds
        fx, fy = facing_vector(p.rot)
        if abs(fy) > abs(fx):
            zone = box(x0, y1, x1, y1 + work) if fy > 0 else box(x0, y0 - work, x1, y0)
        else:
            zone = box(x1, y0, x1 + work, y1) if fx > 0 else box(x0 - work, y0, x0, y1)
        short = zone.difference(rp).area > 0.5
        hit = [q.role for q in ps if q is not p and footprint(q).intersection(zone).area > 0.5]
        if short or hit:
            out.append(_v("KITCHEN_AISLE", f"рабочий проход перед «{p.role}» меньше {work:.0f} см"
                          + (f" — мешает {', '.join(hit)}" if hit else ""), [p.role, *hit], work, f"≥ {work:.0f} см"))
    return out


def check_kitchen_parts(ps: list[Placement]) -> list[Violation]:
    """В кухне есть ряд; стол — мягко (не в каждой кухне он встаёт)."""
    roles = {p.role for p in ps}
    out = []
    if ROLE_RUN not in roles:
        out.append(_v("KITCHEN_NO_RUN", "в кухне нет ряда гарнитура", [ROLE_RUN]))
    if ROLE_TABLE not in roles:
        out.append(_v("KITCHEN_NO_TABLE", "обеденный стол не встал", [ROLE_TABLE], severity=Severity.SOFT))
    return out


def validate_kitchen(room: Room, placements: list[Placement], *, passage: str = "secondary",
                     fast_hard: bool = False) -> Layout:
    checks = [
        lambda: check_boundary(room, placements),
        lambda: check_collisions(placements),
        lambda: check_openings(room, placements),
        lambda: check_radiators(room, placements),
        lambda: check_wall_only(room, placements),
        lambda: check_kitchen_parts(placements),
        lambda: check_kitchen_windows(room, placements),
        lambda: check_kitchen_aisle(room, placements),
    ]
    vs: list[Violation] = []
    for chk in checks:
        vs += chk()
        if fast_hard and any(v.severity is Severity.HARD for v in vs):
            return Layout(room=room, placements=placements, violations=vs, floor_used_pct=0.0)
    return Layout(room=room, placements=placements, violations=vs,
                  floor_used_pct=round(floor_used_pct(room, placements), 1))


__all__ = ["validate_kitchen", "check_kitchen_windows", "check_kitchen_aisle", "check_kitchen_parts", "H_CM"]

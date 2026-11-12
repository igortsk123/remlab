"""Проверки СПАЛЬНИ (план onb-05, ADR-0330 п.1/7): общие физические проверки гостиной + свои нормы спальни.

Путь гостиной не трогается: `validate.validate` зовёт `validate_bedroom` только при `room.room_type == "bedroom"`.
Числа — `rules/occupancy.json` `distances_cm` (одно число — одно место), состав и шаблоны — `rules/bedroom.json`.

Кровать в координатах солвера: `item.w_cm` — ширина (поперёк), `item.d_cm` — длина; «лицо» (rot) смотрит
от изголовья к изножью, изголовье — спинка у стены (как у шкафа в `check_wall_only`).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shapely.affinity import rotate, translate
from shapely.geometry import box

from .clearances import ClearanceSpec, distances
from .geometry import (access_zone, base_role, facing_vector, floor_used_pct, footprint, opening_polygon,
                       radiator_polygon, room_polygon)
from .models import Layout, Placement, Room, Severity, Violation
from .validate import _v, check_boundary, check_collisions, check_openings, check_radiators, check_wall_only, is_flat_floor

BEDROOM_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "bedroom.json"
AREA_EPS = 100.0          # см²: меньше — округление, не нарушение (как в check_access)
WALL_GAP_CM = 10.0        # бок/спинка «у стены» — зазор не больше этого


@lru_cache(maxsize=1)
def bedroom_rules() -> dict:
    return json.loads(BEDROOM_RULES_PATH.read_text(encoding="utf-8"))


def num(key: str, default: float) -> float:
    """Число нормы из `occupancy.json` distances_cm (вилка → нижняя граница)."""
    v = distances().get(key, default)
    return float(v[0]) if isinstance(v, list) else float(v)


def bedroom_role(role: str) -> str:
    """Роль для правил спальни: номер экземпляра снят (`geometry.base_role`: «тумба прикроватная 2»), детская роль —
    её взрослый псевдоним (`rules/bedroom.json` aliases: «кровать детская» → «кровать», «стол детский» → «стол рабочий»,
    «стул детский» → «стул рабочий»): нормы и шаблоны одни (kids-room-01). Взрослым ролям — то же, что `base_role`."""
    b = base_role(role)
    return bedroom_rules().get("aliases", {}).get(b, b)


def is_bed(p: Placement) -> bool:
    return bedroom_role(p.role) == "кровать"


def is_double(p: Placement) -> bool:
    lim = bedroom_rules()["roles"]["кровать"]["double_min_w_cm"]
    return p.item is not None and p.item.w_cm >= lim


def switch(name: str) -> dict:
    """Выключатель правила спальни (`rules/bedroom.json` switches, T-20261112-31): включён — его настройки, иначе {}
    (нет ключа или on=false — прежнее поведение)."""
    s = bedroom_rules().get("switches", {}).get(name) or {}
    return s if s.get("on") else {}


def side_back(p: Placement) -> str | None:
    """Боковая спинка кровати — left | right (бок в осях кровати) | any (по названию, сторона неизвестна) | None.
    Выключатель `switches.bed_side_back` снят — None для всех."""
    if p.item is None or not switch("bed_side_back"):
        return None
    return p.item.side_back


def side_back_denied(purpose: str | None, item) -> bool:
    """Назначение не берёт кровать с боковой спинкой (паре нужен подход с двух сторон, `deny_purposes`)."""
    sw = switch("bed_side_back")
    return bool(sw and item is not None and item.side_back and (purpose or "couple") in sw.get("deny_purposes", ()))


def both_sides(room: Room, p: Placement) -> bool:
    """Подход с ДВУХ сторон — норма пары (Н1); одному, гостю, в кабинете кровать может стоять боком к стене (Н3)."""
    return is_double(p) and (room.purpose or "couple") == "couple"


# Фронт-зоны спальни. Своя таблица, а не `clearances._table`: шкаф спальни держит норму ADR-0330 п.7
# независимо от того, принят ли подъём для гостиной (её путь читает свою таблицу).
def bedroom_spec(role: str) -> ClearanceSpec | None:
    r = bedroom_role(role)
    if r == "шкаф":
        return ClearanceSpec(num("wardrobe_hinged_front_min", 90), 0, 0, "распашной фасад (ADR-0330 п.7)")
    if r == "комод":
        return ClearanceSpec(num("dresser_front", 76), 0, 0, "выдвижной ящик")
    if r in ("туалетный столик", "стол рабочий"):
        return ClearanceSpec(num("desk_chair_clear", 75), 0, 0, "место под стул (Н9)")
    return None


# Тумба — НЕ группа кровати: в проход у бока ей нельзя («тумба в проход не входит», Н1), её место — у изголовья
# (`bed_head_zone`), которое в полосу прохода не входит.
GROUPS = (frozenset({"стол рабочий", "стул рабочий"}),)


def same_group(a: str, b: str) -> bool:
    a, b = bedroom_role(a), bedroom_role(b)
    return any(a in g and b in g for g in GROUPS)


def _local(p: Placement, x0: float, y0: float, x1: float, y1: float):
    """Прямоугольник в локальных координатах предмета (лицо = +y) → комната."""
    return translate(rotate(box(x0, y0, x1, y1), -p.rot, origin=(0, 0), use_radians=False), p.x, p.y)


def bed_zones(p: Placement) -> dict:
    """Полосы прохода кровати: левый/правый бок (без места тумбы у изголовья) и изножье."""
    w, d = p.item.w_cm, p.item.d_cm
    side, foot, head = num("bed_side_passage", 75), num("bed_foot_min", 60), num("bed_head_zone", 50)
    head = min(head, d)
    return {
        "left": _local(p, -w / 2 - side, -d / 2 + head, -w / 2, d / 2),
        "right": _local(p, w / 2, -d / 2 + head, w / 2 + side, d / 2),
        "foot": _local(p, -w / 2, d / 2, w / 2, d / 2 + foot),
        "left_wall": _local(p, -w / 2 - WALL_GAP_CM, -d / 2, -w / 2, d / 2),
        "right_wall": _local(p, w / 2, -d / 2, w / 2 + WALL_GAP_CM, d / 2),
        "back": back_strip(p),
    }


def _zone_clear(room: Room, zone, others: list[Placement]) -> bool:
    rp = room_polygon(room)
    if zone.difference(rp).area > AREA_EPS:
        return False
    for r in room.radiators:
        if zone.intersection(radiator_polygon(room, r)).area > AREA_EPS:
            return False
    return not any(zone.intersection(footprint(o)).area > AREA_EPS for o in others if not is_flat_floor(o))


def _against_wall(room: Room, strip) -> bool:
    """Узкая полоса у бока лежит за стеной (бок к стене)."""
    return strip.difference(room_polygon(room)).area >= 0.8 * strip.area


def bed_template(room: Room) -> str | None:
    """Шаблон кровати, который назначение задаёт явно (`rules/bedroom.json` purposes[*].bed_template; сейчас только
    single_narrow → bed_narrow_wall). У прежних назначений ключа нет — None, их путь не меняется."""
    return (bedroom_rules()["purposes"].get(room.purpose or "") or {}).get("bed_template")


def side_on_wall(room: Room, p: Placement) -> bool:
    """Длинный бок кровати у стены (зазор ≤ WALL_GAP_CM) — признак шаблона bed_narrow_wall."""
    z = bed_zones(p)
    return _against_wall(room, z["left_wall"]) or _against_wall(room, z["right_wall"])


def head_wall(p: Placement) -> str:
    return {0: "south", 90: "west", 180: "north", 270: "east"}[int(p.rot) % 360]


def check_bed(room: Room, ps: list[Placement]) -> list[Violation]:
    out = []
    for b in [p for p in ps if is_bed(p) and p.item is not None]:
        z = bed_zones(b)
        others = [o for o in ps if o is not b]
        sides = {s: _zone_clear(room, z[s], others) for s in ("left", "right")}
        need = num("bed_side_passage", 75)
        if both_sides(room, b):
            for s, ok in sides.items():
                if not ok:
                    out.append(_v("BED_SIDE_PASSAGE", f"у «{b.role}» нет прохода {need:.0f} см сбоку ({s})", [b.role],
                                  need, f"≥{need:.0f} см с обеих сторон двуспальной"))
        elif not any(sides.values()):
            out.append(_v("BED_SIDE_PASSAGE", f"к «{b.role}» нет подхода {need:.0f} см ни с одного бока", [b.role],
                          need, f"≥{need:.0f} см с одной стороны"))
        if not _zone_clear(room, z["foot"], others):
            foot = num("bed_foot_min", 60)
            out.append(_v("BED_FOOT_PASSAGE", f"у изножья «{b.role}» меньше {foot:.0f} см", [b.role],
                          foot, f"≥{foot:.0f} см у изножья"))
        # изголовье — к СПЛОШНОЙ стене: спинка у стены и за ней нет двери/балкона
        if not _against_wall(room, z["back"]):
            out.append(_v("BED_HEAD_WALL", f"изголовье «{b.role}» не у стены", [b.role], None,
                          "изголовье к сплошной стене"))
        for op in room.openings:
            hit = z["back"].intersects(opening_polygon(room, op).buffer(2))
            if hit and op.kind in ("door", "balcony", "opening"):
                out.append(_v("BED_HEAD_WALL", f"изголовье «{b.role}» закрывает проём", [b.role], None,
                              "изголовье к сплошной стене"))
            elif hit and op.kind == "window":
                out.append(_v("BED_HEAD_WINDOW", f"изголовье «{b.role}» под окном", [b.role], None,
                              "изголовье не под окном", Severity.SOFT))
        if any(op.kind in ("door", "balcony") and op.wall == head_wall(b) for op in room.openings):
            out.append(_v("BED_DOOR_WALL", f"изголовье «{b.role}» на стене двери", [b.role], None,
                          "изголовье не на стене двери", Severity.SOFT))
        sb = side_back(b)
        if sb:
            if side_back_denied(room.purpose, b.item):
                out.append(_v("BED_SIDE_BACK_COUPLE", f"у «{b.role}» боковая спинка — паре нужен подход с двух сторон",
                              [b.role], None, "кровать без боковой спинки"))
            walls = {s: _against_wall(room, z[f"{s}_wall"]) for s in ("left", "right")}
            if not (walls[sb] if sb in walls else any(walls.values())):
                out.append(_v("BED_SIDE_BACK_OFF_WALL", f"боковая спинка «{b.role}» не у стены", [b.role], None,
                              "в угол, боковой спинкой к стене"))
        if bed_template(room) == "bed_narrow_wall" and not is_double(b) and not side_on_wall(room, b):
            out.append(_v("BED_NARROW_OFF_WALL", f"длинный бок «{b.role}» не у стены", [b.role], None,
                          "узкая кровать боком к стене (шаблон bed_narrow_wall)", Severity.SOFT))
        soft = num("bed_radiator_soft", 50)
        for r in room.radiators:
            dist = footprint(b).distance(radiator_polygon(room, r))
            if dist < soft:
                out.append(_v("BED_NEAR_RADIATOR", f"«{b.role}» в {dist:.0f} см от радиатора", [b.role],
                              round(dist), f"≥{soft:.0f} см", Severity.SOFT))
    return out


def back_strip(p: Placement, depth: float = 15.0):
    """Полоса за спинкой предмета: лежит за стеной — предмет стоит спинкой к стене."""
    w, d = p.item.w_cm, p.item.d_cm
    return _local(p, -w / 2, -d / 2 - depth, w / 2, -d / 2)


def nightstand_ok(room: Room, n: Placement, beds: list[Placement]) -> bool:
    """Тумба — вплотную к боку кровати, тем же поворотом и спинкой к стене (в Г-комнате не «висит» за концом стены)."""
    return _against_wall(room, back_strip(n)) and any(
        footprint(n).distance(footprint(b)) <= WALL_GAP_CM and int(n.rot) % 360 == int(b.rot) % 360 for b in beds)


def check_nightstands(room: Room, ps: list[Placement]) -> list[Violation]:
    beds = [p for p in ps if is_bed(p)]
    out = []
    for n in [p for p in ps if bedroom_role(p.role) == "тумба прикроватная"]:
        ok = nightstand_ok(room, n, beds)
        if not ok:
            out.append(_v("NIGHTSTAND_DETACHED", f"«{n.role}» не у изголовья кровати", [n.role], None,
                          "у изголовья, спинкой к той же стене", Severity.SOFT))
    return out


def check_bedroom_access(room: Room, ps: list[Placement]) -> list[Violation]:
    """Фронт-зоны хранения и столов: внутри комнаты и свободны (кроме своей группы и ковра)."""
    out = []
    rp = room_polygon(room)
    for a in ps:
        spec = bedroom_spec(a.role)
        if spec is None or a.item is None:
            continue
        zone = access_zone(a, spec=spec)
        if zone.difference(rp).area > AREA_EPS:
            out.append(_v("BR_ACCESS_WALL", f"перед «{a.role}» меньше {spec.front_cm:.0f} см до стены", [a.role],
                          spec.front_cm, f"≥{spec.front_cm:.0f} см перед фасадом"))
        for b in ps:
            if b is a or is_flat_floor(b) or same_group(a.role, b.role):
                continue
            inter = zone.intersection(footprint(b)).area
            if inter > AREA_EPS:
                out.append(_v("BR_ACCESS_BLOCKED", f"«{b.role}» перекрывает подход к «{a.role}»", [a.role, b.role],
                              round(inter / 100, 1), "зона подхода свободна"))
    return out


def check_desk_window(room: Room, ps: list[Placement]) -> list[Violation]:
    wins = [opening_polygon(room, op) for op in room.openings if op.kind == "window"]
    lim = num("desk_window_max", 100)
    out = []
    for d in [p for p in ps if bedroom_role(p.role) == "стол рабочий"]:
        if wins and min(footprint(d).distance(w) for w in wins) > lim:
            out.append(_v("DESK_FAR_FROM_WINDOW", f"«{d.role}» дальше {lim:.0f} см от окна", [d.role], lim,
                          f"≤{lim:.0f} см до окна", Severity.SOFT))
    return out


def light_side(room: Room, desk: Placement) -> str | None:
    """С какой стороны свет ближайшего окна сидящему за столом: front (окно на стене стола, перед глазами) | left | right;
    окна нет — None. Стол стоит спинкой к стене, «лицо» f = `facing_vector(rot)` — в комнату; сидящий смотрит против f.
    ЛЕВО — как в комнате, которую видит покупатель: план (x, y) ложится в сцену как (x, z) three.js (`lib/viewer3d/
    meshes.ts`: `rotation.y = +rot`, y плана → z сцены), а сверху ось z идёт ПО ЧАСОВОЙ от x — план зеркален обычной
    математической плоскости. Поэтому левая рука сидящего — (−f_y, f_x), а не (f_y, −f_x) «по учебнику»."""
    wins = [opening_polygon(room, op) for op in room.openings if op.kind == "window"]
    if not wins or desk.item is None:
        return None
    w = min(wins, key=lambda g: footprint(desk).distance(g))
    fx, fy = facing_vector(desk.rot)
    vx, vy = w.centroid.x - desk.x, w.centroid.y - desk.y
    if vx * fx + vy * fy <= -desk.item.d_cm / 2 + 1:
        return "front"
    return "left" if vx * -fy + vy * fx > 0 else "right"


def check_desk_light(room: Room, ps: list[Placement]) -> list[Violation]:
    """Детская: свет на стол — слева или спереди (правша, ведущую руку не знаем — мягко, Codex 07.11). Взрослым — нет."""
    if room.purpose != "child":
        return []
    return [_v("DESK_LIGHT_RIGHT", f"свет на «{d.role}» справа — тень от руки на тетради", [d.role], None,
               "окно слева или спереди", Severity.SOFT)
            for d in ps if bedroom_role(d.role) == "стол рабочий" and light_side(room, d) == "right"]


def check_bedroom_floor(room: Room, ps: list[Placement]) -> list[Violation]:
    cap = num("bedroom_floor_max_pct", 45)
    used = floor_used_pct(room, [p for p in ps if not is_flat_floor(p)])
    if used > cap:
        return [_v("BEDROOM_FLOOR_OVERFILL", f"мебель занимает {used:.0f} % пола спальни", [], round(used, 1),
                   f"≤{cap:.0f} %", Severity.SOFT)]
    return []


def check_bedroom_passages(room: Room, ps: list[Placement]) -> list[Violation]:
    """Проход 46 см от двери до каждого высокого предмета (`passage_absolute_min_tight`, как у гостиной).

    Отличие от `validate.check_passages`: дуга двери — не стена. В спальне дверь часто открывается в узкий
    карман между кроватью и стеной; общий путь вырезает дугу и считает доступной лишь бо́льшую из частей
    по обе стороны — комод слева от двери выходил «недоступным», хотя к нему идут прямо от входа.
    Здесь доступна ЛЮБАЯ часть, касающаяся дуги двери."""
    from shapely.ops import unary_union

    from .clearances import LOW_ITEM_MAX_H_CM
    from .geometry import free_space, static_blockers, swing_polygon

    need = num("passage_absolute_min_tight", 46)
    free = free_space(room, ps, with_clearance=False)
    for b in static_blockers(room):
        free = free.difference(b)
    core = free.buffer(-need / 2)
    if core.is_empty:
        return [_v("BR_NO_PASSAGE", f"в спальне не осталось прохода {need:.0f} см", [], 0, f"≥{need:.0f} см")]
    parts = [core] if core.geom_type == "Polygon" else list(core.geoms)
    doors = [swing_polygon(room, op) for op in room.openings if op.kind in ("door", "balcony")]
    entry = unary_union([d for d in doors if not d.is_empty]) if doors else None
    if entry is None or entry.is_empty:
        main = max(parts, key=lambda g: g.area)
    else:
        touching = [g for g in parts if g.buffer(need).intersects(entry)]
        if not touching:
            return [_v("BR_DOOR_UNREACHABLE", "от двери нет прохода в спальню", [], None, f"≥{need:.0f} см")]
        main = unary_union(touching)
    out = []
    for p in ps:
        if is_flat_floor(p) or ((p.item.h_cm if p.item else None) or 999) <= LOW_ITEM_MAX_H_CM:
            continue   # низкое (тумба) достают с кровати
        # стол достают через свой стул (стул отодвигают): дошли до стула группы — дошли и до стола (kids-room-01: спальня 2,
        # стол у окна в углу — по бокам стула по 25 см, «нет прохода к столу» было ложным)
        reach = unary_union([footprint(p)] + [footprint(q) for q in ps if q is not p and same_group(p.role, q.role)])
        if not reach.buffer(need / 2 + 1.0).intersects(main):
            out.append(_v("BR_UNREACHABLE", f"к «{p.role}» нет прохода {need:.0f} см", [p.role], need, f"≥{need:.0f} см"))
    return out


def validate_bedroom(room: Room, placements: list[Placement], *, passage: str = "secondary",
                     fast_hard: bool = False) -> Layout:
    checks = [
        lambda: check_boundary(room, placements),
        lambda: check_collisions(placements),
        lambda: check_openings(room, placements),
        lambda: check_radiators(room, placements),
        lambda: check_wall_only(room, placements),
        lambda: check_bed(room, placements),
        lambda: check_bedroom_access(room, placements),
        lambda: check_nightstands(room, placements),
        lambda: check_desk_window(room, placements),
        lambda: check_desk_light(room, placements),
        lambda: check_bedroom_floor(room, placements),
        lambda: check_bedroom_passages(room, placements),   # самая дорогая — последней
    ]
    vs: list[Violation] = []
    for chk in checks:
        vs += chk()
        if fast_hard and any(v.severity is Severity.HARD for v in vs):
            return Layout(room=room, placements=placements, violations=vs, floor_used_pct=0.0)
    return Layout(room=room, placements=placements, violations=vs,
                  floor_used_pct=round(floor_used_pct(room, placements), 1))

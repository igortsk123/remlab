"""Проверки ПРИХОЖЕЙ (план onb-13 Т3, T-20261105-34; по образцу `bedroom_checks.py`, ADR-0330 п.1).

Путь гостиной и спальни не трогается: общие `models.py`/`validate.py` эта задача не меняет (разбор Codex 05.11) — `RoomType`
«hall» и диспетчер по типу комнаты добавляет интегратор (T-37), прихожая регистрируется через его реестр. До того
`validate_hall` и `hall.solve_hall` зовутся напрямую и поле `room.room_type` не читают.
Числа — `rules/occupancy.json` `distances_cm` (одно число — одно место), состав и шаблоны — `rules/hall.json`.

Прихожая — коридор: всё стоит спинкой к стене в линию, середина — проход от входной двери ко всем дверям и предметам.
Двери из прихожей в комнаты чаще открываются В КОМНАТЫ (у прихожей дуги нет, `swing_cm = 0`) — общий `check_openings`
такие двери не видит, поэтому полоса перед каждой дверью держится здесь (`HALL_DOOR_FRONT`). Дуга двери, открывающейся
в прихожую, — не стена для прохода: дверь обычно закрыта, а мебели в дуге нет и так (`DOOR_SWING`).
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from shapely.ops import unary_union

from .bedroom_checks import _against_wall, back_strip
from .clearances import ClearanceSpec, distances
from .geometry import _wall_strip, access_zone, base_role, floor_used_pct, footprint, opening_polygon, room_polygon
from .models import Layout, Opening, Placement, Room, Severity, Violation
from .validate import _v, check_boundary, check_openings, check_radiators, is_flat_floor

HALL_RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "hall.json"
AREA_EPS = 100.0          # см²: меньше — округление, не нарушение (как в bedroom_checks)
EPS = 1.0


@lru_cache(maxsize=1)
def hall_rules() -> dict:
    return json.loads(HALL_RULES_PATH.read_text(encoding="utf-8"))


def num(key: str, default: float) -> float:
    """Число нормы из `occupancy.json` distances_cm (вилка → нижняя граница)."""
    v = distances().get(key, default)
    return float(v[0]) if isinstance(v, list) else float(v)


def role_cfg(role: str) -> dict:
    return hall_rules()["roles"].get(base_role(role), {})


def entrance(room: Room) -> Opening | None:
    """Входная дверь: первая дверь на южной стене (как `entranceWall` просмотрщика), иначе первая дверь комнаты."""
    doors = [op for op in room.openings if op.kind == "door"]
    south = sorted((op for op in doors if op.wall == "south"), key=lambda op: op.offset_cm)
    return south[0] if south else (doors[0] if doors else None)


def is_wall_mirror(p: Placement) -> bool:
    """Настенное зеркало (глубина ≤ `wall_hung_max_d_cm`) — висит на стене, пол не занимает."""
    lim = hall_rules()["roles"]["зеркало"]["wall_hung_max_d_cm"]
    return base_role(p.role) == "зеркало" and p.item is not None and p.item.d_cm <= lim


def is_low(p: Placement) -> bool:
    """Низкая мебель, над которой может висеть зеркало: роль из `over_low_roles` (обувница, консоль, банкетка) и не выше
    `over_low_max_h_cm`. Вешалка — нет: на ней висит одежда, зеркало за ней не видно."""
    cfg = hall_rules()["roles"]["зеркало"]
    return (p.item is not None and p.item.h_cm is not None and p.item.h_cm <= cfg["over_low_max_h_cm"]
            and base_role(p.role) in cfg["over_low_roles"] and not is_wall_mirror(p))


def may_overlap(a: Placement, b: Placement) -> bool:
    """Настенное зеркало над низкой мебелью — законно (зеркало над обувницей/консолью)."""
    return (is_wall_mirror(a) and is_low(b)) or (is_wall_mirror(b) and is_low(a))


def floor_items(ps: list[Placement]) -> list[Placement]:
    """Что занимает пол: всё, кроме ковра и настенного зеркала."""
    return [p for p in ps if not is_flat_floor(p) and not is_wall_mirror(p)]


def hall_spec(role: str) -> ClearanceSpec | None:
    key = role_cfg(role).get("front")
    if not key:
        return None
    return ClearanceSpec(num(key, 50), 0, 0, f"фронт прихожей ({key})")


def door_front(room: Room, op: Opening):
    """Полоса перед дверью прихожей (в любую сторону открывания): ширина проёма × `passage_secondary_comfort` (76)."""
    return _wall_strip(room, op.wall, op.offset_cm, op.width_cm, num("passage_secondary_comfort", 76))


def check_hall_collisions(ps: list[Placement]) -> list[Violation]:
    out = []
    for i, a in enumerate(ps):
        if is_flat_floor(a):
            continue
        fa = footprint(a)
        for b in ps[i + 1:]:
            if is_flat_floor(b) or may_overlap(a, b):
                continue
            inter = fa.intersection(footprint(b)).area
            if inter > EPS * EPS:
                out.append(_v("COLLISION", f"«{a.role}» пересекается с «{b.role}»", [a.role, b.role],
                              round(inter / 100, 1), "0 м² пересечения"))
    return out


def check_hall_wall(room: Room, ps: list[Placement]) -> list[Violation]:
    """В коридоре каждый предмет — спинкой к стене (полоса за спинкой лежит за стеной)."""
    out = []
    for p in ps:
        if is_flat_floor(p) or p.item is None:
            continue
        if not _against_wall(room, back_strip(p)):
            out.append(_v("HALL_NOT_AT_WALL", f"«{p.role}» не спинкой к стене", [p.role], None, "спинкой к стене"))
    return out


def check_door_fronts(room: Room, ps: list[Placement]) -> list[Violation]:
    out = []
    for op in room.openings:
        if op.kind not in ("door", "opening", "balcony"):
            continue
        strip = door_front(room, op).buffer(-EPS)
        for p in floor_items(ps):
            if footprint(p).intersects(strip):
                out.append(_v("HALL_DOOR_FRONT", f"«{p.role}» перекрывает подход к двери ({op.wall}, {op.offset_cm:.0f})",
                              [p.role], num("passage_secondary_comfort", 76), "полоса перед дверью свободна"))
        if any(mirror_on_opening(room, p, op) for p in ps):
            out.append(_v("HALL_DOOR_FRONT", "зеркало висит на проёме", ["зеркало"], None, "зеркало на глухой стене"))
    return out


MIRROR_JAMB_CM = 8.0   # зазор зеркала до проёма: наличник двери ~7 см (гипотеза по типовым наличникам 70 мм)


def mirror_on_opening(room: Room, p: Placement, op: Opening | None = None) -> bool:
    """Настенное зеркало на проёме или на наличнике (ближе `MIRROR_JAMB_CM`). Одна функция — для солвера и проверки."""
    if not is_wall_mirror(p):
        return False
    fp = footprint(p)
    ops = [op] if op is not None else room.openings
    return any(fp.intersects(opening_polygon(room, o).buffer(MIRROR_JAMB_CM)) for o in ops)


def check_hall_access(room: Room, ps: list[Placement]) -> list[Violation]:
    """Фронт-зоны хранения, обувницы, банкетки: внутри комнаты и без чужой мебели (настенное зеркало не мешает)."""
    out = []
    rp = room_polygon(room)
    for a in ps:
        spec = hall_spec(a.role)
        if spec is None or a.item is None:
            continue
        zone = access_zone(a, spec=spec)
        if zone.difference(rp).area > AREA_EPS:
            out.append(_v("HALL_ACCESS_WALL", f"перед «{a.role}» меньше {spec.front_cm:.0f} см до стены", [a.role],
                          spec.front_cm, f"≥{spec.front_cm:.0f} см перед фасадом"))
        for b in floor_items(ps):
            if b is a:
                continue
            inter = zone.intersection(footprint(b)).area
            if inter > AREA_EPS:
                out.append(_v("HALL_ACCESS_BLOCKED", f"«{b.role}» перекрывает подход к «{a.role}»", [a.role, b.role],
                              round(inter / 100, 1), "зона подхода свободна"))
    return out


def _mouth(room: Room, op: Opening, need: float):
    return _wall_strip(room, op.wall, op.offset_cm, op.width_cm, need + 2.0)


def passage_core(room: Room, ps: list[Placement], need: float):
    """Пол, по которому проходит человек шириной need: комната − мебель, сжатая на need/2 (дуги дверей — не стена)."""
    free = room_polygon(room)
    fl = [footprint(p) for p in floor_items(ps)]
    if fl:
        free = free.difference(unary_union(fl))
    return free.buffer(-need / 2)


def _parts(core):
    if core.is_empty:
        return []
    return [core] if core.geom_type == "Polygon" else [g for g in core.geoms if g.geom_type == "Polygon"]


def route_ok(room: Room, ps: list[Placement], need: float) -> tuple[bool, list[Opening], object]:
    """Есть ли проход need от входной двери до всех прочих дверей. → (да?, недоступные двери, часть пола у входа)."""
    ent = entrance(room)
    doors = [op for op in room.openings if op.kind in ("door", "opening", "balcony")]
    parts = _parts(passage_core(room, ps, need))
    if ent is None:
        main = max(parts, key=lambda g: g.area) if parts else None
        return main is not None, [], main
    em = _mouth(room, ent, need)
    touching = [g for g in parts if g.intersects(em)]
    if not touching:
        return False, [op for op in doors if op is not ent], None
    main = unary_union(touching)
    lost = [op for op in doors if op is not ent and not main.intersects(_mouth(room, op, need))]
    return not lost, lost, main


ROOM_NARROW_STEP = 5.0     # см: шаг, которым ищем ширину прохода пустой комнаты к узкой двери
ROOM_NARROW_MIN = 40.0     # см: уже — двери нет и в пустой комнате (ниже не ищем)
_BASE: dict = {}


def _doors(room: Room) -> list[tuple[int, Opening]]:
    ent = entrance(room)
    return [(i, op) for i, op in enumerate(room.openings) if op.kind in ("door", "opening", "balcony") and op is not ent]


def room_widths(room: Room, need: float) -> dict[int, float]:
    """Двери, к которым и ПУСТАЯ комната не даёт прохода need (стены уже нормы: полоса 80 у санузлов, узкое горло Г),
    → {индекс проёма: самый широкий проход пустой комнаты, шаг 5 см}. Это свойство комнаты, не мебели: мебель не должна
    сужать проход сильнее стен. Кэш — по геометрии комнаты (солвер зовёт проверку сотни раз)."""
    key = (room.model_dump_json(include={"width_cm", "depth_cm", "contour", "openings"}), need)
    if key in _BASE:
        return _BASE[key]
    out: dict[int, float] = {}
    _ok, lost, _main = route_ok(room, [], need)
    lost_ids = [i for i, op in _doors(room) if any(op is q for q in lost)]
    for i in lost_ids:
        op = room.openings[i]
        w = need
        while w - ROOM_NARROW_STEP >= ROOM_NARROW_MIN:
            w -= ROOM_NARROW_STEP
            _ok, l2, main = route_ok(room, [], w)
            if main is not None and not any(op is q for q in l2):
                break
        else:
            w = 0.0                     # и в пустой комнате не дойти — проверке мебели тут нечего держать
        out[i] = w
    if len(_BASE) > 256:
        _BASE.clear()
    _BASE[key] = out
    return out


def check_hall_passages(room: Room, ps: list[Placement]) -> list[Violation]:
    """Проход `hall_passage_min` от входа до каждой двери и каждого предмета. Где стены уже нормы (`room_widths`) —
    держим ширину пустой комнаты: мебель её не сужает (жёстко), а сама узость — мягкое `HALL_ROOM_NARROW`."""
    need = num("hall_passage_min", 85)
    base = room_widths(room, need)
    mains: dict = {}

    def main_at(w: float):
        if w not in mains:
            mains[w] = route_ok(room, ps, w)[2]
        return mains[w]

    out = []
    main = main_at(need)
    if main is None and not base:
        return [_v("HALL_NO_PASSAGE", f"от входной двери нет прохода {need:.0f} см", [], need, f"≥{need:.0f} см")]
    for i, op in _doors(room):
        w = base.get(i, need)
        if w <= 0:
            continue
        m = main_at(w)
        if m is None or not m.intersects(_mouth(room, op, w)):
            out.append(_v("HALL_DOOR_UNREACHABLE", f"от входа нет прохода {w:.0f} см к двери ({op.wall}, {op.offset_cm:.0f})",
                          [], w, f"≥{w:.0f} см"))
    reach = main if main is not None else next((main_at(w) for w in sorted(set(base.values()), reverse=True)
                                                 if w > 0 and main_at(w) is not None), None)
    for p in ps:
        if is_flat_floor(p) or p.item is None:
            continue
        fp = footprint(p)
        if is_wall_mirror(p):     # к зеркалу над обувницей/консолью подходят до той мебели — смотрятся поверх неё
            fp = unary_union([fp] + [footprint(q) for q in ps if is_low(q) and footprint(q).intersection(fp).area > 1.0])
        if reach is None or not fp.buffer(need / 2 + EPS).intersects(reach):
            out.append(_v("HALL_UNREACHABLE", f"к «{p.role}» нет прохода {need:.0f} см", [p.role], need, f"≥{need:.0f} см"))
    for i, w in sorted(base.items()):
        op = room.openings[i]
        out.append(_v("HALL_ROOM_NARROW", f"комната уже нормы: к двери ({op.wall}, {op.offset_cm:.0f}) стены дают проход "
                      f"{w:.0f} см (норма {need:.0f}) — мебель его не сужает", [], w, f"≥{need:.0f} см", Severity.SOFT))
    if not any(v.severity is Severity.HARD for v in out):
        comfort = num("hall_passage_comfort", 90)
        cm = route_ok(room, ps, comfort)[2] if comfort > need else None
        tight = comfort > need and (cm is None or any(not cm.intersects(_mouth(room, op, comfort))
                                                      for i, op in _doors(room) if i not in base))
        if tight:
            out.append(_v("HALL_PASSAGE_TIGHT", f"проход от входа уже {comfort:.0f} см", [], comfort, f"≥{comfort:.0f} см",
                          Severity.SOFT))
    return out


def entry_landing(room: Room):
    ent = entrance(room)
    if ent is None:
        return None
    return _wall_strip(room, ent.wall, ent.offset_cm, ent.width_cm, num("hall_entry_depth", 120))


def check_hall_entry(room: Room, ps: list[Placement]) -> list[Violation]:
    zone = entry_landing(room)
    if zone is None:
        return []
    hit = [p.role for p in floor_items(ps) if footprint(p).intersection(zone).area > AREA_EPS]
    if hit:
        d = num("hall_entry_depth", 120)
        return [_v("HALL_ENTRY_TIGHT", f"у входной двери нет площадки {d:.0f} см: {', '.join(hit)}", hit, d,
                   f"≥{d:.0f} см перед входной дверью", Severity.SOFT)]
    return []


def dist_to_entry(room: Room, p: Placement) -> float:
    ent = entrance(room)
    if ent is None:
        return 0.0
    return footprint(p).distance(opening_polygon(room, ent))


def check_hall_near_entry(room: Room, ps: list[Placement]) -> list[Violation]:
    out = []
    shoe, mirror = num("hall_shoe_entry_max", 150), num("hall_mirror_exit_max", 300)
    for p in ps:
        cfg = role_cfg(p.role)
        if p.item is None:
            continue
        d = dist_to_entry(room, p)
        if cfg.get("near_entry") and d > shoe:
            out.append(_v("HALL_SHOE_FAR", f"«{p.role}» в {d:.0f} см от входной двери", [p.role], round(d),
                          f"≤{shoe:.0f} см", Severity.SOFT))
        if cfg.get("near_exit") and d > mirror:
            out.append(_v("HALL_MIRROR_FAR", f"«{p.role}» в {d:.0f} см от входной двери", [p.role], round(d),
                          f"≤{mirror:.0f} см", Severity.SOFT))
    return out


def validate_hall(room: Room, placements: list[Placement], *, passage: str = "secondary",
                  fast_hard: bool = False) -> Layout:
    checks = [
        lambda: check_boundary(room, placements),
        lambda: check_hall_collisions(placements),
        lambda: check_openings(room, [p for p in placements if not is_wall_mirror(p)]),
        lambda: check_radiators(room, floor_items(placements)),
        lambda: check_hall_wall(room, placements),
        lambda: check_door_fronts(room, placements),
        lambda: check_hall_access(room, placements),
        lambda: check_hall_entry(room, placements),
        lambda: check_hall_near_entry(room, placements),
        lambda: check_hall_passages(room, placements),   # самая дорогая — последней
    ]
    vs: list[Violation] = []
    for chk in checks:
        vs += chk()
        if fast_hard and any(v.severity is Severity.HARD for v in vs):
            return Layout(room=room, placements=placements, violations=vs, floor_used_pct=0.0)
    return Layout(room=room, placements=placements, violations=vs,
                  floor_used_pct=round(floor_used_pct(room, floor_items(placements)), 1))


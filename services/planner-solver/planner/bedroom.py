"""Солвер СПАЛЬНИ (план onb-05, ADR-0330 п.1): отдельный модуль, путь гостиной (`zones.py`/`template.py`) не трогает.

Порядок дизайнера: кровать (изголовьем к сплошной стене, по центру или в угол) → тумбы у изголовья → хранение
(шкаф, комод — на стене без окна) → стол у окна со стулом → туалетный столик. Перебор — узкий луч по стенам
с проверкой «влезает» на каждом шаге и полной `validate_bedroom` в конце. Обязательное по назначению
(`rules/bedroom.json` purposes) держим; опциональное, которому нет места, — в `skipped_optional`; не встало
обязательное — `unplaced` и код причины в `meta.reason`. Один вход → одна раскладка (сортировки с ключами).
"""
from __future__ import annotations

import math

from shapely.affinity import rotate as _rot
from shapely.geometry import Point
from shapely.ops import unary_union

from .bedroom_checks import (AREA_EPS, _zone_clear, bed_zones, bedroom_rules, bedroom_spec, both_sides, check_bed,
                             is_double, nightstand_ok, num, same_group, validate_bedroom)
from .geometry import (SAFE_GAP_CM, _wall_point, _wall_strip, access_zone, base_role, footprint, opening_polygon,
                       radiator_polygon, room_edges, room_polygon, swing_polygon)
from .models import Item, Layout, Placement, Room, Severity

BEAM = 8
STEP_CM = 10.0
ORDER = ["кровать", "тумба прикроватная", "стол рабочий", "стул рабочий", "шкаф", "комод", "туалетный столик"]
# вес опционального: чем выше, тем дороже его потерять (шкаф — главное хранение спальни)
WEIGHT = {"кровать": 6.0, "шкаф": 3.0, "тумба прикроватная": 2.0, "комод": 2.0, "стол рабочий": 2.0,
          "стул рабочий": 1.0, "туалетный столик": 1.0}
SOFT_PENALTY = {"BED_HEAD_WINDOW": 3.0, "NIGHTSTAND_DETACHED": 2.0, "BEDROOM_FLOOR_OVERFILL": 2.0,
                "BED_DOOR_WALL": 1.0, "BED_NEAR_RADIATOR": 1.0, "DESK_FAR_FROM_WINDOW": 1.0, "MAIN_PATH_TIGHT": 0.5}
_ROT_BY_NORMAL = {(0, 1): 0, (1, 0): 90, (0, -1): 180, (-1, 0): 270}


def _order_key(role: str) -> tuple:
    b = base_role(role)
    return (ORDER.index(b) if b in ORDER else len(ORDER), role)


class _Statics:
    """Что занято до мебели: дуги и проходы дверей, радиаторы с отступом, окна (для высокого)."""

    def __init__(self, room: Room):
        self.room = room
        self.poly = room_polygon(room)
        door = []
        for op in room.openings:
            sw = swing_polygon(room, op)
            if not sw.is_empty:
                door.append(sw.buffer(-1.0))
            if op.kind == "door":
                door.append(_wall_strip(room, op.wall, op.offset_cm, op.width_cm, 76.0).buffer(-1.0))
        hard = num("sofa_to_radiator_wall", 15)
        rads = [radiator_polygon(room, r).buffer(hard - 1.0) for r in room.radiators]
        self.blocked = unary_union(door + rads) if (door or rads) else None
        self.windows = [(op, opening_polygon(room, op)) for op in room.openings if op.kind == "window"]


def _slots(room: Room, item: Item):
    """Позиции «спинкой к стене» по всем рёбрам контура: шаг сетки + углы + центр + привязки к косякам."""
    out = []
    w, d = item.w_cm, item.d_cm
    marks = []
    for op in room.openings:
        marks += [_wall_point(room, op.wall, op.offset_cm), _wall_point(room, op.wall, op.offset_cm + op.width_cm)]
    for r in room.radiators:
        marks += [_wall_point(room, r.wall, r.offset_cm), _wall_point(room, r.wall, r.offset_cm + r.width_cm)]
    for (ax, ay), (bx, by) in room_edges(room):
        L = math.hypot(bx - ax, by - ay)
        if L + 0.5 < w:
            continue
        ux, uy = (bx - ax) / L, (by - ay) / L
        n = (round(-uy), round(ux))
        if n not in _ROT_BY_NORMAL or abs(abs(ux) + abs(uy) - 1) > 1e-6:
            continue                       # косые стены — следующий шаг (как у гостиной)
        rot = _ROT_BY_NORMAL[n]
        lo, hi = w / 2, L - w / 2
        ts = {lo, hi, L / 2}
        t = lo
        while t < hi:
            ts.add(t)
            t += STEP_CM
        for m in marks:
            tm = (m.x - ax) * ux + (m.y - ay) * uy
            off = abs((m.x - ax) * n[0] + (m.y - ay) * n[1])
            if off > 1 or not (-1 <= tm <= L + 1):
                continue
            for s in (tm - w / 2 - SAFE_GAP_CM, tm + w / 2 + SAFE_GAP_CM, tm - w / 2 - 16, tm + w / 2 + 16):
                if lo <= s <= hi:
                    ts.add(s)
        for t in sorted(ts):
            cx = ax + ux * t + n[0] * d / 2
            cy = ay + uy * t + n[1] * d / 2
            # где на стене (0 — начало, 1 — конец) и длина стены — для оценки «по центру/в угол»
            out.append((round(cx, 1), round(cy, 1), rot, t / L, L, (ax, ay, bx, by)))
    return out


def _place(role: str, item: Item, x: float, y: float, rot: int, tpl: str = "") -> Placement:
    return Placement(role=role, x=x, y=y, rot=rot, item=item, tpl_id=tpl, tpl_version="bedroom-v1" if tpl else "")


def _keepouts(p: Placement, placed: list[Placement], room: Room):
    """Полосы, которые предмет держит свободными после постановки (проходы кровати, фронт хранения)."""
    if base_role(p.role) == "кровать":
        z = bed_zones(p)
        others = [o for o in placed if o is not p]
        sides = [z[s] for s in ("left", "right")]
        if both_sides(room, p):
            return [z["foot"]] + sides
        clear = [s for s in sides if _zone_clear(room, s, others)]
        return [z["foot"]] + clear[:1]
    spec = bedroom_spec(p.role)
    return [access_zone(p, spec=spec)] if spec is not None else []


class _State:
    __slots__ = ("placed", "keep", "score", "skipped")

    def __init__(self, placed, keep, score, skipped):
        self.placed, self.keep, self.score, self.skipped = placed, keep, score, skipped

    def key(self):
        return (-round(self.score, 3), tuple((p.role, p.x, p.y, p.rot) for p in self.placed))


def _fits(st: _State, S: _Statics, p: Placement) -> bool:
    fp = footprint(p)
    if fp.difference(S.poly).area > AREA_EPS / 10:
        return False
    if S.blocked is not None and fp.intersects(S.blocked):
        return False
    h = p.item.h_cm or 0
    for op, win in S.windows:
        if h > max(op.sill_cm, 80) and fp.distance(win) < 10:
            return False
    for q in st.placed:
        if fp.intersection(footprint(q)).area > 1.0:
            return False
    for owner, z in st.keep:
        if same_group(owner, p.role):
            continue
        if fp.intersection(z).area > AREA_EPS:
            return False
    for z in _keepouts(p, st.placed + [p], S.room):
        if z.difference(S.poly).area > AREA_EPS:
            return False
        for q in st.placed:
            if not same_group(p.role, q.role) and z.intersection(footprint(q)).area > AREA_EPS:
                return False
    return True


def _pref(S: _Statics, p: Placement, slot) -> float:
    """Предпочтения шаблонов (мягкие): кровать по центру стены или в угол, хранение у глухой стены, стол у окна."""
    r = base_role(p.role)
    _, _, rot, frac, L, _edge = slot
    fp = footprint(p)
    win_on_wall = any(fp.distance(w) < p.item.d_cm / 2 + 30 and _edge_has(w, _edge) for _, w in S.windows)
    if r == "кровать":
        if is_double(p):
            return -4.0 * abs(frac - 0.5)                         # шаблон bed_center_wall
        corner = min(frac * L - p.item.w_cm / 2, L - frac * L - p.item.w_cm / 2)
        return -0.02 * min(corner, 100) + (0.5 if corner < 1 else 0.0)   # шаблон bed_corner
    if r in ("шкаф", "комод"):
        return -1.5 if win_on_wall else 0.0                     # storage_solid_wall
    if r == "стол рабочий":
        dist = min((fp.distance(w) for _, w in S.windows), default=0.0)
        return -0.01 * dist                                     # work_at_window
    return 0.0


def _edge_has(win, edge) -> bool:
    ax, ay, bx, by = edge
    from shapely.geometry import LineString
    return LineString([(ax, ay), (bx, by)]).distance(win) < 2


def _nightstand_spots(bed: Placement, item: Item):
    w, d = bed.item.w_cm, bed.item.d_cm
    for sx in (-1, 1):
        lx, ly = sx * (w / 2 + item.w_cm / 2 + 1), -d / 2 + item.d_cm / 2
        v = _rot(Point(lx, ly), -bed.rot, origin=(0, 0))
        yield round(bed.x + v.x, 1), round(bed.y + v.y, 1)


def _chair_spot(desk: Placement, item: Item):
    v = _rot(Point(0, desk.item.d_cm / 2 + item.d_cm / 2 + 1), -desk.rot, origin=(0, 0))
    return round(desk.x + v.x, 1), round(desk.y + v.y, 1), int((desk.rot + 180) % 360)


def _candidates(st: _State, S: _Statics, role: str, item: Item):
    b = base_role(role)
    if b == "тумба прикроватная":
        beds = [q for q in st.placed if base_role(q.role) == "кровать"]
        for bed in beds:
            for x, y in _nightstand_spots(bed, item):
                p = _place(role, item, x, y, int(bed.rot), bed.tpl_id)
                if nightstand_ok(S.room, p, [bed]):
                    yield p, 0.0
        return
    if b == "стул рабочий":
        for desk in [q for q in st.placed if base_role(q.role) == "стол рабочий"]:
            x, y, rot = _chair_spot(desk, item)
            yield _place(role, item, x, y, rot, desk.tpl_id), 0.0
        return
    for slot in _slots(S.room, item):
        x, y, rot = slot[0], slot[1], slot[2]
        tpl = ""
        if b == "кровать":
            tpl = "bed_center_wall" if is_double(Placement(role=role, item=item, x=0, y=0)) else "bed_corner"
        elif b in ("шкаф", "комод"):
            tpl = "storage_solid_wall"
        elif b == "стол рабочий":
            tpl = "work_at_window"
        elif b == "туалетный столик":
            tpl = "dressing_table"
        p = _place(role, item, x, y, rot, tpl)
        yield p, _pref(S, p, slot)


def _bed_ok(room: Room, S: _Statics, p: Placement) -> bool:
    """Кровать в одиночку проходит свои жёсткие нормы (изголовье, проходы)."""
    return not any(v.severity is Severity.HARD for v in check_bed(room, [p]))


def solve_bedroom(room: Room, items: list[Item], purpose: str | None = None, *, beam: int = BEAM) -> Layout:
    purpose = purpose or room.purpose or "couple"
    cfg = bedroom_rules()["purposes"].get(purpose)
    meta = {"solver": "bedroom-v1", "purpose": purpose, "reason": []}
    if cfg is None:
        meta["reason"].append("PURPOSE_UNKNOWN")
        return Layout(room=room, placements=[], meta=meta, unplaced=sorted(i.role for i in items))
    if cfg.get("pending"):
        meta["reason"].append("PURPOSE_PENDING")
        meta["pending"] = cfg["pending"]
        return Layout(room=room, placements=[], meta=meta, unplaced=sorted(i.role for i in items))
    required = set(cfg["required"])
    by_role = {i.role: i for i in items}
    missing = sorted(r for r in required if r not in by_role)
    if missing:
        meta["reason"].append("MISSING_ITEM")
        meta["missing"] = missing
    bed = by_role.get("кровать")
    if bed is not None and cfg.get("bed") == "double" and not is_double(Placement(role="кровать", item=bed, x=0, y=0)):
        meta["reason"].append("BED_NOT_DOUBLE")
        return Layout(room=room, placements=[], meta=meta, unplaced=["кровать"])

    S = _Statics(room)
    roles = sorted(by_role, key=_order_key)
    states = [_State([], [], 0.0, [])]
    for role in roles:
        item = by_role[role]
        must = role in required
        nxt = []
        for st in states:
            for p, pref in _candidates(st, S, role, item):
                if base_role(role) == "кровать" and not _bed_ok(room, S, p):
                    continue
                if not _fits(st, S, p):
                    continue
                keep = st.keep + [(role, z) for z in _keepouts(p, st.placed + [p], room)]
                nxt.append(_State(st.placed + [p], keep, st.score + pref, st.skipped))
            if not must:
                nxt.append(_State(st.placed, st.keep, st.score - WEIGHT.get(base_role(role), 1.0) * 10,
                                  st.skipped + [role]))
        if not nxt:
            # обязательное не встало — спальни с этим набором нет: полупустой план (шкаф без кровати) не отдаём
            meta["reason"].append("BED_NO_FIT" if base_role(role) == "кровать" else "REQUIRED_NO_FIT")
            meta["no_fit"] = role
            return Layout(room=room, placements=[], meta=meta, unplaced=sorted(r for r in by_role if r in required),
                          skipped_optional=sorted(r for r in by_role if r not in required))
        nxt.sort(key=_State.key)
        states = _dedupe(nxt)[:beam]

    best, best_key = None, None
    for st in states:
        st, lay = _repair(room, st, required)
        hard = sum(v.severity is Severity.HARD for v in lay.violations)
        soft = sum(SOFT_PENALTY.get(v.code, 0.5) for v in lay.violations if v.severity is Severity.SOFT)
        k = (hard, -(st.score - soft), st.key()[1])
        if best_key is None or k < best_key:
            best, best_key = (st, lay), k
    st, lay = best
    placed_roles = {p.role for p in st.placed}
    lay.unplaced = sorted(r for r in by_role if r in required and r not in placed_roles)
    lay.skipped_optional = sorted(r for r in by_role if r not in required and r not in placed_roles)
    if any(v.severity is Severity.HARD for v in lay.violations):
        meta["reason"].append("HARD_LEFT")
    if lay.unplaced and not meta["reason"]:
        meta["reason"].append("REQUIRED_NO_FIT")
    meta["template"] = next((p.tpl_id for p in st.placed if base_role(p.role) == "кровать"), "")
    lay.meta = meta
    return lay


def _repair(room: Room, st: _State, required: set) -> tuple[_State, Layout]:
    """Полная проверка ловит то, чего не видит пошаговая (проход 46 до предмета через всю комнату). Жёсткое
    из-за ОПЦИОНАЛЬНОГО предмета — снимаем его (самый лёгкий по весу первым) в «не нашлось места», а не сдаём брак."""
    placed = list(st.placed)
    while True:
        lay = validate_bedroom(room, placed)
        bad = {r for v in lay.violations if v.severity is Severity.HARD for r in v.roles}
        drop = sorted((p for p in placed if p.role in bad and p.role not in required),
                      key=lambda p: (WEIGHT.get(base_role(p.role), 1.0), p.role))
        if not drop:
            break
        gone = drop[0].role
        # стул без стола и стол без стула не оставляем: группа уходит целиком; без кровати уходят и тумбы
        placed = [p for p in placed if p.role != gone and not same_group(p.role, gone)
                  and not (base_role(gone) == "кровать" and base_role(p.role) == "тумба прикроватная")]
    if len(placed) == len(st.placed):
        return st, lay
    lost = sum(WEIGHT.get(base_role(p.role), 1.0) * 10 for p in st.placed if p not in placed)
    return _State(placed, [], st.score - lost, st.skipped), lay


DIVERSITY_CM = 30.0   # луч не тратит места на соседние позиции одной стены (шаг 10 см) — держит разные решения


def _dedupe(states: list[_State]) -> list[_State]:
    seen, out = set(), []
    for st in states:
        k = tuple(sorted((p.role, round(p.x / DIVERSITY_CM), round(p.y / DIVERSITY_CM), p.rot) for p in st.placed))
        if k in seen:
            continue
        seen.add(k)
        out.append(st)
    return out

"""Солвер ПРИХОЖЕЙ (план onb-13 Т3, T-20261105-34; по образцу `planner/bedroom.py`, ADR-0330 п.1).

Порядок дизайнера: хранение верхней одежды (шкаф-купе / шкаф / модуль-прихожая — у глухой стены, вешалка, если шкафа
нет) → обувница и банкетка у входа → консоль → вешалка → зеркало (на стене, можно над низкой мебелью). Всё — спинкой
к стене в линию; середина держит проход `hall_passage_min` от входной двери до каждой двери и предмета. Перебор —
узкий луч по стенам (`bedroom._slots`); дешёвые проверки на каждом кандидате, проход — лениво, только у лучших.
Хоть одно хранение из `rules/hall.json` composition.storage_any обязательно (`STORAGE_NO_FIT`); прочее, чему нет
места, — в `skipped_optional`. Один вход → одна раскладка (сортировки с ключами).
"""
from __future__ import annotations

from shapely.geometry import LineString
from shapely.ops import unary_union

from .bedroom import _dedupe, _slots
from .geometry import base_role, footprint, opening_polygon, radiator_polygon, room_polygon, swing_polygon
from .hall_checks import (AREA_EPS, check_hall_passages, dist_to_entry, door_front, hall_rules, hall_spec,
                          is_low, is_wall_mirror, may_overlap, mirror_on_opening, num, validate_hall)
from .models import Item, Layout, Placement, Room, Severity

BEAM = 8
ORDER = ["шкаф-купе", "шкаф", "прихожая", "обувница", "банкетка", "консоль", "вешалка", "зеркало"]
# вес опционального: чем выше, тем дороже его потерять (хранение одежды — главное в прихожей)
WEIGHT = {"шкаф-купе": 5.0, "шкаф": 4.0, "прихожая": 4.0, "обувница": 3.0, "вешалка": 2.5, "банкетка": 2.0,
          "зеркало": 2.0, "консоль": 1.5}
SOFT_PENALTY = {"HALL_PASSAGE_TIGHT": 2.0, "HALL_ENTRY_TIGHT": 1.5, "HALL_SHOE_FAR": 1.0, "HALL_MIRROR_FAR": 0.5}
MIRROR_CENTER_CM = 150.0   # центр настенного зеркала — на уровне глаз (для кадра; правил на высоту нет)


def _order_key(role: str) -> tuple:
    b = base_role(role)
    return (ORDER.index(b) if b in ORDER else len(ORDER), role)


def storage_roles() -> set:
    return set(hall_rules()["composition"]["storage_any"])


class _Statics:
    """Что занято до мебели: дуги дверей внутрь, полосы перед КАЖДОЙ дверью, радиаторы с отступом, окна (для высокого)."""

    def __init__(self, room: Room):
        self.room = room
        self.poly = room_polygon(room)
        parts = []
        for op in room.openings:
            sw = swing_polygon(room, op)
            if not sw.is_empty:
                parts.append(sw.buffer(-1.0))
            if op.kind in ("door", "opening", "balcony"):
                parts.append(door_front(room, op).buffer(-1.0))
        hard = num("sofa_to_radiator_wall", 15)
        parts += [radiator_polygon(room, r).buffer(hard - 1.0) for r in room.radiators]
        self.blocked = unary_union(parts) if parts else None
        self.windows = [(op, opening_polygon(room, op)) for op in room.openings if op.kind == "window"]
        self.openings = [opening_polygon(room, op) for op in room.openings]


def _edge_solid(S: _Statics, edge) -> bool:
    ax, ay, bx, by = edge
    ln = LineString([(ax, ay), (bx, by)])
    return not any(ln.distance(o) < 2 for o in S.openings)


def _place(role: str, item: Item, x: float, y: float, rot: int, tpl: str, low_under: float = 0.0) -> Placement:
    elev = 0.0
    p = Placement(role=role, x=x, y=y, rot=rot, item=item, tpl_id=tpl, tpl_version="hall-v1" if tpl else "")
    if is_wall_mirror(p):
        h = item.h_cm or 60.0
        elev = max(low_under + 10.0, MIRROR_CENTER_CM - h / 2, 0.0)
        p.elev_cm = round(elev, 1)
    return p


class _State:
    __slots__ = ("placed", "keep", "score", "skipped")

    def __init__(self, placed, keep, score, skipped):
        self.placed, self.keep, self.score, self.skipped = placed, keep, score, skipped

    def key(self):
        return (-round(self.score, 3), tuple((p.role, p.x, p.y, p.rot) for p in self.placed))


def _zone(p: Placement):
    spec = hall_spec(p.role)
    if spec is None:
        return None
    from .geometry import access_zone
    return access_zone(p, spec=spec)


def _fits(st: _State, S: _Statics, p: Placement) -> bool:
    """Дешёвые проверки кандидата (без прохода): комната, двери/радиаторы, окно, столкновения, фронты."""
    fp = footprint(p)
    if fp.difference(S.poly).area > AREA_EPS / 10:
        return False
    if S.blocked is not None and fp.intersects(S.blocked):
        return False
    h = p.item.h_cm or 0
    for op, win in S.windows:
        if h > max(op.sill_cm, 80) and fp.distance(win) < 10:
            return False
    mirror = is_wall_mirror(p)
    if mirror and mirror_on_opening(S.room, p):
        return False
    for q in st.placed:
        if fp.intersection(footprint(q)).area > 1.0 and not may_overlap(p, q):
            return False
    if not mirror:
        for _owner, z in st.keep:
            if fp.intersection(z).area > AREA_EPS:
                return False
    z = _zone(p)
    if z is not None:
        if z.difference(S.poly).area > AREA_EPS:
            return False
        for q in st.placed:
            if not is_wall_mirror(q) and z.intersection(footprint(q)).area > AREA_EPS:
                return False
    return True


def _pass_ok(room: Room, placed: list[Placement]) -> bool:
    return not any(v.severity is Severity.HARD for v in check_hall_passages(room, placed))


def _pref(S: _Statics, p: Placement, slot, low_under: float) -> float:
    """Предпочтения шаблонов (мягкие): хранение у глухой стены и в угол, обувь у входа, зеркало у выхода."""
    r = base_role(p.role)
    cfg = hall_rules()["roles"].get(r, {})
    _, _, _rot, frac, L, edge = slot
    d = dist_to_entry(S.room, p)
    if cfg.get("tall"):
        corner = min(frac * L - p.item.w_cm / 2, L - frac * L - p.item.w_cm / 2)
        return (1.0 if _edge_solid(S, edge) else 0.0) + (0.5 if corner < 1 else 0.0) + 0.002 * p.item.w_cm
    if cfg.get("near_entry"):
        return -0.01 * min(d, 400)
    if r == "зеркало":
        return -0.005 * min(d, 600) + (0.3 if low_under else 0.0)
    if r == "вешалка":
        return -0.008 * min(d, 500)
    return -0.002 * min(d, 500)


def _low_under(st: _State, p: Placement) -> float:
    """Высота низкой мебели под настенным зеркалом (0 — пустая стена)."""
    if not is_wall_mirror(p):
        return 0.0
    fp = footprint(p)
    hs = [q.item.h_cm for q in st.placed if is_low(q) and fp.intersection(footprint(q)).area > 1.0]
    return max(hs) if hs else 0.0


def _candidates(st: _State, S: _Statics, role: str, item: Item):
    b = base_role(role)
    cfg = hall_rules()["roles"].get(b, {})
    tpl = ("storage_solid_wall" if cfg.get("tall") else "shoe_at_entry" if cfg.get("near_entry")
           else "mirror_at_exit" if b == "зеркало" else "line_along_wall")
    for slot in _slots(S.room, item):
        x, y, rot = slot[0], slot[1], slot[2]
        p = _place(role, item, x, y, rot, tpl)
        low = _low_under(st, p)
        if low:
            p = _place(role, item, x, y, rot, tpl, low)
        yield p, _pref(S, p, slot, low)


def solve_hall(room: Room, items: list[Item], *, beam: int = BEAM) -> Layout:
    meta = {"solver": "hall-v1", "reason": []}
    by_role = {i.role: i for i in items}
    storage = storage_roles()
    kit_storage = sorted(r for r in by_role if base_role(r) in storage)
    if not kit_storage:
        meta["reason"].append("MISSING_ITEM")
        meta["missing"] = sorted(storage)
        return Layout(room=room, placements=[], meta=meta, unplaced=["хранение"],
                      skipped_optional=sorted(by_role))

    S = _Statics(room)
    states = [_State([], [], 0.0, [])]
    for role in sorted(by_role, key=_order_key):
        item = by_role[role]
        nxt = []
        for st in states:
            for p, pref in _candidates(st, S, role, item):
                if not _fits(st, S, p):
                    continue
                z = _zone(p)
                keep = st.keep + ([(role, z)] if z is not None else [])
                nxt.append(_State(st.placed + [p], keep, st.score + pref, st.skipped))
            nxt.append(_State(st.placed, st.keep, st.score - WEIGHT.get(base_role(role), 1.0) * 10, st.skipped + [role]))
        nxt.sort(key=_State.key)
        # проход — дорогая проверка: лениво, по порядку очков, пока луч не наберётся
        kept, seen = [], set()
        for st in _dedupe(nxt):
            new = [p for p in st.placed if p.role == role]
            if new and not _pass_ok(room, st.placed):
                continue
            k = tuple((p.role, p.x, p.y, p.rot) for p in st.placed)
            if k in seen:
                continue
            seen.add(k)
            kept.append(st)
            if len(kept) >= beam:
                break
        states = kept

    states = [st for st in states if any(base_role(p.role) in storage for p in st.placed)]
    if not states:
        meta["reason"].append("STORAGE_NO_FIT")
        return Layout(room=room, placements=[], meta=meta, unplaced=kit_storage,
                      skipped_optional=sorted(r for r in by_role if r not in kit_storage))

    best, best_key = None, None
    for st in states:
        st, lay = _repair(room, st, storage)
        hard = sum(v.severity is Severity.HARD for v in lay.violations)
        soft = sum(SOFT_PENALTY.get(v.code, 0.5) for v in lay.violations if v.severity is Severity.SOFT)
        k = (hard, -(st.score - soft), st.key()[1])
        if best_key is None or k < best_key:
            best, best_key = (st, lay), k
    st, lay = best
    placed_roles = {p.role for p in st.placed}
    if not any(base_role(r) in storage for r in placed_roles):
        meta["reason"].append("STORAGE_NO_FIT")
        lay.unplaced = kit_storage
    else:
        lay.unplaced = []
    lay.skipped_optional = sorted(r for r in by_role if r not in placed_roles and r not in lay.unplaced)
    if any(v.severity is Severity.HARD for v in lay.violations):
        meta["reason"].append("HARD_LEFT")
    meta["template"] = next((p.tpl_id for p in st.placed if p.tpl_id == "storage_solid_wall"), "")
    lay.meta = meta
    return lay


def _repair(room: Room, st: _State, storage: set) -> tuple[_State, Layout]:
    """Полная проверка ловит то, чего не видит пошаговая. Жёсткое — снимаем предмет (самый лёгкий первым), но последнее
    хранение одежды не снимаем: тогда раскладка остаётся с жёстким и уходит в отказ."""
    placed = list(st.placed)
    while True:
        lay = validate_hall(room, placed)
        bad = {r for v in lay.violations if v.severity is Severity.HARD for r in v.roles}
        n_storage = sum(base_role(p.role) in storage for p in placed)
        drop = sorted((p for p in placed if p.role in bad and not (base_role(p.role) in storage and n_storage <= 1)),
                      key=lambda p: (WEIGHT.get(base_role(p.role), 1.0), p.role))
        if not drop:
            break
        gone = drop[0].role
        placed = [p for p in placed if p.role != gone]
    if len(placed) == len(st.placed):
        return st, lay
    lost = sum(WEIGHT.get(base_role(p.role), 1.0) * 10 for p in st.placed if p not in placed)
    return _State(placed, [], st.score - lost, st.skipped), lay

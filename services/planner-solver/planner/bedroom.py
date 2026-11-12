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

from .bedroom_checks import (AREA_EPS, STORAGE_LIKE, bed_zones, bedroom_role, bedroom_rules, bedroom_spec, both_sides,
                             check_bed, door_swings, foot_swing_share, front_reach, head_exempt, head_side_zones,
                             is_double, light_side, nightstand_ok, num, same_group, side_back, side_back_denied, side_clear,
                             validate_bedroom)
from .bedroom_checks import engine as _engine_of
from .geometry import (SAFE_GAP_CM, _wall_point, _wall_strip, access_zone, footprint, opening_polygon,
                       radiator_polygon, room_edges, room_polygon, swing_polygon)
from .models import Item, Layout, Placement, Room, Severity
from . import room_templates as RT

BEAM = 8
STEP_CM = 10.0
ORDER = ["кровать", "тумба прикроватная", "стол рабочий", "стул рабочий", "шкаф", "комод", "туалетный столик"]
# вес опционального: чем выше, тем дороже его потерять (шкаф — главное хранение спальни)
WEIGHT = {"кровать": 6.0, "шкаф": 3.0, "тумба прикроватная": 2.0, "комод": 2.0, "стол рабочий": 2.0,
          "стул рабочий": 1.0, "туалетный столик": 1.0}
SOFT_PENALTY = {"BED_HEAD_WINDOW": 3.0, "NIGHTSTAND_DETACHED": 2.0, "BEDROOM_FLOOR_OVERFILL": 2.0,
                "BED_DOOR_WALL": 1.0, "BED_NEAR_RADIATOR": 1.0, "DESK_FAR_FROM_WINDOW": 1.0, "DESK_LIGHT_RIGHT": 1.0,
                "MAIN_PATH_TIGHT": 0.5, "BED_NARROW_OFF_WALL": 2.0}
_ROT_BY_NORMAL = {(0, 1): 0, (1, 0): 90, (0, -1): 180, (-1, 0): 270}


def _order_key(role: str) -> tuple:
    b = bedroom_role(role)
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
        # шаблон кровати, заданный назначением (`purposes[*].bed_template`: single_narrow → bed_narrow_wall); нет — прежний выбор
        self.bed_tpl: str | None = None


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


NONE: frozenset = frozenset()


def _keepouts(p: Placement, placed: list[Placement], room: Room) -> list[tuple]:
    """Полосы, которые предмет держит свободными после постановки (проходы кровати, фронт хранения) —
    [(полоса, роли-исключения)]. Исключения есть только у части прохода у изголовья (`bed_zones` *_head, выключатель
    `switches.bed_side_passage_full`): там можно тумбе и лампе (`head_exempt`), прочим — нет."""
    if bedroom_role(p.role) == "кровать":
        z = bed_zones(p)
        others = [o for o in placed if o is not p]

        def strip(s: str) -> list[tuple]:
            return [(z[s], NONE)] + ([(z[f"{s}_head"], head_exempt())] if f"{s}_head" in z else [])
        if both_sides(room, p):
            return [(z["foot"], NONE)] + strip("left") + strip("right")
        clear = [s for s in ("left", "right") if side_clear(room, z, s, others)]
        return [(z["foot"], NONE)] + (strip(clear[0]) if clear else [])
    spec = bedroom_spec(p.role)
    return [(access_zone(p, spec=spec), NONE)] if spec is not None else []


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
    for owner, z, ex in st.keep:
        if same_group(owner, p.role) or bedroom_role(p.role) in ex:
            continue
        if fp.intersection(z).area > AREA_EPS:
            return False
    for z, ex in _keepouts(p, st.placed + [p], S.room):
        if z.difference(S.poly).area > AREA_EPS:
            return False
        for q in st.placed:
            if not same_group(p.role, q.role) and bedroom_role(q.role) not in ex and z.intersection(footprint(q)).area > AREA_EPS:
                return False
    return True


def _pref(S: _Statics, p: Placement, slot) -> float:
    """Предпочтения шаблонов (мягкие): кровать по центру стены или в угол, хранение у глухой стены, стол у окна."""
    r = bedroom_role(p.role)
    _, _, rot, frac, L, _edge = slot
    fp = footprint(p)
    win_on_wall = any(fp.distance(w) < p.item.d_cm / 2 + 30 and _edge_has(w, _edge) for _, w in S.windows)
    if r == "кровать":
        if p.tpl_id in ("bed_narrow_wall", "bed_side_back_corner"):
            # узкая односпальная и кровать с боковой спинкой: изголовье и длинный бок к стенам (в угол) — сильнее мягких
            # штрафов, отход от угла дорог (у боковой спинки «не у стены» ещё и жёстко — BED_SIDE_BACK_OFF_WALL)
            corner = min(frac * L - p.item.w_cm / 2, L - frac * L - p.item.w_cm / 2)
            return -0.05 * min(corner, 100) + (1.0 if corner < 1 else 0.0)
        if is_double(p):
            return -4.0 * abs(frac - 0.5)                         # шаблон bed_center_wall
        corner = min(frac * L - p.item.w_cm / 2, L - frac * L - p.item.w_cm / 2)
        return -0.02 * min(corner, 100) + (0.5 if corner < 1 else 0.0)   # шаблон bed_corner
    if r in ("шкаф", "комод"):
        return -1.5 if win_on_wall else 0.0                     # storage_solid_wall
    if r == "стол рабочий":
        dist = min((fp.distance(w) for _, w in S.windows), default=0.0)
        # work_at_window; детская — свет слева (desk_light_left): в луче, иначе место со светом слева отсекается до финала
        # (спальня 2 зеркально — стол справа от окна). Стол достаётся через свой стул (`check_bedroom_passages`)
        right = S.room.purpose == "child" and light_side(S.room, p) == "right"
        return -0.01 * dist - (SOFT_PENALTY["DESK_LIGHT_RIGHT"] if right else 0.0)
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
    b = bedroom_role(role)
    if b == "тумба прикроватная":
        beds = [q for q in st.placed if bedroom_role(q.role) == "кровать"]
        for bed in beds:
            for x, y in _nightstand_spots(bed, item):
                p = _place(role, item, x, y, int(bed.rot), bed.tpl_id)
                if nightstand_ok(S.room, p, [bed]):
                    yield p, 0.0
        return
    if b == "стул рабочий":
        for desk in [q for q in st.placed if bedroom_role(q.role) == "стол рабочий"]:
            x, y, rot = _chair_spot(desk, item)
            yield _place(role, item, x, y, rot, desk.tpl_id), 0.0
        return
    for slot in _slots(S.room, item):
        x, y, rot = slot[0], slot[1], slot[2]
        tpl = ""
        if b == "кровать":
            probe = Placement(role=role, item=item, x=0, y=0)
            dbl = is_double(probe)
            tpl = S.bed_tpl if (S.bed_tpl and not dbl) else ("bed_center_wall" if dbl else "bed_corner")
            if side_back(probe):
                tpl = "bed_side_back_corner"      # угловая модель — в угол спинкой к стене (T-20261112-31)
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


def _prelude(room: Room, items: list[Item], purpose: str, solver: str):
    """Общее начало обоих движков: назначение → состав (`purposes`), обязательное, отказы по кровати.
    → (cfg, meta, must_have, by_role, Layout-отказ | None)."""
    cfg = bedroom_rules()["purposes"].get(purpose)
    meta = {"solver": solver, "purpose": purpose, "reason": []}
    if cfg is None:
        meta["reason"].append("PURPOSE_UNKNOWN")
        return None, meta, None, None, Layout(room=room, placements=[], meta=meta, unplaced=sorted(i.role for i in items))
    if cfg.get("ages"):            # детская: состав по возрасту (Room.child_age); возраста нет в правилах — ждёт
        meta["child_age"] = room.child_age
        cfg = cfg["ages"].get(room.child_age or "", cfg)
    if cfg.get("pending"):
        meta["reason"].append("PURPOSE_PENDING")
        meta["pending"] = cfg["pending"]
        return cfg, meta, None, None, Layout(room=room, placements=[], meta=meta, unplaced=sorted(i.role for i in items))
    required = set(cfg["required"])
    alias = bedroom_rules().get("aliases", {})

    def must_have(role: str) -> bool:
        """Обязательное по назначению — сама роль или её детский псевдоним («стол детский» закрывает «стол рабочий»)."""
        return role in required or alias.get(role) in required
    by_role = {i.role: i for i in items}
    missing = sorted(r for r in required if not any(x == r or alias.get(x) == r for x in by_role))
    if missing:
        meta["reason"].append("MISSING_ITEM")
        meta["missing"] = missing
    bed = by_role.get("кровать") or next((i for x, i in by_role.items() if alias.get(x) == "кровать"), None)
    refuse = None
    if bed is not None and cfg.get("bed") == "double" and not is_double(Placement(role="кровать", item=bed, x=0, y=0)):
        refuse = "BED_NOT_DOUBLE"
    elif bed is not None and cfg.get("bed") == "single" and is_double(Placement(role="кровать", item=bed, x=0, y=0)):
        refuse = "BED_NOT_SINGLE"      # узкое назначение (single_narrow) двуспальную не ставит
    elif bed is not None and side_back_denied(purpose, bed):
        refuse = "BED_SIDE_BACK_COUPLE"  # угловая модель паре не годится — подход нужен с двух сторон
    if refuse:
        meta["reason"].append(refuse)
        return cfg, meta, must_have, by_role, Layout(room=room, placements=[], meta=meta, unplaced=["кровать"])
    return cfg, meta, must_have, by_role, None


def solve_bedroom(room: Room, items: list[Item], purpose: str | None = None, *, beam: int = BEAM,
                  engine: str | None = None) -> Layout:
    """engine — движок (`bedroom_checks.engine`: явный → env BEDROOM_ENGINE → rules _meta.engine). items — поштучно
    (прежнее байт в байт), groups — группы-шаблоны (`_solve_groups`, T-20261112-38)."""
    purpose = purpose or room.purpose or "couple"
    if _engine_of(engine) == "groups":
        return _solve_groups(room, items, purpose, beam=beam)
    cfg, meta, must_have, by_role, early = _prelude(room, items, purpose, "bedroom-v1")
    if early is not None:
        return early

    S = _Statics(room)
    S.bed_tpl = cfg.get("bed_template")
    roles = sorted(by_role, key=_order_key)
    states = [_State([], [], 0.0, [])]
    for role in roles:
        item = by_role[role]
        must = must_have(role)
        nxt = []
        for st in states:
            for p, pref in _candidates(st, S, role, item):
                if bedroom_role(role) == "кровать" and not _bed_ok(room, S, p):
                    continue
                if not _fits(st, S, p):
                    continue
                keep = st.keep + [(role, z, ex) for z, ex in _keepouts(p, st.placed + [p], room)]
                nxt.append(_State(st.placed + [p], keep, st.score + pref, st.skipped))
            if not must:
                nxt.append(_State(st.placed, st.keep, st.score - WEIGHT.get(bedroom_role(role), 1.0) * 10,
                                  st.skipped + [role]))
        if not nxt:
            # обязательное не встало — спальни с этим набором нет: полупустой план (шкаф без кровати) не отдаём
            meta["reason"].append("BED_NO_FIT" if bedroom_role(role) == "кровать" else "REQUIRED_NO_FIT")
            meta["no_fit"] = role
            return Layout(room=room, placements=[], meta=meta, unplaced=sorted(r for r in by_role if must_have(r)),
                          skipped_optional=sorted(r for r in by_role if not must_have(r)))
        nxt.sort(key=_State.key)
        states = _dedupe(nxt)[:beam]

    best, best_key = None, None
    for st in states:
        st, lay = _repair(room, st, must_have)
        hard = sum(v.severity is Severity.HARD for v in lay.violations)
        soft = sum(SOFT_PENALTY.get(v.code, 0.5) for v in lay.violations if v.severity is Severity.SOFT)
        k = (hard, -(st.score - soft), st.key()[1])
        if best_key is None or k < best_key:
            best, best_key = (st, lay), k
    st, lay = best
    placed_roles = {p.role for p in st.placed}
    lay.unplaced = sorted(r for r in by_role if must_have(r) and r not in placed_roles)
    lay.skipped_optional = sorted(r for r in by_role if not must_have(r) and r not in placed_roles)
    if any(v.severity is Severity.HARD for v in lay.violations):
        meta["reason"].append("HARD_LEFT")
    if lay.unplaced and not meta["reason"]:
        meta["reason"].append("REQUIRED_NO_FIT")
    meta["template"] = next((p.tpl_id for p in st.placed if bedroom_role(p.role) == "кровать"), "")
    lay.meta = meta
    return lay


def _repair(room: Room, st: _State, must_have, strict: bool = False) -> tuple[_State, Layout]:
    """Полная проверка ловит то, чего не видит пошаговая (проход 46 до предмета через всю комнату). Жёсткое
    из-за ОПЦИОНАЛЬНОГО предмета — снимаем его (самый лёгкий по весу первым) в «не нашлось места», а не сдаём брак.
    must_have(роль) — обязательна ли роль по назначению (с детскими псевдонимами). strict — проверки движка групп."""
    placed = list(st.placed)
    while True:
        lay = validate_bedroom(room, placed, strict=strict)
        bad = {r for v in lay.violations if v.severity is Severity.HARD for r in v.roles}
        drop = sorted((p for p in placed if p.role in bad and not must_have(p.role)),
                      key=lambda p: (WEIGHT.get(bedroom_role(p.role), 1.0), p.role))
        if not drop:
            break
        gone = drop[0].role
        # стул без стола и стол без стула не оставляем: группа уходит целиком; без кровати уходят и тумбы
        placed = [p for p in placed if p.role != gone and not same_group(p.role, gone)
                  and not (bedroom_role(gone) == "кровать" and bedroom_role(p.role) == "тумба прикроватная")]
    if len(placed) == len(st.placed):
        return st, lay
    lost = sum(WEIGHT.get(bedroom_role(p.role), 1.0) * 10 for p in st.placed if p not in placed)
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


# ───────────────────────── движок ГРУПП-ШАБЛОНОВ (T-20261112-38/2, план bedroom-groups-01, ADR-0384) ─────────────────────────
# Группа ставится целиком или не ставится: «сон» (кровать + тумбы вплотную по бокам) — по варианту pair → one_side → solo;
# работа (стол + стул) — вместе; хранение и туалетный — каждый предмет спинкой к стене. Порядок — сначала группы с
# обязательными ролями назначения (кабинет и детская 7–12 — стол первым), потом `order` паспорта. Шаблон, группы, варианты
# и уровни-составы — паспорт общего формата `rules/room-templates/bedroom.json` (`planner/room_templates.py`); здесь —
# геометрия групп. Уровень — ЦЕЛЫЙ состав (Codex): pair + хранение > one_side + хранение > pair без хранения; варианты «сна»
# перебираем по порядку шаблона и останавливаемся, когда лучший уровень уже не улучшить. Строгие проверки
# (`bedroom_checks.check_group_rules`) — и в луче, и в финальной.

VARIANTS = ("pair", "one_side", "solo")
NS_NEED = {"pair": 2, "one_side": 1, "solo": 0}
CENTER_PER_CM = 0.01          # пара: штраф за отход центра кровати от центра стены, на см (мягко — уступает дуге двери)
_GENERIC = {"id": "br.generic", "groups": [{"id": "sleep", "variants": list(VARIANTS)}, {"id": "storage", "variants": ["each_on_wall"]}],
            "levels": [{"id": f"{s}{i}", "use": u} for i, (s, u) in enumerate(
                [(v[0].upper(), {"sleep": v, "storage": "each_on_wall"}) for v in VARIANTS] + [(v[0], {"sleep": v}) for v in VARIANTS])]}


def group_of(role: str) -> str:
    """Группа роли по паспорту `rules/room-templates/bedroom.json` groups[*].roles (детские роли — через псевдонимы);
    вне групп — сама роль."""
    return RT.group_of("bedroom", bedroom_role(role)) or "other:" + role


def _found(tpl: dict, placed: list[Placement]) -> dict:
    """{группа: вариант} фактической раскладки для выбора уровня: «сон» — по числу тумб, прочие — первый вариант группы,
    если её роль стоит."""
    out = {}
    roles = {group_of(p.role) for p in placed}
    for g in tpl.get("groups", []):
        if g["id"] == "sleep":
            v = _variant_of(placed)
            if v:
                out["sleep"] = v
        elif g["id"] in roles and g.get("variants"):
            out[g["id"]] = g["variants"][0]
    return out


def _relation(tpl: dict, kind: str, purpose: str) -> bool:
    return any(r.get("kind") == kind and (not r.get("purpose") or purpose in r["purpose"]) for r in tpl.get("relations", []))


def _wardrobe_denied(room: Room, purpose: str, tpl: dict | None = None) -> bool:
    """ADR-0384 поправка 2: пара в малой (≤ bedroom_small_couple_max_m2) и НЕ вытянутой комнате — без шкафа
    (связь шаблона no_wardrobe_small_square)."""
    if purpose != "couple" or (tpl is not None and not _relation(tpl, "no_wardrobe_small_square", purpose)):
        return False
    w, d = room.width_cm, room.depth_cm
    aspect = max(w, d) / max(1.0, min(w, d))
    return room.area_m2 <= num("bedroom_small_couple_max_m2", 10.5) and aspect < num("bedroom_elongated_aspect_min", 1.4)


def _bed_tpl(S: _Statics, role: str, item: Item) -> str:
    probe = Placement(role=role, item=item, x=0, y=0)
    dbl = is_double(probe)
    tpl = S.bed_tpl if (S.bed_tpl and not dbl) else ("bed_center_wall" if dbl else "bed_corner")
    return "bed_side_back_corner" if side_back(probe) else tpl


def _pref_g(S: _Statics, p: Placement, slot) -> float:
    """Предпочтения движка групп: как `_pref`, но двуспальная — к центру стены по сантиметрам (центр уступает дуге двери
    и проходам, которые здесь жёсткие), а не по доле стены."""
    if bedroom_role(p.role) == "кровать" and is_double(p) and p.tpl_id == "bed_center_wall":
        _, _, _rot, frac, L, _edge = slot
        return -CENTER_PER_CM * abs(frac * L - L / 2)
    return _pref(S, p, slot)


def _hz(S: _Statics, bed: Placement) -> list:
    """Зоны у изголовья кровати (кэш на позицию: в луче одна кровать проверяется тысячи раз)."""
    k = (bed.x, bed.y, int(bed.rot), bed.item.w_cm, bed.item.d_cm)
    if k not in S.hz:
        S.hz[k] = head_side_zones(S.room, bed)
    return S.hz[k]


def _strict_fit(S: _Statics, p: Placement, placed: list[Placement]) -> bool:
    """Строгие проверки движка групп для одного нового предмета (то же, что `check_group_rules`, но сразу в луче)."""
    r = bedroom_role(p.role)
    if r == "кровать":
        if foot_swing_share(S.room, p, S.swings) >= num("bed_foot_swing_max_share", 0.15):
            return False
        stor = [q for q in placed if bedroom_role(q.role) in STORAGE_LIKE]
        return not stor or not any(z.intersection(footprint(q)).area > AREA_EPS for z in _hz(S, p) for q in stor)
    if r in STORAGE_LIKE:
        fp = footprint(p)
        for b in placed:
            if bedroom_role(b.role) == "кровать" and any(z.intersection(fp).area > AREA_EPS for z in _hz(S, b)):
                return False
        if r in ("шкаф", "комод") and S.rads:
            k = (p.x, p.y, int(p.rot), p.item.w_cm, p.item.d_cm)
            if k not in S.reach:
                S.reach[k] = front_reach(p)
            near = S.reach[k]
            if any(near.intersection(rp).area > AREA_EPS for rp in S.rads):
                return False
    return True


def _chain(st: _State, S: _Statics, plist: list[Placement], pref: float) -> _State | None:
    """Группа целиком: каждый предмет проходит «влезает» и строгие проверки с уже стоящими и предыдущими из группы."""
    cur = st
    for p in plist:
        if bedroom_role(p.role) == "кровать" and not _bed_ok(S.room, S, p):
            return None
        if not _fits(cur, S, p) or not _strict_fit(S, p, cur.placed):
            return None
        keep = cur.keep + [(p.role, z, ex) for z, ex in _keepouts(p, cur.placed + [p], S.room)]
        cur = _State(cur.placed + [p], keep, cur.score, cur.skipped)
    cur.score = st.score + pref
    return cur


def _free_side_ok(S: _Statics, bed: Placement, sides) -> bool:
    """Бок кровати без тумбы — либо к стене (зазор ≤ WALL_GAP_CM), либо с полным проходом (bed_side_passage) внутри
    комнаты: узкая «мёртвая» полоса между боком и стеной не годится (T-20261112-38, лист UK 325×280)."""
    z = bed_zones(bed)
    for s in sides:
        wall = z[f"{s}_wall"]
        if wall.difference(S.poly).area >= 0.8 * wall.area:
            continue
        if z[s].difference(S.poly).area > AREA_EPS:
            return False
    return True


def _sleep_units(st: _State, S: _Statics, bed_role: str, bed: Item, ns: list[tuple[str, Item]], variant: str):
    """Кандидаты группы «сон» варианта: кровать в слоте + тумбы вплотную по бокам (pair — обе, one_side — одна слева или
    справа, solo — без тумб). Бок без тумбы — к стене или с полным проходом (`_free_side_ok`)."""
    for slot in _slots(S.room, bed):
        p = _place(bed_role, bed, slot[0], slot[1], slot[2], _bed_tpl(S, bed_role, bed))
        pref = _pref_g(S, p, slot)
        if variant == "solo":
            if _free_side_ok(S, p, ("left", "right")):
                yield [p], pref
            continue
        if variant == "pair":
            (r0, i0), (r1, i1) = ns[0], ns[1]
            a = list(_nightstand_spots(p, i0))[0]
            b = list(_nightstand_spots(p, i1))[1]
            ps = [_place(r0, i0, a[0], a[1], int(p.rot), p.tpl_id), _place(r1, i1, b[0], b[1], int(p.rot), p.tpl_id)]
            if all(nightstand_ok(S.room, n, [p]) for n in ps):
                yield [p] + ps, pref
            continue
        r0, i0 = ns[0]
        for (x, y), free in zip(_nightstand_spots(p, i0), ("right", "left")):
            n = _place(r0, i0, x, y, int(p.rot), p.tpl_id)
            if nightstand_ok(S.room, n, [p]) and _free_side_ok(S, p, (free,)):
                yield [p, n], pref


def _work_units(st: _State, S: _Statics, desk_role: str, desk: Item, chair: tuple[str, Item] | None):
    for p, pref in _candidates(st, S, desk_role, desk):
        if chair is None:
            yield [p], pref
            continue
        x, y, rot = _chair_spot(p, chair[1])
        yield [p, _place(chair[0], chair[1], x, y, rot, p.tpl_id)], pref


def _single_units(st: _State, S: _Statics, role: str, item: Item):
    for p, pref in _candidates(st, S, role, item):
        yield [p], pref


def _diverse(states: list[_State], beam: int) -> list[_State]:
    """Луч по группе «сон»: держим РАЗНЫЕ стены изголовья (Codex: пары «сон × хранение» на разных стенах), по кругу —
    лучший каждой стены, потом второй и т. д."""
    buckets: dict = {}
    for st in states:
        bed = next((p for p in st.placed if bedroom_role(p.role) == "кровать"), None)
        buckets.setdefault(int(bed.rot) if bed else -1, []).append(st)
    out, k = [], 0
    while len(out) < beam and any(len(v) > k for v in buckets.values()):
        for v in buckets.values():
            if len(v) > k and len(out) < beam:
                out.append(v[k])
        k += 1
    return sorted(out, key=_State.key)


def _stages(by_role: dict, must_have, order: list[str], denied: set) -> list[tuple]:
    """Группы набора по порядку: (имя, обязательна ли, роли). Группы с обязательной ролью — первыми."""
    groups: dict = {}
    for role in sorted(by_role, key=_order_key):
        if role in denied:
            continue
        groups.setdefault(group_of(role), []).append(role)
    idx = {g: i for i, g in enumerate(order)}
    names = sorted(groups, key=lambda g: (not any(must_have(r) for r in groups[g]), idx.get(g, len(order)), g))
    return [(g, any(must_have(r) for r in groups[g]), groups[g]) for g in names]


def _run_variant(S: _Statics, by_role: dict, stages: list, variant: str | None, must_have, beam: int) -> tuple:
    """Луч по группам для одного варианта «сна» → (состояния, None) или (None, роли не вставшей обязательной группы)."""
    states = [_State([], [], 0.0, [])]
    for g, required, roles in stages:
        if g == "sleep":
            bed_role = next((r for r in roles if bedroom_role(r) == "кровать"), None)
            ns = [(r, by_role[r]) for r in roles if bedroom_role(r) == "тумба прикроватная"]
            units = [("sleep", roles, lambda st, br=bed_role, ns=ns: _sleep_units(st, S, br, by_role[br], ns, variant))] \
                if bed_role else [(r, [r], lambda st, r=r: _single_units(st, S, r, by_role[r])) for r in roles]
            bed_required = bool(bed_role) and must_have(bed_role)
        elif g == "work":
            desk = next((r for r in roles if bedroom_role(r) == "стол рабочий"), None)
            chair = next(((r, by_role[r]) for r in roles if bedroom_role(r) == "стул рабочий"), None)
            units = [("work", roles, lambda st, d=desk, c=chair: _work_units(st, S, d, by_role[d], c))] if desk else \
                [(r, [r], lambda st, r=r: _single_units(st, S, r, by_role[r])) for r in roles]
            bed_required = False
        else:
            units = [(r, [r], lambda st, r=r: _single_units(st, S, r, by_role[r])) for r in roles]
            bed_required = False
        for name, uroles, gen in units:
            must = any(must_have(r) for r in uroles) or (name == "sleep" and bed_required)
            nxt = []
            for st in states:
                for plist, pref in gen(st):
                    got = _chain(st, S, plist, pref)
                    if got is not None:
                        nxt.append(got)
                if not must:
                    lost = [r for r in uroles if not (name == "sleep" and bedroom_role(r) == "тумба прикроватная")]
                    nxt.append(_State(st.placed, st.keep,
                                      st.score - sum(WEIGHT.get(bedroom_role(r), 1.0) * 10 for r in lost), st.skipped + uroles))
            if not nxt:
                return None, uroles
            nxt.sort(key=_State.key)
            nxt = _dedupe(nxt)
            states = _diverse(nxt, beam) if name == "sleep" else nxt[:beam]
    return states, None


def _variant_of(placed: list[Placement]) -> str | None:
    if not any(bedroom_role(p.role) == "кровать" for p in placed):
        return None
    n = sum(1 for p in placed if bedroom_role(p.role) == "тумба прикроватная")
    return "pair" if n >= 2 else ("one_side" if n == 1 else "solo")


def _solve_groups(room: Room, items: list[Item], purpose: str, *, beam: int = BEAM) -> Layout:
    cfg, meta, must_have, by_role, early = _prelude(room, items, purpose, "bedroom-groups-v1")
    meta["engine"] = "groups"
    if early is not None:
        return early
    doc = RT.load("bedroom")
    tpl = RT.template_for("bedroom", purpose, room.child_age) or _GENERIC
    S = _Statics(room)
    S.bed_tpl = cfg.get("bed_template")
    S.swings = door_swings(room)
    S.rads = [radiator_polygon(room, r) for r in room.radiators]
    S.hz, S.reach = {}, {}
    denied = set()
    if _wardrobe_denied(room, purpose, tpl):
        denied = {r for r in by_role if bedroom_role(r) == "шкаф" and not must_have(r)}
        if denied:
            meta["storage_why"] = "WARDROBE_SMALL_SQUARE"
    stages = _stages(by_role, must_have, doc.get("order", ["sleep", "work", "storage", "dressing"]), denied)
    has_bed = any(bedroom_role(r) == "кровать" for r in by_role)
    n_ns = sum(1 for r in by_role if bedroom_role(r) == "тумба прикроватная")
    order = RT.variants(tpl, "sleep") or list(VARIANTS)
    variants = [v for v in order if NS_NEED.get(v, 99) <= n_ns] if has_bed else [None]
    storage_kit = any(group_of(r) == "storage" for r in by_role if r not in denied)
    couple = cfg.get("bed") == "double"
    step = tpl.get("next_step") or {}
    step_on = bool(step) and purpose in (step.get("purpose") or [purpose])
    sleep_next = f"bed_{step.get('value')}" if step_on else None

    def n_storage(placed):
        return sum(1 for p in placed if group_of(p.role) == "storage")

    best, best_key, tried, failed = None, None, [], None
    for i, v in enumerate(variants):
        states, why = _run_variant(S, by_role, stages, v, must_have, beam)
        tried.append(v)
        if not states:
            failed = failed or why
            continue
        top = None
        for st in states:
            st, lay = _repair(room, st, must_have, strict=True)
            hard = sum(x.severity is Severity.HARD for x in lay.violations)
            soft = sum(SOFT_PENALTY.get(x.code, 0.5) for x in lay.violations if x.severity is Severity.SOFT)
            miss = sum(1 for r in by_role if must_have(r) and r not in {p.role for p in st.placed})
            lvl, _ = RT.level_of(tpl, _found(tpl, st.placed))
            k = (hard, miss, lvl, -n_storage(st.placed), -round(st.score - soft, 3), st.key()[1])
            if top is None or k < top[0]:
                top = (k, st, lay)
        if best_key is None or top[0] < best_key:
            best_key, best = top[0], (top[1], top[2])
        rest = [RT.best_possible(tpl, "sleep", w) for w in variants[i + 1:]]
        if best_key[0] == 0 and best_key[1] == 0 and (not rest or best_key[2] <= min(rest)):
            break                                  # лучший уровень дальше не улучшить — следующие варианты «сна» не нужны
    meta["variants_tried"] = tried
    if best is None:
        bed_role = next((r for r in (failed or []) if bedroom_role(r) == "кровать"), None)
        code = "BED_NO_FIT" if bed_role else "REQUIRED_NO_FIT"
        meta["reason"].append(code)
        meta["no_fit"] = bed_role or next((r for r in (failed or []) if must_have(r)), None)
        meta["composition"] = {"template": tpl["id"], "level": None, "degraded_from": [lv["id"] for lv in tpl.get("levels", [])]}
        if couple and code == "BED_NO_FIT" and sleep_next:
            meta["sleep_next"] = sleep_next
        return Layout(room=room, placements=[], meta=meta, unplaced=sorted(r for r in by_role if must_have(r)),
                      skipped_optional=sorted(r for r in by_role if not must_have(r)))
    st, lay = best
    placed_roles = {p.role for p in st.placed}
    lay.unplaced = sorted(r for r in by_role if must_have(r) and r not in placed_roles)
    lay.skipped_optional = sorted(r for r in by_role if not must_have(r) and r not in placed_roles)
    if any(v.severity is Severity.HARD for v in lay.violations):
        meta["reason"].append("HARD_LEFT")
    if lay.unplaced and not meta["reason"]:
        meta["reason"].append("REQUIRED_NO_FIT")
    var = _variant_of(st.placed)
    meta["template"] = next((p.tpl_id for p in st.placed if bedroom_role(p.role) == "кровать"), "")
    meta["sleep_variant"] = var
    if var in ("one_side", "solo") and n_ns > NS_NEED[var]:
        meta["sleep_why"] = "NIGHTSTAND_PAIR_NO_FIT" if var == "one_side" else "NIGHTSTAND_NO_FIT"
    meta["groups"] = {}
    for p in st.placed:
        meta["groups"].setdefault(group_of(p.role), []).append(p.role)
    lvl, lid = RT.level_of(tpl, _found(tpl, st.placed))
    meta["composition"] = {"template": tpl["id"], "level": lid,
                           "degraded_from": [lv["id"] for lv in tpl.get("levels", [])[:lvl]]}
    before = RT.level_index(tpl, step.get("before_level"))
    if couple and sleep_next and var is not None and storage_kit and before is not None and lvl >= before:
        meta["sleep_next"] = sleep_next          # ступень 140 раньше «без хранения» (next_step.before_level шаблона)
    lw = tpl.get("label_without") or {}
    if lw and lw.get("group") not in _found(tpl, st.placed) and not lay.unplaced and st.placed:
        meta["room_label"] = lw["label"]         # ADR-0384 поправка 3: без кровати — «кабинет», не спальня
    lay.meta = meta
    return lay

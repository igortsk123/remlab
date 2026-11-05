"""Посадка КУХНИ на план комнаты (план onb-09 Т2, ADR-0330 п.1/7): какая стена, с какого места, форма, где колонны и
холодильник, у какой точки вентканал. Модуль отдельный (`room_type=kitchen`): путь гостиной и спальни не трогает.

Перебор: каждая стена прямоугольной комнаты × положение ряда вдоль неё (углы, края препятствий, сетка 10 см) × конец
колонн. Жёсткие проверки — ряд не на двери (дуга створки, полоса прохода, косяк), не на радиаторе, колонны и верхние
шкафы не у окна, нижний ряд под окном — только при высоком подоконнике, рабочий проход перед линией, место холодильнику.
Из годных — лучшая по весам `rules/kitchen.json` score (глухая стена, близко вентканал, колонны дальше от двери, в угол).
Не встало ни одно положение — `ok: False` и коды причин с числами. Треугольник и модули внутри ряда меряет набор
(`lib/viewer3d/kits/kitchen-checks.ts`) — по точкам, которые отдаёт посадка (`vent_at_cm`, `fridge_at_cm`, `no_hob_cm`).

ПУТЬ НАБОРА `s` (как `kitchen-layout.ts`): 0 — левый конец линии, если стоять в комнате лицом к стене, L — правый.
"""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .bedroom_checks import num
from .geometry import _wall_point, _wall_strip, radiator_polygon, swing_polygon
from .models import Room

RULES_PATH = Path(__file__).resolve().parent.parent / "rules" / "kitchen.json"
WALLS = ("north", "south", "west", "east")
# Набор ставится как предмет (`Placement`: центр, `rot` по часовой, 0 → лицом в +y; в сцене `rotation.y = rot`, x → X, y → Z —
# `lib/viewer3d/viewer.ts:placeGroup`). Лицо набора — внутренняя нормаль стены (+Z набора), его +X («правая рука» стоящего лицом
# к стене) после поворота rot: (cos rot, −sin rot) в осях плана.
ROT = {"south": 0, "west": 90, "north": 180, "east": 270}
RIGHT = {"south": (1.0, 0.0), "north": (-1.0, 0.0), "west": (0.0, -1.0), "east": (0.0, 1.0)}
NORMAL = {"south": (0.0, 1.0), "north": (0.0, -1.0), "west": (1.0, 0.0), "east": (-1.0, 0.0)}
FLIP = {w: (RIGHT[w][0] + RIGHT[w][1]) < 0 for w in WALLS}   # путь набора идёт против отсчёта стены (запад→восток / юг→север)
# угол: (стена, конец 0 — начало отсчёта / 1 — конец) → (соседняя стена, её конец)
CORNER = {("south", 0): ("west", 0), ("south", 1): ("east", 0), ("north", 0): ("west", 1), ("north", 1): ("east", 1),
          ("west", 0): ("south", 0), ("west", 1): ("north", 0), ("east", 0): ("south", 1), ("east", 1): ("north", 1)}
STEP_CM = 10.0
EPS = 0.5


@lru_cache(maxsize=1)
def kitchen_rules() -> dict:
    return json.loads(RULES_PATH.read_text(encoding="utf-8"))


def rule(section: str, key: str) -> float:
    return float(kitchen_rules()[section][key]["v"])


@dataclass(frozen=True)
class KitchenKit:
    """Что сажаем: основная линия (вместе с колоннами и угловым квадратом Г), глубина, форма, колонны у одного конца."""

    length_cm: float
    depth_cm: float = 60.0
    shape: str = "straight"
    tall_cm: float = 0.0
    uppers: bool = True
    fridge_in_column: bool = False
    leg_cm: float | None = None
    peninsula: bool = False
    # глубина верхних шкафов — как `kitchen-layout.ts:UPPER_D` (сверяет tests/unit/kitchen-fit.test.ts)
    upper_depth_cm: float = 35.0


@dataclass(frozen=True)
class Vent:
    """Вентканал на стене; `assumed` — места нет в данных застройщика, это допущение (помечается в отчёте)."""

    wall: str
    offset_cm: float
    assumed: bool = True


def wall_len(room: Room, wall: str) -> float:
    return room.width_cm if wall in ("south", "north") else room.depth_cm


def room_depth(room: Room, wall: str) -> float:
    """От стены ряда до стены напротив."""
    return room.depth_cm if wall in ("south", "north") else room.width_cm


def _u_of_s(wall: str, u0: float, length: float, s: float) -> float:
    return u0 + length - s if FLIP[wall] else u0 + s


def _strip_s(room: Room, wall: str, u0: float, length: float, s0: float, s1: float, depth: float) -> Polygon:
    a, b = sorted((_u_of_s(wall, u0, length, s0), _u_of_s(wall, u0, length, s1)))
    return _wall_strip(room, wall, a, b - a, depth)


def _hits(poly: Polygon, obstacles: list[tuple[str, Polygon]]) -> list[str]:
    return sorted({code for code, ob in obstacles if poly.intersection(ob).area > EPS})


class _Statics:
    """Что занято до кухни: двери (дуга, полоса прохода, косяк), радиаторы, окна (с запасом — для высокого)."""

    def __init__(self, room: Room):
        passage = rule("openings", "door_passage_cm")
        jamb = rule("openings", "door_jamb_gap_cm")
        gap = num("sofa_to_radiator_wall", 15)          # тот же порог, что `validate.check_radiators` (одно число)
        clear = rule("openings", "window_clear_cm")
        self.floor: list[tuple[str, Polygon]] = []
        self.doors: list[Point] = []
        for op in room.openings:
            if op.kind == "window":
                continue
            sw = swing_polygon(room, op)
            if not sw.is_empty:
                self.floor.append(("KITCHEN_DOOR_SWING", sw))
            self.floor.append(("KITCHEN_DOOR_PASSAGE", _wall_strip(room, op.wall, op.offset_cm, op.width_cm, passage)))
            self.floor.append(("KITCHEN_DOOR_JAMB", _wall_strip(room, op.wall, op.offset_cm - jamb, op.width_cm + 2 * jamb, 1.0)))
            self.doors.append(_wall_point(room, op.wall, op.offset_cm + op.width_cm / 2))
        for rad in room.radiators:
            self.floor.append(("KITCHEN_RADIATOR", radiator_polygon(room, rad).buffer(gap)))
        windows = [op for op in room.openings if op.kind in ("window", "balcony")]
        # высокое (колонны, верх, холодильник) — не ближе `window_clear_cm` к откосу; низ — только ниже подоконника
        self.tall = [("KITCHEN_WINDOW_TALL", _wall_strip(room, op.wall, op.offset_cm - clear, op.width_cm + 2 * clear, 1.0)) for op in windows]
        low = rule("openings", "base_under_window_min_sill_cm")
        self.base = [("KITCHEN_WINDOW_SILL", _wall_strip(room, op.wall, op.offset_cm, op.width_cm, 1.0))
                     for op in windows if op.kind == "balcony" or op.sill_cm < low]
        self.windows = windows
        self.room = room
        self._fridge_free: list[tuple[str, float, Polygon]] | None = None

    def fridge_free(self) -> list[tuple[str, float, Polygon]]:
        """Места холодильника у стен, свободные от дверей, радиаторов и окон (сетка 10 см) — один раз на комнату."""
        if self._fridge_free is None:
            room, fw, fd = self.room, rule("fridge", "w_cm"), rule("fridge", "d_cm")
            taken = unary_union([ob for _, ob in self.floor + self.tall]) if self.floor or self.tall else None
            out = []
            for side in WALLS:
                a = 0.0
                while a + fw <= wall_len(room, side) + EPS:
                    poly = _wall_strip(room, side, a, fw, fd)
                    if taken is None or poly.intersection(taken).area <= EPS:
                        out.append((side, a, poly))
                    a += STEP_CM
            self._fridge_free = out
        return self._fridge_free


def _vent_point(room: Room, vent: Vent | None) -> Point | None:
    return _wall_point(room, vent.wall, vent.offset_cm) if vent else None


def _end_u(wall: str, u0: float, length: float, end: str) -> float:
    """Отсчёт стены у конца набора `start` (s=0) или `end` (s=L)."""
    return _u_of_s(wall, u0, length, 0.0 if end == "start" else length)


def _room_corner(room: Room, wall: str, u: float) -> int | None:
    if abs(u) < EPS:
        return 0
    if abs(u - wall_len(room, wall)) < EPS:
        return 1
    return None


def _leg_polys(room: Room, kit: KitchenKit, wall: str, u0: float, end: str) -> tuple[Polygon, Polygon | None, str | None]:
    """Плечо Г у конца `end`: низ (D поперёк, `leg_cm` от стены в комнату) и верх вдоль боковой стены (нет у полуострова)."""
    leg = kit.leg_cm or rule("shapes", "corner_leg_cm")
    D = kit.depth_cm
    s0, s1 = (0.0, D) if end == "start" else (kit.length_cm - D, kit.length_cm)
    a, b = sorted((_u_of_s(wall, u0, kit.length_cm, s0), _u_of_s(wall, u0, kit.length_cm, s1)))
    base = _wall_strip(room, wall, a, b - a, leg)
    side = None
    corner = _room_corner(room, wall, _end_u(wall, u0, kit.length_cm, end))
    if corner is not None:
        side = CORNER[(wall, corner)][0]
    upper = None
    if kit.uppers and not kit.peninsula and side:
        nb = CORNER[(wall, corner)][1]
        L2 = wall_len(room, side)
        upper = _wall_strip(room, side, 0 if nb == 0 else L2 - leg, leg, kit.upper_depth_cm)
    return base, upper, side


def _check(room: Room, kit: KitchenKit, st: _Statics, wall: str, u0: float, columns_at: str | None,
           corner_at: str | None, cooks: int) -> dict:
    """Одно положение: годно ли (коды отказа) и что о нём знать дальше (холодильник, окно над рядом)."""
    L, D = kit.length_cm, kit.depth_cm
    fail: list[str] = []
    checks: list[dict] = []
    run = _strip_s(room, wall, u0, L, 0, L, D)
    fail += _hits(run, st.floor) + _hits(run, st.base)
    tall = None
    if kit.tall_cm > 0 and columns_at:
        s0, s1 = (0.0, kit.tall_cm) if columns_at == "start" else (L - kit.tall_cm, L)
        tall = _strip_s(room, wall, u0, L, s0, s1, D)
        fail += _hits(tall, st.tall)
    if kit.uppers:
        s0, s1 = (kit.tall_cm, L) if columns_at == "start" else (0.0, L - kit.tall_cm)
        fail += _hits(_strip_s(room, wall, u0, L, s0, s1, kit.upper_depth_cm), st.tall)
    work = rule("aisle", "work_two_cooks_cm" if cooks == 2 else "work_one_cook_cm")
    depth = room_depth(room, wall)
    checks.append({"code": "KITCHEN_AISLE", "value": round(depth - D), "need": work, "ok": depth - D >= work})
    leg_base = None
    if corner_at:
        leg_base, leg_upper, side = _leg_polys(room, kit, wall, u0, corner_at)
        if not side and not kit.peninsula:
            fail.append("KITCHEN_LEG_NO_WALL")
        fail += _hits(leg_base, st.floor) + _hits(leg_base, st.base)
        if leg_upper is not None:
            fail += _hits(leg_upper, st.tall)
        leg = kit.leg_cm or rule("shapes", "corner_leg_cm")
        walk = num("passage_main", 91)
        checks.append({"code": "KITCHEN_LEG_WALKWAY", "value": round(depth - leg), "need": walk, "ok": depth - leg >= walk})
        across = wall_len(room, wall) - D
        checks.append({"code": "KITCHEN_LEG_AISLE", "value": round(across), "need": work, "ok": across >= work})
    fail += [c["code"] for c in checks if not c["ok"]]
    spots: list[dict] = []
    if not kit.fridge_in_column and not fail:
        n = NORMAL[wall]
        x0, y0, x1, y1 = run.bounds
        aisle = box(min(x0, x0 + n[0] * (D + work)), min(y0, y0 + n[1] * (D + work)),
                    max(x1, x1 + n[0] * (D + work)), max(y1, y1 + n[1] * (D + work)))
        busy = [aisle] + ([leg_base.buffer(work, join_style=2)] if leg_base is not None else [])
        spots = _fridge_spots(room, kit, st, wall, u0, columns_at, corner_at, busy)
        if not spots:
            fail.append("KITCHEN_FRIDGE_NO_PLACE")
    return {"fail": sorted(set(fail)), "checks": checks, "fridge": spots, "run": run, "tall": tall, "leg": leg_base}


def _local(room: Room, wall: str, u0: float, length: float, P: Point) -> dict:
    """Точка плана в осях набора: `s` — по пути набора от его левого конца, `out` — от задней стены в комнату."""
    o = _wall_point(room, wall, _u_of_s(wall, u0, length, 0.0))
    r, n = RIGHT[wall], NORMAL[wall]
    dx, dy = P.x - o.x, P.y - o.y
    return {"s": round(dx * r[0] + dy * r[1], 1), "out": round(dx * n[0] + dy * n[1], 1)}


def _spot(room: Room, wall: str, u0: float, L: float, side: str, a: float, where: str, blind=None) -> dict:
    fw, fd = rule("fridge", "w_cm"), rule("fridge", "d_cm")
    poly = _wall_strip(room, side, a, fw, fd)
    c = _wall_point(room, side, a + fw / 2)
    front = Point(c.x + NORMAL[side][0] * fd, c.y + NORMAL[side][1] * fd)   # середина дверцы — точка треугольника
    return {"where": where, "wall": side, "offset_cm": round(a, 1), **_local(room, wall, u0, L, front), "poly": poly, "blind": blind}


def _fridge_spots(room: Room, kit: KitchenKit, st: _Statics, wall: str, u0: float, columns_at: str | None,
                  corner_at: str | None, busy: list[Polygon]) -> list[dict]:
    """Где встанет отдельный холодильник (`rules/kitchen.json` fridge), по убыванию предпочтения — берётся первый непустой ярус:
    `end` — у свободного конца на своей стене (`kitchen-from-example.ts:freeEndFridgesCm`) или `leg` — у конца плеча Г;
    `corner` — ряд впритык к углу, у конца нет места: на соседней стене сразу за глубиной ряда, последние `d_cm` ряда
    глухие (`blind` — без мойки и варочной); `wall` — у любой стены вне ряда, его рабочего прохода и прохода у двери
    (ближайшее к середине ряда). У места — точка дверцы в осях набора (`s`, `out`) и след `poly`."""
    R = kitchen_rules()["fridge"]
    fw, fd = rule("fridge", "w_cm"), rule("fridge", "d_cm")
    L, Lw, D = kit.length_cm, wall_len(room, wall), kit.depth_cm
    room_poly = box(0, 0, room.width_cm, room.depth_cm)
    clear = st.floor + st.tall + [("RUN", b) for b in busy]
    # за углом холодильник по определению стоит перед глухим концом ряда — проход перед рядом ему не помеха
    clear_corner = st.floor + st.tall + [("RUN", b) for b in busy[1:]]

    def good(s: dict, obstacles=None) -> bool:
        return 0 <= s["offset_cm"] + EPS and s["offset_cm"] + fw <= wall_len(room, s["wall"]) + EPS \
            and not _hits(s["poly"], clear if obstacles is None else obstacles) and room_poly.contains(s["poly"].buffer(-EPS))

    near: list[dict] = []
    corner_spots: list[dict] = []
    ends = [e for e in ("start", "end") if not (kit.tall_cm > 0 and columns_at == e) and corner_at != e]
    for e in ends:
        s0, s1 = (-fw, 0.0) if e == "start" else (L, L + fw)
        a = min(_u_of_s(wall, u0, L, s0), _u_of_s(wall, u0, L, s1))
        sp = _spot(room, wall, u0, L, wall, a, "end")
        if good(sp):
            near.append(sp)
            continue
        corner = _room_corner(room, wall, _end_u(wall, u0, L, e))
        if corner is None or not R["around_corner"]["v"]:
            continue
        side, nb = CORNER[(wall, corner)]
        a = D if nb == 0 else wall_len(room, side) - D - fw
        blind = [0.0, fd] if e == "start" else [round(L - fd, 1), L]
        sp = _spot(room, wall, u0, L, side, a, "corner", blind)
        if good(sp, clear_corner):
            corner_spots.append(sp)
    if corner_at and not kit.peninsula:
        leg = kit.leg_cm or rule("shapes", "corner_leg_cm")
        corner = _room_corner(room, wall, _end_u(wall, u0, L, corner_at))
        if corner is not None:
            side, nb = CORNER[(wall, corner)]
            a = leg if nb == 0 else wall_len(room, side) - leg - fw
            sp = _spot(room, wall, u0, L, side, a, "leg")
            if good(sp):
                near.append(sp)
    for tier in (near, corner_spots):
        if tier:
            return sorted(tier, key=lambda f: (f["s"], f["out"]))
    if not R["anywhere"]["v"]:
        return []
    mid = _wall_point(room, wall, u0 + L / 2)
    best = None
    boxes = [b.bounds for b in busy]                      # проход и плечо — прямоугольники: хватает границ
    for side, off, poly in st.fridge_free():
        x0, y0, x1, y1 = poly.bounds
        if any((min(x1, b[2]) - max(x0, b[0])) * (min(y1, b[3]) - max(y0, b[1])) > EPS
               and min(x1, b[2]) > max(x0, b[0]) and min(y1, b[3]) > max(y0, b[1]) for b in boxes):
            continue
        key = (round(poly.centroid.distance(mid), 1), WALLS.index(side), off)
        if best is None or key < best[0]:
            best = (key, side, off)
    if best:
        return [_spot(room, wall, u0, L, best[1], best[2], "wall")]
    return []


def _positions(room: Room, kit: KitchenKit, st: _Statics, wall: str) -> list[float]:
    """Где может начаться ряд: углы, края препятствий у этой стены, сетка."""
    Lw, L = wall_len(room, wall), kit.length_cm
    if L > Lw + EPS:
        return []
    near = _wall_strip(room, wall, 0, Lw, kit.depth_cm)
    edges = {0.0, Lw - L}
    axis = 0 if wall in ("south", "north") else 1
    for _, ob in st.floor + st.tall + st.base:
        hit = ob.intersection(near)
        if hit.is_empty:
            continue
        lo, hi = hit.bounds[axis], hit.bounds[axis + 2]
        edges |= {hi, lo - L}
    k = 0.0
    while k <= Lw - L + EPS:
        edges.add(k)
        k += STEP_CM
    return sorted(round(u, 1) for u in edges if -EPS <= u <= Lw - L + EPS)


def _vent_info(room: Room, kit: KitchenKit, wall: str, u0: float, vent: Vent | None) -> dict:
    P = _vent_point(room, vent)
    if P is None:
        return {"vent_at_cm": None, "vent_distance_cm": None}
    a, b = _wall_point(room, wall, u0), _wall_point(room, wall, u0 + kit.length_cm)
    back = LineString([a, b])
    t = back.project(P)                                   # от точки u0 вдоль стены
    s = kit.length_cm - t if FLIP[wall] else t
    return {"vent_at_cm": round(s, 1), "vent_distance_cm": round(back.distance(P), 1)}


def _no_hob(room: Room, kit: KitchenKit, st: _Statics, wall: str, u0: float) -> list[list[float]]:
    """Отрезки пути, где над рядом окно: варочную туда не ставят (NKBA — не под открывающимся окном)."""
    out = []
    for op in st.windows:
        if op.wall != wall:
            continue
        a, b = max(op.offset_cm, u0), min(op.offset_cm + op.width_cm, u0 + kit.length_cm)
        if b - a > EPS:
            s = sorted(((u0 + kit.length_cm - a) if FLIP[wall] else (a - u0), (u0 + kit.length_cm - b) if FLIP[wall] else (b - u0)))
            out.append([round(s[0], 1), round(s[1], 1)])
    return out


def _score(room: Room, kit: KitchenKit, st: _Statics, wall: str, u0: float, columns_at: str | None, vent: dict,
           shape_changed: bool, fridge: str | None = None) -> float:
    W = kitchen_rules()["score"]
    sc = W["fridge_" + fridge] if fridge else 0.0
    if any(op.wall == wall for op in st.windows):
        sc += W["wall_with_window"]
    if any(op.wall == wall and op.kind != "window" for op in room.openings):
        sc += W["wall_with_door"]
    if vent["vent_distance_cm"] is not None:
        sc += W["vent_per_cm"] * vent["vent_distance_cm"]
    if _room_corner(room, wall, u0) is None and _room_corner(room, wall, u0 + kit.length_cm) is None:
        sc += W["not_at_corner"]
    if columns_at and kit.tall_cm > 0 and st.doors:
        near = min(st.doors, key=lambda d: d.distance(_wall_point(room, wall, u0 + kit.length_cm / 2)))
        cu, ou = _end_u(wall, u0, kit.length_cm, columns_at), _end_u(wall, u0, kit.length_cm, "end" if columns_at == "start" else "start")
        if near.distance(_wall_point(room, wall, cu)) < near.distance(_wall_point(room, wall, ou)) - EPS:
            sc += W["columns_near_door"]
    if shape_changed:
        sc += W["shape_changed"]
    return sc


def _corner_ends(room: Room, kit: KitchenKit, wall: str, u0: float) -> list[str]:
    """Концы набора, где может быть угол Г: у колонн угла нет (`kitchen-layout.ts`), без полуострова — только в углу комнаты."""
    out = []
    for e in ("start", "end"):
        if kit.peninsula or _room_corner(room, wall, _end_u(wall, u0, kit.length_cm, e)) is not None:
            out.append(e)
    return out


def _pose(room: Room, kit: KitchenKit, wall: str, u0: float) -> dict:
    mid = _wall_point(room, wall, u0 + kit.length_cm / 2)
    n, r = NORMAL[wall], RIGHT[wall]
    return {"pose": {"x": round(mid.x + n[0] * kit.depth_cm / 2, 1), "y": round(mid.y + n[1] * kit.depth_cm / 2, 1), "rot": ROT[wall]},
            "right": list(r), "normal": list(n)}


def _attempts(room: Room, kit: KitchenKit, st: _Statics, vent: Vent | None, cooks: int, shape: str, changed: bool):
    for wall in WALLS:
        for u0 in _positions(room, kit, st, wall):
            col_opts = ["start", "end"] if kit.tall_cm > 0 else [None]
            for columns_at in col_opts:
                corners = [None] if shape == "straight" else [
                    e for e in _corner_ends(room, kit, wall, u0) if not (kit.tall_cm > 0 and e == columns_at)]
                for corner_at in corners:
                    r = _check(room, kit, st, wall, u0, columns_at, corner_at, cooks)
                    yield wall, u0, columns_at, corner_at, r, changed


def seat_kitchen(room: Room, kit: KitchenKit, vent: Vent | None = None, cooks: int = 1) -> dict:
    """Лучшая посадка набора `kit` в комнату или отказ с причинами. Детерминирована: перебор и сортировка с ключами."""
    if room.contour:
        return {"ok": False, "reason": ["KITCHEN_CONTOUR"], "why": ["контур не прямоугольник — посадка кухни пока только в прямоугольной комнате"]}
    st = _Statics(room)
    kits = [(kit, False)]
    if kit.shape == "straight":
        # прямая нигде не встала — ТОТ ЖЕ ПОГОНАЖ углом (`rules` shapes): линия короче на плечо за углом
        leg = kit.leg_cm or rule("shapes", "corner_leg_cm")
        kits.append((replace(kit, shape="corner", length_cm=kit.length_cm - (leg - kit.depth_cm), leg_cm=leg), True))
    tried, fails = 0, {}
    best = None
    for k, changed in kits:
        for wall, u0, columns_at, corner_at, r, ch in _attempts(room, k, st, vent, cooks, k.shape, changed):
            tried += 1
            if r["fail"]:
                for c in r["fail"]:
                    fails[c] = fails.get(c, 0) + 1
                continue
            v = _vent_info(room, k, wall, u0, vent)
            sc = _score(room, k, st, wall, u0, columns_at, v, ch, r["fridge"][0]["where"] if r["fridge"] else None)
            key = (sc, WALLS.index(wall), u0, str(columns_at), str(corner_at))
            if best is None or key < best[0]:
                best = (key, wall, u0, columns_at, corner_at, r, v, k, ch)
        if best:
            break
    if not best and not tried:
        return {"ok": False, "reason": ["KITCHEN_TOO_LONG"], "tried": 0, "why": [WHY["KITCHEN_TOO_LONG"]]}
    if not best:
        top = sorted(fails.items(), key=lambda kv: (-kv[1], kv[0]))
        return {"ok": False, "reason": [c for c, _ in top], "tried": tried, "why": [_why(c, n, tried) for c, n in top]}
    (sc, *_), wall, u0, columns_at, corner_at, r, v, k, ch = best
    out = {
        "ok": True, "reason": [], "wall": wall, "u0_cm": u0, "shape": k.shape, "shape_changed": ch,
        "length_cm": k.length_cm, "columns_at": columns_at, "corner_at": corner_at,
        "leg_cm": (k.leg_cm or rule("shapes", "corner_leg_cm")) if corner_at else None,
        "room_depth_cm": room_depth(room, wall), "cooks": cooks,
        **v, "vent_assumed": bool(vent and vent.assumed),
        "fridge_at_cm": [f["s"] for f in r["fridge"] if f["where"] in ("end", "leg")],
        "fridge": [{k2: v2 for k2, v2 in f.items() if k2 != "poly"} for f in r["fridge"]],
        "blind_cm": [f["blind"] for f in r["fridge"] if f["blind"]], "no_hob_cm": _no_hob(room, k, st, wall, u0),
        "checks": r["checks"], "score": sc, "tried": tried, **_pose(room, k, wall, u0),
        "kit": asdict(kit),
    }
    out["dining"] = dining_fit(room, k, st, r, wall, cooks)
    out["views"] = kitchen_views(room, k, wall, u0, st.doors, out["dining"]["center_cm"])
    return out


def kitchen_views(room: Room, kit: KitchenKit, wall: str, u0: float, doors: list[Point] | None = None,
                  table: list[float] | None = None) -> dict:
    """Два вида кухни (`rules/kitchen.json` views): `kit` — на гарнитур от стены напротив; `counter` — встречный: от конца
    ряда, дальнего от обеденного стола (нет стола — от двери), на стол или по диагонали в дальний угол. Точки плана, см."""
    V = kitchen_rules()["views"]
    n = NORMAL[wall]
    Lw, depth = wall_len(room, wall), room_depth(room, wall)

    def at(u: float, out_cm: float, h: float) -> dict:
        p = _wall_point(room, wall, u)
        return {"x": round(p.x + n[0] * out_cm, 1), "y": round(p.y + n[1] * out_cm, 1), "h": h}

    k, c = V["kit"], V["counter"]
    mid = u0 + kit.length_cm / 2
    ends = [u0 + c["eye_from_end_cm"], u0 + kit.length_cm - c["eye_from_end_cm"]]
    away = [Point(*table)] if table else doors
    if away:
        ends.sort(key=lambda u: (-min(d.distance(_wall_point(room, wall, u)) for d in away), u))
    eu = ends[0]
    tu = Lw - c["target_inset_cm"] if eu < Lw / 2 else c["target_inset_cm"]
    target = at(tu, depth - c["target_inset_cm"], c["target_h_cm"])
    if table:
        target = {"x": round(table[0], 1), "y": round(table[1], 1), "h": c["target_h_cm"]}
    return {
        "kit": {"eye": at(mid, depth - k["eye_from_wall_cm"], k["eye_h_cm"]), "target": at(mid, kit.depth_cm / 2, k["target_h_cm"])},
        "counter": {"eye": at(eu, kit.depth_cm + c["eye_from_run_cm"], c["eye_h_cm"]),
                    "target": target},
    }


ROLE_RUN, ROLE_BLIND, ROLE_TALL, ROLE_LEG, ROLE_FRIDGE, ROLE_TABLE = (
    "кухня-ряд", "кухня-глухой-конец", "кухня-колонна", "кухня-плечо", "холодильник", "стол обеденный")
H_CM = {ROLE_RUN: 90, ROLE_BLIND: 90, ROLE_LEG: 90, ROLE_TALL: 220, ROLE_FRIDGE: 200, ROLE_TABLE: 75}


def _placement(role: str, poly: Polygon, wall: str):
    """Прямоугольник следа у стены `wall` → предмет солвера: ширина вдоль стены, глубина от неё, поворот лицом в комнату."""
    from .models import Item, Placement
    x0, y0, x1, y1 = poly.bounds
    along_x = wall in ("south", "north")
    w, d = (x1 - x0, y1 - y0) if along_x else (y1 - y0, x1 - x0)
    return Placement(role=role, x=round((x0 + x1) / 2, 2), y=round((y0 + y1) / 2, 2), rot=ROT[wall],
                     item=Item(role=role, w_cm=round(w, 2), d_cm=round(d, 2), h_cm=H_CM[role]))


def kitchen_placements(room: Room, r: dict) -> list:
    """Годная посадка `seat_kitchen` → предметы солвера для проверок типа комнаты (`kitchen_checks.validate_kitchen`):
    ряд (без колонн и глухого конца), колонны, глухой конец перед холодильником за углом, плечо Г, первый холодильник,
    обеденный стол. Верхние шкафы — на стене, не на полу: их держит посадка (`KITCHEN_WINDOW_TALL`)."""
    if not r.get("ok"):
        return []
    wall, u0, L = r["wall"], r["u0_cm"], r["length_cm"]
    D = r["kit"]["depth_cm"]
    tall = r["kit"]["tall_cm"] if r["columns_at"] else 0.0
    f = r["fridge"][0] if r.get("fridge") else None
    blind = f["blind"] if f and f["blind"] else None
    s0, s1 = 0.0, L
    out = []
    if tall:
        a, b = (0.0, tall) if r["columns_at"] == "start" else (L - tall, L)
        out.append(_placement(ROLE_TALL, _strip_s(room, wall, u0, L, a, b, D), wall))
        s0, s1 = (tall, L) if r["columns_at"] == "start" else (0.0, L - tall)
    if blind:
        out.append(_placement(ROLE_BLIND, _strip_s(room, wall, u0, L, blind[0], blind[1], D), wall))
        s0, s1 = (max(s0, blind[1]), s1) if blind[0] <= 0 else (s0, min(s1, blind[0]))
    if r.get("corner_at"):
        # угловой квадрат — часть плеча: перед ним не рабочий проход ряда, а само плечо
        kit = replace(KitchenKit(**r["kit"]), length_cm=L, leg_cm=r["leg_cm"])
        base, _, side = _leg_polys(room, kit, wall, u0, r["corner_at"])
        if side:
            out.append(_placement(ROLE_LEG, base, side))
            s0, s1 = (max(s0, D), s1) if r["corner_at"] == "start" else (s0, min(s1, L - D))
    out.insert(0, _placement(ROLE_RUN, _strip_s(room, wall, u0, L, s0, s1, D), wall))
    if f:
        out.append(_placement(ROLE_FRIDGE, _wall_strip(room, f["wall"], f["offset_cm"], rule("fridge", "w_cm"), rule("fridge", "d_cm")),
                              f["wall"]))
    dn = r.get("dining") or {}
    if dn.get("max_seats"):
        (tl, td), (rw, _), (cx, cy) = dn["table_cm"], dn["region_cm"], dn["center_cm"]
        w, d = (tl, td) if rw == tl else (td, tl)
        from .models import Item, Placement
        out.append(Placement(role=ROLE_TABLE, x=cx, y=cy, rot=0, item=Item(role=ROLE_TABLE, w_cm=w, d_cm=d, h_cm=H_CM[ROLE_TABLE])))
    return out


WHY = {
    "KITCHEN_DOOR_SWING": "ряд попадает в дугу двери",
    "KITCHEN_DOOR_PASSAGE": "ряд в проходе у двери",
    "KITCHEN_DOOR_JAMB": "ряд на проёме двери",
    "KITCHEN_RADIATOR": "ряд на радиаторе",
    "KITCHEN_WINDOW_TALL": "колонна, холодильник или верхние шкафы у окна",
    "KITCHEN_WINDOW_SILL": "нижний ряд под окном с низким подоконником",
    "KITCHEN_AISLE": "рабочий проход перед линией меньше нормы",
    "KITCHEN_LEG_WALKWAY": "проход у торца плеча Г меньше нормы",
    "KITCHEN_LEG_AISLE": "проход перед плечом Г меньше нормы",
    "KITCHEN_LEG_NO_WALL": "угол Г не у стены",
    "KITCHEN_TOO_LONG": "ряд длиннее любой стены — и прямой, и углом",
    "KITCHEN_FRIDGE_NO_PLACE": "холодильнику нет места — ни у конца ряда, ни за углом, ни у другой стены",
}


def _why(code: str, n: int, tried: int) -> str:
    return f"{WHY.get(code, code)} — в {n} из {tried} положений"


def dining_fit(room: Room, kit: KitchenKit, st: _Statics, r: dict, wall: str, cooks: int) -> dict:
    """Самый большой обеденный стол (2/4/6 мест), который встаёт вне кухни, её рабочего прохода и прохода у двери.
    Место — стол и отодвинутые стулья с двух длинных сторон (`dining` в `rules/kitchen.json`)."""
    work = rule("aisle", "work_two_cooks_cm" if cooks == 2 else "work_one_cook_cm")
    pull = num("dining_chair_pullout", 55)
    edge = rule("dining", "edge_per_seat_cm")
    depths = kitchen_rules()["dining"]["table_depth_cm"]["v"]
    n = NORMAL[wall]
    busy = [r["run"].buffer(0)]
    # рабочий проход — полоса перед рядом на глубину нормы (и перед плечом Г)
    rx0, ry0, rx1, ry1 = r["run"].bounds
    aisle = box(min(rx0, rx0 + n[0] * work), min(ry0, ry0 + n[1] * work), max(rx1, rx1 + n[0] * work), max(ry1, ry1 + n[1] * work))
    busy.append(aisle)
    if r.get("leg") is not None:
        busy.append(r["leg"].buffer(work, join_style=2))
    busy += [ob for _, ob in st.floor]
    if r.get("tall") is not None:
        busy.append(r["tall"])
    busy += [f["poly"] for f in r.get("fridge") or []]   # холодильник — у любого из мест (какое — выберет набор)
    free = box(0, 0, room.width_cm, room.depth_cm).difference(unary_union(busy))
    for seats in sorted(kitchen_rules()["dining"]["seats"], reverse=True):
        tl = math.ceil(seats / 2) * edge
        td = float(depths[str(seats)])
        for w, d in ((tl, td + 2 * pull), (td + 2 * pull, tl)):
            spot = _fit_rect(free, room, w, d)
            if spot:
                return {"max_seats": seats, "table_cm": [tl, td], "region_cm": [w, d], "center_cm": spot}
    return {"max_seats": 0, "table_cm": None, "region_cm": None, "center_cm": None}


def _fit_rect(free, room: Room, w: float, d: float) -> list[float] | None:
    y = d / 2
    while y <= room.depth_cm - d / 2 + EPS:
        x = w / 2
        while x <= room.width_cm - w / 2 + EPS:
            if free.contains(box(x - w / 2, y - d / 2, x + w / 2, y + d / 2).buffer(-EPS)):
                return [round(x, 1), round(y, 1)]
            x += STEP_CM
        y += STEP_CM
    return None

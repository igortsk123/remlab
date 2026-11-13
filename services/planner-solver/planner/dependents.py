"""РЕШАТЕЛЬ ЗАВИСИМЫХ МЕСТ (T-20261112-67, план living-full-01 П1.6 «ничего в цене без 3D»; Codex 12.11
`_intake/codex/2026-11-12-living-passport-carriers-answer.md` §4–§7, этап 1 «общий placement IR»).

Тень: живая сборка (`flat215_demo.py`, `lib/**`, `scene.py`/`template.py`) этот модуль НЕ зовёт.

Вход: размещённые носители (`Placement` с `slot_instance_id` «группа.место#n» и габаритами товара), компилированный уровень
паспорта (`room_templates.compile_level`), комната (стены, окна, потолок). Выход — `Result`: зависимые места с родителем,
точкой крепления, позой в осях носителя и мировыми координатами — ЛИБО отказ всей композиции с причиной
(`on_failure: reject_composition`: частичного набора нет, «тихо без вазы» не бывает). Исключение — места, что паспорт
объявил условными (`on_failure: leave_empty`, картины «при глухой стене», T-20261112-71): не встало — пусто с причиной в
`Result.empty`, не молча.

Шаг детерминированный, после пола: порядок — поверхности носителей → края → проёмы (шторы) → стена (экран, картины, кашпо)
→ потолок. Числа — только из `rules/occupancy.json` по ссылке паспорта (`rule_ref`) или по таблице ссылок `_SURFACE_REF`
на нормы `heights_cm.*`; диапазон берётся серединой. Свои числа в коде — нет.

elev_cm зависимого места — опорная точка правила: верх поверхности носителя (подушка, ваза, лампа, плед), низ картины,
центр экрана (без товара; с товаром — низ), низ люстры, высота штанги штор, низ кашпо.
`limits` — конверт места для будущего подбора товара (ширина клетки, предельный свес люстры, ширина штанги) — товар
выбирает следующий шаг, не этот.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import room_templates as RT
from .back_gap import back_wall_of
from .geometry import base_role, footprint
from .models import Anchor, Item, LocalPose, Opening, Placement, Room

# Высоты поверхностей носителя, когда у товара их нет: ссылка на норму (не число). Роль → поверхность → `heights_cm.*`.
# «top» без нормы (комод, приставной) — берётся только `item.h_cm`; нет и его — честный отказ CARRIER_SURFACE_UNKNOWN.
_SURFACE_REF = {
    "диван": {"seat": "heights_cm.sofa_seat", "arm": "heights_cm.sofa_armrest", "back": "heights_cm.sofa_back",
              "seat_depth": "heights_cm.sofa_seat_depth"},
    "столик": {"top": "heights_cm.coffee_table"},
    "тв-тумба": {"top": "heights_cm.tv_stand_low_h"},
    "стол обеденный": {"top": "heights_cm.dining_table"},
    # верх матраса у изножья: у кровати `h_cm` — высота изголовья, поэтому «top» не годится (T-20261113-22)
    "кровать": {"foot": "heights_cm.bed_top"},
}
# Порядок шагов (детерминизм и зависимости по стене): шторы раньше картин — штанга занимает стену у окна
_ORDER = ("item_surface", "item_edge", "opening", "wall_above", "ceiling_over")
_OVER_KEY = "center_from_floor_over55inch"      # порог диагонали — из имени ключа правила tv_screen, не число в коде
_CM_PER_INCH = 2.54                              # единицы, не норма
_INTO_ROOM_ROT = {"south": 0, "north": 180, "west": 90, "east": 270}
_WALLS = ("south", "east", "north", "west")


class Reject(Exception):
    """Отказ всей композиции: code — машинная причина, place — место паспорта, message — по-человечески."""

    def __init__(self, code: str, place: str, message: str):
        super().__init__(f"{code} {place}: {message}")
        self.code, self.place, self.message = code, place, message


@dataclass
class Result:
    placements: list[Placement] = field(default_factory=list)
    reject: dict | None = None            # {code, place, message} — композиция не годится целиком
    limits: dict = field(default_factory=dict)   # slot_instance_id → конверт места (для подбора товара)
    skipped: list[str] = field(default_factory=list)  # места, чьё `when` не выполнено (не нужны — не отказ)
    empty: list[dict] = field(default_factory=list)   # места `on_failure: leave_empty`, что не встали: {code, place, message}

    @property
    def ok(self) -> bool:
        return self.reject is None


# ───────────────────────── числа из правил ─────────────────────────

def _mid(v):
    return (v[0] + v[1]) / 2 if isinstance(v, list) else v


def _rule(ref: str | None, place: str):
    v = RT.rule_value(ref) if ref else RT._MISSING
    if v is RT._MISSING:
        raise Reject("RULE_MISSING", place, f"нет правила {ref} в occupancy.json")
    return v


def _norm(ref: str):
    v = RT.norm_value(ref)
    return None if v is RT._MISSING else v


# ───────────────────────── оси носителя и стены ─────────────────────────

def _axes(rot: float) -> tuple[tuple[float, float], tuple[float, float]]:
    """(право, лицо) носителя в мире: x носителя — вдоль ширины, y — к лицу (rot 0 → лицо +y)."""
    r = math.radians(rot)
    return (math.cos(r), -math.sin(r)), (math.sin(r), math.cos(r))


def _world(car: Placement, dx: float, dy: float) -> tuple[float, float]:
    (rx, ry), (fx, fy) = _axes(car.rot)
    return round(car.x + dx * rx + dy * fx, 2), round(car.y + dx * ry + dy * fy, 2)


def _wall_len(room: Room, wall: str) -> float:
    return room.width_cm if wall in ("south", "north") else room.depth_cm


def _on_wall(room: Room, wall: str, s: float, off: float) -> tuple[float, float]:
    """Точка на стене: s — вдоль стены от её начала (запад→восток / юг→север), off — от стены внутрь комнаты."""
    return {"south": (s, off), "north": (s, room.depth_cm - off),
            "west": (off, s), "east": (room.width_cm - off, s)}[wall]


def _span_on(room: Room, p: Placement, wall: str) -> tuple[float, float, float]:
    """Проекция следа на стену (от, до) и зазор от стены до следа."""
    x0, y0, x1, y1 = footprint(p).bounds
    gap = {"south": y0, "north": room.depth_cm - y1, "west": x0, "east": room.width_cm - x1}[wall]
    return ((x0, x1) if wall in ("south", "north") else (y0, y1)) + (gap,)


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _opening_z(op: Opening) -> tuple[float, float]:
    """Высоты проёма от пола; высоты нет — до потолка (строго: неизвестное мешает)."""
    lo = op.sill_cm if op.kind == "window" else 0.0
    return lo, (lo + op.height_cm) if op.height_cm else math.inf


def _surface_h(car: Placement, surface: str, place: str) -> float:
    """Высота поверхности носителя: верх товара (top/back) или норма роли; нет ни того, ни другого — отказ."""
    it = car.item
    if surface in ("top", "back") and it is not None and it.h_cm:
        return float(it.h_cm)
    cap = (it.caps or {}).get(f"{surface}_h_cm") if it is not None else None
    if cap:
        return float(cap)
    ref = _SURFACE_REF.get(base_role(car.role), {}).get(surface)
    v = _norm(ref) if ref else None
    if v is None:
        raise Reject("CARRIER_SURFACE_UNKNOWN", place, f"у носителя {car.slot_instance_id or car.role} нет высоты «{surface}»")
    return float(_mid(v))


# ───────────────────────── занятость стен ─────────────────────────

@dataclass
class _Wall:
    """Что уже занято на стене: интервал вдоль стены × интервал высот (Codex §4: отрезок + высоты, не «стена целиком»)."""
    busy: dict = field(default_factory=lambda: {w: [] for w in _WALLS})

    def add(self, wall, s, z, who):
        self.busy[wall].append((s, z, who))

    def clash(self, wall, s, z):
        for s2, z2, who in self.busy[wall]:
            if _overlap(s, s2) and _overlap(z, z2):
                return who
        return None


def _wall_state(room: Room, floor: list[Placement]) -> _Wall:
    """Стены до зависимых: проёмы (по высотам) + высокие корпуса, стоящие спинкой к стене (их верх — граница)."""
    st = _Wall()
    for i, op in enumerate(room.openings):
        st.add(op.wall, (op.offset_cm, op.offset_cm + op.width_cm), _opening_z(op), f"{op.kind}#{i}")
    gap_max = RT.rule_value("distances_cm.mounting.wall_carrier.back_gap_max")
    for p in floor:
        if p.item is None or not p.item.h_cm:
            continue
        wall = back_wall_of(room, p)
        lo, hi, gap = _span_on(room, p, wall)
        if gap_max is not RT._MISSING and gap <= gap_max:
            st.add(wall, (lo, hi), (0.0, float(p.item.h_cm)), p.slot_instance_id or p.role)
    return st


# ───────────────────────── места по видам крепления ─────────────────────────

def _inst(pid: str, i: int) -> str:
    return f"{pid}#{i}"


def _dep(p: dict, i: int, parent: str, xy, rot, elev, anchor: Anchor, local: LocalPose, mount: str,
         item: Item | None) -> Placement:
    return Placement(role=p["role"], x=xy[0], y=xy[1], rot=rot % 360, item=item, elev_cm=round(max(0.0, elev), 2),
                     slot_instance_id=_inst(p["id"], i), parent_slot_instance_id=parent, anchor=anchor, local=local,
                     mount=mount, priced=bool(p.get("sellable", True)), marker=p.get("marker"))


def _section(it: Item) -> float:
    """Глубина основной секции дивана: у Г-дивана — `corner_section_cm` (плечо глубже, d — вся буква Г), у прямого — d.
    Спинка — на тыльной стороне следа (-d/2 в осях носителя), сиденье и подлокотники — в пределах секции."""
    return min(it.corner_section_cm, it.d_cm) if it.corner else it.d_cm


def _cap(n: int, p: dict, counts: dict) -> int:
    """Мест не больше, чем товаров набора на это место (`counts`; нет сведений или 0 — по норме: место ждёт подбора)."""
    k = counts.get(p["id"])
    return min(n, k) if k else n


def _surface(group: list[dict], car: Placement, items: dict, out: Result, counts: dict | None = None) -> None:
    """item_surface: подушки на сиденье (число и клетки по ширине; товаров набора меньше — мест столько, сколько товаров),
    ваза/лампа на столешнице (клетки вдоль ширины носителя, отступ от края, доля площади). Несколько мест на одной поверхности
    делят её поровну, порядок — по id места."""
    it = car.item
    surface = group[0]["anchor"].get("surface")
    if it is None:
        raise Reject("CARRIER_NO_SIZE", group[0]["id"], f"у носителя {car.slot_instance_id} нет габаритов товара")
    elev = _surface_h(car, surface, group[0]["id"])
    if surface == "seat":
        for p in group:
            rule = _rule((p.get("cardinality") or {}).get("rule_ref"), p["id"])
            n = _cap(RT.count_by_width(rule["by_outer_width_cm"], it.w_cm), p, counts or {})
            inset, gap = rule["arm_inset_cm"][0], _mid(rule["gap_between_cm"])
            span = it.w_cm - 2 * inset
            cell = (span - gap * (n - 1)) / n
            sku = items.get(p["id"])
            if cell <= 0 or (sku is not None and sku.w_cm > cell):
                raise Reject("FIT_FAIL", p["id"], f"{n} шт. не влезают на сиденье {it.w_cm:g} см (клетка {cell:.1f})")
            depth = _norm(_SURFACE_REF["диван"]["seat_depth"])
            sec = _section(it)
            dy = -it.d_cm / 2 + (sec - _mid(depth) if depth is not None and sec > _mid(depth) else sec / 2)
            for i in range(n):
                dx = -span / 2 + cell / 2 + i * (cell + gap)
                out.placements.append(_dep(p, i, car.slot_instance_id, _world(car, dx, dy), car.rot, elev,
                                           Anchor(kind="item_surface", surface="seat"),
                                           LocalPose(dx=round(dx, 2), dy=round(dy, 2), dz=elev), "surface", sku))
                out.limits[_inst(p["id"], i)] = {"w_max": round(cell, 1)}
        return
    # столешница: n мест → n клеток вдоль ширины; норма — СВОЯ у каждого места (лампа — `table_lamp_on_surface`, ваза —
    # `surface_decor`), зазор между клетками — наибольший из норм группы
    rules = [_rule((p.get("fit") or {}).get("rule_ref"), p["id"]) for p in group]
    n, gap = len(group), max(_mid(r["gap_between_cm"]) for r in rules)
    cell = (it.w_cm - gap * (n - 1)) / n
    used, share = 0.0, None
    for i, (p, rule) in enumerate(zip(group, rules)):
        sku = items.get(p["id"])
        dx = -it.w_cm / 2 + cell / 2 + i * (cell + gap)
        if "edge_clear_cm" in rule:          # лампа: опора целиком на столешнице, абажур в своей клетке и не в проход
            why = lamp_on_top(cell, it.d_cm, sku, rule)
            if why:
                raise Reject("FIT_FAIL", p["id"], f"не влезает на {car.slot_instance_id}: {why}")
            out.limits[_inst(p["id"], p.get("_inst", 0))] = {"w_max": round(cell, 1),
                                                             "d_max": round(it.d_cm + 2 * rule["shade_overhang_front_cm"], 1)}
        else:
            base = max(sku.w_cm, sku.d_cm) if sku is not None else 0.0
            m = max(rule["edge_inset_min_cm"], base / 2 + rule["edge_inset_over_half_base_cm"])
            if cell / 2 < m or it.d_cm / 2 < m or (sku is not None and base > cell):
                raise Reject("FIT_FAIL", p["id"], f"не влезает на {car.slot_instance_id}: клетка {cell:.1f}×{it.d_cm:g}, отступ {m:g}")
            used += sku.w_cm * sku.d_cm if sku is not None else 0.0
            share = rule["max_share_of_top"] if share is None else min(share, rule["max_share_of_top"])
            out.limits[_inst(p["id"], p.get("_inst", 0))] = {"w_max": round(cell - 2 * (m - base / 2), 1),
                                                             "d_max": round(it.d_cm - 2 * (m - base / 2), 1)}
        out.placements.append(_dep(p, p.get("_inst", 0), car.slot_instance_id, _world(car, dx, 0.0), car.rot, elev,
                                   Anchor(kind="item_surface", surface=surface),
                                   LocalPose(dx=round(dx, 2), dz=elev), "surface", sku))
    if share is not None and used > share * it.w_cm * it.d_cm:
        raise Reject("FIT_FAIL", group[0]["id"], f"декор занимает больше доли {share} столешницы {car.slot_instance_id}")


def lamp_base(sku: Item) -> tuple[float, float]:
    """Опора лампы (Ш, Г): основание по модели (`Item.base_*`), нет — весь габарит лампы (осторожно)."""
    return float(sku.base_w_cm or sku.w_cm), float(sku.base_d_cm or sku.d_cm)


def lamp_on_top(top_w: float, top_d: float, sku: Item | None, rule: dict) -> str | None:
    """Норма `table_lamp_on_surface` для лампы в центре клетки `top_w × top_d` (Ш вдоль ширины носителя, Г — к лицу): None — встаёт,
    иначе причина. Опора целиком на столешнице с отступом `edge_clear_cm`; абажур (габарит карточки) не шире клетки и не свисает к
    лицу больше `shade_overhang_front_cm`. Доля площади и пропорции — мягкие (выбор лампы, `dependent_decor.lamp_score`), не отказ.
    Та же формула в сцене — `lib/configurator/carrier-decor.ts:onCarrier`; общие векторы — `tests/lamp_fit_vectors.json`."""
    if sku is None:
        return None if top_w > 2 * rule["edge_clear_cm"] and top_d > 2 * rule["edge_clear_cm"] else f"клетка {top_w:.1f}×{top_d:g} мала"
    bw, bd = lamp_base(sku)
    c = rule["edge_clear_cm"]
    if bw + 2 * c > top_w or bd + 2 * c > top_d:
        return f"основание {bw:g}×{bd:g} + отступ {c:g} шире клетки {top_w:.1f}×{top_d:g}"
    if sku.w_cm > top_w:
        return f"абажур {sku.w_cm:g} шире клетки {top_w:.1f}"
    if sku.d_cm / 2 > top_d / 2 + rule["shade_overhang_front_cm"]:
        return f"абажур {sku.d_cm:g} свисает к лицу комода глубиной {top_d:g}"
    return None


def _clearance_side(room: Room, car: Placement, side: int, others: list[Placement]) -> float:
    """Свободно ли сбоку от подлокотника (side −1 — левый торец, +1 — правый): расстояние до стены или чужого следа."""
    from shapely.geometry import Point
    x, y = _world(car, side * car.item.w_cm / 2, 0.0)
    (rx, ry), _ = _axes(car.rot)
    dx, dy = side * rx, side * ry          # наружу от торца — вдоль ширины носителя
    if abs(dx) > abs(dy):
        walls = room.width_cm - x if dx > 0 else x
    else:
        walls = room.depth_cm - y if dy > 0 else y
    pt = Point(x, y)
    near = [footprint(o).distance(pt) for o in others if o is not car and o.item is not None]
    return min([walls] + near)


def _edge(p: dict, car: Placement, room: Room, floor: list[Placement], items: dict, out: Result) -> None:
    """item_edge (плед, драпировка): подлокотник со свободным боком (у Г-дивана — торец без плеча), иначе спинка.
    Предмет не выкидывается: подлокотник или спинка — выбор места (паспорт, `throw_drape._source`)."""
    it = car.item
    if it is None:
        raise Reject("CARRIER_NO_SIZE", p["id"], f"у носителя {car.slot_instance_id} нет габаритов товара")
    rule = _rule((p.get("placement") or {}).get("rule_ref"), p["id"])
    if (p.get("anchor") or {}).get("surface") == "foot":
        _foot(p, car, rule, items, out)
        return
    sides = [1 if it.corner_left else -1] if it.corner else [1, -1]
    free = [s for s in sides if _clearance_side(room, car, s, floor) > 0]
    sku = items.get(p["id"])
    if free:
        s = max(free, key=lambda k: (_clearance_side(room, car, k, floor), k))
        dx, h = s * it.w_cm / 2, _surface_h(car, "arm", p["id"])
        anchor = Anchor(kind="item_edge", surface="arm", edge="arm_right" if s > 0 else "arm_left")
        out.limits[_inst(p["id"], 0)] = {"overhang": rule["arm_overhang_cm"]}
    else:
        share = _mid(rule["back_share_of_section"])
        s = sides[0]
        dx, h = s * (it.w_cm / 2 - share * it.w_cm / 2), _surface_h(car, "back", p["id"])
        anchor = Anchor(kind="item_edge", surface="back", edge="back")
        out.limits[_inst(p["id"], 0)] = {"w": round(share * it.w_cm, 1)}
    dy = -it.d_cm / 2 if anchor.surface == "back" else -it.d_cm / 2 + _section(it) / 2   # подлокотник — середина основной секции
    out.placements.append(_dep(p, 0, car.slot_instance_id, _world(car, dx, dy), car.rot, h, anchor,
                               LocalPose(dx=round(dx, 2), dy=round(dy, 2), dz=h), "surface", sku))


def _foot(p: dict, car: Placement, rule: dict, items: dict, out: Result) -> None:
    """item_edge «foot» (покрывало, плед на кровати, T-20261113-22): сложенной дорожкой поперёк изножья — по ширине кровати без
    выхода за её след (`side_inset_cm`), глубиной `folded_depth_cm`, передний край — у изножья (лицо кровати, +y в осях носителя).
    Низ — верх матраса у изножья: замер меша (`caps.foot_h_cm`), иначе норма `heights_cm.bed_top`, но не выше габарита кровати."""
    it = car.item
    depth, inset = _mid(rule["folded_depth_cm"]), _mid(rule["side_inset_cm"])
    w = it.w_cm - 2 * inset
    if w <= 0 or depth >= it.d_cm:
        raise Reject("FIT_FAIL", p["id"], f"кровать {it.w_cm:g}×{it.d_cm:g} мала для покрывала глубиной {depth:g}")
    cap = (it.caps or {}).get("foot_h_cm")
    h = float(cap) if cap else min(_surface_h(car, "foot", p["id"]), float(it.h_cm or math.inf))
    dy = it.d_cm / 2 - depth / 2
    out.placements.append(_dep(p, 0, car.slot_instance_id, _world(car, 0.0, dy), car.rot, h,
                               Anchor(kind="item_edge", surface="foot", edge="foot"),
                               LocalPose(dx=0.0, dy=round(dy, 2), dz=h), "surface", items.get(p["id"])))
    out.limits[_inst(p["id"], 0)] = {"w": round(w, 1), "d": round(depth, 1)}


def _opening(p: dict, room: Room, walls: _Wall, items: dict, out: Result) -> None:
    """opening (шторы): по экземпляру на каждое окно; штанга над проёмом и шире его с каждой стороны — по правилу,
    не выходит за угол стены и не выше потолка. Высоты окна нет — штанга под потолком; нет и потолка — отказ."""
    rule = _rule((p.get("placement") or {}).get("rule_ref"), p["id"])
    count = (p.get("cardinality") or {}).get("count", 1)
    windows = [(i, op) for i, op in enumerate(room.openings) if op.kind == "window"]
    if not windows:
        raise Reject("NO_OPENING", p["id"], "в комнате нет окна для штор")
    k = 0
    for i, op in windows:
        beyond = _mid(rule["beyond_opening_each_side"])
        lo = max(0.0, op.offset_cm - beyond)
        hi = min(_wall_len(room, op.wall), op.offset_cm + op.width_cm + beyond)
        if op.height_cm:
            elev = op.sill_cm + op.height_cm + _mid(rule["rod_above_opening"])
            if room.ceiling_cm:
                elev = min(elev, room.ceiling_cm)
        elif room.ceiling_cm:
            elev = room.ceiling_cm
        else:
            raise Reject("OPENING_HEIGHT_UNKNOWN", p["id"], f"у окна #{i} нет высоты, у комнаты — потолка")
        walls.add(op.wall, (lo, hi), (0.0, elev), _inst(p["id"], k))
        for _ in range(count):
            xy = _on_wall(room, op.wall, (lo + hi) / 2, 0.0)
            out.placements.append(_dep(p, k, f"window#{i}", (round(xy[0], 2), round(xy[1], 2)),
                                       _INTO_ROOM_ROT[op.wall], elev,
                                       Anchor(kind="opening", wall=op.wall, opening=i),
                                       LocalPose(dz=elev), "rod", items.get(p["id"])))
            out.limits[_inst(p["id"], k)] = {"rod_w": round(hi - lo, 1), "drop": round(elev, 1)}
            k += 1


def _carrier_wall(room: Room, car: Placement, place: str) -> tuple[str, float, float]:
    """Стена за спинкой носителя и его проекция на неё; носитель дальше `back_gap_max` — не у стены (отказ)."""
    wall = back_wall_of(room, car)
    lo, hi, gap = _span_on(room, car, wall)
    if gap > _rule("distances_cm.mounting.wall_carrier.back_gap_max", place):
        raise Reject("CARRIER_NOT_AT_WALL", place, f"{car.slot_instance_id} стоит в {gap:.0f} см от стены {wall}")
    return wall, lo, hi


def _check_wall(room, walls, wall, s, z, place, clear, edge) -> None:
    if s[0] < edge or s[1] > _wall_len(room, wall) - edge:
        raise Reject("WALL_EDGE", place, f"место на стене {wall} выходит к углу ближе {edge:g} см")
    who = walls.clash(wall, (s[0] - clear, s[1] + clear), z)
    if who:
        raise Reject("WALL_NOT_SOLID", place, f"стена {wall} над носителем занята: {who}")


def _screen(p: dict, car: Placement, room: Room, walls: _Wall, items: dict, out: Result) -> None:
    rule = _rule((p.get("placement") or {}).get("rule_ref"), p["id"])
    it = car.item
    if it is None:
        raise Reject("CARRIER_NO_SIZE", p["id"], f"у носителя {car.slot_instance_id} нет габаритов товара")
    wall, lo, hi = _carrier_wall(room, car, p["id"])
    w_max = rule["max_share_of_stand"] * it.w_cm
    sku = items.get(p["id"])
    w = sku.w_cm if sku is not None else w_max
    if w > w_max:
        raise Reject("FIT_FAIL", p["id"], f"экран {w:g} шире доли {rule['max_share_of_stand']} тумбы {it.w_cm:g}")
    inch = int(re.search(r"over(\d+)inch", _OVER_KEY).group(1))
    big = sku is not None and sku.h_cm and math.hypot(sku.w_cm, sku.h_cm) / _CM_PER_INCH > inch
    center = _mid(rule[_OVER_KEY if big else "center_from_floor"])
    half = sku.h_cm / 2 if sku is not None and sku.h_cm else 0.0
    top = _surface_h(car, "top", p["id"])
    if center - half < top:
        raise Reject("FIT_FAIL", p["id"], f"низ экрана {center - half:g} ниже верха тумбы {top:g}")
    mid = (lo + hi) / 2
    s, z = (mid - w / 2, mid + w / 2), (center - half, center + half)
    _check_wall(room, walls, wall, s, z, p["id"], 0.0, 0.0)
    walls.add(wall, s, z, _inst(p["id"], 0))
    xy = _on_wall(room, wall, mid, 0.0)
    out.placements.append(_dep(p, 0, car.slot_instance_id, xy, _INTO_ROOM_ROT[wall], center - half,
                               Anchor(kind="wall_above", surface="wall", wall=wall),
                               LocalPose(dz=round(center - half - top, 2)), "wall", sku))
    out.limits[_inst(p["id"], 0)] = {"w_max": round(w_max, 1), "center": center}


def _art_on(p: dict, car: Placement, room: Room, walls: _Wall, items: dict, n_max: int | None = None) -> tuple[list[tuple], dict, str]:
    """Картины над одним носителем: (места, конверт, стена) или Reject. Пара — рядом с зазором, общий ширинный коридор
    `width_share_range`; не влезла пара — одна (как живая сцена `lib/configurator/wall-art.ts`)."""
    rule = _rule((p.get("placement") or {}).get("rule_ref"), p["id"])
    it = car.item
    if it is None:
        raise Reject("CARRIER_NO_SIZE", p["id"], f"у носителя {car.slot_instance_id} нет габаритов товара")
    wall, lo, hi = _carrier_wall(room, car, p["id"])
    W, gap = hi - lo, _mid(rule["gap_between_frames"])
    sku = items.get(p["id"])
    n = rule["max_count"] if p.get("symmetry") == "pair" else 1
    n = min(n, n_max) if n_max else n
    if sku is not None:
        while n > 1 and n * sku.w_cm + gap * (n - 1) > rule["width_share_range"][1] * W:
            n -= 1
        frame = sku.w_cm
        if frame > rule["width_share_range"][1] * W:
            raise Reject("FIT_FAIL", p["id"], f"картина {frame:g} шире коридора над {car.slot_instance_id}")
    else:
        frame = (rule["width_share_of_carrier"] * W - gap * (n - 1)) / n
    total = n * frame + gap * (n - 1)
    bottom = _surface_h(car, "back" if base_role(car.role) == "диван" else "top", p["id"]) + _mid(rule["bottom_above_carrier"])
    top = bottom + (sku.h_cm if sku is not None and sku.h_cm else 0.0)
    if room.ceiling_cm and top > room.ceiling_cm - rule["ceiling_gap"]:
        raise Reject("CEILING_TOO_LOW", p["id"], f"верх картины {top:g} ближе {rule['ceiling_gap']} см к потолку")
    mid = (lo + hi) / 2
    s = (mid - total / 2, mid + total / 2)
    z = (bottom, top if top > bottom else (room.ceiling_cm or math.inf))
    _check_wall(room, walls, wall, s, z, p["id"], rule["opening_clear"],
                _rule("distances_cm.mounting.wall_carrier.wall_edge", p["id"]))
    spots = []
    for i in range(n):
        c = s[0] + frame / 2 + i * (frame + gap)
        spots.append((c, bottom))
    return spots, {"frame_w": round(frame, 1), "h_max": round((room.ceiling_cm or math.inf) - rule["ceiling_gap"] - bottom, 1)
                   if room.ceiling_cm else None, "s": s, "z": z}, wall


def _art(p: dict, cars: list[Placement], room: Room, walls: _Wall, items: dict, out: Result, counts: dict | None = None) -> None:
    """wall_above над носителем: кандидаты по порядку one_of (следующий носитель — раньше отказа, Codex §5). Пара — не больше
    картин, чем товаров набора (`counts`)."""
    last = None
    for car in cars:
        try:
            spots, env, wall = _art_on(p, car, room, walls, items, (counts or {}).get(p["id"]))
        except Reject as e:
            last = e
            continue
        walls.add(wall, env["s"], env["z"], _inst(p["id"], 0))
        for i, (c, bottom) in enumerate(spots):
            xy = _on_wall(room, wall, c, 0.0)
            out.placements.append(_dep(p, i, car.slot_instance_id, xy, _INTO_ROOM_ROT[wall], bottom,
                                       Anchor(kind="wall_above", surface="wall", wall=wall),
                                       LocalPose(dz=round(bottom, 2)), "wall", items.get(p["id"])))
            out.limits[_inst(p["id"], i)] = {"frame_w": env["frame_w"], "h_max": env["h_max"]}
        return
    raise last if last else Reject("CARRIER_MISSING", p["id"], "нет носителя")


def _free_wall(p: dict, room: Room, walls: _Wall, floor: list[Placement], items: dict, out: Result) -> None:
    """wall_above на свободной стене (кашпо `of: free_wall`): самый длинный свободный отрезок на высоте крепления;
    над дверью (проход) низ не ниже `over_passage_bottom_min`. На пол не падает (Codex §5)."""
    rule = _rule((p.get("placement") or {}).get("rule_ref"), p["id"])
    sku = items.get(p["id"])
    bottom = _mid(rule["bottom_from_floor"])
    top = bottom + (sku.h_cm if sku is not None and sku.h_cm else 0.0)
    need = sku.w_cm if sku is not None else 0.0
    best = None
    for wall in _WALLS:
        L = _wall_len(room, wall)
        cuts = sorted(s for s, z, _ in walls.busy[wall] if z[0] <= top and bottom <= z[1])
        x = 0.0
        for a, b in cuts + [(L, L)]:
            if a - x > need and (best is None or a - x > best[2] - best[1]):
                best = (wall, x, a)
            x = max(x, b)
    if best is None:
        raise Reject("NO_FREE_WALL", p["id"], "нет свободного отрезка стены на высоте крепления")
    wall, a, b = best
    mid = (a + b) / 2
    door = any(op.wall == wall and op.kind != "window" and _overlap((op.offset_cm, op.offset_cm + op.width_cm), (a, b))
               for op in room.openings)
    elev = max(bottom, rule["over_passage_bottom_min"]) if door else bottom
    off = rule["off_wall_min"]
    xy = _on_wall(room, wall, mid, off)
    walls.add(wall, (mid - need / 2, mid + need / 2), (elev, top), _inst(p["id"], 0))
    out.placements.append(_dep(p, 0, f"wall:{wall}", (round(xy[0], 2), round(xy[1], 2)), _INTO_ROOM_ROT[wall], elev,
                               Anchor(kind="wall_above", surface="wall", wall=wall),
                               LocalPose(dy=off, dz=elev), "wall", sku))
    out.limits[_inst(p["id"], 0)] = {"w_max": round(b - a, 1)}


def _ceiling(p: dict, cars: list[Placement], room: Room, zone: bool, items: dict, out: Result) -> None:
    """ceiling_over: центр ковра зоны (нет ковра — рамки зоны) или стола; низ — не ниже нормы. Длинная люстра — отказ места
    (замена товара — не здесь); без товара — предельный свес в `limits`."""
    rule = _rule((p.get("placement") or {}).get("rule_ref"), p["id"])
    if not room.ceiling_cm:
        raise Reject("CEILING_UNKNOWN", p["id"], "у комнаты нет высоты потолка")
    if room.ceiling_cm < rule["bottom_min"]:
        raise Reject("CEILING_TOO_LOW", p["id"], f"потолок {room.ceiling_cm:g} ниже нормы низа люстры {rule['bottom_min']}")
    rug = next((c for c in cars if base_role(c.role) == "ковёр"), None) if zone else None
    ref = [rug] if rug is not None else cars
    sized = [c for c in ref if c.item is not None]
    if not sized:
        raise Reject("CARRIER_NO_SIZE", p["id"], "у носителей зоны нет габаритов")
    x0s, y0s, x1s, y1s = zip(*(footprint(c).bounds for c in sized))
    cx, cy = (min(x0s) + max(x1s)) / 2, (min(y0s) + max(y1s)) / 2
    if zone:
        lo, target = rule["over_seating_bottom"][0], _mid(rule["over_seating_bottom"])
        parent = f"zone:{cars[0].slot_instance_id.split('.')[0]}" if cars[0].slot_instance_id else "zone"
    else:
        table = sized[0]
        top = _surface_h(table, "top", p["id"])
        lo, target = top + rule["above_dining_table"][0], top + _mid(rule["above_dining_table"])
        parent = table.slot_instance_id
    sku = items.get(p["id"])
    if sku is not None and sku.h_cm:
        bottom = room.ceiling_cm - sku.h_cm
        if bottom < lo:
            raise Reject("FIT_FAIL", p["id"], f"люстра длинная: низ {bottom:g} ниже нормы {lo:g}")
    else:
        bottom = min(target, room.ceiling_cm)
    out.placements.append(_dep(p, 0, parent, (round(cx, 2), round(cy, 2)), 0, bottom,
                               Anchor(kind="ceiling_over", ceiling=True), LocalPose(dz=round(bottom, 2)), "ceiling", sku))
    out.limits[_inst(p["id"], 0)] = {"drop_max": round(room.ceiling_cm - lo, 1)}


# ───────────────────────── вход ─────────────────────────

def room_facts(room: Room) -> dict:
    """Факты комнаты для `when` мест (окно/эркер — из проёмов; площадь — из комнаты)."""
    return {"area_m2": room.area_m2, "has_window": any(o.kind == "window" for o in room.openings)}


def resolve(places: list[dict], carriers: list[Placement], room: Room, items: dict | None = None,
            facts: dict | None = None, counts: dict | None = None) -> Result:
    """Зависимые места уровня. places — из `compile_level`; carriers — размещённые самостоятельные места
    (slot_instance_id «группа.место#n»); items — выбранные товары мест {id места: Item} (нет — место без товара, конверт
    в `limits`); counts — сколько товаров набора на место {id места: n} (подушки, пара картин — мест не больше товаров).
    Неудача места `reject_composition` — отказ композиции целиком; `leave_empty` — место пусто, причина в `Result.empty`."""
    items = items or {}
    counts = counts or {}
    facts = {**room_facts(room), **(facts or {})}
    out = Result()
    by_place: dict[str, list[Placement]] = {}
    for c in sorted(carriers, key=lambda c: c.slot_instance_id):
        by_place.setdefault(c.slot_instance_id.split("#")[0], []).append(c)
    deps = [p for p in places if p["kind"] == "dependent"]
    kind_of = lambda p: (p.get("anchor") or {}).get("kind")        # noqa: E731
    deps.sort(key=lambda p: (_ORDER.index(kind_of(p)) if kind_of(p) in _ORDER else len(_ORDER),
                             0 if p.get("marker") == "virtual_screen" else 1, p["id"]))
    walls = _wall_state(room, carriers)
    try:
        surf: dict[tuple, list[dict]] = {}
        for p in deps:
            if p.get("on_failure") not in RT.ON_FAILURE:
                raise Reject("ON_FAILURE_UNKNOWN", p["id"], f"on_failure {p.get('on_failure')!r}")
            if not RT.when_ok(p.get("when"), facts):
                out.skipped.append(p["id"])
                continue
            kind = (p.get("anchor") or {}).get("kind")
            if kind != "item_surface" and surf:   # поверхности — раньше остальных (порядок _ORDER), сводим при первом другом
                _flush(surf, by_place, carriers, items, out, counts)
            try:
                _one(p, kind, by_place, surf, carriers, room, walls, items, out, counts)
            except Reject as e:
                if p.get("on_failure") != "leave_empty" or kind == "item_surface":
                    raise
                out.empty.append({"code": e.code, "place": e.place, "message": e.message})
        _flush(surf, by_place, carriers, items, out, counts)
    except Reject as e:
        return Result(reject={"code": e.code, "place": e.place, "message": e.message})
    out.placements.sort(key=lambda q: q.slot_instance_id)
    return out


def _one(p: dict, kind: str | None, by_place: dict, surf: dict, carriers: list[Placement], room: Room, walls: _Wall,
         items: dict, out: Result, counts: dict) -> None:
    """Одно зависимое место: носители-кандидаты → вид крепления. Места на поверхности копятся в `surf` (сводятся `_flush`)."""
    car = p.get("carrier") or {}
    if "slot_ref" in car or "one_of" in car:
        refs = [car["slot_ref"]] if "slot_ref" in car else list(car["one_of"])
        cands = [c for r in refs for c in by_place.get(r, [])[:1]]
        if not cands:
            raise Reject("CARRIER_MISSING", p["id"], f"носителя {' / '.join(refs)} нет среди размещённых")
    elif "zone" in car:
        cands = [c for k, v in sorted(by_place.items()) if k.split(".")[0] == car["zone"] for c in v]
        if not cands:
            raise Reject("CARRIER_MISSING", p["id"], f"зоны {car['zone']} нет среди размещённых")
    else:
        cands = []
    if kind == "item_surface" and p.get("symmetry") == "pair" and "slot_ref" in car:
        # «по предмету на каждый носитель» (лампа на каждой тумбе, T-20261113-22): все экземпляры места-носителя по порядку,
        # но не больше товаров набора на место (`counts`); экземпляр зависимого = номер носителя
        every = by_place.get(car["slot_ref"], [])
        for i, c in enumerate(every[:_cap(len(every), p, counts)]):
            surf.setdefault((c.slot_instance_id, p["anchor"].get("surface")), []).append({**p, "_inst": i})
    elif kind == "item_surface":
        surf.setdefault((cands[0].slot_instance_id, p["anchor"].get("surface")), []).append(p)
    elif kind == "item_edge":
        _edge(p, cands[0], room, carriers, items, out)
    elif kind == "opening":
        _opening(p, room, walls, items, out)
    elif kind == "wall_above" and car.get("support") == "wall":
        _free_wall(p, room, walls, carriers, items, out)
    elif kind == "wall_above" and p.get("marker") == "virtual_screen":
        _screen(p, cands[0], room, walls, items, out)
    elif kind == "wall_above":
        _art(p, cands, room, walls, items, out, counts)
    elif kind == "ceiling_over":
        _ceiling(p, cands, room, "zone" in car, items, out)
    else:
        raise Reject("ANCHOR_UNSUPPORTED", p["id"], f"вид крепления {kind!r} решателем не поддержан")


def _flush(surf: dict, by_place: dict, carriers: list[Placement], items: dict, out: Result, counts: dict | None = None) -> None:
    index = {c.slot_instance_id: c for c in carriers}
    for (cid, _surf), group in sorted(surf.items()):
        _surface(sorted(group, key=lambda p: p["id"]), index[cid], items, out, counts)
    surf.clear()


def resolve_level(doc: dict, tpl: dict, level_id: str, carriers: list[Placement], room: Room, items: dict | None = None,
                  facts: dict | None = None, counts: dict | None = None) -> Result:
    """Уровень паспорта целиком: разворот (`compile_level`) → зависимые. Ошибка разворота — тоже отказ с причиной."""
    places, err = RT.compile_level(doc, tpl, level_id)
    if err:
        return Result(reject={"code": "LEVEL_INVALID", "place": level_id, "message": "; ".join(err)})
    return resolve(places, carriers, room, items, facts, counts)

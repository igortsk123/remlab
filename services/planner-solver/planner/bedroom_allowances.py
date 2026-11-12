"""Допуски `compact` в спальне — покупателю строкой (T-20261112-68, ADR-0394; канон `.memory_bank/domain/room-templates.md`
§ «Проходы»: «Покупателю, когда взят допуск, — строкой у места: факт, цель, почему можно, что даёт альтернатива»).

`allowances(room, placements, optional)` меряет фактическую ширину каждого прохода раскладки (бок кровати, изножье, фронт
шкафа и комода, путь от двери) и отдаёт те, что уже цели: где, факт, цель, допуск, почему можно и что даст альтернатива —
«без комода будет 76 см» (предмет из optional, без которого проход шире всего). Числа — `planner/passage_norms.py`.
"""
from __future__ import annotations

from . import passage_norms as PN
from .bedroom_checks import (_against_wall, _local, _zone_clear, bed_zones, bedroom_role, bedroom_spec, both_sides, is_bed,
                             num, route_violations, same_group, side_clear, side_name)
from .geometry import room_polygon
from .models import Placement, Room

GEN = {"комод": "комода", "шкаф": "шкафа", "тумба прикроватная": "тумбы", "стол рабочий": "стола", "стул рабочий": "стула",
       "туалетный столик": "туалетного столика"}
WHY = {"bed_side_couple": "к кровати подходят с обеих сторон", "bed_side_work": "к кровати подходят сбоку",
       "bed_foot_route": "окно и радиатор доступны", "route_door_window": "путь от двери к окну и кровати непрерывный",
       "wardrobe_hinged_front": "шкаф открывается полностью", "storage_sliding_front": "шкаф открывается полностью",
       "dresser_front": "ящики выдвигаются полностью"}
FRONT = {"шкаф", "комод"}
MEASURE_MAX_CM = 300.0
_ROUTE = ("BR_NO_PASSAGE", "BR_DOOR_UNREACHABLE", "BR_UNREACHABLE", "BR_BED_SIDE_UNREACHABLE", "BR_WINDOW_UNREACHABLE")


def _max_depth(ok, lo: float, hi: float) -> float:
    """Наибольшее целое d в [lo, hi], при котором ok(d) (ok монотонна: уже — тоже годно); ok(lo) ложно — lo − 1."""
    if not ok(lo):
        return lo - 1
    if ok(hi):
        return hi
    a, b = int(lo), int(hi)
    while b - a > 1:
        m = (a + b) // 2
        a, b = (m, b) if ok(m) else (a, m)
    return float(a)


def _bed_sides(room: Room, b: Placement, others: list[Placement]) -> list[str]:
    z = bed_zones(b)
    if both_sides(room, b):
        return ["left", "right"]
    return [s for s in ("left", "right") if not _against_wall(room, z[f"{s}_wall"]) and side_clear(room, z, s, others)]


def _measures(room: Room, ps: list[Placement]) -> list[dict]:
    """Факт по каждому проходу раскладки: [{name, role, side, fact}] (fact — до MEASURE_MAX_CM)."""
    out = []
    for b in [p for p in ps if is_bed(p) and p.item is not None]:
        others = [o for o in ps if o is not b]
        w, d = b.item.w_cm, b.item.d_cm
        head = min(num("bed_head_zone", 50), d)
        sides = _bed_sides(room, b, others)
        facts = {}
        for s in sides:
            sx = -1 if s == "left" else 1

            def ok(dd, sx=sx):
                x0, x1 = (-w / 2 - dd, -w / 2) if sx < 0 else (w / 2, w / 2 + dd)
                return _zone_clear(room, _local(b, x0, -d / 2 + head, x1, d / 2), others)
            facts[s] = _max_depth(ok, 1, MEASURE_MAX_CM)
        if facts:
            if both_sides(room, b):
                out += [{"name": side_name(b), "role": b.role, "side": s, "fact": f} for s, f in facts.items()]
            else:
                s = max(facts, key=facts.get)
                out.append({"name": side_name(b), "role": b.role, "side": s, "fact": facts[s]})
        out.append({"name": "bed_foot_route", "role": b.role, "side": "foot",
                    "fact": _max_depth(lambda dd: _zone_clear(room, _local(b, -w / 2, d / 2, w / 2, d / 2 + dd), others),
                                       1, MEASURE_MAX_CM)})
    rp = room_polygon(room)
    for a in [p for p in ps if bedroom_role(p.role) in FRONT and p.item is not None]:
        others = [o for o in ps if o is not a and not same_group(a.role, o.role)]
        w, d = a.item.w_cm, a.item.d_cm

        def ok(dd, a=a, w=w, d=d, others=others):
            z = _local(a, -w / 2, d / 2, w / 2, d / 2 + dd)
            return z.difference(rp).area <= 100.0 and _zone_clear(room, z, others)
        name = "dresser_front" if bedroom_role(a.role) == "комод" else (
            "storage_sliding_front" if PN.wardrobe_kind(a.item) != "hinged" else "wardrobe_hinged_front")
        out.append({"name": name, "role": a.role, "side": "front", "fact": _max_depth(ok, 1, MEASURE_MAX_CM)})
    return out


def _route_fact(room: Room, ps: list[Placement], lo: float, hi: float) -> float:
    def ok(n):
        return not any(v.code in _ROUTE for v in route_violations(room, ps, n, extra=True))
    return _max_depth(ok, lo, hi)


def _target(m: dict, ps: list[Placement]) -> float:
    """Цель прохода: фронт — по товару (дуга створки, вылет ящика) в режиме target, прочее — target профиля."""
    if m["side"] == "front":
        a = next(p for p in ps if p.role == m["role"])
        with PN.using("target", PN.profile()):
            return bedroom_spec(a.role, a.item).front_cm
    return PN.clearance(m["name"], "target")


def allowances(room: Room, ps: list[Placement], optional: set | None = None) -> list[dict]:
    """Проходы уже цели (взят допуск): [{name, where, role, side, fact, target, compact, hard, why, alt, text}].
    alt — {without, fact}: предмет из optional, без которого этот проход шире всего (группа уходит целиком)."""
    optional = set(optional or ())
    out = []
    meas = _measures(room, ps)
    tr = PN.triple("route_door_window")
    rfact = _route_fact(room, ps, tr["hard"], tr["target"])
    if rfact < tr["target"]:
        meas.append({"name": "route_door_window", "role": "", "side": "route", "fact": rfact})
    for m in meas:
        target = _target(m, ps)
        if m["fact"] >= target - 0.5:
            continue
        tri = PN.triple(m["name"])
        alt = None
        for r in sorted(optional):
            if r == m["role"] or not any(p.role == r for p in ps):
                continue
            rest = [p for p in ps if p.role != r and not same_group(p.role, r)
                    and not (is_bed(next(q for q in ps if q.role == r)) and bedroom_role(p.role) == "тумба прикроватная")]
            if m["role"] and not any(p.role == m["role"] for p in rest):
                continue
            if m["side"] == "route":
                f = _route_fact(room, rest, tr["hard"], MEASURE_MAX_CM)
            else:
                f = next((x["fact"] for x in _measures(room, rest)
                          if x["role"] == m["role"] and x["side"] == m["side"] and x["name"] == m["name"]), m["fact"])
            if f > m["fact"] + 0.5 and (alt is None or f > alt["fact"]):
                alt = {"without": r, "fact": f}
        fact = int(m["fact"])
        where = PN.where(m["name"])
        text = (f"Компактно: {where} {fact} см вместо {target:.0f} — допустимо для обычной квартиры, "
                f"{WHY.get(m['name'], 'проход не уже нормы')}.")
        if alt:
            gen = GEN.get(bedroom_role(alt["without"]), f"«{alt['without']}»")
            text += f" Без {gen} будет {int(min(alt['fact'], MEASURE_MAX_CM))} см."
        out.append({"name": m["name"], "where": where, "role": m["role"], "side": m["side"], "fact": fact,
                    "target": target, "compact": tri["compact"], "hard": tri["hard"],
                    "why": WHY.get(m["name"], ""), "alt": alt, "text": text})
    return out

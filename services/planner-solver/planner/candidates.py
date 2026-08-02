"""Э2: генератор позиций-кандидатов.

Стратегия по роли (а не по конкретному товару — правило владельца «только масштабируемое»):
у стены / в углу / относительно якоря (зона-билдер как anchor-based generation) / в середине
свободного прямоугольника. Ориентации — только осевые. Кандидаты, не влезающие в свободный
полигон, отбрасываются ДО скоринга (ProcTHOR: фильтр размера предшествует сэмплингу).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from shapely.geometry import Polygon
from shapely.prepared import prep

from .clearances import (LOW_ITEM_MAX_H_CM, NEVER_BLOCKING_ROLES, band_scale, distances,
                         rules)
from .geometry import blocked_footprint, footprint, free_space, largest_free_rectangles, room_polygon
from .models import Item, Placement, Room

GRID_CM = 25.0          # шаг скольжения вдоль стены (Holodeck DFS работал на 15 см;
                        # 25 см достаточно: локальное уточнение Э4 добирает точность)
WALL_GAP_CM = 5.0       # технологический зазор от стены (ProcTHOR padding 5 см)

# приоритет размещения: якоря зоны первыми (PT: PRIORITY_ASSET_TYPES для LivingRoom)
# ТВ-зона первой: ТВ-тумба самая ограниченная (только у стены) и задаёт ось зоны —
# ProcTHOR ставит Television первым в PRIORITY_ASSET_TYPES гостиной по той же причине.
# порядок: ось зоны (ТВ, диван) → крупное пристенное хранение → наполнение зоны → мелочь
ROLE_ORDER = ["тв-тумба", "диван", "стенка", "камин", "шкаф", "комод", "витрина", "стеллаж",
              "столик", "кресло", "пуф", "стол обеденный", "стул", "торшер", "кашпо", "ковёр"]

WALLS = ("north", "south", "west", "east")
# роли, которым разрешён «отплыв» от стены (наш narrow_room.float_from_wall + проход за спинкой)
FLOATABLE = frozenset({"диван"})
FLOAT_OFFSETS_CM = (0.0, 80.0, 130.0, 180.0)   # 0 = к стене; далее — только с проходом ≥76 см
# поворот, при котором «лицо» смотрит от стены внутрь комнаты
WALL_FACING_ROT = {"north": 180, "south": 0, "west": 90, "east": 270}


@dataclass(frozen=True)
class Candidate:
    placement: Placement
    kind: str          # wall | corner | anchor | middle
    note: str = ""


def role_rank(role: str) -> int:
    return ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER)


def order_items(items: list[Item]) -> list[Item]:
    """Порядок размещения: сначала якоря зоны, внутри группы — крупные первыми."""
    return sorted(items, key=lambda it: (role_rank(it.role), -(it.w_cm * it.d_cm)))


def _dims_for_rot(item: Item, rot: float) -> tuple[float, float]:
    return (item.d_cm, item.w_cm) if int(rot) % 180 == 90 else (item.w_cm, item.d_cm)


class _Fitter:
    """Подготовленная геометрия свободного места: contains() в разы дешевле сырого полигона."""

    def __init__(self, room: Room, free: Polygon):
        self.free = prep(free.buffer(1))

    def __call__(self, cand: Placement) -> bool:
        return self.free.contains(footprint(cand))


def _fits(room: Room, cand: Placement, free) -> bool:
    return free(cand) if callable(free) else _Fitter(room, free)(cand)


def wall_candidates(room: Room, item: Item, free: Polygon, *, step: float = GRID_CM) -> list[Candidate]:
    """Скольжение вдоль каждой стены спинкой к ней (углы отдаются отдельным kind='corner')."""
    out: list[Candidate] = []
    for wall in WALLS:
        rot = WALL_FACING_ROT[wall]
        w, d = _dims_for_rot(item, rot)
        along = room.width_cm if wall in ("north", "south") else room.depth_cm
        if w + 2 * WALL_GAP_CM > along:
            continue
        lo, hi = WALL_GAP_CM + w / 2, along - WALL_GAP_CM - w / 2
        n = max(1, int((hi - lo) // step))
        offs = [lo + i * (hi - lo) / n for i in range(n + 1)]
        floats = FLOAT_OFFSETS_CM if item.role in FLOATABLE else (0.0,)
        for off in offs:
            for fl in floats:
                x, y = _wall_xy(room, wall, off, d, float_cm=fl)
                p = Placement(role=item.role, x=x, y=y, rot=rot, item=item)
                if not _fits(room, p, free):
                    continue
                if fl == 0:
                    is_corner = off <= lo + step / 2 or off >= hi - step / 2
                    out.append(Candidate(p, "corner" if is_corner else "wall", f"{wall}"))
                else:
                    out.append(Candidate(p, "wall", f"{wall}, отплыв {fl:.0f} см"))
    return out


def _wall_xy(room: Room, wall: str, off: float, depth: float, *, float_cm: float = 0.0) -> tuple[float, float]:
    if wall == "south":
        return off, WALL_GAP_CM + depth / 2 + float_cm
    if wall == "north":
        return off, room.depth_cm - WALL_GAP_CM - depth / 2 - float_cm
    if wall == "west":
        return WALL_GAP_CM + depth / 2 + float_cm, off
    return room.width_cm - WALL_GAP_CM - depth / 2 - float_cm, off


def middle_candidates(room: Room, item: Item, free: Polygon, *, limit: int = 6,
                      fitter=None) -> list[Candidate]:
    """Центры крупнейших свободных прямоугольников (PT: макс. прямоугольники открытого полигона)."""
    out: list[Candidate] = []
    fit = fitter or _Fitter(room, free)
    for rect in largest_free_rectangles(free, min_side_cm=min(item.w_cm, item.d_cm), limit=limit):
        cx, cy = rect.centroid.x, rect.centroid.y
        for rot in (0, 90):
            p = Placement(role=item.role, x=cx, y=cy, rot=rot, item=item)
            if _fits(room, p, fit):
                out.append(Candidate(p, "middle", f"{rect.area / 10_000:.1f} м²"))
    return out


def anchor_candidates(room: Room, item: Item, placed: list[Placement], free: Polygon) -> list[Candidate]:
    """Позиции относительно уже поставленных якорей — перенос зона-билдера (ADR-0050/0051)."""
    by = {p.role: p for p in placed}
    role = item.role
    out: list[Candidate] = []

    def seat_center(anchor: Placement) -> tuple[float, float]:
        """Центр СВОБОДНОГО сегмента посадки: у Г-дивана короткое плечо занимает часть ширины,
        и столик, центрированный по всей ширине, влезает прямо в плечо (был провал сетов 38/97)."""
        if anchor.item is None or not anchor.item.corner:
            return anchor.x, anchor.y
        fx, fy = _face_dir(anchor.rot)
        # плечо занимает локальный +x, что в мировых координатах = −lateral (см. relative_position),
        # поэтому центр свободного сегмента смещаем на +lateral
        lat = anchor.item.corner_section_cm / 2
        return anchor.x + lat * (-fy), anchor.y + lat * fx

    def add(x: float, y: float, rot: float, note: str):
        p = Placement(role=role, x=x, y=y, rot=rot, item=item)
        if _fits(room, p, free):
            out.append(Candidate(p, "anchor", note))

    sofa = by.get("диван")
    tv = by.get("тв-тумба")
    if role == "диван" and tv is not None:
        # диван напротив ТВ: ось зоны задана тумбой, дистанция — по шкале площади
        lo, hi = band_scale("sofa_tv_cm", room.band, distances().get("sofa_tv_cm", [180, 300]))
        fx, fy = _face_dir(tv.rot)
        tfp = footprint(tv)
        rot = (tv.rot + 180) % 360
        w, d = _dims_for_rot(item, rot)
        for frac in (0.15, 0.35, 0.55, 0.75, 0.9):
            gap = min(max(lo + (hi - lo) * frac, lo + 3), hi - 3)   # держим запас от границ шкалы
            from .geometry import seating_front_offset
            off = gap + _half_along(tfp, fx, fy) + seating_front_offset(item)
            add(tv.x + fx * off, tv.y + fy * off, rot, f"напротив ТВ, {gap:.0f} см")
    if role == "тв-тумба" and sofa is not None:
        lo, hi = band_scale("sofa_tv_cm", room.band, distances().get("sofa_tv_cm", [180, 300]))
        fx, fy = _face_dir(sofa.rot)
        sfp = footprint(sofa)
        for frac in (0.35, 0.5, 0.75):
            gap = min(max(lo + (hi - lo) * frac, lo + 3), hi - 3)
            w, d = _dims_for_rot(item, (sofa.rot + 180) % 360)
            scx, scy = seat_center(sofa)
            cx = scx + fx * (gap + _half_along(sfp, fx, fy) + d / 2)
            cy = scy + fy * (gap + _half_along(sfp, fx, fy) + d / 2)
            add(cx, cy, (sofa.rot + 180) % 360, f"напротив дивана, {gap:.0f} см")
    if role == "столик" and sofa is not None:
        lo, hi = band_scale("sofa_table_cm", room.band, distances().get("sofa_coffee_table", [36, 50]))
        fx, fy = _face_dir(sofa.rot)
        sfp = footprint(sofa)
        from .geometry import seating_front_offset
        scx, scy = seat_center(sofa)
        for gap in (lo + 3, (lo + hi) / 2, hi - 3):
            off = gap + seating_front_offset(sofa.item) + _dims_for_rot(item, sofa.rot)[1] / 2
            add(scx + fx * off, scy + fy * off, sofa.rot, f"перед диваном, {gap:.0f} см")
    if role == "кресло" and sofa is not None:
        out += _arc_candidates(room, item, by, free, sofa)
    if role == "пуф" and ("столик" in by or sofa is not None):
        anchor = by.get("столик") or sofa
        for ang in (90, 270):                      # сбоку от столика, ВНЕ оси просмотра
            fx, fy = _face_dir((anchor.rot + ang) % 360)
            off = 40 + max(item.w_cm, item.d_cm) / 2 + max(anchor.item.w_cm, anchor.item.d_cm) / 2
            add(anchor.x + fx * off, anchor.y + fy * off, (anchor.rot + ang + 180) % 360, "сбоку от столика")
    if role == "торшер":
        for anchor in (by.get("кресло"), sofa):
            if anchor is None:
                continue
            afp = footprint(anchor)
            x0, y0, x1, y1 = afp.bounds
            for cx, cy in ((x0 - 20 - item.w_cm / 2, y0 + item.d_cm / 2),
                           (x1 + 20 + item.w_cm / 2, y0 + item.d_cm / 2)):
                add(cx, cy, anchor.rot, f"у «{anchor.role}»")
    if role == "стул" and "стол обеденный" in by:
        t = by["стол обеденный"]
        tw, td = _dims_for_rot(t.item, t.rot)
        for dx, dy, rot in ((0, -1, 0), (0, 1, 180), (-1, 0, 90), (1, 0, 270)):
            add(t.x + dx * (tw / 2 + item.d_cm / 2 - 8), t.y + dy * (td / 2 + item.d_cm / 2 - 8),
                rot, "у обеденного стола")
    return out


def _arc_candidates(room: Room, item: Item, by: dict, free: Polygon, sofa: Placement) -> list[Candidate]:
    """Кресло полукругом вокруг разговорной зоны (ADR-0051, схема ProcTHOR)."""
    scheme = rules().get("dynamic", {}).get("armchair_clearances", {}).get("placement_scheme", {})
    lo, hi = scheme.get("arc_deg_from_tv_axis", [135, 225])
    jit = scheme.get("jitter_deg", 35)
    center = by.get("столик") or sofa
    cx, cy = center.x, center.y
    base = max(item.w_cm, item.d_cm) / 2 + 45 + max(center.item.w_cm, center.item.d_cm) / 2
    out: list[Candidate] = []
    for th in (lo, hi, lo + jit, hi - jit, lo - jit, hi + jit):
        for k in (1.0, 1.35, 1.7):
            r = math.radians(th)
            # 180° — сторона дивана, 0° — сторона ТВ (ось зоны совпадает с «лицом» дивана)
            ax, ay = _face_dir(sofa.rot)          # направление «лица» дивана = ось зоны на ТВ
            R = base * k
            px = cx + R * (ax * math.cos(r) + ay * math.sin(r))
            py = cy + R * (ay * math.cos(r) - ax * math.sin(r))
            rot = _rot_towards(px, py, cx, cy)
            p = Placement(role=item.role, x=px, y=py, rot=rot, item=item)
            if _fits(room, p, free):
                out.append(Candidate(p, "anchor", f"дуга {th:.0f}°"))
                break   # для угла берём ближайший подходящий радиус
    return out


def _face_dir(rot: float) -> tuple[float, float]:
    r = math.radians(rot)
    return (round(math.sin(r), 6), round(math.cos(r), 6))


def _half_along(poly: Polygon, fx: float, fy: float) -> float:
    x0, y0, x1, y1 = poly.bounds
    return (x1 - x0) / 2 if abs(fx) > abs(fy) else (y1 - y0) / 2


def _rot_towards(x: float, y: float, tx: float, ty: float) -> int:
    dx, dy = tx - x, ty - y
    if abs(dx) > abs(dy):
        return 90 if dx > 0 else 270
    return 0 if dy > 0 else 180


# Функциональные группы: внутри группы зоны подхода друг друга не блокируют (стул ДОЛЖЕН стоять
# в зоне «отодвинуть стул» у стола, кресло — у фронта дивана). Идея ProcTHOR: asset group ставится
# целиком, margin применяется к группе, а не к её членам.
GROUPS = (frozenset({"диван", "столик", "кресло", "пуф"}),
          frozenset({"стол обеденный", "стул"}))
ZONE_GROUP = GROUPS[0]


def group_of(role: str) -> frozenset[str]:
    for g in GROUPS:
        if role in g:
            return g
    return frozenset()


def is_low(item: Item) -> bool:
    """Низкий/проходной предмет: столик, пуф, ковёр — им можно стоять в чужой зоне подхода."""
    return item.role in NEVER_BLOCKING_ROLES or (item.h_cm or 999) <= LOW_ITEM_MAX_H_CM


def generate(room: Room, item: Item, placed: list[Placement], *, limit: int = 48) -> list[Candidate]:
    """Все кандидаты для предмета при текущем состоянии комнаты (дедуп по сетке 10 см)."""
    ignore = group_of(item.role)
    free_poly = free_space(room, placed, with_clearance=not is_low(item), ignore_access_of=ignore)
    free = _Fitter(room, free_poly)
    cands = anchor_candidates(room, item, placed, free)
    cands += wall_candidates(room, item, free)
    if item.role in ("стол обеденный", "столик", "пуф", "ковёр"):
        cands += middle_candidates(room, item, free_poly, fitter=free)
    seen: set[tuple] = set()
    out: list[Candidate] = []
    for c in cands:
        key = (round(c.placement.x / 10), round(c.placement.y / 10), int(c.placement.rot) % 360)
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= limit:
            break
    return out

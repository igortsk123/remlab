"""Скоринг раскладки: формулы Infinigen (BSD-3, перенос идей в 2D) + веса из rules/weights.json.

Веса — стартовая таблица гостиной Infinigen, пересобранная под наши правила (кап пола наш,
шкалы диван↔ТВ/столик наши). Каждый терм возвращает штраф ≥0; итог = −Σ вес×штраф,
чтобы «больше — лучше». Разбор по термам сохраняется для объяснений top-K (Э5).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Polygon

from .clearances import band_scale, distances
from .geometry import facing_vector, floor_used_pct, footprint, free_space, room_polygon
from .models import Placement, Room

WEIGHTS_PATH = Path(__file__).resolve().parent.parent / "rules" / "weights.json"


@lru_cache(maxsize=1)
def weights() -> dict:
    return json.loads(WEIGHTS_PATH.read_text(encoding="utf-8"))


@dataclass
class Score:
    total: float = 0.0
    terms: dict[str, float] = field(default_factory=dict)

    def add(self, name: str, penalty: float, weight: float) -> None:
        if penalty <= 0:
            return
        self.terms[name] = round(self.terms.get(name, 0.0) + penalty * weight, 3)
        self.total -= penalty * weight


def hinge(x: float, lo: float, hi: float, *, scale: float = 100.0) -> float:
    """0 внутри коридора, линейный штраф вне (Infinigen hinge). scale — нормировка (см)."""
    if x < lo:
        return (lo - x) / scale
    if x > hi:
        return (x - hi) / scale
    return 0.0


def focus_score(a: Placement, b: Placement) -> float:
    """0 = «a» смотрит точно на «b», 0.5 = перпендикулярно, 1 = отвернулся (Infinigen)."""
    ax, ay = facing_vector(a.rot)
    dx, dy = b.x - a.x, b.y - a.y
    n = math.hypot(dx, dy) or 1.0
    return -(ax * dx / n + ay * dy / n) / 2 + 0.5


def wall_alignment_penalty(room: Room, p: Placement) -> float:
    """Штраф за неосевой поворот (инвариант «параллельно стенам»)."""
    return 0.0 if int(round(p.rot)) % 90 == 0 else 1.0


def _wall_distance(room: Room, p: Placement) -> float:
    fp = footprint(p)
    x0, y0, x1, y1 = fp.bounds
    return min(x0, y0, room.width_cm - x1, room.depth_cm - y1)


def score_layout(room: Room, ps: list[Placement], *, fast: bool = False) -> Score:
    w = weights()
    s = Score()
    by = {p.role: p for p in ps}
    # 1) заполненность пола — наша шкала от площади (НЕ 60–90% Infinigen: конфликт, канон наш)
    # кап пола — ВЕРХНЯЯ граница (недобор не дефект: состав сета задаёт витрина, не солвер)
    _cap_lo, cap_hi = band_scale("floor_cap_pct", room.band, [26, 50])
    used = floor_used_pct(room, ps)
    s.add("floor_overfill", hinge(used, 0, cap_hi, scale=10.0), w["floor_fill"])
    # 2) зона: диван↔ТВ, диван↔столик — по нашим шкалам
    if "диван" in by and "тв-тумба" in by:
        lo, hi = band_scale("sofa_tv_cm", room.band, distances().get("sofa_tv_cm", [180, 300]))
        g = footprint(by["диван"]).distance(footprint(by["тв-тумба"]))
        s.add("sofa_tv_dist", hinge(g, lo, hi), w["sofa_tv_dist"])
        s.add("sofa_faces_tv", focus_score(by["диван"], by["тв-тумба"]), w["sofa_faces_tv"])
        s.add("tv_faces_sofa", focus_score(by["тв-тумба"], by["диван"]), w["tv_faces_sofa"])
    if "диван" in by and "столик" in by:
        lo, hi = band_scale("sofa_table_cm", room.band, distances().get("sofa_coffee_table", [36, 50]))
        g = footprint(by["диван"]).distance(footprint(by["столик"]))
        s.add("sofa_table_dist", hinge(g, lo, hi), w["sofa_table_dist"])
    if "кресло" in by and "диван" in by:
        g = footprint(by["кресло"]).distance(footprint(by["диван"]))
        lo, hi = distances().get("facing_seats", [110, 240])
        s.add("seats_group", hinge(g, 0, hi), w["seats_group"])
        if "тв-тумба" in by:
            s.add("armchair_faces_tv", focus_score(by["кресло"], by["тв-тумба"]), w["armchair_faces_tv"])
        if "столик" in by:   # полукруг вокруг столика: не дальше вытянутой руки от зоны
            gz = footprint(by["кресло"]).distance(footprint(by["столик"]))
            s.add("armchair_zone_radius", hinge(gz, 30, 75), w["armchair_zone_radius"])
        if "тв-тумба" in by:  # кресло, приткнутое вплотную к ТВ, читается как «мебель у техники»
            gt = footprint(by["кресло"]).distance(footprint(by["тв-тумба"]))
            s.add("armchair_not_at_tv", hinge(gt, 90, 10_000), w["armchair_not_at_tv"])
    # 3) пристенность: хранение — к стене; обеденный стол — наоборот, от стен (Infinigen)
    for p in ps:
        d = _wall_distance(room, p)
        if p.role in ("шкаф", "комод", "стенка", "витрина", "стеллаж", "тв-тумба", "камин"):
            s.add("wall_hug", hinge(d, 0, 15, scale=50.0), w["wall_hug"])
        if p.role == "диван":
            # диван либо ВПЛОТНУЮ к стене, либо «отплыл» с проходом за спинкой (≥76 см);
            # промежуточное положение — щель, в которую не пройти (наш narrow_room-свод)
            pass_behind = distances().get("sofa_to_wall_passage", 70)
            if 15 < d < pass_behind:
                s.add("sofa_dead_gap", min(d - 15, pass_behind - d) / 20.0, w["wall_hug"])
        if p.role == "стол обеденный":
            s.add("dining_off_wall", hinge(d, 60, 10_000, scale=50.0), w["dining_off_wall"])
        s.add("axis_alignment", wall_alignment_penalty(room, p), w["axis_alignment"])
    # 3b) якоря зоны — по центру своей стены (Infinigen: центрировать ТВ-стенд вдоль стены)
    for role in ("диван", "тв-тумба"):
        p = by.get(role)
        if p is None:
            continue
        along = room.width_cm if int(p.rot) % 180 == 0 else room.depth_cm
        pos = p.x if int(p.rot) % 180 == 0 else p.y
        s.add("wall_centering", abs(pos - along / 2) / 100.0, w["wall_centering"])
    # 3c) щели-невидимки: зазор 5–60 см между предметами непроходим и «съедает» комнату.
    # Дешёвый прокси связности — без него beam находит красивые, но непроходимые раскладки.
    pass_min = distances().get("passage_secondary_min", 60)
    fps = [(p, footprint(p)) for p in ps]
    for i, (a, fa) in enumerate(fps):
        for b, fb in fps[i + 1:]:
            g = fa.distance(fb)
            if 5 < g < pass_min:
                s.add("sliver_gap", (pass_min - g) / pass_min, w["sliver_gap"])
    # 4) не сбиваться в кучу: пристенные попарно 20–60 см (Infinigen)
    wallish = [p for p in ps if p.role in ("шкаф", "комод", "стенка", "витрина", "стеллаж")]
    for i, a in enumerate(wallish):
        for b in wallish[i + 1:]:
            g = footprint(a).distance(footprint(b))
            if g < 20:
                s.add("storage_spacing", hinge(g, 20, 10_000, scale=50.0), w["storage_spacing"])
    # 5) компактность/проходы: чем более рваное свободное место, тем хуже
    if fast:                      # в beam-поиске дорогие полигонные операции пропускаем
        return s
    free = free_space(room, ps, with_clearance=False)
    if not free.is_empty:
        parts = 1 if free.geom_type == "Polygon" else len(free.geoms)
        s.add("free_space_fragmentation", max(0, parts - 1), w["free_space_fragmentation"])
    return s

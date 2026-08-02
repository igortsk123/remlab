"""Э5: объяснения вариантов — сильные стороны, компромиссы, разбор скора.

Пользователь (и владелец) выбирает раскладку глазами: нужно человеческое «почему этот
вариант», а не число. Термы скоринга переводятся в короткие фразы; нарушения показываются
как есть (у них уже есть message/expected).
"""
from __future__ import annotations

from .models import Layout, Room, Severity
from .score import score_layout

TERM_LABEL = {
    "floor_overfill": "мебели больше, чем допускает кап пола",
    "sofa_tv_dist": "дистанция диван↔ТВ на краю шкалы",
    "sofa_faces_tv": "диван смотрит на ТВ неточно",
    "tv_faces_sofa": "ТВ развёрнут не на диван",
    "sofa_table_dist": "столик далековат/близковат к дивану",
    "seats_group": "кресло далеко от дивана — зона рыхлая",
    "armchair_faces_tv": "кресло смотрит мимо ТВ",
    "armchair_zone_radius": "кресло вне полукруга вокруг столика",
    "armchair_not_at_tv": "кресло приткнуто к ТВ-тумбе",
    "wall_hug": "мебель хранения не прижата к стене",
    "sofa_dead_gap": "за диваном щель, в которую не пройти",
    "dining_off_wall": "обеденный стол зажат к стене",
    "axis_alignment": "предметы не параллельны стенам",
    "storage_spacing": "корпусная мебель сбита в кучу",
    "sliver_gap": "между предметами щели, в которые не пройти",
    "wall_centering": "зона смещена от центра стены",
    "free_space_fragmentation": "свободное место разорвано на куски",
}

STRENGTH_RULES = [
    ("зона собрана: диван, столик и ТВ на одной оси", ("sofa_tv_dist", "sofa_table_dist", "sofa_faces_tv")),
    ("кресло в полукруге у зоны", ("armchair_zone_radius", "seats_group")),
    ("хранение прижато к стенам, центр свободен", ("wall_hug", "storage_spacing")),
    ("свободное место цельное, проходы не режутся", ("free_space_fragmentation",)),
    ("пол не перегружен мебелью", ("floor_overfill",)),
    ("композиция по центру стены", ("wall_centering",)),
]


def explain(room: Room, layout: Layout) -> dict:
    """Разбор варианта: score, термы, сильные стороны, компромиссы, нарушения."""
    sc = score_layout(room, layout.placements)
    terms = dict(sorted(sc.terms.items(), key=lambda kv: -kv[1]))
    strengths = [text for text, keys in STRENGTH_RULES if all(terms.get(k, 0) < 1e-6 for k in keys)]
    tradeoffs = [f"{TERM_LABEL.get(k, k)} (−{v:.1f})" for k, v in list(terms.items())[:3]]
    return {
        "score": round(sc.total, 2),
        "terms": terms,
        "strengths": strengths,
        "tradeoffs": tradeoffs,
        "blockers": [f"[{v.code}] {v.message}" for v in layout.violations
                     if v.severity is Severity.HARD]
        + ([f"[UNPLACED] не удалось разместить: {', '.join(layout.unplaced)}"]
           if layout.unplaced else []),
        "floor_used_pct": layout.floor_used_pct,
        "unplaced": layout.unplaced,
    }


def why_not(layout: Layout) -> str | None:
    """Короткая причина, почему вариант не считается валидным (для UI и логов)."""
    hard = [v for v in layout.violations if v.severity is Severity.HARD]
    if layout.unplaced:
        tail = f"; также {hard[0].message}" if hard else ""
        return f"не удалось разместить: {', '.join(layout.unplaced)}{tail}"
    if not hard:
        return None
    first = hard[0]
    tail = f" (+ещё {len(hard) - 1})" if len(hard) > 1 else ""
    return f"{first.message}{tail}"

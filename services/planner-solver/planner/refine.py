"""Э4: локальное уточнение — coordinate descent с violation-first приёмкой.

Схема приёмки — из Infinigen (BSD-3, идея): ход, уменьшающий число hard-нарушений, принимается
ВСЕГДА; увеличивающий — никогда; при равенстве решает скоринг. Сдвиги проецируются на
разрешённые степени свободы: пристенный предмет скользит ВДОЛЬ стены, повороты квантованы.
"""
from __future__ import annotations

from .geometry import footprint
from .models import Layout, Placement, Room, Severity
from .score import score_layout
from .validate import WALL_ONLY_ROLES, validate

STEPS_CM = (20.0, 10.0, 5.0)
MAX_ROUNDS = 6


def _hard(layout: Layout) -> int:
    return sum(1 for v in layout.violations if v.severity is Severity.HARD)


def _axes_for(room: Room, p: Placement) -> list[tuple[float, float]]:
    """Разрешённые направления сдвига: у стены — только вдоль неё, иначе обе оси."""
    if p.role in WALL_ONLY_ROLES:
        return [(1.0, 0.0)] if int(p.rot) % 180 == 0 else [(0.0, 1.0)]
    return [(1.0, 0.0), (0.0, 1.0)]


def refine(room: Room, layout: Layout, *, rounds: int = MAX_ROUNDS) -> Layout:
    """Доводка раскладки: те же предметы, чуть другие координаты — меньше нарушений."""
    best = layout
    best_h, best_s = _hard(best), score_layout(room, best.placements).total
    if best_h == 0:                 # валидную раскладку только полируем — дешёвый режим
        rounds, steps = 2, (10.0,)
    else:
        steps = STEPS_CM
    for _ in range(rounds):
        improved = False
        # чинить в первую очередь тех, кто фигурирует в нарушениях (violation-first)
        guilty = {r for v in best.violations for r in v.roles}
        order = sorted(range(len(best.placements)),
                       key=lambda i: 0 if best.placements[i].role in guilty else 1)
        for i in order:
            p = best.placements[i]
            for step in steps:
                for ax, ay in _axes_for(room, p):
                    for sign in (1, -1):
                        cand = list(best.placements)
                        cand[i] = p.model_copy(update={"x": p.x + ax * step * sign,
                                                       "y": p.y + ay * step * sign})
                        trial = validate(room, cand)
                        h, sc = _hard(trial), score_layout(room, cand).total
                        if h < best_h or (h == best_h and sc > best_s + 1e-9):
                            best, best_h, best_s = trial, h, sc
                            p = cand[i]
                            improved = True
        if not improved:
            break
    best.unplaced = layout.unplaced
    return best

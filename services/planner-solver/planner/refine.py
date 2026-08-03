"""Э4: локальное уточнение — coordinate descent с violation-first приёмкой.

Схема приёмки — из Infinigen (BSD-3, идея): ход, уменьшающий число hard-нарушений, принимается
ВСЕГДА; увеличивающий — никогда; при равенстве решает скоринг. Сдвиги проецируются на
разрешённые степени свободы: пристенный предмет скользит ВДОЛЬ стены, повороты квантованы.
"""
from __future__ import annotations

from .candidates import generate
from .geometry import footprint
from .models import Layout, Placement, Room, Severity
from .score import score_layout
from .validate import WALL_ONLY_ROLES, validate

STEPS_CM = (20.0, 10.0, 5.0)
MAX_ROUNDS = 6


def _hard(layout: Layout) -> int:
    return sum(1 for v in layout.violations if v.severity is Severity.HARD)


def _hard_codes(layout: Layout) -> set:
    """Набор кодов нарушений: считать только ЧИСЛО нельзя — размен «одно на другое» проходил
    как равный и выпускал раскладку за границу шкалы (сет 28: диван↔ТВ 189 при минимуме 190)."""
    return {v.code for v in layout.violations if v.severity is Severity.HARD}


def _axes_for(room: Room, p: Placement) -> list[tuple[float, float]]:
    """Разрешённые направления сдвига: у стены — только вдоль неё, иначе обе оси."""
    if p.role in WALL_ONLY_ROLES:
        return [(1.0, 0.0)] if int(p.rot) % 180 == 0 else [(0.0, 1.0)]
    return [(1.0, 0.0), (0.0, 1.0)]


MOVABLE_FOR_REPAIR = ("шкаф", "комод", "стенка", "витрина", "стеллаж", "камин", "кашпо",
                      "торшер", "кресло", "пуф")


def repair_unplaced(room: Room, layout: Layout, items: list) -> Layout:
    """Перестановка ради непоставленного: подвинуть уже стоящее пристенное и повторить попытку.

    Жадный проход не умеет отступать — крупное хранение занимает лучшие стены, и последнему
    предмету места не остаётся. Здесь ветка получает второй шанс: до 3 альтернатив на каждый
    уже поставленный предмет, приёмка — только если непоставленных стало меньше, а hard-нарушений
    не прибавилось (violation-first, детерминированно).
    """
    if not layout.unplaced:
        return layout
    by_role = {it.role: it for it in items}
    best = layout
    for role in list(layout.unplaced):
        item = by_role.get(role)
        if item is None:
            continue
        placed = list(best.placements)
        done = False
        # 1) прямая попытка в текущей раскладке
        for c in generate(room, item, placed)[:24]:
            trial = validate(room, placed + [c.placement])
            if not [v for v in trial.violations if v.severity is Severity.HARD]:
                best = trial
                best.unplaced = [r for r in best.unplaced + layout.unplaced if r != role]
                done = True
                break
        if done:
            continue
        # 2) подвинуть уже стоящее пристенное и повторить
        for i, p in enumerate(placed):
            if p.role not in MOVABLE_FOR_REPAIR or done:
                continue
            others = [q for j, q in enumerate(placed) if j != i]
            for alt in generate(room, p.item, others)[:4]:
                base = others + [alt.placement]
                for c in generate(room, item, base)[:8]:
                    trial = validate(room, base + [c.placement])
                    if not [v for v in trial.violations if v.severity is Severity.HARD]:
                        trial.unplaced = [r for r in layout.unplaced if r != role]
                        best = trial
                        done = True
                        break
                if done:
                    break
    return best


def refine(room: Room, layout: Layout, *, rounds: int = MAX_ROUNDS) -> Layout:
    """Доводка раскладки: те же предметы, чуть другие координаты — меньше нарушений."""
    best = layout
    best_h, best_s = _hard(best), score_layout(room, best.placements).total
    best_codes = _hard_codes(best)
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
                        codes = _hard_codes(trial)
                        if codes - best_codes:        # появился НОВЫЙ вид нарушения — ход не берём
                            continue
                        if h < best_h or (h == best_h and sc > best_s + 1e-9):
                            best, best_h, best_s, best_codes = trial, h, sc, codes
                            p = cand[i]
                            improved = True
        if not improved:
            break
    best.unplaced = layout.unplaced
    return best

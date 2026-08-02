"""Э2: beam search по кандидатам — вместо жадного DFS с пост-фиксами.

Луч ведёт НЕСКОЛЬКО частичных раскладок сразу и отбирает по частичному скорингу; в конце
остаются top-K РАЗНЫХ вариантов (keep_best_diverse). Детерминизм: при равных скорах порядок
задаётся стабильным ключом кандидата, случайности нет — input+seed → тот же результат.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .candidates import Candidate, generate, order_items
from .geometry import footprint
from .models import Item, Layout, Placement, Room
from .refine import refine
from .score import Score, score_layout
from .validate import (
    check_boundary,
    check_distances,
    check_collisions,
    check_facing,
    check_openings,
    check_radiators,
    check_sightline,
    check_wall_only,
    check_zone,
    validate,
)

BEAM_WIDTH = 20          # спека: 20–30
CAND_PER_ITEM = 8        # сколько кандидатов раскрываем от каждого состояния
DIVERSITY_CM = 60.0      # два варианта «разные», если хоть один предмет сдвинут дальше этого
# штраф за НЕразмещённый предмет: без него ветка «выкинуть ТВ» побеждает ветку «подвинуть диван»
CORE_ROLES = frozenset({"диван", "тв-тумба", "столик", "кресло"})
UNPLACED_PENALTY = {"core": 120.0, "other": 25.0}


@dataclass
class State:
    placements: list[Placement] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)
    score: float = 0.0
    penalty: float = 0.0     # накопленный штраф за неразмещённое (в score уже учтён)

    def key(self) -> tuple:
        return tuple(sorted((p.role, round(p.x, 1), round(p.y, 1), int(p.rot) % 360)
                            for p in self.placements))


def _hard_ok(room: Room, ps: list[Placement]) -> bool:
    """Быстрые hard-проверки для отсечения кандидата (полная валидация — в конце)."""
    return not (check_boundary(room, ps) or check_collisions(ps)
                or check_openings(room, ps) or check_radiators(room, ps)
                or check_facing(ps) or check_distances(room, ps)
                or check_wall_only(room, ps) or check_zone(ps)
                or check_sightline(ps))


def _diverse(a: State, b: State) -> bool:
    """Разные ли раскладки: хоть один общий предмет стоит дальше DIVERSITY_CM."""
    pa = {p.role: p for p in a.placements}
    for p in b.placements:
        q = pa.get(p.role)
        if q is None:
            return True
        if ((p.x - q.x) ** 2 + (p.y - q.y) ** 2) ** 0.5 > DIVERSITY_CM:
            return True
        # разворот считается «другим вариантом» только для якорей зоны: повёрнутое кашпо —
        # не другая планировка (иначе top-K заполняется клонами)
        if p.role in CORE_ROLES and int(p.rot) != int(q.rot):
            return True
    return False


def keep_best_diverse(states: list[State], k: int) -> list[State]:
    """Топ-K по скору, но каждый следующий обязан отличаться от уже взятых."""
    out: list[State] = []
    for st in sorted(states, key=lambda s: (-s.score, s.key())):
        if all(_diverse(st, o) for o in out):
            out.append(st)
        if len(out) >= k:
            break
    return out


def solve(room: Room, items: list[Item], *, top_k: int = 3, beam_width: int = BEAM_WIDTH,
          cand_per_item: int = CAND_PER_ITEM, polish: bool = True) -> list[Layout]:
    """Комната + предметы → до top_k валидных РАЗНЫХ раскладок, лучшие первыми."""
    beams: list[State] = [State()]
    for item in order_items(items):
        nxt: list[State] = []
        seen: set[tuple] = set()
        for st in beams:
            cands: list[Candidate] = generate(room, item, st.placements)
            scored: list[tuple[float, Candidate, Score]] = []
            for c in cands:
                ps = st.placements + [c.placement]
                if not _hard_ok(room, ps):
                    continue
                sc = score_layout(room, ps, fast=True)
                scored.append((sc.total, c, sc))
            scored.sort(key=lambda t: (-t[0], t[1].placement.x, t[1].placement.y, t[1].placement.rot))
            if not scored:  # предмет не встал ни в одну позицию — ветка продолжается без него
                pen = st.penalty + UNPLACED_PENALTY["core" if item.role in CORE_ROLES else "other"]
                st2 = State(list(st.placements), st.unplaced + [item.role],
                            st.score - (pen - st.penalty), pen)
                if st2.key() not in seen:
                    seen.add(st2.key())
                    nxt.append(st2)
                continue
            for total, c, _sc in scored[:cand_per_item]:
                st2 = State(st.placements + [c.placement], list(st.unplaced),
                            total - st.penalty, st.penalty)
                k = st2.key()
                if k in seen:
                    continue
                seen.add(k)
                nxt.append(st2)
        # отбор луча — с разнообразием: иначе ветки-клоны вытесняют принципиально другие схемы
        beams = keep_best_diverse(nxt, beam_width) or sorted(nxt, key=lambda s: -s.score)[:beam_width]
        if not beams:
            beams = [State()]
    finals: list[State] = []
    for st in beams:  # полная валидация (проходы/связность/шкалы) — только для финалистов
        layout = validate(room, st.placements)
        layout.unplaced = st.unplaced
        if layout.ok:
            finals.append(State(st.placements, st.unplaced, st.score, st.penalty))
    if not finals and polish:
        # ни одна ветка не прошла полную валидацию (обычно тесная комната + узкие проходы):
        # доводим лучшие ветки Э4-уточнением и берём те, что после доводки стали валидны
        for st in beams[:8]:
            fixed = refine(room, validate(room, st.placements))
            fixed.unplaced = st.unplaced
            if fixed.ok:
                finals.append(State(fixed.placements, st.unplaced, st.score, st.penalty))
    pool = finals or beams
    out: list[Layout] = []
    kept: list[State] = []
    # разнообразие проверяем ПОСЛЕ доводки: уточнение стягивает похожие ветки в одну точку
    for st in keep_best_diverse(pool, max(top_k * 4, 8)):
        layout = validate(room, st.placements)
        layout.unplaced = st.unplaced
        if polish:                      # Э4: доводка — снимает остаточные нарушения
            layout = refine(room, layout)
        cand = State(layout.placements, layout.unplaced, st.score, st.penalty)
        if any(not _diverse(cand, k) for k in kept):
            continue
        kept.append(cand)
        out.append(layout)
        if len(out) >= top_k:
            break
    out.sort(key=lambda l: (not l.ok, -score_layout(room, l.placements).total))
    return out

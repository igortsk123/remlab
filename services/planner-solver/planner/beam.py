"""Э2: beam search по кандидатам — вместо жадного DFS с пост-фиксами.

Луч ведёт НЕСКОЛЬКО частичных раскладок сразу и отбирает по частичному скорингу; в конце
остаются top-K РАЗНЫХ вариантов (keep_best_diverse). Детерминизм: при равных скорах порядок
задаётся стабильным ключом кандидата, случайности нет — input+seed → тот же результат.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .candidates import Candidate, generate, order_items
from .clearances import rules
from .geometry import footprint
from .models import Item, Layout, Placement, Room, Severity
from .refine import refine, repair_unplaced
from .score import Score, score_layout
from .validate import (
    check_access,
    check_behind_sofa,
    check_boundary,
    check_distances,
    check_collisions,
    check_facing,
    check_layout_rules,
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
# Ярусы наполнения гостиной берём из ФАЙЛА правил (placement_tiers), не из кода: база
# обязательна, хранение и обеденная группа — по площади, остальное по остаточному принципу.
# Штраф за неразмещённое должен ЗАВЕДОМО перевешивать сумму мягких штрафов (плавающий Г-диван
# в большой комнате набирал 40+, и ветка «выкинуть диван» обгоняла ветку «оставить»).
UNPLACED_PENALTY = {"base": 400.0, "storage": 200.0, "dining": 120.0, "optional": 40.0}


def tier_of(role: str) -> str:
    t = rules().get("placement_tiers", {})
    for name in ("base", "storage", "dining", "optional"):
        if role in t.get(name, ()):
            return name
    return "optional"


def _unplaced_cost(role: str) -> float:
    return UNPLACED_PENALTY.get(tier_of(role), 40.0)


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
    """Быстрые проверки для отсечения кандидата — ТОЛЬКО жёсткие.

    Раньше проверялось «список нарушений пуст», и любая МЯГКАЯ пометка (ТВ у окна, буфер зоны)
    убивала кандидата наравне с коллизией — движок терял диван в комнатах 50+.
    """
    for check in (check_boundary(room, ps), check_collisions(ps), check_openings(room, ps),
                  check_radiators(room, ps), check_facing(ps), check_distances(room, ps),
                  check_wall_only(room, ps), check_zone(ps), check_sightline(ps),
                  check_behind_sofa(room, ps), check_layout_rules(room, ps), check_access(ps)):
        if any(v.severity is Severity.HARD for v in check):
            return False
    return True


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
        if tier_of(p.role) == "base" and int(p.rot) != int(q.rot):
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


def drop_optional_until_valid(room: Room, layout: Layout) -> Layout:
    """Раскладка не сходится → УБИРАЕМ опциональное, а не ставим его с нарушением.

    Иначе движок отдавал «лучшее из плохого»: кресло вставало в один ряд с ТВ-тумбой, лишь бы
    стоять. Опциональный предмет, которому нет законного места, — это норма (ярусы наполнения).
    """
    if layout.ok:
        return layout
    guilty_first = sorted(
        [p for p in layout.placements if tier_of(p.role) == "optional"],
        key=lambda p: 0 if any(p.role in v.roles for v in layout.violations
                               if v.severity is Severity.HARD) else 1)
    dropped: list[str] = []
    cur = layout
    for p in guilty_first:
        if cur.ok:
            break
        trial = validate(room, [q for q in cur.placements if q is not p])
        if len(trial.violations) < len(cur.violations) or trial.ok:
            dropped.append(p.role)
            trial.unplaced = list(cur.unplaced)
            trial.skipped_optional = list(cur.skipped_optional) + [p.role]
            cur = trial
    if dropped:
        cur.skipped_optional = sorted(set(cur.skipped_optional))
    return cur


def solve(room: Room, items: list[Item], *, top_k: int = 3, beam_width: int = BEAM_WIDTH,
          cand_per_item: int = CAND_PER_ITEM, polish: bool = True) -> list[Layout]:
    """Комната + предметы → до top_k валидных РАЗНЫХ раскладок, лучшие первыми."""
    beams: list[State] = [State()]
    for item in order_items(items):
        nxt: list[State] = []
        seen: set[tuple] = set()
        # раскрываем столько кандидатов, чтобы луч оставался полным: на первом предмете веток
        # всего одна, и cand_per_item=8 давал 8 позиций — если среди них нет ни одной, куда
        # встанет следующий предмет, вся раскладка теряла его (сеты 50+ теряли диван)
        per_state = max(cand_per_item, -(-beam_width // max(1, len(beams))))
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
                pen = st.penalty + _unplaced_cost(item.role)
                st2 = State(list(st.placements), st.unplaced + [item.role],
                            st.score - (pen - st.penalty), pen)
                if st2.key() not in seen:
                    seen.add(st2.key())
                    nxt.append(st2)
                continue
            for total, c, _sc in scored[:per_state]:
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
        layout.unplaced = [r for r in st.unplaced if tier_of(r) != "optional"]
        layout.skipped_optional = [r for r in st.unplaced if tier_of(r) == "optional"]
        if polish:                      # Э4: доводка — снимает остаточные нарушения
            if layout.unplaced:         # ...и перестановка ради непоставленного (шаг 1 плана gaps)
                layout = repair_unplaced(room, layout, items)
            layout = refine(room, layout)
            layout = drop_optional_until_valid(room, layout)
        cand = State(layout.placements, layout.unplaced, st.score, st.penalty)
        if any(not _diverse(cand, k) for k in kept):
            continue
        kept.append(cand)
        out.append(layout)
        if len(out) >= top_k:
            break
    out.sort(key=lambda l: (not l.ok, -score_layout(room, l.placements).total))
    return out

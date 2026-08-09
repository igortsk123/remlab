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
    from .geometry import base_role
    role = base_role(role)
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
          cand_per_item: int = CAND_PER_ITEM, polish: bool = True,
          fixed: list[Placement] | None = None) -> list[Layout]:
    """Комната + предметы → до top_k валидных РАЗНЫХ раскладок, лучшие первыми.

    С Г-диваном сначала пробуем «диван в угол первым» (канон); если так теряется ТВ-тумба
    (большая комната: угол и шкала диван↔ТВ несовместимы) — пере-решаем старым порядком и
    берём вариант без потерь. Компромисс зафиксирован: лучше диван посреди стены с ТВ, чем
    угол без ТВ (вердикт по перегону 2026-08-06; финальное слово — калибровка владельцем)."""
    # T6 truth-first: band выставляется ЗДЕСЬ, а не лениво в validate() — иначе быстрые
    # check_* в _hard_ok первого прогона видят band предыдущей сцены процесса, и повторное
    # решение той же комнаты даёт другую раскладку (найдено fuzz_rooms 08.08, подтверждено
    # сбросом глобала). Один процесс = много сцен (solver_check, фаззер) — заражение реально.
    from .validate import _ROOM_BAND
    _ROOM_BAND[0] = room.band
    outs = _solve_ordered(room, items, top_k=top_k, beam_width=beam_width,
                          cand_per_item=cand_per_item, polish=polish, corner_sofa_first=True,
                          fixed=fixed)
    has_corner = any(it.role == "диван" and it.corner for it in items)
    # носитель ТВ — тумба ИЛИ стенка (правило владельца 08.08); прежняя страховка знала
    # только тумбу, и Г-диван-первым терял СТЕНКУ без пере-решения (set113, 19 предметов → 3)
    _bearer = ("тв-тумба" if any(it.role == "тв-тумба" for it in items)
               else ("стенка" if any(it.role == "стенка" for it in items) else None))
    def _lost(lay):
        return _bearer is not None and _bearer not in {p.role for p in lay.placements}
    def _anchors(lay):
        pr = {p.role for p in lay.placements}
        return (('диван' in pr) + (_bearer in pr if _bearer else 1),
                -sum(1 for r in lay.unplaced))
    if has_corner and outs and _lost(outs[0]):
        alt = _solve_ordered(room, items, top_k=top_k, beam_width=beam_width,
                             cand_per_item=cand_per_item, polish=polish, corner_sofa_first=False,
                             fixed=fixed)
        # выбор ветки — по ОБОИМ якорям (диван И носитель), не только носителю:
        # прежний выбор брал вариант со стенкой, но без дивана (set113)
        if alt and _anchors(alt[0]) > _anchors(outs[0]):
            outs = alt
    from .geometry import base_role as _br
    for lay in outs:
        # П8 (вердикт 07.08, сет 47) + вердикт 08.08 («минимум 2 стула»): обеденная группа
        # целиком или никак — стол без ≥2 стульев снимается, стулья без стола снимаются
        chairs_placed = [p for p in lay.placements if _br(p.role) == "стул"]
        tbl_p = next((p for p in lay.placements if p.role == "стол обеденный"), None)
        if tbl_p is not None and chairs_placed:
            # в группе считаются только стулья У СТОЛА (≤45 см до кромки — порог CHAIR_ORPHAN
            # с запасом): стул, уехавший через комнату, не «член группы», а брак — снимаем
            tfp = footprint(tbl_p)
            far = [p for p in chairs_placed if footprint(p).distance(tfp) > 45]
            if far:
                gone = [p.role for p in far]
                lay.placements = [p for p in lay.placements if p.role not in gone]
                lay.unplaced = lay.unplaced + gone
                chairs_placed = [p for p in chairs_placed if p.role not in gone]
        tbl_placed = tbl_p is not None
        if tbl_placed and len(chairs_placed) < 2:
            gone = ["стол обеденный"] + [p.role for p in chairs_placed]
            lay.placements = [p for p in lay.placements if p.role not in gone]
            lay.unplaced = lay.unplaced + gone
        elif not tbl_placed and chairs_placed:
            gone = [p.role for p in chairs_placed]
            lay.placements = [p for p in lay.placements if p.role not in gone]
            lay.unplaced = lay.unplaced + gone
        # Рефери 08.08 (Q1/3.3): ярусы dining/storage — приоритет удержания, не обязательный
        # инвентарь. Не встали (площадный гейт состава — префильтр, финальное слово за
        # геометрией) → честный дроп в skipped_optional, а не провал всей сцены.
        droppable = [r for r in lay.unplaced if tier_of(r) in ("dining", "storage", "optional")]
        if droppable:
            lay.unplaced = [r for r in lay.unplaced if r not in droppable]
            lay.skipped_optional = sorted(set(lay.skipped_optional) | set(droppable))
        # Страховка (вердикт 07.08, сет 76: стул в 140 см прошёл «ok»): ПОЛНАЯ ревалидация
        # финального размещения — доводка/ремонт не имеют права выпускать hard мимо отчёта
        from .refine import _snap_bearer_axis, _snap_rug_anchor, _snap_table_center
        lay2 = _snap_table_center(room, _snap_rug_anchor(room, _snap_bearer_axis(room, lay)))
        lay.placements = lay2.placements
        fresh = validate(room, lay.placements)
        lay.violations = fresh.violations
        lay.floor_used_pct = fresh.floor_used_pct
    # Z3 (правка владельца 07.08): финальный отбор — ЛЕКСИКОГРАФИЧЕСКИ по уровням
    # feasibility → circulation → functional → zone → aesthetics: эстетика никогда не
    # компенсирует заблокированный проход. Внутри beam — быстрая сумма, здесь — строгий порядок.
    from .score import score_layout as _sl
    from .zones import lexo_key

    def _key(lay):
        hard = sum(1 for v in lay.violations if v.severity is Severity.HARD)
        req = sum(1 for r in lay.unplaced if tier_of(r) != "optional")
        return lexo_key(hard, req, _sl(room, lay.placements).terms)
    outs.sort(key=_key)
    return outs


def _solve_ordered(room: Room, items: list[Item], *, top_k: int, beam_width: int,
                   cand_per_item: int, polish: bool, corner_sofa_first: bool,
                   fixed: list[Placement] | None = None) -> list[Layout]:
    beams: list[State] = [State(placements=list(fixed))] if fixed else [State()]
    for item in order_items(items, corner_sofa_first=corner_sofa_first):
        nxt: list[State] = []
        seen: set[tuple] = set()
        # раскрываем столько кандидатов, чтобы луч оставался полным: на первом предмете веток
        # всего одна, и cand_per_item=8 давал 8 позиций — если среди них нет ни одной, куда
        # встанет следующий предмет, вся раскладка теряла его (сеты 50+ теряли диван)
        per_state = max(cand_per_item, -(-beam_width // max(1, len(beams))))
        # L3 (MASTER-layout-v5): пара кресел раскрывается АТОМАРНО — joint-кандидаты конкурируют
        # с одиночными в одном шаге луча; «кресло 2» из порядка не убирается: состояния, где
        # пара уже стоит, проносятся сквозь его шаг без изменений (см. ниже)
        pair_partner = None
        if item.role == "кресло":
            pair_partner = next((it for it in items if it.role == "кресло 2"), None)
        for st in beams:
            if any(p.role == item.role for p in st.placements):
                # предмет уже поставлен joint-кандидатом на шаге первого кресла
                if st.key() not in seen:
                    seen.add(st.key())
                    nxt.append(st)
                continue
            cands: list[Candidate] = generate(room, item, st.placements)
            if pair_partner is not None and not any(p.role == pair_partner.role
                                                    for p in st.placements):
                from .candidates import pair_candidates
                cands = cands + pair_candidates(room, item, pair_partner, st.placements)
            scored: list[tuple[float, Candidate, Score]] = []
            for c in cands:
                ps = st.placements + [c.placement, *c.extra]
                if not _hard_ok(room, ps):
                    continue
                sc = score_layout(room, ps, fast=True)
                scored.append((sc.total, c, sc))
            scored.sort(key=lambda t: (-t[0], t[1].placement.x, t[1].placement.y, t[1].placement.rot))
            # L3.2: пары и одиночки — РАЗДЕЛЬНЫЕ квоты среза. Joint-пара размещает 2 предмета,
            # её fast-score систематически выше одиночного → пары вытесняли одиночные ветки из
            # per_state-среза, а на полной валидации падали (A/B 09.08: −6 кресел, +5 hard).
            # Пары идут ДОБАВКОЙ к полному одиночному срезу, а не вместо него.
            if any(t[1].extra for t in scored):
                singles = [t for t in scored if not t[1].extra][:per_state]
                pairs = [t for t in scored if t[1].extra][:max(2, per_state // 2)]
                expand = singles + pairs
            else:
                expand = scored[:per_state]
            if not scored:  # предмет не встал ни в одну позицию — ветка продолжается без него
                pen = st.penalty + _unplaced_cost(item.role)
                st2 = State(list(st.placements), st.unplaced + [item.role],
                            st.score - (pen - st.penalty), pen)
                if st2.key() not in seen:
                    seen.add(st2.key())
                    nxt.append(st2)
                continue
            for total, c, _sc in expand:
                st2 = State(st.placements + [c.placement, *c.extra], list(st.unplaced),
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

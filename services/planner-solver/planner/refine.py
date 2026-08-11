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
            for alt in generate(room, p.item, others)[:6]:
                base = others + [alt.placement]
                for c in generate(room, item, base)[:12]:
                    trial = validate(room, base + [c.placement])
                    if not [v for v in trial.violations if v.severity is Severity.HARD]:
                        trial.unplaced = [r for r in layout.unplaced if r != role]
                        best = trial
                        done = True
                        break
                if done:
                    break
    return best


def _snap_bearer_axis(room: Room, layout: Layout) -> Layout:
    """Снап носителя ТВ (стенка/тумба) к ОСИ дивана: медиа-блок центрируется по посадке,
    не по стене (канон: практика просмотра важнее симметрии стены; вердикт владельца 08.08 —
    смещения 40–132 см). Скользим вдоль своей стены; принять, если hard не хуже."""
    from .geometry import base_role, footprint
    by = {}
    for p in layout.placements:
        by.setdefault(base_role(p.role), p)
    sofa = by.get("диван")
    bearer = by.get("тв-тумба") or by.get("стенка")
    if sofa is None or bearer is None or sofa.item is None or bearer.item is None:
        return layout
    if bearer.role in LOCKED:
        return layout        # носитель поставлен медиа-блоком
    import math
    r = math.radians(sofa.rot)
    fx, fy = math.sin(r), math.cos(r)
    dx, dy = bearer.x - sofa.x, bearer.y - sofa.y
    lat = dx * (-fy) + dy * fx
    act = (sofa.item.corner_section_cm / 2) if sofa.item.corner else 0.0
    if abs(lat - act) < 8:
        return layout
    from .validate import validate
    # T3-фикс (10.08, set37): «hard не больше ЧИСЛОМ» позволял ОБМЕН нарушений —
    # снап тумбы вносил RADIATOR вместо ушедшего другого hard. Правило как в refine:
    # никаких НОВЫХ видов hard (по коду+ролям); базу считаем честным пересчётом.
    old_set = {(v.code, tuple(v.roles)) for v in
               validate(room, layout.placements).violations if v.severity.name == "HARD"}
    # полный сдвиг может не влезть (стенка 360 в стене 490) — центрируем НАСКОЛЬКО влезает
    for frac in (1.0, 0.6, 0.35):
        sx = -(lat - act) * (-fy) * frac
        sy = -(lat - act) * fx * frac
        moved = [p if p is not bearer else p.model_copy(update={"x": p.x + sx, "y": p.y + sy})
                 for p in layout.placements]
        trial = validate(room, moved)
        new_set = {(v.code, tuple(v.roles)) for v in trial.violations
                   if v.severity.name == "HARD"}
        if new_set <= old_set:
            trial.unplaced = layout.unplaced
            trial.skipped_optional = layout.skipped_optional
            return trial
    return layout


def _snap_rug_anchor(room: Room, layout: Layout) -> Layout:
    """I2 (канон): ковёр снапится к якорю — центр по активной посадке, задний край под
    передние ножки (25–30 см), длинной стороной по фронту."""
    from .geometry import base_role, footprint
    by = {}
    for p in layout.placements:
        by.setdefault(base_role(p.role), p)
    sofa, rug = by.get("диван"), by.get("ковёр")
    if sofa is None or rug is None or sofa.item is None or rug.item is None:
        return layout
    if rug.role in LOCKED:
        return layout        # ковёр поставлен шаблоном — не трогаем
    import math
    r = math.radians(sofa.rot)
    fx, fy = math.sin(r), math.cos(r)
    act = (sofa.item.corner_section_cm / 2) if sofa.item.corner else 0.0
    rug_deep = min(rug.item.w_cm, rug.item.d_cm)
    rot0 = int(sofa.rot) % 180 if rug.item.w_cm >= rug.item.d_cm else (int(sofa.rot) + 90) % 180
    fwd_c = sofa.item.d_cm / 2 - 27 + rug_deep / 2
    nx = sofa.x + fx * fwd_c + (-fy) * act
    ny = sofa.y + fy * fwd_c + fx * act
    if abs(nx - rug.x) < 2 and abs(ny - rug.y) < 2 and int(rug.rot) % 180 == rot0:
        return layout
    moved = [p if p is not rug else p.model_copy(update={"x": nx, "y": ny, "rot": float(rot0)})
             for p in layout.placements]
    from .validate import validate
    trial = validate(room, moved)
    old_hard = sum(1 for v in layout.violations if v.severity.name == "HARD")
    if sum(1 for v in trial.violations if v.severity.name == "HARD") <= old_hard:
        trial.unplaced = layout.unplaced
        trial.skipped_optional = layout.skipped_optional
        return trial
    return layout


def _snap_table_center(room: Room, layout: Layout) -> Layout:
    """D2 (вердикты 08.08 «столики не всегда по центру»): пробуем поставить столик РОВНО в
    центр активной посадки; свободно и не хуже по hard — принимаем."""
    from .geometry import base_role, facing_vector, footprint
    by = {}
    for p in layout.placements:
        by.setdefault(base_role(p.role), p)
    sofa, tbl = by.get("диван"), by.get("столик")
    if sofa is None or tbl is None or sofa.item is None:
        return layout
    if tbl.role in LOCKED:
        return layout        # столик поставлен шаблоном
    import math
    r = math.radians(sofa.rot)
    fx, fy = math.sin(r), math.cos(r)
    act = (sofa.item.corner_section_cm / 2) if sofa.item.corner else 0.0
    dx, dy = tbl.x - sofa.x, tbl.y - sofa.y
    fwd = dx * fx + dy * fy
    nx = sofa.x + fx * fwd + (-fy) * act
    ny = sofa.y + fy * fwd + fx * act
    if abs(nx - tbl.x) < 2 and abs(ny - tbl.y) < 2:
        return layout
    moved = [p if p is not tbl else p.model_copy(update={"x": nx, "y": ny})
             for p in layout.placements]
    from .validate import validate
    trial = validate(room, moved)
    old_hard = sum(1 for v in layout.violations if v.severity.name == "HARD")
    if sum(1 for v in trial.violations if v.severity.name == "HARD") <= old_hard:
        trial.unplaced = layout.unplaced
        trial.skipped_optional = layout.skipped_optional
        return trial
    return layout


LOCKED: set[str] = set()   # роли-члены зонных БЛОКОВ: доводка их не трогает
                           # (правило владельца 11.08 «шаблоны нерушимы»): внутренняя
                           # геометрия блока уже параметрическая — отступы пересчитаны
                           # от фактических габаритов SKU, снапам там нечего улучшать.


def refine(room: Room, layout: Layout, *, rounds: int = MAX_ROUNDS) -> Layout:
    """Доводка раскладки: те же предметы, чуть другие координаты — меньше нарушений.

    Члены зонных блоков (`LOCKED`) пропускаются: их позиции заданы шаблоном."""
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
            if p.role in LOCKED:
                continue          # член блока — шаблон нерушим
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

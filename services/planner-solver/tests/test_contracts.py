"""Constraint-contract CI — T6 truth-first (рефери §16, обобщение уроков 203/204).

Урок, из которого вырос файл: пара CHAIR_ORPHAN (стул ≤40 см от стола) × ACCESS_BLOCKED
(<55 см — блокер) делала обеденную группу ГЕОМЕТРИЧЕСКИ НЕВОЗМОЖНОЙ, и никто не видел,
пока составы не потребовали стулья массово. Правила проверяются на СОВМЕСТНУЮ выполнимость,
а не поодиночке:

  A. pair-contract: «обязательная» позиция одного правила проходит валидатор целиком;
  B. group satisfiability: каждая посадочная группа собирается в канонической пустой
     комнате без hard (у неё существует хотя бы одна допустимая конфигурация);
  C. monotonicity: комната увеличилась, препятствий не добавилось → раскладка не должна
     стать невозможной;
  D. candidate smoke: каждый тип якоря отдаёт ≥1 кандидата в канонической комнате
     (мёртвый код-путь «якорь всегда бракуется» — урок 204);
  E. инвариант приставного: side-table НЕ ловит правила журнального столика
     (SOFA_TABLE_DIST/TABLE_OFF_AXIS привязаны к роли «столик») — ловушка рефери §7.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from planner.beam import solve                       # noqa: E402
from planner.candidates import generate, order_items  # noqa: E402
from planner.models import Item, Opening, Room, Severity    # noqa: E402
from planner.validate import validate                # noqa: E402
from planner.zones import solve_zoned, zone_rules    # noqa: E402

DIMS = {'диван': (220, 95, 85), 'диван 2': (160, 90, 85), 'кресло': (80, 85, 90),
        'кресло 2': (80, 85, 90), 'столик': (110, 60, 42), 'тв-тумба': (160, 42, 50),
        'стол обеденный': (140, 80, 75), 'стул': (45, 50, 90), 'стул 2': (45, 50, 90),
        'пуф': (60, 45, 40), 'торшер': (35, 35, 160), 'ковёр': (200, 140, 1),
        'приставной': (45, 40, 55), 'compact_sectional': (200, 150, 85)}


def canonical_room(w=520, d=460) -> Room:
    return Room(width_cm=w, depth_cm=d, band='21-25' if w * d / 1e4 <= 25 else '26-30',
                openings=[Opening(kind='door', wall='south', offset_cm=30, width_cm=90,
                                  swing_cm=92)])


def mk(role: str) -> Item:
    w, d, h = DIMS.get(role.split(' ')[0] if role not in DIMS else role, (60, 60, 60))
    return Item(role=role, w_cm=w, d_cm=d, h_cm=h)


def hard_codes(layout) -> list[str]:
    return [v.code for v in layout.violations if v.severity is Severity.HARD]


# ---------------------------------------------------------------- A. pair-contract

def test_pair_chair_at_table_passes_full_validator():
    """Стул в «обязательной» позиции CHAIR_ORPHAN (у кромки стола) проходит валидатор
    ЦЕЛИКОМ — допуски пары правил пересекаются (регресс урока 203)."""
    room = canonical_room()
    items = [mk('стол обеденный'), mk('стул'), mk('стул 2')]
    layouts = solve(room, items, top_k=1)
    assert layouts, 'обеденная группа не решилась вовсе'
    lay = layouts[0]
    placed = {p.role.split(' ')[0] for p in lay.placements}
    if 'стол' in ' '.join(placed):
        assert not hard_codes(lay), f'обеденная группа даёт hard: {hard_codes(lay)}'


def test_pair_sofa_table_gap_passes():
    """Столик в комфортной вилке 36–46 от дивана не ловит ни одного hard."""
    room = canonical_room()
    layouts = solve(room, [mk('диван'), mk('тв-тумба'), mk('столик')], top_k=1)
    assert layouts and not hard_codes(layouts[0]), \
        f'база диван+ТВ+столик даёт hard: {hard_codes(layouts[0]) if layouts else "нет решения"}'


# ---------------------------------------------------------------- B. group satisfiability

def test_every_seating_group_satisfiable():
    """Каждая посадочная группа из zones.json собирается в канонической пустой комнате.
    Невыполнимая группа = сет заявляет то, что солвер не может поставить никогда."""
    zr = zone_rules()
    losers = []
    for g in zr['seating_groups']:
        need_m2 = g['footprint_m2']
        side = max(520, int((need_m2 * 2.6) ** 0.5 * 100))
        room = canonical_room(side, side)
        roles = [r for r in g['roles']['required']]
        items = [mk(r) for r in roles] + [mk('тв-тумба')]
        try:
            layouts, picked = solve_zoned(room, items)
        except Exception as e:  # noqa: BLE001
            losers.append(f"{g['id']}: CRASH {e}")
            continue
        if not layouts:
            losers.append(f"{g['id']}: нет решения")
            continue
        lay = layouts[0]
        req_missing = [r for r in lay.unplaced or []]
        if req_missing or hard_codes(lay):
            losers.append(f"{g['id']}: unplaced={req_missing} hard={hard_codes(lay)}")
    assert not losers, 'невыполнимые группы: ' + '; '.join(losers)


# ---------------------------------------------------------------- C. monotonicity

def test_bigger_room_does_not_break():
    """Комната больше, препятствий не прибавилось → решаемость не должна пропасть."""
    items = [mk('диван'), mk('тв-тумба'), mk('столик'), mk('кресло')]
    small = canonical_room(460, 420)
    big = canonical_room(640, 560)
    l_small = solve(small, [Item(**i.model_dump()) for i in items], top_k=1)
    l_big = solve(big, [Item(**i.model_dump()) for i in items], top_k=1)
    if l_small and not hard_codes(l_small[0]):
        assert l_big and not hard_codes(l_big[0]), \
            'малая комната решается, большая — нет (масштабное правило ломает monotonicity)'


# ---------------------------------------------------------------- D. candidate smoke

def test_each_role_has_candidates():
    """Каждый предмет типового состава получает ≥1 позицию-кандидата в канонической
    комнате (урок 204: якорь, который никогда не проходит фильтр, — мёртвый код-путь)."""
    room = canonical_room()
    items = [mk('диван'), mk('тв-тумба'), mk('столик'), mk('кресло'), mk('пуф'),
             mk('торшер'), mk('стол обеденный'), mk('стул')]
    placed = []
    empty = []
    for it in order_items(items):
        cands = generate(room, it, placed)
        if not cands:
            empty.append(it.role)
        else:
            placed.append(cands[0].placement)
    assert not empty, f'роли без единого кандидата: {empty}'


# ---------------------------------------------------------------- E. приставной ≠ столик

def test_side_table_not_caught_by_coffee_table_rules():
    """Ловушка рефери §7: приставной у кресла НЕ должен ловить SOFA_TABLE_DIST /
    TABLE_OFF_AXIS (они привязаны к роли «столик»). Smoke-инвариант против рефакторинга,
    который схлопнет приставной в столик через base_role."""
    room = canonical_room()
    layouts = solve(room, [mk('диван'), mk('тв-тумба'), mk('столик')], top_k=1)
    assert layouts and layouts[0].placements
    lay = layouts[0]
    side = mk('приставной')
    from planner.models import Placement
    sofa = next(p for p in lay.placements if p.role == 'диван')
    ps = list(lay.placements) + [Placement(role='приставной', x=min(sofa.x + 150, room.width_cm - 40),
                                           y=sofa.y, rot=0, item=side)]
    codes = [v.code for v in validate(room, ps).violations]
    bad = [c for c in ('SOFA_TABLE_DIST', 'TABLE_OFF_AXIS', 'TABLE_BEHIND_SOFA')
           if c in codes and 'приставной' in str([v.roles for v in validate(room, ps).violations
                                                  if v.code == c])]
    assert not bad, f'приставной пойман правилами столика: {bad}'

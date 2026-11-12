"""V4-B свода №10 (MASTER-zones-v4): выбор посадочных шаблонов.

Сторожа: band — верхний кап + предпочтение, НЕ жёсткий whitelist (Q37);
sofa_armchair пробуется ДО sofa_pouf в любой комнате при полном инвентаре;
seating_search-трейс объясняет каждую победу sofa_pouf при кресле в банке;
№210 (set105-pylons) — позитивный large-room регресс.
"""
import glob
import json
import os

from planner.models import Item, Opening, Room
from planner.zones import pick_ladder

# данные экзамена — tools/scout этой копии или env EXAM_SCOUT_DIR (прогон из worktree по данным основной копии, T-94)
SCOUT = os.environ.get('EXAM_SCOUT_DIR') or os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


def _big_room():
    return Room(width_cm=700, depth_cm=650)     # usable ≫ 30 м² (band max999)


def test_armchair_reachable_in_large_room():
    """Q37: одно кресло в большой комнате — sofa_armchair в лестнице ДО sofa_pouf."""
    ladder = [g['id'] for g in pick_ladder(_big_room(),
                                           {'диван': 1, 'кресло': 1, 'пуф': 1})]
    assert 'sofa_armchair' in ladder, ladder
    assert ladder.index('sofa_armchair') < ladder.index('sofa_pouf'), ladder


def test_band_still_caps_rich_groups():
    """Кап сверху остаётся: в крошечной комнате богатые группы недоступны."""
    tiny = Room(width_cm=280, depth_cm=280)
    ladder = [g['id'] for g in pick_ladder(
        tiny, {'диван': 2, 'кресло': 2, 'пуф': 1})]
    assert 'two_sofas_2armchairs' not in ladder, ladder


def test_diag_covers_all_ladder_steps():
    diag = []
    pick_ladder(_big_room(), {'диван': 1, 'кресло': 1}, diag=diag)
    ids = {d['id'] for d in diag}
    assert {'sofa_armchair', 'sofa_pouf', 'sofa_2armchairs'} <= ids
    arm = next(d for d in diag if d['id'] == 'sofa_armchair')
    assert arm['inventory_complete'] and arm['eligible']
    two = next(d for d in diag if d['id'] == 'sofa_2armchairs')
    assert not two['inventory_complete']     # одно кресло — состав неполон


def _room_210():
    """Комната №210 (set105-pylons): контур с пилоном 775×595 (46 м²), проёмы и радиатор — как в артефакте экзамена 12.11."""
    from planner.models import Radiator
    return Room(width_cm=775, depth_cm=595,
                contour=[(0, 0), (775, 0), (775, 260), (720, 260), (720, 335), (775, 335), (775, 595), (0, 595)],
                openings=[Opening(kind='door', wall='south', offset_cm=432, width_cm=90, swing_cm=92),
                          Opening(kind='window', wall='east', offset_cm=303, width_cm=156, sill_cm=80)],
                radiators=[Radiator(wall='east', offset_cm=303, width_cm=156, depth_cm=15)])


def test_positive_regression_210_sofa_2armchairs():
    """B4: №210 — прямой диван + 2 кресла в 46 м² (референс владельца) → `sofa_2armchairs`, оба кресла в плане.

    T-20261112-94: раньше тест читал живой отчёт, а сет 105 банк меняет сам — 15.08 прямой диван + 2 кресла, 26.08 угловой
    Берлин 237×158 + 4 кресла (`two_sofas_2armchairs`), 12.11 модульный угловой Этен 268×165 (`sectional_armchair` — по
    приоритету носителя ТВ, `planner/zones.py` media_min). Ожидание референса — про правило выбора посадки, поэтому предметы
    закреплены здесь, а не берутся из банка: тест краснеет от поломки выбора, а не от смены товара."""
    from planner.zones import solve_zoned_beam
    items = [Item(role='диван', w_cm=230, d_cm=95), Item(role='кресло', w_cm=80, d_cm=90),
             Item(role='кресло 2', w_cm=80, d_cm=90), Item(role='тв-тумба', w_cm=160, d_cm=45),
             Item(role='столик', w_cm=110, d_cm=60), Item(role='ковёр', w_cm=240, d_cm=170),
             Item(role='торшер', w_cm=30, d_cm=30)]
    outs, gid = solve_zoned_beam(_room_210(), items, top_k=1)
    assert outs and gid.startswith('sofa_2armchairs'), gid
    roles = {p.role for p in outs[0].placements}
    assert {'кресло', 'кресло 2', 'тв-тумба'} <= roles, roles


def test_live_210_seating_explained():
    """Живой №210 (банк меняется): победила не `sofa_2armchairs` — трасса `_seating_search` обязана объяснить почему
    (состав неполон / не прошла hard / носитель ТВ хуже победителя). Тихая потеря богатой посадки — поломка."""
    rep = os.path.join(SCOUT, 'acceptance-report-zoned.jsonl')
    art_p = os.path.join(SCOUT, 'v3set105-layout-acc-zoned-set105-pylons.json')
    if not (os.path.exists(rep) and os.path.exists(art_p)):
        import pytest
        pytest.skip('нет отчёта приёмки или артефакта set105-pylons')
    row = next((json.loads(l) for l in open(rep, encoding='utf-8') if l.strip() and '"set105-pylons"' in l), None)
    if row is None or (row.get('templates') or '').startswith('sofa_2armchairs'):
        return
    ss = json.load(open(art_p, encoding='utf-8')).get('_seating_search') or {}
    two = ss.get('sofa_2armchairs')
    win = next((v for v in ss.values() if v.get('winner')), None)
    assert two is not None and win is not None, f"нет трассы выбора посадки: {row.get('templates')}"
    explained = (not two.get('inventory_complete') or not two.get('generated') or not two.get('hard_valid')
                 or (two.get('media_min') or 0) < (win.get('media_min') or 0))
    assert explained, f"sofa_2armchairs проиграла без причины в трассе: {two} против победителя {win}"


def test_pouf_wins_are_explained():
    """B3: sofa_pouf при кресле в банке — только с трейсом, объясняющим, почему
    более богатая ступень не победила (запись о sofa_armchair обязана быть)."""
    arts = glob.glob(os.path.join(SCOUT, 'v3set*-layout-acc-zoned-*.json'))
    if not arts:
        import pytest
        pytest.skip('нет артефактов экзамена')
    unexplained = []
    for f in arts:
        art = json.load(open(f, encoding='utf-8'))
        ss = art.get('_seating_search')
        if ss is None:
            continue                          # артефакт до V4-B — не судим
        win = next((k for k, v in ss.items() if v.get('winner')), None)
        if win != 'sofa_pouf':
            continue
        arm = ss.get('sofa_armchair')
        # жертва ступени ради столовой (+sacrN) — законное объяснение: sacrifice
        # перепрыгивает верх лестницы по правилу владельца (ADR-0097)
        sacr = (art.get('_dining') or {}).get('sacrifice_step')
        if sacr:
            continue
        if arm is None or (arm.get('eligible') and not arm.get('generated')):
            unexplained.append(os.path.basename(f))
    assert not unexplained, f'необъяснимые победы sofa_pouf: {unexplained[:6]}'

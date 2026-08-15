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

SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


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


def test_positive_regression_210_sofa_2armchairs():
    """B4: №210 (set105-pylons) — диван + 2 кресла в 46 м² (референс владельца)."""
    rep = os.path.join(SCOUT, 'acceptance-report-zoned.jsonl')
    if not os.path.exists(rep):
        import pytest
        pytest.skip('нет отчёта приёмки')
    row = next((json.loads(l) for l in open(rep, encoding='utf-8')
                if json.loads(l)['scene'] == 'set105-pylons'), None)
    if row is None:
        import pytest
        pytest.skip('сцены set105-pylons нет в отчёте')
    assert (row.get('templates') or '').startswith('sofa_2armchairs'), row['templates']


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

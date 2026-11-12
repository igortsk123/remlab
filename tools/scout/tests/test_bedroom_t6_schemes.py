"""Тесты перевода результата движка спальни в предметы схемы (tools/scout/bedroom_t6_schemes.py, T-20261112-62)."""
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(ROOT / 'services' / 'planner-solver'))

pytest.importorskip('PIL')
import bedroom_t6_schemes as t6  # noqa: E402

ROOM = {'W': 400.0, 'D': 300.0}


@pytest.mark.parametrize('rot,wall', [(0, 'south'), (90, 'west'), (180, 'north'), (270, 'east'), (360, 'south'),
                                      (-90, 'east'), (89.6, 'west')])
def test_back_wall_by_rotation(rot, wall):
    assert t6.back_wall(rot) == wall


def test_to_item_wall_offset_gap_and_zones():
    sku = {'w': 120.0, 'd': 60.0, 'h': 200.0, 'name': 'шкаф'}
    # шкаф спиной к восточной стене с зазором 5 см: след x 335..395, y 40..160
    it = t6.to_item(ROOM, 'шкаф', sku, (335.0, 40.0, 395.0, 160.0), 270)
    assert it['kind'] == 'wardrobe' and it['wall'] == 'east'
    assert it['off'] == 40.0 and it['gap_wall'] == pytest.approx(5.0)
    z = it['zones'][0]
    assert z['code'] == 'WARDROBE_FRONT'
    assert z['rect'] == pytest.approx((335.0 - t6.bs.WARD, 40.0, 335.0, 160.0))   # зона — от фасада, не от стены


def test_to_item_bed_side_and_foot_zones():
    sku = {'w': 160.0, 'd': 200.0, 'h': 100.0, 'name': 'кровать'}
    it = t6.to_item(ROOM, 'кровать', sku, (120.0, 100.0, 280.0, 300.0), 180, 'pair')   # изголовьем к северу
    assert it['wall'] == 'north' and it['off'] == 120.0 and it['gap_wall'] == 0.0
    assert it['foot_zone'] == pytest.approx((120.0, 100.0 - t6.bs.FOOT, 280.0, 100.0))
    assert it['side_zone']['lo'] == pytest.approx((120.0 - t6.bs.SIDE, 100.0, 120.0, 300.0))
    assert it['gap'] == {'lo': 120.0, 'hi': 120.0}


def test_moved_matches_twin_items_by_place():
    def ns(x):
        return {'role': 'тумба', 'kind': 'ns', 'wall': 'south', 'rect': (x, 0, x + 40, 40)}
    a = [dict(ns(10), role='тумба'), dict(ns(300), role='тумба 2')]
    b = [dict(ns(300), role='тумба'), dict(ns(20), role='тумба 2')]   # движок поменял имена местами и сдвинул одну
    assert t6.moved(a, b) == ['тумба: +10 см вдоль стены']
    assert t6.moved(a, b[:1]) == ['тумба — убран']

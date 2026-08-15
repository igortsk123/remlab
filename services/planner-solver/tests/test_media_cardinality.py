"""V3-A свода №9 (MASTER-zones-v3): кардинальность media — ровно один носитель.

P0 план №269: тумба и стенка стояли одновременно (вейвер лестницы + добор цепочки).
Сторожа: (1) данные cardinality объявлены; (2) по последнему экзамену ни в одном
артефакте нет двух носителей.
"""
import glob
import json
import os

RULES = os.path.join(os.path.dirname(__file__), '..', 'rules', 'zones.json')
SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


def test_cardinality_declared():
    card = json.load(open(RULES, encoding='utf-8'))['zone_priority']['cardinality']
    assert card['media']['rule'] == 'at_most_one_carrier'
    assert set(card['media']['carrier_roles']) == {'тв-тумба', 'стенка'}


def test_no_plan_has_two_carriers():
    arts = glob.glob(os.path.join(SCOUT, 'v3set*-layout-acc-zoned-*.json'))
    if not arts:
        import pytest
        pytest.skip('нет артефактов экзамена')
    bad = []
    for f in arts:
        art = json.load(open(f, encoding='utf-8'))
        carriers = [r for r in art
                    if isinstance(art.get(r), dict) and r.split(' ')[0] in
                    ('тв-тумба', 'стенка')]
        if len(carriers) > 1:
            bad.append((os.path.basename(f), carriers))
    assert not bad, f'два носителя media в планах: {bad}'


def test_validator_fires_on_double_carrier():
    from planner.models import Item, Placement, Room
    from planner.validate import validate
    room = Room(width_cm=500, depth_cm=500)
    ps = [Placement(role='тв-тумба', x=250, y=20, rot=0,
                    item=Item(role='тв-тумба', w_cm=140, d_cm=40, h_cm=50)),
          Placement(role='стенка', x=250, y=480, rot=180,
                    item=Item(role='стенка', w_cm=280, d_cm=50, h_cm=200))]
    codes = {v.code for v in validate(room, ps).violations}
    assert 'MEDIA_DOUBLE_CARRIER' in codes


def test_validator_semantic_incl_tandem_carrier():
    """Поправка рефери: носитель считается СЕМАНТИЧЕСКИ (по ролям размещений),
    включая carrier, поставленный составной схемой +tvfp (медиа+камин). Камин
    носителем не является и в кардинальность не входит."""
    from planner.models import Item, Placement, Room
    from planner.validate import validate
    room = Room(width_cm=500, depth_cm=500)
    tandem = [Placement(role='стенка', x=250, y=480, rot=180,
                        item=Item(role='стенка', w_cm=280, d_cm=50, h_cm=200)),
              Placement(role='камин', x=60, y=480, rot=180,
                        item=Item(role='камин', w_cm=120, d_cm=42, h_cm=110))]
    # стенка из тандема + камин: ОДИН носитель — чисто
    assert not any(v.code == 'MEDIA_DOUBLE_CARRIER'
                   for v in validate(room, tandem).violations)
    # + standalone тумба к тандему: двойной носитель — hard
    extra = tandem + [Placement(role='тв-тумба', x=250, y=20, rot=0,
                                item=Item(role='тв-тумба', w_cm=140, d_cm=40, h_cm=50))]
    assert any(v.code == 'MEDIA_DOUBLE_CARRIER'
               for v in validate(room, extra).violations)

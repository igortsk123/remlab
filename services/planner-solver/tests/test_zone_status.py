"""Пакет F свода №8 (MASTER-zones-v2): статусы зон — данные, не хардкод.

Сторожа: каждый элемент zone_priority.order имеет статус; все теги цепочки
замаплены; required-семантика читается из данных.
"""
import json
import os

RULES = os.path.join(os.path.dirname(__file__), '..', 'rules', 'zones.json')


def _zp():
    return json.load(open(RULES, encoding='utf-8'))['zone_priority']


def test_every_zone_has_status():
    zp = _zp()
    st = zp['status']
    assert set(st) == set(zp['order']), 'статус обязан покрывать все зоны order'
    assert set(st.values()) <= {'required', 'preferred', 'optional'}


def test_every_chain_tag_mapped():
    zp = _zp()
    for tag, zone in zp['tags'].items():
        assert zone in zp['order'], f'{tag} → {zone} вне order'
    # теги вейвера и второго прохода не забыты
    for t in ('+tvw', '+st2', '+dc2', '+rd2'):
        assert t in zp['tags'], f'тег {t} не замаплен'


def test_core_zones_required_dining_preferred():
    st = _zp()['status']
    assert st['media'] == 'required' and st['seating'] == 'required'
    assert st['dining'] == 'preferred'
    assert st['decor'] == 'optional'

"""P3 свода №12: паспорта = runtime.

- каждая схема зоны в templates.json имеет статус implemented_as:… или sleeping:…;
- формы посадки (shapes) — в паспорте zones.json, код читает их оттуда; 'u' у sofa_2armchairs;
- media_installation: паспорт с params и реализация в коде;
- template_gaps репортит спящие паспорта (отчёт «0 gaps» больше не молчит).
"""
import json
import os

RULES = os.path.join(os.path.dirname(__file__), '..', 'rules')
PLANNER = os.path.join(os.path.dirname(__file__), '..', 'planner')
SCOUT = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tools', 'scout')


def _tpl():
    return json.load(open(os.path.join(RULES, 'templates.json'), encoding='utf-8'))


def test_every_scheme_has_status():
    bad = []
    for zname, z in _tpl()['zones'].items():
        for s in z.get('schemes') or []:
            st = str(s.get('status', ''))
            if not (st.startswith('implemented') or st.startswith('sleeping')):
                bad.append(f'{zname}/{s["id"]}')
    assert not bad, f'схемы без статуса implemented_as/sleeping: {bad}'


def test_shapes_live_in_passport_and_u_for_two_armchairs():
    z = json.load(open(os.path.join(RULES, 'zones.json'), encoding='utf-8'))
    groups = {g['id']: g for g in z['seating_groups']}
    assert 'u' in groups['sofa_2armchairs'].get('shapes', []), 'u для sofa_2armchairs (владелец №192)'
    assert 'u' in groups['sofa_4armchairs'].get('shapes', [])
    src = open(os.path.join(PLANNER, 'template.py'), encoding='utf-8').read()
    assert "shapes = {'sofa_4armchairs'" not in src, 'словарь форм в коде — вторая истина'
    assert "g.get('shapes')" in src


def test_media_installation_passport_and_code():
    schemes = {s['id']: s for s in _tpl()['zones']['media']['schemes']}
    mi = schemes['media_installation']
    p = mi['params']
    assert p['wall_min_cm'] >= 400 and p['gap_cm'] > 0 and p['max_companions'] >= 1
    src = open(os.path.join(PLANNER, 'template.py'), encoding='utf-8').read()
    assert 'def build_media_installation' in src and 'def place_media_installation' in src
    assert 'place_media_installation(room, items, free, fixed=fixed)' in src, \
        'инсталляция — альтернатива внутри place_media (лексо-сравнение с одиночным носителем)'


def test_gaps_report_includes_sleeping():
    src = open(os.path.join(SCOUT, 'template_gaps.py'), encoding='utf-8').read()
    assert 'PASSPORT_SLEEPING' in src


def test_build_media_installation_geometry():
    from planner.models import Item
    from planner.template import build_media_installation
    by = {'стенка': Item(role='стенка', w_cm=240, d_cm=45, h_cm=180),
          'витрина': Item(role='витрина', w_cm=80, d_cm=40, h_cm=190),
          'комод': Item(role='комод', w_cm=100, d_cm=45, h_cm=85)}
    params = {'wall_min_cm': 520, 'gap_cm': 40, 'max_companions': 2,
              'companion_roles': ['витрина', 'стеллаж', 'комод']}
    b = build_media_installation(by, 780, params)
    assert b is not None and len(b.rel) == 3
    assert build_media_installation(by, 400, params) is None, 'короткая стена — инсталляции нет'

"""Правки комнат агента поверх прочитанного плана (`tools/floorplan/room_edits.py`, T-20261110-36): поиск комнаты, масштаб, канон цел."""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import room_edits as RE  # noqa: E402


def _res():
    def room(i, kind, x, y, w, d):
        return {'id': i, 'kind': kind, 'name': i.upper(), 'flags': ['dims_mismatch'] if i == 'b' else [], 'areaM2': w * d / 1e4,
                'bbox': {'x': x, 'y': y, 'w': w, 'd': d}, 'contour': [[x, y], [x + w, y], [x + w, y + d], [x, y + d]]}
    return {'panels': [{'id': 'p0', 'rooms': [room('a', 'living', 0, 0, 500, 400), room('b', 'bedroom', 500, 0, 300, 400)]},
                       {'id': 'p1', 'rooms': [room('a', 'bedroom', 0, 0, 400, 400)]}]}


def _e(src, panel='p0', w=None, d=None, name='', kind='', anchor=(0.5, 0.5), built=False):
    return {'panel': panel, 'srcId': src, 'anchor': {'x': anchor[0], 'y': anchor[1]}, 'name': name, 'kind': kind, 'wCm': w, 'dCm': d,
            'built': built}


def test_scale_about_centre_keeps_original_and_canon_untouched():
    src = _res()
    keep = copy.deepcopy(src)
    res, done = RE.apply(src, [_e('b', w=360, d=320, name='Кабинет', kind='other')])
    assert src == keep and done and done[0][1:] == ('p0', 'b')
    b = res['panels'][0]['rooms'][1]
    assert b['bbox'] == {'x': 470.0, 'y': 40.0, 'w': 360.0, 'd': 320.0} and b['contour'][0] == [470.0, 40.0]
    assert b['plan']['bbox'] == {'x': 500, 'y': 0, 'w': 300, 'd': 400} and b['edited'] == {'w': 360, 'd': 320}
    assert b['areaM2'] == round(12.0 * 1.2 * 0.8, 2) and b['flags'] == ['dims_mismatch', 'user_dims']
    assert b['name'] == 'Кабинет' and b['user_name'] is True and b['kind'] == 'other'
    assert res['panels'][1]['rooms'][0]['bbox']['w'] == 400            # тот же id плана на другой панели — не тронут


def test_name_only_edit_keeps_geometry():
    res, done = RE.apply(_res(), [_e('a', name='Гостиная-столовая')])
    a = res['panels'][0]['rooms'][0]
    assert done and a['name'] == 'Гостиная-столовая' and 'plan' not in a and 'user_dims' not in a['flags'] and a['bbox']['w'] == 500


def test_anchor_match_uses_untouched_bboxes_and_one_room_per_edit():
    """id сменились: по центру в долях охвата панели. Первая правка растягивает гостиную — вторая всё равно ищется по прочитанным охватам."""
    edits = [_e('x1', w=700, d=500, anchor=(0.3125, 0.5)), _e('x2', w=280, d=380, anchor=(0.8125, 0.5)), _e('x3', anchor=(0.3, 0.5))]
    res, done = RE.apply(_res(), edits)
    assert [(p, r) for _, p, r in done] == [('p0', 'a'), ('p0', 'b')]  # третья — к уже занятой комнате не прикладывается
    assert RE.dirty_keys(done) == {('p0', 'a'), ('p0', 'b')}


def test_far_anchor_and_unknown_panel_skipped():
    res, done = RE.apply(_res(), [_e('zz', anchor=(0.5, 3.0)), _e('a', panel='p9', w=100, d=100)])
    assert done == [] and res == _res()


def test_built_edits_not_dirty():
    _, done = RE.apply(_res(), [_e('a', w=520, d=400, built=True), _e('b', w=320, d=400)])
    assert RE.dirty_keys(done) == {('p0', 'b')}

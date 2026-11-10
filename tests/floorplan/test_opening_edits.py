"""Окна и двери агента поверх прочитанного плана (`tools/floorplan/opening_edits.py`, T-20261110-39): снять, сдвинуть, добавить; поиск
распознанного после перечитывания; какие комнаты пересобрать; дверь агента даёт комнате вход (`trial_room.openings_of`)."""
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(0, str(ROOT / 'tools' / 'scout'))
import opening_edits as OE  # noqa: E402
import room_edits as RE  # noqa: E402


def _room(i, kind, x, y, w, d):
    return {'id': i, 'kind': kind, 'name': i.upper(), 'flags': [], 'areaM2': w * d / 1e4,
            'bbox': {'x': x, 'y': y, 'w': w, 'd': d}, 'contour': [[x, y], [x + w, y], [x + w, y + d], [x, y + d]]}


def _res():
    # a (0..500) | b (510..810): перегородка 10 см на x 500..510; окно a — на верхней стене, дверь a–b — на перегородке
    return {'panels': [{'id': 'p0', 'rooms': [_room('a', 'living', 0, 0, 500, 400), _room('b', 'bedroom', 510, 0, 300, 400)],
                        'walls': [],
                        'openings': [{'kind': 'window', 'c': [250.0, 0.0], 'widthCm': 150.0, 'exterior': True},
                                     {'kind': 'door', 'c': [505.0, 200.0], 'widthCm': 80.0, 'exterior': False}]},
                       {'id': 'p1', 'rooms': [_room('c', 'bedroom', 0, 0, 400, 400)], 'walls': [], 'openings': []}]}


def _op(key, kind='door', c=(0, 0), w=80, removed=False, panel='p0', src_c=None, built=False):
    return {'panel': panel, 'key': key, 'srcIdx': int(key[1:]) if key[0] == 's' else None, 'srcC': list(src_c) if src_c else None,
            'kind': kind, 'c': list(c), 'widthCm': w, 'removed': removed, 'built': built}


def test_remove_recognized_door_dirty_both_sides_canon_untouched():
    src = _res()
    keep = copy.deepcopy(src)
    res, done = OE.apply(src, [_op('s1', removed=True, src_c=(505, 200))])
    assert src == keep
    ops = res['panels'][0]['openings']
    assert [o['key'] for o in ops] == ['s0'] and ops[0]['kind'] == 'window'
    assert OE.dirty_rooms(res, done) == {('p0', 'a'), ('p0', 'b')}
    assert res['panels'][1]['openings'] == []


def test_move_and_widen_recognized_keeps_key_and_source_centre():
    res, done = OE.apply(_res(), [_op('s0', kind='window', c=(120, 0), w=200, src_c=(250, 0))])
    o = res['panels'][0]['openings'][0]
    assert o['key'] == 's0' and o['c'] == [120.0, 0.0] and o['widthCm'] == 200.0 and o['user'] is True and o['srcC'] == [250.0, 0.0]
    assert o['exterior'] is True
    assert OE.dirty_rooms(res, done) == {('p0', 'a')}             # окно наружной стены гостиной — спальню не трогаем


def test_added_door_between_rooms_is_interior_added_window_exterior():
    res, done = OE.apply(_res(), [_op('uAAAAAA1', kind='door', c=(500, 330), w=90),
                                  _op('uAAAAAA2', kind='window', c=(810, 200), w=120)])
    added = {o['key']: o for o in res['panels'][0]['openings'] if o['key'][0] == 'u'}
    assert added['uAAAAAA1']['exterior'] is False and added['uAAAAAA2']['exterior'] is True
    assert OE.dirty_rooms(res, done) == {('p0', 'a'), ('p0', 'b')}


def test_added_door_inside_overlapping_neighbour_is_interior():
    src = _res()
    src['panels'][0]['rooms'].append(_room('e', 'bathroom', 100, 340, 200, 200))   # санузел наехал на гостиную: её стена y=400 внутри него
    res, _ = OE.apply(src, [_op('uDDDDDD1', kind='door', c=(150, 400), w=80)])
    assert [o['exterior'] for o in res['panels'][0]['openings'] if o['key'] == 'uDDDDDD1'] == [False]


def test_reread_shifted_index_found_by_centre_far_one_skipped():
    src = _res()
    src['panels'][0]['openings'].insert(0, {'kind': 'window', 'c': [700.0, 400.0], 'widthCm': 100.0, 'exterior': True})
    res, done = OE.apply(src, [_op('s1', removed=True, src_c=(505, 200)),        # номер 1 теперь — окно; дверь — номер 2, найдена по центру
                               _op('s0', kind='door', c=(0, 0), src_c=(999, 999))])  # такого проёма нет — правка не ложится
    kinds = [o['kind'] for o in res['panels'][0]['openings']]
    assert kinds == ['window', 'window'] and len(done) == 1


def test_built_edits_do_not_dirty():
    res, done = OE.apply(_res(), [_op('s1', removed=True, src_c=(505, 200), built=True), _op('uBBBBBB1', c=(500, 50), removed=True, built=True)])
    assert len(res['panels'][0]['openings']) == 1 and OE.dirty_rooms(res, done) == set()


def test_removed_own_door_disappears_and_dirties_its_rooms():
    # своя дверь a–b опубликована, потом снята: в проёмах её нет, обе комнаты у неё — пересобрать (иначе no_match, мебель под дверь, e2e T-39/2)
    res, done = OE.apply(_res(), [_op('uBBBBBB1', c=(500, 330), removed=True)])
    assert [o['key'] for o in res['panels'][0]['openings']] == ['s0', 's1']
    assert OE.dirty_rooms(res, done) == {('p0', 'a'), ('p0', 'b')}


def test_added_door_gives_room_an_entry_after_room_resize():
    import trial_room as TR
    src = _res()
    src['panels'][0]['openings'] = [o for o in src['panels'][0]['openings'] if o['kind'] == 'window']   # спальня b — без двери
    pan0 = src['panels'][0]
    cfg = TR.rules()
    assert not [o for o in TR.openings_of(pan0, pan0['rooms'][1], cfg)[0] if o['kind'] == 'door']
    # размер спальни правлен (контур масштабирован), дверь ставится на ИСХОДНУЮ стену — привязка по исходным контурам
    res, _ = RE.apply(src, [{'panel': 'p0', 'srcId': 'b', 'anchor': {'x': 0.8, 'y': 0.5}, 'name': '', 'kind': '', 'wCm': 360, 'dCm': 400,
                             'built': False}])
    res, done = OE.apply(res, [_op('uCCCCCC1', kind='door', c=(510, 300), w=80)])
    pan = res['panels'][0]
    ours = TR.openings_of(pan, pan['rooms'][1], cfg)[0]
    assert [o['kind'] for o in ours if o['kind'] == 'door'] == ['door']

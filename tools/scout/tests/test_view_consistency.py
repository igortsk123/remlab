"""АБЗАЦ СОГЛАСОВАННОСТИ ВИДОВ (`tools/scout/view_consistency.py`, T-20261117-03): по синтетическим комнатам (без реальных ID) — какие стены и проёмы видит
камера, окно вне обоих кадров, картины на стене спинки, камера спиной к окну, полнота данных; сторона «вправо» — как у настоящей камеры рендера.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_view_consistency.py -q"""
import math
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))

import draft_render as DR  # noqa: E402
import view_consistency as VC  # noqa: E402


def room(**over):
    r = {'w': 400, 'd': 300, 'kind': 'bedroom',
         'openings': [{'kind': 'window', 'wall': 'north', 'offset_cm': 100, 'width_cm': 150}, {'kind': 'door', 'wall': 'south', 'offset_cm': 150, 'width_cm': 90}]}
    r.update(over)
    return r


def order(c1, c2, **over):
    pl = {'room': room(), 'cams': [dict(name='C1', fov=90, **c1), dict(name='C2', fov=90, **c2)],
          'items': [{'role': 'кровать', 'x': 200, 'y': 250, 'rot': 180, 'w': 180, 'd': 210}],
          'decor': [{'role': 'картина', 'sku': {'name': 'Картина'}}, {'role': 'картина 2', 'sku': {'name': 'Картина 2'}}],
          'views': [{'camera': 'C1', 'id': 'a' * 64}, {'camera': 'C2', 'id': 'b' * 64}]}
    pl.update(over)
    return pl


# C1 смотрит на север (rot 180: взгляд (sin a, −cos a) = (0, 1)) на окно, C2 стоит у северной стены и смотрит на юг (rot 0) на дверь
FACE_WINDOW, FACE_DOOR = dict(x=200, y=20, rot=180), dict(x=200, y=280, rot=0)


def test_window_visible_ahead_and_door_behind_it():
    f = VC.facts(order(FACE_WINDOW, FACE_DOOR))
    v1, v2 = f['views']
    assert v1['facing'] == 'north' and v2['facing'] == 'south'
    win1 = next(o for o in v1['openings'] if o['kind'] == 'window')
    win2 = next(o for o in v2['openings'] if o['kind'] == 'window')
    door1 = next(o for o in v1['openings'] if o['kind'] == 'door')
    door2 = next(o for o in v2['openings'] if o['kind'] == 'door')
    assert win1['frac'] > 0.9 and win1['pos'] == 'centre'          # окно прямо перед камерой
    assert win2['frac'] == 0 and door1['frac'] == 0                # камера спиной к окну; дверь за спиной у первой
    assert door2['frac'] > 0.9
    text = VC.block(order(FACE_WINDOW, FACE_DOOR))
    assert 'window in the NORTH wall (whole, centre)' in text and 'seen in VIEW 1 only' in text
    assert 'door in the SOUTH wall' in text


def test_camera_with_back_to_the_window_does_not_see_it():
    # обе камеры смотрят на юг и на восток — окно на северной стене и дверь на южной: окно не видно НИ В ОДНОМ виде → «не рисовать»
    pl = order(dict(x=200, y=150, rot=90), dict(x=200, y=150, rot=45))
    pl['room'] = room(openings=[{'kind': 'window', 'wall': 'west', 'offset_cm': 60, 'width_cm': 150}])
    text = VC.block(pl)
    assert 'seen in NEITHER view — do NOT draw it' in text and text.count('NO window, door or opening is visible in this view') == 2
    assert 'draw none' in text


def test_right_hand_side_matches_the_renderer_camera():
    # правая рука камеры — как `Camera.basis()` рендера: (−fy, fx); окно справа в кадре — в «right part», слева — в «left part»
    for rot in (0, 90, 145, 200, 300):
        cam = DR.Camera(name='t', eye=(100.0, 120.0, 100.0), target=(100 + 400 * math.sin(math.radians(rot)), 120.0, 100 - 400 * math.cos(math.radians(rot))),
                        fov_deg=90.0, width=1344, height=896, shift_y=0.0)
        right = cam.basis()[2]                                     # (x, 0, z) плана: z = y
        pt = (100 + 50 * float(right[0]) + 120 * math.sin(math.radians(rot)), 100 + 50 * float(right[2]) - 120 * math.cos(math.radians(rot)))
        rel = VC._rel({'w': 10000, 'd': 10000}, {'x': 100, 'y': 100, 'rot': rot}, pt)
        assert 0 < rel < 90, (rot, rel)                            # точка справа от оси и впереди — угол положительный
    r = room(openings=[{'kind': 'window', 'wall': 'west', 'offset_cm': 200, 'width_cm': 80}])
    v = VC.facts(order(dict(x=200, y=20, rot=180), FACE_DOOR, room=r))['views'][0]
    assert v['openings'][0]['pos'] == 'right part'                 # лицом на север западная стена — справа


def test_wall_art_on_the_back_wall_of_the_bed():
    pl = order(FACE_WINDOW, FACE_DOOR)
    f = VC.facts(pl)
    assert (f['anchor'], f['art_wall']) == ('bed', 'north')        # спинка кровати (rot 180) — у северной стены
    text = VC.block(pl)
    assert 'hang ONLY on the NORTH wall above the bed' in text and 'VIEW 1' in text.split('WALL ART')[1]
    shown = order(FACE_WINDOW, FACE_DOOR, decor=[{'role': 'картина', 'shown': True, 'sku': {'name': 'К'}}])
    t2 = VC.block(shown)
    assert 'already drawn in IMAGE 1' in t2 and 'hang ONLY' not in t2          # нарисованные в 3D — место задал кадр
    assert 'WALL ART' not in VC.block(order(FACE_WINDOW, FACE_DOOR, decor=[]))  # картин нет — строки нет
    sofa = order(FACE_WINDOW, FACE_DOOR, items=[{'role': 'диван', 'x': 100, 'y': 40, 'rot': 0, 'w': 200, 'd': 90}])
    assert (VC.facts(sofa)['anchor'], VC.facts(sofa)['art_wall']) == ('sofa', 'south')


def test_incomplete_data_is_reported_not_guessed():
    assert VC.skip_reason(order(FACE_WINDOW, FACE_DOOR)) is None
    assert VC.skip_reason(order(FACE_WINDOW, FACE_DOOR, cams=[])) == 'нет камер C1 и C2'
    assert VC.skip_reason(order(FACE_WINDOW, FACE_DOOR, room={})) == 'нет размеров комнаты'
    assert VC.skip_reason(order(FACE_WINDOW, FACE_DOOR, room=room(openings=[]))) == 'нет проёмов комнаты'
    assert VC.skip_reason(order(FACE_WINDOW, FACE_DOOR, room=room(openings=[{'kind': 'window', 'wall': 'up', 'offset_cm': 1, 'width_cm': 2}]))) \
        == 'проём без стены или размера'
    bad = order(FACE_WINDOW, FACE_DOOR)
    bad['cams'][1].pop('x')
    assert 'поза камеры C2' in VC.skip_reason(bad)
    swapped = order(FACE_WINDOW, FACE_DOOR, views=[{'camera': 'C1', 'id': 'a' * 64}, {'camera': 'C3', 'id': 'b' * 64}])
    assert VC.skip_reason(swapped) == 'кадры не C1 и C2'
    other = order(FACE_WINDOW, FACE_DOOR, views=[{'camera': 'C1', 'id': 'a' * 64, 'room': '1x1|'}, {'camera': 'C2', 'id': 'b' * 64}])
    assert VC.skip_reason(other) == 'кадры другой комнаты'
    for p in (bad, swapped, other):
        assert VC.block(p) is None


def test_camera_outside_the_room_is_clamped_like_the_renderer():
    # как `cams_from_request`: точка зажимается внутрь на 3 см — взгляд из-за стены не должен ломать вычисление
    out = order(dict(x=-50, y=900, rot=180), FACE_DOOR)
    assert VC.block(out) is not None and VC.facts(out)['views'][0]['name'] == 'C1'


def test_insert_goes_before_output_and_geometry_sig_tracks_inputs():
    pl = order(FACE_WINDOW, FACE_DOOR)
    text = VC.block(pl)
    p = VC.insert('A\n\nRULES\n\nOUTPUT\n\nReturn ONE image.', text)
    assert p.index('VIEW CONSISTENCY') < p.index('\nOUTPUT') and p.endswith('Return ONE image.')
    assert VC.insert('no output paragraph', text).endswith(text)
    s = VC.geometry_sig(pl)
    assert s == VC.geometry_sig(order(FACE_WINDOW, FACE_DOOR, style='другой'))               # стиль не влияет
    assert s != VC.geometry_sig(order(dict(FACE_WINDOW, rot=170), FACE_DOOR))
    assert s != VC.geometry_sig(order(FACE_WINDOW, FACE_DOOR, room=room(w=410)))
    assert s != VC.geometry_sig(order(FACE_WINDOW, FACE_DOOR, items=[{'role': 'кровать', 'x': 210, 'y': 250, 'rot': 180, 'w': 180, 'd': 210}]))
    assert s != VC.geometry_sig(order(FACE_WINDOW, FACE_DOOR, decor=[{'role': 'картина', 'shown': True}]))


def test_no_scene_ids_in_the_module():
    src = open(os.path.join(HERE, '..', 'view_consistency.py'), encoding='utf-8').read()
    for bad in ('living-', 'bed1-', 'bed2-', 'bedroom-1', 'bedroom-2', 'set1', 'idx'):
        assert bad not in src, bad


def test_doorless_opening_is_a_known_kind():
    # реальные туры (13–17.11): у гостиной есть проём без двери — kind 'opening'; раньше абзац пропадал целиком («проём без стены или размера»)
    r = room(openings=[{'kind': 'window', 'wall': 'north', 'offset_cm': 100, 'width_cm': 150}, {'kind': 'opening', 'wall': 'south', 'offset_cm': 120, 'width_cm': 170}])
    pl = order(FACE_WINDOW, FACE_DOOR, room=r)
    assert VC.skip_reason(pl) is None
    text = VC.block(pl)
    assert 'doorless opening in the SOUTH wall' in text and 'The doorless opening (SOUTH wall, 170 cm wide)' in text
    assert VC.skip_reason(order(FACE_WINDOW, FACE_DOOR, room=room(openings=[{'kind': 'niche', 'wall': 'south', 'offset_cm': 1, 'width_cm': 2}]))) == 'проём без стены или размера'

"""Проба агента: данные страницы /demo под загруженный план (план agent-trial-08, задача А; T-20261109-21). Без сети и без банка:
контекст живого демо (правила, модель товара) подставлен, планы и сцены синтетические — по контракту `contracts/trial.ts:floorplanResult`
и формату `scene.json` из `trial_demo.py`.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_trial_bundle.py -q"""
import ast
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import trial_bundle as TB  # noqa: E402

CTX = {'rules': {'sofa_tv_cm': [180, 300]}, 'msid_of': lambda sid: f'm-{sid}', 'slot_band': lambda g: {'диван': {'min': g['w']}}}
JOB = 'AbCdEfGhIjKlMnOpQrStUv'
RECT = [(0, 0), (500, 0), (500, 400), (0, 400)]


def room(rid, kind, contour=RECT, name='', area=20.0):
    xs, ys = [p[0] for p in contour], [p[1] for p in contour]
    return {'id': rid, 'name': name or kind, 'kind': kind, 'contour': [list(p) for p in contour],
            'bbox': {'x': min(xs), 'y': min(ys), 'w': max(xs) - min(xs), 'd': max(ys) - min(ys)}, 'areaM2': area, 'flags': []}


def op(kind, c, w, exterior=False):
    return {'kind': kind, 'c': list(c), 'widthCm': w, 'exterior': exterior}


WINDOW = op('window', (250, 0), 120)
DOOR = op('door', (500, 200), 90)


def panel(pid, rooms, openings, title='Plan 1'):
    return {'id': pid, 'title': title, 'rooms': rooms, 'walls': [{'z0': 0, 'z1': 270, 'polys': []}], 'openings': openings}


def result(*panels, status='listing', flags=()):
    return {'version': 1, 'units': 'cm', 'source': {'mime': 'image/png', 'pages': 1, 'usedPages': 1, 'imageW': 1, 'imageH': 1},
            'scale': {'status': status, 'ppm': 50, 'inliers': 3, 'n': 3}, 'panels': list(panels), 'flags': list(flags),
            'timings': {}, 'costUsd': 0}


def simple(status='listing'):
    return result(panel('p0', [room('r1', 'living', name='Lounge')], [WINDOW, DOOR]), status=status)


def build(res, scene=None):
    return TB.build(JOB, res, scene, ctx=CTX)


def scene_for(res, status='ok', variants=None):
    """Сцена по формату `trial_demo.build`: ядро — вся комната, одна геометрия, ряд на стиль."""
    def row(role, x, y, w, d):
        return {'role': role, 'name': f'{role} A', 'mid': 1, 'eid': '2', 'sid': '1_2', 'price': 100, 'url': 'https://shop.example/a',
                'img': '//img.example/a.jpg', 'w': w, 'd': d, 'h': 80.0, 'x': x, 'y': y, 'rot': 90.0, 'corner': role == 'диван'}

    def var(style, n, failed=False, post_ok=True, hard=()):
        items = [] if failed else [row('диван', 250.0, 340.0, 200.0, 90.0), row('стул 2', 50.0, 50.0, 40.0, 40.0)]
        place = [{'role': r['role'], 'x': r['x'], 'y': r['y'], 'rot': 90.0, 'w': r['w'], 'd': r['d'], 'h': 80.0, 'elev': 0.0,
                  'corner': r['corner'], 'corner_left': r['role'] == 'диван', 'section': 95.0} for r in items]
        v = {'style': style, 'set_index': n, 'set_id': f's{n}', 'geometry': 0, 'items': items, 'absent_roles': ['ковёр'] if not failed else [],
             'hard': list(hard), 'post_ok': post_ok, 'problems': [] if post_ok else [{'code': 'route_blocked'}], 'placements': place,
             'placements_core': place}
        if failed:
            v['failed'] = True
        return v

    ops = [{'wall': 'south', 'offset_cm': 190.0, 'width_cm': 120.0, 'kind': 'window', 'sill_cm': 85, 'height_cm': 150},
           {'kind': 'door', 'wall': 'east', 'offset_cm': 155.0, 'width_cm': 90.0, 'swing_cm': 90, 'hinge': 'left', '_junction': None},
           {'kind': 'door', 'wall': 'north', 'offset_cm': 10.0, 'width_cm': 150.0, 'swing_cm': 0}]
    s = {'trial_id': JOB, 'status': status, 'flags': ['band_lowered'], 'problems': [],
         'room': {'id': 'r1', 'name': 'Lounge', 'kind': 'living', 'panel': 'p0'},
         'core': {'rect': [0, 0, 500, 400], 'w': 500.0, 'd': 400.0, 'area_m2': 20.0}, 'openings_core': ops,
         'geometries': [{'id': 'g0', 'openings_core': ops}],
         'variants': variants if variants is not None else [var('сканди', 7), var('лофт', 9, failed=True), var('минимализм', 11, post_ok=False)]}
    return s


def test_empty_room_is_explicitly_pending_not_ready():
    d = build(simple())
    assert list(d['rooms_geo']) == ['living']
    assert d['room'] is d['rooms_geo']['living']
    v = d['variants'][0]
    assert v['items'] == [] and v['pending'] is True and v['furniture_state'] == 'pending'
    assert v['id'] and v['room_id'] == 'living' and v['style'] == 'сканди' and v['style_id'] == 'scandi'
    assert v['room_size'] == {'w': 500, 'd': 400}
    assert d['trial']['job_id'] == JOB and d['trial']['furniture'] == 'pending'
    assert d['feeds'] == {} and d['rules']['sofa_tv_cm'] and d['apartment_rooms'][0]['contentState'] == 'ready'
    assert d['rooms_enabled'] == ['living']
    assert _outcomes(d)['living'] == ('pending', None, None)


def _outcomes(d):
    return {r['id']: (r['furniture_state'], r['furniture_code'], r['furniture_text']) for r in d['apartment_rooms']}


def test_room_outcome_every_room_ready_pending_or_refused_with_text():
    bath = [(600, 0), (800, 0), (800, 200), (600, 200)]
    def plan():
        return result(panel('p0', [room('r1', 'living', name='Lounge'), room('b1', 'bathroom', contour=bath, area=4)], [WINDOW, DOOR]))
    res = plan()
    empty = _outcomes(build(res))
    assert empty['living'] == ('pending', None, None)
    assert empty['bathroom-1'][:2] == ('refused', 'room_kind_not_furnished') and empty['bathroom-1'][2]
    assert _outcomes(build(res, scene_for(res)))['living'] == ('ready', None, None)
    failed = scene_for(res, status='refused')
    failed['refusal'] = {'code': 'living_core_small', 'detail': 'x'}
    state, code, text = _outcomes(build(res, failed))['living']
    assert (state, code) == ('refused', 'living_core_small') and 'мала' in text


def test_room_outcome_refused_when_no_variant_has_furniture():
    res = simple()
    scene = scene_for(res, variants=[])
    scene['variants'] = [{**scene_for(res)['variants'][1]}]             # единственный вариант — сбой
    state, code, text = _outcomes(build(res, scene))['living']
    assert (state, code) == ('refused', 'furniture_failed') and text


def test_openings_mapped_to_walls_and_radiators_never_invented():
    geo = build(simple())['rooms_geo']['living']
    by = {o['kind']: o for o in geo['openings']}
    assert by['window']['wall'] == 'south' and by['window']['offset_cm'] == 190 and by['window']['width_cm'] == 120
    assert by['door']['wall'] == 'east' and by['door']['offset_cm'] == 155 and by['door']['swing_cm'] == 90
    assert geo['radiators'] == []
    assert not any(k.startswith('_') for o in geo['openings'] for k in o)


def test_geometry_ignores_furniture_refusals():
    # масштаб не проверен, нет окна — адаптер отказал бы мебели, а комната есть
    d = build(simple(status='not_verified'))
    assert d['trial']['scale'] == 'not_verified' and d['variants'][0]['pending'] is True
    no_window = result(panel('p0', [room('r1', 'living')], [DOOR]))
    assert build(no_window)['variants'][0]['pending'] is True


def test_ambiguous_opening_is_refused_not_guessed():
    # проём между near и far — не наш и не соседа
    bad = result(panel('p0', [room('r1', 'living')], [WINDOW, DOOR, op('window', (250, -40), 80)]))
    with pytest.raises(TB.BundleRefused) as e:
        build(bad)
    assert e.value.code == 'opening_ambiguous'


def test_no_living_is_refused_with_reason():
    with pytest.raises(TB.BundleRefused) as e:
        build(result(panel('p0', [room('r1', 'bedroom')], [WINDOW, DOOR])))
    assert e.value.code == 'no_living'


def test_one_refused_living_stays_listed_other_goes_on():
    far = [(1000, 0), (1500, 0), (1500, 400), (1000, 400)]
    good = room('r2', 'living', far, area=20)
    bad = room('r1', 'living', RECT, area=30)
    res = result(panel('p0', [bad, good], [op('window', (250, -40), 80), op('window', (1250, 0), 120), op('door', (1500, 200), 90)]))
    d = build(res)
    assert list(d['rooms_geo']) == ['living']
    assert d['trial']['refused_rooms'][0]['room_id'] == 'living-2' and d['trial']['refused_rooms'][0]['code'] == 'opening_ambiguous'
    by = {r['id']: r for r in d['apartment_rooms']}
    assert by['living']['contentState'] == 'ready' and by['living-2']['contentState'] == 'soon'


def test_room_ids_unique_across_panels_and_kinds_keep_counters():
    p0 = panel('p0', [room('r1', 'living'), room('r2', 'bedroom')], [WINDOW, DOOR], title='Ground Floor')
    p1 = panel('p1', [room('r1', 'bedroom'), room('r2', 'living', area=10)], [WINDOW, DOOR], title='First Floor')
    d = build(result(p0, p1))
    ids = [r['id'] for r in d['apartment_rooms']]
    assert len(ids) == len(set(ids)) and set(ids) == {'living', 'living-2', 'bedroom-1', 'bedroom-2'}
    assert {v['room_id'] for v in d['variants']} == {'living', 'living-2'}
    assert len({v['id'] for v in d['variants']}) == 2
    by = {r['id']: r for r in d['apartment_rooms']}
    assert by['living']['storey'] == 0 and by['living-2']['storey'] == 1 and d['rooms_geo']['living-2']['storey'] == 1
    assert 'floor' not in d and 'floorsTotal' not in d and all('floor' not in r for r in d['apartment_rooms'])
    assert [p['storey'] for p in d['trial']['panels']] == [0, 1]
    assert {r['id'] for p in d['trial']['panels'] for r in p['rooms']} == set(ids)


@pytest.mark.parametrize('title,want', [
    ('Ground Floor', 0), ('GROUND FLOOR', 0), ('Lower Ground Floor', -1), ('Basement', -1), ('First Floor', 1), ('2nd Floor', 2),
    ('Floor 3', 3), ('Level 1', 1), ('2 этаж', 2), ('Второй этаж', 2), ('Plan 1', None), ('', None), (None, None),
    ('Ground and First Floor', None), ('First Floor Flat', 1),
])
def test_storey_title(title, want):
    assert TB.storey_of(title) == want


@pytest.mark.parametrize('titles', [('Plan 1', 'Plan 2'), ('Ground Floor', 'Plan 2'), ('Ground Floor', 'Ground Floor')])
def test_unconfirmed_storeys_are_not_published(titles):
    p0 = panel('p0', [room('r1', 'living')], [WINDOW, DOOR], title=titles[0])
    p1 = panel('p1', [room('r1', 'bedroom')], [WINDOW, DOOR], title=titles[1])
    d = build(result(p0, p1))
    assert all('storey' not in r for r in d['apartment_rooms']) and 'storey_unconfirmed' in d['trial']['flags']
    assert all('storey' not in p for p in d['trial']['panels'])


def test_single_panel_keeps_its_storey():
    d = build(result(panel('p0', [room('r1', 'living')], [WINDOW, DOOR], title='Ground Floor')))
    assert d['rooms_geo']['living']['storey'] == 0 and 'storey_unconfirmed' not in d['trial']['flags']


def test_second_living_id_and_one_named_living():
    small = [(600, 0), (900, 0), (900, 200), (600, 200)]
    p = panel('p0', [room('r2', 'living', contour=small, area=6), room('r1', 'living', area=20)], [WINDOW, DOOR])
    d = build(result(p))
    # самая большая — `living`, как `trial_room.pick_living`
    assert d['apartment_rooms'][0]['id'] == 'living' and d['trial']['panels'][0]['rooms'][1]['id'] == 'living'
    assert sum(1 for r in d['apartment_rooms'] if r['id'] == 'living') == 1


def test_scene_variants_replace_pending_ready_first_and_mapped():
    res = simple()
    d = build(res, scene_for(res))
    ids = [v['id'] for v in d['variants']]
    assert ids == ['set7', 'set11', 'set9'], 'провалившийся стиль — в конце: страница открывает первый'
    v = d['variants'][0]
    assert v['pending'] is False and v['furniture_state'] == 'ready' and v['title'] == 'Сканди' and v['style_id'] == 'scandi'
    it = v['items'][0]
    assert it['role'] == 'диван' and it['x'] == 250.0 and it['y'] == 340.0 and it['rot'] == 90 and it['w'] == 200.0 and it['h'] == 80.0
    assert it['corner'] is True and it['corner_left'] is True and it['section'] == 95.0
    assert it['sku']['msid'] == 'm-1_2' and it['sku']['img'] == 'https://img.example/a.jpg' and it['sku']['price'] == 100
    assert v['missing_item'] == [{'role': 'ковёр'}]
    assert d['variants'][1]['furniture_state'] == 'partial' and d['variants'][1]['furniture_problem']['codes'] == ['route_blocked']
    assert d['variants'][2]['furniture_state'] == 'failed' and d['variants'][2]['items'] == []
    assert d['trial']['furniture'] == 'ready' and d['trial']['flags'] == ['band_lowered']
    assert d['rules']['slot_band_cm'] == {'диван': {'min': 500}}
    # лента замен — только товары сцены; порядок по цене
    assert [p['sid'] for p in d['feeds']['диван']] == ['1_2'] and set(d['feeds']['диван'][0]['styles']) == {'сканди', 'минимализм'}
    assert d['sofa_feed'] == d['feeds']['диван']


def test_scene_core_and_junctions_for_page():
    res = simple()
    scene = scene_for(res)
    scene['core'].update(w=450.0, d=380.0)
    geo = build(res, scene)['rooms_geo']['living']
    assert (geo['w'], geo['d']) == (450, 380) and geo['radiators'] == []
    kinds = {(o['wall'], o['kind']) for o in geo['openings']}
    assert ('north', 'opening') in kinds and ('east', 'door') in kinds and not any(k.startswith('_') for o in geo['openings'] for k in o)
    assert next(o for o in geo['openings'] if o['kind'] == 'opening').get('swing_cm') is None


def test_scene_furnishes_one_living_other_stops_spinning():
    p = panel('p0', [room('r1', 'living', area=30), room('r2', 'living', area=10)], [WINDOW, DOOR])
    res = result(p)
    res['panels'][0]['rooms'][1]['contour'] = [[1000, 0], [1400, 0], [1400, 300], [1000, 300]]
    res['panels'][0]['rooms'][1]['bbox'] = {'x': 1000, 'y': 0, 'w': 400, 'd': 300}
    res['panels'][0]['openings'] = [WINDOW, DOOR, op('window', (1200, 0), 100), op('door', (1400, 150), 90)]
    d = build(res, scene_for(res))
    other = [v for v in d['variants'] if v['room_id'] == 'living-2'][0]
    assert other['pending'] is False and other['furniture_state'] == 'none' and other['items'] == []
    state, code, text = _outcomes(d)['living-2']
    assert (state, code) == ('refused', 'one_living_furnished') and text


@pytest.mark.parametrize('status', ['refused', 'failed'])
def test_scene_without_furniture_keeps_room_and_says_why(status):
    res = simple()
    scene = {'trial_id': JOB, 'status': status, 'flags': [], 'problems': [{'code': 'solver_failed'}], 'room': None}
    if status == 'refused':
        scene['refusal'] = {'code': 'living_core_small', 'detail': 'не влезает'}
    d = build(res, scene)
    v = d['variants'][0]
    assert v['pending'] is False and v['furniture_state'] == 'failed' and v['items'] == [] and v['room_id'] == 'living'
    assert v['furniture_problem']['code'] == ('living_core_small' if status == 'refused' else 'solver_failed')
    assert d['trial']['furniture'] == 'failed'


def test_scene_of_another_job_or_room_refused():
    res = simple()
    with pytest.raises(TB.BundleRefused, match='scene_mismatch'):
        build(res, {**scene_for(res), 'trial_id': 'other'})
    wrong = scene_for(res)
    wrong['room'] = {'id': 'r9', 'panel': 'p0'}
    with pytest.raises(TB.BundleRefused, match='scene_mismatch'):
        build(res, wrong)
    wrong = scene_for(res)
    wrong.pop('core')
    with pytest.raises(TB.BundleRefused, match='scene_mismatch'):
        build(res, wrong)


@pytest.mark.parametrize('job', ['', '../x', 'a b'])
def test_bad_job_id_refused(job):
    with pytest.raises(TB.BundleRefused, match='bad_job_id'):
        TB.build(job, simple(), ctx=CTX)


def test_bad_result_refused():
    with pytest.raises(TB.BundleRefused, match='bad_result'):
        build({**simple(), 'units': 'm'})


def test_style_ids_match_live_demo():
    src = open(os.path.join(HERE, '..', 'flat215_demo.py'), encoding='utf-8').read()
    node = next(n for n in ast.parse(src).body if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'STYLE_IDS')
    assert ast.literal_eval(node.value) == TB.STYLE_IDS


def test_output_is_valid_json_with_no_shapely_leftovers():
    res = simple()
    json.dumps(build(res), ensure_ascii=False)
    json.dumps(build(res, scene_for(res)), ensure_ascii=False)


def test_sample_for_ts_contract_is_current():
    """Образец читает `tests/unit/trial-bundle.test.ts` и прогоняет через Zod: форма Python и TS не разъедутся. UPDATE_TRIAL_SCHEMA=1 — перезаписать."""
    path = os.path.join(HERE, '..', '..', '..', 'tests', 'fixtures', 'trial-bundle.sample.json')
    res = simple()
    now = json.dumps({'empty': build(res), 'furnished': build(res, scene_for(res))}, ensure_ascii=False, indent=1, sort_keys=True) + '\n'
    if os.environ.get('UPDATE_TRIAL_SCHEMA') == '1':
        with open(path, 'w', encoding='utf-8') as f:
            f.write(now)
    with open(path, encoding='utf-8') as f:
        assert f.read() == now

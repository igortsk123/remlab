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

QUIZ = {'questions': [{'id': 'style', 'ru': 'Какой стиль?', 'en': 'Which style?'}]}
CTX = {'rules': {'sofa_tv_cm': [180, 300]}, 'msid_of': lambda sid: f'm-{sid}', 'slot_band': lambda g: {'диван': {'min': g['w']}},
       'quiz': QUIZ}
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
    assert d['apartment_rooms'][0]['furniture_outcome'] == 'pending' and d['trial']['complete'] is False
    assert d['quiz'] == QUIZ


def _outcomes(d):
    return {r['id']: (r['furniture_state'], r['furniture_code'], r['furniture_text']) for r in d['apartment_rooms']}


def test_room_outcome_every_room_ready_pending_or_refused_with_text():
    bath = [(600, 0), (800, 0), (800, 200), (600, 200)]
    def plan():
        return result(panel('p0', [room('r1', 'living', name='Lounge'), room('b1', 'bathroom', contour=bath, area=4)], [WINDOW, DOOR]))
    res = plan()
    empty = _outcomes(build(res))
    assert empty['living'] == ('pending', None, None)
    assert empty['bathroom-1'][:2] == ('not_furnished', 'room_kind_not_furnished') and empty['bathroom-1'][2]
    assert _outcomes(build(res, scene_for(res)))['living'] == ('ready', None, None)
    failed = scene_for(res, status='refused')
    failed['refusal'] = {'code': 'living_core_small', 'detail': 'x'}
    state, code, text = _outcomes(build(res, failed))['living']
    assert (state, code, text) == ('refused', 'living_core_small', TB.OUTCOME_TEXT['no_products'][0])
    assert text == 'Нет подходящих товаров согласно действующим шаблонам.'


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
    assert d['trial']['scale'] == 'not_verified' and 'living' in d['rooms_geo']
    assert d['variants'][0]['furniture_state'] == 'awaiting_check'          # TG 533: масштаб не подтверждён — ждёт проверки
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
    assert {v['room_id'] for v in d['variants']} == {'living', 'living-2', 'bedroom-1', 'bedroom-2'}
    assert len({v['id'] for v in d['variants']}) == 4
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


def test_room_order_numbers_within_same_name_and_storeys_bottom_up():
    """T-20261110-04: «Bedroom 2» шла раньше «Bedroom 1» (порядок чертежа). Одноимённые с номером — по номеру на своих местах, прочие
    не двигаются; этажи — снизу вверх по подтверждённому этажу; id комнат не меняются (по ним живут куски стадий)."""
    up = panel('p0', [room('a', 'bedroom', name='Bedroom 2'), room('b', 'bedroom', name='Bedroom 1'), room('c', 'hall', name='Landing'),
                      room('d', 'bedroom', name='Bedroom 3'), room('e', 'other', name='Cupboard')], [WINDOW, DOOR], title='First Floor')
    down = panel('p1', [room('r1', 'living', name='Lounge'), room('k', 'kitchen', name='Kitchen')], [WINDOW, DOOR], title='Ground Floor')
    names = [r['name'] for r in TB.room_order([up, down], TB.storeys([up, down])[0])]
    assert names == ['Lounge', 'Kitchen', 'Bedroom 1', 'Bedroom 2', 'Landing', 'Bedroom 3', 'Cupboard']
    assert [r['name'] for r in TB.room_order([up, down], {})] == ['Bedroom 1', 'Bedroom 2', 'Landing', 'Bedroom 3', 'Cupboard', 'Lounge', 'Kitchen']
    d = build(result(up, down))
    rows = [(r['titleEn'], r['id'], r['ordinal']) for r in d['apartment_rooms']]
    assert [t for t, _, _ in rows][:4] == ['Lounge', 'Kitchen', 'Bedroom 1', 'Bedroom 2'] and [o for _, _, o in rows] == list(range(1, 8))
    assert dict((t, i) for t, i, _ in rows)['Bedroom 2'] == 'bedroom-1'      # id — по порядку чертежа, как раньше


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
    assert it['sku']['msid'] == 'm-1_2' and it['sku']['name'] == 'Диван · 200×90 см' and it['sku']['name_en'] == 'Sofa · 200×90 cm'
    assert not {'img', 'url', 'price', 'sid'} & set(it['sku'])
    assert v['missing_item'] == [{'role': 'ковёр'}]
    assert d['variants'][1]['furniture_state'] == 'partial' and d['variants'][1]['furniture_problem']['codes'] == ['route_blocked']
    assert d['variants'][2]['furniture_state'] == 'failed' and d['variants'][2]['items'] == []
    assert d['trial']['furniture'] == 'ready' and d['trial']['flags'] == ['band_lowered']
    assert d['rules']['slot_band_cm'] == {'диван': {'min': 500}}
    # лента замен — только товары сцены; порядок по цене
    assert [p['msid'] for p in d['feeds']['диван']] == ['m-1_2'] and set(d['feeds']['диван'][0]['styles']) == {'сканди', 'минимализм'}
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
    assert other['pending'] is False and other['furniture_state'] == 'failed' and other['items'] == []
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


def test_scene_no_products_leaves_room_empty_with_owner_text():
    """`trial_demo` 09.11: ни один стиль не встал — статус `no_products` (с отказом или без): комната пустая, текст «нет товаров»."""
    res = simple()
    for refusal in (None, {'code': 'living_core_small', 'detail': 'не влезает'}):
        scene = {**scene_for(res, status='no_products'), 'problems': [{'code': 'solver_failed'}]}
        if refusal:
            scene['refusal'] = refusal
        d = build(res, scene)
        assert [v['furniture_state'] for v in d['variants']] == ['failed'] and d['variants'][0]['items'] == []
        state, code, text = _outcomes(d)['living']
        assert state == 'refused' and code == (refusal or {}).get('code', 'no_products') and text.startswith('Нет подходящих товаров')
        assert d['trial']['furniture'] == 'failed' and d['trial']['complete'] is True
    with pytest.raises(TB.BundleRefused, match='scene_mismatch'):     # подбор не дошёл до конца — сборщик такую сцену не берёт
        build(res, {**scene_for(res), 'status': 'pending'})


def test_scene_rows_of_new_format_keep_checked_model_and_colour():
    """Строка `trial_demo.public_row`: `msid` уже проверен (null — годной модели нет), по `sid` модель семьи не выводится; цвет — свой."""
    res = simple()
    scene = scene_for(res)
    for v in scene['variants']:
        for r in v['items']:
            for k in ('name', 'url', 'img', 'price', 'mid', 'eid'):
                r.pop(k)
            r.update(msid=None, mesh='none', name_en='Kirmas corner sofa, terracotta velour', colour_en='terracotta velour')
    it = build(res, scene)['variants'][0]['items'][0]
    assert it['sku']['msid'] is None and it['sku']['colour_en'] == 'terracotta velour' and it['sku']['name_en'] == 'Sofa · 200×90 cm'
    assert it['sku']['colour_ru'] == 'терракотовый велюр'
    scene['variants'][0]['items'][0].update(msid='112923_1', colour_en='Kirmas velour')        # чужое слово в цвете — цвет пустой
    it = build(res, scene)['variants'][0]['items'][0]
    assert it['sku']['msid'] == '112923_1' and it['sku']['colour_en'] == ''


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


# ───────── третья проверка советника и владелец 09.11: опрос, очистка, «не обставляется», пустая комната с текстом ─────────

def test_quiz_rule_goes_into_bundle_and_live_rule_is_bilingual():
    assert build(simple())['quiz'] == QUIZ
    live = TB.quiz_rule()
    assert live['questions'] and all(q.get('ru') and q.get('en') for q in live['questions'])
    with pytest.raises(TB.BundleRefused, match='quiz_missing'):
        TB.build(JOB, simple(), ctx={**CTX, 'quiz': {'questions': []}})


def _walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_keys(v)


def test_no_shop_names_links_or_prices_anywhere():
    res = simple()
    scene = scene_for(res)
    for sv in scene['variants']:
        for r in sv['items']:
            r.update(name='Диван угловой Бергамо Hoff', shop='hoff', brand='Hoff')
    d = build(res, scene)
    text = json.dumps(d, ensure_ascii=False).lower()
    assert 'бергамо' not in text and 'hoff' not in text and 'shop.example' not in text and 'img.example' not in text
    assert not set(_walk_keys(d)) & TB.BANNED_KEYS
    for v in d['variants']:
        for it in v['items']:
            assert set(it) <= TB.ITEM_KEYS and set(it['sku']) <= TB.SKU_KEYS
    for rows in d['feeds'].values():
        assert all(set(r) <= TB.FEED_KEYS for r in rows)


def test_output_check_catches_leaks():
    with pytest.raises(TB.BundleRefused, match='shop_leak'):
        TB.assert_public({'a': [{'url': 'x'}]}, [])
    with pytest.raises(TB.BundleRefused, match='shop_leak'):
        TB.assert_public({'a': 'см. https://divan.ru/x'}, [])
    with pytest.raises(TB.BundleRefused, match='shop_leak'):
        TB.assert_public({'a': {'name': 'Диван Бергамо угловой'}}, ['диван бергамо угловой'])
    TB.assert_public({'a': {'name': 'Диван', 'name_en': 'Sofa'}}, ['диван бергамо угловой'])


def test_colour_en_only_dictionary_words():
    assert TB.colour_en(None, 'диван') == '' and TB.colour_en('Диван Викс', 'диван') == ''
    c = TB.colour_en('Диван прямой Викс Рогожка Серый', 'диван')
    assert c and not TB._CYR.search(c) and 'viks' not in c.lower()


# ───────── имена предметов уникальны (T-20261109-35/3): страница узнаёт товар по `sku.name` ─────────

def _names_unique(d):
    """В туре: одно имя — один товар (роль, модель, размер); у одного товара — одно имя (во всех стилях и в ленте)."""
    by_name, by_key = {}, {}
    for v in d['variants']:
        for it in v['items']:
            s = it['sku']
            key = (TB._base_role(it['role']), s.get('msid'), s.get('w'), s.get('d'), s.get('sleep_w'))
            assert by_name.setdefault(s['name'], key) == key, f"одно имя у двух товаров: {s['name']}"
            assert by_key.setdefault(key, (s['name'], s['name_en'])) == (s['name'], s['name_en'])
            en_key = by_name.setdefault('en:' + s['name_en'], key)
            assert en_key == key, f"одно английское имя у двух товаров: {s['name_en']}"
    for role, rows in d['feeds'].items():
        names = [p['name'] for p in rows]
        assert len(names) == len(set(names)) and all(n in by_name for n in names), role
    return by_name


def test_item_names_unique_two_equal_sofas_get_suffix():
    """Два разных дивана одного размера (сценарий «Заменить» сломана): « · 2»; тот же диван в другом стиле — то же имя."""
    res = simple()
    scene = scene_for(res)
    a, b = scene['variants'][0], scene['variants'][2]
    b['items'][0] = {**b['items'][0], 'sid': '9_9'}                        # другой товар того же размера
    a['items'].append({**a['items'][0], 'role': 'диван 2', 'sid': '8_8', 'x': 100.0})   # и третий — в том же стиле
    d = build(res, scene)
    names = _names_unique(d)
    sofas = sorted(n for n in names if not n.startswith('en:') and n.startswith('Диван'))
    assert sofas == ['Диван · 200×90 см', 'Диван · 200×90 см · 2', 'Диван · 200×90 см · 3']
    assert sorted(n[3:] for n in names if n.startswith('en:Sofa')) == ['Sofa · 200×90 cm', 'Sofa · 200×90 cm · 2', 'Sofa · 200×90 cm · 3']
    assert len(d['feeds']['диван']) == 3
    # стулья (`стул`/`стул 2`) — один товар: одно имя без суффикса
    chairs = {it['sku']['name'] for v in d['variants'] for it in v['items'] if it['role'].startswith('стул')}
    assert chairs == {'Стул · 40×40 см'}


def test_item_names_unique_on_fixtures_and_rebuild_does_not_double():
    flat = flat_with_bedrooms()
    parts = [bedroom_part(), bedroom_part('bedroom-2')]
    parts[1]['variants'][0]['items'][0]['sku'].update(msid='m-bed-2')      # другая кровать того же размера в другой спальне
    d = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=parts)
    names = _names_unique(d)
    assert {'Кровать 160 см · 170×210 см', 'Кровать 160 см · 170×210 см · 2'} <= set(names)
    # лента спальни — под ключом комнаты, как ищет страница (`roomKeysOf`); гостиной — голая роль
    assert [p['msid'] for p in d['feeds']['bedroom-1:кровать']] == ['m-bed'] and [p['msid'] for p in d['feeds']['bedroom-2:кровать']] == ['m-bed-2']
    assert 'кровать' not in d['feeds'] and 'диван' in d['feeds'] and d['sofa_feed'] == d['feeds']['диван']
    for fx in ('empty', 'furnished', 'rooms'):
        _names_unique(json.load(open(os.path.join(HERE, '..', '..', '..', 'tests', 'fixtures', 'trial-bundle.sample.json')))[fx])
    # пересборка «Обустроить» берёт куски с уже готовыми именами — размер не удваивается
    again = [{**p, 'variants': [{**v, 'items': [dict(it, sku=dict(it['sku'])) for it in v['items']]} for v in p['variants']]} for p in parts]
    for p, v in zip(again, [x for x in d['variants'] if x['room_id'].startswith('bedroom')]):
        p['variants'][0]['items'][0]['sku']['name'] = v['items'][0]['sku']['name']
    d2 = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=again)
    assert sorted(_names_unique(d2)) == sorted(names)


def test_item_without_size_keeps_role_name_and_unique_suffix():
    res = simple()
    scene = scene_for(res)
    for k, sid in enumerate(('1_1', '2_2')):
        scene['variants'][0]['items'].append({**scene['variants'][0]['items'][0], 'role': 'торшер' if k == 0 else 'торшер 2', 'sid': sid,
                                              'w': None, 'd': None, 'corner': False})
    d = build(res, scene)
    lamps = [it['sku']['name'] for it in d['variants'][0]['items'] if it['role'].startswith('торшер')]
    assert lamps == ['Торшер', 'Торшер · 2']


@pytest.mark.parametrize('colour,item,want', [
    ('grey woven fabric', 'Диван', 'серая рогожка'), ('mint velour', 'Кровать', 'мятный велюр'), ('white', 'ТВ-тумба', 'белая'),
    ('white', 'Кресло', 'белое'), ('blue', 'Прикроватная тумба', 'синяя'), ('grey', 'Кровать', 'серая'),
    ('dark beige ceramic/walnut', 'Столик', 'темно-бежевая керамика/орех'), ('beige/black velour', 'Стул', 'бежевый/чёрный велюр'),
    ('black/natural', 'Обеденный стол', 'чёрный/натуральный'), ('graphite bouclé', 'Диван', 'графитовое букле'),
    ('Diamond latte', 'ТВ-тумба', 'ромб латте'), ('Kirmas velour', 'Диван', ''), ('', 'Диван', ''), (None, 'Диван', ''),
])
def test_colour_ru_from_colour_en_agrees_in_gender(colour, item, want):
    assert TB.colour_ru(colour, item) == want


def bedroom_part(rid='bedroom-1', state='ready', code=None, with_items=True):
    """Кусок как `trial_bedroom.bundle_parts`: магазинное имя и ссылка нарочно — сборка обязана их снять."""
    items = [{'role': 'кровать', 'x': 200, 'y': 150, 'rot': 0, 'w': 170, 'd': 210, 'h': 100, 'dims_src': 'catalog', 'corner': False,
              'corner_left': False, 'section': None, 'url': 'https://shop.example/bed',
              'sku': {'name': 'Кровать Люкс Hoff', 'msid': 'm-bed', 'w': 170, 'd': 210, 'h': 100, 'sleep_w': 160, 'img': '//x.example/b.jpg'}}]
    geo = {'w': 400, 'd': 350, 'title': 'Bedroom 12.0 m²', 'openings': [], 'radiators': []}
    out = {'rooms_geo': {rid: geo} if with_items else {},
           'apartment_rooms': [{'id': rid, 'kind': 'bedroom', 'furniture_state': state, 'furniture_code': code, 'furniture_text': 'x'}],
           'variants': [{'id': f'{rid}-scandi', 'room_id': rid, 'style': 'сканди', 'style_id': 'scandi', 'title': 'Сканди', 'items': items,
                         'pending': False, 'furniture_state': 'ready'}] if with_items else []}
    return out


def flat_with_bedrooms():
    far = [(600, 0), (1000, 0), (1000, 350), (600, 350)]
    far2 = [(1100, 0), (1500, 0), (1500, 350), (1100, 350)]
    kit = [(0, 500), (300, 500), (300, 700), (0, 700)]
    rooms = [room('r1', 'living', name='Lounge'), room('b1', 'bedroom', far, name='Bedroom 1', area=14),
             room('b2', 'bedroom', far2, name='Bedroom 2', area=14), room('k1', 'kitchen', kit, name='Kitchen', area=6),
             room('h1', 'hall', kit, name='Hall', area=6)]
    ops = [WINDOW, DOOR, op('window', (800, 0), 120), op('door', (1000, 175), 90), op('window', (1300, 0), 120), op('door', (1500, 175), 90)]
    return result(panel('p0', rooms, ops))


def test_bedrooms_pending_until_their_stage_then_ready_or_empty_with_owner_text():
    res = flat_with_bedrooms()
    d = build(res)
    o = _outcomes(d)
    assert o['bedroom-1'] == ('pending', None, None) and o['bedroom-2'][0] == 'pending' and d['trial']['complete'] is False
    assert {v['room_id'] for v in d['variants'] if v['pending']} == {'living', 'bedroom-1', 'bedroom-2'}
    assert o['kitchen-1'][:2] == ('not_furnished', 'room_kind_not_furnished') and o['hall-1'][0] == 'not_furnished'
    # стадия спален: первая обставлена, во второй нет подходящих товаров — пустая комната с текстом владельца, остальные обставлены
    d = TB.build(JOB, res, scene_for(res), ctx=CTX, parts=[bedroom_part(), bedroom_part('bedroom-2', 'refused', 'no_products', False)])
    o = _outcomes(d)
    by = {r['id']: r for r in d['apartment_rooms']}
    assert o['living'][0] == 'ready' and o['bedroom-1'][0] == 'ready' and by['bedroom-1']['furniture_outcome'] == 'furnished'
    assert o['bedroom-2'] == ('refused', 'no_products', 'Нет подходящих товаров согласно действующим шаблонам.')
    assert by['bedroom-2']['furniture_outcome'] == 'no_products'
    assert by['bedroom-2']['furniture_text_en'] == 'No suitable products under the current templates.'
    empty = [v for v in d['variants'] if v['room_id'] == 'bedroom-2']
    assert len(empty) == 1 and empty[0]['items'] == [] and empty[0]['furniture_state'] == 'failed' and 'bedroom-2' in d['rooms_geo']
    assert by['kitchen-1']['furniture_outcome'] == 'not_furnished' and by['kitchen-1']['furniture_text_en']
    assert d['trial']['complete'] is True
    bed = next(v for v in d['variants'] if v['room_id'] == 'bedroom-1')['items'][0]
    assert bed['sku'] == {'name': 'Кровать 160 см · 170×210 см', 'name_en': 'Bed 160 cm · 170×210 cm', 'msid': 'm-bed', 'w': 170, 'd': 210,
                          'h': 100, 'sleep_w': 160}
    assert 'url' not in bed and 'hoff' not in json.dumps(d, ensure_ascii=False).lower()


def test_size_flag_room_awaits_check_not_furnished_and_does_not_hold_done():
    """TG 531: «размер не сошёлся» (`dims_mismatch`) — гостиная/спальня ждёт проверки: без мебели, с текстом на обоих языках;
    `complete` не держит; снятая проверка (`release`) — комната снова в обычном пути."""
    flat = flat_with_bedrooms()
    for r in flat['panels'][0]['rooms']:
        if r['id'] in ('r1', 'b1'):
            r['flags'] = ['dims_mismatch']
    d = TB.build(JOB, flat, None, ctx=CTX, parts=[bedroom_part(), bedroom_part('bedroom-2', 'refused', 'no_products', False)])
    rooms = {r['id']: r for r in d['apartment_rooms']}
    for rid in ('living', 'bedroom-1'):
        r = rooms[rid]
        assert (r['furniture_state'], r['furniture_outcome'], r['furniture_code']) == ('awaiting_check', 'size_unverified', 'dims_mismatch')
        assert r['furniture_text'].startswith('Размер может быть неточным') and r['furniture_text_en'].startswith('Size may be approximate')
        v = next(v for v in d['variants'] if v['room_id'] == rid)
        assert v['items'] == [] and v['pending'] is False and v['furniture_state'] == 'awaiting_check'
    assert rooms['bedroom-2']['furniture_state'] == 'refused' and d['trial']['complete'] is True
    # агент проверил размер: гостиная снова ждёт мебель, спальня берёт свой кусок
    d = TB.build(JOB, flat, None, ctx=CTX, parts=[bedroom_part()], release=['living', 'bedroom-1'])
    rooms = {r['id']: r['furniture_state'] for r in d['apartment_rooms']}
    assert rooms['living'] == 'pending' and rooms['bedroom-1'] == 'ready' and d['trial']['complete'] is False
    # гостиную обставили по запросу (готовая сцена) — показываем мебель, флаг не мешает
    d = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=[bedroom_part()], release=['bedroom-1'])
    assert {r['id']: r['furniture_state'] for r in d['apartment_rooms']}['living'] == 'ready'


def test_scale_unverified_whole_flat_awaits_check_by_switch(monkeypatch):
    """TG 533: масштаб ВСЕЙ квартиры не подтверждён — все гостиные и спальни ждут проверки; переключатель — одна константа."""
    flat = flat_with_bedrooms()
    flat['scale']['status'] = 'not_verified'
    d = TB.build(JOB, flat, None, ctx=CTX)
    got = {r['id']: (r['furniture_state'], r['furniture_code']) for r in d['apartment_rooms'] if r['kind'] in ('living', 'bedroom')}
    assert got and set(got.values()) == {('awaiting_check', 'scale_unverified')} and d['trial']['complete'] is True
    monkeypatch.setattr(TB, 'SCALE_UNVERIFIED_AWAITS_CHECK', False)
    d = TB.build(JOB, flat, None, ctx=CTX)
    assert {r['furniture_state'] for r in d['apartment_rooms'] if r['kind'] in ('living', 'bedroom')} == {'pending'}


def test_scale_from_total_area_furnishes_with_soft_note():
    """T-26: масштаб по общей площади (`area`) — комнаты обставляются как обычно, на плане мягкая пометка ru/en; у прочих — без неё."""
    flat = flat_with_bedrooms()
    flat['scale']['status'] = 'area'
    d = TB.build(JOB, flat, None, ctx=CTX)
    assert {r['furniture_state'] for r in d['apartment_rooms'] if r['kind'] in ('living', 'bedroom')} == {'pending'}
    assert d['trial']['scale'] == 'area' and set(d['trial']['scale_note']) == {'ru', 'en'}
    assert 'примерн' in d['trial']['scale_note']['ru'] and 'approximate' in d['trial']['scale_note']['en']
    assert 'scale_note' not in build(simple())['trial']


def test_approx_consent_room_released_and_marked():
    """Р1 «Обустроить»: флаг `approx_consent` в результате (ставит пересборка) снимает проверку как `release`; запись комнаты несёт
    `approx_consent: true` (страница — «размеры примерные»); прочие комнаты ждут проверки, `scale` остаётся `not_verified`."""
    flat = flat_with_bedrooms()
    flat['scale']['status'] = 'not_verified'
    b1 = next(r for r in flat['panels'][0]['rooms'] if r['id'] == 'b1')
    b1['flags'] = ['approx_consent']
    d = TB.build(JOB, flat, None, ctx=CTX, parts=[bedroom_part()])
    rooms = {r['id']: r for r in d['apartment_rooms']}
    assert rooms['bedroom-1']['furniture_state'] == 'ready' and rooms['bedroom-1']['approx_consent'] is True
    assert rooms['living']['furniture_state'] == 'awaiting_check' and 'approx_consent' not in rooms['living']
    assert d['trial']['scale'] == 'not_verified'
    # тот же флаг при подтверждённом масштабе — размеры не «примерные», метки нет
    flat['scale']['status'] = 'verified'
    d = TB.build(JOB, flat, None, ctx=CTX, parts=[bedroom_part()])
    assert all('approx_consent' not in r for r in d['apartment_rooms'])


def _photo(d):
    return {r['id']: r['photo_ok'] for r in d['apartment_rooms']}


@pytest.mark.parametrize('scale,want', [('verified', True), ('listing', True), ('area', False), ('not_verified', False)])
def test_photo_ok_only_for_furnished_living_and_bedroom_with_confirmed_scale(scale, want):
    """T-20261109-34, план agent-trial-08 § «Правило фото»: фото — только гостиной/спальне, обставленной (`ready`), при масштабе
    `verified`/`listing`. «Подбирается», «нет товаров», «не обставляется» (кухня, прихожая), `area` без сверки — нет."""
    flat = flat_with_bedrooms()
    flat['scale']['status'] = scale
    d = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=[bedroom_part(), bedroom_part('bedroom-2', 'refused', 'no_products', False)],
                 release=['living', 'bedroom-1'] if scale == 'not_verified' else ())
    p = _photo(d)
    assert p['living'] is want and p['bedroom-1'] is want
    assert p['bedroom-2'] is False and p['kitchen-1'] is False and p['hall-1'] is False
    assert not any(_photo(build(flat)).values())                     # без сцены и кусков — всё «подбирается»: фото нет


def test_photo_ok_false_for_size_flag_and_approx_consent():
    """Флаг размера (`dims_mismatch`) — ждёт проверки, фото нет; «Обустроить как есть» (`approx_consent`) — мебель есть, фото нет."""
    flat = flat_with_bedrooms()
    flat['scale']['status'] = 'verified'
    b1 = next(r for r in flat['panels'][0]['rooms'] if r['id'] == 'b1')
    b1['flags'] = ['dims_mismatch']
    d = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=[bedroom_part()])
    assert _photo(d)['bedroom-1'] is False and _photo(d)['living'] is True
    b1['flags'] = ['dims_mismatch', 'approx_consent']
    d = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=[bedroom_part()])
    by = {r['id']: r for r in d['apartment_rooms']}
    assert by['bedroom-1']['furniture_state'] == 'ready' and by['bedroom-1']['approx_consent'] is True and by['bedroom-1']['photo_ok'] is False
    # гостиную обставили по запросу при флаге размера (готовая сцена): мебель показываем, фото — нет
    r1 = next(r for r in flat['panels'][0]['rooms'] if r['id'] == 'r1')
    r1['flags'] = ['dims_mismatch']
    d = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=[bedroom_part()])
    assert {r['id']: r['furniture_state'] for r in d['apartment_rooms']}['living'] == 'ready' and _photo(d)['living'] is False


def test_parts_matched_by_source_room_and_foreign_room_refused():
    res = flat_with_bedrooms()
    part = bedroom_part('bedroom-7')
    part['apartment_rooms'][0].update(panel='p0', src_id='b2')
    d = TB.build(JOB, res, None, ctx=CTX, parts=[part])
    assert _outcomes(d)['bedroom-2'][0] == 'ready' and {v['room_id'] for v in d['variants'] if v['items']} == {'bedroom-2'}
    with pytest.raises(TB.BundleRefused, match='parts_mismatch'):
        TB.build(JOB, res, None, ctx=CTX, parts=[bedroom_part('bedroom-9')])
    with pytest.raises(TB.BundleRefused, match='parts_mismatch'):
        TB.build(JOB, res, None, ctx=CTX, parts=[bedroom_part('living')])


# ───────── язык (владелец TG 486–488, Codex lang п.2.1): контракт языково-нейтральный ─────────

@pytest.mark.parametrize('name,kind,ru,en', [
    ('Lounge', 'living', 'Гостиная', 'Lounge'), ('Bedroom 3', 'bedroom', 'Спальня 3', 'Bedroom 3'),
    ('BEDROOM 1', 'bedroom', 'Спальня 1', 'Bedroom 1'), ('Kitchen/Diner', 'kitchen', 'Кухня-столовая', 'Kitchen/Diner'), ('Lounge/Diner', 'living', 'Гостиная/столовая', 'Lounge/Diner'),
    ('WC #1', 'bathroom', 'Туалет 1', 'WC #1'), ('FIRST FLOOR LANDING', 'hall', 'Прихожая', 'First Floor Landing'),
    ('Lounge and Dining Room', 'living', 'Гостиная и столовая', 'Lounge and Dining Room'),
    ('Bedroom 2 / En-suite', 'bedroom', 'Спальня 2 / санузел при спальне', 'Bedroom 2 / En-suite'),
    ('Snug', 'living', 'Малая гостиная', 'Snug'), ('Den', 'living', 'Гостиная', 'Den'), ('Bedroom', 'bedroom', 'Спальня', 'Bedroom'),
    ('Кухня-гостиная', 'living', 'Кухня-гостиная', 'Kitchen-living room'), ('Спальня 2', 'bedroom', 'Спальня 2', 'Bedroom 2'),
    ('Гостиная', 'living', 'Гостиная', 'Living room'), ('Санузел', 'bathroom', 'Санузел', 'Bathroom'),
    ('Кладовка у лестницы', 'other', 'Кладовка у лестницы', 'Room'), ('Спальня №4', 'bedroom', 'Спальня №4', 'Bedroom 4'),
    ('', 'hall', 'Прихожая', 'Hall'), (None, 'bedroom', 'Спальня', 'Bedroom'),
])
def test_room_titles_both_languages(name, kind, ru, en):
    assert TB.room_titles(name, kind) == (ru, en)


def _plan(names):
    xs = [0, 600, 1100, 1600]
    rooms, ops = [], []
    for i, (name, kind) in enumerate(names):
        x0 = xs[i]
        rooms.append(room(f'r{i}', kind, [(x0, 0), (x0 + 450, 0), (x0 + 450, 380), (x0, 380)], name=name, area=17.1))
        ops += [op('window', (x0 + 225, 0), 120), op('door', (x0 + 450, 190), 90)]
    return result(panel('p0', rooms, ops))


@pytest.mark.parametrize('names', [
    [('Гостиная', 'living'), ('Спальня 1', 'bedroom'), ('Кухня', 'kitchen'), ('Санузел', 'bathroom')],
    [('Lounge', 'living'), ('Bedroom 1', 'bedroom'), ('Kitchen', 'kitchen'), ('Bathroom', 'bathroom')],
], ids=['ru-plan', 'uk-plan'])
def test_ru_and_uk_plans_give_both_languages(names):
    d = build(_plan(names))
    for r, (src, _) in zip(d['apartment_rooms'], names):
        assert r['name_src'] == src and r['titleRu'] and r['titleEn']
        assert not TB._CYR.search(r['titleEn']) and TB._CYR.search(r['titleRu'])
        assert r['furniture_outcome'] in ('pending', 'not_furnished')
        assert r['furniture_text_en'] is None or not TB._CYR.search(r['furniture_text_en'])
    by = {r['id']: r for r in d['apartment_rooms']}
    assert by['living']['titleRu'] == 'Гостиная' and by['bedroom-1']['titleRu'] == 'Спальня 1' and by['bedroom-1']['titleEn'] == 'Bedroom 1'
    for rid, g in d['rooms_geo'].items():
        assert g['title_en'].endswith('m²') and not TB._CYR.search(g['title_en']) and g['title_ru'].endswith('м²') and g['title'] == g['title_ru']
        assert g['name_src'] == by[rid]['name_src'] and g['approx'] is False


def test_approx_room_marked():
    ell = [(0, 0), (600, 0), (600, 300), (300, 300), (300, 500), (0, 500)]
    d = build(result(panel('p0', [room('r1', 'living', ell, area=24)], [op('window', (450, 0), 120), op('door', (0, 150), 90)])))
    assert d['rooms_geo']['living']['approx'] is True
    assert build(simple())['rooms_geo']['living']['approx'] is False


def test_sample_for_ts_contract_is_current():
    """Образец читает `tests/unit/trial-bundle.test.ts` и прогоняет через Zod: форма Python и TS не разъедутся. UPDATE_TRIAL_SCHEMA=1 — перезаписать."""
    path = os.path.join(HERE, '..', '..', '..', 'tests', 'fixtures', 'trial-bundle.sample.json')
    res = simple()
    flat = flat_with_bedrooms()
    rooms = TB.build(JOB, flat, scene_for(flat), ctx=CTX, parts=[bedroom_part(), bedroom_part('bedroom-2', 'refused', 'no_products', False)])
    now = json.dumps({'empty': build(res), 'furnished': build(res, scene_for(res)), 'rooms': rooms}, ensure_ascii=False, indent=1,
                     sort_keys=True) + '\n'
    if os.environ.get('UPDATE_TRIAL_SCHEMA') == '1':
        with open(path, 'w', encoding='utf-8') as f:
            f.write(now)
    with open(path, encoding='utf-8') as f:
        assert f.read() == now

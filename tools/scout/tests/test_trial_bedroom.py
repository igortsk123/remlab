"""Проба агента: все спальни загруженного плана (план agent-trial-04-bedroom, задачи Б–Д; T-20261109-22). Без базы и платного:
банк, сторож моделей и каталог — поддельные.

  1) спальни всех панелей найдены, id комнат и вариантов уникальны на задание;
  2) масштаб не подтверждён — отказ по всем комнатам, ни одного предмета;
  3) правило кровати (TG 1377): идеальной ширины нет модели → другая, что влезает; никакая → без кровати и с текстом; узких 90 нет;
  4) только разрешённые поля: ни магазинов, ни ссылок; подложенная утечка ловится;
  5) готовая расстановка банка (`layout`) не читается; мебель проверена по полному контуру;
  6) куски для общей версии данных совпадают с контрактом.
    ~/venvs/scout/bin/python -m pytest tools/scout/tests/test_trial_bedroom.py -q"""
import json
import os
import re
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
sys.path.insert(0, SCOUT)
import trial_bedroom as TB  # noqa: E402
import trial_demo as TD  # noqa: E402

SHOP = 'ШопМирТест'
URL = 'https://shop-test.example/item'


def item(mid, w, d=205, h=100, sleep=None, name=None):
    return {'mid': mid, 'eid': mid + '0', 'name': name or f'Товар {mid} особенный', 'w': w, 'd': d, 'h': h, 'sleep_w': sleep, 'shop': SHOP, 'url': URL,
            'img': URL + '.jpg', 'price': 12345}


def rec(style, bed, stand=None, ward=None, layout=None):
    its = {'кровать': bed}
    if stand:
        its['тумба прикроватная'] = stand
    if ward:
        its['шкаф'] = ward
    return {'room_id': 'bedroom-1', 'style': style, 'purpose': 'couple', 'tier': 'mid', 'items': its, 'alternates': {}, 'layout': layout or {}}


def ctx(records, blocked=()):
    def mesh_ok(sku):
        return 'нет модели' if sku['sid'] in blocked else ''
    return {'bank': records, 'catalog': [], 'catalog_error': '', 'mesh_ok': mesh_ok, 'msid': lambda sid: (sid or '').replace(':', '_'),
            'defect': None, 'thr': 6.6, 'used': {}}


def full_bank(bed_w=170, sleep=160):
    return [rec(st, item(f'b{i}', bed_w, sleep=sleep), item(f's{i}', 45, 40, 50), item(f'w{i}', 120, 60, 210)) for i, st in enumerate(TB.STYLES)]


def rect_room(rid, name, x0, y0, w, d, kind='bedroom'):
    c = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + d], [x0, y0 + d]]
    return {'id': rid, 'name': name, 'kind': kind, 'contour': c, 'bbox': {'x': x0, 'y': y0, 'w': w, 'd': d}, 'areaM2': w * d / 1e4, 'flags': []}


def openings(x0, y0, w, d):
    return [{'kind': 'door', 'c': [x0 + 60, y0], 'widthCm': 80, 'exterior': False}, {'kind': 'window', 'c': [x0 + w / 2, y0 + d], 'widthCm': 120, 'exterior': True}]


def plan(status='verified', sizes=((420, 380), (400, 360))):
    panels = []
    for i, (w, d) in enumerate(sizes):
        panels.append({'id': f'p{i}', 'title': f'Storey {i}', 'rooms': [rect_room('r1', f'Bedroom {i + 1}', 0, 0, w, d)], 'walls': [], 'openings': openings(0, 0, w, d)})
    return {'version': 1, 'units': 'cm', 'scale': {'status': status, 'ppm': 100.0, 'inliers': 3, 'n': 3}, 'panels': panels, 'flags': []}


@pytest.fixture(autouse=True)
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(TD, 'TRIAL_ROOT', str(tmp_path))


def beds(room):
    return [next(i for i in v['items'] if i['role'] == 'кровать') for v in room['variants']]


def test_all_bedrooms_unique_ids():
    job = TB.build('t1', plan(), ctx(full_bank()))
    assert [r['room_id'] for r in job['rooms']] == ['bedroom-1', 'bedroom-2']
    assert [r['panel'] for r in job['rooms']] == ['p0', 'p1']
    assert {r['src_id'] for r in job['rooms']} == {'r1'}         # один и тот же id плана на двух этажах — не конфликт
    ids = [v['id'] for r in job['rooms'] for v in r['variants']]
    assert ids and len(ids) == len(set(ids))
    for r in job['rooms']:
        assert r['outcome']['state'] == 'ready' and len(r['variants']) == len(TB.STYLES)


def test_kind_other_named_bedroom_found_and_ensuite_not():
    p = plan(sizes=((420, 380),))
    p['panels'][0]['rooms'].append(dict(rect_room('r2', 'Bedroom 2 / Study', 500, 0, 350, 340), kind='other'))
    p['panels'][0]['rooms'].append(dict(rect_room('r3', 'En-suite', 900, 0, 200, 200), kind='bathroom'))
    assert [r['id'] for _, r, _ in TB.bedrooms_of(p)] == ['r1', 'r2']


def test_scale_unverified_refused_no_furniture(tmp_path):
    job = TB.build('t2', plan('not_verified'), None)            # даже без данных: до подбора дело не доходит
    assert job['status'] == 'refused'
    for r in job['rooms']:
        assert r['variants'] == [] and r['outcome']['state'] == 'refused' and r['outcome']['code'] == 'scale_unverified' and r['outcome']['text']
    saved = json.load(open(os.path.join(tmp_path, 't2', 'bedrooms.json'), encoding='utf-8'))
    assert saved['status'] == 'refused'


def test_bed_without_model_replaced_by_other_width():
    bank = []
    for i, st in enumerate(TB.STYLES):
        r = rec(st, item(f'i{i}', 170, sleep=160), item(f's{i}', 45, 40, 50))
        r['alternates'] = {'кровать': [item(f'a{i}', 150, sleep=140)]}
        bank.append(r)
    blocked = {f'i{i}_i{i}0' for i in range(len(TB.STYLES))}      # идеальной ширине модели нет
    job = TB.build('t3', plan(sizes=((420, 380),)), ctx(bank, blocked))
    r = job['rooms'][0]
    assert r['outcome']['state'] == 'ready'
    assert {b['sku']['sleep_w'] for b in beds(r)} == {140}


def test_no_bed_fits_refused_with_text():
    job = TB.build('t4', plan(sizes=((230, 300),)), ctx(full_bank(bed_w=190, sleep=180)))
    o = job['rooms'][0]['outcome']
    assert o['state'] == 'refused' and o['text'] == TB.TEXT_NO_PRODUCTS and job['rooms'][0]['variants'] == []
    assert job['status'] == 'refused'


def test_no_ready_model_refused_with_text():
    blocked = {f'b{i}_b{i}0' for i in range(len(TB.STYLES))}
    job = TB.build('t5', plan(sizes=((420, 380),)), ctx(full_bank(), blocked))
    o = job['rooms'][0]['outcome']
    assert o['state'] == 'refused' and o['code'] == 'no_products' and o['text'] == 'No suitable products under the current templates.'


def test_single_90_excluded():
    bank = [rec(st, item(f'n{i}', 95, sleep=90)) for i, st in enumerate(TB.STYLES)]
    job = TB.build('t6', plan(sizes=((420, 380),)), ctx(bank))
    assert job['rooms'][0]['variants'] == [] and job['rooms'][0]['outcome']['code'] == 'no_products'


def test_partial_when_item_missing():
    bank = [rec(st, item(f'b{i}', 170, sleep=160)) for i, st in enumerate(TB.STYLES)]   # только кровати: тумб и шкафов нет
    job = TB.build('t7', plan(sizes=((420, 380),)), ctx(bank))
    r = job['rooms'][0]
    assert r['outcome']['state'] == 'partial' and r['outcome']['text']
    assert all(v['status'] == 'partial' and {m['role'] for m in v['missing_item']} >= {'тумба прикроватная'} for v in r['variants'])


def test_output_allowlist_no_shop():
    job = TB.build('t8', plan(), ctx(full_bank()))
    blob = json.dumps(job, ensure_ascii=False, default=str)
    assert SHOP not in blob and 'shop-test' not in blob and 'особенный' not in blob and 'http' not in blob
    for r in job['rooms']:
        for v in r['variants']:
            for it in v['items']:
                assert set(it) <= TB.ITEM_KEYS and set(it['sku']) <= TB.SKU_KEYS


@pytest.mark.parametrize('leak', [{'url': 'x'}, {'note': 'https://x.example'}, {'note': f'купить в {SHOP}'}, {'a': [{'shop': 'y'}]}])
def test_shop_leak_caught(leak):
    with pytest.raises(TB.ShopLeak):
        TB.assert_no_shop({'rooms': [leak]}, [SHOP.lower()])


def test_build_fails_closed_on_leak(monkeypatch):
    real = TB.public_item

    def leaky(p, it, msid):
        return dict(real(p, it, msid), note=f'купить в {SHOP}')
    monkeypatch.setattr(TB, 'public_item', leaky)
    with pytest.raises(TB.ShopLeak):
        TB.build('t9', plan(), ctx(full_bank()))


def test_bank_layout_not_used():
    bank = full_bank()
    for r in bank:
        r['layout'] = {'кровать': {'x': -999, 'z': -999, 'rot': 0}}
    job = TB.build('t10', plan(), ctx(bank))
    assert all(p['x'] > -500 for r in job['rooms'] for v in r['variants'] for p in v['placements'])


def test_l_shape_checked_over_full_contour():
    c = [[0, 0], [480, 0], [480, 300], [300, 300], [300, 460], [0, 460]]
    room = {'id': 'r1', 'name': 'Bedroom 1', 'kind': 'bedroom', 'contour': c, 'bbox': {'x': 0, 'y': 0, 'w': 480, 'd': 460}, 'areaM2': 17.2, 'flags': []}
    p = {'version': 1, 'units': 'cm', 'scale': {'status': 'verified', 'ppm': 100, 'inliers': 3, 'n': 3}, 'flags': [],
         'panels': [{'id': 'p0', 'title': 'x', 'rooms': [room], 'walls': [], 'openings': [{'kind': 'door', 'c': [100, 0], 'widthCm': 80, 'exterior': False},
                                                                                          {'kind': 'window', 'c': [150, 460], 'widthCm': 120, 'exterior': True}]}]}
    job = TB.build('t11', p, ctx(full_bank()))
    r = job['rooms'][0]
    assert r['variants'] and all(v['post_ok'] and not v['hard'] for v in r['variants'])
    x0, y0, x1, y1 = r['core']['rect']
    assert x0 >= -1 and y0 >= -1 and x1 <= 481 and y1 <= 461


def test_bed_head_not_against_niche_air():
    # ниша 55 см вдоль восточной стены: сторона ядра над ней — не стена, кровать изголовьем туда не ставим
    from shapely.geometry import Point, Polygon
    c = [[0, 0], [400, 0], [400, 280], [345, 280], [345, 420], [0, 420]]
    room = {'id': 'r1', 'name': 'Bedroom 1', 'kind': 'bedroom', 'contour': c, 'bbox': {'x': 0, 'y': 0, 'w': 400, 'd': 420}, 'areaM2': 15.7, 'flags': []}
    p = {'version': 1, 'units': 'cm', 'scale': {'status': 'verified', 'ppm': 100, 'inliers': 3, 'n': 3}, 'flags': [],
         'panels': [{'id': 'p0', 'title': 'x', 'rooms': [room], 'walls': [], 'openings': [{'kind': 'door', 'c': [60, 0], 'widthCm': 80, 'exterior': False},
                                                                                          {'kind': 'window', 'c': [170, 420], 'widthCm': 120, 'exterior': True}]}]}
    job = TB.build('t16', p, ctx(full_bank()))
    r = job['rooms'][0]
    assert r['variants']
    edge = Polygon(c).exterior
    for v in r['variants']:
        b = next(q for q in v['placements'] if q['role'] == 'кровать')
        rad = __import__('math').radians(b['rot'])
        bx, by = b['x'] - __import__('math').sin(rad) * b['d'] / 2, b['y'] - __import__('math').cos(rad) * b['d'] / 2
        assert edge.distance(Point(bx, by)) <= TB.BACK_GAP_CM + 1


def test_not_furnished_without_entry():
    p = plan(sizes=((420, 380),))
    p['panels'][0]['openings'] = [p['panels'][0]['openings'][1]]   # окно есть, двери нет
    job = TB.build('t12', p, ctx(full_bank()))
    o = job['rooms'][0]['outcome']
    assert o['state'] == 'refused' and o['code'] == 'no_entry' and o['text']


def test_variants_diverse_products():
    bank = []
    for i, st in enumerate(TB.STYLES):
        r = rec(st, item(f'b{i}', 170, sleep=160), item(f's{i}', 45, 40, 50))
        r['alternates'] = {'кровать': [item(f'c{i}', 170, sleep=160)]}
        bank.append(r)
    job = TB.build('t13', plan(), ctx(bank))
    first, second = (beds(r)[0]['sku']['msid'] for r in job['rooms'])
    assert first != second                                       # вторая спальня берёт незанятую кровать того же стиля


def test_bundle_parts_contract():
    job = TB.build('t14', plan(), ctx(full_bank()))
    parts = TB.bundle_parts(job, {'p0': 0, 'p1': 1})
    assert set(parts) == {'rooms_geo', 'apartment_rooms', 'variants'}
    ids = [v['id'] for v in parts['variants']]
    assert len(ids) == len(set(ids))
    for v in parts['variants']:
        assert re.fullmatch(r'[a-z0-9-]{1,40}', v['room_id']) and v['pending'] is False and isinstance(v['furniture_state'], str) and v['room_id'] in parts['rooms_geo']
    for a in parts['apartment_rooms']:
        assert a['furniture_state'] in ('ready', 'pending', 'refused')
    assert [a['storey'] for a in parts['apartment_rooms']] == [0, 1]
    geo = parts['rooms_geo']['bedroom-1']
    assert geo['w'] > 0 and all(not k.startswith('_') for o in geo['openings'] for k in o)


def test_bundle_parts_refused_room_has_no_variants():
    job = TB.build('t15', plan('not_verified'), None)
    parts = TB.bundle_parts(job)
    assert parts['variants'] == [] and parts['rooms_geo'] == {}
    assert all(a['furniture_state'] == 'refused' and a['furniture_text'] for a in parts['apartment_rooms'])


def test_coverage_counts_ready_by_width_style():
    bank = full_bank()
    cov = TB.coverage(ctx(bank, {'b0_b00'}))
    st0, st1 = TB.STYLES[0], TB.STYLES[1]
    assert cov['table'][st1]['160']['bank'] == 1 and cov['table'][st0]['160']['bank'] == 0
    assert {'style': st0, 'sleep_w': 160} in cov['empty_cells']
    assert not any(c['sleep_w'] == 90 for c in cov['empty_cells'])

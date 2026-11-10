"""Проба агента: все спальни загруженного плана (план agent-trial-04-bedroom, задачи Б–Д; T-20261109-22). Без базы и платного:
банк, сторож моделей и каталог — поддельные.

  1) спальни всех панелей найдены, id комнат и вариантов уникальны на задание;
  2) масштаб не подтверждён — отказ по всем комнатам, ни одного предмета;
  3) правило шаблонов (владелец 09.11, TG 478/480): шаблон (назначение × ширина) → товары под него → нет или не встали → следующий;
     ни один — комната пустая, исход кодом `no_products`, остальные обставляются; кровать без тумб — не шаблон; узких 90 нет;
     исход — коды (`furnished`/`no_products`/`not_readable`/`scale_unverified`), готовых надписей одного языка нет (TG 486–488);
     все стили комнаты — на одном ядре и с одной петлёй (у страницы одна геометрия комнаты); сторож спрашивается с моделью сцены;
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
        assert r['outcome']['state'] == 'furnished' and len(r['variants']) == len(TB.STYLES)


def test_kind_other_named_bedroom_found_and_ensuite_not():
    p = plan(sizes=((420, 380),))
    p['panels'][0]['rooms'].append(dict(rect_room('r2', 'Bedroom 2 / Study', 500, 0, 350, 340), kind='other'))
    p['panels'][0]['rooms'].append(dict(rect_room('r3', 'En-suite', 900, 0, 200, 200), kind='bathroom'))
    assert [r['id'] for _, r, _ in TB.bedrooms_of(p)] == ['r1', 'r2']


def test_scale_unverified_refused_no_furniture(tmp_path):
    job = TB.build('t2', plan('not_verified'), None)            # даже без данных: до подбора дело не доходит
    assert job['status'] == 'refused'
    for r in job['rooms']:
        assert r['variants'] == [] and r['outcome']['state'] == 'scale_unverified' and r['outcome']['code'] == 'scale_unverified'
        assert 'text' not in r['outcome']                        # исход — код, надпись на языке страницы ставит сборщик
    saved = json.load(open(os.path.join(tmp_path, 't2', 'bedrooms.json'), encoding='utf-8'))
    assert saved['status'] == 'refused'


def test_scale_unverified_consented_room_furnished_others_refused():
    """Р1 «Обустроить»: масштаб не подтверждён, агент снял проверку с одной спальни (`approx_consent`) — её обставляем «как есть»
    (флаг в исходе), вторая — отказ `scale_unverified`, как раньше."""
    p = plan('not_verified')
    p['panels'][1]['rooms'][0]['flags'] = ['approx_consent']
    job = TB.build('t2c', p, ctx(full_bank()))
    a, b = job['rooms']
    assert a['outcome']['state'] == 'scale_unverified' and a['variants'] == []
    assert b['outcome']['state'] == 'furnished' and b['variants'] and 'approx_consent' in b['flags']
    assert job['status'] == 'partial'


def test_bed_without_model_replaced_by_other_width():
    bank = []
    for i, st in enumerate(TB.STYLES):
        r = rec(st, item(f'i{i}', 170, sleep=160), item(f's{i}', 45, 40, 50))
        r['alternates'] = {'кровать': [item(f'a{i}', 150, sleep=140)]}
        bank.append(r)
    blocked = {f'i{i}_i{i}0' for i in range(len(TB.STYLES))}      # идеальной ширине модели нет
    job = TB.build('t3', plan(sizes=((420, 380),)), ctx(bank, blocked))
    r = job['rooms'][0]
    assert r['outcome']['state'] == 'furnished'
    assert {b['sku']['sleep_w'] for b in beds(r)} == {140}
    assert {v['template'] for v in r['variants']} <= {'guest-140', 'single-140'}


def test_no_bed_fits_room_empty_no_products():
    job = TB.build('t4', plan(sizes=((230, 300),)), ctx(full_bank(bed_w=190, sleep=180)))
    o = job['rooms'][0]['outcome']
    assert o['state'] == 'no_products' and job['rooms'][0]['variants'] == []
    assert job['status'] == 'refused'


def test_no_ready_model_no_products():
    blocked = {f'b{i}_b{i}0' for i in range(len(TB.STYLES))}
    job = TB.build('t5', plan(sizes=((420, 380),)), ctx(full_bank(), blocked))
    o = job['rooms'][0]['outcome']
    assert o['state'] == 'no_products' and o['code'] == 'no_products'
    for f in job['rooms'][0]['style_failures']:                  # причина по каждому шаблону: кроватей его ширины с моделью нет
        assert f['templates'] and all(t['why'] == 'no_bed' for t in f['templates'])


def test_single_90_excluded():
    bank = [rec(st, item(f'n{i}', 95, sleep=90)) for i, st in enumerate(TB.STYLES)]
    job = TB.build('t6', plan(sizes=((420, 380),)), ctx(bank))
    assert job['rooms'][0]['variants'] == [] and job['rooms'][0]['outcome']['code'] == 'no_products'


def test_bed_without_nightstand_is_no_template():
    # шаблон — кровать И тумбы (ведущие роли спальни): одни кровати без тумб — не шаблон, комната пустая, «кровать в одиночку» не ставим
    bank = [rec(st, item(f'b{i}', 170, sleep=160)) for i, st in enumerate(TB.STYLES)]
    job = TB.build('t7', plan(sizes=((420, 380),)), ctx(bank))
    r = job['rooms'][0]
    assert r['variants'] == [] and r['outcome']['state'] == 'no_products'
    assert any(t['why'] == 'no_nightstand' for f in r['style_failures'] for t in f['templates'])


def test_output_allowlist_no_shop():
    job = TB.build('t8', plan(), ctx(full_bank()))
    blob = json.dumps(job, ensure_ascii=False, default=str)
    assert SHOP not in blob and 'shop-test' not in blob and 'особенный' not in blob and 'http' not in blob
    assert '"text"' not in blob and 'furniture_text' not in blob       # готовых надписей одного языка нет (владелец TG 486–488)
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
    assert o['state'] == 'not_readable' and o['code'] == 'no_entry'          # отдельно от «нет подходящих товаров» (Codex lang п.2.4)


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
        assert a['furniture_state'] in ('ready', 'pending', 'refused') and a['furniture_outcome'] == 'furnished'
        assert a['panel'] in ('p0', 'p1') and a['src_id'] == 'r1'    # сборщик находит комнату куска по (панель, id плана)
        assert 'furniture_text' not in a and 'titleEn' not in a      # ни готовых надписей, ни подписей одного языка
    assert [a['storey'] for a in parts['apartment_rooms']] == [0, 1]
    geo = parts['rooms_geo']['bedroom-1']
    assert geo['w'] > 0 and all(not k.startswith('_') for o in geo['openings'] for k in o)


def test_bundle_parts_refused_room_has_no_variants():
    job = TB.build('t15', plan('not_verified'), None)
    parts = TB.bundle_parts(job)
    assert parts['variants'] == [] and parts['rooms_geo'] == {}
    assert all(a['furniture_state'] == 'refused' and a['furniture_outcome'] == 'scale_unverified' and a['furniture_code'] == 'scale_unverified'
               for a in parts['apartment_rooms'])


def test_coverage_counts_ready_by_width_style():
    bank = full_bank()
    cov = TB.coverage(ctx(bank, {'b0_b00'}))
    st0, st1 = TB.STYLES[0], TB.STYLES[1]
    assert cov['table'][st1]['160']['bank'] == 1 and cov['table'][st0]['160']['bank'] == 0
    assert {'style': st0, 'sleep_w': 160} in cov['empty_cells']
    assert not any(c['sleep_w'] == 90 for c in cov['empty_cells'])


# ───── ПРАВИЛО ШАБЛОНОВ (владелец 09.11, TG 478/480): шаблон → товары под него → нет / не встали → следующий; ни один — комната пустая ─────

def test_templates_order_from_rules():
    big = TB.templates(16.0, 380.0)                              # NDSS для пары, идеальная ширина 160
    ids = [t['id'] for t in big]
    assert ids[0] == 'couple-160' and 'couple-180' in ids and not any(i.endswith('-90') for i in ids)
    assert {t['nightstands'] for t in big if t['purpose'] == 'couple'} == {2}
    small = [t['id'] for t in TB.templates(9.5, 280.0)]         # не для пары, идеальная 140
    assert small[0] == 'guest-140' and not any(i.startswith('couple') for i in small)


def test_template_not_fit_goes_to_next_template(monkeypatch):
    # кровати 160 и 120 есть; 160 «не встаёт» → следующие шаблоны; выполнен первый с кроватью 120, перебор записан
    real = TB._solve_kit

    def fake(ad, cand, cfg, kit, purpose):
        return None if kit['кровать']['w'] > 150 else real(ad, cand, cfg, kit, purpose)
    monkeypatch.setattr(TB, '_solve_kit', fake)
    bank = []
    for i, st in enumerate(TB.STYLES):
        r = rec(st, item(f'b{i}', 170, sleep=160), item(f's{i}', 45, 40, 50))
        r['alternates'] = {'кровать': [item(f'a{i}', 130, sleep=120)]}
        bank.append(r)
    job = TB.build('t17', plan(sizes=((420, 380),)), ctx(bank))
    r = job['rooms'][0]
    assert r['outcome']['state'] == 'furnished' and len(r['variants']) == len(TB.STYLES)
    for v in r['variants']:
        assert v['template'] == 'guest-120' and v['bed_sleep_w'] == 120
        tried = {t['template']: t['why'] for t in v['templates_tried']}
        assert tried['couple-160'] == 'no_fit' and tried['guest-160'] == 'no_fit' and tried['couple-180'] == 'no_bed'


def test_one_room_empty_others_furnished():
    job = TB.build('t18', plan(sizes=((200, 280), (420, 380))), ctx(full_bank()))
    a, b = job['rooms']
    assert a['variants'] == [] and a['outcome']['state'] == 'no_products'
    assert b['outcome']['state'] == 'furnished' and len(b['variants']) == len(TB.STYLES)
    assert job['status'] == 'partial'
    parts = TB.bundle_parts(job)
    assert [x['furniture_outcome'] for x in parts['apartment_rooms']] == ['no_products', 'furnished']
    assert {v['room_id'] for v in parts['variants']} == {'bedroom-2'}     # пустая комната — без вариантов, сборщик кладёт пустую с надписью
    assert set(parts['rooms_geo']) == {'bedroom-1', 'bedroom-2'}          # но с геометрией: показывается пустой


def test_parts_accepted_by_page_bundle():
    # стыковка со сборщиком страницы (`trial_bundle.build`, main 8087fd5d): комнаты по (панель, id плана), надписи RU/EN по коду, чистка — его
    import trial_bundle as BU
    p = plan(sizes=((200, 280), (420, 380)))
    p['panels'][0]['rooms'].append(rect_room('lv', 'Living room', 600, 0, 500, 400, kind='living'))
    p['panels'][0]['openings'] += openings(600, 0, 500, 400)
    job = TB.build('t21', p, ctx(full_bank()))
    cb = {'rules': {'sofa_tv_cm': [180, 300]}, 'msid_of': lambda sid: f'm-{sid}', 'slot_band': lambda g: {'диван': {'min': g['w']}},
          'quiz': BU.quiz_rule()}
    d = BU.build('t21', p, None, ctx=cb, parts=[TB.bundle_parts(job)])
    beds_ = {a['name_src']: a for a in d['apartment_rooms'] if a['kind'] == 'bedroom'}
    empty, full = beds_['Bedroom 1'], beds_['Bedroom 2']
    assert empty['furniture_outcome'] == 'no_products' and empty['furniture_text_en'] == 'No suitable products under the current templates.'
    assert empty['furniture_text'].startswith('Нет подходящих товаров') and empty['id'] in d['rooms_geo']
    assert [v['items'] for v in d['variants'] if v['room_id'] == empty['id']] == [[]]          # пустая, без мебели
    assert full['furniture_outcome'] == 'furnished' and full['titleRu'] == 'Спальня 2' and full['titleEn'] == 'Bedroom 2'
    bed = next(it for v in d['variants'] if v['room_id'] == full['id'] for it in v['items'] if it['role'] == 'кровать')
    # имя в туре уникально: ширина спального места + габарит (T-20261109-35/3)
    assert bed['sku']['name'].startswith('Кровать 160 см · ') and bed['sku']['name_en'].startswith('Bed 160 cm · ')
    assert SHOP not in json.dumps(d, ensure_ascii=False)


def test_variants_share_core_and_hinge():
    # у страницы у комнаты одна геометрия: все стили на одном ядре и с одной петлёй двери
    c = [[0, 0], [480, 0], [480, 300], [300, 300], [300, 460], [0, 460]]
    room = {'id': 'r1', 'name': 'Bedroom 1', 'kind': 'bedroom', 'contour': c, 'bbox': {'x': 0, 'y': 0, 'w': 480, 'd': 460}, 'areaM2': 17.2, 'flags': []}
    p = {'version': 1, 'units': 'cm', 'scale': {'status': 'verified', 'ppm': 100, 'inliers': 3, 'n': 3}, 'flags': [],
         'panels': [{'id': 'p0', 'title': 'x', 'rooms': [room], 'walls': [], 'openings': [{'kind': 'door', 'c': [100, 0], 'widthCm': 80, 'exterior': False},
                                                                                          {'kind': 'window', 'c': [150, 460], 'widthCm': 120, 'exterior': True}]}]}
    r = TB.build('t19', p, ctx(full_bank()))['rooms'][0]
    assert len(r['variants']) == len(TB.STYLES)
    assert len({v['hinge'] for v in r['variants']}) == 1 and all(v['openings_core'] == r['openings_core'] for v in r['variants'])


# ───── УЗКАЯ СПАЛЬНЯ 2,1×3,7 (T-20261110-02, лист T «Bedroom 3»): кровать у стены с проходами по нормам солвера, честные коды отказа ─────

def one_room(w, d, ops):
    return {'version': 1, 'units': 'cm', 'scale': {'status': 'verified', 'ppm': 100, 'inliers': 3, 'n': 3}, 'flags': [],
            'panels': [{'id': 'p0', 'title': 'x', 'rooms': [rect_room('r1', 'Bedroom 3', 0, 0, w, d)], 'walls': [], 'openings': ops}]}


def door(c, w=68):
    return {'kind': 'door', 'c': c, 'widthCm': w, 'exterior': False}


def window(c, w=120):
    return {'kind': 'window', 'c': c, 'widthCm': w, 'exterior': True}


def narrow_bank(bed_w=130, sleep=120, h=100):
    return [rec(st, item(f'n{i}', bed_w, 205, h, sleep=sleep), item(f's{i}', 45, 40, 50), item(f'w{i}', 100, 60, 200))
            for i, st in enumerate(TB.STYLES)]


def passages_ok(r, v):
    """Независимая сверка нормами солвера (`planner.bedroom_checks.check_bed`): проход сбоку кровати и у изножья, изголовье у стены."""
    from planner.bedroom_checks import check_bed
    from planner.models import Item, Opening, Placement, Room
    x0, y0 = r['core']['rect'][0], r['core']['rect'][1]
    room = Room(width_cm=r['core']['w'], depth_cm=r['core']['d'], openings=[Opening(**o) for o in v['openings_core']], radiators=[],
                room_type='bedroom', purpose=v['purpose'])
    ps = [Placement(role=q['role'], x=q['x'] - x0, y=q['y'] - y0, rot=q['rot'], item=Item(role=q['role'], w_cm=q['w'], d_cm=q['d'], h_cm=q['h']))
          for q in v['placements']]
    bad = [x.code for x in check_bed(room, ps) if x.severity.name == 'HARD']
    return not bad, bad


@pytest.mark.parametrize('name,ops', [
    ('дверь в короткой стене', [door([44, 370]), window([0, 150])]),
    ('дверь в длинной стене', [door([210, 110]), window([105, 0])]),
])
def test_narrow_room_gets_single_bed_with_passages(name, ops):
    job = TB.build('t22', one_room(210, 370, ops), ctx(narrow_bank()))
    r = job['rooms'][0]
    assert r['outcome']['state'] == 'furnished' and len(r['variants']) == len(TB.STYLES), (name, r['outcome'], r['style_failures'][:1])
    for v in r['variants']:
        assert v['template'] in ('guest-120', 'single-120') and v['bed_sleep_w'] == 120
        assert v['post_ok'] and not v['hard']
        ok, bad = passages_ok(r, v)
        assert ok, (name, bad)
        roles = [p['role'] for p in v['placements']]
        assert 'кровать' in roles and 'тумба прикроватная' in roles
    assert r['bed_frame_max_cm'] == 135                         # 210 − проход 75: спрос на кровати уже рамы 135


def test_narrow_room_only_wide_beds_is_no_products_not_no_fit():
    # лист T до правки: готовые кровати — только 140 (рама 145): 145 + 75 > 210 — шаблон 140 «больше комнаты», 120 — товаров нет →
    # честное «нет подходящих по размеру товаров» (`no_products`), а не «не встала» (`bed_no_fit`)
    job = TB.build('t23', one_room(210, 370, [door([47, 370]), window([99, 0], 177)]), ctx(narrow_bank(145, 140)))
    r = job['rooms'][0]
    assert r['variants'] == [] and r['outcome']['state'] == 'no_products' and r['outcome']['code'] == 'no_products'
    for f in r['style_failures']:
        why = {t['template']: t['why'] for t in f['templates']}
        assert why['guest-140'] == why['single-140'] == 'too_small' and why['guest-120'] == 'no_bed'


def test_t_like_room_bed_under_window_only_with_low_headboard():
    # геометрия листа T: дверь в углу короткой стены, окно почти во всю противоположную. Изголовье у двери — тумбе места нет (дуга двери),
    # под окном — только кровать ниже подоконника (WINDOW_BLOCKED солвера): высокая спинка — честный отказ, низкая — кровать с тумбой под окном
    ops = [door([47, 370]), window([99, 0], 177)]
    tall = TB.build('t24', one_room(210, 370, ops), ctx(narrow_bank(130, 120, h=100)))['rooms'][0]
    assert tall['variants'] == [] and tall['outcome']['code'] == 'bed_no_fit'
    low = TB.build('t25', one_room(210, 370, ops), ctx(narrow_bank(130, 120, h=80)))['rooms'][0]
    assert low['outcome']['state'] == 'furnished'
    for v in low['variants']:
        assert passages_ok(low, v)[0] and 'тумба прикроватная' in [p['role'] for p in v['placements']]


def test_tiny_room_honest_too_small():
    # 1,8×2,6: уже любой кровати шаблонов с проходом (120 + 75) — «мала», а не «не прочитана» (было `no_core` → not_readable)
    job = TB.build('t26', one_room(180, 260, [door([44, 260]), window([90, 0])]), ctx(narrow_bank()))
    r = job['rooms'][0]
    assert r['variants'] == [] and r['outcome']['state'] == 'no_products' and r['outcome']['code'] == 'room_too_small'


def test_narrow_single_off_until_rules_switch(monkeypatch):
    # узкая односпальная (single_narrow, 90–100) — выключатель ночной сборки (`empty` в rules/bedroom-composition.json, TG 1377):
    # выключена — шаблонов 90 нет; снимут `empty` — комната 2,1×3,7 получает кровать 90 у стены по шаблону солвера bed_narrow_wall
    assert not TB.narrow_enabled() and not any(t['sleep_w'] < 120 for t in TB.templates(7.8, 210.0))
    p = dict(TB.COMP['purposes']['single_narrow'])
    p.pop('empty')
    monkeypatch.setitem(TB.COMP['purposes'], 'single_narrow', p)
    assert TB.narrow_enabled() and {'single_narrow-90', 'single_narrow-100'} <= {t['id'] for t in TB.templates(7.8, 210.0)}
    job = TB.build('t27', one_room(210, 370, [door([210, 110]), window([105, 0])]), ctx(narrow_bank(98, 90)))
    r = job['rooms'][0]
    assert r['outcome']['state'] == 'furnished'
    for v in r['variants']:
        assert v['template'] == 'single_narrow-90' and v['purpose'] == 'single_narrow' and passages_ok(r, v)[0]


def test_gate_asked_with_scene_model():
    # сторож моделей решает по модели, которую грузит сцена (`msid`); без неё живой сторож отвечал «модели сцены нет» всем кроватям
    asked = []

    def mesh_ok(sku):
        asked.append(sku)
        return '' if sku.get('msid') == 'm-' + sku['sid'] else 'модели сцены нет'
    mesh_ok.msid = lambda sid: 'm-' + sid
    c = ctx(full_bank())
    c['mesh_ok'] = mesh_ok
    job = TB.build('t20', plan(sizes=((420, 380),)), c)
    assert asked and job['rooms'][0]['outcome']['state'] == 'furnished'


# ───── рама до среза и длина по реальным рамам (T-20261110-20; разбор T-18: Bedroom 3 5,8 м², ядро 205×370) ─────

def bank_120(order=('kevia', 'seilor', 'vilena'), d=None):
    frames = {'kevia': (150, 226), 'seilor': (153, 210), 'vilena': (126, 210)}
    out = []
    for i, st in enumerate(TB.STYLES):
        bs = [item(f'{k}{i}', frames[k][0], d or frames[k][1], 92, sleep=120, name=f'Кровать {k} {i} особенная') for k in order]
        r = rec(st, bs[0], item(f's{i}', 45, 40, 50), item(f'w{i}', 100, 60, 200))
        r['alternates'] = {'кровать': bs[1:]}
        out.append(r)
    return out


NARROW_OPS = [door([205, 110]), window([102, 0])]


def test_narrow_core_frame_filtered_before_cut():
    # первыми в банке — широкие Кевия 150 и Сейлор 153: раньше они занимали оба места шаблона (BEDS_PER_TEMPLATE) → no_fit; теперь
    # их рама с проходом (150 + 75 > 205) отсеяна до среза — встаёт Вилена 126
    r = TB.build('t30', one_room(205, 370, NARROW_OPS), ctx(bank_120()))['rooms'][0]
    assert r['outcome']['state'] == 'furnished', (r['outcome'], r['style_failures'][:1])
    assert {b['sku']['w'] for b in beds(r)} == {126}
    assert r['bed_frame_max_cm'] == 130


def test_narrow_core_only_wide_frames_honest_bed_no_fit():
    # кровати ширины есть, но ни одна рама с проходами не встаёт → «не встала» (bed_no_fit), а не «нет товаров»
    r = TB.build('t31', one_room(205, 370, NARROW_OPS), ctx(bank_120(('kevia', 'seilor'))))['rooms'][0]
    assert r['variants'] == [] and r['outcome']['state'] == 'no_products' and r['outcome']['code'] == 'bed_no_fit'
    for f in r['style_failures']:
        why = {t['template']: t['why'] for t in f['templates']}
        assert why['guest-120'] == why['single-120'] == 'frame_too_wide'


def test_wide_core_order_unchanged():
    # ядро ≥ 280: все рамы проходят — первая по порядку банка (Кевия), как до правки
    r = TB.build('t32', one_room(300, 400, [door([300, 110]), window([150, 0])]), ctx(bank_120()))['rooms'][0]
    assert r['outcome']['state'] == 'furnished'
    assert {b['sku']['w'] for b in beds(r)} == {150}


def test_template_length_from_real_frames():
    # ядро 210×275: по запасной длине 195 + 60 = 255 «влезает», но самая короткая готовая рама 120 — 226 (226 + 60 > 275) —
    # шаблон честно «мал» (too_small), решатель не тратится
    need_old = TB.bed_need(120, 'single')
    assert need_old[1] == TB.BED_LEN_MIN_CM + 60 and TB.bed_need(120, 'single', 226)[1] == 286
    assert TB.frames_len([]) is None and TB.frames_len([{'d': 226}, {'d': 210}, {'d': None}]) == TB.BED_LEN_MIN_CM
    r = TB.build('t33', one_room(210, 275, [door([210, 110]), window([105, 0])]), ctx(bank_120(('vilena',), d=226)))['rooms'][0]
    assert r['variants'] == []
    for f in r['style_failures']:
        why = {t['template']: t['why'] for t in f['templates']}
        assert why['guest-120'] == why['single-120'] == 'too_small'

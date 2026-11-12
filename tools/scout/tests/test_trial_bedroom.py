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


def test_couple_slim_nightstands_before_next_template(monkeypatch):
    """Лестница тумб пары (T-20261112-95): обычные 45×40 «не встают» парой → узкие 33×32 из запаса банка, та же кровать 160 и тот же
    шаблон пары, а не следующий шаблон; у гостевой (не пара) ступеней нет. Нет узкой в банке — как было (следующий шаблон)."""
    real = TB._solve_kit

    def fake(ad, cand, cfg, kit, purpose):
        return None if kit['тумба прикроватная']['w'] > 36 else real(ad, cand, cfg, kit, purpose)
    monkeypatch.setattr(TB, '_solve_kit', fake)
    bank = []
    for i, st in enumerate(TB.STYLES):
        r = rec(st, item(f'b{i}', 170, sleep=160), item(f's{i}', 45, 40, 50))
        r['alternates'] = {'тумба прикроватная': [item(f'n{i}', 33, 32, 50)]}
        bank.append(r)
    job = TB.build('t17s', plan(sizes=((420, 380),)), ctx(bank))
    r = job['rooms'][0]
    assert r['outcome']['state'] == 'furnished' and len(r['variants']) == len(TB.STYLES)
    for v in r['variants']:
        assert v['template'] == 'couple-160' and v['ns_step'] == 'slim'
        assert [i['w'] for i in v['items'] if i['role'].startswith('тумба')] == [33, 33]
    assert TB.slim_stands([rec('сканди', item('b', 170, sleep=160), item('s', 45, 40, 50))], 'сканди', lambda s: '', None, set()) == []


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
    assert r['bed_frame_max_cm'] == 160                         # 210 − проход 50 (нормы движка, T-96): спрос на кровати уже рамы 160


def test_narrow_room_only_wide_beds_is_no_products_not_no_fit():
    # готовые кровати — только 140 (рама 145), комната 1,85: 140 + проход 50 > 185 — шаблон 140 «больше комнаты», 120 — товаров нет →
    # честное «нет подходящих по размеру товаров» (`no_products`), а не «не встала» (`bed_no_fit`). Проход — норма движка (T-96: прежде
    # 75, и так отсекался лист T 2,1 м; при 50 там рама 145 по размеру проходит и решает решатель)
    job = TB.build('t23', one_room(185, 370, [door([47, 370]), window([92, 0], 150)]), ctx(narrow_bank(145, 140)))
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
    # 1,6×2,6: уже любой кровати шаблонов с проходом (120 + 50, нормы движка, T-96) — «мала», а не «не прочитана» (было `no_core` →
    # not_readable)
    job = TB.build('t26', one_room(160, 260, [door([44, 260]), window([80, 0])]), ctx(narrow_bank()))
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


# ядро 1,8 (нормы движка, T-96: проход у бока 50; прежде то же правило проверялось на 2,05 при проходе 75)
NARROW_OPS = [door([180, 110]), window([90, 0])]


def test_narrow_core_frame_filtered_before_cut():
    # первыми в банке — широкие Кевия 150 и Сейлор 153: раньше они занимали оба места шаблона (BEDS_PER_TEMPLATE) → no_fit; теперь
    # их рама с проходом (150 + 50 > 180) отсеяна до среза — встаёт Вилена 126
    r = TB.build('t30', one_room(180, 370, NARROW_OPS), ctx(bank_120()))['rooms'][0]
    assert r['outcome']['state'] == 'furnished', (r['outcome'], r['style_failures'][:1])
    assert {b['sku']['w'] for b in beds(r)} == {126}
    assert r['bed_frame_max_cm'] == 130


def test_narrow_core_only_wide_frames_honest_bed_no_fit():
    # кровати ширины есть, но ни одна рама с проходами не встаёт → «не встала» (bed_no_fit), а не «нет товаров»
    r = TB.build('t31', one_room(180, 370, NARROW_OPS), ctx(bank_120(('kevia', 'seilor'))))['rooms'][0]
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
    # ядро 210×275: по запасной длине 195 + 50 = 245 «влезает», но самая короткая готовая рама 120 — 226 (226 + 50 > 275) —
    # шаблон честно «мал» (too_small), решатель не тратится. Проход у изножья — норма движка `bed_foot_route` (T-96)
    need_old = TB.bed_need(120, 'single')
    assert need_old[1] == TB.BED_LEN_MIN_CM + 50 and TB.bed_need(120, 'single', 226)[1] == 276
    assert TB.frames_len([]) is None and TB.frames_len([{'d': 226}, {'d': 210}, {'d': None}]) == TB.BED_LEN_MIN_CM
    r = TB.build('t33', one_room(210, 275, [door([210, 110]), window([105, 0])]), ctx(bank_120(('vilena',), d=226)))['rooms'][0]
    assert r['variants'] == []
    for f in r['style_failures']:
        why = {t['template']: t['why'] for t in f['templates']}
        assert why['guest-120'] == why['single-120'] == 'too_small'


# ───────────────────────── правка комнаты агентом (T-20261110-36) ─────────────────────────

def _edited(p, panel, w, d, name=None):
    """Правка комнаты тем же модулем, что у конвейера (`tools/floorplan/room_edits.py`)."""
    sys.path.insert(0, os.path.join(SCOUT, '..', 'floorplan'))
    import room_edits
    e = {'panel': panel, 'srcId': 'r1', 'anchor': {'x': 0.5, 'y': 0.5}, 'name': name or '', 'kind': '', 'wCm': w, 'dCm': d, 'built': False}
    return room_edits.apply(p, [e])[0]


def test_edit_rebuilds_only_dirty_bedroom_others_reused():
    """Правка спальни 2: спальня 1 — та же запись (та же мебель, без перебора), спальня 2 — обставлена заново по новому размеру;
    кровати взятой спальни заняты для новой (`used`)."""
    c = ctx(full_bank())
    first = TB.build('t36', plan(), c)
    p = _edited(plan(), 'p1', 460, 330, 'Спальня гостевая')
    c2 = ctx(full_bank())
    job = TB.build('t36', p, c2, reuse={'prev': first, 'dirty': {('p1', 'r1')}})
    a, b = job['rooms']
    assert a.get('reused') is True and a['variants'] == first['rooms'][0]['variants'] and job['timings']['reused'] == ['bedroom-1']
    assert not b.get('reused') and b['name'] == 'Спальня гостевая' and b['variants']
    assert b['area_m2'] == round(14.4 * 460 / 400 * 330 / 360, 2)
    for v in a['variants']:                                  # заняты ПО СТИЛЮ — ключом, которым их ищет подбор (имя стиля, не style_id)
        taken = {q['sku']['sid'] for q in v['items'] if (q.get('sku') or {}).get('sid')}
        assert taken and {s.replace('_', ':', 1) for s in taken} <= c2['used'][v['style']]   # ключ подбора `_sid` — «mid:eid»
    # пересборка одной комнаты даёт ей ту же мебель, что полная сборка квартиры (взятая спальня стоит раньше — её товары заняты так же)
    full = TB.build('t36', p, ctx(full_bank()))['rooms'][1]
    items = lambda r: [[(q['role'], (q.get('sku') or {}).get('sid'), q['x'], q['y']) for q in v['items']] for v in r['variants']]
    assert items(b) == items(full)


def test_edit_changed_undirty_room_not_reused():
    """Запись прежняя, а комната изменилась (перечитан план): отпечаток другой — обставляем заново, а не берём старое."""
    first = TB.build('t36b', plan(), ctx(full_bank()))
    p = plan(sizes=((430, 380), (400, 360)))
    job = TB.build('t36b', p, ctx(full_bank()), reuse={'prev': first, 'dirty': set()})
    assert [bool(r.get('reused')) for r in job['rooms']] == [False, True]


def test_reuse_survives_server_json_roundtrip():
    """Первая сборка — по своему result.json (433.0), пересборка правки — по результату с сервера, где JS пишет целые без «.0» (433):
    комната та же — запись берётся, а не собирается заново (поймано сквозным прогоном T-36 на плане из объявления)."""
    p = plan()
    first = TB.build('t36e', p, ctx(full_bank()))
    q = json.loads(json.dumps(p))
    for pan in q['panels']:
        for r in pan['rooms']:
            r['contour'] = [[int(c) if float(c).is_integer() else c for c in pt] for pt in r['contour']]
            r['contour'][0][0] = float(r['contour'][0][0])     # и наоборот: целое стало 433.0
    assert TB.room_fp(q['panels'][0]['rooms'][0]) == TB.room_fp(p['panels'][0]['rooms'][0])
    job = TB.build('t36e', q, ctx(full_bank()), reuse={'prev': first, 'dirty': set()})
    assert all(r.get('reused') for r in job['rooms'])


def test_all_reused_needs_no_live_data(monkeypatch):
    """Ничего из спален не правлено (правка кухни): живые данные (банк, каталог) не грузятся — всё из прежней записи."""
    first = TB.build('t36c', plan(), ctx(full_bank()))
    monkeypatch.setattr(TB, 'default_ctx', lambda: (_ for _ in ()).throw(AssertionError('живые данные не нужны')))
    job = TB.build('t36c', plan(), None, reuse={'prev': first, 'dirty': set()})
    assert all(r.get('reused') for r in job['rooms']) and job['status'] == first['status']


def test_user_dims_is_consent_without_approx_flag():
    """Масштаб не подтверждён, агент задал размер спальни правкой (`user_dims`): её обставляем, и это не «примерно» (флага approx нет);
    вторая спальня без согласия — отказ, как раньше."""
    p = _edited(plan('not_verified'), 'p1', 410, 350)
    job = TB.build('t36d', p, ctx(full_bank()))
    a, b = job['rooms']
    assert a['outcome']['state'] == 'scale_unverified'
    assert b['outcome']['state'] == 'furnished' and 'approx_consent' not in b['flags']


def _bank_with_dresser():
    bank = full_bank()
    for i, r in enumerate(bank):
        r['items']['комод'] = item(f'k{i}', 80, 45, 80)
    return bank


def test_dresser_without_wardrobe_when_wardrobe_breaks_template(monkeypatch):
    """T-20261111-06/2: шкаф ломает шаблон (любой набор со шкафом — с проблемой по контуру), комод встаёт — комната не теряет
    предмет: вариант «комод без шкафа», шкаф в `missing_item` как `no_space` (модель есть, места нет)."""
    real = TB._solve_kit

    def fake(ad, cand, cfg, kit, purpose):
        res = real(ad, cand, cfg, kit, purpose)
        return dict(res, score=(1, res['score'][1])) if res and 'шкаф' in kit else res
    monkeypatch.setattr(TB, '_solve_kit', fake)
    r = TB.build('t40', plan(sizes=((420, 380),)), ctx(_bank_with_dresser()))['rooms'][0]
    assert r['outcome']['state'] == 'furnished' and len(r['variants']) == len(TB.STYLES)
    for v in r['variants']:
        roles = {TB.base_role(i['role']) for i in v['items']}
        assert 'комод' in roles and 'шкаф' not in roles
        assert {m['role']: m['why'] for m in v['missing_item']} == {'шкаф': 'no_space'}


def test_wardrobe_and_dresser_both_when_room_allows():
    """Просторная спальня: шкаф и комод стоят вместе (первая проба — самые широкие оба)."""
    r = TB.build('t41', plan(sizes=((460, 420),)), ctx(_bank_with_dresser()))['rooms'][0]
    assert r['outcome']['state'] == 'furnished'
    for v in r['variants']:
        roles = {TB.base_role(i['role']) for i in v['items']}
        assert {'шкаф', 'комод'} <= roles, v['missing_item']


def test_fit_extras_tries_bounded(monkeypatch):
    """Ничего не встаёт: проб не больше обязательных (широкие оба, комод без шкафа, шкаф без комода) + EXTRA_TRIES, и «комод без
    шкафа» среди них есть — перебор размеров не съедает бюджет комнаты (Jsfx20: 30 → 25 предметов на 4 размерах без потолка)."""
    calls = []

    def fake(ad, cand, cfg, kit, purpose):
        calls.append(set(kit))
        return None
    monkeypatch.setattr(TB, 'solve_kit', fake)
    extras = {'шкаф': [item(f'w{i}', 200 - 40 * i, 60, 210) for i in range(3)],
              'комод': [item(f'k{i}', 120 - 20 * i, 45, 80) for i in range(3)]}
    core = {'кровать': item('b', 170, sleep=160), 'тумба прикроватная': item('s', 45, 40, 50)}
    res, kit = TB.fit_extras({}, {}, {}, core, extras, {'purpose': 'couple', 'nightstands': 2}, deadline=float('inf'))
    tries = calls[1:]                                  # первый вызов — сам шаблон (кровать и тумбы)
    assert len(tries) <= 3 + TB.EXTRA_TRIES
    assert any('комод' in k and 'шкаф' not in k for k in tries) and any('шкаф' in k and 'комод' not in k for k in tries)
    assert set(kit) == set(core) and res is None


def test_sliver_gap_is_wall_for_back_check():
    """T-20261111-13 («Этажи», спальня 1): выступ перегородки 20 см у правой стены — ядро 330 при стене 350. Щель уже `TR.SLIVER_CM`
    остатком не считается, у ядра там стена (и в 3D тоже), поэтому шкаф и комод у этой стороны — у стены, не «в воздухе»
    (`room_edge`): спальня получает шкаф и комод. Ниша глубже (55 см, `test_bed_head_not_against_niche_air`) — по-прежнему воздух."""
    from shapely.geometry import Point, Polygon
    c = [[0, 0], [350, 0], [350, 280], [330, 280], [330, 395], [350, 395], [350, 520], [180, 520], [180, 390], [0, 390]]
    room = {'id': 'r1', 'name': 'Bedroom 1', 'kind': 'bedroom', 'contour': c, 'bbox': {'x': 0, 'y': 0, 'w': 350, 'd': 520},
            'areaM2': 14.9, 'flags': []}
    panel = {'id': 'p0', 'title': 'x', 'rooms': [room], 'walls': [],
             'openings': [{'kind': 'door', 'c': [265, 520], 'widthCm': 80, 'exterior': False},
                          {'kind': 'window', 'c': [175, 0], 'widthCm': 150, 'exterior': True}]}
    ad = TB.adapt_room(panel, room, TB.TR.rules())
    cand = next(k for k in ad['candidates'] if abs(k['rect'][2] - k['rect'][0] - 330) <= 1 and k['rect'][3] - k['rect'][1] > 300)
    side = Point(cand['rect'][2], (cand['rect'][1] + 280) / 2)       # правая сторона ядра против щели 20 см
    assert Polygon(c).exterior.distance(side) > TB.BACK_GAP_CM
    assert TB.room_edge(ad, cand).distance(side) <= 1
    p = {'version': 1, 'units': 'cm', 'scale': {'status': 'verified', 'ppm': 100, 'inliers': 3, 'n': 3}, 'flags': [], 'panels': [panel]}
    r = TB.build('t42', p, ctx(_bank_with_dresser()))['rooms'][0]
    assert r['outcome']['state'] == 'furnished'
    assert any({'шкаф', 'комод'} <= {TB.base_role(i['role']) for i in v['items']} for v in r['variants'])


NICHE_FIXTURE = os.path.join(HERE, 'fixtures', 'bedroom-niche-door-iT0X.json')


def test_niche_junction_is_not_a_door_strip():
    """T-20261112-96/2: спальня 7,85 м² тура iT0X — дверь в нише за ядром 330×250. Стык ядра с нишей решатель получает как дверь без
    полотна во всю ширину стыка (`trial_room.solver_openings`); полоса 76 перед ней запирала ядро — после T-68 (окно 70 у бока) кровать
    не вставала ни в один слот. Полоса — только у двери с полотном (как `validate.check_openings`): кровать гостя встаёт на это ядро."""
    from planner.bedroom import _Statics, solve_bedroom
    from planner.models import Item, Opening, Room
    from shapely.geometry import Point
    p = json.load(open(NICHE_FIXTURE, encoding='utf-8'))
    panel, room, rid = TB.bedrooms_of(p)[2]
    assert room.get('name') == 'Bedroom 3' and rid == 'bedroom-3'
    cfg = TB.TR.rules()
    cand = TB.adapt_room(panel, room, cfg)['candidates'][0]
    assert (cand['w'], cand['d']) == (330.0, 250.0)
    r, ops = TB.build_room(cand, cfg, 'left', 'guest')
    assert any(o['kind'] == 'door' and o['swing_cm'] == 0 and o['width_cm'] >= 200 for o in ops)      # стык ниши, не дверь
    lay = solve_bedroom(r, [Item(role='кровать', w_cm=130, d_cm=212, h_cm=85),
                            Item(role='тумба прикроватная', w_cm=42, d_cm=35, h_cm=52)], 'guest')
    assert any(TB.base_role(q.role) == 'кровать' for q in lay.placements), lay.meta.get('clearance')
    # дверь с полотном держит полосу 76 (точка перед дверью вне дуги, 70 см от стены — занята); стык без полотна — только узкую
    # полосу у самой линии (`JUNCTION_STRIP_CM`: спинкой в проём ниши нельзя), 70 см от стены свободно
    def blocked_at(swing, y_off):
        rm = Room(width_cm=400, depth_cm=400, openings=[Opening(kind='door', wall='south', offset_cm=100, width_cm=80, swing_cm=swing,
                                                                hinge='left')], radiators=[], room_type='bedroom', purpose='guest')
        b = _Statics(rm).blocked
        return b is not None and any(b.contains(Point(175, y)) for y in (y_off, 400 - y_off))
    assert blocked_at(80, 70.0) and not blocked_at(0, 70.0) and blocked_at(0, 10.0)


def test_catalog_bed_without_goods_not_in_pool():
    """T-20261112-96/2: кровать каталога без товара (ушла из фида — `catalog_media` None) в подбор не идёт: иначе сборщик подменял её
    крупнейшей кроватью витрины без ширины спального места («Лео», тур iT0X, спальня 2). Каталог недоступен — список прежний."""
    from types import SimpleNamespace as NS
    cat = [NS(mid='1', eid='a'), NS(mid='2', eid='b'), NS(mid='3', eid='c')]
    keep = TB.sellable_catalog(cat, goods=lambda sid: None if sid == '2_b' else {'name': 'x', 'price': 1})
    assert [c.mid for c in keep] == ['1', '3']

    def down(sid):
        raise RuntimeError('каталог недоступен')
    assert TB.sellable_catalog(cat, goods=down) == cat


def _nofit_rig(monkeypatch, refuse):
    """Поддельный решатель: `refuse(items)` → причина отказа (кровать не ставится) или None (кровать и тумба встают)."""
    import planner.bedroom as PB
    from types import SimpleNamespace as NS
    calls = []

    def fake(room, items, purpose):
        calls.append([(i.role, i.w_cm) for i in items])
        why = refuse(items)
        if why:
            return NS(placements=[], meta={'reason': [why]}, violations=[], skipped_optional=[], floor_used_pct=0)
        ps = [NS(role=i.role, x=0, y=0, rot=0, item=i) for i in items]
        return NS(placements=ps, meta={'reason': []}, violations=[], skipped_optional=[], floor_used_pct=30)
    monkeypatch.setattr(PB, 'solve_bedroom', fake)
    monkeypatch.setattr(TB, 'build_room', lambda cand, cfg, hinge, purpose: (NS(openings=[]), []))
    monkeypatch.setattr(TB.TD, 'hard_of', lambda room, ps: [])
    monkeypatch.setattr(TB.TR, 'post_check', lambda ad, cand, ps: {'problems': [], 'ok': True})
    monkeypatch.setattr(TB, 'back_off_wall', lambda ad, cand, ps: [])
    ad = {'memo': {}, 'hinges': TB.HINGES}
    cand = {'area_m2': 8.2, 'rect': (0, 0, 330, 250), 'w': 330, 'd': 250}
    return ad, cand, calls


def test_bed_nofit_memo_skips_solver_for_same_bed(monkeypatch):
    """T-20261112-96/2: кровать не встала на ядре ни на одной петле (BED_NO_FIT) — та же кровать с другой тумбой и в другом стиле
    решателю не идёт (ответ из памяти); иначе медленные отказы съедали долю времени стиля и исход был «budget», а не «не встала»."""
    ad, cand, calls = _nofit_rig(monkeypatch, lambda items: 'BED_NO_FIT')
    bed = {'w': 150, 'd': 212, 'h': 100, 'name': 'Кровать'}
    assert TB.solve_kit(ad, cand, {}, {'кровать': bed, 'тумба прикроватная': {'w': 42, 'd': 35, 'h': 52}}, 'guest') is None
    assert len(calls) == len(TB.HINGES)
    n = len(calls)
    other = {'кровать': dict(bed, name='Та же рама, другой стиль'), 'тумба прикроватная': {'w': 30, 'd': 30, 'h': 45}}
    assert TB.bed_nofit_known(ad, cand, other, 'guest')
    assert TB.solve_kit(ad, cand, {}, other, 'guest') is None and len(calls) == n          # решатель не звали
    # другая рама (ниже, у окна), другое ядро, другое назначение — память не режет
    assert not TB.bed_nofit_known(ad, cand, {'кровать': dict(bed, h=80)}, 'guest')
    assert not TB.bed_nofit_known(ad, dict(cand, rect=(0, 0, 220, 365), area_m2=8.0), other, 'guest')
    assert not TB.bed_nofit_known(ad, cand, other, 'single')


def test_bed_nofit_memo_not_cut_by_stand_refusal(monkeypatch):
    """Отказ из-за тумбы (REQUIRED_NO_FIT) и набор со шкафом — не доказательство для кровати самой по себе: кровать, которая встаёт
    с другой (узкой) тумбой, память не режет."""
    wide = lambda items: 'REQUIRED_NO_FIT' if any(i.role.startswith('тумба') and i.w_cm > 40 for i in items) else None  # noqa: E731
    ad, cand, calls = _nofit_rig(monkeypatch, wide)
    bed = {'w': 150, 'd': 212, 'h': 100, 'name': 'Кровать'}
    assert TB.solve_kit(ad, cand, {}, {'кровать': bed, 'тумба прикроватная': {'w': 50, 'd': 40, 'h': 55}}, 'guest') is None
    assert not ad.get('bed_nofit')
    got = TB.solve_kit(ad, cand, {}, {'кровать': bed, 'тумба прикроватная': {'w': 30, 'd': 30, 'h': 45}}, 'guest')
    assert got is not None and any(TB.base_role(p.role) == 'кровать' for p in got['placements'])
    # BED_NO_FIT в наборе со шкафом в память не идёт (шкаф мог помешать по порядку групп)
    ad2, cand2, _ = _nofit_rig(monkeypatch, lambda items: 'BED_NO_FIT')
    TB.solve_kit(ad2, cand2, {}, {'кровать': bed, 'шкаф': {'w': 100, 'd': 60, 'h': 200, 'name': 'Шкаф'}}, 'guest')
    assert not ad2.get('bed_nofit')

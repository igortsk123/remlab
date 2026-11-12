"""Картины над мебелью в наборах витрины (viz-decor-01 шаг 3, T-20261112-26). Без сети и базы:
  1) подбор: одна картина или пара похожего размера ≈ 2/3 ширины опоры, внутри коридора доли; по высоте — до потолка с зазором;
     стиль варианта; опора по порядку кровать → диван → комод; нет опоры или товара — картины нет;
  2) декор варианта: роль «картина»/«картина 2», стратегия плоскости, Ш×В товара, толщина подрамника, без модели; лента замен;
  3) выключатель (`DEMO_WALL_ART=0`) — ничего не добавляется;
  4) белое поле фото срезается, фото без поля не трогается;
  5) сцена сервера (`draft_render.decor_layout`) картину на столешницу не ставит и вазы со столика не снимает.
    python -m pytest tools/scout/tests/test_wall_art.py -q -p no:cacheprovider"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))   # draft_render держит planner

import wall_art as WA  # noqa: E402

R = WA.rules()
BED = {'role': 'кровать', 'w': 180, 'd': 210, 'h': 110}
SOFA = {'role': 'диван', 'w': 210, 'd': 95, 'h': 85}


def pic(sid, w, h, style='сканди'):
    return {'sid': sid, 'name': f'Картина {sid}', 'price': 3990, 'img': f'https://x/{sid}.jpg', 'url': 'https://x', 'shop': 'divan.ru',
            'w': w, 'd': None, 'h': h, 'style': style, 'styles': [style], 'soft': True}


def test_one_or_pair_near_two_thirds():
    # кровать 180 → цель 120: одна 120 лучше пары 50+50
    assert [p['sid'] for p in WA.pick([pic('a', 50, 70), pic('b', 50, 70), pic('c', 120, 80)], BED, 270, R)] == ['c']
    # одной подходящей нет (90 — 0,5, 40 — мало) → пара 60+60 (130 / 180 = 0,72)
    got = WA.pick([pic('a', 60, 80), pic('b', 60, 80), pic('c', 40, 50)], BED, 270, R)
    assert sorted(p['sid'] for p in got) == ['a', 'b']
    # пара непохожих не собирается
    assert WA.pick([pic('a', 60, 80), pic('b', 30, 30)], BED, 270, R) == []
    # пара одной серии лучше пары разных серий того же размера
    assert WA.series('Картина divan.ru Рельеф-2 Арки Белый 60x60') == 'рельеф'
    mix = [dict(pic('m', 60, 80), name='Картина divan.ru Монстера Бежевый'), dict(pic('a', 60, 80), name='Картина divan.ru Арки Белый'),
           dict(pic('b', 60, 80), name='Картина divan.ru Арки Оливковый')]
    assert sorted(p['sid'] for p in WA.pick(mix, BED, 270, R)) == ['a', 'b']


def test_height_fits_below_ceiling():
    # 270 − 20 − (110 + 22) = 118: картина 120 высотой не влезает, 100 — влезает
    assert WA.headroom(BED, 270, R) == 118
    assert WA.pick([pic('a', 120, 120)], BED, 270, R) == []
    assert WA.pick([pic('a', 120, 100)], BED, 270, R)


def test_support_order():
    assert WA.support([SOFA, BED], R)['role'] == 'кровать'
    assert WA.support([SOFA, {'role': 'комод', 'w': 100, 'h': 85}], R)['role'] == 'диван'
    assert WA.support([{'role': 'стол обеденный', 'w': 160, 'h': 75}], R) is None


def _data():
    return {'room': {'w': 439, 'd': 325, 'height_cm': 270},
            'rooms_geo': {'bedroom-1': {'w': 450, 'd': 293}},
            'apartment_rooms': [{'id': 'living', 'kind': 'living'}, {'id': 'bedroom-1', 'kind': 'bedroom'},
                                {'id': 'hall-1', 'kind': 'hall'}],
            'variants': [{'id': 'set1', 'room_id': 'living', 'style': 'сканди', 'items': [SOFA], 'decor': [{'role': 'ваза'}]},
                         {'id': 'b1', 'room_id': 'bedroom-1', 'style': 'сканди', 'items': [BED], 'decor': []},
                         {'id': 'b2', 'room_id': 'bedroom-1', 'style': 'лофт', 'items': [BED], 'decor': []},
                         {'id': 'h1', 'room_id': 'hall-1', 'style': 'сканди', 'items': [{'role': 'комод', 'w': 100, 'h': 85}]}],
            'feeds': {}}


def test_annotate_decor_rows_and_feeds():
    data = _data()
    pool = [pic('a', 60, 80), pic('b', 60, 80), pic('c', 120, 80), pic('d', 140, 90)]
    got = {vid: names for vid, _, names in WA.annotate(data, pool, R)}
    v = {x['id']: x for x in data['variants']}
    art = [d for d in v['b1']['decor'] if WA.is_art(d, R)]
    assert [d['role'] for d in art] == ['картина']
    assert art[0]['strategy'] == 'procedural_plane'
    assert art[0]['sku']['msid'] is None and art[0]['sku']['d'] == R['depth_cm'] and art[0]['sku']['w'] == 120
    assert [d['role'] for d in v['set1']['decor']] == ['ваза', 'картина']      # диван 210 → 140
    assert got['b2'] == []                                                     # лофта в пуле нет — честно без картины
    assert 'h1' not in got and not any(WA.is_art(d, R) for d in v['h1'].get('decor') or [])
    assert set(data['feeds']) == {'картина', 'bedroom:картина'}
    assert all(p['d'] == R['depth_cm'] and 'soft' not in p for p in data['feeds']['картина'])
    # повторная сборка не вешает вторую картину
    assert all(vid != 'b1' for vid, _, _ in WA.annotate(data, pool, R))


def test_switch_off(monkeypatch):
    monkeypatch.setenv('DEMO_WALL_ART', '0')
    data = _data()
    assert WA.annotate(data, [pic('c', 120, 80)], R) == []
    assert not data['feeds']


def test_crop_white(tmp_path):
    from PIL import Image
    im = Image.new('RGB', (400, 300), (255, 255, 255))
    im.paste((40, 90, 120), (100, 50, 300, 250))
    src, dst = str(tmp_path / 'a.jpg'), str(tmp_path / 'a-art.jpg')
    im.save(src, quality=95)
    assert WA.crop_white(src, dst, R)
    w, h = Image.open(dst).size
    assert abs(w - 200) <= 4 and abs(h - 200) <= 4
    # белая картина на светло-сером фоне: срез шире товара — лишнее снимается по краям до пропорции товара
    gray = Image.new('RGB', (400, 300), (245, 245, 245))
    gray.paste((225, 225, 225), (100, 50, 150, 250))      # тень слева от рамы
    gray.paste((150, 120, 90), (150, 50, 250, 250))       # рама
    gray.paste((255, 255, 255), (155, 55, 245, 245))      # белое полотно
    gsrc, gdst = str(tmp_path / 'g.jpg'), str(tmp_path / 'g-art.jpg')
    gray.save(gsrc, quality=95)
    assert WA.crop_white(gsrc, gdst, R, aspect=0.5)
    gw, gh = Image.open(gdst).size
    assert abs(gw / gh - 0.5) < 0.03
    full = str(tmp_path / 'b.jpg')
    Image.new('RGB', (400, 300), (40, 90, 120)).save(full)
    assert not WA.crop_white(full, str(tmp_path / 'b-art.jpg'), R)


def test_annotate_crop_sets_img_art(tmp_path):
    from PIL import Image
    os.makedirs(tmp_path / 'img')
    im = Image.new('RGB', (400, 400), (255, 255, 255))
    im.paste((10, 10, 10), (50, 50, 350, 350))
    im.save(tmp_path / 'img' / 'p.jpg')
    data = {'variants': [{'decor': [{'role': 'картина', 'strategy': 'procedural_plane', 'sku': {'img': 'img/p.jpg'}},
                                    {'role': 'ваза', 'sku': {'img': 'img/p.jpg'}}]}],
            'feeds': {'bedroom:картина': [{'img': 'img/p.jpg'}]}}
    assert WA.annotate_crop(data, str(tmp_path), R) == (2, 2)
    assert data['variants'][0]['decor'][0]['sku']['img_art'] == 'img/p-art.jpg'
    assert 'img_art' not in data['variants'][0]['decor'][1]['sku']
    assert os.path.exists(tmp_path / 'img' / 'p-art.jpg')


def test_server_frame_keeps_vases_on_table():
    import draft_render as DR
    vase = {'role': 'ваза', 'sku': {'name': 'Ваза', 'w': 20, 'd': 20, 'h': 30}}
    art = {'role': 'картина', 'strategy': 'procedural_plane', 'sku': {'name': 'Картина', 'w': 120, 'd': 2.5, 'h': 80}}
    pay = {'items': [{'role': 'столик', 'x': 200, 'y': 150, 'rot': 0, 'w': 80, 'd': 60, 'h': 45}], 'decor': [vase, art]}
    placed, rest = DR.decor_layout(pay)
    assert [p['decor']['role'] for p in placed] == ['ваза']
    assert rest == [art]

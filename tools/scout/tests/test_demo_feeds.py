"""Ленты замен тура = ленты /demo под место предмета (T-20261110-37, план `tour-as-demo-01`): чтение лент витрины, «влезает в слот»,
лента позиции тура (свои товары первыми, стили — только те, в чьё место влезает), счётчик `feeds_short`, модель у обеденного стола,
подстановка товара ленты на место чужой геометрии."""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import demo_feeds as DF  # noqa: E402
import trial_bundle as TB  # noqa: E402
import trial_demo as TD  # noqa: E402
from planner.models import Item, Placement  # noqa: E402


def row(sid, w, d, styles, name=None, msid='m', img='img/0123456789abcdef.jpg', **kw):
    return dict({'sid': sid, 'name': name or f'товар {sid}', 'w': w, 'd': d, 'h': 75, 'styles': list(styles),
                 'style': styles[0], 'msid': msid, 'img': img}, **kw)


def demo_file(tmp_path, feeds):
    p = tmp_path / 'demo-data.json'
    p.write_text(json.dumps({'feeds': feeds}, ensure_ascii=False), encoding='utf-8')
    return str(p)


def test_load_splits_room_kinds_and_tiles(tmp_path):
    p = demo_file(tmp_path, {'диван': [row('1_a', 200, 90, ['лофт'])],
                             'bedroom:кровать': [row('2_b', 160, 200, ['сканди'], img='img/aaaaaaaaaaaaaaaa.jpg')]})
    d = DF.load(p)
    assert set(d) == {'living', 'bedroom'} and d['bedroom']['кровать'][0]['sid'] == '2_b'
    assert DF.tile_of('2_b', p) == 'img/aaaaaaaaaaaaaaaa.jpg' and DF.tile_of('нет', p) is None
    assert DF.load(str(tmp_path / 'нет.json')) == {}
    assert DF.room_kind('living-2') == 'living' and DF.room_kind('bedroom-1') == 'bedroom' and DF.room_kind('') == 'living'


def test_fits_slot_and_rug_turns():
    assert DF.fits('стол обеденный', {'w': 120.6, 'd': 80}, (120, 80))        # округление каталога
    assert not DF.fits('стол обеденный', {'w': 140, 'd': 80}, (120, 80))
    assert DF.fits('ковёр', {'w': 160, 'd': 230}, (230, 160))                 # ковёр кладут любой стороной
    assert not DF.fits('диван', {'w': 0, 'd': 90}, (200, 90))                 # без размера — не «влезает»


def test_room_feed_own_first_styles_cut_by_slot_and_merge():
    data = {'living': {'стол обеденный': [
        row('1_a', 120, 80, ['лофт', 'сканди']),          # влезает только в место лофта
        row('1_b', 90, 90, ['сканди']),                   # влезает в сканди
        row('1_c', 100, 70, ['лофт'], msid=None),         # без модели — не берём
        row('1_d', 80, 80, ['минимализм']),               # стиль, которого в комнате нет
        row('1_e', 110, 80, ['лофт'], name='свой')]}}     # тот же товар, что свой, — сливается
    own = [{'name': 'свой', 'msid': 'm', 'w': 110, 'd': 80, 'style': 'сканди', 'styles': ['сканди'], 'src': 'set'}]
    slots = {'лофт': [(125, 85)], 'сканди': [(100, 95)]}
    rows, count = DF.room_feed(data, 'living', 'стол обеденный', slots, own)
    assert rows[0]['src'] == 'set' and rows[0]['styles'] == ['сканди', 'лофт']
    by = {r.get('sid'): r for r in rows}
    assert by['1_a']['styles'] == ['лофт'] and by['1_b']['styles'] == ['сканди']
    assert '1_c' not in by and '1_d' not in by and '1_e' not in by
    assert count == {'лофт': 2, 'сканди': 2}


def test_slot_pick_largest_fitting_with_model():
    data = {'living': {'диван': [row('1_a', 180, 90, ['лофт']), row('1_b', 210, 95, ['лофт']), row('1_c', 260, 95, ['лофт']),
                                 row('1_d', 205, 95, ['лофт'], msid=None)]}}
    assert DF.slot_pick(data, 'living', 'диван', 'лофт', (220, 100))['sid'] == '1_b'
    assert DF.slot_pick(data, 'living', 'диван', 'лофт', (220, 100), ok=lambda r: r['w'] < 200)['sid'] == '1_a'
    assert DF.slot_pick(data, 'living', 'диван', 'сканди', (220, 100)) is None


def _variant(style, items, room_id='living'):
    return {'room_id': room_id, 'style': style,
            'items': [{'role': r, 'w': w, 'd': d, 'sku': {'name': f'{r} {style}', 'msid': f'{r}-{style}', 'w': w, 'd': d,
                                                          'img': 'img/0123456789abcdef.jpg'}} for r, w, d in items]}


def test_feeds_for_counts_short_and_rug_has_no_model():
    demo = {'living': {'стол обеденный': [row(f'1_{i}', 100, 80, ['лофт']) for i in range(25)],
                       'ковёр': [row(f'2_{i}', 160, 230, ['лофт'], msid=f'2_{i}') for i in range(3)]},
            'bedroom': {'кровать': [row(f'3_{i}', 160, 200, ['сканди']) for i in range(4)]}}
    variants = [_variant('лофт', [('стол обеденный', 110, 85), ('ковёр', 240, 170)]),
                _variant('сканди', [('кровать', 170, 210)], room_id='bedroom-1')]
    feeds, short = TB.feeds_for(variants, demo)
    assert len(feeds['стол обеденный']) == 26                        # свой + 25 витрины
    assert 'стол обеденный' not in short                              # 26 ≥ 20 — не «мало»
    # мало — с причиной числом: у витрины в стиле всего 3 ковра (`demo`), в место влезли все
    assert short['ковёр'] == {'лофт': {'n': 4, 'demo': 3}} and short['bedroom-1:кровать'] == {'сканди': {'n': 5, 'demo': 4}}
    assert all('msid' not in r for r in feeds['ковёр'])               # ковёр — плита с фото, модели нет
    assert all('sid' not in r for lst in feeds.values() for r in lst) # ключ поставщика в данные страницы не идёт
    feeds0, short0 = TB.feeds_for(variants, None)                     # без витрины — прежние ленты своих товаров
    assert len(feeds0['стол обеденный']) == 1 and short0['стол обеденный'] == {'лофт': {'n': 1, 'demo': 0}}


def test_feeds_for_cuts_by_place_of_scene_not_by_current_product():
    demo = {'living': {'стол обеденный': [row('1_a', 125, 88, ['лофт']), row('1_b', 140, 90, ['лофт'])]}}
    v = _variant('лофт', [('стол обеденный', 110, 85)])
    v[TB.SLOTS_KEY] = {'стол обеденный': [130.0, 90.0]}              # место геометрии крупнее нынешнего стола
    feeds, _ = TB.feeds_for([v], demo)
    assert [r.get('w') for r in feeds['стол обеденный']] == [110, 125]   # 125 влез в место 130, 140 — нет
    assert TB.SLOTS_KEY not in v                                      # служебное поле снято до данных страницы
    v2 = _variant('лофт', [('стол обеденный', 110, 85)])
    feeds2, _ = TB.feeds_for([v2], demo)                              # мест нет (спальня, перевыпуск) — по размеру товара
    assert [r.get('w') for r in feeds2['стол обеденный']] == [110]


def test_dev_flat_is_demo_owner_and_its_uk_twin(tmp_path):
    assert TB.dev_flat() == {'ru': 'flat215', 'en': 'demo-uk-215'}      # реестр репо: хозяйка витрины и её британский двойник
    (tmp_path / 'a.json').write_text(json.dumps({'apartments': [{'id': 'x1', 'sources': {'demoData': '/demo/demo-data.json'}}]}),
                                     encoding='utf-8')
    assert TB.dev_flat(str(tmp_path)) == {'ru': 'x1', 'en': 'x1'}       # двойника нет — та же квартира
    assert TB.dev_flat(str(tmp_path / 'нет')) is None


def test_dining_table_is_mesh_role_rug_is_not():
    assert TD.mesh_role('стол обеденный') and TD.mesh_role('стол обеденный 2') and TD.mesh_role('диван')
    assert not TD.mesh_role('ковёр')


def test_usable_set_swaps_table_without_model_from_feed():
    data = {'living': {'стол обеденный': [row('7_x', 100, 80, ['лофт'], name='Стол из ленты')]}}
    picker = TD.FeedPicker(data, mesh_ok=lambda it: it.get('from_feed', False) or it.get('mid') == 1)
    st = {'style': 'лофт', 'items': {'диван': {'mid': 1, 'w': 200, 'd': 90, 'name': 'Диван прямой'},
                                     'стол обеденный': {'mid': 2, 'w': 110, 'd': 85, 'name': 'Стол без модели'}}}
    got = TD.usable_set(st, picker.mesh_ok, picker)
    assert got['items']['стол обеденный']['name'] == 'Стол из ленты' and got['no_mesh_swapped'] == ['стол обеденный']
    assert got['no_mesh_dropped'] == []
    gone = TD.usable_set(st, picker.mesh_ok, TD.FeedPicker({}, picker.mesh_ok))
    assert 'стол обеденный' not in gone['items'] and gone['no_mesh_dropped'] == ['стол обеденный']


def test_slot_fit_puts_feed_goods_on_foreign_geometry_places():
    def P(role, w, d, corner=False):
        return Placement(role=role, x=100, y=100, rot=0, item=Item(role=role, w_cm=w, d_cm=d, h_cm=80, corner=corner))
    geo = [P('диван', 200, 95), P('тв-тумба', 150, 40), P('тв', 120, 10), P('столик', 80, 50)]
    data = {'living': {'диван': [row('1_s', 195, 90, ['лофт'], name='Диван прямой'),
                                 row('1_c', 190, 90, ['лофт'], name='Диван угловой')],
                       'тв-тумба': [row('2_t', 140, 40, ['лофт'])],
                       'столик': []}}
    picker = TD.FeedPicker(data)
    st = {'style': 'лофт', 'items': {'диван': {'mid': 9, 'w': 230, 'd': 100, 'name': 'Диван прямой'},
                                     'стенка': {'mid': 8, 'w': 220, 'd': 45}, 'столик': {'mid': 7, 'w': 70, 'd': 45}}}
    got, swaps = TD.slot_fit(st, geo, picker)
    it = got['items']
    assert it['диван']['name'] == 'Диван прямой' and it['диван']['w'] == 195   # свой не влез → прямой из ленты (форма места)
    assert 'стенка' not in it and it['тв-тумба']['w'] == 140                    # носитель ТВ — тумба под место
    assert it['столик']['mid'] == 7                                             # свой влезает — остаётся
    assert swaps == ['диван', 'тв-тумба']
    full, swaps2 = TD.slot_fit(st, geo, picker, full=True)
    assert full['items']['столик']['mid'] == 7 and swaps2 == ['диван', 'тв-тумба']   # заменить нечем — свой остаётся
    # место у окна: потолок высоты (`window_caps`, правило WINDOW_BLOCKED) — высокий диван ленты не берём, даже если он крупнее
    data['living']['диван'].append(row('1_t', 198, 92, ['лофт'], name='Диван прямой высокий', h=96))
    assert TD.slot_fit(st, geo, TD.FeedPicker(data))[0]['items']['диван']['w'] == 198
    low, _ = TD.slot_fit(st, geo, TD.FeedPicker(data), caps={'диван': 85})
    assert low['items']['диван']['w'] == 195


def test_window_caps_only_for_places_at_window():
    from planner.models import Opening, Room
    room = Room(width_cm=500, depth_cm=400, openings=[Opening(kind='window', wall='north', offset_cm=150, width_cm=200, sill_cm=90)])
    def P(role, x, y, w, d):
        return Placement(role=role, x=x, y=y, rot=0, item=Item(role=role, w_cm=w, d_cm=d, h_cm=60))
    caps = TD.window_caps(room, [P('диван', 250, 50, 200, 90), P('тв-тумба', 250, 380, 150, 40)])
    assert len(caps) == 1 and list(caps.values()) == [90]


def test_screen_caps_tv_bearer_back_to_window_wall_and_slot_fit_narrows_it():
    """Лофт 4y0opq (T-37): носитель ТВ геометрии стоял спиной к стене с окном (прошёл по вейверу решателя), подставленная тумба шире —
    экран на окне (`SCREEN_OVER_WINDOW`). Потолок экрана — тем же правилом; тумба ленты под место — не шире, чем даёт потолок."""
    from planner.models import Opening, Room
    from planner.tv import screen_width_cm
    room = Room(width_cm=500, depth_cm=400, openings=[Opening(kind='window', wall='south', offset_cm=300, width_cm=150, sill_cm=90)])
    tv = Placement(role='тв-тумба', x=200, y=20, rot=0, item=Item(role='тв-тумба', w_cm=160, d_cm=40, h_cm=60))
    far = Placement(role='тв-тумба', x=200, y=380, rot=180, item=Item(role='тв-тумба', w_cm=160, d_cm=40, h_cm=60))
    caps = TD.screen_caps(room, [tv])
    assert abs(caps['тв-тумба'] - 220) < 0.5                  # экран от центра 200 до окна 300 (+10 см захода) — 2×110
    assert TD.screen_caps(room, [far]) == {}                  # спиной к стене без окна — без потолка
    lim = screen_width_cm(140, 'тв-тумба', 'min') + 1                # экран тумбы 140 влезает, 158 и своей 159 — нет
    data = {'living': {'тв-тумба': [row('2_w', 158, 40, ['лофт']), row('2_n', 140, 40, ['лофт'])]}}
    st = {'style': 'лофт', 'items': {'тв-тумба': {'mid': 1, 'w': 159, 'd': 40}}}
    got, swaps = TD.slot_fit(st, [tv], TD.FeedPicker(data), screens={'тв-тумба': lim})
    assert got['items']['тв-тумба']['w'] == 140 and swaps == ['тв-тумба']
    assert TD.slot_fit(st, [tv], TD.FeedPicker(data))[0]['items']['тв-тумба']['mid'] == 1   # без потолка своя остаётся

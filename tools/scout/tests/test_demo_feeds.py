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
    # строка витрины — товар: фото, магазин, ссылка, цена (T-40: строки без них в ленту тура не идут)
    return dict({'sid': sid, 'name': name or f'товар {sid}', 'w': w, 'd': d, 'h': 75, 'styles': list(styles),
                 'style': styles[0], 'msid': msid, 'img': img, 'url': f'https://shop.example/{sid}', 'shop': 'Магазин', 'price': 10000},
                **kw)


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
                                                          'img': 'img/0123456789abcdef.jpg', 'url': 'https://shop.example/x',
                                                          'price': 9000}} for r, w, d in items]}


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


def test_room_feed_only_goods_band_and_own_gets_goods():
    """T-40 (владелец TG 917/872): в ленте — только товары (фото, магазин, цена) не мельче полосы места; своя строка без товара и тот же
    товар витрины — одна строка С ТОВАРОМ."""
    data = {'living': {'диван': [
        row('1_a', 200, 90, ['лофт']),
        row('1_b', 205, 90, ['лофт'], url=None),            # нет ссылки в магазин — не товар
        row('1_c', 150, 90, ['лофт']),                      # мельче полосы места (0,8 текущего)
        row('1_d', 210, 90, ['лофт'], name='Диван Лофт')]}}  # тот же товар, что свой без товара
    own = [{'name': 'Диван · 210×90 см', 'msid': 'm', 'w': 210, 'd': 90, 'style': 'лофт', 'styles': ['лофт'], 'src': 'set'}]
    rows, count = DF.room_feed(data, 'living', 'диван', {'лофт': [(215, 95)]}, own, lo={'лофт': 168})
    assert [r['name'] for r in rows] == ['Диван Лофт', 'товар 1_a'] and rows[0]['src'] == 'set' and DF.has_goods(rows[0])
    assert count == {'лофт': 2}
    # витрины нет — тур собирается прежним путём: свои строки без товара остаются
    rows0, _ = DF.room_feed({}, 'living', 'диван', {'лофт': [(215, 95)]}, own)
    assert [r['name'] for r in rows0] == ['Диван · 210×90 см']


def test_same_goods_same_model_and_size_untinted_origin_first():
    data = {'bedroom': {'кровать': [row('2_x', 160, 200, ['сканди'], msid='M'), row('M', 160, 200, ['сканди'], msid='M'),
                                    row('2_t', 160, 200, ['сканди'], msid='M', tint='#ffffff')]}}
    assert DF.same_goods(data, 'bedroom', 'кровать', {'msid': 'M', 'w': 160.4, 'd': 200})['sid'] == 'M'   # с которого снята модель
    assert DF.same_goods(data, 'bedroom', 'кровать', {'msid': 'M', 'w': 180, 'd': 200}) is None           # другой размер
    only_tint = {'bedroom': {'кровать': [row('2_t', 160, 200, ['сканди'], msid='M', tint='#ffffff')]}}
    assert DF.same_goods(only_tint, 'bedroom', 'кровать', {'msid': 'M', 'w': 160, 'd': 200}) is None       # фото не того цвета


GEO = {'w': 400, 'd': 300}


def _it(role, x, y, w, d, rot=0, **sku):
    return {'role': role, 'x': x, 'y': y, 'w': w, 'd': d, 'rot': rot, 'sku': dict({'name': role, 'w': w, 'd': d}, **sku)}


def test_free_place_span_to_neighbours_and_walls_capped():
    sofa, chair = _it('диван', 100, 45, 200, 90), _it('кресло', 260, 45, 80, 80)
    rug = _it('ковёр', 200, 150, 240, 170)
    r1 = lambda p: tuple(round(x, 1) for x in p)  # noqa: E731
    assert r1(TB.free_place(sofa, [sofa, chair, rug], GEO)) == (220, 99)    # до кресла 220 (= 1,1 ширины), вглубь — 1,1 глубины
    tight = _it('кресло', 250, 45, 80, 80)
    assert r1(TB.free_place(sofa, [sofa, tight], GEO)) == (210, 99)         # до соседа 210
    assert TB.free_place(sofa, [sofa], {'w': 190, 'd': 300})[0] == 200      # тесно — не меньше своего размера
    assert TB.free_place(rug, [sofa, rug], GEO) == (240, 170)               # ковёр — подложка: место = свой размер
    assert TB.free_place(sofa, [sofa], None) == (200, 90)                   # без коробки комнаты — свой размер
    side = _it('комод', 30, 150, 100, 50, rot=90)                           # повёрнут: «вдоль» — по оси y комнаты
    assert r1(TB.free_place(side, [side], GEO)) == (110, 55)


def test_goods_from_feeds_same_bank_slot_and_wall_edge():
    """Предмет без товара (тур до T-25, перенесённый перевыпуском) — товар: та же модель витрины / товар банка по модели / товар
    витрины по месту (ковёр без модели, стул снятого с продажи товара); край у стены после замены — у стены."""
    demo = {'living': {'диван': [row('S', 200, 90, ['лофт'], msid='S')],
                       'ковёр': [row('R1', 160, 230, ['лофт'], msid='R1'), row('R2', 120, 180, ['лофт'], msid='R2')],
                       'стул': [row('C2', 44, 44, ['лофт'], msid='C2')]}}
    v = {'room_id': 'living', 'style': 'лофт', 'items': [
        _it('диван', 100, 45, 200, 90, msid='S'),
        _it('кресло', 300, 200, 80, 80, msid='K'),
        _it('ковёр', 200, 150, 240, 170),
        _it('стул', 377.5, 22.5, 45, 45, msid='GONE')]}
    bank = {'name': 'Кресло банка', 'img': 'img/k.jpg', 'url': 'https://shop.example/k', 'price': 5000, 'shop': 'Магазин'}
    st = TB.goods_from_feeds([v], demo, lambda sid, role: dict(bank) if sid == 'K' else None, {'living': GEO})
    assert st == {'same': 1, 'bank': 1, 'slot': 2, 'model_only': 0, 'none': 0, 'own': 0}
    sofa, chair, rug, stool = v['items']
    assert sofa['sku']['msid'] == 'S' and sofa['w'] == 200 and DF.has_goods(sofa['sku'])            # модель и место те же
    assert chair['sku']['name'] == 'Кресло банка' and chair['sku']['msid'] == 'K'
    # ковёр: R2 короче дивана (180 < 200) — не берём; R1 длинной стороной вдоль длинной стороны места; модели у плиты нет
    assert (rug['w'], rug['d']) == (230, 160) and rug['sku']['url'].endswith('R1') and 'msid' not in rug['sku']
    # стул: товар снят → товар витрины по месту со своей моделью; стоял в углу — остался в углу
    assert stool['sku']['msid'] == 'C2' and (stool['w'], stool['d']) == (44, 44) and (stool['x'], stool['y']) == (378.0, 22.0)
    # без витрины и без резолвера — ничего не трогаем
    v2 = {'room_id': 'living', 'style': 'лофт', 'items': [_it('стул', 100, 100, 45, 45, msid='GONE')]}
    assert TB.goods_from_feeds([v2], None, None) == {'same': 0, 'bank': 0, 'slot': 0, 'model_only': 0, 'none': 0, 'own': 0}


def test_goods_from_feeds_never_replaces_placed_offer():
    """T-20261112-96/3 (Codex В2): предмет с ключом товара `_sid` (кровать каталога спальни: ушла из продажи, нет плитки фото, каталог
    недоступен) — НЕ подменяется витринным товаром ни по модели, ни по банку, ни по месту: модель, размеры рамы и спального места,
    место — поставленные. Витрина может дать только фото того же товара (строка с тем же `sid`). Предмет без `_sid` — как было."""
    demo = {'bedroom': {'кровать': [row('B9', 160, 200, ['лофт'], msid='MB'), row('1:B1', 180, 210, ['лофт'], msid='MB1')]}}
    bed = _it('кровать', 200, 150, 160, 200, msid='MB', sleep_w=140, h=95, _sid='77_bed')      # той же модели и размера, что B9
    bed2 = _it('кровать', 200, 150, 180, 210, msid='MB1', sleep_w=160, h=95, _sid='1_B1', name='Кровать Б1', price=9000,
               url='https://shop.example/B1', shop='Магазин')                                  # свой товар есть, нет только фото
    legacy = _it('кровать', 200, 150, 150, 200, msid='OLD', sleep_w=140)                      # тур до T-25: без ключа товара
    before = [{k: it['sku'].get(k) for k in ('msid', 'w', 'd', 'h', 'sleep_w', '_sid')} | {k: it[k] for k in ('x', 'y', 'w', 'd')}
              for it in (bed, bed2)]
    vs = [{'room_id': 'bedroom-1', 'style': 'лофт', 'items': [x]} for x in (bed, bed2, legacy)]
    st = TB.goods_from_feeds(vs, demo, lambda sid, role: {'name': 'чужой', 'img': 'img/x.jpg', 'url': 'https://x.example/a', 'price': 1},
                             {'bedroom-1': {'w': 400, 'd': 350}})
    after = [{k: it['sku'].get(k) for k in ('msid', 'w', 'd', 'h', 'sleep_w', '_sid')} | {k: it[k] for k in ('x', 'y', 'w', 'd')}
             for it in (bed, bed2)]
    assert after == before and st['own'] == 1 and st['same'] == 1
    assert 'price' not in bed['sku'] and 'img' not in bed['sku'] and bed['sku']['name'] == 'кровать'      # B9 — другой товар той же модели
    # фото того же товара — с витрины; свои название, цена, ссылка — не тронуты
    assert bed2['sku']['img'] == 'img/0123456789abcdef.jpg' and (bed2['sku']['name'], bed2['sku']['price']) == ('Кровать Б1', 9000)
    assert legacy['sku']['name'] == 'чужой' and st['bank'] == 1           # старый — прежний fallback (товар по модели)


def test_feeds_for_writes_page_band_from_place():
    demo = {'living': {'диван': [row(f'1_{i}', w, 90, ['лофт']) for i, w in enumerate((150, 170, 205, 219, 230))]}}
    sofa, chair = _it('диван', 100, 45, 200, 90, msid='m', img='img/a.jpg', url='https://shop.example/s', price=1), \
        _it('кресло', 260, 45, 80, 80)
    bands: dict = {}
    feeds, _ = TB.feeds_for([{'room_id': 'living', 'style': 'лофт', 'items': [sofa, chair]}], demo, geo={'living': GEO}, bands=bands)
    assert sorted(r['w'] for r in feeds['диван']) == [170, 200, 205, 219]       # 150 мельче 0,8×200, 230 не влезает в 220
    assert bands['диван'] == {'lo': 160, 'side': 'w', 'hi': 221}               # страница режет той же полосой


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

"""Условные шторы и плед гостиной (T-20261112-74): цвет — по названию товара (swatch — только без цвета в названии), тюль и
вуаль — полупрозрачные; место — решатель паспорта (`dependents.resolve`: шторы — `textile.curtains` на окне, плед — `soft.throw`
на краю дивана). Без сети: комната — геометрия гостиной `flat215.json`, предметы — синтетика.
    ~/venvs/scout/bin/python tools/scout/tests/test_textile_abstract.py"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import textile_abstract as TX  # noqa: E402

fails = 0


def ok(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if extra and not cond else ''))
    fails += 0 if cond else 1


# 1) цвет по названию: раннее слово, длинная основа при равном начале; «серия» — не серый
ok('экрю', TX.colour_of_name('Тюль Кассандра экрю') == ('#e6dcc6', 'экрю'))
ok('сливочный раньше экрю', TX.colour_of_name('Вуаль сливочный экрю')[1] == 'сливоч')
ok('оранжевый/темно-серый — первым оранжевый', TX.colour_of_name('Штора оранжевый/темно-серый')[1] == 'оранжев')
ok('темно-серый — не просто серый', TX.colour_of_name('Штора темно-серая')[1] == 'темно-сер')
ok('«Серия» — не цвет', TX.colour_of_name('Штора Серия Лён') is None)
ok('основа — с начала слова: «бел» не в «колыбель»', TX.colour_of_name('Плед Колыбельный') is None)
ok('пусто — None', TX.colour_of_name(None) is None and TX.colour_of_name('') is None)

# 2) look: название → swatch → нейтральный; тюль/вуаль — прозрачные
lk = TX.look_of({'name': 'Вуаль сливочный экрю', 'swatch': '#6a6156'})
ok('название главнее swatch', lk == {'hex': '#eee4cf', 'from': 'name:сливоч', 'sheer': True, 'of': 'Вуаль сливочный экрю'}, lk)
ok('нет цвета в названии — swatch', TX.look_of({'name': 'Штора Пайнон', 'sid': 'p1', 'swatch': '#AABBCC'})
   == {'hex': '#aabbcc', 'from': 'swatch', 'sheer': False, 'of': 'p1'})
ok('ни того, ни другого — нейтральный', TX.look_of({'name': 'Штора Пайнон'})['from'] == 'neutral')
ok('плотная штора — не тюль', not TX.look_of({'name': 'Портьера Квентин серый'})['sheer'])

# 3) место решателем паспорта на гостиной flat215: окно на западной стене, плед — на подлокотнике дивана
geo = json.load(open(os.path.join(HERE, '..', 'flat215.json'), encoding='utf-8'))['rooms'][0]
sofa = {'role': 'диван', 'x': 166, 'y': 280, 'rot': 180, 'w': 162, 'd': 90, 'h': 80}
objs = [sofa, {'role': 'журнальный столик', 'x': 166, 'y': 180, 'rot': 0, 'w': 80, 'd': 50, 'h': 45}]
cur, why = TX.place_of('шторы', objs, geo, {'name': 'Тюль экрю', 'w': 300, 'h': 260}, 270)
wi = next(i for i, o in enumerate(geo['openings']) if o['kind'] == 'window')
ok('шторы: место у окна', cur is not None and cur['kind'] == 'curtain' and cur['opening'] == wi, why or cur)
ok('шторы: стена окна', cur and cur['wall'] == geo['openings'][wi]['wall'], cur)
thr, why = TX.place_of('плед', objs, geo, {'name': 'Плед'}, 270)
ok('плед: место на диване', thr is not None and thr['kind'] == 'throw' and thr['parent'].startswith('seating.sofa'), why or thr)
ok('плед: на высоте сиденья/подлокотника', thr and 30 <= thr['elev_cm'] <= 90, thr)

# 4) annotate: одна штора на окно; без названия — мимо; второй комплект — только список
decor = [{'role': 'шторы', 'sku': {'name': 'Тюль экрю', 'w': 300, 'h': 260}},
         {'role': 'шторы 2', 'sku': {'name': 'Портьера серая', 'w': 300, 'h': 260}},
         {'role': 'плед', 'sku': {'name': 'Плед терракотовый'}}, {'role': 'плед 2', 'sku': {}}]
n = TX.annotate(decor, objs, geo, 'test', 270)
ok('annotate: штора и плед — по одному', n == 2 and [d.get('strategy') for d in decor] == [TX.STRATEGY, None, TX.STRATEGY, None],
   [d.get('strategy') for d in decor])
ok('annotate: цвет пледа по названию', decor[2]['look']['hex'] == '#b8644a', decor[2].get('look'))

# 5) без дивана пледу места нет — строка остаётся без места (только список)
thr0, why0 = TX.place_of('плед', [objs[1]], geo, {'name': 'Плед'}, 270)
ok('плед без дивана — без места, с причиной', thr0 is None and bool(why0), why0)

# 6) ПОДУШКИ (T-20261113-02): габарит стоя у спинки — малая сторона толщина, большая ширина
ok('подушка 45×45×11 — лицо 45×45, толщина 11', TX.pillow_size({'w': 45, 'd': 45, 'h': 11}) == {'w': 45, 'd': 11, 'h': 45})
ok('валик 50×18×18 — вдоль сиденья', TX.pillow_size({'w': 18, 'd': 50, 'h': 18}) == {'w': 50, 'd': 18, 'h': 18})
ok('без размеров — типовая', TX.pillow_size({}) == {'w': 45.0, 'd': 12.0, 'h': 45.0})

# 7) по месту на строку на сиденье дивана; без модели — условная цветом товара, с моделью — msid и габарит по мешу
pil = [{'role': 'подушка', 'sku': {'name': 'Подушка Линкс бежевая', 'sid': 'a_1', 'w': 45, 'd': 45, 'h': 11}},
       {'role': 'подушка 2', 'sku': {'name': 'Подушка Удина серая', 'sid': 'a_2', 'w': 45, 'd': 45, 'h': 11, 'msid': None}}]
model = lambda sk: ('m1', (1.99, 1.95, 0.72)) if sk['sid'] == 'a_1' else (None, 'нет модели на сервере')  # noqa: E731
n = TX.annotate(pil, objs, geo, 'test', 270, model)
p0, p1 = pil[0].get('place') or {}, pil[1].get('place') or {}
ok('подушки: обе с местом', n == 2 and all(d.get('strategy') == TX.STRATEGY for d in pil), [d.get('place') for d in pil])
ok('подушки: разные места на одном диване', p0.get('slot_instance_id') == 'soft.pillows#0' and p1.get('slot_instance_id') == 'soft.pillows#1'
   and p0.get('parent') == p1.get('parent') and str(p0.get('parent')).startswith('seating.sofa'), (p0, p1))
ok('подушки: на высоте сиденья', 40 <= p0.get('elev_cm', 0) <= 50, p0)
ok('подушки: в следе дивана', all(abs(p['x'] - sofa['x']) < sofa['w'] / 2 and abs(p['y'] - sofa['y']) < sofa['d'] / 2 for p in (p0, p1)),
   (p0, p1))
ok('подушки: лицом как диван', p0.get('rot') == sofa['rot'] and p0.get('kind') == 'pillow', p0)
ok('с моделью — msid и габарит по мешу одним масштабом', pil[0]['sku'].get('msid') == 'm1' and p0['w'] == 45 and 15 < p0['d'] < 17
   and 43 < p0['h'] < 45, (pil[0]['sku'], p0))
ok('без модели — условная: msid пуст, габарит товара, цвет по названию', not pil[1]['sku'].get('msid') and p1['d'] == 11
   and pil[1]['look']['hex'] == '#9a9c9e', (pil[1]['sku'], p1, pil[1].get('look')))
ok('служебный размер в строку не утёк', all('_size' not in d for d in pil))
# центр подушки — на толщину вперёд от спинки: диван смотрит на юг (rot 180) — подушка ближе к стене дивана, чем его центр
ok('подушка у спинки, не на краю сиденья', sofa['y'] < p0['y'] < sofa['y'] + sofa['d'] / 2, p0)

# 8) подушек больше, чем влезает на узкий диван — лишняя только в списке; без дивана — ни одной
narrow = [dict(sofa, w=120)] + objs[1:]
many = [{'role': f'подушка {i}' if i else 'подушка', 'sku': {'name': f'Подушка {i}', 'w': 45, 'd': 45, 'h': 11}} for i in range(3)]
ok('узкий диван: две из трёх', TX.annotate(many, narrow, geo, 'test', 270) == 2 and many[2].get('place') is None,
   [d.get('place') for d in many])
none = [{'role': 'подушка', 'sku': {'name': 'Подушка'}}]
ok('без дивана — без места', TX.annotate(none, [objs[1]], geo, 'test', 270) == 0 and 'place' not in none[0])

# 9) ЦВЕТ И МОДЕЛЬ — ОТ ТОВАРА, КОТОРЫЙ СТОИТ (T-20261113-02/2; витрина b345e311: вторая подушка вариантов 0, 1, 4 — look.of
# прежнего товара, страница её из 3D снимала). Разметка — после замены мягкого; модель из ленты замены не остаётся; сторож снимает
# место у строки, чей товар сменили после разметки
import ast  # noqa: E402
SRC = open(os.path.join(HERE, '..', 'flat215_demo.py'), encoding='utf-8').read()
FUNCS = {f.name: ast.get_source_segment(SRC, f) for f in ast.parse(SRC).body if isinstance(f, ast.FunctionDef)}
b = FUNCS['build']
ok('сборка: разметка тканей — после замены мягкого, один раз', b.count('_TX.annotate(') == 1
   and b.index('soft_fixed.append(') < b.index('_TX.annotate('))
ok('сборка: замена мягкого обнуляет модель', "d['sku']['msid'] = None" in b)
ok('сборка: сторож цвета перед записью данных', FUNCS['main'].index('look_guard(') < FUNCS['main'].index("'demo-data.json'), data"))
swap = [{'role': 'подушка', 'sku': {'name': 'Подушка Удина Рогожка Серый', 'sid': 'u_1', 'w': 45, 'd': 45, 'h': 11, 'msid': 'feed_m'}}]
TX.annotate(swap, objs, geo, 'test', 270, lambda sk: (None, 'нет модели на сервере'))
ok('после замены: look.of — ключ товара, модель ленты снята', swap[0]['look']['of'] == 'u_1' and swap[0]['sku']['msid'] is None
   and swap[0]['look']['hex'] == '#9a9c9e', swap[0])
var = [{'id': 'set1', 'decor': [dict(pil[0]), dict(pil[1], sku={'name': 'Подушка Винси бежевая', 'sid': 'v_9'})]}]
lines = TX.look_guard(var)
ok('сторож: чужой цвет — место и цвет сняты, строка в списке', len(lines) == 1 and 'set1' in lines[0]
   and 'place' not in var[0]['decor'][1] and 'look' not in var[0]['decor'][1] and var[0]['decor'][1]['sku']['sid'] == 'v_9', lines)
ok('сторож: свой цвет — строка не тронута', 'place' in var[0]['decor'][0] and var[0]['decor'][0]['look']['of'] == 'a_1')

# 10) ЛЕНТЫ ТКАНЕЙ НЕСУТ ЦВЕТ И МОДЕЛЬ (T-20261113-24, владелец TG 1629: замена подушки на странице — подушка исчезала из 3D):
# у каждого товара ленты штор, пледа, подушек — свой look; у подушки — модель только проверенная, размер по карточке/мешу
feeds = {'подушка': [{'name': 'Подушка Homelines зеленый 45х45', 'sid': 'h_1', 'w': 45, 'd': 45, 'h': 11, 'msid': None},
                     {'name': 'Подушка Удина Серый', 'sid': 'm_2', 'w': 45, 'd': 45, 'h': 11}],
         'плед': [{'name': 'Плед Ваби бежевый', 'sid': 't_1'}], 'bedroom:шторы': [{'name': 'Тюль Кассандра экрю', 'sid': 'c_1'}],
         'ваза': [{'name': 'Ваза белая', 'sid': 'v_1'}]}
model = lambda sk: (('m_2', (1.0, 1.0, 0.25)) if sk['sid'] == 'm_2' else (None, 'нет модели на сервере'))  # noqa: E731
line = TX.annotate_feeds(feeds, model)
ok('ленты: цвет у всех тканей (подушки, плед, шторы спальни)', all(p.get('look', {}).get('of') == p['sid']
   for k in ('подушка', 'плед', 'bedroom:шторы') for p in feeds[k]), feeds)
ok('ленты: цвет нового товара — его, а не прежнего', feeds['подушка'][0]['look']['hex'] == '#6f8a63', feeds['подушка'][0]['look'])
ok('ленты: не ткань — без цвета', 'look' not in feeds['ваза'][0] and 'pillow' not in feeds['плед'][0])
p0, p1 = feeds['подушка'][0]['pillow'], feeds['подушка'][1]['pillow']
ok('ленты: подушка без модели — условная, размер по карточке', p0 == {'msid': None, 'w': 45.0, 'd': 11.0, 'h': 45.0}, p0)
ok('ленты: подушка с проверенной моделью — msid и размер по мешу', p1['msid'] == 'm_2' and p1['w'] == 45.0, p1)
ok('ленты: строка отчёта', 'подушек 2 (с моделью 1)' in line, line)
ok('сборка: ленты тканей размечаются перед записью данных', FUNCS['main'].index('annotate_feeds(') < FUNCS['main'].index("'demo-data.json'), data"))

print('ИТОГ:', 'всё OK' if not fails else f'{fails} FAIL')
sys.exit(1 if fails else 0)

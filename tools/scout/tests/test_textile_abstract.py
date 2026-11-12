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

print('ИТОГ:', 'всё OK' if not fails else f'{fails} FAIL')
sys.exit(1 if fails else 0)

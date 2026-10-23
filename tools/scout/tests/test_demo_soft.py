"""Мягкое комплекта — в списке и в «Улучшить фото», но не в 3D (demo-24, владелец 23.10). Без сети, базы и модели.

Владелец: «они должны быть в списке, но появляться на 3D-модели не должны, а отправляться в GPT должны; нет смысла из них меши
делать». Стенд проверяет:
  1) роли — одно правило канона: `asset_strategy.soft_roles` (стратегия cutout без настольного декора) = экспорт = сцена сервера;
  2) экспорт кладёт мягкое строками варианта без модели (`msid` пуст), лента замен мягкого — без конверта размера и меша;
  3) сцена сервера (`decor_layout`) мягкое не ставит — ни на столешницу, ни в «дорисовать как декор»;
  4) запрос «Улучшить»: мягкое — третьим листом и местом словами, шторы товаром вместо «шторы под стиль», исключение из правила
     «не выдумывать подушки»; без мягкого текст прежний; третий лист реально уходит в модель.
    ~/venvs/scout/bin/python tools/scout/tests/test_demo_soft.py"""
import ast
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
fails = 0


def check(name, cond, info=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    fails += 0 if cond else 1


import asset_strategy as AS  # noqa: E402
import draft_render as DR  # noqa: E402
import flat215_demo as F  # noqa: E402
import improve_mode as IM  # noqa: E402

# 1) роли
check('канон: мягкое = cutout без настольных часов', AS.soft_roles() == {'плед', 'подушка', 'покрывало', 'полка', 'шторы'},
      str(AS.soft_roles()))
check('экспорт и сцена сервера — то же правило', set(F.soft_roles()) == AS.soft_roles()
      and all(F.soft_role(r) and DR.soft_role(r) for r in ('подушка', 'подушка 2', 'шторы', 'плед')))
check('ваза, часы, диван — не мягкое', not any(F.soft_role(r) or DR.soft_role(r) for r in ('ваза', 'часы', 'диван', 'кресло 2')))
check('мягкому меш не положен (канон)', AS.soft_roles() <= AS.non_mesh_roles() and AS.soft_roles() <= F.NOMESH_ROLES | {'полка'})

# 2) экспорт: строка ленты мягкого
keep = (sys.modules.get('img_alive'), F._basis, F._pack_of)
import types  # noqa: E402
sys.modules['img_alive'] = types.SimpleNamespace(alive_now=lambda u: True)
F._basis = lambda mid, eid: 'feed'
F._pack_of = lambda mid, eid, name: 1
try:
    curt = {'mid': 1, 'eid': 'c', 'name': 'Шторы', 'price': 10459, 'w': 260, 'd': None, 'h': 300, 'img': '//i/c.jpg', 'url': 'https://s/c'}
    row = F.set_feed_row('шторы', curt, 'сканди')
    check('лента: шторы без глубины — в ленте (конверта размера нет)', bool(row) and row['price'] == 10459, str(row))
    check('лента: у мягкого нет модели', bool(row) and row['msid'] is None and row.get('soft') is True)
    check('лента: без ссылки в магазин или цены — нет строки',
          F.set_feed_row('шторы', {**curt, 'url': None}, 'сканди') is None
          and F.set_feed_row('подушка', {**curt, 'price': None}, 'сканди') is None)
finally:
    if keep[0] is None:
        sys.modules.pop('img_alive', None)
    else:
        sys.modules['img_alive'] = keep[0]
    F._basis, F._pack_of = keep[1], keep[2]

SRC = open(os.path.join(HERE, '..', 'flat215_demo.py'), encoding='utf-8').read()
FUNCS = {n.name: ast.get_source_segment(SRC, n) for n in ast.parse(SRC).body if isinstance(n, ast.FunctionDef)}
check('экспорт варианта: мягкое — в список варианта, модель обнулена',
      "soft = soft_role(role)" in FUNCS['build'] and "sk['msid'] = None" in FUNCS['build'])
check('данные: правило ролей уходит странице (rules.soft_roles)', "'soft_roles': soft_roles()" in FUNCS['build'])

# 3) сцена сервера
pay = {'items': [{'role': 'столик', 'x': 200, 'y': 150, 'rot': 0, 'w': 120, 'd': 60, 'h': 40}],
       'decor': [{'role': 'ваза', 'sku': {'name': 'Ваза', 'w': 15, 'd': 15, 'h': 25}},
                 {'role': 'подушка', 'sku': {'name': 'Подушка', 'w': 45, 'd': 45, 'h': 11}},
                 {'role': 'шторы', 'sku': {'name': 'Шторы', 'w': 260, 'h': 300}}]}
placed, rest = DR.decor_layout(pay)
check('сцена: ваза — на столике', [p['decor']['role'] for p in placed] == ['ваза'])
check('сцена: мягкого нет ни в поставленном, ни в «дорисовать как декор»',
      not any(DR.soft_role(d['role']) for d in rest) and not any(DR.soft_role(p['decor']['role']) for p in placed))

# 4) запрос «Улучшить»
soft = IM.soft_items(pay)
check('запрос: мягкое берётся из списка варианта', [d['role'] for d in soft] == ['подушка', 'шторы'])
sl = IM.soft_list(soft, 1, pay['items'] + [{'role': 'диван'}])
check('место словами: подушка — на диване, шторы — на окне',
      'sofa' in sl[0]['place'] and 'window' in sl[1]['place'] and sl[0]['size_cm'] == '45×45' and sl[1]['size_cm'] == '260×300', str(sl))
th = IM.soft_list([{'role': 'плед', 'sku': {'name': 'Плед'}}], 1, [{'role': 'кресло'}])
th2 = IM.soft_list([{'role': 'плед', 'sku': {'name': 'Плед'}}], 1, [{'role': 'диван'}])
check('плед — на кресле, без кресла — на подлокотнике дивана', 'armchair' in th[0]['place'] and 'sofa arm' in th2[0]['place'])
p0 = IM.prompt_for('сканди')
p1 = IM.prompt_for('сканди', None, None, None, None, None, sl)
check('без мягкого: две картинки и «шторы под стиль», блока нет',
      p0.startswith('You are given TWO images') and 'DRESS THE WINDOW WITH CURTAINS' in p0 and 'SOFT TEXTILES' not in p0)
check('с мягким: три картинки, блок SOFT TEXTILES со списком', p1.startswith('You are given THREE images')
      and 'SOFT TEXTILES FROM IMAGE 3 — MUST BE ADDED' in p1 and '"item": "cushion"' in p1)
check('с мягким: шторы — товар с листа, не «под стиль»', 'HANG THE CURTAINS FROM IMAGE 3 (#2)' in p1
      and 'DRESS THE WINDOW WITH CURTAINS' not in p1)
check('с мягким: исключение из «не выдумывать подушки» — в жёстких правилах',
      'EXCEPTION: the cushions and throws listed under SOFT TEXTILES' in p1
      and p1.index('EXCEPTION: the cushions') < p1.index('STYLE GUIDE'))
pd = IM.prompt_for('сканди', [{'role': 'ваза'}], None, None, None, None, IM.soft_list(soft, 2, pay['items']))
check('декор и мягкое вместе: декор — по своим номерам на опору, мягкое — после',
      'Every decor item on IMAGE 3 (#1)' in pd and 'HANG THE CURTAINS FROM IMAGE 3 (#3)' in pd)
RSRC = open(os.path.join(HERE, '..', 'draft_render.py'), encoding='utf-8').read()
check('третий лист уходит в модель (был только в тексте)', "built.get('dsheet') is not None and 'IMAGE 3' in prompt" in RSRC)
ISRC = open(os.path.join(HERE, '..', 'improve_mode.py'), encoding='utf-8').read()
check('оба сборщика отдают третий лист и мягкое в промпт',
      ISRC.count("'dsheet': dsheet") == 2 and ISRC.count('soft_list(soft, len(decor) + 1') == 2)

ASRC = open(os.path.join(HERE, '..', 'scene_artifacts.py'), encoding='utf-8').read()
check('ночная проверка сцены не ищет модель у мягкого', '_AS.soft_roles()' in ASRC)

print('итог:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)

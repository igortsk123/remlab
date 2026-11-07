"""Комната без выбранного стиля — молча похожий вариант (план style-fallback-01, владелец 07.11 TG 309, вариант А). Без сети и базы.

Проверяет правило `demo_room.style_fallback` и запись карты сборкой (`flat215_demo.room_style_fallback`):
  1) неоклассика есть только в гостиной → спальни и прихожая получают соседа «легко спутать» (современный) первым;
  2) у стиля два соседа в комнате → ближе по палитре опроса (`colour_sim` = `quizSim`), без палитры — порядок вкладок;
  3) комната со всеми стилями и комната без вариантов (кухня) в карту не попадают; стиль, которого нет нигде, — не вкладка, не ключ;
  4) все комнаты полные → поля в данных нет (данные прежние байт в байт); ключи карты — латинские id стилей страницы.
    ~/venvs/scout/bin/python tools/scout/tests/test_style_fallback.py"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import demo_room as R  # noqa: E402

fails = 0


def check(name, cond, info=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    fails += 0 if cond else 1


FIVE = ['сканди', 'современный', 'минимализм', 'лофт', 'джапанди']
TABS = FIVE[:4] + ['неоклассика', 'джапанди']

# 1) неоклассика только в гостиной
rooms = {'living': TABS, 'bedroom-1': FIVE, 'bedroom-2': FIVE, 'hall': FIVE}
fb = R.style_fallback(rooms, TABS)
check('гостиная полная — в карте её нет', 'living' not in fb, fb)
check('спальни и прихожая: неоклассика → современный первым (сосед из confusable_pairs)',
      all(fb.get(r, {}).get('неоклассика', [None])[0] == 'современный' for r in ('bedroom-1', 'bedroom-2', 'hall')), fb)
check('замена — только из стилей самой комнаты, все по одному разу',
      sorted(fb['hall']['неоклассика']) == sorted(FIVE), fb.get('hall'))
check('в комнате нет ничего, кроме неоклассики — подменять больше нечего', list(fb['hall']) == ['неоклассика'], fb.get('hall'))

# 2) у минимализма соседи современный, джапанди и сканди — решает палитра, без неё порядок вкладок
room2 = {'living': TABS, 'hall': ['сканди', 'современный', 'джапанди', 'лофт']}
plain = R.style_fallback(room2, TABS)['hall']['минимализм']
check('без палитры: соседи по порядку вкладок (сканди, современный, джапанди), не-сосед (лофт) последним',
      plain == ['сканди', 'современный', 'джапанди', 'лофт'], plain)
col = {'минимализм': {'light': 0.6, 'cool': 0.4}, 'сканди': {'light': 0.2, 'warm': 0.8},
       'современный': {'light': 0.5, 'cool': 0.5}, 'джапанди': {'warm': 1.0}, 'лофт': {'light': 0.6, 'cool': 0.4}}
by_col = R.style_fallback(room2, TABS, colours=col)['hall']['минимализм']
check('с палитрой: среди соседей ближе по цвету первым (современный), не-сосед лофт — после соседей, хоть и одинаковый по цвету',
      by_col == ['современный', 'сканди', 'джапанди', 'лофт'], by_col)
check('мера = quizSim: одинаковые палитры — 1, без общего — 0',
      R.colour_sim({'a': 1}, {'a': 1}) == 1 and R.colour_sim({'a': 1}, {'b': 1}) == 0)

# 3) пустая комната и стиль, которого нет нигде
fb3 = R.style_fallback({'living': FIVE, 'kitchen': [], 'hall': ['лофт']}, FIVE)
check('кухня без вариантов — нет в карте (у неё остаётся плашка)', 'kitchen' not in fb3, fb3)
check('прихожая с одним лофтом — все остальные вкладки → лофт', fb3['hall'] == {s: ['лофт'] for s in FIVE if s != 'лофт'}, fb3)
check('неоклассики нет ни в одной комнате — не вкладка и не ключ', all('неоклассика' not in m for m in fb3.values()))

# 4) запись сборкой: id страницы и «полные комнаты — поля нет»
try:
    import flat215_demo as F
    F.quiz_colours = lambda vs, pal, root: {}          # node и палитра здесь не нужны — равенство решает порядок вкладок
    F.living_room_id = lambda: 'living'
    V = lambda room, st: {'id': f'{room}-{st}', 'style': st, 'room_id': room}  # noqa: E731
    full = {'variants': [V(r, s) for r in ('living', 'bedroom-1') for s in FIVE]}
    check('все комнаты со всеми стилями — пусто (сборка поле не пишет)', F.room_style_fallback(full, '.') == {})
    part = {'variants': [V('living', s) for s in TABS] + [V('bedroom-1', s) for s in FIVE] + [{'id': 'mine', 'mine': True, 'style': 'лофт'}]}
    got = F.room_style_fallback(part, '.')
    check('сборка: {комната: {id вкладки: [id стилей]}} — bedroom-1: neoclassic → modern первым',
          list(got) == ['bedroom-1'] and list(got['bedroom-1']) == ['neoclassic'] and got['bedroom-1']['neoclassic'][0] == 'modern', got)
except ImportError as e:
    print(f'SKIP сборка: {e}')

print(f'test_style_fallback: fails {fails}')
sys.exit(1 if fails else 0)

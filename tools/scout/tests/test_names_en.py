"""Английские названия товаров витрины (план demo-31, T-20261030-01): 0 кириллицы, 0 доменов и названий магазинов, размеры
сохранены — на всех товарах текущей витрины (русские названия — из `data/names-en.json`, он снят с витрины 30.10; живой
`~/scout-scenes/flat215-demo/demo-data.json` — если есть) и словарём для «новых» товаров ночных фидов. Без сети.
    ~/venvs/scout/bin/python tools/scout/tests/test_names_en.py"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import names_en as N  # noqa: E402

LIVE = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
SHOPS = re.compile(r'divan\.?ru|tvoydom|mnogomebeli|ormatek|орматек|divanboss|\.ru\b|\.com\b', re.I)
fails = 0


def check(name, cond, info=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    fails += 0 if cond else 1


def sizes(ru: str) -> list:
    """Размеры из русского названия так, как их пишет английское: «120х80» → «120x80», «32,5» → «32.5», «160*200» → «160x200»."""
    s = re.sub(r'(?<=\d)\s*[хХxX×*]\s*(?=\d)', 'x', ru).replace(',', '.')
    out = re.findall(r'\d+(?:\.\d+)?(?:x\d+(?:\.\d+)?)+', s)
    out += re.findall(r'(\d+(?:\.\d+)?)\s*(?:см|мм)', s)
    return out


def clean_en(name: str, ru: str) -> list:
    """Что не так с английским названием: кириллица, магазин, потерянный размер."""
    why = []
    if N.CYR.search(name):
        why.append('кириллица')
    if SHOPS.search(name):
        why.append('магазин')
    why += [f'нет размера {z}' for z in sizes(ru) if z not in name]
    return why


def main():
    D = N.load_dict()
    M = N.load_map()
    check('names-en.json: есть записи текущей витрины (≥ 900)', len(M) >= 900, len(M))
    # 1) ручной перевод — каждая запись чистая и с размерами
    bad = {v['ru']: clean_en(v['name'], v['ru']) for v in M.values() if clean_en(v['name'], v['ru'])}
    check('names-en.json: 0 кириллицы, 0 магазинов, размеры на месте', not bad, list(bad.items())[:5])
    check('names-en.json: у каждой записи ru/name, colour — хвост названия',
          all(v.get('ru') and v.get('name') and (not v.get('colour') or v['name'].endswith(v['colour'])) for v in M.values()))
    # 2) словарь без ручного перевода — так пойдут новые товары ночных фидов
    bad, neutral = {}, []
    for v in M.values():
        r = N.translate(v['ru'], '', D)
        if r['how'] == 'neutral':
            neutral.append(v['ru'])
        elif clean_en(r['name'], v['ru']):
            bad[v['ru']] = (r['name'], clean_en(r['name'], v['ru']))
    check('словарь на всех названиях витрины: 0 кириллицы, 0 магазинов, размеры на месте', not bad, list(bad.items())[:5])
    check('словарь на всех названиях витрины: нейтральных нет', not neutral, neutral[:5])
    # 3) образцы словаря
    for ru, want in [('Диван прямой divan.ru Викс Рогожка Серый', 'Viks straight sofa, grey woven fabric'),
                     ('Журнальный стол divan.ru Лори Ореx', 'Lori coffee table, walnut'),
                     ('Ковер divan.ru Котри Серый 140х200', 'Kotri rug 140x200, grey'),
                     ('Кровать Орматек Тест 160*200 Велюр Синий', 'Test bed 160x200, blue velour'),
                     ('Ваза Glasar с ручками 16х16х18см', 'Glasar vase with handles 16x16x18 cm')]:
        got = N.translate(ru, '', D)['name']
        check(f'словарь: «{ru}» → «{want}»', got == want, got)
    r = N.translate('Диван угловой divan.ru Зефирка Велюр Изумрудный', 'диван', D)
    check('новая модель и цвет вне словаря — транслитерация, без кириллицы', not N.CYR.search(r['name']) and
          r['translit'] == ['Зефирка', 'Изумрудный'], r)
    r = N.translate('Кресло mnogomebeli.com Ӧлӧ', 'кресло', D)
    check('осталась кириллица вне таблицы — нейтральное по роли', r['how'] == 'neutral' and r['name'] == 'Armchair', r)
    check('нейтральное у роли с номером («стул 2») и без роли', N.neutral('стул 2', D) == 'Chair' and N.neutral('', D))
    # 4) ручной перевод берётся, только пока русское название то же
    sid, v = next(iter(M.items()))
    p = {'sid': sid, 'name': v['ru'], 'price': 1}
    check('перевод по sid', N.name_en(p, '', M, D)['how'] == 'map')
    p2 = dict(p, name='Диван прямой divan.ru Викс Велюр Серый')
    check('магазин переименовал товар — перевод заново словарём', N.name_en(p2, '', M, D)['how'] == 'dict')
    # 5) annotate: роли по месту и поле у каждого товара
    data = {'variants': [{'items': [{'role': 'диван', 'sku': {'name': 'Диван divan.ru Ӧ', 'price': 1}}],
                          'decor': [{'role': 'подушка 2', 'sku': {'name': 'Подушка divan.ru Ӧ', 'price': 1}}]}],
            'feeds': {'ковёр': [{'name': 'Ковер Ӧ', 'price': 1}]}, 'sofa_feed': [{'name': 'Ӧ', 'price': 1}],
            'sets': [{'roles': {'торшер': {'name': 'Ӧ', 'price': 1}}}],
            'bedroom_catalog': {'roles': {'кровать': [{'name': 'Ӧ', 'price': 1}]}}}
    rep = N.annotate(data, {}, D)
    got = [p['name_en'] for p, _ in N.products(data)]
    check('annotate: роли по месту (предмет, декор с номером, лента, sofa_feed, комплект, спальня)',
          got == ['Sofa', 'Cushion', 'Rug', 'Sofa', 'Floor lamp', 'Bed'], got)
    check('annotate: отчёт считает нейтральные', rep['neutral'] == 6 and rep['items'] == 6, rep)
    # 6) живая витрина — все товары
    if os.path.exists(LIVE):
        live = json.load(open(LIVE, encoding='utf-8'))
        rep = N.annotate(live, M, D)
        prods = N.products(live)
        bad = [(p['name'], p.get('name_en'), clean_en(p.get('name_en') or '', p['name'])) for p, _ in prods
               if not p.get('name_en') or clean_en(p['name_en'], p['name'])]
        check(f'живая витрина: у всех {len(prods)} товаров name_en без кириллицы и магазина, с размерами', not bad, bad[:5])
        check('живая витрина: нейтральных нет', rep['neutral'] == 0, rep['neutral_names'][:5])
        print('     ' + N.report_lines(rep)[0])
    else:
        print('SKIP живая витрина — файла нет')
    print('FAILS', fails)
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

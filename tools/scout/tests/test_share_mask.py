"""Страница подборки «отправить себе» по британской маске английского демо (demo-31): при `mask: true` — £, английские подписи, без
магазина и ссылки; без маски — ₽, магазин и ссылка, как было. Функции берём разбором исходника — импорт `draft_service` тянет рендер.
    ~/venvs/scout/bin/python tools/scout/tests/test_share_mask.py"""
import ast
import html
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'draft_service.py')
NAMES = {'SHARE_PAGE', 'SHARE_PAGE_EN', '_share_opts', '_share_money', '_share_prod', '_share_block', '_share_page'}
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


# безопасный адрес — как у `draft_guard.safe_url` по сути: http(s), путь сайта или картинка витрины
ns = {'esc': html.escape, 'safe_url': lambda u: u if re.match(r'^(https?://|/|img/)', str(u or '')) else ''}
for n in ast.parse(open(SRC, encoding='utf-8').read()).body:
    if (isinstance(n, ast.FunctionDef) and n.name in NAMES) or \
            (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') in NAMES for t in n.targets)):
        exec(compile(ast.Module([n], []), SRC, 'exec'), ns)
page = ns['_share_page']

RU_ITEMS = [{'name': 'Диван прямой divan.ru Викс Рогожка Серый', 'price': 25990, 'url': 'https://xf.gdeslon.ru/cm/x?goto=divan.ru',
             'img': 'img/833aa090526a8096.jpg', 'shop': 'divan.ru', 'role': 'диван', 'qty': 1}]
EN_ITEMS = [{'name': 'Viks straight sofa, grey woven fabric', 'price': 347, 'img': 'img/833aa090526a8096.jpg', 'role': 'sofa', 'qty': 1},
            {'name': 'Cushion', 'price': 43, 'img': '', 'role': 'cushion', 'qty': 1}]

ru = page({'title': 'Квартира №215'}, [{'url': '/test/a.jpg', 'label': 'сканди · эскиз', 'items': RU_ITEMS}])
check('без маски: цена в рублях', '25 990 ₽' in ru)
check('без маски: магазин и ссылка на месте', 'divan.ru' in ru and 'href="https://xf.gdeslon.ru' in ru)
check('без маски: русская страница', '<html lang="ru">' in ru and 'Товары на фото' in ru and 'ссылками в магазин' in ru)

# посторонние поля без `mask: true` маску не включают — русский путь не меняется
ru2 = page({'title': 'Квартира №215', 'currency': 'GBP', 'lang': 'en'}, [{'url': '/test/a.jpg', 'label': 'сканди · эскиз', 'items': RU_ITEMS}])
check('валюта без маски — как было', ru2 == ru)

en = page({'title': 'Apartment No. 215 · 73.7 m²', 'mask': True, 'currency': 'GBP', 'lang': 'en'},
          [{'url': '/test/a.jpg', 'label': 'Scandi · sketch · 14:05', 'items': EN_ITEMS},
           {'url': '/test/b.jpg', 'label': '', 'items': [dict(RU_ITEMS[0], name='Sofa', role='sofa', price=347)]}])
check('маска: цены в фунтах, итог — сумма строк', '£347' in en and '£390' in en and '₽' not in en)
check('маска: ни ссылок, ни магазина — даже если страница их прислала', 'href=' not in en and 'divan.ru' not in en and 'gdeslon' not in en)
check('маска: английская страница без слов про магазины', '<html lang="en">' in en and 'Items in the photo' in en
      and 'shop' not in en.lower().replace('photo', ''))
check('маска: на странице нет кириллицы', not re.search('[А-Яа-яЁё]', en))

sys.exit(1 if fails else 0)

#!/usr/bin/env python3
"""Каталог через API Гдеслона — независимо от ссылок на выгрузки.

ЗАЧЕМ ТРИ ВЕЩИ СРАЗУ.

1. **Ссылки выгрузок умирают молча.** `777e580d…` не отдавалась ни разу (3 неудачи подряд,
   `last_ok` пуст), а до этого nonton 404-ил две недели и мы показывали товары магазина,
   которого у нас нет. API не зависит от статичных ссылок из кабинета.
2. **API отдаёт `original_picture` — картинку с CDN САМОГО МАГАЗИНА, 800×600** против 450×338
   в фиде. Это прямо снимает потолок по тонким деталям: у ковра и проволочного основания
   лишний вдвое пиксель решает, останется деталь в маске или нет.
3. **API отдаёт `description`**, которого в фиде нет — а обогащение по тексту без описания
   вынуждено угадывать по названию.

КАК ПЕРЕЧИСЛЯЕМ. Поиск требует запроса, и пустой упирается в ~1100 товаров на магазин. Обход
по словам-ролям даёт 5440 из 5763 у divan.ru (94%) за 103 запроса и 29 секунд — и это ровно
наш домен: то, что в роли не попало, нам и не нужно.

ЧТО ПИШЕМ. Свои данные складываем в `api_offers` и оттуда переносим в `products` только то,
что фид дать не может: `image_url_hd` и `description`. Перезаписывать цену и наличие поверх
`load3.py` не будем — у него свой контракт и своя дельта; API здесь дополняет, а не спорит.

  catalog_api_sync.py                # обойти все магазины каталога
  catalog_api_sync.py --mid 112923   # один магазин
  catalog_api_sync.py --report       # что уже собрано
"""
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from gdeslon_api import SEARCH_URL, token  # noqa: E402

PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

# Слова обхода — наши роли. Перечисление по ним даёт наш домен и не тратит запросы на чужое.
ROLES = ['диван', 'кресло', 'стул', 'комод', 'тумба', 'стеллаж', 'шкаф', 'витрина', 'стол',
         'столик', 'ковёр', 'плед', 'подушка', 'штора', 'люстра', 'бра', 'лампа', 'торшер',
         'ваза', 'кашпо', 'статуэтка', 'зеркало', 'часы', 'полка', 'камин', 'пуф', 'банкетка',
         'растение', 'картина', 'покрывало']
MAX_PAGES = int(os.environ.get('API_MAX_PAGES', '12'))

SCHEMA = """
create table if not exists api_offers (
  shop_mid int not null,
  external_id text not null,
  name text, description text,
  price numeric, oldprice numeric, charge numeric,
  picture text, image_url_hd text,          -- original_picture: CDN магазина, крупнее фида
  vendor text, model text, url text, direct_url text,
  available boolean, gs_category_id text, article text,
  seen_at timestamptz default now(),
  primary key (shop_mid, external_id)
);
alter table products add column if not exists image_url_hd text;
"""


def db(sql: str) -> list[list[str]]:
    r = subprocess.run(PSQL, capture_output=True, text=True, input=sql)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]


def q(v) -> str:
    if v is None or v == '':
        return 'null'
    return "'" + str(v).replace("'", "''") + "'"


def page(mid: int, query: str, p: int, tok: str, limit: int = 100) -> list[dict]:
    url = SEARCH_URL.format(q=urllib.parse.quote(query), mid=mid, l=limit, p=p, tok=tok)
    raw = urllib.request.urlopen(url, timeout=60).read().decode('utf-8', 'ignore')
    out = []
    for o in ET.fromstring(raw).iter('offer'):
        d = {c.tag: (c.text or '').strip() for c in o}
        out.append({
            'id': o.attrib.get('id'), 'available': o.attrib.get('available') == 'true',
            'gs_category_id': o.attrib.get('gs_category_id'), 'article': o.attrib.get('article'),
            'name': d.get('name'), 'description': d.get('description'),
            'price': d.get('price'), 'oldprice': d.get('oldprice'), 'charge': d.get('charge'),
            'picture': d.get('picture'), 'image_url_hd': d.get('original_picture'),
            'vendor': d.get('vendor'), 'model': d.get('model'), 'url': d.get('url'),
            'direct_url': d.get('destination-url-do-not-send-traffic'),
        })
    return out


def sync_shop(mid: int, tok: str) -> tuple[int, int]:
    """→ (уникальных офферов, запросов). Обход по ролям, страница за страницей до повторов."""
    seen: dict[str, dict] = {}
    calls = 0
    for word in ROLES:
        for p in range(1, MAX_PAGES + 1):
            try:
                items = page(mid, word, p, tok)
                calls += 1
            except Exception as e:  # noqa: BLE001 — сеть моргнула: слово пропускаем, не прогон
                print(f'  {mid} «{word}» стр {p}: {type(e).__name__}: {str(e)[:60]}', flush=True)
                break
            if not items:
                break
            fresh = [i for i in items if i['id'] and i['id'] not in seen]
            for i in fresh:
                seen[i['id']] = i
            if not fresh:
                break                       # страницы пошли по кругу
    for i in seen.values():
        db(f"""insert into api_offers (shop_mid, external_id, name, description, price, oldprice,
                 charge, picture, image_url_hd, vendor, model, url, direct_url, available,
                 gs_category_id, article, seen_at)
               values ({mid}, {q(i['id'])}, {q(i['name'])}, {q(i['description'])},
                 {q(i['price']) if i['price'] else 'null'},
                 {q(i['oldprice']) if i['oldprice'] else 'null'},
                 {q(i['charge']) if i['charge'] else 'null'},
                 {q(i['picture'])}, {q(i['image_url_hd'])}, {q(i['vendor'])}, {q(i['model'])},
                 {q(i['url'])}, {q(i['direct_url'])}, {str(i['available']).lower()},
                 {q(i['gs_category_id'])}, {q(i['article'])}, now())
               on conflict (shop_mid, external_id) do update set
                 name=excluded.name, description=excluded.description, price=excluded.price,
                 oldprice=excluded.oldprice, charge=excluded.charge, picture=excluded.picture,
                 image_url_hd=excluded.image_url_hd, url=excluded.url,
                 direct_url=excluded.direct_url, available=excluded.available,
                 seen_at=now()""")
    return len(seen), calls


# СВЯЗЬ С КАТАЛОГОМ — НЕ ПО ID. Идентификаторы в API испорчены округлением: приходят
# 20-значные числа с хвостом нулей (`18010903478735600000`) — это float64, потерявший точность
# на стороне Гдеслона. Совпадений с фидом: 17 из 5763. Рабочие ключи, замерено 29.08:
#   картинка (с добавленной схемой) — 4449 совпадений, путь на CDN уникален для товара;
#   название — 4636, но названия у вариантов цвета повторяются, поэтому оно ДОБОРОМ.
JOIN_PICTURE = ("a.shop_mid = p.shop_mid and ('https:' || p.image_url) = a.picture")
JOIN_NAME = ("a.shop_mid = p.shop_mid and p.name = a.name "
             "and p.image_url_hd is null")     # только тем, кому картинка не помогла


def merge_into_products() -> tuple[int, int]:
    """Переносим в каталог только то, чего фид дать не может: крупное фото и описание.

    Цену и наличие не трогаем: за них отвечает `load3.py` со своей дельтой и своим контрактом,
    и два писателя одного поля — верный способ получить расхождение, которого никто не заметит.
    """
    hd = 0
    for cond in (JOIN_PICTURE, JOIN_NAME):
        hd += len(db(f"""update products p set image_url_hd = a.image_url_hd
                           from api_offers a
                          where {cond} and a.image_url_hd is not null
                            and p.image_url_hd is distinct from a.image_url_hd
                        returning 1"""))
    desc = len(db(f"""update products p set description = a.description
                        from api_offers a
                       where {JOIN_PICTURE} and a.description is not null
                         and a.description <> '' and coalesce(p.description, '') = ''
                     returning 1"""))
    return hd, desc


def report() -> None:
    db(SCHEMA)
    tot = db('select count(*) from api_offers')[0][0]
    hd = db('select count(*) from api_offers where image_url_hd is not null')[0][0]
    de = db("select count(*) from api_offers where coalesce(description,'') <> ''")[0][0]
    print(f'офферов из API: {tot} · с крупным фото: {hd} · с описанием: {de}')
    print('по магазинам:')
    for r in db('select shop_mid, count(*), max(seen_at)::date from api_offers group by 1 order by 2 desc'):
        if len(r) == 3:
            print(f'  {r[0]:>8}  {r[1]:>6}  обновлён {r[2]}')
    inprod = db('select count(*) from products where image_url_hd is not null')[0][0]
    print(f'в каталоге с крупным фото: {inprod}')


def main() -> int:
    db(SCHEMA)
    if '--report' in sys.argv:
        report()
        return 0
    tok = token()
    if '--mid' in sys.argv:
        mids = [int(sys.argv[sys.argv.index('--mid') + 1])]
    else:
        mids = [int(r[0]) for r in db(
            'select distinct shop_mid from products where shop_mid is not null') if r and r[0]]
    t0 = time.time()
    total = 0
    for mid in mids:
        n, calls = sync_shop(mid, tok)
        total += n
        print(f'  магазин {mid}: {n} офферов за {calls} запросов', flush=True)
    hd, desc = merge_into_products()
    print(f'[api-sync] офферов {total} за {time.time() - t0:.0f} с; '
          f'в каталог: крупных фото +{hd}, описаний +{desc}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

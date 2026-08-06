#!/usr/bin/env python3
"""Дерево категорий из самих фидов — вместо угадывания роли по названию товара.

Роль товара у нас определялась регексами по строке `category_path`, а сама строка склеивалась
как попало. Из-за этого в «шторы» попали карнизы и потолочные плинтусы (199 из 746), а в «кашпо» —
садовые вазоны для рассады (173 из 636). Стиль по карнизу определять бессмысленно, и в комплект
гостиной он попасть не должен вовсе.

В YML-фиде категории лежат деревом: `<category id="12" parentId="3">Карнизы</category>`. Значит
можно не гадать, а взять готовую классификацию магазина, разложить её по уровням и решать
осознанно: эту ветку берём, эту не берём никогда.

  ~/venvs/scout/bin/python feed_taxonomy.py --build     # собрать дерево из всех фидов
  ~/venvs/scout/bin/python feed_taxonomy.py --tree "шторы"   # показать ветки по слову
  ~/venvs/scout/bin/python feed_taxonomy.py --unmapped       # крупные категории без решения
"""
import glob
import json
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
FEEDS = os.path.join(HERE, 'feeds2')
OUT = os.path.join(HERE, 'feed-taxonomy.json')


def build() -> dict:
    """Категории всех фидов с родителями, полным путём и числом товаров."""
    cats: dict[str, dict] = {}
    for z in sorted(glob.glob(os.path.join(FEEDS, '*.zip'))):
        zf = zipfile.ZipFile(z)
        name = zf.namelist()[0]
        shop_cats: dict[str, dict] = {}
        counts: dict[str, int] = {}
        with zf.open(name) as f:
            for _, el in ET.iterparse(f):
                if el.tag == 'category':
                    # В стандарте Яндекса атрибут `parentId`, но магазины пишут и `parent_id` —
                    # из-за этого дерево схлопывалось в один уровень и вся вложенность терялась
                    shop_cats[el.get('id')] = {
                        'name': (el.text or '').strip(),
                        'parent': el.get('parentId') or el.get('parent_id')}
                elif el.tag == 'offer':
                    cid = el.findtext('categoryId')
                    url = el.findtext('url') or ''
                    m = re.search(r'mid=(\d+)', url) or re.search(r'mid%3D(\d+)', url)
                    if cid:
                        counts[cid] = counts.get(cid, 0) + 1
                    if m and 'shop_mid' not in shop_cats:
                        shop_cats['shop_mid'] = int(m.group(1))
                    el.clear()
        mid = shop_cats.pop('shop_mid', 0)

        def path_of(cid, depth=0):
            c = shop_cats.get(cid)
            if not c or depth > 8:
                return []
            return path_of(c['parent'], depth + 1) + [c['name']] if c['parent'] else [c['name']]

        for cid, c in shop_cats.items():
            key = f'{mid}:{cid}'
            p = path_of(cid)
            cats[key] = {'mid': mid, 'id': cid, 'name': c['name'], 'parent': c['parent'],
                         'path': ' / '.join(p), 'depth': len(p), 'offers': counts.get(cid, 0)}
        print(f'{os.path.basename(z)[:12]}… mid {mid}: категорий {len(shop_cats)}, '
              f'товаров разложено {sum(counts.values())}', flush=True)
    json.dump(cats, open(OUT, 'w'), ensure_ascii=False)
    tot = sum(c['offers'] for c in cats.values())
    print(f'\nвсего категорий: {len(cats)}, товаров в них: {tot}')
    print(f'глубина дерева: {max(c["depth"] for c in cats.values())} уровней')
    return cats


def load() -> dict:
    return json.load(open(OUT)) if os.path.exists(OUT) else build()


def tree(word: str) -> None:
    cats = load()
    hits = [c for c in cats.values() if re.search(word, c['path'], re.I)]
    hits.sort(key=lambda c: -c['offers'])
    print(f'категорий со словом «{word}»: {len(hits)}, товаров в них '
          f'{sum(c["offers"] for c in hits)}\n')
    for c in hits[:40]:
        print(f'  {c["offers"]:>6}  [{c["mid"]}] {c["path"]}')


def unmapped(limit: int = 60) -> None:
    """Самые крупные листовые категории — по ним и надо принимать решение."""
    cats = load()
    parents = {c['parent'] for c in cats.values() if c['parent']}
    leaves = [c for c in cats.values() if c['id'] not in parents and c['offers'] > 0]
    leaves.sort(key=lambda c: -c['offers'])
    print(f'листовых категорий с товарами: {len(leaves)}\n')
    for c in leaves[:limit]:
        print(f'  {c["offers"]:>6}  [{c["mid"]}] {c["path"]}')


def main() -> None:
    if '--build' in sys.argv:
        build()
    elif '--tree' in sys.argv:
        tree(sys.argv[sys.argv.index('--tree') + 1])
    elif '--unmapped' in sys.argv:
        unmapped()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()

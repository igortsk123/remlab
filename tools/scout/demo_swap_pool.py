#!/usr/bin/env python3
"""Пул замены для демо: «любая мебель, у которой есть меш и которая подходит стилю».

Владелец 08.09: «сделай так, чтобы мебель можно было выбирать любую из тех, что есть меши и
соответствуют стилю; изначальный набор в сете рекомендуемой мебели остаётся». И там же —
временное ограничение: «по 30 вариантов товаров каждой подкатегории в каждом стиле» (компромисс
по месту на сервере: без него под все стили нужно 8–11 ГБ моделей при 16 ГБ свободных).

Подкатегория — `functional_subtype` из обогащения (мягкая_мебель, тумба_под_тв, журнальный_стол…),
стиль — из `styles` того же обогащения со СИЛОЙ «высокая»/«средняя» (ключ есть у всех товаров,
поэтому фильтровать по наличию ключа бессмысленно). Внутри группы берём лучших по качеству
обогащения, при равенстве — стабильно по артикулу.

МОДЕЛЬ ОДНА НА СЕМЕЙСТВО (ADR-0196): цветовые варианты делят меш представителя, поэтому в пуле у
товара два артикула — свой (`sid`, для карточки и ссылки) и модельный (`msid`, по нему сцена
грузит GLB). Публикуем и держим на сервере только модели представителей.

  ~/venvs/scout/bin/python demo_swap_pool.py            # сводка
  ~/venvs/scout/bin/python demo_swap_pool.py --json f   # выгрузить пул
  python3 demo_swap_pool.py --selftest
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

PER_GROUP = int(os.environ.get('DEMO_SWAP_PER_GROUP', '30'))
STYLES = ('лофт', 'сканди', 'джапанди', 'минимализм', 'неоклассика', 'современный')
# роли, которые демо расставляет объёмными моделями (ковры и прочее плоское — вклейкой)
ROLES = ('диван', 'кресло', 'столик', 'тв-тумба', 'стеллаж', 'комод', 'торшер', 'пуф',
         'кашпо', 'витрина', 'банкетка', 'стол обеденный', 'стул',
         # НАСТОЛЬНЫЙ ДЕКОР (владелец 08.09: «вазы настольные и что там ещё есть, если есть меши
         # и стили, добавлять в список товаров и считать сумму»). Меши сегодня есть только у вазы
         # и кашпо; статуэтки/часы/картины пойдут сюда сами, когда их меши появятся.
         'ваза')


def _lit(xs) -> str:
    return ','.join("'" + str(x).replace("'", "''") + "'" for x in xs) or "''"


def pool_sql(per_group: int = PER_GROUP) -> str:
    """Запрос пула. Вынесен отдельно, чтобы `--selftest` проверял его форму без БД."""
    return f"""
with cand as (
  select p.shop_mid||':'||p.external_id as sku,
         coalesce(p.mesh_family_rep, p.shop_mid||':'||p.external_id) as rep,
         coalesce(e.payload->'model'->>'functional_subtype', p.cat_role) as sub,
         s.style, p.cat_role, coalesce(p.name,'') as name, coalesce(p.shop,'') as shop,
         coalesce(p.image_url_hd, p.image_url) as img, p.url, p.price_rub as price,
         p.w_cm, p.d_cm, p.h_cm, coalesce(e.quality, 0) as q
    from products p
    join product_enrichment e using (shop_mid, external_id)
    cross join lateral (select unnest(array[{_lit(STYLES)}]) as style) s
   where p.cat_role in ({_lit(ROLES)})
     and p.mesh_status = 'ready' and p.in_stock and p.status = 'active'
     and p.w_cm is not null and p.d_cm is not null and p.h_cm is not null
     and coalesce(p.image_url_hd, p.image_url) is not null
     and e.payload->'model'->'styles'->>s.style in ('высокая','средняя')),
ranked as (
  select *, row_number() over (partition by sub, style order by q desc, sku) as rn from cand)
select sku, rep, sub, style, cat_role, name, shop, img, url, coalesce(price::text,''),
       w_cm, d_cm, h_cm
  from ranked where rn <= {per_group} order by cat_role, style, sku"""


def pool() -> list[dict]:
    from mesh_queue import db
    out = []
    for r in db(pool_sql()):
        if len(r) != 13:
            continue
        sku, rep, sub, style, role, name, shop, img, url, price, w, d, h = r
        out.append({'sid': sku.replace(':', '_', 1), 'msid': rep.replace(':', '_', 1),
                    'sub': sub, 'style': style, 'role': role, 'name': name, 'shop': shop,
                    'img': img, 'url': url,
                    'price': int(float(price)) if price else None,
                    'w': float(w), 'd': float(d), 'h': float(h)})
    return out


def report(items: list[dict] | None = None) -> list[dict]:
    items = items if items is not None else pool()
    models = {i['msid'] for i in items}
    groups: dict[tuple, int] = {}
    for i in items:
        groups[(i['sub'], i['style'])] = groups.get((i['sub'], i['style']), 0) + 1
    print(f'пул замены: товаров {len(items)}, моделей (уникальных мешей) {len(models)}, '
          f'групп «подкатегория×стиль» {len(groups)}, лимит на группу {PER_GROUP}')
    by_role: dict[str, int] = {}
    for i in items:
        by_role[i['role']] = by_role.get(i['role'], 0) + 1
    print('по ролям:', dict(sorted(by_role.items(), key=lambda kv: -kv[1])))
    print(f'вес моделей ≈ {len(models) * 7.6 / 1024:.1f} ГБ')
    return items


def _selftest() -> int:
    bad = 0
    q = pool_sql(7)
    for must in ('functional_subtype', 'mesh_status', "'высокая','средняя'", 'rn <= 7',
                 'mesh_family_rep', 'partition by sub, style'):
        if must not in q:
            bad += 1
            print('  FAIL: в запросе нет', must)
    if _lit(["a'b"]) != "'a''b'":
        bad += 1
        print('  FAIL: экранирование кавычек')
    if 'ковёр' in ROLES:
        bad += 1
        print('  FAIL: плоские роли (ковёр) в пул моделей не входят')
    print(f'demo_swap_pool selftest: случаев 8, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(_selftest())
    items = report()
    if '--json' in sys.argv:
        path = sys.argv[sys.argv.index('--json') + 1]
        json.dump(items, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print('пул выгружен →', path)

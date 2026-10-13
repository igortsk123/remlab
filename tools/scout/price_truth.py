#!/usr/bin/env python3
"""Правдивая цена (план conv-10, ADR-0260): что показывать покупателю — фид или страницу магазина.

ЗАЧЕМ. Истиной цены был фид (`products.price_rub`), а цена со страницы (`product_page_facts.price_seen`,
снимает недельная проверка наличия) только сравнивалась в health. Замер 13.10: у tvoydom (второй
магазин демо) 4 118 из 10 500 цен со страницы расходятся с фидом больше чем на 10 %, у divanboss и
mnogomebeli — около половины. Демо и сертификат считали сумму по неверным числам.

ПРАВИЛО (`rules/price-truth.json`): магазину задано `feed` или `page`; не задано — решает замер
(расхождение > drift_pct у более чем drift_share сравнённых, не меньше min_compared). Для `page` берём
цену со страницы, если ей не больше max_page_age_days, иначе фид с пометкой `feed-stale`. Пишем
`price_shown_rub`, `price_basis`, `price_checked_at`. Ничего не блокируем — владелец 13.10: «как у A101,
цена с датой и оговоркой».

  ~/venvs/scout/bin/python price_truth.py            # пересчитать и показать таблицу
  ~/venvs/scout/bin/python price_truth.py --dry      # только таблица, без записи
  python3 price_truth.py --selftest
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RULES = os.path.join(HERE, 'rules', 'price-truth.json')


def load_rules(path: str = RULES) -> dict:
    return json.load(open(path, encoding='utf-8'))


def decide(shop: str, compared: int, drifted: int, rules: dict) -> tuple[str, str]:
    """→ (basis, why). Явное правило магазина сильнее замера; мало данных — фиду верим."""
    fixed = (rules.get('shops') or {}).get(shop)
    if fixed in ('feed', 'page'):
        return fixed, 'правило'
    a = rules.get('auto') or {}
    if compared < int(a.get('min_compared', 20)):
        return 'feed', f'мало сравнений ({compared})'
    share = drifted / compared if compared else 0
    if share > float(a.get('drift_share', 0.2)):
        return 'page', f'замер: расходится {share:.0%}'
    return 'feed', f'замер: расходится {share:.0%}'


def measure(db, rules: dict) -> list[tuple]:
    """По магазину: сравнено, расходится > drift_pct, среднее расхождение %."""
    pct = float((rules.get('auto') or {}).get('drift_pct', 10)) / 100
    age = int(rules.get('max_page_age_days', 21))
    return [(r[0], int(r[1]), int(r[2]), float(r[3] or 0)) for r in db(f"""
        select p.shop, count(*),
               count(*) filter (where abs(f.price_seen - p.price_rub) > {pct} * p.price_rub),
               round(avg(abs(f.price_seen - p.price_rub) / p.price_rub) * 100, 1)
          from product_page_facts f join products p using (shop_mid, external_id)
         where f.price_seen > 0 and p.price_rub > 0 and f.seen_at > now() - interval '{age} days'
         group by 1 order by 2 desc""") if len(r) >= 4]


def apply_sql(page_shops: list[str], age_days: int) -> str:
    lit = ','.join("'" + s.replace("'", "''") + "'" for s in page_shops) or "''"
    return f"""
with f as (select shop_mid, external_id, price_seen, seen_at from product_page_facts
            where price_seen > 0 and seen_at > now() - interval '{age_days} days')
update products p set
  price_shown_rub = case when p.shop in ({lit}) and f.price_seen is not null then f.price_seen else p.price_rub end,
  price_basis = case when p.shop not in ({lit}) then 'feed'
                     when f.price_seen is not null then 'page' else 'feed-stale' end,
  price_checked_at = case when p.shop in ({lit}) and f.price_seen is not null then f.seen_at else now() end
  from products p2 left join f using (shop_mid, external_id)
 where p.shop_mid = p2.shop_mid and p.external_id = p2.external_id
"""


def main() -> int:
    from mesh_queue import db
    rules = load_rules()
    rows = measure(db, rules)
    page = []
    print(f"{'магазин':18} {'сравнено':>9} {'> порога':>9} {'среднее %':>10}  истина")
    for shop, n, d, avg in rows:
        basis, why = decide(shop, n, d, rules)
        if basis == 'page':
            page.append(shop)
        print(f'{shop:18} {n:9d} {d:9d} {avg:10.1f}  {basis} ({why})')
    for shop, b in (rules.get('shops') or {}).items():
        if b == 'page' and shop not in page:
            page.append(shop)                    # правило есть, а наблюдений за срок нет — всё равно page
    if '--dry' in sys.argv:
        return 0
    db(apply_sql(page, int(rules.get('max_page_age_days', 21))))
    stats = db("select price_basis, count(*) from products where in_stock group by 1 order by 2 desc")
    print('показываемая цена у товаров в наличии:', ', '.join(f'{r[0]} {r[1]}' for r in stats if len(r) >= 2))
    stale = sum(int(r[1]) for r in stats if len(r) >= 2 and r[0] == 'feed-stale')
    if stale:
        print(f'WARN:price_stale: у {stale} товаров магазинов «по странице» цена со страницы старше '
              f'{rules.get("max_page_age_days", 21)} дней — показываем фид с пометкой', flush=True)
    return 0


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    rules = {'shops': {'divan.ru': 'feed', 'tvoydom.ru': 'page'}, 'auto': {'drift_pct': 10, 'drift_share': 0.2, 'min_compared': 20}}
    ok('явное правило сильнее замера', decide('divan.ru', 1000, 900, rules)[0] == 'feed')
    ok('tvoydom по правилу — страница', decide('tvoydom.ru', 5, 0, rules)[0] == 'page')
    ok('незнакомый магазин с расхождением 50 % — страница', decide('x.ru', 100, 50, rules)[0] == 'page')
    ok('незнакомый магазин с расхождением 5 % — фид', decide('x.ru', 100, 5, rules)[0] == 'feed')
    ok('мало сравнений — фиду верим', decide('x.ru', 10, 10, rules)[0] == 'feed')
    sql = apply_sql(["o'shop"], 21)
    ok('имя магазина экранировано в SQL', "'o''shop'" in sql and "interval '21 days'" in sql)
    ok('правила в репозитории читаются', load_rules().get('shops', {}).get('tvoydom.ru') == 'page')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())

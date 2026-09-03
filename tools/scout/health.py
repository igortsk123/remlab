#!/usr/bin/env python3
"""ОТЧЁТ О ЖИВОСТИ ТОВАРОВ В КОМПЛЕКТАХ (31.08.2026 — только отчёт, без записи).

Раньше этот скрипт сам ходил по страницам и сам гасил `products.in_stock`. Оба решения оказались
неверными:
- вердикт из него `load3` стирал на следующем прогоне (наличие писали пятеро, побеждал последний);
- проверка покрывала только товары комплектов (721 из 20 544) и для divanboss/mnogomebeli искала
  слова названия БЕЗ цвета на странице серии — «жив» получался любой цвет, пока жива серия;
- он же правил `sets2.json`, конкурируя с `sets_incremental --heal` за один и тот же файл.

Теперь карточки проверяет `stock_check.py` (весь каталог, с подтверждением и предохранителями),
наличие считает `stock_truth.reconcile()`, замены в комплектах делает `sets_incremental --heal`.
Здесь остался отчёт: что из показываемого пользователю мертво, подозрительно или давно не
проверялось. Отчёт — `health-report.json`.

  health.py            # отчёт по всем поколениям комплектов
  health.py --json     # только путь к отчёту (для скриптов)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from stock_truth import db, q   # noqa: E402

REPORT = os.path.join(HERE, 'health-report.json')
STALE_DAYS = 14        # дольше без проверки — повод для внимания, но НЕ повод снимать товар


def sets_items() -> dict:
    """(mid, eid) → где используется, во всех поколениях комплектов."""
    todo = {}
    for src, fname in (('v1', 'sets.json'), ('v2', 'sets2.json'), ('v3', 'sets3.json')):
        path = os.path.join(HERE, fname)
        if not os.path.exists(path):
            continue
        for si, s in enumerate(json.load(open(path, encoding='utf-8'))):
            for role, it in (s.get('items') or {}).items():
                if not it or not it.get('mid'):
                    continue
                key = (int(it['mid']), str(it['eid']))
                rec = todo.setdefault(key, {'name': it.get('name', ''), 'refs': []})
                rec['refs'].append(f'{src}:сет{si + 1}:{role}')
    return todo


def main() -> int:
    todo = sets_items()
    if not todo:
        print('комплектов нет — отчёт пуст')
        return 0
    keys = ','.join(f"({m}, {q(e)})" for m, e in todo)
    rows = db(f"""
    select p.shop_mid, p.external_id, p.shop, p.name, p.in_stock,
           coalesce(ps.state, 'не проверялся'), coalesce(ps.reason, ''),
           coalesce(round(extract(epoch from now() - ps.checked_at) / 86400)::int, -1)
      from products p
      left join product_page_status ps on ps.shop_mid = p.shop_mid and ps.external_id = p.external_id
     where (p.shop_mid, p.external_id) in ({keys});""")
    report = {'checked': len(rows), 'dead': [], 'stale': [], 'missing_in_db': []}
    seen = set()
    for mid, eid, shop, name, in_stock, state, reason, age_d in rows:
        key = (int(mid), eid)
        seen.add(key)
        item = {'mid': int(mid), 'eid': eid, 'shop': shop, 'name': (name or '')[:60],
                'state': state, 'reason': reason, 'age_days': int(age_d),
                'in_stock': in_stock == 't', 'used_in': todo[key]['refs']}
        if state in ('gone', 'oos'):
            report['dead'].append(item)
        elif int(age_d) < 0 or int(age_d) > STALE_DAYS:
            report['stale'].append(item)
    for key, rec in todo.items():
        if key not in seen:
            report['missing_in_db'].append({'mid': key[0], 'eid': key[1],
                                            'name': rec['name'][:60], 'used_in': rec['refs']})
    # ЧЕСТНОСТЬ НАЛИЧИЯ ПО МАГАЗИНАМ (Н2): на чём держится in_stock и сколько свидетельств устарело.
    # Это отчёт, не приговор: feed — «верим фиду, не проверяли/не смогли», stale — проверяли давно.
    rows2 = db("""select p.shop, coalesce(p.availability_basis,'feed'),
                        count(*), count(*) filter (where p.stock_evidence_at < now() - interval '14 days')
                   from products p where p.in_stock group by 1, 2 order by 1, 2""")
    basis = {}
    for shop, b, n, stale in rows2:
        rec = basis.setdefault(shop, {})
        rec[b] = int(n)
        if b == 'page':
            rec['page_stale_14d'] = int(stale)
    report['stock_basis'] = basis
    # ЦЕНА СО СТРАНИЦЫ ПРОТИВ ФИДА (Н3): расхождение > 5 % — сигнал, что фид отстал; фид остаётся владельцем цены
    rows3 = db("""select p.shop, count(*), count(*) filter (where abs(f.price_seen - p.price_rub) > 0.05 * p.price_rub)
                   from product_page_facts f join products p using (shop_mid, external_id)
                  where f.price_seen is not null and p.price_rub > 0 and f.seen_at > now() - interval '14 days'
                  group by 1""")
    report['price_drift'] = {shop: {'compared': int(n), 'drift_over_5pct': int(d)} for shop, n, d in rows3}
    for shop, rec in report['price_drift'].items():
        if rec['compared'] >= 20 and rec['drift_over_5pct'] > 0.10 * rec['compared']:
            print(f"WARN:price_drift: {shop} — цена страницы расходится с фидом у {rec['drift_over_5pct']} из {rec['compared']} (> 10 %)", flush=True)
    json.dump(report, open(REPORT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'товаров в комплектах: {len(todo)} | мертвы: {len(report["dead"])} | '
          f'давно не проверялись: '
          f'{len(report["stale"])} | нет в каталоге: {len(report["missing_in_db"])}')
    for it in report['dead'][:10]:
        print(f'  МЁРТВ {it["shop"]:16s} {it["name"][:44]:44s} — {it["reason"]} '
              f'({", ".join(it["used_in"][:2])})')
    print('OK: health-report.json — замены сделает sets_incremental.py --heal --apply')
    return 0


if __name__ == '__main__':
    sys.exit(main())

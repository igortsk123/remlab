#!/usr/bin/env python3
"""СНИМОК СОСТОЯНИЯ КОНВЕЙЕРА — чтобы «прогон отработал» можно было доказать, а не поверить.

Зачем. Владелец 01.09: «мы ещё не убедились, что прогоны вообще работают». `refresh-status.json`
отвечает только «шаг не упал» — это не то же самое, что «шаг что-то сделал»: `stock_check`
двадцать раз подряд может завершаться успешно и не проверить ни одной карточки, если её не
выбрал `candidates()`. Поэтому меряем НАБЛЮДАЕМЫЙ РЕЗУЛЬТАТ и сравниваем два снимка.

    pipeline_snapshot.py before.json          # снять
    pipeline_snapshot.py --diff before.json after.json

Читает только БД и файлы банка/демо; ничего не меняет.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PSQL = ["docker", "exec", "-i", "remlab-devdb", "psql", "-U", "remlab", "-d", "remlab",
        "-q", "-v", "ON_ERROR_STOP=1", "-tAc"]


def db(q: str) -> list:
    out = subprocess.run(PSQL + [q], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr.strip()[:300])
    return [ln.split('|') for ln in out.stdout.splitlines() if ln]


def one(q: str):
    r = db(q)
    return r[0][0] if r else None


def bank_keys(path: str) -> set:
    """Уникальные товары банка (mid, eid) — множество, которое обязано проверяться ежедневно."""
    out = set()
    if not os.path.exists(path):
        return out
    for st in json.load(open(path, encoding='utf-8')):
        for it in (st.get('items') or {}).values():
            if it and it.get('mid'):
                out.add(f"{int(it['mid'])}:{it['eid']}")
    return out


def demo_items() -> list:
    """Товары, реально показанные на странице демо (варианты + ленты замен)."""
    # сборка кладёт файл в ~/scout-scenes/flat215-demo (`flat215_demo.OUT`), а не в репозиторий:
    # в репо лежит только index.html страницы
    p = os.path.expanduser('~/scout-scenes/flat215-demo/demo-data.json')
    if not os.path.exists(p):
        return []
    d = json.load(open(p, encoding='utf-8'))
    out = []
    for v in d.get('variants') or []:
        for it in v.get('items') or []:
            sku = it.get('sku') or {}
            if sku.get('name'):
                out.append({'variant': v.get('id'), 'role': it.get('role'),
                            'sid': sku.get('sid'), 'name': sku.get('name')})
    return out


def snap() -> dict:
    bank = bank_keys(os.path.join(HERE, 'sets3.json'))
    vals = ','.join("(" + k.split(':')[0] + ",'" + k.split(':')[1] + "')" for k in bank) or "(0,'')"
    checked = {r[0]: int(r[1]) for r in db(
        f"with b(mid,eid) as (values {vals}) "
        "select coalesce(ps.state,'НЕ ПРОВЕРЯЛСЯ'), count(*)::text from b "
        "left join product_page_status ps on ps.shop_mid=b.mid and ps.external_id=b.eid group by 1")}
    return {
        'at': subprocess.run(['date', '+%F %T'], capture_output=True, text=True).stdout.strip(),
        'products': int(one("select count(*)::text from products")),
        'in_stock': int(one("select count(*)::text from products where in_stock")),
        'page_status_rows': int(one("select count(*)::text from product_page_status")),
        'page_gone': int(one("select count(*)::text from product_page_status where state in ('gone','oos')")),
        'page_checked_24h': int(one(
            "select count(*)::text from product_page_status where checked_at > now() - interval '24 hours'")),
        'observations': int(one("select count(*)::text from product_page_observation")),
        'obs_runs': [r[0] for r in db(
            "select run_id from product_page_observation group by 1 order by 1 desc limit 5")],
        'bank_size': len(bank),
        'bank_by_state': checked,
        'bank_keys': sorted(bank),
        'demo_items': demo_items(),
        'refresh_status': json.load(open(os.path.join(HERE, 'refresh-status.json'), encoding='utf-8'))
        if os.path.exists(os.path.join(HERE, 'refresh-status.json')) else {},
    }


def diff(a: dict, b: dict) -> None:
    print(f"снимок «до»:    {a['at']}")
    print(f"снимок «после»: {b['at']}\n")
    rows = [('товаров в каталоге', 'products'), ('в наличии', 'in_stock'),
            ('строк проверки карточек', 'page_status_rows'), ('снято карточкой', 'page_gone'),
            ('проверено за 24 ч', 'page_checked_24h'), ('наблюдений всего', 'observations')]
    print(f"{'показатель':<28}{'до':>10}{'после':>10}{'дельта':>10}")
    for title, k in rows:
        d = b[k] - a[k]
        print(f"{title:<28}{a[k]:>10}{b[k]:>10}{d:>+10}")
    print(f"\nбанк: {a['bank_size']} → {b['bank_size']} уникальных товаров")
    print(f"  до:    {a['bank_by_state']}")
    print(f"  после: {b['bank_by_state']}")
    gone_now = b['bank_by_state'].get('gone', 0) + b['bank_by_state'].get('oos', 0)
    unchecked = b['bank_by_state'].get('НЕ ПРОВЕРЯЛСЯ', 0)
    print(f"  ВЕРДИКТ: непроверенных в банке {unchecked} "
          f"({'ЕЖЕДНЕВНЫЙ ОБХОД БАНКА НЕ ВЫПОЛНЕН' if unchecked else 'банк обойдён целиком'})"
          f"; мёртвых осталось в банке {gone_now}")
    ain, bin_ = set(a['bank_keys']), set(b['bank_keys'])
    if ain - bin_:
        print(f"  ушло из банка ({len(ain - bin_)}): {sorted(ain - bin_)[:12]}")
    if bin_ - ain:
        print(f"  пришло в банк ({len(bin_ - ain)}): {sorted(bin_ - ain)[:12]}")
    da = {(x['variant'], x['role']): x for x in a['demo_items']}
    dbb = {(x['variant'], x['role']): x for x in b['demo_items']}
    print(f"\nдемо: позиций {len(a['demo_items'])} → {len(b['demo_items'])}")
    for k in sorted(set(da) | set(dbb)):
        x, y = da.get(k), dbb.get(k)
        if x and y and x['name'] != y['name']:
            print(f"  ЗАМЕНА {k[0]}/{k[1]}: «{x['name'][:38]}» → «{y['name'][:38]}»")
        elif x and not y:
            print(f"  СНЯТО  {k[0]}/{k[1]}: «{x['name'][:38]}» (замены не нашлось)")
        elif y and not x:
            print(f"  ДОБАВЛЕНО {k[0]}/{k[1]}: «{y['name'][:38]}»")
    fa, fb = a.get('refresh_status') or {}, b.get('refresh_status') or {}
    if fa.get('finished') != fb.get('finished'):
        fails = [k for k, v in fb.items() if v == 'FAIL']
        print(f"\nночной цикл: {fb.get('date')} финиш {fb.get('finished')}; "
              f"шагов {sum(1 for v in fb.values() if v in ('ok', 'FAIL'))}, "
              f"упало: {fails or 'ничего'}")
        new_steps = sorted(set(k for k, v in fb.items() if v in ('ok', 'FAIL')) -
                           set(k for k, v in fa.items() if v in ('ok', 'FAIL')))
        if new_steps:
            print(f"  шаги, которых в прошлом прогоне НЕ БЫЛО: {new_steps}")


if __name__ == '__main__':
    if '--diff' in sys.argv:
        i = sys.argv.index('--diff')
        diff(json.load(open(sys.argv[i + 1], encoding='utf-8')),
             json.load(open(sys.argv[i + 2], encoding='utf-8')))
    else:
        s = snap()
        json.dump(s, open(sys.argv[1], 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f"снимок записан: {sys.argv[1]}")
        print(f"  каталог {s['products']}, в наличии {s['in_stock']}, "
              f"строк проверки {s['page_status_rows']} (снято {s['page_gone']}, "
              f"за 24 ч {s['page_checked_24h']})")
        print(f"  банк {s['bank_size']}: {s['bank_by_state']}")
        print(f"  демо: позиций {len(s['demo_items'])}")

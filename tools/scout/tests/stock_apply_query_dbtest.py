#!/usr/bin/env python3
"""Запрос истории наблюдений в `stock_check.apply_run` на НАСТОЯЩЕМ Postgres (pakardev): старый `in (список пар)` против нового
соединения со `VALUES` — T-20261112-56/5, план `stock-check-fix-01`. База ТОЛЬКО читается (select, курсоры без записи).
В CI не идёт (нужна база с наблюдениями); запуск: `r python3 tools/scout/tests/stock_apply_query_dbtest.py [run_id] [--memory]`.

Проверяет на реальной выборке ключей прогона (по умолчанию — последний прогон):
  1. строки: новый запрос (весь список одним запросом и пачками `history_by_sku`) равен старому по множеству строк
     (старый берётся пачками по 500 ключей — на целом списке он и есть причина обвала);
  2. изменения статусов: `fold()` по каждому ключу даёт то же (state, negatives, reason) и те же счётчики `changes`, что у старого;
  3. порядок равных времён: при равном `observed_at` новый порядок стабилен (`o.id`);
  4. `--memory`: память процесса базы (`pg_backend_memory_contexts`, курсор) до/после на 500, 1500 и всех ключах прогона;
     `explain` нового запроса — без `BitmapOr` из тысяч ветвей.
"""
from __future__ import annotations

import os
import sys
SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)
sys.path.append(SCOUT)
import remlab_tmp  # noqa: E402
remlab_tmp.use('stock_apply_query_dbtest')

import stock_check as SC  # noqa: E402
from stock_truth import db, fold, q  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  OK  ' if cond else '  FAIL ') + name + (f' — {extra}' if extra and not cond else ''), flush=True)
    bad += 0 if cond else 1


def old_sql(keys: list) -> str:
    """ЗАМОРОЖЕННАЯ копия прежнего запроса (до T-20261112-56/5): эталон для сравнения. Не править."""
    ks = ','.join(f"({m}, {q(e)})" for m, e in keys)
    return f"""
        select o.shop_mid, o.external_id, o.verdict, o.url_hash,
               to_char(o.observed_at, 'YYYY-MM-DD HH24:MI:SS'), coalesce(o.reason, '')
          from product_page_observation o
         where (o.shop_mid, o.external_id) in ({ks})
           and o.observed_at > now() - interval '90 days'
           and coalesce(o.disposition, 'accepted') = 'accepted'
           and (o.probe_version = {SC.PROBE_VERSION} or o.evidence_kind = 'http_gone')
         order by o.shop_mid, o.external_id, o.observed_at;"""


def run_keys(run_id: str) -> list:
    rows = db(f"select distinct shop_mid, external_id from product_page_observation where run_id = {q(run_id)} "
              "and coalesce(disposition, 'accepted') = 'accepted' order by 1, 2;")
    return [(int(r[0]), r[1]) for r in rows]


def states(by_sku: dict) -> tuple:
    per = {k: fold(h) for k, h in by_sku.items()}
    changes = {'gone': 0, 'oos': 0, 'alive': 0, 'unknown': 0}
    for st, _n, _r in per.values():
        changes[st] = changes.get(st, 0) + 1
    return per, changes


def mem_line(label: str, sql: str) -> str:
    body = sql.strip().rstrip(';')
    out = db(f"""
begin;
declare c no scroll cursor for {body};
fetch 1 from c;
select '{label}|first', round((select sum(used_bytes) from pg_backend_memory_contexts)/1048576.0, 1),
       round((select sum(total_bytes) from pg_backend_memory_contexts)/1048576.0, 1);
move forward all in c;
select '{label}|all', round((select sum(used_bytes) from pg_backend_memory_contexts)/1048576.0, 1),
       round((select sum(total_bytes) from pg_backend_memory_contexts)/1048576.0, 1);
close c;
commit;""")
    return '; '.join(f"{r[0]} used={r[1]} total={r[2]} МБ" for r in out if len(r) == 3)


def main() -> int:
    mem = '--memory' in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    run_id = args[0] if args else SC.last_run_id()
    keys = run_keys(run_id)
    print(f'прогон {run_id}: ключей {len(keys)}', flush=True)
    ok('в прогоне есть ключи', len(keys) > 0)
    if not keys:
        return 1
    uk = SC.unique_keys(keys + keys[:50])
    ok('unique_keys: без повторов, порядок первого появления', uk == keys, f'{len(uk)} против {len(keys)}')

    # 1. строки: старый пачками по 500, новый — целиком и пачками
    old_rows = []
    for i in range(0, len(keys), 500):
        old_rows += db(old_sql(keys[i:i + 500]))
    new_rows = db(SC.history_sql(keys))
    batch_by = SC.history_by_sku(keys)
    print(f'  строк истории: старый {len(old_rows)}, новый {len(new_rows)}', flush=True)
    ok('множество строк: новый (весь список) == старый', sorted(map(tuple, old_rows)) == sorted(map(tuple, new_rows)),
       f'{len(old_rows)} против {len(new_rows)}')
    new_by = SC.group_history(new_rows)
    ok('пачками == целиком (те же ключи и история)', batch_by == new_by, f'{len(batch_by)} против {len(new_by)}')

    # 2. изменения статусов
    old_by = SC.group_history(old_rows)
    ties = {k for k, h in old_by.items() if len({x[2] for x in h}) != len(h)}   # ключи с равными observed_at
    o_per, o_ch = states(old_by)
    n_per, n_ch = states(new_by)
    diff = [k for k in set(o_per) | set(n_per) if o_per.get(k) != n_per.get(k)]
    print(f'  ключей с историей {len(n_per)}; с равными observed_at {len(ties)}; состояния: {n_ch}', flush=True)
    ok('те же ключи с историей', set(o_per) == set(n_per))
    ok('fold по каждому ключу: (state, negatives, reason) совпал', not diff, f'расхождений {len(diff)}, из них с равными временами {len(set(diff) & ties)}')
    ok('счётчики изменений статусов совпали', o_ch == n_ch, f'{o_ch} против {n_ch}')

    # 3. стабильность порядка: второй раз — тот же порядок строк (при равных временах решает id)
    again = db(SC.history_sql(keys))
    ok('порядок строк стабилен между запусками', again == new_rows)

    if mem:
        print('память процесса базы (курсор; used — занято, total — выделено):', flush=True)
        for n in (500, 1500, len(keys)):
            sub = keys[:n]
            print(f'  N={n}:', flush=True)
            print('    старый:', mem_line(f'old{n}', old_sql(sub)), flush=True)
            print('    новый :', mem_line(f'new{n}', SC.history_sql(sub)), flush=True)
        plan = db('explain (memory, costs off) ' + SC.history_sql(keys[:1000]).strip().rstrip(';'))
        text = '\n'.join(r[0] for r in plan)
        print('  explain нового (1000 ключей), первые строки:\n    ' + '\n    '.join(text.splitlines()[:8]), flush=True)
        ok('explain нового: нет BitmapOr', 'BitmapOr' not in text)
    print(f'stock_apply_query_dbtest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

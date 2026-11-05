#!/usr/bin/env python3
"""Тень правила «сиденье по названию» (`category_map.seat_role`, T-20261105-53) по ВСЕМУ каталогу — без записи в БД.

Что считает (всё — только чтение `products`, `product_enrichment`, `mesh_demand`, `room_catalog`, живых банков):
  * сколько товаров с ролью диван/кресло меняют роль, «было → стало» (в наличии и всего), по причинам;
  * 30 случайных примеров (зерно фиксировано — повтор даёт те же);
  * спорные: смена, где обогащение моделью (`product_enrichment.payload.model.role`) считает товар диваном/креслом —
    кандидаты в ложные срабатывания, глазами;
  * пропущенные: роль не меняется, а модель считает товар пуфом — что правило по названию не ловит;
  * где сменившиеся товары сейчас стоят: живые банки гостиной/спальни/прихожей (составы и запасные), каталог комнат,
    очередь мешей (`mesh_demand.role`);
  * SQL применения и отката для `tools/ops/db-migrate-safe.sh` (сам ничего не применяет).

  ~/venvs/scout/bin/python seat_role_shadow.py --out ~/remlab-logs/t53-roles-$(date +%H%M)
Env: REMLAB_DEVDB_NAME — другая база (одноразовая копия), SCOUT_LIVE_DIR — где лежат живые банки (по умолчанию —
основная копия репо, `env_keys.main_root()`: в worktree их нет).
"""
import json
import os
import random
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import category_map  # noqa: E402

FS = '\x1f'
SQL_ROWS = f"""
select p.shop_mid, p.external_id, p.cat_role, p.in_stock, p.category_path, p.name,
       e.payload->'model'->>'role', e.payload->'model'->>'functional_subtype',
       d.role, d.status
  from products p
  left join product_enrichment e on e.shop_mid=p.shop_mid and e.external_id=p.external_id and e.status='active'
  left join mesh_demand d on d.sku = p.shop_mid||':'||p.external_id
 where p.cat_role in ({','.join("'" + r + "'" for r in sorted(category_map.SEAT_ROLES))})
 order by p.shop_mid, p.external_id
"""


def psql(sql: str) -> list[list[str]]:
    db = os.environ.get('REMLAB_DEVDB_NAME', 'remlab')
    r = subprocess.run(['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', db, '-q', '-v', 'ON_ERROR_STOP=1',
                        '-t', '-A', '-F', FS], input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f'SQL упал: {r.stderr[:300]}')
    return [ln.split(FS) for ln in r.stdout.split('\n') if ln]


def live_dir() -> str:
    if os.environ.get('SCOUT_LIVE_DIR'):
        return os.environ['SCOUT_LIVE_DIR']
    import env_keys
    return os.path.join(env_keys.main_root(), 'tools', 'scout')


def bank_skus(path: str) -> dict[str, list[str]]:
    """sku → где в банке: «<set id>/<слот>» (состав) или «<set id>/<слот> запас»."""
    out: dict[str, list[str]] = {}
    if not os.path.exists(path):
        return out
    for s in json.load(open(path, encoding='utf-8')):
        sid = s.get('id') or s.get('set_id') or '?'
        for slot, it in (s.get('items') or {}).items():
            for x in (it if isinstance(it, list) else [it]):
                if isinstance(x, dict) and x.get('mid') is not None:
                    out.setdefault(f"{x['mid']}:{x.get('eid')}", []).append(f'{sid}/{slot}')
        for slot, alts in (s.get('alternates') or {}).items():
            for a in alts or []:
                if isinstance(a, dict) and a.get('mid') is not None:
                    out.setdefault(f"{a['mid']}:{a.get('eid')}", []).append(f'{sid}/{slot} запас')
    return out


def q(s) -> str:
    return 'null' if s is None else "'" + str(s).replace("'", "''") + "'"


def main() -> None:
    out_dir = os.path.expanduser(sys.argv[sys.argv.index('--out') + 1]) if '--out' in sys.argv else None
    if not out_dir:
        raise SystemExit('нужен --out <новая папка>')
    os.makedirs(out_dir, exist_ok=True)
    rows = psql(SQL_ROWS)
    live = live_dir()
    banks = {room: bank_skus(os.path.join(live, f)) for room, f in
             (('гостиная', 'sets3.json'), ('спальня', 'sets-bedroom.json'), ('прихожая', 'sets-hall.json'))}
    rc = {f'{m}:{e}': f'{room}/{role}' for m, e, room, role in psql('select shop_mid, external_id, room, role from room_catalog')}
    changed, missed, total = [], [], {'всего': 0, 'в наличии': 0}
    for mid, eid, old, stock, path, name, erole, esub, drole, dstat in rows:
        total['всего'] += 1
        total['в наличии'] += stock == 't'
        new, why = category_map.seat_role(old, name)
        sku = f'{mid}:{eid}'
        rec = {'sku': sku, 'name': name, 'category': path, 'in_stock': stock == 't', 'old': old, 'new': new, 'why': why,
               'enrich_role': erole or None, 'enrich_subtype': esub or None, 'mesh_role': drole or None,
               'mesh_status': dstat or None, 'banks': {r: b[sku] for r, b in banks.items() if sku in b},
               'room_catalog': rc.get(sku)}
        if why:
            changed.append(rec)
        elif erole in ('пуф',):
            missed.append(rec)
    flow: dict[str, dict[str, int]] = {}
    for c in changed:
        k = f"{c['old']} → {c['new'] or 'без роли'}"
        f = flow.setdefault(k, {'всего': 0, 'в наличии': 0})
        f['всего'] += 1
        f['в наличии'] += c['in_stock']
    by_why: dict[str, int] = {}
    for c in changed:
        by_why[c['why']] = by_why.get(c['why'], 0) + 1
    rnd = random.Random(53)
    sample = rnd.sample(changed, min(30, len(changed)))
    disputed = [c for c in changed if c['enrich_role'] in ('диван', 'кресло')]
    in_banks = [c for c in changed if c['banks']]
    in_rc = [c for c in changed if c['room_catalog']]
    mesh = [c for c in changed if c['mesh_role']]
    summary = {'base': os.environ.get('REMLAB_DEVDB_NAME', 'remlab'), 'live_dir': live, 'seat_rows': total,
               'changed': len(changed), 'changed_in_stock': sum(c['in_stock'] for c in changed), 'flow': flow, 'by_why': by_why,
               'disputed_enrich_says_seat': len(disputed), 'missed_enrich_says_pouf': len(missed),
               'changed_in_live_banks': {r: sum(1 for c in changed if r in c['banks']) for r in banks},
               'changed_in_room_catalog': len(in_rc), 'changed_in_mesh_demand': len(mesh),
               'mesh_role_flow': {}}
    for c in mesh:
        k = f"{c['mesh_role']} ({c['mesh_status']}) → {c['new'] or 'без роли'}"
        summary['mesh_role_flow'][k] = summary['mesh_role_flow'].get(k, 0) + 1
    json.dump({'summary': summary, 'changed': changed, 'sample30': sample, 'disputed': disputed, 'missed': missed,
               'in_banks': in_banks}, open(os.path.join(out_dir, 'shadow.json'), 'w'), ensure_ascii=False, indent=1)
    # SQL применения: только строки, у которых роль всё ещё та, что видела тень (иначе — не трогаем: каталог успел
    # перезагрузиться). Очередь мешей — роль у тех же SKU, если новая роль есть (без роли — спрос сам уйдёт в not_required).
    # Форма SQL — под разбор `db-migrate-safe.sh:sql_scan`: «update <таблица> set» БЕЗ псевдонима и без временных таблиц.
    # С псевдонимом («update products p set») сканер таблицу не видит и снимает копию одной схемы — без данных (поймано сухим
    # прогоном 05.11). Значения — подзапросом `(values …) as t`, не temp-таблицей.
    vals = ',\n'.join(f"({q(c['sku'])},{q(c['old'])},{q(c['new'])})" for c in changed)
    mvals = ',\n'.join(f"({q(c['sku'])},{q(c['mesh_role'])},{q(c['new'])})" for c in mesh if c['new'])
    n_mesh = sum(1 for c in mesh if c['new'])

    def upd(table: str, col: str, key: str, rows: str, frm: str, to: str) -> str:
        return (f"update {table} set {col}=t.{to}\n  from (values\n{rows}) as t(sku, old_role, new_role)\n"
                f" where {key}=t.sku and {table}.{col} is not distinct from t.{frm};\n")
    p_key = "products.shop_mid||':'||products.external_id"
    head = ("-- T-20261105-53: роли сидений по названию (category_map.seat_role). Применять ТОЛЬКО через\n"
            "-- tools/ops/db-migrate-safe.sh (пауза кронов, pg_dump, одна транзакция, проверка «после», rollback.sh).\n"
            f"-- products: {len(changed)} строк; mesh_demand: {n_mesh}. Меняется только строка, у которой роль всё ещё прежняя.\n")
    apply_sql = head + upd('products', 'cat_role', p_key, vals, 'old_role', 'new_role')
    if mvals:
        apply_sql += upd('mesh_demand', 'role', 'mesh_demand.sku', mvals, 'old_role', 'new_role')
    open(os.path.join(out_dir, 'seat-roles-apply.sql'), 'w').write(apply_sql)
    back_sql = ("-- откат T-20261105-53 узко: старые роли — ТОЛЬКО строкам, которые всё ещё в новой роли\n"
                "-- (полный откат — rollback.sh рядом с дампом db-migrate-safe)\n"
                + upd('products', 'cat_role', p_key, vals, 'new_role', 'old_role'))
    if mvals:
        back_sql += upd('mesh_demand', 'role', 'mesh_demand.sku', mvals, 'new_role', 'old_role')
    open(os.path.join(out_dir, 'seat-roles-rollback.sql'), 'w').write(back_sql)
    # проверка «после» для --check: ни одного товара из списка в старой роли
    open(os.path.join(out_dir, 'check.sql'), 'w').write(
        "not exists (select 1 from products p where p.cat_role in ('диван','кресло') and p.shop_mid||':'||p.external_id in ("
        + ','.join(q(c['sku']) for c in changed) + "))")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f'→ {out_dir}/shadow.json, seat-roles-apply.sql, seat-roles-rollback.sql, check.sql')


if __name__ == '__main__':
    main()

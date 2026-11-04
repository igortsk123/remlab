#!/usr/bin/env python3
"""СНИМОК ДО/ПОСЛЕ ГЛУБИНЫ С ЧЕРТЕЖА (conv-15, T-20261104-06/4) — только чтение БД и файла кандидатов, для отката и
приёмки включения оверлея `drawing_dims` в `load3`.

По SKU mnogomebeli (114667) и divanboss (114082): размеры, `dims_source`, `dims_evidence.d`, хеши и статусы обогащения,
мешевые поля (`mesh_required`, `mesh_status`, `mesh_family`, `mesh_family_rep`), есть ли в кандидатах банка. Плюс общие
счётчики по всей базе: mesh_required, семьи и представители, кандидаты банка по ролям.

    ~/venvs/scout/bin/python drawing_snapshot.py --out <новая папка>          # снимок → <папка>/snapshot.json
    ~/venvs/scout/bin/python drawing_snapshot.py --diff <до.json> <после.json> # что поменялось (сводка в stdout)

Папку `--out` создаёт; если в ней уже есть snapshot.json — стоп (снимок не перезаписывается). Env: SCOUT_PSQL_CMD,
SCOUT_CANDIDATES (по умолчанию `candidates-index.json` рядом).
"""
import collections
import datetime
import json
import os
import shlex
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SHOPS = (114667, 114082)
PSQL = shlex.split(os.environ.get('SCOUT_PSQL_CMD') or '') or [
    'docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-q', '-v', 'ON_ERROR_STOP=1']
CAND = os.environ.get('SCOUT_CANDIDATES') or os.path.join(HERE, 'candidates-index.json')

SKU_SQL = f"""
select coalesce(json_agg(t order by t.sku), '[]') from (
  select p.shop_mid||':'||p.external_id sku, p.shop_mid mid, p.cat_role role, p.status, p.in_stock,
         p.w_cm w, p.d_cm d, p.h_cm h, p.dims_source, p.dims_evidence->'d' ev_d,
         p.mesh_required, p.mesh_status, p.mesh_family, p.mesh_family_rep rep,
         e.geometry_hash, e.hash_version, e.status e_status, e.enrichment_status
    from products p left join product_enrichment e using (shop_mid, external_id)
   where p.shop_mid in ({','.join(map(str, SHOPS))})) t"""
TOTALS_SQL = f"""
select json_build_object(
  'products', count(*),
  'mesh_required', count(*) filter (where mesh_required),
  'mesh_required_shops', count(*) filter (where mesh_required and shop_mid in ({','.join(map(str, SHOPS))})),
  'families', count(distinct mesh_family),
  'reps', count(distinct mesh_family_rep),
  'families_shops', count(distinct mesh_family) filter (where shop_mid in ({','.join(map(str, SHOPS))})),
  'reps_shops', count(distinct mesh_family_rep) filter (where shop_mid in ({','.join(map(str, SHOPS))})),
  'd_drawing', count(*) filter (where dims_evidence->'d'->>'source' = 'drawing'),
  'stale', (select count(*) from product_enrichment where enrichment_status = 'stale'))
  from products"""


def q(sql: str):
    r = subprocess.run(PSQL + ['-At'], input=sql, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:400])
    return json.loads(r.stdout.strip())


def candidates() -> dict:
    if not os.path.exists(CAND):
        return {'path': CAND, 'missing': True}
    items = json.load(open(CAND, encoding='utf-8')).get('items', {})
    shops = {k for k, v in items.items() if int(v.get('mid') or 0) in SHOPS}
    return {'path': CAND, 'mtime': datetime.datetime.fromtimestamp(os.path.getmtime(CAND)).isoformat(timespec='seconds'),
            'total': len(items), 'by_role': dict(collections.Counter(v.get('role') for v in items.values()).most_common()),
            'shops_total': len(shops), 'shops_by_role': dict(collections.Counter(items[k].get('role') for k in shops)),
            'shops_keys': sorted(shops)}


def snapshot(out: str) -> int:
    path = os.path.join(out, 'snapshot.json')
    if os.path.exists(path):
        print(f'СТОП: {path} уже есть — снимок не перезаписываю', flush=True)
        return 2
    snap = {'at': datetime.datetime.now().isoformat(timespec='seconds'), 'totals': q(TOTALS_SQL), 'skus': q(SKU_SQL),
            'candidates': candidates()}
    os.makedirs(out, exist_ok=True)
    json.dump(snap, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
    t = snap['totals']
    print(f"снимок {path}: SKU двух магазинов {len(snap['skus'])}, d с чертежа {t['d_drawing']}, mesh_required {t['mesh_required']} "
          f"(магазины {t['mesh_required_shops']}), семей {t['families']} / представителей {t['reps']}, stale {t['stale']}, "
          f"кандидатов банка {snap['candidates'].get('total')} (магазины {snap['candidates'].get('shops_total')})", flush=True)
    return 0


def diff(a: dict, b: dict) -> dict:
    """Сводка изменений между снимками: по SKU (размеры, источник, обогащение, меш, семья) и общие счётчики."""
    A, B = {x['sku']: x for x in a['skus']}, {x['sku']: x for x in b['skus']}
    c: collections.Counter = collections.Counter()
    status_moves: collections.Counter = collections.Counter()
    for k in A.keys() & B.keys():
        x, y = A[k], B[k]
        if x['d'] is None and y['d'] is not None:
            c['d: пусто → есть'] += 1
        elif x['d'] is not None and y['d'] is None:
            c['d: есть → пусто'] += 1
        elif x['d'] != y['d']:
            c['d: другое число'] += 1
        if (x['w'], x['h']) != (y['w'], y['h']):
            c['w/h изменились'] += 1
        for f in ('dims_source', 'geometry_hash', 'mesh_required', 'mesh_family', 'rep'):
            if x[f] != y[f]:
                c[f'{f} изменился'] += 1
        if x['enrichment_status'] != y['enrichment_status']:
            status_moves[f"{x['enrichment_status']} → {y['enrichment_status']}"] += 1
    ca, cb = set(a['candidates'].get('shops_keys') or []), set(b['candidates'].get('shops_keys') or [])
    return {'skus': dict(c), 'enrichment_status': dict(status_moves),
            'sku_only_before': len(A.keys() - B.keys()), 'sku_only_after': len(B.keys() - A.keys()),
            'totals': {k: [a['totals'][k], b['totals'][k]] for k in a['totals'] if a['totals'][k] != b['totals'].get(k)},
            'candidates_shops': {'+': len(cb - ca), '-': len(ca - cb)},
            'candidates_total': [a['candidates'].get('total'), b['candidates'].get('total')]}


def main(argv: list[str]) -> int:
    if '--diff' in argv:
        i = argv.index('--diff')
        a, b = (json.load(open(p, encoding='utf-8')) for p in argv[i + 1:i + 3])
        print(json.dumps(diff(a, b), ensure_ascii=False, indent=1))
        return 0
    if '--out' in argv:
        return snapshot(argv[argv.index('--out') + 1])
    print(__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

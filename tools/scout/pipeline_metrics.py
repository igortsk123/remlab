#!/usr/bin/env python3
"""Метрики конвейера: мерим СЕТЫ, а не меши.

ЗАЧЕМ. «Сделано 300 мешей» ничего не говорит о продукте: если они размазаны по каталогу, ни один
сет не стал показываемым. Полезность измеряется числом комплектов, которые можно показать
целиком, и покрытием ячеек `band × style × tier` — по ним видно, где ассортимент есть, а где
дыра (критика Codex 29.08).

  ~/venvs/scout/bin/python pipeline_metrics.py            # отчёт
  ~/venvs/scout/bin/python pipeline_metrics.py --json     # для страницы
"""
import collections
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mesh_queue import db  # noqa: E402
from render_strategy import asset_ready, base_role, strategy  # noqa: E402

SETS = os.path.join(HERE, 'sets3.json')


def collect() -> dict:
    sets = json.load(open(SETS))
    full = 0
    per_set = []
    cells = collections.defaultdict(lambda: [0, 0])
    for n, s in enumerate(sets, 1):
        need = ok = 0
        for slot, it in (s.get('items') or {}).items():
            if not it or not it.get('mid'):
                continue
            need += 1
            ok += bool(asset_ready(f"{it['mid']}:{it['eid']}", base_role(slot)))
        done = need > 0 and ok == need
        full += done
        per_set.append({'n': n, 'set_id': s.get('set_id'), 'ready': ok, 'need': need})
        cell = f"{s.get('band','?')} · {s.get('style','?')} · {s.get('tier','?')}"
        cells[cell][0] += 1
        cells[cell][1] += done

    # резерв
    try:
        import reserve
        rows = reserve.coverage()['rows']
        slots = len(rows)
        with2 = sum(1 for r in rows if r['ready'] >= 2)
        with1 = sum(1 for r in rows if r['ready'] >= 1)
    except Exception:  # noqa: BLE001
        slots = with1 = with2 = 0

    # очередь и возраст
    age = db("select coalesce(max(extract(epoch from now()-created))/3600, 0)::int "
             "from mesh_jobs where status='queued'")
    jobs = {r[0]: int(r[1]) for r in db("select status, count(*) from mesh_jobs group by 1")
            if len(r) == 2}
    lead = db("select coalesce(percentile_disc(0.5) within group "
              "  (order by extract(epoch from r.created - j.created)/3600), 0)::int, "
              "       coalesce(percentile_disc(0.95) within group "
              "  (order by extract(epoch from r.created - j.created)/3600), 0)::int "
              "  from mesh_jobs j join asset_revisions r on r.sku = j.sku "
              " where r.status='accepted'")
    return {
        'sets_total': len(sets), 'sets_ready': full,
        'per_set': sorted(per_set, key=lambda x: x['need'] - x['ready'])[:12],
        'cells': {k: v for k, v in sorted(cells.items())},
        'slots': slots, 'slots_1': with1, 'slots_2': with2,
        'jobs': jobs, 'oldest_queued_h': int(age[0][0]) if age and age[0] else 0,
        'lead_p50_h': int(lead[0][0]) if lead and len(lead[0]) == 2 else 0,
        'lead_p95_h': int(lead[0][1]) if lead and len(lead[0]) == 2 else 0,
    }


def main() -> None:
    m = collect()
    if '--json' in sys.argv:
        print(json.dumps(m, ensure_ascii=False))
        return
    print(f"полностью готовых комплектов : {m['sets_ready']} из {m['sets_total']}")
    print(f"слотов с запасом             : {m['slots']} "
          f"(с 1 заменой {m['slots_1']}, с 2 — {m['slots_2']})")
    print(f"заданий                      : {m['jobs']}; старейшему {m['oldest_queued_h']} ч")
    print(f"«в очереди → принят»         : p50 {m['lead_p50_h']} ч, p95 {m['lead_p95_h']} ч")
    ready_cells = sum(1 for v in m['cells'].values() if v[1])
    print(f"\nячеек band×стиль×ярус        : {len(m['cells'])}, "
          f"с готовым комплектом {ready_cells}")
    print('\nближе всего к готовности:')
    for r in m['per_set'][:8]:
        print(f"  №{r['n']:<4} {r['set_id']:16} {r['ready']}/{r['need']} "
              f"— не хватает {r['need'] - r['ready']}")


if __name__ == '__main__':
    main()

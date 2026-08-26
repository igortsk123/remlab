#!/usr/bin/env python3
"""Глобальная пост-оптимизация сетов — T5 truth-first (рефери §9–10: greedy «каждый предмет
отдельно хорош — комплект средний»; сначала top-K на роль, потом set-level поиск).

v1: локальный поиск по уже сохранённым alternates (top-3 на роль от compose2):
  - целевая функция уровня НАБОРА: среднее компонент set_score (материал/масса/теплота/
    отделка/узор/цвет — GNN-мотивация набора) + стилевой вектор замен;
  - охрана: hard-пропорции не ухудшаются (proportion_check), цена замены в ±30% исходной,
    качество карточки ≥ 0.65;
  - принимаем замену только при росте J; проходов ≤ 2 (сходится быстро — поиск локальный).

Пишет sets3-optimized.json + отчёт-сравнение (A/B против greedy). sets3.json НЕ трогает:
переключение на оптимизированные сеты — отдельное решение после просмотра A/B владельцем.

  ~/venvs/scout/bin/python set_optimize.py [--sets 1,21,55]
"""
import copy
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import enrich_bridge as EB          # noqa: E402
import proportion_check             # noqa: E402
import set_score                    # noqa: E402

PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab',
        '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']
MIN_GAIN = 0.05
PRICE_BAND = 0.30


def fetch_products(keys: set[tuple]) -> dict:
    if not keys:
        return {}
    cond = ','.join(f"({m},'{e}')" for m, e in keys)
    out = subprocess.run(PSQL, input=f"""
        select shop_mid, external_id, name, shop, coalesce(direct_url, url, ''),
               w_cm, d_cm, dia_cm, h_cm, price_rub, in_stock::int, coalesce(image_url,'')
          from products where (shop_mid, external_id) in ({cond});
    """, capture_output=True, text=True).stdout
    res = {}
    for line in out.strip().split('\n'):
        f = line.split('\x1f')
        if len(f) >= 11:
            num = lambda v: float(v) if v else None  # noqa: E731
            w, d, dia = num(f[5]), num(f[6]), num(f[7])
            fp = (w * d / 1e4 if w and d else
                  3.1416 * (dia / 200) ** 2 if dia else None)
            res[(int(f[0]), f[1])] = {
                'mid': int(f[0]), 'eid': f[1], 'name': f[2], 'shop': f[3], 'url': f[4],
                'w': w, 'd': d, 'dia': dia, 'h': num(f[8]),
                'fp': round(fp, 3) if fp else None,
                # ФОТО БЕРЁМ ВМЕСТЕ С ТОВАРОМ (26.08): раньше строка каталога не несла картинку,
                # и слияние `{**cur, **row}` оставляло позиции фото ПРЕДЫДУЩЕГО товара.
                'price': int(f[9]) if f[9] else None, 'in_stock': f[10] == '1',
                'img': (f[11] or None) if len(f) > 11 else None}
    return res


def J(idx: int, sets: list) -> float:
    comps = set_score.score(idx + 1, sets)
    nums = [v for v in comps.values() if isinstance(v, (int, float))]
    return sum(nums) / len(nums) if nums else 0.0


def optimize(sets: list, only: set[int] | None) -> dict:
    # один заход в БД за всеми альтернативами
    keys = set()
    for i, st in enumerate(sets):
        if only and (i + 1) not in only:
            continue
        for alts in (st.get('alternates') or {}).values():
            for a in alts:
                keys.add((a['mid'], a['eid']))
    cat = fetch_products(keys)
    report = {'improved': 0, 'checked': 0, 'swaps': []}
    for i, st in enumerate(sets):
        if only and (i + 1) not in only:
            continue
        report['checked'] += 1
        base_viol = len(proportion_check.check(i + 1, sets))
        base_j = J(i, sets)
        target_style = st.get('style')
        for _pass in range(2):
            changed = False
            for role, alts in sorted((st.get('alternates') or {}).items()):
                cur = st['items'].get(role)
                if not cur:
                    continue
                cur_style = (EB.style_scores(cur['mid'], cur['eid']) or {}).get(target_style, 5.0)
                for a in alts:
                    row = cat.get((a['mid'], a['eid']))
                    if not row or not row['in_stock'] or row['fp'] is None:
                        continue
                    if not cur.get('price') or not row['price'] or \
                            abs(row['price'] - cur['price']) > PRICE_BAND * cur['price']:
                        continue
                    if not EB.quality_ok(row['mid'], row['eid']):
                        continue
                    alt_style = (EB.style_scores(row['mid'], row['eid']) or {}).get(target_style, 5.0)
                    if alt_style < cur_style - 0.5:
                        continue
                    trial = list(sets)
                    trial[i] = copy.deepcopy(sets[i])
                    # позиция собирается ЦЕЛИКОМ из нового товара; от слота переносим только
                    # слотовую метаинформацию, визуальные признаки старой картинки не тащим
                    trial[i]['items'][role] = dict(
                        row, **{k: cur[k] for k in ('qty', 'why', 'score', 'pair_key',
                                                    'pair_provenance') if k in cur})
                    if len(proportion_check.check(i + 1, trial)) > base_viol:
                        continue
                    nj = J(i, trial)
                    if nj > base_j + MIN_GAIN:
                        sets[i] = trial[i]
                        st = sets[i]
                        report['swaps'].append({'set': i + 1, 'role': role,
                                                'from': cur['name'][:48], 'to': row['name'][:48],
                                                'j': [round(base_j, 3), round(nj, 3)]})
                        base_j, cur, changed = nj, st['items'][role], True
            if not changed:
                break
        if any(s['set'] == i + 1 for s in report['swaps']):
            report['improved'] += 1
    return report


def main() -> None:
    only = None
    if '--sets' in sys.argv:
        only = {int(x) for x in sys.argv[sys.argv.index('--sets') + 1].split(',')}
    sets = json.load(open(os.path.join(HERE, 'sets3.json')))
    before = [round(J(i, sets), 3) for i in range(len(sets))]
    rep = optimize(sets, only)
    after = [round(J(i, sets), 3) for i in range(len(sets))]
    json.dump(sets, open(os.path.join(HERE, 'sets3-optimized.json'), 'w'),
              ensure_ascii=False, indent=1)
    json.dump(rep, open(os.path.join(HERE, 'set-optimize-report.json'), 'w'),
              ensure_ascii=False, indent=1)
    n = rep['checked']
    d = [a - b for a, b in zip(after, before) if a != b]
    print(f"проверено {n} сетов, улучшено {rep['improved']}, замен {len(rep['swaps'])}; "
          f"средний прирост J по улучшенным {sum(d)/len(d):.3f}" if d else
          f"проверено {n} сетов — улучшений не найдено (greedy уже локально оптимален "
          f"на top-3 альтернативах)")
    for s in rep['swaps'][:8]:
        print(f"  сет {s['set']} {s['role']}: «{s['from']}» → «{s['to']}» (J {s['j'][0]}→{s['j'][1]})")
    print('→ sets3-optimized.json (sets3.json не тронут; переключение — решение владельца)')


if __name__ == '__main__':
    main()

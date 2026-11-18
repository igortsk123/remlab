"""Построитель границ ценовых ступеней роли → `rules/price-segments.json` (ОТДЕЛЬНАЯ команда, ночью сама не запускается;
v1 заморожено до явного пересчёта; автопересчёт с гистерезисом — позже, план `plans/price-segments-01.md`).

Метод (Codex 18.11, `_intake/codex/2026-11-18-price-segments-answer.md`): цена СЕМЕЙСТВА = медиана показываемых цен его вариантов
(`price_tiers.family_prices`); ступени — терцили цен семейств роли, граница стоит на разрыве между разными ценами (одна цена — в одной
ступени): B1 — первая цена «комфорта», B2 — первая цена «премиума»; хвосты не режутся, верх премиума открыт.
Метод по числу семейств N (пороги — `rules/price-segments-config.json`):
  local    N ≥ 30 и ≥ 10 разных цен — свои терцили;
  shrink   15 ≤ N < 30 — смесь своих терцилей и «приора» в log-пространстве, вес своих (N−15)/15;
  prior    7 ≤ N < 15 — только приор: медиана роли × типичное отношение «терциль/медиана» зрелых ролей (родитель, иначе общий);
  previous N < 7 или < 3 разных цен — прежние опубликованные границы, иначе `manual` из конфига, иначе границ нет (`none`).
Приор считается по зрелым ролям (`local`) явной родительской группы конфига (≥3 роли и ≥100 семейств), иначе по всем зрелым
(≥5 ролей и ≥500 семейств).

  python3 price_segments_build.py --selftest
  ~/venvs/scout/bin/python price_segments_build.py              # сухо: таблица границ и отличие от текущего файла
  ~/venvs/scout/bin/python price_segments_build.py --write      # записать rules/price-segments.json (после проверки таблицы)
"""
import datetime
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import price_tiers as PT  # noqa: E402

CONFIG_PATH = os.path.join(HERE, 'rules', 'price-segments-config.json')
SCHEMA = 1


def quantile7(sorted_vals: list, q: float) -> float:
    """Квантиль type-7 (линейная интерполяция) по отсортированному списку."""
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    h = (n - 1) * q
    lo = int(math.floor(h))
    hi = min(lo + 1, n - 1)
    return float(sorted_vals[lo] + (h - lo) * (sorted_vals[hi] - sorted_vals[lo]))


def snap_bounds(prices: list, cuts=(1 / 3, 2 / 3)):
    """Границы терцилей на разрыве цен: B — первая цена верхней группы; число цен ниже B — ближайшее к долям `cuts`.
    Одна цена не делится между ступенями. → (B1, B2) или None, если разных цен меньше трёх."""
    ps = sorted(float(x) for x in prices)
    n = len(ps)
    vals = sorted(set(ps))
    if len(vals) < 3:
        return None
    below = {}
    c = 0
    for v in ps:
        below.setdefault(v, c)
        c += 1
    cand = vals[1:]                                   # граница на самой низкой цене оставила бы «эконом» пустым
    b1 = min(cand, key=lambda v: (abs(below[v] - cuts[0] * n), v))
    cand2 = [v for v in vals if v > b1]
    if not cand2:
        return None
    b2 = min(cand2, key=lambda v: (abs(below[v] - cuts[1] * n), v))
    return b1, b2


def ratios(prices: list, cuts) -> list:
    """ln(Qk/медиана) собственных терцилей роли (type-7) — «форма» её цен для приора."""
    ps = sorted(float(x) for x in prices)
    med = statistics.median(ps)
    return [math.log(quantile7(ps, c) / med) for c in cuts]


def build(fam: dict, cfg: dict, prev: dict | None = None) -> dict:
    """fam {роль: {семейство: цена}} → {'roles': {роль: {boundaries_rub, families, distinct_prices, method, ...}}}."""
    cuts = cfg['cuts']
    prev_roles = (prev or {}).get('roles') or {}
    stat = {}
    for role, fm in fam.items():
        ps = [p for p in fm.values() if p > 0]
        stat[role] = {'n': len(ps), 'dist': len(set(ps)), 'prices': ps, 'med': statistics.median(ps) if ps else 0.0}
    mature = {r for r, s in stat.items() if s['n'] >= cfg['min_local_families'] and s['dist'] >= cfg['min_local_distinct_prices']}
    parent_of = {r: g for g, rs in cfg['parents'].items() for r in rs}

    def delta(roles):
        """Медиана по ролям ln(Qk/медиана) → список по числу границ."""
        return [statistics.median(ratios(stat[r]['prices'], cuts)[k] for r in roles) for k in range(len(cuts))]

    def prior_for(role):
        """→ (приор [Q1, Q2] в рублях, источник) или None."""
        g = parent_of.get(role)
        for src, name, rs, need in (('parent', g, [r for r in cfg['parents'].get(g, []) if r in mature and r != role], cfg['parent_prior']),
                                    ('global', 'all', [r for r in mature if r != role], cfg['global_prior'])):
            if len(rs) >= need['min_mature_roles'] and sum(stat[r]['n'] for r in rs) >= need['min_families']:
                d = delta(rs)
                return [stat[role]['med'] * math.exp(x) for x in d], f'{src}:{name}'
        return None

    out = {}
    for role in sorted(stat):
        s = stat[role]
        e = {'families': s['n'], 'distinct_prices': s['dist'], 'median_rub': round(s['med'])}
        if role in mature:
            b = snap_bounds(s['prices'], cuts)
            e.update(method='local', boundaries_rub=[round(b[0]), round(b[1])])
        elif s['n'] >= cfg['shrink_from_families'] and s['dist'] >= cfg['min_distinct_prices_any'] and prior_for(role):
            pr, src = prior_for(role)
            ps = sorted(s['prices'])
            w = (s['n'] - cfg['shrink_from_families']) / float(cfg['min_local_families'] - cfg['shrink_from_families'])
            b = [math.exp(w * math.log(quantile7(ps, c)) + (1 - w) * math.log(p)) for c, p in zip(cuts, pr)]
            e.update(method='shrink', prior=src, weight_local=round(w, 2), boundaries_rub=[int(round(b[0], -1)), int(round(b[1], -1))])
        elif s['n'] >= cfg['prior_only_from_families'] and s['dist'] >= cfg['min_distinct_prices_any'] and prior_for(role):
            pr, src = prior_for(role)
            e.update(method='prior', prior=src, boundaries_rub=[int(round(pr[0], -1)), int(round(pr[1], -1))])
        elif (prev_roles.get(role) or {}).get('boundaries_rub'):
            e.update(method='previous', boundaries_rub=prev_roles[role]['boundaries_rub'])
        elif (cfg.get('manual') or {}).get(role):
            e.update(method='manual', boundaries_rub=cfg['manual'][role])
        else:
            e.update(method='none', boundaries_rub=None)
        b = e['boundaries_rub']
        if b and not (0 < b[0] < b[1]):                # приор мог схлопнуть границы — тогда ступеней нет, а не кривые
            e.update(method='none', boundaries_rub=None, note='границы схлопнулись')
        out[role] = e
    return {'roles': out}


def table(rules: dict, fam: dict) -> list:
    """Строки таблицы: роль · семейств · цен · метод · B1 · B2 · сколько семейств в эконом/комфорт/премиум."""
    rows = ['роль\tсемейств\tцен\tметод\tB1\tB2\tэконом\tкомфорт\tпремиум']
    for role, e in sorted(rules['roles'].items(), key=lambda x: -x[1]['families']):
        b = e['boundaries_rub']
        cnt = {'lo': 0, 'mid': 0, 'hi': 0}
        if b:
            for p in fam[role].values():
                cnt[PT.KEYS[0] if p < b[0] else PT.KEYS[1] if p < b[1] else PT.KEYS[2]] += 1
        rows.append(f"{role}\t{e['families']}\t{e['distinct_prices']}\t{e['method']}{('/' + e['prior']) if e.get('prior') else ''}\t"
                    f"{b[0] if b else '—'}\t{b[1] if b else '—'}\t{cnt['lo']}\t{cnt['mid']}\t{cnt['hi']}")
    return rows


def _selftest() -> int:
    bad = 0
    cfg = json.load(open(CONFIG_PATH, encoding='utf-8'))
    # одинаковые цены не делятся: 40 семейств по 100, 20 по 200, 20 по 300 → B1=200 (эконом 40), B2=300 (комфорт 20)
    ps = [100] * 40 + [200] * 20 + [300] * 20
    b = snap_bounds(ps)
    if b != (200.0, 300.0):
        bad += 1
        print('  FAIL: граница на разрыве цен', b)
    for v in set(ps):
        if sum(1 for x in ps if x == v and (x < b[0]) != (v < b[0])) or sum(1 for x in ps if x == v and (x < b[1]) != (v < b[1])):
            bad += 1
            print('  FAIL: одна цена в двух ступенях', v)
    ps = list(range(1, 91))
    b = snap_bounds(ps)
    cnt = [sum(1 for x in ps if x < b[0]), sum(1 for x in ps if b[0] <= x < b[1]), sum(1 for x in ps if x >= b[1])]
    if cnt != [30, 30, 30]:
        bad += 1
        print('  FAIL: равномерные цены → терцили 30/30/30', cnt)
    if snap_bounds([5, 5, 5, 7, 7]) is not None:
        bad += 1
        print('  FAIL: меньше трёх разных цен → границ нет')
    # хвосты не режутся: самая дешёвая — эконом, самая дорогая (выброс) — премиум
    ps = list(range(1000, 1090)) + [5_000_000]
    b = snap_bounds(ps)
    if not (b[0] > 1000 and b[1] < 5_000_000):
        bad += 1
        print('  FAIL: выброс не должен утащить границы', b)
    # методы по числу семейств
    import random
    rnd = random.Random(7)
    mk = lambda n, base: {f'f{i}': round(base * math.exp(rnd.gauss(0, .6)), -1) + i for i in range(n)}  # noqa: E731
    fam = {'диван': mk(200, 80000), 'кресло': mk(100, 30000), 'пуф': mk(60, 11000), 'банкетка': mk(20, 7000),
           'кроватка': mk(9, 9000), 'прихожая': mk(5, 30000), 'стенка': mk(2, 30000)}
    R = build(fam, cfg)['roles']
    got = {k: v['method'] for k, v in R.items()}
    if got != {'диван': 'local', 'кресло': 'local', 'пуф': 'local', 'банкетка': 'shrink', 'кроватка': 'none', 'прихожая': 'none', 'стенка': 'none'}:
        bad += 1
        print('  FAIL: методы по N', got)
    if not R['банкетка']['boundaries_rub'] or not (R['банкетка']['boundaries_rub'][0] < R['банкетка']['boundaries_rub'][1]):
        bad += 1
        print('  FAIL: shrink даёт возрастающие границы', R['банкетка'])
    fam2 = dict(fam, **{'пуф': mk(10, 11000), 'шкаф': mk(250, 18000), 'комод': mk(150, 25000), 'стеллаж': mk(100, 11000)})
    R2 = build(fam2, cfg)['roles']                                      # пуф: 10 семейств; родитель — 2 зрелые роли (<3) → общий приор
    if R2['пуф']['method'] != 'prior' or not R2['пуф']['boundaries_rub'] or not R2['пуф']['prior'].startswith('global'):
        bad += 1
        print('  FAIL: 7 ≤ N < 15 → приор (родитель мал → общий)', R2['пуф'])
    R2b = build(dict(fam2, **{'банкетка': mk(10, 7000), 'кресло': mk(100, 30000), 'пуф': mk(60, 11000)}), cfg)['roles']
    if not R2b['банкетка']['prior'].startswith('parent'):
        bad += 1
        print('  FAIL: родитель из ≥3 зрелых ролей и ≥100 семейств — приор родителя', R2b['банкетка'])
    # прежние и ручные границы для N < 7
    prev = {'roles': {'прихожая': {'boundaries_rub': [20000, 40000]}}}
    cfg_m = dict(cfg, manual={'стенка': [10000, 50000]})
    R3 = build(fam, cfg_m, prev)['roles']
    if not (R3['прихожая']['method'] == 'previous' and R3['прихожая']['boundaries_rub'] == [20000, 40000]
            and R3['стенка']['method'] == 'manual'):
        bad += 1
        print('  FAIL: N < 7 → прежние, иначе ручные', R3['прихожая'], R3['стенка'])
    # ступени по итоговым границам не пересекаются и покрывают все цены
    for role, e in R.items():
        if e['boundaries_rub']:
            ts = [PT.tier_of(role, p, {'roles': R}) for p in fam[role].values()]
            if None in ts or set(ts) - set(PT.KEYS):
                bad += 1
                print('  FAIL: каждая цена семейства — ровно в одной ступени', role)
    print(f'price_segments_build selftest: случаев 11, ошибок {bad}')
    return 1 if bad else 0


def main(argv: list) -> int:
    if '--selftest' in argv:
        return _selftest()
    cfg = json.load(open(CONFIG_PATH, encoding='utf-8'))
    prev = PT.load()
    fam = PT.family_prices(rooms=True)
    res = build(fam, cfg, prev)
    today = datetime.date.today().isoformat()
    ver = f"{today}.1"
    if prev.get('version', '').startswith(today):
        ver = f"{today}.{int(prev['version'].split('.')[-1]) + 1}"
    rules = {'schema_version': SCHEMA, 'version': ver, 'built_at': today, 'price_field': 'coalesce(price_shown_rub, price_rub)',
             'family_algorithm': 'mesh_family_rep, иначе магазин + модель по названию (без цвета/ткани/размера) + ширина до 10 см',
             'algorithm': {'cuts': cfg['cuts'], 'family_price': 'median', 'boundary': 'на разрыве цен; B1/B2 — первая цена комфорта/премиума',
                           'min_local_families': cfg['min_local_families']},
             'population': 'по всем стилям: активен, в наличии, цена > 0, живое фото (+ каталог спальни/прихожей: свежий фид, живое фото); '
                           'не влияют меш, габариты, стиль, конверт',
             'config': 'rules/price-segments-config.json', **res}
    print('\n'.join(table(rules, fam)))
    if prev.get('roles'):
        ch = [(r, (prev['roles'].get(r) or {}).get('boundaries_rub'), e['boundaries_rub']) for r, e in rules['roles'].items()
              if (prev['roles'].get(r) or {}).get('boundaries_rub') != e['boundaries_rub']]
        print(f"\nотличие от версии {prev.get('version')}: {len(ch)} ролей" + ''.join(f"\n  {r}: {a} → {b}" for r, a, b in ch[:40]))
    if '--write' in argv:
        json.dump(rules, open(PT.RULES_PATH, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        open(PT.RULES_PATH, 'a').write('\n')
        print(f'записано {PT.RULES_PATH} (версия {ver})')
    else:
        print('\nсухо: файл не записан (--write)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

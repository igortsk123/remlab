"""Аудит выбросов цены ДО границ ценовых ступеней (T-20261118-61/4; план `plans/price-segments-01.md`, Codex
`_intake/codex/2026-11-18-price-segments-answer.md` § «Выбросы»).

Зачем: в роли «шкаф» оказались комплектующие гардеробных систем (направляющие, штанги, заглушки по 3–20 ₽), в «стеллаже» —
крепёж и заглушки: они сдвигают терцили (эконом = «заглушки»). Дорогие дизайнерские вещи — законный премиум, их по цене не режем.

Что делает (всё — по правилам `rules/price-segments-config.json` → `outliers`, не по ID товара):
  ИСКЛЮЧЕНИЕ из популяции границ (только это, с причиной) — правило `component_name`: название начинается с термина комплектующей /
  запчасти / крепежа (в первых пяти словах и РАНЬШЕ слова самой роли: «Люстра на штанге», «Ваза с ручками» — целы), либо в названии
  есть «накладк…» (накладки на диван — запчасть). Товар не удаляется и в ленте не прячется — просто не считается в границах.
  ТОЛЬКО ОТЧЁТ (Codex: «не обрезать автоматически за дороговизну»): `family_vs_variants` — цена варианта дальше ×3 от медианы своего
  семейства; `role_mad` — |ln(цена семейства) − медиана ln роли| > 5 × 1,4826 × MAD роли; `low_price` — цена < `low_price_rub`.

Модуль чистый (без БД): `audit(rows, cfg)` → (оставшиеся строки, отчёт). Строка популяции: роль, shop_mid, external_id, rep, имя, ширина, цена.
  python3 price_outliers.py --selftest
"""
import math
import re
import statistics
import sys

try:
    import price_tiers as PT
except ImportError:  # pragma: no cover
    PT = None


def _tokens(name: str) -> list:
    return re.findall(r'[\w\-./]+', (name or '').lower().replace('ё', 'е'))


def component_reason(name: str, role: str, cfg: dict):
    """Причина исключения по названию или None. `terms` — основы слов комплектующей (`exact_terms` — слово целиком: «ручка», «опора»,
    чтобы «с ручками» и «опорный» не цеплялись): нужно вхождение в первых `head_words` словах и раньше слова роли (основа — первые
    `role_stem` букв названия роли); `anywhere` — основы, которые достаточно найти где угодно."""
    toks = _tokens(name)
    head = toks[:cfg.get('head_words', 5)]
    stem = (role or '').lower().replace('ё', 'е')[:cfg.get('role_stem', 4)]
    role_at = next((i for i, t in enumerate(toks) if stem and t.startswith(stem)), len(toks))
    for i, t in enumerate(head):
        if i >= role_at:
            break
        for term in cfg.get('terms', []):
            if t.startswith(term):
                return f'component_name:{term}'
        if t in cfg.get('exact_terms', []):
            return f'component_name:{t}'
    for t in toks:
        for term in cfg.get('anywhere', []):
            if t.startswith(term):
                return f'component_name:{term}'
    return None


def audit(rows: list, cfg: dict):
    """rows → (kept_rows, report). report: {'excluded': {роль: {причина: [строки]}}, 'flags': {правило: [(роль, семейство, цена, имя, деталь)]},
    'n_in', 'n_kept'}. Исключает только `component_name` (если `exclude` включён в cfg); флаги по статистике — не исключают."""
    c = cfg.get('outliers') or {}
    kept, excluded = [], {}
    for r in rows:
        why = None
        if c.get('exclude_components', True):
            why = f'component_shop:{r[1]}' if r[1] in (c.get('exclude_shops') or {}) else component_reason(r[4], r[0], c)
        if why:
            excluded.setdefault(r[0], {}).setdefault(why, []).append(r)
        else:
            kept.append(r)
    recall = {}                                     # магазины-исключения: сколько узнало бы одно правило названий (оценка запаса)
    for role, d in excluded.items():
        for why, rs in d.items():
            if why.startswith('component_shop:'):
                recall[why.split(':')[1]] = [sum(1 for r in rs if component_reason(r[4], r[0], c)), len(rs)]
    flags = {'family_vs_variants': [], 'role_mad': [], 'low_price': []}
    by = {}
    for r in kept:
        by.setdefault(r[0], {}).setdefault(PT.family_key(r[1], r[4], r[5], r[3]), []).append(r)
    k = c.get('variant_ratio', 3)
    low = c.get('low_price_rub', 300)
    for role, fams in by.items():
        fp = {f: statistics.median([x[6] for x in v]) for f, v in fams.items()}
        for f, v in fams.items():
            if len(v) > 1:
                for x in v:
                    if x[6] > k * fp[f] or x[6] < fp[f] / k:
                        flags['family_vs_variants'].append((role, f, x[6], x[4], f'медиана семейства {round(fp[f])}'))
            for x in v:
                if x[6] < low:
                    flags['low_price'].append((role, f, x[6], x[4], f'< {low}'))
        if len(fp) >= c.get('mad_min_families', 7):
            ls = [math.log(p) for p in fp.values()]
            med = statistics.median(ls)
            mad = statistics.median([abs(x - med) for x in ls])
            thr = c.get('mad_k', 5) * 1.4826 * mad
            if thr > 0:
                for f, p in fp.items():
                    if abs(math.log(p) - med) > thr:
                        flags['role_mad'].append((role, f, p, fams[f][0][4], f"{'ниже' if math.log(p) < med else 'выше'} медианы роли {round(math.exp(med))} (порог ×{math.exp(thr):.1f})"))
    return kept, {'excluded': excluded, 'flags': flags, 'n_in': len(rows), 'n_kept': len(kept), 'shop_name_recall': recall,
                  'shop_reasons': dict(c.get('exclude_shops') or {})}


def summary_for_rules(rep: dict) -> dict:
    """Компактное для `price-segments.json`: сколько и почему исключено по ролям (списки товаров — в отчёте, не в правиле)."""
    return {'excluded_total': rep['n_in'] - rep['n_kept'],
            'excluded_by_role': {role: {why: len(rs) for why, rs in d.items()} for role, d in sorted(rep['excluded'].items())},
            'shops': {m: {'reason': rep['shop_reasons'].get(m), 'by_name_alone': f'{a} из {b}'} for m, (a, b) in rep['shop_name_recall'].items()},
            'flags': {k: len(v) for k, v in rep['flags'].items()}}


def lines(rep: dict, limit: int = 8) -> list:
    out = [f"аудит выбросов: в популяции {rep['n_in']}, исключено {rep['n_in'] - rep['n_kept']} (комплектующие: по названию и по правилу магазина), осталось {rep['n_kept']}"]
    for role, d in sorted(rep['excluded'].items(), key=lambda x: -sum(len(v) for v in x[1].values())):
        n = sum(len(v) for v in d.values())
        out.append(f"  исключено · {role}: {n} · " + ', '.join(f'{w.split(":")[1]} {len(v)}' for w, v in sorted(d.items(), key=lambda x: -len(x[1]))[:8]))
        ex = sorted((r for v in d.values() for r in v), key=lambda r: r[6])
        out += [f'      {round(r[6])} ₽ · {r[4][:72]}' for r in ex[:3]]
    for m, (a, b) in rep['shop_name_recall'].items():
        out.append(f"  магазин {m}: {rep['shop_reasons'].get(m)}; правило названий само узнало бы {a} из {b}")
    for k, v in rep['flags'].items():
        out.append(f'  флаг (только отчёт) · {k}: {len(v)}')
        out += [f'      {role} · {round(p)} ₽ · {name[:64]} · {det}' for role, _f, p, name, det in sorted(v, key=lambda x: x[2])[:limit]]
    return out


def _selftest() -> int:
    bad = 0
    c = {'head_words': 5, 'role_stem': 4, 'terms': ['штанг', 'направляющ', 'заглушк', 'кронштейн', 'полкодержат', 'абажур'], 'anywhere': ['накладк'], 'exact_terms': ['ручка', 'опора']}
    cases = [('INTEGRO Щеточный уплотнитель', 'шкаф', None), ('ВОГ ЛАЙТ Штангодержатель пластиковый', 'шкаф', 'component_name:штанг'),
             ('ИКМ 15 Направляющая универсальная, L-6000', 'шкаф', 'component_name:направляющ'),
             ('Ваза Glasar с ручками 17х17х23см', 'ваза', None), ('Кашпо с ручками Glasar 22х16х19 см', 'ваза', None),
             ('PS65 Ручка, L-100, серебро', 'шкаф', 'component_name:ручка'), ('Шкаф с опорным цоколем', 'шкаф', None), ('Люстра на штанге Arte Lamp', 'люстра', None),
             ('Накладки 2 шт. на диван Босс', 'диван', 'component_name:накладк'), ('Босс кресло-кровать Накладки Дымчатый', 'кресло', 'component_name:накладк'),
             ('Шкаф-купе Рим 2 двери с ручкой', 'шкаф-купе', None), ('Кронштейн Verdemax для кашпо 35 см', 'кашпо', 'component_name:кронштейн'),
             ('Абажур серая полоска, е27', 'лампа', 'component_name:абажур'), ('Торшер Citilux со столиком и абажуром', 'торшер', None)]
    for name, role, want in cases:
        got = component_reason(name, role, c)
        if got != want:
            bad += 1
            print('  FAIL: название', name, '→', got, 'ждали', want)
    mk = lambda role, i, name, p, rep='': (role, '1', str(i), rep, name, 100.0, float(p))  # noqa: E731
    rows = [mk('шкаф', i, f'Шкаф Модель{i} 100x50', 20000 + i * 100) for i in range(12)] + [mk('шкаф', 100, 'ВОГ Штанга овальная', 13), mk('шкаф', 101, 'PS Направляющая верхняя', 16)]
    kept, rep = audit(rows + [mk('шкаф', 200, 'Шкаф Витрина 100', 30000)[:1] + ('9', '201', '', 'Корзина сетчатая', 100.0, 1200.0)], {'outliers': {**c, 'exclude_shops': {'9': 'тест'}}})
    if sum(1 for _ in rep['excluded']['шкаф'].get('component_shop:9', [])) != 1:
        bad += 1
        print('  FAIL: правило магазина с причиной', rep['excluded'])
    kept, rep = audit(rows, {'outliers': c})
    if len(kept) != 12 or rep['n_in'] - rep['n_kept'] != 2 or list(rep['excluded']) != ['шкаф']:
        bad += 1
        print('  FAIL: исключены только комплектующие, мебель на месте', len(kept), rep['n_kept'])
    if rep['flags']['low_price']:
        bad += 1
        print('  FAIL: исключённые в флаги не попадают', rep['flags']['low_price'])
    # статистика только флагует, не исключает: дорогая вещь и вариант-выброс остаются в популяции
    rows2 = [mk('ваза', i, f'Ваза Модель{i} серая', 3000 + i * 40) for i in range(12)] + [mk('ваза', 50, 'Ваза Дизайнерская', 900000)] + \
            [mk('ваза', 60, 'Ваза Дуэт синяя 20', 4000, 'a_dua'), mk('ваза', 61, 'Ваза Дуэт красная 20', 4100, 'a_dua'), mk('ваза', 62, 'Ваза Дуэт белая 20', 20000, 'a_dua')]
    kept2, rep2 = audit(rows2, {'outliers': {**c, 'mad_min_families': 7}})
    if len(kept2) != len(rows2):
        bad += 1
        print('  FAIL: статистические флаги ничего не исключают')
    if not any(f[2] == 900000 for f in rep2['flags']['role_mad']) or not any(f[2] == 20000 for f in rep2['flags']['family_vs_variants']):
        bad += 1
        print('  FAIL: флаги role_mad (900000) и family_vs_variants (вариант 20000 при медиане 4100)', rep2['flags'])
    s = summary_for_rules(rep)
    if s['excluded_total'] != 2 or s['excluded_by_role'] != {'шкаф': {'component_name:штанг': 1, 'component_name:направляющ': 1}}:
        bad += 1
        print('  FAIL: сводка для правила', s)
    print(f'price_outliers selftest: случаев 14, ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else 0)

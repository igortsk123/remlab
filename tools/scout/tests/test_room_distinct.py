#!/usr/bin/env python3
"""Две комнаты одного назначения в одном стиле — разные товары (план bedroom-distinct-01, владелец 07.11 голос TG 348).

ЗАЧЕМ. Сборщик банка берёт лучшее по роли для каждой комнаты независимо — спальня 1 и 2 одного стиля совпадали в 3–5 товарах
из 5–6 (замер ведущего 07.11). Правило витрины (`demo_room.distinct_items`): вторая комната того же типа и стиля по каждой роли
берёт лучший товар, которого нет в предыдущих (свои `alternates`, потом запас того же стиля), по тем же правилам, что сторож
модели: годная модель, известный размер, полоса размера у чужого товара; пара тумб — пара; пул исчерпан — повтор и строка `dup`
(сборка печатает WARN demo_room_dup); порядок комнат — реестр квартиры. Без базы и файлов: адаптер, товары и солвер — заглушки.

  python3 tests/test_room_distinct.py
"""
from __future__ import annotations

import copy
import os
import sys

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import demo_room as R  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


def solve(geo, dims, purpose):
    return {**{r: {'x': 50.0 + 10 * i, 'z': 50.0, 'rot': 0} for i, (r, *_x) in enumerate(dims)}, '_fill_pct': 40}


SPEC = R.Showcase(room_type='bedroom', solver_roles=('кровать', 'тумба прикроватная', 'комод'),
                  place_roles=('кровать', 'тумба прикроватная', 'комод', 'ковёр'), solve=solve, list_roles=('лампа',),
                  band_cm={'*': {}, 'single': {'кровать': {'lo': 80, 'hi': 140}}})
GEO = {'w': 400, 'd': 350}


def it(eid: str, w=100, d=50, h=60, **kw) -> dict:
    return {'mid': 1, 'eid': eid, 'name': f'товар {eid}', 'w': w, 'd': d, 'h': h, 'img': 'x', **kw}


def sku(items, role):
    x = items.get(role) or items.get(R.base_role(role))
    if not x:
        return None
    return {'sid': f"{x['mid']}_{x['eid']}", 'name': x['name'], 'w': x.get('w'), 'd': x.get('d'), 'h': x.get('h')}


def dims_of(v, s, role=''):
    s = s or {}
    if not (s.get('w') and s.get('d') and s.get('h')):
        return {'w': s.get('w'), 'd': s.get('d'), 'h': s.get('h'), 'dims_unknown': True}
    return {'w': s['w'], 'd': s['d'], 'h': s['h'], 'dims_src': 'каталог'}


def style_id(st):
    return {'сканди': 'scandi', 'лофт': 'loft'}.get(st)


def rec(room_id: str, style='сканди', purpose='couple', tier='эконом', **over) -> dict:
    r = {'room_id': room_id, 'purpose': purpose, 'style': style, 'tier': tier,
         'items': {'кровать': it('b1', 170, 210, 90), 'тумба прикроватная': it('t1', 45, 40, 50),
                   'тумба прикроватная 2': it('t1', 45, 40, 50), 'комод': it('k1', 120, 45, 80),
                   'ковёр': it('c1', 200, 140, 1), 'лампа': it('l1'), 'плед': it('p1')},
         'alternates': {'кровать': [it('b2', 170, 210, 90), it('b3', 170, 210, 90)],
                        'тумба прикроватная': [it('t2', 45, 40, 50)], 'комод': [it('k2', 120, 45, 80)],
                        'ковёр': [it('c2', 200, 140, 1)], 'плед': [it('p2')]}}
    r.update(over)
    return r


# готовая расстановка без `_room` (место замены не пересчитывается — `_fits` возвращает её как есть): ковёр стоит из неё, как
# у банка (солвер ковёр не ставит)
LAYOUT = {'кровать': {'x': 200, 'z': 100, 'rot': 0}, 'тумба прикроватная': {'x': 90, 'z': 30, 'rot': 0},
          'тумба прикроватная 2': {'x': 310, 'z': 30, 'rot': 0}, 'комод': {'x': 200, 'z': 320, 'rot': 180},
          'ковёр': {'x': 200, 'z': 200, 'rot': 0}, '_fill_pct': 40}


def build(r, used=None, spares=None, mesh_ok=None):
    v, why = R.build_variant(SPEC, copy.deepcopy(r), GEO, sku, dims_of, style_id, lead=('кровать',), lead_any=False,
                             pairs=('тумба прикроватная',), mesh_ok=mesh_ok, used=used, distinct_spares=spares,
                             layout=copy.deepcopy(LAYOUT), decor_role=lambda x: R.base_role(x) == 'плед')
    return v, why


def by_role(v) -> dict:
    out = {}
    for o in (v or {}).get('items', []) + (v or {}).get('decor', []):
        out.setdefault(o['role'], o['sku']['sid'])
    return out


def main() -> int:
    r1, r2 = rec('bedroom-1'), rec('bedroom-2')
    v0, _ = build(r1)
    v1, _ = build(r1, used=set())
    ok('без предыдущих комнат (used пуст) — вариант байт в байт прежний', v0 == v1)
    u = R.variant_sids(v1)
    ok('sid варианта — предметы 3D и строки списка', u == {'1_b1', '1_t1', '1_k1', '1_c1', '1_l1', '1_p1'}, sorted(u))

    v2, _ = build(r2, used=u)
    b2 = by_role(v2)
    ok('вторая комната того же стиля: каждая роль с запасом — первый запасной без повтора (кровать b2, тумба t2, комод k2, '
       'ковёр c2, плед p2)', [b2.get(k) for k in ('кровать', 'тумба прикроватная', 'комод', 'ковёр', 'плед')]
       == ['1_b2', '1_t2', '1_k2', '1_c2', '1_p2'], b2)
    ok('пара тумб внутри комнаты осталась парой (тумба 1 = тумба 2 = t2)',
       b2.get('тумба прикроватная') == b2.get('тумба прикроватная 2') == '1_t2', b2)
    ok('у лампы запаса нет — повтор и строка dup с причиной «пул роли исчерпан»',
       [d['role'] for d in v2.get('dup') or []] == ['лампа'] and 'пул роли исчерпан' in v2['dup'][0]['why'], v2.get('dup'))
    ok('замены — в distinct_swaps (было → стало), 5 ролей',
       sorted(e['role'] for e in v2.get('distinct_swaps') or []) == ['ковёр', 'комод', 'кровать', 'плед', 'тумба прикроватная'])
    common = (R.variant_sids(v2) & u) - {'1_l1'}
    ok('общих товаров с первой комнатой — 0, кроме роли с исчерпанным пулом', not common, common)

    # третья комната: не повторяет ни первую, ни вторую — кровать b3, у остальных пул исчерпан (повторы видны)
    u2 = u | R.variant_sids(v2)
    v3, _ = build(rec('bedroom-3'), used=u2)
    ok('третья комната: кровать — следующий без повтора (b3); тумба/комод/ковёр/плед/лампа — повтор с WARN',
       by_role(v3).get('кровать') == '1_b3'
       and sorted(d['role'] for d in v3.get('dup') or []) == ['ковёр', 'комод', 'лампа', 'плед', 'тумба прикроватная'],
       (by_role(v3), v3.get('dup')))

    # запасной, уже стоящий в первой комнате, пропускается
    r2b = rec('bedroom-2', alternates={'кровать': [it('b1', 170, 210, 90), it('b9', 170, 210, 90)]})
    v, _ = build(r2b, used={'1_b1'})
    ok('запасной, который уже в первой комнате, пропущен — следующий (b9)', by_role(v).get('кровать') == '1_b9', by_role(v))

    # годная модель: запасной без модели не берётся
    gate = lambda s: 'модель не выложена' if s.get('sid') == '1_b2' else ''   # noqa: E731
    v, _ = build(r2, used={'1_b1'}, mesh_ok=gate)
    ok('запасной без годной модели пропущен — следующий годный (b3)', by_role(v).get('кровать') == '1_b3', by_role(v))
    v, _ = build(rec('bedroom-2', alternates={'кровать': [it('b2', 170, 210, None)]}), used={'1_b1'})
    ok('запасной без размера — не берётся, повтор с причиной «размер не указан»',
       by_role(v).get('кровать') == '1_b1' and 'размер не указан' in (v.get('dup') or [{}])[0].get('why', ''), v.get('dup'))

    # запас того же стиля из других записей: в полосе размера назначения; чужой стиль сюда не идёт
    rs = rec('bedroom-2', purpose='single', alternates={})
    sp = {'кровать': [('лофт', it('bL', 120, 200, 80)), ('сканди', it('bW', 170, 210, 90)), ('сканди', it('bS', 120, 200, 80))]}
    v, _ = build(rs, used={'1_b1'}, spares=sp)
    ok('запас: чужой стиль (лофт) не берётся, свой вне полосы размера назначения (170 > 140) — пропущен, свой в полосе — взят',
       by_role(v).get('кровать') == '1_bS', by_role(v))

    # другой стиль — своя история: used по стилю (сборка ведёт словарь стиль → sid)
    vl, _ = build(rec('bedroom-2', style='лофт'), used=None)
    ok('комната другого стиля без used — как прежде (товары свои, без замен)',
       by_role(vl).get('кровать') == '1_b1' and not vl.get('distinct_swaps'), by_role(vl))

    # порядок комнат — реестр квартиры, не порядок флага
    reg = [{'id': 'living'}, {'id': 'bedroom-1'}, {'id': 'bedroom-2'}]
    order = [x['room_id'] for x in R.by_registry([rec('bedroom-2'), rec('bedroom-x'), rec('bedroom-1')], reg)]
    ok('порядок: спальня 1 первой (реестр), комната вне реестра — в конце', order == ['bedroom-1', 'bedroom-2', 'bedroom-x'], order)
    order2 = [x['room_id'] for x in R.by_registry([rec('bedroom-1'), rec('bedroom-2')], reg)]
    ok('порядок устойчив: уже по реестру — без перестановки', order2 == ['bedroom-1', 'bedroom-2'])

    # в сборке `flat215_demo.room_variants` правило подключено, повтор — громкий WARN demo_room_dup
    src = open(os.path.join(SCOUT, 'flat215_demo.py'), encoding='utf-8').read()
    ok('flat215_demo.room_variants: used по стилю, порядок by_registry, WARN:demo_room_dup',
       'used_by_style' in src and 'R.by_registry(recs' in src and 'WARN:demo_room_dup' in src)
    print(f'test_room_distinct: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

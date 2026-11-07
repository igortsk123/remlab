#!/usr/bin/env python3
"""Цвет по стилю и роли (план style-color-01, шаг 1, T-20261107-12): один оценщик `compose_common.color_eval` и его место в
ранжировании сборщиков спальни и прихожей и в квоте мешей. Без базы и сети.

ЗАЧЕМ. «Минимализм» с изумрудной кроватью и тумбами графит/розовый (витрина 06.11, разбор T-94/2): пара акцентов стиля
награждала цвет у крупной мебели, а меш стоял в ранжировании выше эстетики — штраф баллом не помогал. Здесь:
  • регрессии плана — изумрудная кровать, терракотовая кровать сканди, тумба графит/розовый, оливковый шкаф, коричневое
    дерево (не акцент), синий/зелёный бархат неоклассики (допустим);
  • ярус — ключ ДО меша: нейтральная без меша раньше цветной с готовым мешом (спальня и прихожая), forbidden не кандидат;
  • предел цветных якорей набора; правила полны (каждый стиль × группа × категория);
  • квота мешей: forbidden — не единица, порядок добора — по ярусу; без оценщика — как раньше.

  python3 tests/test_style_color.py
"""
from __future__ import annotations

import os
import sys

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)

import compose_bedroom as CB  # noqa: E402
import compose_common as CC  # noqa: E402
import compose_hall as CH  # noqa: E402
import room_mesh_demand as RMD  # noqa: E402

bad = 0


def ok(name, cond):
    global bad
    print(('OK   ' if cond else 'FAIL ') + name)
    bad += not cond


P = CC.color_policy()
T = lambda name, cls, rgb, role, style, ctx=None: CC.color_eval({'name': name, 'cls': cls, 'rgb': rgb}, role, style, P, ctx)  # noqa: E731

EMERALD = ('Кровать divan.ru Бран-2 160 Велюр Зеленый', 'accent_green', [58, 97, 89])
TERRA = ('Кровать divan.ru Слипсон 160 Велюр Терракотовый', 'accent_terra', [143, 92, 73])
GRAPH_PINK = ('Тумба прикроватная divan.ru Изи 40x56 Графитовый/Розовый', 'neutral_grey', [117, 110, 112])
OLIVE = ('Распашной шкаф divan.ru Трейвис 3-137x205 Оливковый', 'accent_yellow', [120, 118, 95])
WOOD = ('Комод Лофт 120', 'accent_terra', [140, 90, 40])           # коричневое дерево, насыщенность > 0,55 — classify: terra
NAVY = ('Кровать divan.ru Вилена 160 Велюр Синий', 'accent_blue', [30, 45, 69])
NEUTRAL = ('Кровать divan.ru Белла 160 Велюр Бежевый', 'accent_pink', [200, 150, 160])

# ---- регрессии плана
ok('изумрудная кровать: минимализм — forbidden (цвет в названии — уверенный), джапанди — не выше discouraged',
   T(*EMERALD, 'кровать', 'минимализм')['tier'] == 'forbidden'
   and T(*EMERALD, 'кровать', 'джапанди')['tier'] in ('discouraged', 'forbidden'))
ok('терракотовая кровать сканди — allowed (не отсечка): ранг мягкого якоря = нейтральной (T-12/2), дельта балла ниже; '
   'терракотовый комод сканди — ранг ниже нейтрального',
   T(*TERRA, 'кровать', 'сканди')['tier'] == 'allowed'
   and T(*TERRA, 'кровать', 'сканди')['rank'] == T(*NEUTRAL, 'кровать', 'сканди')['rank']
   and T(*TERRA, 'кровать', 'сканди')['delta'] < T(*NEUTRAL, 'кровать', 'сканди')['delta']
   and T(*TERRA, 'комод', 'сканди')['rank'] > T(*NEUTRAL, 'комод', 'сканди')['rank'])
ok('ранг allowed = preferred только у мягкого якоря сканди / современного / неоклассики; у минимализма, джапанди, лофта — нет',
   all(T(*TERRA, 'кровать', st)['rank'] == 0 for st in ('сканди', 'современный', 'неоклассика'))
   and T('Кровать Х Оливковый', 'accent_yellow', [120, 118, 95], 'кровать', 'лофт')['rank'] == 1
   and all(T('Шкаф Х Оливковый', 'accent_yellow', [120, 118, 95], 'шкаф', st)['rank'] >= 1
           for st in ('сканди', 'современный', 'неоклассика', 'лофт')))
ok('второй цветной якорь у сканди — discouraged и ранг ниже нейтрали (не больше одного якоря на набор)',
   T(*TERRA, 'кровать', 'сканди', {'chroma': 1})['tier'] == 'discouraged'
   and T(*TERRA, 'кровать', 'сканди', {'chroma': 1})['rank'] == P['tier_rank']['discouraged'])
ok('тумба графит/розовый: второй цвет — discouraged у минимализма (второй кластер не отсекает), у современного — allowed',
   T(*GRAPH_PINK, 'тумба прикроватная', 'минимализм')['tier'] == 'discouraged'
   and T(*GRAPH_PINK, 'тумба прикроватная', 'минимализм')['cat'] == 'secondary'
   and T(*GRAPH_PINK, 'тумба прикроватная', 'современный')['tier'] == 'allowed')
ok('оливковый шкаф (фото — accent_yellow): семья olive по названию; минимализм — forbidden, джапанди — discouraged',
   T(*OLIVE, 'шкаф', 'минимализм')['tier'] == 'forbidden' and T(*OLIVE, 'шкаф', 'минимализм')['family'] == 'olive'
   and T(*OLIVE, 'шкаф', 'джапанди')['tier'] == 'discouraged')
ok('коричневое дерево (фото terra, оттенок дерева) — материал, не акцент: ни в одном стиле не ниже allowed',
   all(T(*WOOD, 'комод', st)['cat'] == 'material' and T(*WOOD, 'комод', st)['tier'] in ('preferred', 'allowed')
       for st in P['styles']))
ok('синий/зелёный бархат неоклассики у кровати — preferred (допустим, наравне с нейтральной)',
   T(*NAVY, 'кровать', 'неоклассика')['tier'] == 'preferred' and T(*EMERALD, 'кровать', 'неоклассика')['tier'] == 'preferred')

# ---- признаки цвета
ok('название сильнее фото: «Бежевый» при розовом фото — нейтральный; «Белла» — не «белый»',
   T(*NEUTRAL, 'кровать', 'минимализм')['cat'] == 'neutral'
   and CC.color_evidence({'name': 'Кровать Белла 160', 'cls': 'neutral_light'}, P)[0] == 'neutral')
ok('без цвета в названии: слабая насыщенность по фото — weak (у минимализма discouraged, не forbidden), уверенная — forbidden',
   T('Тумба Х', 'accent_yellow', [120, 118, 95], 'тумба прикроватная', 'минимализм')['tier'] == 'discouraged'
   and T('Тумба Х', 'accent_green', [60, 170, 70], 'тумба прикроватная', 'минимализм')['tier'] == 'forbidden')
ok('«Серо-зелёный» — приглушённый green, «оранжевый/тёмно-серый» — яркий orange',
   CC.color_evidence({'name': 'Комод Виклу Серо-зеленый'}, P)[:2] == ('muted', 'green')
   and CC.color_evidence({'name': 'Плед Этель оранжевый/темно-серый'}, P)[:2] == ('vivid', 'orange'))
ok('лофт: терракот и рыжий — материал стиля (не якорь), у других стилей — цвет',
   T(*TERRA, 'кровать', 'лофт')['cat'] == 'material' and not T(*TERRA, 'кровать', 'лофт')['anchor']
   and T(*TERRA, 'кровать', 'современный')['anchor'])
ok('роль с номером («тумба прикроватная 2») — та же группа; незнакомая роль — декор',
   CC.color_group('тумба прикроватная 2', P) == 'large_casework' and CC.color_group('ваза', P) == 'decor')
ok('предел цветных якорей: у современного второй цветной якорь — discouraged, первый — preferred',
   T(*NAVY, 'кровать', 'современный', {'chroma': 0})['tier'] == 'preferred'
   and T(*NAVY, 'кровать', 'современный', {'chroma': 1})['tier'] == 'discouraged')
ok('счёт якорей набора: синяя кровать + графит/розовая тумба + дерево = 1',
   CC.color_anchors({'кровать': dict(zip(('name', 'cls', 'rgb'), NAVY)), 'тумба прикроватная': dict(zip(('name', 'cls', 'rgb'), GRAPH_PINK)),
                     'комод': dict(zip(('name', 'cls', 'rgb'), WOOD))}, 'современный', P) == 1)
ok('правила полны: 6 стилей × 5 групп × 6 категорий, версия и провенанс',
   len(P['styles']) == 6 and all(set(S['tiers']) == set(P['groups']) and all(set(r) == set(P['categories'])
                                                                              for r in S['tiers'].values())
                                 for S in P['styles'].values()) and P['version'] and P['provenance'].get('passport'))
ok('у «монохромов» нет цветных якорей и пары минимализма нет',
   P['styles']['минимализм']['max_chromatic_anchors'] == 0 and P['styles']['джапанди']['max_chromatic_anchors'] == 0
   and P['styles']['минимализм']['pair'] == [])

# ---- ярус — ключ ДО меша: спальня
_R = CB.rules()
C = CB.Composer([], [], set(), set(), _R, (0.8, 1.1), 6.6)


def bed(eid, name, cls, rgb, mesh=None, style='минимализм', sc=8.0):
    return {'mid': 1, 'eid': eid, 'sid': f'1:{eid}', 'role': 'кровать', 'name': name, 'cls': cls, 'cls2': cls, 'rgb': rgb,
            'mesh': mesh, 'styles': {style: sc}, 'price': 100, 'fam': eid}


rk = C.ranked([bed('g', *EMERALD, mesh='ready'), bed('w', 'Кровать Белая', 'neutral_light', [240, 240, 238]),
               bed('p', 'Кровать Тумбс Графитовый/Розовый', 'neutral_grey', [117, 110, 112], mesh='ready')], 'минимализм', {})
ok('спальня, минимализм: изумрудная с готовым мешом — не кандидат; белая без меша раньше графит/розовой с мешом',
   [c['eid'] for c in rk] == ['w', 'p'] and rk[0]['color_tier'] == 'preferred' and rk[1]['color_tier'] == 'discouraged')
rk = C.ranked([bed('t', *TERRA, mesh='ready', style='сканди'), bed('w', 'Кровать Белая', 'neutral_light', [240, 240, 238],
                                                                     style='сканди', sc=7.0)], 'сканди', {})
ok('спальня, сканди, кровать: ранг цвета равный (T-12/2) — терракотовая с мешом раньше нейтральной без меша',
   [c['eid'] for c in rk] == ['t', 'w'])
rk = C.ranked([bed('t', *TERRA, mesh='ready', style='сканди'), bed('w', 'Кровать Белая', 'neutral_light', [240, 240, 238],
                                                                     style='сканди', sc=7.0)], 'сканди', {'chroma': 1})
ok('спальня, сканди: цветной якорь в наборе уже есть — нейтральная без меша раньше терракотовой с мешом',
   [c['eid'] for c in rk] == ['w', 't'] and rk[1]['color_tier'] == 'discouraged')


def case(eid, name, cls, rgb, mesh=None, style='современный', role='комод'):
    return dict(bed(eid, name, cls, rgb, mesh, style), role=role)


rk = C.ranked([case('o', 'Комод Дигарс Оливковый', 'accent_yellow', [120, 118, 95], mesh='ready'),
               case('l', 'Комод Дигарс Латте', 'neutral_light', [220, 210, 195])], 'современный', {})
ok('спальня, современный: корпусная — нейтральная без меша раньше оливковой с мешом (ранг корпуса не выровнен)',
   [c['eid'] for c in rk] == ['l', 'o'])
ok('спальня: крупная мебель — пара стиля не награждает (балл зелёной кровати современного = стиль + дельта яруса)',
   C.score(bed('g', *EMERALD, style='современный'), 'современный', {})[0] == 8.0 + P['delta']['preferred'])
ok('спальня: в «почему» — ярус цвета и его причина', 'цвет: приглушённый цвет green (название) → preferred'
   in C.score(bed('g', *EMERALD, style='современный'), 'современный', {})[1])

# ---- прихожая
H = CH.Composer.__new__(CH.Composer)
H.R = CH.rules()


def shoe(eid, name, cls, rgb, mesh=None, sc=8.0, role='обувница'):
    return {'mid': 1, 'eid': eid, 'sid': f'1:{eid}', 'role': role, 'name': name, 'cls': cls, 'cls2': cls, 'rgb': rgb,
            'mesh': mesh, 'styles': {'джапанди': sc}, 'price': 100, 'fam': eid}


rk = H.ranked([shoe('o', 'Обувница Оливковый', 'accent_yellow', [120, 118, 95], mesh='ready'),
               shoe('n', 'Обувница Дуб натуральный', 'wood_light', [200, 170, 130]),
               shoe('v', 'Обувница Изумрудный', 'accent_green', [20, 160, 90], mesh='ready')], 'джапанди', {})
ok('прихожая, джапанди: дерево без меша раньше оливковой с мешом; изумрудная (яркая) — не кандидат',
   [c['eid'] for c in rk] == ['n', 'o'] and rk[1]['color_tier'] == 'discouraged')
rk = H.ranked([shoe('v', 'Банкетка Изумрудный', 'accent_green', [20, 160, 90], role='банкетка')], 'джапанди', {}, unknown=True)
ok('прихожая: forbidden не поднимается и для товара без оценки стиля', rk == [])

# ---- квота мешей
sl = {'h1': {'обувница': [{'role': 'обувница', 'band': {'w': [48, 66]}}]}}
g = lambda it, slot, band: None if all(lo <= it.get(k, 0) <= hi for k, (lo, hi) in band.items()) else 'вне'  # noqa: E731
q = lambda sku, name, cls, rgb, sc=7.0: {'sku': sku, 'fam': sku, 'role': 'обувница', 'w': 60, 'styles': {'минимализм': sc},  # noqa: E731
                                         'price': 100, 'name': name, 'cls': cls, 'rgb': rgb}
its = [q('1:g', 'Обувница Зеленый', 'accent_green', [58, 97, 89], sc=9.0), q('1:p', 'Обувница Белый/Розовый', 'neutral_light',
                                                                            [240, 240, 240], sc=8.5),
       q('1:w', 'Обувница Белый', 'neutral_light', [240, 240, 240])]
stt = {s['sku']: 'job' for s in its}
col = lambda it, role, st: CC.color_eval(it, role, st, P)['tier']  # noqa: E731
T0 = RMD.quota_table(sl, ['минимализм'], its, stt, set(), g, 6.6, 'sku')
T1 = RMD.quota_table(sl, ['минимализм'], its, stt, set(), g, 6.6, 'sku', color=col)
ok('квота без оценщика — как раньше (по баллу стиля: зелёная, белая/розовая, белая)',
   T0[0]['ranked'] == ['1:g', '1:p', '1:w'] and T0[0]['fit'] == 3 and T0[0]['color_forbidden'] == 0)
ok('квота с оценщиком: зелёная forbidden — не единица; белая (preferred) раньше белой/розовой (discouraged)',
   T1[0]['ranked'] == ['1:w', '1:p'] and T1[0]['fit'] == 2 and T1[0]['color_forbidden'] == 1)
T2 = RMD.quota_table(sl, ['минимализм'], its, stt, set(), g, 6.6, 'sku', color=lambda it, role, st: CC.color_eval(it, role, st, P))
ok('квота с полным оценщиком (как room_quota: {tier, rank}) — тот же порядок, что по ярусу',
   T2[0]['ranked'] == T1[0]['ranked'] and T2[0]['color_forbidden'] == 1)
ok('квота: ярус цвета — первый ключ ленты, раньше «в ленте» (T-12/2)',
   RMD.quota_table(sl, ['минимализм'], its, stt, {'1:p'}, g, 6.6, 'sku', color=col)[0]['ranked'] == ['1:w', '1:p'])
sc_its = [dict(q('1:t', 'Кровать Терракотовый', 'accent_terra', [143, 92, 73], sc=9.0), role='кровать', styles={'сканди': 9.0}),
          dict(q('1:n', 'Кровать Серый', 'neutral_grey', [150, 150, 150]), role='кровать', styles={'сканди': 7.0})]
sl_b = {'b1': {'кровать': [{'role': 'кровать', 'band': {'w': [48, 66]}}]}}
T3 = RMD.quota_table(sl_b, ['сканди'], sc_its, {s['sku']: 'job' for s in sc_its}, set(), g, 6.6, 'sku',
                     color=lambda it, role, st: CC.color_eval(it, role, st, P))
ok('квота, сканди, кровать: ранг якоря выровнен — порядок решает балл стиля (терракотовая 9 раньше серой 7)',
   T3[0]['ranked'] == ['1:t', '1:n'])

print(f'FAILS {bad}')
sys.exit(1 if bad else 0)

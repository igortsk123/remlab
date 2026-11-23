#!/usr/bin/env python3
"""Тесты detail_zones (зоны деталей/стекла/проёмов для 07, T-20261123-47/4) на заглушках: синтетическая развёртка T×T, без GLB. Запуск: python tools/scout/salad/trellis/tests_detail_zones.py"""
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import detail_zones as DZ  # noqa: E402
import mesh_type_passports as MTP  # noqa: E402

R = DZ.load_rules()
R['buttons'].update(dilate=2)
T = 256
FAIL = 0


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def scene(parts=None, tone=(60.0, 5.0, 10.0), dots=0, dot_tone=(15.0, 5.0, 10.0), part_tones=None):
    """Развёртка: одна геометрия; parts — {номер: (y0,y1,x0,x1)} (остальное — часть 0); dots — круглые пятна чужого тона (радиус 3) на части 0."""
    pm = np.zeros((T, T), np.int32)
    lab = np.zeros((T, T, 3)) + np.array(tone)
    for p, (y0, y1, x0, x1) in (parts or {}).items():
        pm[y0:y1, x0:x1] = p
        if part_tones and p in part_tones:
            lab[y0:y1, x0:x1] = part_tones[p]
    yy, xx = np.mgrid[0:T, 0:T]
    for i in range(dots):
        cy, cx = 40 + 30 * i, 40 + 20 * i
        lab[(yy - cy) ** 2 + (xx - cx) ** 2 <= 1] = dot_tone
    return [lab], [np.ones((T, T), bool)], [pm]


def pol(role):
    return MTP.paint_policy(role)


def zones(role, sc, roles=None, card=None, rules=None):
    lab, kn, pm = sc
    return DZ.detail_zones(lab, kn, pm, roles or {}, pol(role), card, rules or R)


import copy  # noqa: E402
RP = copy.deepcopy(R)
RP['pillows']['enabled'] = True                                                  # проверка кода признака под флагом (в правилах по умолчанию выключен)


# 1. в коде нет чисел порогов и ID товаров
src = open(os.path.join(HERE, 'detail_zones.py'), encoding='utf-8').read()
ok(not re.search(r'\b\d{5,}_\d{6,}\b', src) and not re.search(r"(dE_min|min_share|max_share|min_count)\s*=\s*\d", src), 'в коде нет ID товаров и присвоенных порогов')

# 2. диван: пуговицы — круглые пятна чужого тона (≥ min_count) → зона; без пятен → воздержание no_evidence
r1 = zones('диван', scene(dots=5))
ok(r1['report']['buttons']['status'] == 'zone' and r1['zones']['buttons'][0].sum() >= 5 * 9, 'диван: 5 круглых пятен чужого тона → зона buttons')
yy, xx = np.mgrid[0:T, 0:T]
ok(not r1['zones']['buttons'][0][200:, 200:].any(), 'диван: зона только на пятнах, не на всей обивке')
r1n = zones('диван', scene(dots=0))
ok(r1n['report']['buttons']['status'] == 'abstain' and r1n['report']['buttons']['reason'] == 'no_evidence' and r1n['zones']['buttons'][0].sum() == 0, 'диван без пуговиц: воздержание no_evidence, зоны нет')
r1f = zones('диван', scene(dots=2))
ok(r1f['report']['buttons']['status'] == 'abstain', 'диван: 2 пятна < min_count — не пуговицы (случайность)')

sd = scene()
for cy in range(20, 240, 20):
    for cx in range(20, 240, 20):
        sd[0][0][cy, cx] = (15.0, 5.0, 10.0)                                      # рисунок «горох»: 121 тёмная точка
rt = zones('диван', sd)
ok(rt['report']['buttons']['status'] == 'abstain' and rt['report']['buttons']['reason'] in ('texture', 'no_evidence'), 'диван с рисунком-горохом: ямки тонут в узоре → воздержание (не пуговицы)')
# 3. подушка (под флагом): часть другого тона → зона; тот же тон — воздержание; служебная роль (ножки) — не подушка
pt = {1: (100, 180, 60, 190)}
ok(zones('диван', scene(parts=pt, part_tones={1: (80.0, 20.0, 30.0)}))['report']['pillows']['reason'] == 'not_implemented', 'подушки по тону части выключены правилом (ложные зоны на листах) — воздержание not_implemented')
r2 = zones('диван', scene(parts=pt, part_tones={1: (80.0, 20.0, 30.0)}), rules=RP)
ok(r2['report']['pillows']['status'] == 'zone' and r2['zones']['pillows'][0][100:180, 60:190].all() and not r2['zones']['pillows'][0][:50].any(), 'диван: часть другого тона (доля в пределах) → зона pillows')
r2s = zones('диван', scene(parts=pt), rules=RP)
ok(r2s['report']['pillows']['reason'] == 'no_evidence', 'диван: та же ткань и тон — подушку по тону не отличить, воздержание')
r2l = zones('диван', scene(parts=pt, part_tones={1: (80.0, 20.0, 30.0)}), roles={1: 'legs'}, rules=RP)
ok(r2l['report']['pillows']['status'] == 'abstain', 'диван: часть с ролью legs — не подушка')

# 4. комод: фурнитура по роли handles (Z1) и по пятнам; рельеф двери — по роли facade; нет роли — no_facade_part
sc3 = scene(parts={2: (10, 30, 100, 160), 3: (40, 120, 20, 200)})
r3 = zones('комод', sc3, roles={2: 'handles', 3: 'facade'})
ok(r3['report']['facade_hardware']['source'].startswith('Z1') and r3['zones']['facade_hardware'][0][10:30, 100:160].all() and not r3['zones']['facade_hardware'][0][40:120, 20:200].any(), 'комод: части с ролью handles → зона facade_hardware (Z1)')
ok(r3['report']['door_relief']['status'] == 'zone' and r3['zones']['door_relief'][0][40:120, 20:200].all(), 'комод: часть с ролью facade → зона door_relief')
r3n = zones('комод', scene(dots=0), roles={})
ok(r3n['report']['door_relief']['reason'] == 'no_facade_part' and r3n['report']['facade_hardware']['reason'] == 'no_evidence', 'комод без ролей и пятен: воздержание с причинами')
r3b = zones('комод', scene(dots=2, dot_tone=(20.0, 0.0, 0.0)), roles={})
ok(r3b['report']['facade_hardware']['status'] == 'zone' and r3b['report']['facade_hardware']['source'].startswith('Z3'), 'комод: ручки без роли — пятна чужого тона (Z3) → зона')

# 5. стекло по ПАРАМ карточки: значение «Стекло» в «Материал …» → канал → роль части; «Наличие зеркал: нет» — не стекло
ok(DZ.glass_channels({'Материал столешницы': 'Стекло', 'Материал ножек': 'металл'}, R) == ['top'], 'карточка: «Материал столешницы: Стекло» → канал top')
ok(DZ.glass_channels({'Наличие зеркал': 'нет', 'Материал корпуса': 'ЛДСП'}, R) == [], 'карточка: «Наличие зеркал: нет» — не стекло (ложное по слову)')
ok(DZ.glass_channels({'Наличие зеркал': 'да'}, R) == ['mirror'], 'карточка: «Наличие зеркал: да» → зеркало')
ok(DZ.glass_channels({'name': 'Шкаф со стеклянной дверью'}, R) == [], 'слово «стекл» вне пары «Материал …» — не источник')
# заглушка «коробка с проёмом и стеклянной дверцей»: каркас (frame), дверца (facade) со стеклом по карточке, проём — void
box = scene(parts={1: (40, 200, 20, 60), 2: (40, 200, 60, 200)})
rb = zones('витрина', box, roles={1: 'frame', 2: 'facade'}, card={'Материал фасада': 'Стекло закалённое'})
ok(rb['report']['glass']['status'] == 'zone' and rb['report']['glass']['source'].startswith('params') and rb['zones']['glass'][0][40:200, 60:200].all() and not rb['zones']['glass'][0][40:200, 20:60].any(), 'витрина (заглушка): стекло = часть-дверца, каркас не стекло')
ok(rb['report']['void']['reason'] == 'not_implemented', 'витрина: проём void — детектора ещё нет, честное воздержание')
rb2 = zones('витрина', box, roles={1: 'frame', 2: 'facade'}, card={'Материал фасада': 'ЛДСП'})
ok(rb2['report']['glass']['reason'] == 'no_glass_source' and rb2['zones']['glass'][0].sum() == 0, 'витрина: карточка не называет стекло → no_glass_source, зоны нет')
rb3 = zones('витрина', box, roles={1: 'frame'}, card={'Материал фасада': 'Стекло'})
ok(rb3['report']['glass']['reason'] == 'no_glass_part', 'витрина: стекло по карточке, но части с ролью канала нет → no_glass_part')

# 6. тип без исключений — ничего не ищем; записи extra.rules[] (формат rule_record.entry)
r4 = zones('ваза', scene(dots=5))
ok(r4['wanted'] == [] and r4['any'][0].sum() == 0, 'ваза: паспорт исключений не просит — зон нет')
es = DZ.rule_entries('диван', r1)
ok(es[0]['rule_id'] == 'R-DETAIL-EXCLUSIONS-07' and es[0].get('applied') is True and es[0]['type'] == 'диван' and es[0]['digest'], 'запись: R-DETAIL-EXCLUSIONS-07 применено (тип, digest паспорта)')
ok(es[1]['rule_id'] == 'R-OPENINGS-ZONES-07' and 'abstain' in es[1], 'запись: R-OPENINGS-ZONES-07 у дивана — воздержание (паспорт проёмов не просит)')
eb = DZ.rule_entries('витрина', rb)
ok(eb[1].get('applied') is True and 'glass' in eb[1]['note'], 'запись: витрина со стеклом — R-OPENINGS-ZONES-07 применено')
en = DZ.rule_entries('диван', r1n)
ok('abstain' in en[0] and 'buttons:no_evidence' in en[0]['abstain'], 'запись: воздержание несёт причины по видам (buttons:no_evidence)')

# 7. известное не меняется: функция только читает вход
lab0, kn0, pm0 = scene(dots=5)
lab_copy = lab0[0].copy()
DZ.detail_zones(lab0, kn0, pm0, {}, pol('диван'), None, R)
ok(np.array_equal(lab0[0], lab_copy), 'функция не меняет вход (маска, не перекраска)')

def test_detail_zones_positive():
    """диван с пуговицами: зона buttons найдена, запись R-DETAIL-EXCLUSIONS-07 «применено»; витрина со стеклом по паре карточки: зона glass, запись R-OPENINGS-ZONES-07 «применено» (заглушка, не реальный товар)"""
    a = zones('диван', scene(dots=5))
    b = zones('витрина', scene(parts={1: (40, 200, 20, 60), 2: (40, 200, 60, 200)}), roles={1: 'frame', 2: 'facade'}, card={'Материал фасада': 'Стекло закалённое'})
    assert a['report']['buttons']['status'] == 'zone' and DZ.rule_entries('диван', a)[0].get('applied') is True
    assert b['report']['glass']['status'] == 'zone' and DZ.rule_entries('витрина', b)[1].get('applied') is True


def test_detail_zones_negative():
    """диван без пуговиц и витрина без стекла в карточке: зоны нет, воздержание с причиной (no_evidence / no_glass_source), записи — abstain"""
    a = zones('диван', scene(dots=0))
    b = zones('витрина', scene(parts={1: (40, 200, 20, 60), 2: (40, 200, 60, 200)}), roles={1: 'frame', 2: 'facade'}, card={'Материал фасада': 'ЛДСП', 'Наличие зеркал': 'нет'})
    assert a['report']['buttons']['reason'] == 'no_evidence' and a['zones']['buttons'][0].sum() == 0 and 'abstain' in DZ.rule_entries('диван', a)[0]
    assert b['report']['glass']['reason'] == 'no_glass_source' and b['zones']['glass'][0].sum() == 0 and 'abstain' in DZ.rule_entries('витрина', b)[1]


try:
    test_detail_zones_positive()
    test_detail_zones_negative()
    ok(True, 'парные тесты реестра: positive и negative')
except AssertionError:
    ok(False, 'парные тесты реестра: positive и negative')

print('FAIL' if FAIL else 'OK', FAIL)
sys.exit(1 if FAIL else 0)

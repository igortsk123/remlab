#!/usr/bin/env python3
"""T-99/12 шаг 2: выбор образца библиотеки по рисунку фото (part_grain_pick.py): выключатель, паспорт образца выбирает себя, один образец на материал, тон не участвует, штраф за нехватку σ.
Запуск: python tools/scout/salad/trellis/tests_part_grain_pick.py   (numpy, opencv, библиотека data/flat3d/top-library)"""
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', '..'))
import part_grain as PG  # noqa: E402
import part_grain_pick as PK  # noqa: E402

OK = []


def check(cond, msg):
    OK.append(bool(cond))
    print(('ok   ' if cond else 'FAIL ') + msg)


R = PG.load_rules()
PPC = 9.2
src = open(os.path.join(HERE, 'part_grain_pick.py'), encoding='utf-8').read()
check('112923' not in src, 'в коде нет ID товаров')
check(R['pattern_pick']['enabled'] is False, 'выключатель rules.pattern_pick.enabled = false по умолчанию')
lib = PK.library_passports(PPC, ['straight'], 40.0)
check(len(lib) >= 10 and all(0 <= v['clarity'] <= 1 for v in lib.values()), 'паспорта образцов считаются (%d шт.)' % len(lib))
check(len({round(v['stroke_cm'], 1) for v in lib.values()}) > 3 and max(v['coarse'] for v in lib.values()) - min(v['coarse'] for v in lib.values()) > 0.1, 'образцы различаются по рисунку (штрих, крупное)')


def part(i, tone, sigma=3.0, card=None, role='top'):
    return {'id': i, 'name': 'g%d' % i, 'tone_lab': tone, 'photo_sigma': sigma, 'card': card, 'role': role}


name, sp = sorted(lib.items())[3]
pas = {0: dict({k: sp[k] for k in ('clarity', 'stroke_cm', 'stroke_across_cm', 'coarse', 'angle')}, n_px=5000)}
for tone in ([20.0, 5.0, 5.0], [80.0, 0.0, 0.0]):
    pk = PK.pick([part(0, tone, sigma=1.0)], pas, R, PPC)
    check(pk[0]['bin'] == name and pk[0]['dist'] < 0.01, 'паспорт фото = паспорт образца %s → выбран он, тон %s не влияет' % (name, tone))
# один образец на материал: две части с общим материалом карточки; у второй паспорта нет → берёт образец первой
card = {'Материал столешницы': 'массив ясеня', 'Материал ножек': 'массив ясеня'}
ps = [part(0, [60.0, 8.0, 20.0], card=card, role='top'), part(1, [40.0, 8.0, 20.0], card=card, role='legs')]
pk = PK.pick(ps, {0: pas[0], 1: None}, R, PPC)
check(0 in pk and 1 in pk and pk[0]['bin'] == pk[1]['bin'] and pk[1]['source'] == 'material' and pk[1]['from'] == 0, 'одна карточка-материал → один образец; у части без паспорта — по паспорту видимой')
# разные материалы / нет материала в карточке → независимо
ps = [part(0, [60.0, 8.0, 20.0]), part(1, [40.0, 8.0, 20.0])]
pk = PK.pick(ps, {0: pas[0], 1: None}, R, PPC)
check(0 in pk and 1 not in pk, 'материал не назван и паспорта нет → часть не в ответе (путь по тону как раньше)')
# штраф: фото-σ слишком велика для образца при amp_max — образец с малым σ не выигрывает у равного по рисунку
big = PK.pick([part(0, [60.0, 8.0, 20.0], sigma=50.0)], pas, R, PPC)
small = PK.pick([part(0, [60.0, 8.0, 20.0], sigma=1.0)], pas, R, PPC)
check(big[0]['dist'] > small[0]['dist'] + 0.5, 'штраф за нехватку σ образца: фото σ 50 при amp_max %.2f → расстояние %.2f > %.2f' % (R['amp_max'], big[0]['dist'], small[0]['dist']))
# plan_grain: ключ 'pick' ведёт образец; без ключа путь по тону
import numpy as np  # noqa: E402
parts = [dict(part(0, [67.4, 9.8, 15.9], sigma=3.0), tone_sigma=0.0, n_texels=5000, is_wood=True, classes=['straight'])]
base = PG.plan_grain(copy.deepcopy(parts), R)
alt = copy.deepcopy(parts)
alt[0]['pick'] = {'bin': name, 'dist': 0.0, 'source': 'own', 'from': 0, 'passport': {'clarity': 0, 'stroke_cm': 0, 'coarse': 0}, 'sample': {'clarity': 0, 'stroke_cm': 0, 'coarse': 0}}
pl = PG.plan_grain(alt, R)
check(pl[0]['bin']['bin'] == name and pl[0].get('pick') and pl[0]['apply'] is not False, 'plan_grain: ключ pick → образец %s' % name)
check('pick' not in base[0] and base[0]['bin']['bin'] != name or base[0]['bin']['bin'] == name, 'plan_grain без pick: путь по тону (ключа pick в записи нет)')
check(json.dumps({k: v for k, v in base[0].items() if k not in ('pat',)}, default=str) == json.dumps({k: v for k, v in PG.plan_grain(copy.deepcopy(parts), R)[0].items() if k not in ('pat',)}, default=str), 'без pick результат повторяем')
# путь wood_always (боевой): тот же ключ pick ведёт образец
Rw = copy.deepcopy(R)
Rw['wood_always']['enabled'] = True
pw = [dict(part(0, [67.4, 9.8, 15.9], sigma=3.0, card={'Материал столешницы': 'массив ясеня'}), tone_sigma=0.0, n_texels=5000, is_wood=True)]
pw[0]['pick'] = {'bin': name, 'dist': 0.0, 'source': 'own', 'from': 0, 'passport': {'clarity': 0, 'stroke_cm': 0, 'coarse': 0}, 'sample': {'clarity': 0, 'stroke_cm': 0, 'coarse': 0}}
plw = PG.plan_grain(copy.deepcopy(pw), Rw)
check(plw[0].get('apply') and plw[0]['bin']['bin'] == name and plw[0].get('pick'), 'plan_grain (wood_always): ключ pick → образец %s' % name)
pw0 = [dict(pw[0])]
pw0[0].pop('pick')
plw0 = PG.plan_grain(copy.deepcopy(pw0), Rw)
check('pick' not in plw0[0], 'plan_grain (wood_always) без pick: путь по тону, ключа pick нет')
print('ИТОГО: %d провалов' % OK.count(False))
sys.exit(1 if False in OK else 0)

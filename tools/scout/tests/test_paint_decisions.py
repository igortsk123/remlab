#!/usr/bin/env python3
"""Четыре состояния решения (T-20261123-19/1): pass / fail / uncertain / not_applicable по реестру rules/paint-decisions.json. Без numpy; ID товаров нет.
Запуск: python tools/scout/tests/test_paint_decisions.py"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import paint_check as PC  # noqa: E402
import paint_decisions as PD  # noqa: E402

REG = PD.load()
FAIL = 0


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def stage(name, **metrics):
    return {'stage': name, 'status': 'ok', 'reason': '', 'metrics': {k: v if isinstance(v, dict) else {'value': v, 'ok': True} for k, v in metrics.items()}}


S06 = stage('06-visible', silhouette_iou=0.95, edge_bg_share=0.0, lab_dE=0.3, known_visible_share=0.8, known_share=0.2, edge_corr=0.95)
S07 = stage('07-fill', dE00_front_back=2.0, dL_front_back=1.0, far_excess_pct=-5, filled_faces_step_pct=1.0, quilt_lattice_max=0.1, pool_rejected_pct=0, front_on_back_corr=0.1, known_changed_share_pct=0, empty_pct=0, cpu_s={'value': 300, 'ok': False}, time_s={'value': 100, 'ok': True})
COV = {'stage': 'coverage', 'status': 'ok', 'reason': ''}
PAL = {'stage': 'palette', 'status': 'ok', 'reason': ''}
SURF = {'stage': 'surface', 'status': 'ok', 'reason': '', 'metrics': {
    'top_vs_photo_dE00': {'value': 3.0, 'ok': True}, 'empty_flat_pct': {'value': 0.0, 'ok': True}, 'group_bleed_pct': {'value': 0.0, 'ok': True}, 'lighter_than_photo_pct': {'value': 0.0, 'ok': True}}}
EX = {'coverage': COV, 'palette': PAL, 'surface': SURF}


def run(stages, extra=None):
    return PD.decide_product(stages, EX if extra is None else extra, REG)


# 1. всё посчитано и в пороге → pass (cpu_s не ок — информационная, в итог не входит; не откалиброванные дают uncertain в тени)
d = run([S06, S07])
ok(d['items']['07.cpu_s']['state'] in ('uncertain', 'fail', 'pass') and d['items']['07.cpu_s']['severity'] == 'info', 'cpu_s — info')
ok('07.cpu_s' not in d['uncertain'] and '07.cpu_s' not in d['fail'], 'info в итог не входит')
ok(d['items']['06.edge_corr']['state'] == 'uncertain' and d['items']['06.edge_corr']['raw'] == 'pass', 'порог не откалиброван → uncertain, сырой итог сохранён')
ok(d['items']['06.known_visible_share']['state'] == 'pass' and d['items']['06.known_share']['severity'] == 'info', 'T-215: известность гейтится по known_visible_share; known_share справочная')

# 2. пустое front_on_back_corr (раньше «прошло») → uncertain
s7 = stage('07-fill', **{k: v for k, v in S07['metrics'].items()})
s7['metrics']['front_on_back_corr'] = {'value': None, 'ok': True}
d = run([S06, s7])
ok(d['items']['07.front_on_back_corr']['state'] == 'uncertain' and 'пуст' in d['items']['07.front_on_back_corr']['why'], 'front_on_back_corr = null → uncertain, не pass')

# 3. мерки нет в check.json → uncertain; с `na_when_absent` → not_applicable с причиной
s7b = stage('07-fill', **{k: v for k, v in S07['metrics'].items() if k not in ('empty_pct', 'quilt_lattice_max')})
d = run([S06, s7b])
ok(d['items']['07.empty_pct']['state'] == 'uncertain', 'мерки нет → uncertain')
ok(d['items']['07.quilt_lattice_max']['state'] == 'not_applicable' and 'квилт' in d['items']['07.quilt_lattice_max']['why'], 'нет квилта → not_applicable с причиной')

# 4. нет check.json этапа → uncertain по всем его решениям; итог state = uncertain
miss = {'stage': '07-fill', 'status': 'missing', 'reason': 'нет check.json', 'metrics': {}}
d = run([S06, miss])
ok(all(d['items'][i]['state'] == 'uncertain' for i in d['items'] if i.startswith('07.')), 'нет check.json этапа → всё uncertain')
ok(d['state'] == 'uncertain', 'итог uncertain, не pass')
d = run([S06])
ok(d['items']['07.far_excess_pct']['state'] == 'uncertain', 'этапа 07 в списке нет → uncertain')

# 5. жёсткая мерка не прошла → fail; мягкая не прошла → пометка, не fail
s7c = stage('07-fill', **{k: v for k, v in S07['metrics'].items()})
s7c['metrics']['far_excess_pct'] = {'value': 30, 'ok': False}
d = run([S06, s7c])
ok(d['state'] == 'fail' and '07.far_excess_pct' in d['fail'], 'жёсткая вне порога → fail')
s7d = stage('07-fill', **{k: v for k, v in S07['metrics'].items()})
s7d['metrics']['dL_front_back'] = {'value': 9, 'ok': False}
d = run([S06, s7d])
ok(d['state'] != 'fail' and '07.dL_front_back' in d['notes'], 'мягкая вне порога → пометка, не fail')

# 6. сторож 09: missing → uncertain; refused → fail; ok → pass
d = run([S06, S07], {'coverage': {'stage': 'coverage', 'status': 'missing', 'reason': 'сторож не запускался'}, 'palette': PAL, 'surface': SURF})
ok(d['items']['09.coverage']['state'] == 'uncertain' and d['state'] == 'uncertain', 'охват не запускался → uncertain')
d = run([S06, S07], {'coverage': {'stage': 'coverage', 'status': 'refused', 'reason': 'reject'}, 'palette': PAL, 'surface': SURF})
ok(d['items']['09.coverage']['state'] == 'fail' and d['state'] == 'fail', 'охват reject → fail')

# 7. тень: мерки поверхности не в `state`, а в `state_with_shadow`
sh = dict(SURF, metrics=dict(SURF['metrics'], top_vs_photo_dE00={'value': 40.0, 'ok': False}, empty_flat_pct={'value': 3.0, 'ok': False}))
d = run([S06, S07], {'coverage': COV, 'palette': PAL, 'surface': sh})
ok(d['state'] != 'fail', 'теневые решения старый итог не меняют')
ok(d['items']['09.top_vs_photo']['state'] == 'fail' and d['state_with_shadow'] == 'fail', 'в тени верх↔фото/пустая плоскость fail → state_with_shadow = fail')
na = dict(SURF, metrics=dict(SURF['metrics'], top_vs_photo_dE00={'value': None, 'ok': None, 'na': 'верх не виден на фото'}))
d = run([S06, S07], {'coverage': COV, 'palette': PAL, 'surface': na})
ok(d['items']['09.top_vs_photo']['state'] == 'not_applicable' and 'не виден' in d['items']['09.top_vs_photo']['why'], 'na сторожа → not_applicable с его причиной')
er = dict(SURF, metrics=dict(SURF['metrics'], empty_flat_pct={'value': None, 'ok': None, 'error': 'ValueError: x'}))
d = run([S06, S07], {'coverage': COV, 'palette': PAL, 'surface': er})
ok(d['items']['09.empty_flat']['state'] == 'uncertain', 'мерка упала → uncertain')

# 8. реестр: поля, ID, пороги не копируются, soft совпадает с paint-check.json, ID товаров нет
ids = [x['id'] for x in REG['decisions']]
ok(len(ids) == len(set(ids)), 'id решений уникальны')
txt = open(PD.RULES, encoding='utf-8').read()
ok(not re.search(r'\b\d{5,6}_\d{6,}\b', txt), 'в реестре нет ID товаров')
ok(all('threshold_ref' in x and 'owner' in x and 'requires' in x for x in REG['decisions']), 'у каждой строки владелец, ссылка на порог и предпосылки')
pc = PC.load_rules()
for stg in ('06-visible', '07-fill'):
    soft_pc = set(pc['soft'].get(stg, []))
    soft_reg = {x['metric'] for x in REG['decisions'] if x['stage'] == stg and x['severity'] in ('soft', 'info')}
    ok(soft_pc <= soft_reg, f'{stg}: мягкие мерки paint-check.json есть в реестре как soft ({sorted(soft_pc - soft_reg)})')
ok(not re.search(r'"threshold"\s*:', txt) and '0.30' not in txt and '0,30' not in txt, 'порогов-чисел в реестре нет (только ссылки)')
print('FAIL' if FAIL else 'ВСЁ ЗЕЛЁНОЕ', FAIL)
sys.exit(1 if FAIL else 0)

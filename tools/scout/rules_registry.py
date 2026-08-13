#!/usr/bin/env python3
"""Сборка РЕЕСТРА ПРАВИЛ движка из кода (план rules-consistency-audit, владелец 13.08).

Зачем: правила писались независимо — в валидаторе, шаблонах, зонах, композиторе — и нигде
не записано, какое главнее. За два дня это дало семь противоречий (резерв столовой отнимал
стену у медиа; свой порог столика против вилки движка; эвристика против канона визави…).
Реестр делает набор правил ВИДИМЫМ и проверяемым.

Собирает:
  * hard-правила       — коды из `_v("CODE"...)` в planner/validate.py
  * резервы места      — вычитания из свободной площади в zones.py/template.py
  * фильтры кандидатов — `_axis_filter` / `_view_filter` / `_jamb_candidates` и т.п.
  * каскады            — перебор схем и составов в template.py
  * слоты и геометрия  — из rules/templates.json и rules/zones.json

  ~/venvs/scout/bin/python rules_registry.py            # отчёт
  ~/venvs/scout/bin/python rules_registry.py --write    # записать rules/registry.json
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')
PLANNER = os.path.join(SOLVER, 'planner')
RULES = os.path.join(SOLVER, 'rules')

# СТАДИИ дизайнерского порядка (ADR-0091) — единственная шкала приоритета
STAGES = ['архитектура', 'фокус-стена', 'диван', 'циркуляция', 'носитель ТВ',
          'ковёр и столик', 'доп. посадка', 'хранение', 'свет и приставные', 'декор']

# К какой стадии относится hard-правило (по ролям в коде правила).
_STAGE_BY_KEY = [
    (('DOOR', 'RADIATOR', 'WINDOW', 'OUT_OF_ROOM', 'NOT_AT_WALL', 'ZONE_BUFFER'), 'архитектура'),
    (('PASSAGE', 'UNREACHABLE', 'ACCESS', 'PATH', 'SLIVER', 'DEAD_ZONE'), 'циркуляция'),
    (('TV', 'SIGHTLINE', 'FACING', 'AIM'), 'носитель ТВ'),
    (('FIREPLACE',), 'фокус-стена'),
    (('RUG', 'TABLE', 'COFFEE'), 'ковёр и столик'),
    (('ARMCHAIR', 'POUF', 'SEAT', 'SOFA', 'PAIR'), 'доп. посадка'),
    (('STORAGE', 'TALL', 'CHAIR_WITHOUT', 'DINING', 'CHAIR_ORPHAN'), 'хранение'),
    (('LAMP', 'SERVICE'), 'свет и приставные'),
    (('PLANT', 'FLOOR_OVERFILL'), 'декор'),
    (('COLLISION',), 'архитектура'),          # физика: пересечение — базовое правило
]


def _stage_for(code: str) -> str:
    for keys, stage in _STAGE_BY_KEY:
        if any(k in code for k in keys):
            return stage
    return 'не определена'


def hard_rules() -> list[dict]:
    src = open(os.path.join(PLANNER, 'validate.py'), encoding='utf-8').read()
    out = {}
    for m in re.finditer(r'_v\(\s*"([A-Z_]+)"\s*,\s*f?"([^"]*)"', src):
        code, msg = m.group(1), m.group(2)
        out.setdefault(code, {
            'id': code, 'вид': 'hard', 'стадия': _stage_for(code),
            'сообщение': msg[:80], 'где': 'planner/validate.py',
        })
    return list(out.values())


def space_reservations() -> list[dict]:
    """Вычитания из свободной площади: кто у кого отнимает место."""
    src = open(os.path.join(PLANNER, 'zones.py'), encoding='utf-8').read()
    out = []
    for m in re.finditer(r'difference\((_[a-z_]+)\(', src):
        out.append({'id': m.group(1), 'вид': 'резерв места',
                    'стадия': 'фокус-стена' if 'tv' in m.group(1) else 'хранение',
                    'где': 'planner/zones.py'})
    return out


def candidate_filters() -> list[dict]:
    src = open(os.path.join(PLANNER, 'template.py'), encoding='utf-8').read()
    out = []
    for name in re.findall(r'def (_[a-z_]*(?:filter|candidates))\(', src):
        out.append({'id': name, 'вид': 'фильтр кандидатов', 'где': 'planner/template.py',
                    'стадия': ('носитель ТВ' if ('axis' in name or 'jamb' in name)
                               else 'фокус-стена' if 'view' in name
                               else 'диван')})
    return out


def slots_and_geometry() -> list[dict]:
    out = []
    z = json.load(open(os.path.join(RULES, 'zones.json'), encoding='utf-8'))
    for role, cfg in (z.get('template_slot_envelopes', {}).get('slots') or {}).items():
        out.append({'id': f'слот:{role}', 'вид': 'слот размера', 'стадия': 'подбор товара',
                    'источник': (cfg.get('why') or '')[:90], 'где': 'rules/zones.json'})
    t = json.load(open(os.path.join(RULES, 'templates.json'), encoding='utf-8'))
    for k, cfg in (t.get('geometry') or {}).items():
        if k.startswith('_'):
            continue
        out.append({'id': f'геометрия:{k}', 'вид': 'число схемы', 'стадия': 'ковёр и столик',
                    'значение': cfg.get('v'), 'источник': (cfg.get('why') or '')[:90],
                    'где': 'rules/templates.json'})
    return out


def cascades() -> list[dict]:
    src = open(os.path.join(PLANNER, 'template.py'), encoding='utf-8').read()
    n = len(re.findall(r'tries\.append', src))
    return [{'id': 'каскад схем посадки', 'вид': 'каскад', 'стадия': 'диван',
             'ступеней': n, 'где': 'planner/template.py'}]


def build() -> dict:
    reg = {'_purpose': ('РЕЕСТР ПРАВИЛ движка (план rules-consistency-audit). Собирается из кода '
                        'скриптом tools/scout/rules_registry.py — правило есть в коде, но нет '
                        'здесь = дыра. Стадии — из дизайнерского порядка ADR-0091.'),
           'стадии_по_приоритету': STAGES,
           'правила': (hard_rules() + space_reservations() + candidate_filters()
                       + slots_and_geometry() + cascades())}
    return reg


def main() -> int:
    reg = build()
    by_kind, by_stage = {}, {}
    for r in reg['правила']:
        by_kind[r['вид']] = by_kind.get(r['вид'], 0) + 1
        by_stage[r.get('стадия', '?')] = by_stage.get(r.get('стадия', '?'), 0) + 1
    print(f"правил всего: {len(reg['правила'])}")
    print('по виду:  ', by_kind)
    print('по стадии:', by_stage)
    unknown = [r['id'] for r in reg['правила'] if r.get('стадия') == 'не определена']
    if unknown:
        print(f'\nСТАДИЯ НЕ ОПРЕДЕЛЕНА ({len(unknown)}): {unknown}')
    if '--write' in sys.argv:
        p = os.path.join(RULES, 'registry.json')
        json.dump(reg, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'\nзаписано: {p}')
    return 0


if __name__ == '__main__':
    sys.exit(main())

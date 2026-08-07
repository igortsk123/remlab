#!/usr/bin/env python3
"""Экспорт ВСЕГО действующего свода правил в один .xlsx — для ревизии владельцем.

Листы: оглавление · канон occupancy.json (один файл на оба движка) · zones.json (группы/зоны/
inventory-prior/иерархия) · weights.json (веса скоринга) · composition.json (доли пола по
метражу) · size-bands.json (размерные гейты) · proportions.json · коды валидатора (из
validate.py, с severity и местом).

Запуск: ~/venvs/scout/bin/python rules_export.py [выходной .xlsx]
"""
import datetime
import json
import os
import re
import sys

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
SOLVER = os.path.join(HERE, '..', '..', 'services', 'planner-solver')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    f'~/rules-svod-{datetime.date.today().isoformat()}.xlsx')

FILES = [
    ('occupancy.json', os.path.join(SOLVER, 'rules', 'occupancy.json'),
     'КАНОН расстановки: шкалы расстояний по метражу, доли, ярусы, именованные правила '
     '(один файл на оба движка; tools/scout/occupancy.json — синхронизированная копия)'),
    ('zones.json', os.path.join(SOLVER, 'rules', 'zones.json'),
     'Зоны-first (ADR-0074): 10 посадочных групп с футпринтами, внутренняя схема группы, '
     'функциональные зоны, inventory-prior по usable-площади, лексикографическая иерархия'),
    ('weights.json', os.path.join(SOLVER, 'rules', 'weights.json'),
     'Веса мягких термов скоринга солвера'),
    ('composition.json', os.path.join(HERE, 'composition.json'),
     'Состав сетов: доли площади пола по ролям в каждом метраже'),
    ('size-bands.json', os.path.join(HERE, 'size-bands.json'),
     'Размерный гейт: допустимая ширина роли в метраже'),
    ('proportions.json', os.path.join(HERE, 'proportions.json'),
     'Пропорции предметов друг к другу (жёсткий фильтр до скоринга)'),
]


def flatten(obj, path=''):
    rows = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            rows += flatten(v, f'{path}.{k}' if path else str(k))
    elif isinstance(obj, list) and any(isinstance(x, (dict, list)) for x in obj):
        for i, v in enumerate(obj):
            rows += flatten(v, f'{path}[{i}]')
    else:
        val = json.dumps(obj, ensure_ascii=False) if isinstance(obj, list) else obj
        rows.append((path, val))
    return rows


def add_sheet(wb, title, rows, headers):
    ws = wb.create_sheet(title[:31])
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in rows:
        ws.append(list(r))
    widths = {}
    for row in ws.iter_rows():
        for c in row:
            widths[c.column] = min(90, max(widths.get(c.column, 10),
                                           len(str(c.value or '')) + 2))
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w
    ws.freeze_panes = 'A2'
    return ws


def validator_codes():
    src = open(os.path.join(SOLVER, 'planner', 'validate.py')).read()
    rows = []
    func = ''
    fdoc = ''
    for i, line in enumerate(src.splitlines(), 1):
        m = re.match(r'def (check_\w+)', line)
        if m:
            func = m.group(1)
            rest = src.split(line, 1)[1]
            d = re.match(r'[^"]*"""(.*?)"""', rest, re.S)
            fdoc = ' '.join(d.group(1).split())[:200] if d else ''
        for code in re.findall(r'"([A-Z][A-Z_]{3,})"', line):
            sev = ('SOFT' if 'Severity.SOFT' in line or 'soft' in line.lower() else
                   'HARD' if 'Severity.HARD' in line else '')
            rows.append((code, sev, func, i, fdoc))
    seen = {}
    for code, sev, fn, ln, doc in rows:
        if code not in seen:
            seen[code] = [code, sev, fn, f'validate.py:{ln}', doc]
        elif sev and not seen[code][1]:
            seen[code][1] = sev
    return sorted(seen.values())


def main():
    wb = Workbook()
    ws = wb.active
    ws.title = 'Оглавление'
    ws.append(['Свод правил remlab — полный экспорт', ''])
    ws['A1'].font = Font(bold=True, size=14)
    ws.append([f'Дата: {datetime.date.today().isoformat()}', ''])
    ws.append(['Лист', 'Что это'])
    for name, _, note in FILES:
        ws.append([name, note])
    ws.append(['коды валидатора', 'все именованные проверки размещения: код, жёсткость, '
               'функция и строка в validate.py'])
    for col, w in (('A', 28), ('B', 110)):
        ws.column_dimensions[col].width = w
    for name, path, _ in FILES:
        data = json.load(open(path))
        add_sheet(wb, name, flatten(data), ['Правило (путь в файле)', 'Значение'])
    add_sheet(wb, 'коды валидатора', validator_codes(),
              ['Код', 'Жёсткость', 'Проверка', 'Место', 'Описание проверки'])
    wb.save(OUT)
    print(f'{OUT}: {len(wb.sheetnames)} листов')


if __name__ == '__main__':
    main()

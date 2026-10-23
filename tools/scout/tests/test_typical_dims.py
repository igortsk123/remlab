"""Список напольных ролей солвера — один и в git (T-20261023-10). Без сети, базы и солвера.

`solver_run.py` ставит на пол только роли из `typical-dims.json`. Файл лежал вне git, а запасной список в коде отстал (без
ковра, приставного, банкетки): в свежей копии ковёр молча выпадал из всех расстановок, и демо снимало все стили. Проверяем:
  1) файл есть в репозитории и читается: роль → [ширина, глубина] > 0;
  2) в нём все роли, которые демо ставит на пол (`flat215_demo.PLACEABLE`) и дозаполняет (`demo_fill.FILL_ROLES`, ядро);
  3) запасного списка в `solver_run.py` нет — нет файла → громкий отказ, а не тихая расстановка без ковра.
    python3 tools/scout/tests/test_typical_dims.py"""
import ast
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
sys.path.insert(0, SCOUT)
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


path = os.path.join(SCOUT, 'typical-dims.json')
check('typical-dims.json в репозитории', os.path.exists(path))
td = json.load(open(path, encoding='utf-8')) if os.path.exists(path) else {}
check('каждая роль — [ширина, глубина] > 0',
      bool(td) and all(isinstance(v, list) and len(v) == 2 and all(isinstance(x, (int, float)) and x > 0 for x in v)
                       for v in td.values()))

import demo_fill as DF  # noqa: E402

src = open(os.path.join(SCOUT, 'flat215_demo.py'), encoding='utf-8').read()
placeable = ast.literal_eval(re.search(r'^PLACEABLE = (\{[^}]*\})', src, re.M | re.S).group(1))
miss = sorted((placeable | DF.FILL_ROLES) - set(td))
check(f'все напольные роли демо и ядро (ковёр, торшер…) есть в списке солвера{": нет " + ", ".join(miss) if miss else ""}',
      not miss and 'ковёр' in td)

solver = open(os.path.join(SCOUT, 'solver_run.py'), encoding='utf-8').read()
line = next((ln for ln in solver.splitlines() if ln.startswith('FLOOR_TYPICAL=')), '')
check('solver_run: список ролей только из файла, запасного в коде нет; без файла — отказ',
      'typical-dims.json' in solver and line and ' else ' not in line and "('диван',(190,95))" not in solver
      and re.search(r"if not os\.path\.exists\(_TD\):\s*\n\s*sys\.exit\(", solver) is not None)

print('test_typical_dims:', 'FAIL' if fails else 'OK')
sys.exit(1 if fails else 0)

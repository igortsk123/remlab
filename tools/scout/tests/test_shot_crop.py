"""Окно превью кадра замораживается в записи реестра (demo-22 п.2): `_cams_clean` оставляет позы камер и `crop` по
пропорциям, мусор отбрасывает. Функции берём разбором исходника — импорт `draft_service` тянет рендер и сеть.
    ~/venvs/scout/bin/python tools/scout/tests/test_shot_crop.py"""
import ast
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'draft_service.py')
fails = 0


def check(name, cond):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name)
    fails += 0 if cond else 1


ns = {'re': re}
for n in ast.parse(open(SRC, encoding='utf-8').read()).body:
    if (isinstance(n, ast.FunctionDef) and n.name in ('_crop_clean', '_cams_clean')) or \
            (isinstance(n, ast.Assign) and any(getattr(t, 'id', '') == '_CROP_KEY' for t in n.targets)):
        exec(compile(ast.Module([n], []), SRC, 'exec'), ns)
clean = ns['_cams_clean']

cams = clean([{'name': 'C1', 'x': 120, 'y': 40, 'rot': 210, 'fov': 72, 'pose': 2,
               'crop': {'0.531': {'x': 0.2, 'y': 0, 'w': 0.386, 'h': 1, 'keep': ['sofa-1', 'tv-2']},
                        '1.500': {'x': 0, 'y': 0.04, 'w': 1, 'h': 0.917},
                        'wide': {'x': 0, 'y': 0, 'w': 1, 'h': 1},
                        '0.673': {'x': 'левее'}}},
              {'name': 'C2', 'x': 300, 'y': 280, 'rot': 30, 'fov': 78, 'pose': 2}, 'мусор'])
check('поза камеры — как раньше', {k: cams[0][k] for k in ('name', 'x', 'y', 'rot', 'fov', 'pose')} ==
      {'name': 'C1', 'x': 120, 'y': 40, 'rot': 210, 'fov': 72, 'pose': 2})
check('окно превью сохранено по пропорциям', sorted(cams[0]['crop']) == ['0.531', '1.500'])
check('доли и keep — как прислала страница', cams[0]['crop']['0.531'] == {'x': 0.2, 'y': 0.0, 'w': 0.386, 'h': 1.0, 'keep': ['sofa-1', 'tv-2']})
check('камера без окна — без поля crop', 'crop' not in cams[1] and len(cams) == 2)
check('доли зажаты в 0…1', clean([{'name': 'C1', 'crop': {'0.673': {'x': -1, 'y': 0, 'w': 2, 'h': 1}}}])[0]['crop']['0.673'] ==
      {'x': 0.0, 'y': 0.0, 'w': 1.0, 'h': 1.0})
check('нет камер / не список — пусто', clean(None) == [] and clean('C1') == [])
check('не больше 4 камер', len(clean([{'name': f'C{i}'} for i in range(9)])) == 4)
sys.exit(1 if fails else 0)

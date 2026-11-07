#!/usr/bin/env python3
"""Пометка обломков `cut_alien_debris` (T-20261106-85/3) — без GPU, на маленьких мешах с текстурой.

ЗАЧЕМ. С 04.09 функция грузила GLB как Scene и звала `to_mesh`, которого нет в trimesh 4.4.7 образа: каждый паспорт
v2 получал `gpu.alien.error = "AttributeError: 'Scene' object has no attribute 'faces'"`, то есть пометка не работала ни
разу. Стенд закрепляет:
  1) GLB (грузится как Scene) судится без ошибки, текстура доходит до цветов, тёмный кусок у пола — подозрение;
  2) обычный Trimesh (OBJ с текстурой) судится так же;
  3) белый товар без чужого цвета — 0 подозрений; кусок чужого цвета наверху — не подозрение;
  4) `ALIEN_CUT=0` (как на боевых) файл не меняет, только пишет `.alien_suspect`; `ALIEN_CUT=1` режет.
Функция достаётся из `pipeline.py` разбором (импорт модуля тянет torch и Hunyuan).

Запуск: ~/venvs/scout/bin/python tests_alien_debris.py   (тот же файл — и под trimesh 4.4.7, как в образе)
"""
import ast
import hashlib
import os
import sys
import tempfile

import numpy as np
import trimesh
from PIL import Image
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('tests_alien_debris')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)

HERE = os.path.dirname(os.path.abspath(__file__))
LIGHT, DARK = (225, 220, 205), (20, 18, 16)
ERR = []


def check(ok: bool, what: str) -> None:
    print(('  ok  ' if ok else '  FAIL') + ' ' + what, flush=True)
    if not ok:
        ERR.append(what)


def load_fn(name: str):
    path = os.path.join(HERE, 'pipeline.py')
    tree = ast.parse(open(path, encoding='utf-8').read())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {'os': os}
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), ns)
    return ns[name]


def part(extents, center, uv, subdiv):
    m = trimesh.creation.box(extents=extents)
    for _ in range(subdiv):
        m = m.subdivide()
    m.apply_translation(center)
    return m, np.tile(uv, (len(m.vertices), 1))


def build(pieces) -> trimesh.Trimesh:
    """Корпус 1×1×0.5 (3072 грани) + куски; цвет каждого — пиксель текстуры 2×1 по UV."""
    parts = [part((1.0, 1.0, 0.5), (0, 0.5, 0), (0.25, 0.5), 4)] + [part(*p) for p in pieces]
    V, F, UV, off = [], [], [], 0
    for m, uv in parts:
        V.append(m.vertices), F.append(m.faces + off), UV.append(uv)
        off += len(m.vertices)
    img = Image.new('RGB', (2, 1))
    img.putpixel((0, 0), LIGHT), img.putpixel((1, 0), DARK)
    mesh = trimesh.Trimesh(np.vstack(V), np.vstack(F), process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=np.vstack(UV), image=img)
    return mesh


DEBRIS_LOW = ((0.15, 0.1, 0.15), (0.7, 0.05, 0.0), (0.75, 0.5), 1)    # тёмный ком у пола, 48 граней
DARK_TOP = ((0.15, 0.1, 0.15), (0.7, 0.95, 0.0), (0.75, 0.5), 1)      # тёмная деталь наверху
LIGHT_LOW = ((0.15, 0.1, 0.15), (0.7, 0.05, 0.0), (0.25, 0.5), 1)     # кусок в цвет корпуса у пола


def sha(path: str) -> str:
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def main() -> None:
    fn = load_fn('cut_alien_debris')
    print(f'trimesh {trimesh.__version__}', flush=True)
    with tempfile.TemporaryDirectory(dir=os.environ.get('ALIEN_TEST_TMP')) as tmp:
        os.environ['ALIEN_CUT'] = '0'

        # 1) GLB → Scene: та самая загрузка, на которой функция падала
        glb = os.path.join(tmp, 'debris.glb')
        build([DEBRIS_LOW]).export(glb)
        check(isinstance(trimesh.load(glb), trimesh.Scene), 'GLB без force грузится как Scene (случай боевых паспортов)')
        before = sha(glb)
        r = fn(glb)
        check(r.get('error') is None and r.get('skipped') is None, f'GLB судится без ошибки: {r}')
        check(r.get('suspect') == 48, f'тёмный ком у пола помечен целиком (48 граней): {r.get("suspect")}')
        check(sha(glb) == before, 'ALIEN_CUT=0: файл меша не изменён')
        mark = glb + '.alien_suspect'
        check(os.path.exists(mark) and open(mark).read() == '48', 'ALIEN_CUT=0: пометка .alien_suspect = 48')

        # 2) обычный Trimesh: OBJ с текстурой грузится сразу мешем
        obj_dir = os.path.join(tmp, 'obj')
        os.makedirs(obj_dir)
        obj = os.path.join(obj_dir, 'debris.obj')
        build([DEBRIS_LOW]).export(obj)
        loaded = trimesh.load(obj)
        check(isinstance(loaded, trimesh.Trimesh) and getattr(loaded.visual, 'kind', None) == 'texture',
              f'OBJ грузится Trimesh с текстурой: {type(loaded).__name__}/{getattr(loaded.visual, "kind", None)}')
        r = fn(obj)
        check(r == {'suspect': 48, 'skipped': None, 'error': None}, f'Trimesh судится так же: {r}')

        # 3) без чужого цвета у пола — молчит; чужой цвет наверху — не подозрение
        for name, pieces in (('light', [LIGHT_LOW]), ('top', [DARK_TOP])):
            p = os.path.join(tmp, f'{name}.glb')
            build(pieces).export(p)
            r = fn(p)
            check(r == {'suspect': 0, 'skipped': None, 'error': None}, f'{name}: подозрений 0 — {r}')
            check(not os.path.exists(p + '.alien_suspect'), f'{name}: пометки нет')

        # одно тело — честный пропуск, не ошибка
        p = os.path.join(tmp, 'one.glb')
        build([]).export(p)
        r = fn(p)
        check(r.get('skipped') == 'одно тело' and r.get('error') is None, f'одно тело: {r}')

        # 4) ALIEN_CUT=1 — срез на копии: граней меньше ровно на ком
        p = os.path.join(tmp, 'cut.glb')
        build([DEBRIS_LOW]).export(p)
        n0 = len(trimesh.load(p, force='mesh').faces)
        os.environ['ALIEN_CUT'] = '1'
        r = fn(p)
        os.environ['ALIEN_CUT'] = '0'
        n1 = len(trimesh.load(p, force='mesh').faces)
        check(r.get('suspect') == 48 and n0 - n1 == 48, f'ALIEN_CUT=1: срезано {n0 - n1} граней из {n0}')

    print(f'\n{"ВСЁ ЗЕЛЁНОЕ" if not ERR else f"ОШИБОК: {len(ERR)}"} (trimesh {trimesh.__version__})')
    sys.exit(1 if ERR else 0)


if __name__ == '__main__':
    main()

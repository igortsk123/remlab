#!/usr/bin/env python3
"""Меши обстановки комнаты (телевизор, окно, дверь) из набора Kenney → в галерею мешей.

ЗАЧЕМ. У телевизора, окна и двери нет товара, значит нет и `sid`, — сцена рисовала их
clay-плашками: синий прямоугольник вместо ТВ модель честно принимала за панель на стене.
Меши берём из набора Kenney Furniture Pack (`~/scout-scenes/kits/kenney`, лицензия **CC0**:
коммерческое использование без ограничений и без обязательной ссылки — проверено в
`License.txt`). Sketchfab-модели, отобранные 01.09, скачать не удалось: там нужен вход в
аккаунт (см. `.memory_bank/domain/integrations.md` § Sketchfab).

ЧТО ДЕЛАЕТ. Переводит OBJ в GLB, ЗАПЕКАЯ цвет материала в цвет граней: растеризатор берёт
цвет через `mesh_render.flat_colors`, а тот читает только face/vertex colors — материал без
текстуры он не видит и заливает предмет серым (175). Затем кладёт файл рядом с товарными
мешами (`/test/mesh-pilot10/<id>/model.glb`), поэтому сцена достаёт его обычным
`draft_render._scene3d_glb`, без второго механизма.

ЗАПУСК:  python kit_fixtures.py [--publish]
Без `--publish` — только собрать в `out/kit-fixtures/`. Соответствие «роль → id» живёт в
`draft_render.FIXTURE_MESH` вместе с каноническим разворотом фронта.
"""
import argparse
import os
import subprocess
import sys

import numpy as np
import trimesh

KIT = os.path.expanduser('~/scout-scenes/kits/kenney/Models')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'kit-fixtures')
REMOTE = 'root@89.167.127.0:/opt/remlab/test/mesh-pilot10'
PORT = '22222'

# ЭКРАН ВЫКЛЮЧЕННОГО ТЕЛЕВИЗОРА — ТЁМНЫЙ (решение 26.08). У модели он светло-бирюзовый, и на
# кадре читался как включённый; модель по такому кадру рисует синий прямоугольник.
SCREEN_OFF = np.array([28, 30, 32, 255], np.uint8)

# id в галерее → (файл набора, {имя материала: цвет-замена})
FIXTURES = {
    'kit-tv-modern': ('televisionModern', {'metal': SCREEN_OFF}),
}


def bake(src_name: str, recolor: dict) -> trimesh.Trimesh:
    """OBJ → одна сетка с цветом материала, запечённым в грани."""
    path = os.path.join(KIT, src_name + '.obj')
    if not os.path.exists(path):
        raise SystemExit(f'нет модели {path}')
    scene = trimesh.load(path, force='scene')
    parts = []
    for name, geom in scene.geometry.items():
        mat = getattr(geom.visual, 'material', None)
        col = getattr(mat, 'baseColorFactor', None) if mat is not None else None
        if col is None and mat is not None:
            col = getattr(mat, 'diffuse', None)
        col = np.array(col if col is not None else [175, 175, 175, 255])[:4].astype(np.uint8)
        if name in recolor:
            col = recolor[name]
        flat = trimesh.Trimesh(vertices=geom.vertices.copy(), faces=geom.faces.copy(),
                               process=False)
        flat.visual = trimesh.visual.color.ColorVisuals(
            mesh=flat, face_colors=np.tile(col, (len(flat.faces), 1)))
        parts.append(flat)
    return trimesh.util.concatenate(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--publish', action='store_true', help='выложить в галерею мешей прода')
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    for mid, (src, recolor) in FIXTURES.items():
        mesh = bake(src, recolor)
        d = os.path.join(OUT, mid)
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, 'model.glb')
        mesh.export(dst)
        cols = np.unique(mesh.visual.face_colors[:, :3], axis=0).tolist()
        print(f'{mid}: {src}.obj → граней {len(mesh.faces)}, цвета {cols}')
        if args.publish:
            subprocess.run(['ssh', '-p', PORT, REMOTE.split(':')[0],
                            f'mkdir -p /opt/remlab/test/mesh-pilot10/{mid}'], check=True)
            subprocess.run(['scp', '-P', PORT, dst, f'{REMOTE}/{mid}/model.glb'], check=True)
            subprocess.run(['ssh', '-p', PORT, REMOTE.split(':')[0],
                            f'chown -R 1000:1000 /opt/remlab/test/mesh-pilot10/{mid}'], check=True)
            print(f'  выложен: https://remont-lab.online/test/mesh-pilot10/{mid}/model.glb')
    return 0


if __name__ == '__main__':
    sys.exit(main())

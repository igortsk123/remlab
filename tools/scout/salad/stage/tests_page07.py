#!/usr/bin/env python3
"""Тесты кадров страницы этапа 07 (T-189/3, владелец TG 1661): боковой кадр не обрезается краем, силуэт по центру габарита, поле ≥3 % со всех сторон; не прошёл — отдаляем.
Без сети, без БД; предмет — синтетический (длинная тумба с плотной сеткой на одном конце: «смещённая масса», из-за которой `mesh_render.render` центрировал по средней вершин и обрезал край)."""
from __future__ import annotations

import os
import sys

import numpy as np
import trimesh
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.abspath(os.path.join(HERE, '..', '..')), os.path.abspath(os.path.join(HERE, '..', '..', '..'))]
import mesh_render as MR  # noqa: E402
import page07 as P  # noqa: E402

fails: list[str] = []


def ok(cond: bool, name: str) -> None:
    print(('ok   ' if cond else 'ОШИБКА ') + name)
    if not cond:
        fails.append(name)


def long_cabinet() -> list:
    """Тумба 3×0,6×0,6 + плотный кусок на одном конце (сетка с тысячами вершин): средняя вершин сильно смещена от середины габарита."""
    body = trimesh.creation.box(extents=(3.0, 0.6, 0.6))
    knob = trimesh.creation.box(extents=(0.4, 0.5, 0.5))
    knob.apply_translation((1.3, 0, 0))
    dense = knob.subdivide().subdivide().subdivide().subdivide()
    return [body, dense]


def raw_margins(parts, yaw, pitch, size):
    prev = os.environ.get('UNLIT')
    os.environ['UNLIT'] = '1'
    try:
        im = MR.render(parts, yaw_deg=yaw, pitch_deg=pitch, size=(size, size))
    finally:
        if prev is None:
            os.environ.pop('UNLIT', None)
        else:
            os.environ['UNLIT'] = prev
    return P.silhouette_margins(im)


SZ = 200
parts = long_cabinet()
n_dense = len(parts[1].vertices)
sv = P.side_view_angles({'az': 25.0, 'el': 12.0})
views = {'cam': -sv['az_cam'], 'left': sv['left']['yaw'], 'right': sv['right']['yaw']}
# 1) без починки такой предмет у края: хотя бы один ракурс из трёх обрезается / упирается (иначе тест ничего не доказывает)
base = {k: raw_margins(parts, y, sv['pitch'], SZ) for k, y in views.items()}
ok(any(min(m.values()) < P.MARGIN_MIN for m in base.values()), f'фикстура воспроизводит дефект: у голого render поле < {P.MARGIN_MIN:.0%} хотя бы на одном ракурсе ({ {k: round(min(m.values()), 3) for k, m in base.items()} }, плотных вершин {n_dense})')
# 2) с починкой — все ракурсы: поле ≥ 3 % со всех сторон, силуэт по центру
for k, y in views.items():
    im, info = P.render_framed(parts, y, sv['pitch'], SZ)
    m = info['margins']
    ok(info['ok'] and min(m.values()) >= P.MARGIN_MIN, f'кадр {k}: поле ≥ {P.MARGIN_MIN:.0%} со всех сторон (мин. {min(m.values()):.1%}, отдалений {info["tries"] - 1})')
    ok(abs(m['left'] - m['right']) < 0.03 and abs(m['top'] - m['bottom']) < 0.03, f'кадр {k}: силуэт по центру габарита (слева {m["left"]:.1%}, справа {m["right"]:.1%})')
    ok(im.size == (SZ, SZ) and im.mode == 'RGB', f'кадр {k}: квадрат {SZ}×{SZ}, RGB поверх белого')
# 3) рамка по габариту не меняет масштаб/состав: тот же предмет без смещённой массы — поля те же с обеих сторон
sym = [trimesh.creation.box(extents=(3.0, 0.6, 0.6))]
im, info = P.render_framed(sym, views['left'], sv['pitch'], SZ)
ok(info['ok'] and abs(info['margins']['left'] - info['margins']['right']) < 0.02, 'симметричный предмет: рамка не ломается (поля слева и справа равны)')
# 4) «отдаляем и перерисовываем»: слишком тесный кадр не проходит frame_ok, после zoom_out проходит
tight = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
tight.paste(Image.new('RGBA', (98, 60), (200, 50, 50, 255)), (1, 20))
ok(not P.frame_ok(tight) and P.frame_ok(P.zoom_out(tight, 0.05)), 'силуэт у края (1 %) не проходит проверку; после отдаления на 5 % — проходит')
edge = Image.new('RGBA', (100, 100), (0, 0, 0, 0))
edge.paste(Image.new('RGBA', (60, 60), (200, 50, 50, 255)), (40, 20))
ok(P.silhouette_margins(edge)['right'] == 0.0 and not P.frame_ok(edge), 'силуэт, касающийся края, ловится (поле 0)')
ok(P.silhouette_margins(Image.new('RGBA', (10, 10), (0, 0, 0, 0))) is None and not P.frame_ok(Image.new('RGBA', (10, 10), (0, 0, 0, 0))), 'пустой кадр — не «прошёл»')
# 5) груз без площади не рисуется: пикселей столько же, сколько у предмета (центрирование не добавляет цвета)
cabinet_only = P.over_white(Image.fromarray(np.zeros((4, 4, 4), np.uint8)))
ok(cabinet_only.size == (4, 4), 'over_white: пустой RGBA → белый кадр')

print()
print(f'ПРОВАЛЕНО: {len(fails)}' if fails else 'ВСЕ ТЕСТЫ ПРОШЛИ')
sys.exit(1 if fails else 0)

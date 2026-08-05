#!/usr/bin/env python3
"""СХЕМА кадра: форма и место каждого предмета, без внешнего вида.

Зачем. В аппликации предмет показан своей фотографией — узнаваемо, но фотография снята с чужой
точки и спорит с ракурсом. В схеме наоборот: показываем ТОЛЬКО геометрию — где предмет стоит, как
развёрнут, какой он формы, — а внешний вид модель берёт с листа эталонов. Владелец 2026-08-05:
«нам нужны схематичные изображения каждого предмета, чтобы модель видела, где объект расположен,
и по референсам собирала точно».

Форма берётся из 3D-модели товара, если она есть (`meshes/`), иначе из прокси-объёма компилятора
сцены. Всё заливается ровным серым: цвет и материал — не наше дело на этом шаге.

  ~/venvs/scout/bin/python schema_make.py 21 --cams C1,C2
"""
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))

from scene_build import load_scene  # noqa: E402
KIT = os.path.join(SCENE_DIR, 'kits', 'kenney')
# Схематичные модели мебели — бесплатный CC0-кит Kenney (Furniture Kit, 120 моделей). Своя
# 3D-модель товара для схемы не нужна: форма нужна КАТЕГОРИИ, а внешний вид приходит с эталона
# (владелец, 2026-08-05). Модель кита масштабируется под НАШИ габариты по каждой оси.
KIT_ROLE = {
    'диван': 'loungeSofaCorner', 'кресло': 'loungeChair', 'пуф': 'benchCushionLow',
    'столик': 'tableCoffee', 'стол': 'table', 'обеденный стол': 'table',
    'комод': 'bookcaseClosedWide', 'тумба': 'cabinetTelevision', 'тв-тумба': 'cabinetTelevision',
    'стеллаж': 'bookcaseOpen', 'полка': 'bookcaseOpenLow', 'шкаф': 'bookcaseClosedDoors',
    'кашпо': 'pottedPlant', 'растение': 'pottedPlant', 'ковёр': 'rugRectangle',
    'люстра': 'lampSquareCeiling', 'торшер': 'lampSquareFloor', 'лампа': 'lampSquareTable',
    'тв': 'televisionModern', 'кровать': 'bedDouble', 'ваза': 'pottedPlant', 'подушка': 'pillow', 'плед': 'pillowLong',
}


def kit_mesh(role: str, it):
    """Модель кита, растянутая под наши габариты (Ш×Г×В в сантиметрах)."""
    name = KIT_ROLE.get(role)
    if not name:
        return None
    import glob as _g

    import trimesh
    hits = _g.glob(os.path.join(KIT, '**', f'{name}.obj'), recursive=True)
    if not hits:
        return None
    m = trimesh.load(hits[0], force='mesh')
    ext = m.extents.copy()
    ext[ext < 1e-6] = 1.0
    w, d, h = float(it.w_cm or 60), float(it.d_cm or 60), float(it.h_cm or 60)
    m.apply_scale([w / ext[0], h / ext[1], d / ext[2]])     # кит Y-вверх
    m.apply_translation(-m.bounds.mean(axis=0))
    return m
from viz_paste import FLOOR, SKIP, SOFT, billboard, mesh_yaw_pitch  # noqa: E402
from planner.scene import cameras_for, compile_scene  # noqa: E402

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
GREY = (198, 201, 204)          # предметы
SHELL = (238, 238, 236)         # стены и потолок
FLOORC = (223, 219, 213)        # пол


def mesh_silhouette(n: int, role: str, p, it, cam, W: int, H: int):
    """Серый силуэт предмета: модель кита под наши габариты, под углом нашей камеры."""
    try:
        from mesh_render import render
        m = kit_mesh(role, it)
        if m is None:
            return None
        yaw, pitch = mesh_yaw_pitch(p, it, cam)
        return render([m], yaw, pitch, size=(900, 900), flat=GREY)
    except Exception:  # noqa: BLE001 — нет модели: рисуем прокси-объём
        return None


def place(canvas: np.ndarray, cam, p, it, img: Image.Image) -> int:
    """Ставит силуэт по видимой ширине следа и линии касания пола (та же геометрия, что вклейка)."""
    import math

    from viz_paste import trim_alpha
    H, W = canvas.shape[:2]
    eye, fwd, right, up = cam.basis()
    corner, wv, hv, _ = billboard(p, it, cam)
    quad = np.array([corner, corner + wv, corner + wv + hv, corner + hv])
    rel = quad - eye
    if float(np.max(rel @ fwd)) <= 1.0:
        return 0
    focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    z = np.maximum(rel @ fwd, 1e-3)
    us = W / 2 + focal * (rel @ right) / z
    vs = H / 2 - focal * (rel @ up) / z + cam.shift_y * H
    bw = float(us.max() - us.min())
    if bw < 4:
        return 0
    cut = trim_alpha(img)
    k = bw / cut.width
    nw, nh = max(int(cut.width * k), 2), max(int(cut.height * k), 2)
    cut = cut.resize((nw, nh), Image.LANCZOS)
    src = np.asarray(cut).astype(np.float32)
    ox = int(round((us.min() + us.max()) / 2 - nw / 2))
    oy = int(round(float(vs.max()) - nh))
    y0, x0 = max(oy, 0), max(ox, 0)
    y1, x1 = min(oy + nh, H), min(ox + nw, W)
    if y1 <= y0 or x1 <= x0:
        return 0
    src = src[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    a = (src[..., 3:4] / 255.0) if src.shape[2] > 3 else np.ones(src.shape[:2] + (1,), np.float32)
    ok = a[..., 0] > 0.15
    if ok.sum() < 30:
        return 0
    yy, xx = np.nonzero(ok)
    canvas[yy + y0, xx + x0] = np.clip(src[yy, xx, :3], 0, 255).astype(np.uint8)
    return int(ok.sum())


def build(n: int, cam_name: str) -> str:
    prefix = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}')
    room, placements = load_scene(n)
    cam = next(c for c in cameras_for(room, placements) if c.name == cam_name)
    out = compile_scene(room, placements, cam)
    ins = out['instances']
    H, W = ins.shape
    sem = out.get('semantic')

    # Оболочку берём из нашего же нейтрального рендера пустой комнаты: там видны угол, линия
    # пола и проёмы. Плоская заливка их теряла, и схема читалась как обои (2026-08-05).
    empty = f'{prefix}-empty-clay.png'
    if os.path.exists(empty):
        canvas = np.asarray(Image.open(empty).convert('RGB').resize((W, H))).copy()
    else:
        canvas = np.full((H, W, 3), SHELL, np.uint8)

    frame = json.load(open(f'{prefix}-frame.json'))
    id_map = {int(k): v for k, v in (frame.get('ids') or {}).items()}
    in_frame = set(frame['visible'])
    by = {p.role: p for p in placements}
    ex, _, ez = cam.eye
    order = sorted(id_map.items(),
                   key=lambda kv: (0 if kv[1] in FLOOR else 1,
                                   -((by[kv[1]].x - ex) ** 2 + (by[kv[1]].y - ez) ** 2)
                                   if kv[1] in by else 0))
    drawn = []
    for sid, role in order:
        if role in SKIP or role not in in_frame or role not in by:
            continue
        p = by[role]
        if p.item is None:
            continue
        mask = ins == int(sid)
        if role in SOFT or role in FLOOR or not mask.any():
            if mask.any():                       # текстиль и ковёр — просто плоским пятном
                canvas[mask] = GREY if role not in FLOOR else (232, 229, 224)
                drawn.append(role)
            continue
        sil = mesh_silhouette(n, role, p, p.item, cam, W, H)
        if sil is not None and place(canvas, cam, p, p.item, sil) > 0:
            drawn.append(role)
        else:                                    # нет модели — прокси-объём компилятора
            canvas[mask] = GREY
            drawn.append(role)

    # ВЫНОСКИ, а не подписи поверх предмета: подпись на объекте его загораживает — даже на схеме
    # (владелец, 2026-08-05). Номер с габаритами стоит над предметом, тонкая линия ведёт внутрь.
    img = Image.fromarray(canvas)
    d = ImageDraw.Draw(img, 'RGBA')
    from viz_marks import numbering
    nums = numbering(n, ('C1', 'C2'))
    f_num = ImageFont.truetype(FONT, 30)
    f_dim = ImageFont.truetype(FONT, 22)
    used: list[tuple[float, float]] = []
    for sid, role in sorted(id_map.items(), key=lambda kv: kv[0]):
        if role not in drawn or role not in by or by[role].item is None:
            continue
        mask = ins == int(sid)
        if not mask.any():
            continue
        ys, xs = np.nonzero(mask)
        num = nums.get(role)
        if not num:
            continue
        it = by[role].item
        dims = f'{int(it.w_cm)}×{int(it.d_cm)}×{int(it.h_cm or 0)}'
        cx = float(xs.mean())
        top = float(ys.min())
        my = max(top - 46, 26)
        mx = min(max(cx, 40), W - 40)
        for _ in range(14):                       # разводим выноски, чтобы не наезжали
            if all(abs(my - uy) > 44 or abs(mx - ux) > 130 for ux, uy in used):
                break
            my += 46
        used.append((mx, my))
        near = np.argmin((ys - float(ys.mean())) ** 2 + (xs - cx) ** 2)
        ax, ay = float(xs[near]), float(ys[near])
        d.line([mx, my + 18, ax, ay], fill=(200, 30, 30, 200), width=2)
        d.ellipse([ax - 5, ay - 5, ax + 5, ay + 5], fill=(200, 30, 30, 230))
        d.ellipse([mx - 18, my - 18, mx + 18, my + 18], fill=(200, 30, 30, 240),
                  outline=(255, 255, 255, 255), width=3)
        d.text((mx, my), str(num), fill=(255, 255, 255), font=f_num, anchor='mm')
        tw = d.textlength(dims, font=f_dim)
        ty = my - 18 - 26
        d.rectangle([mx - tw / 2 - 6, ty - 3, mx + tw / 2 + 6, ty + 24],
                    fill=(200, 30, 30, 210), outline=(255, 255, 255, 230), width=2)
        d.text((mx, ty + 11), dims, fill=(255, 255, 255), font=f_dim, anchor='mm')
    dst = f'{prefix}-schema.jpg'
    img.save(dst, quality=94)
    print(f'{cam_name}: схема, предметов {len(drawn)} → {dst}', flush=True)
    return dst


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    for cam in cams:
        build(n, cam)


if __name__ == '__main__':
    main()

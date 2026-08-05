#!/usr/bin/env python3
"""НАСТОЯЩАЯ 3D-сцена комнаты из схематичных моделей — и съёмка её нашими камерами.

Владелец 2026-08-05: «сначала построй 3D-модель комнаты с предметами в реальных размерах, потом
расставь камеры по углам». Здесь именно это: каждый предмет — модель из бесплатного CC0-кита
(Kenney Furniture Kit), растянутая под НАШИ габариты, поставленная в НАШИ координаты и повёрнутая
как решил планировщик. Комната — пол и стены. Дальше сцена снимается перспективной камерой из
угла, тем же объективом и с тем же сдвигом, что и остальной конвейер.

Внешний вид не показываем вообще: всё серое. Цвет, материал и детали модель берёт с листа
эталонов — схема отвечает только за геометрию.

  ~/venvs/scout/bin/python schema3d.py 21 --cams C1,C2
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))

from scene_build import load_scene  # noqa: E402
from viz_paste import SKIP  # noqa: E402
from planner.scene import cameras_for  # noqa: E402

FONT = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
KIT = os.path.join(SCENE_DIR, 'kits', 'kenney')
KIT_ROLE = {
    'диван': 'loungeSofaCorner', 'кресло': 'loungeChair', 'пуф': 'benchCushionLow',
    'столик': 'tableCoffee', 'стол': 'table', 'обеденный стол': 'table',
    'комод': 'bookcaseClosedWide', 'тумба': 'cabinetTelevision', 'тв-тумба': 'cabinetTelevision',
    'стеллаж': 'bookcaseOpen', 'полка': 'bookcaseOpenLow', 'шкаф': 'bookcaseClosedDoors',
    'кашпо': 'pottedPlant', 'растение': 'pottedPlant', 'ковёр': 'rugRectangle',
    'люстра': 'lampSquareCeiling', 'торшер': 'lampSquareFloor', 'лампа': 'lampSquareTable',
    'тв': 'televisionModern', 'кровать': 'bedDouble', 'ваза': 'pottedPlant',
    'подушка': 'pillow', 'подушка 2': 'pillow', 'плед': 'pillowLong',
}
WALL = np.array([232, 231, 228], np.float32)
FLOOR = np.array([214, 205, 194], np.float32)
OBJ = np.array([176, 181, 186], np.float32)


def sofa_mesh(p, it):
    """Диван строим ПО СВОИМ ДАННЫМ, а не растягиваем чужую модель.

    Из кита диван приезжает со своими пропорциями, и при растяжении под 230×150 он плывёт
    (владелец, 2026-08-05). У нас есть точный след (у углового — Г-образный), высота сиденья 42 см
    и общая высота из чертежа: сиденье = экструзия следа, спинка — плита вдоль тыльной стороны,
    подлокотник — по краю прямой секции.
    """
    import trimesh
    from planner.geometry import footprint
    from shapely.affinity import translate as _tr
    poly = footprint(p, it)
    poly = _tr(poly, -p.x, -p.y)                     # в локальные координаты предмета
    h = float(it.h_cm or 88)
    seat_h = min(42.0, h * 0.5)
    back_t, arm_t, arm_h = 22.0, 20.0, seat_h + 22.0
    parts = [trimesh.creation.extrude_polygon(poly, seat_h)]
    x0, y0, x1, y1 = poly.bounds
    face = {0: (0.0, 1.0), 90: (1.0, 0.0), 180: (0.0, -1.0),
            270: (-1.0, 0.0)}.get(int(round(p.rot)) % 360, (0.0, -1.0))
    back = trimesh.creation.box(extents=[x1 - x0, back_t, h - seat_h])
    # НЕ ДОСТРОИТЬ ЛУЧШЕ, ЧЕМ ПЕРЕСТРОИТЬ (правило владельца, 2026-08-05). В схеме показываем
    # только то, что ИЗМЕРЕНО: след из плана, высоту сиденья и общую высоту. Подлокотники мы не
    # знаем — их не рисуем: выдуманную деталь модель примет за факт, а недостающую дорисует по
    # эталону сама. Спинка — единственная добавка, без неё сиденье читается как тумба; она стоит
    # у тыльной стороны прямой секции и не выходит за её пределы.
    sec = float(getattr(it, 'corner_section_cm', 0) or 0) if getattr(it, 'corner', False) else 0.0
    if face[1] != 0:
        by = (y0 + back_t / 2) if face[1] > 0 else (y1 - back_t / 2)
        back.apply_translation([(x0 + x1) / 2, by, seat_h + (h - seat_h) / 2])
    else:
        back = trimesh.creation.box(extents=[back_t, y1 - y0, h - seat_h])
        bx = (x0 + back_t / 2) if face[0] > 0 else (x1 - back_t / 2)
        back.apply_translation([bx, (y0 + y1) / 2, seat_h + (h - seat_h) / 2])
    m = trimesh.util.concatenate(parts + [back])
    # экструзия даёт Z-вверх, а наш мир Y-вверх — разворачиваем
    v = np.asarray(m.vertices, np.float64).copy()
    m.vertices = np.column_stack([v[:, 0], v[:, 2], v[:, 1]])
    return m


def box_mesh(p, it):
    """Самая простая честная форма: объём НАСТОЯЩЕГО следа предмета на его высоту.

    Максимально схематично (владелец, 2026-08-05): никаких чужих моделей и придуманных деталей —
    только то, что измерено. Форму вещи модель возьмёт с эталона, от схемы нужны место, размер и
    разворот.
    """
    import trimesh
    from planner.geometry import footprint
    from shapely.affinity import translate as _tr
    poly = _tr(footprint(p, it), -p.x, -p.y)
    m = trimesh.creation.extrude_polygon(poly, max(float(it.h_cm or 40), 2.0))
    v = np.asarray(m.vertices, np.float64).copy()
    m.vertices = np.column_stack([v[:, 0], v[:, 2], v[:, 1]])      # экструзия Z-вверх → наш Y-вверх
    return m


def kit_model(role: str, it):
    """Модель кита под наши габариты, начало координат — в центре следа на полу."""
    import glob as _g

    import trimesh
    name = KIT_ROLE.get(role)
    if not name:
        return None
    hits = _g.glob(os.path.join(KIT, '**', f'{name}.obj'), recursive=True)
    if not hits:
        return None
    m = trimesh.load(hits[0], force='mesh')
    ext = m.extents.copy()
    ext[ext < 1e-6] = 1.0
    w, d, h = float(it.w_cm or 60), float(it.d_cm or 60), float(it.h_cm or 60)
    m.apply_scale([w / ext[0], h / ext[1], d / ext[2]])       # кит Y-вверх, как и наш мир
    lo = m.bounds[0].copy()
    m.apply_translation([-(m.bounds[0][0] + m.bounds[1][0]) / 2, -lo[1],
                         -(m.bounds[0][2] + m.bounds[1][2]) / 2])
    return m


def room_mesh(room):
    """Пол и две стены комнаты как плоскости — оболочка сцены."""
    W, D, H = room.width_cm, room.depth_cm, 270.0
    faces, verts, colors = [], [], []

    def quad(a, b, c, d, col):
        i = len(verts)
        verts.extend([a, b, c, d])
        faces.extend([[i, i + 1, i + 2], [i, i + 2, i + 3]])
        colors.extend([col, col])

    quad([0, 0, 0], [W, 0, 0], [W, 0, D], [0, 0, D], FLOOR)          # пол
    quad([0, 0, D], [W, 0, D], [W, H, D], [0, H, D], WALL)           # дальняя стена
    quad([0, 0, 0], [0, 0, D], [0, H, D], [0, H, 0], WALL)           # левая
    quad([W, 0, 0], [W, 0, D], [W, H, D], [W, H, 0], WALL)           # правая
    quad([0, 0, 0], [W, 0, 0], [W, H, 0], [0, H, 0], WALL)           # ближняя
    quad([0, H, 0], [W, H, 0], [W, H, D], [0, H, D], WALL)           # потолок
    return np.array(verts, np.float64), np.array(faces, np.int32), np.array(colors, np.float32)


def scene_geometry(n: int, only: set | None = None):
    """Сцена в мировых координатах: вершины, грани, цвет грани, id предмета на грань.

    `only` — какие предметы вообще строить. Схема обязана показывать РОВНО то, что наш компилятор
    считает попавшим в кадр: иначе в кадр лезет предмет, который легенда объявила отсутствующим,
    и модель получает противоречие (владелец: «на виде 2 диван, хотя не должно быть», 2026-08-05).
    """
    room, placements = load_scene(n)
    V, F, C = room_mesh(room)
    ids = np.zeros(len(F), np.int32)
    names: dict[int, str] = {}
    sid = 0
    for p in sorted(placements, key=lambda q: q.role):
        if p.item is None or p.role in SKIP:
            continue
        if only is not None and p.role not in only:
            continue
        try:
            m = sofa_mesh(p, p.item) if p.role in ('диван', 'кресло-кровать') else box_mesh(p, p.item)
        except Exception:  # noqa: BLE001 — не вышло: пропускаем предмет, чем рисовать неверно
            m = None
        if m is None:
            continue
        sid += 1
        names[sid] = p.role
        v = np.asarray(m.vertices, np.float64).copy()
        if False:                                        # след уже повёрнут — не крутим
            a = math.radians(-float(p.rot))
            ca, sa = math.cos(a), math.sin(a)
            x, z = v[:, 0] * ca - v[:, 2] * sa, v[:, 0] * sa + v[:, 2] * ca
            v[:, 0], v[:, 2] = x, z
        v[:, 0] += p.x
        v[:, 2] += p.y
        v[:, 1] += float(getattr(p, 'elev_cm', 0.0))
        f = np.asarray(m.faces, np.int32) + len(V)
        V = np.vstack([V, v])
        F = np.vstack([F, f])
        C = np.vstack([C, np.repeat(OBJ[None, :], len(f), axis=0)])
        ids = np.concatenate([ids, np.full(len(f), sid, np.int32)])
    return room, placements, V, F, C, ids, names


def render(cam, V, F, C, ids, size=(1344, 896)):
    """Перспективный рендер с z-буфером: тот же объектив и сдвиг, что у всего конвейера."""
    W, H = size
    eye, fwd, right, up = cam.basis()
    rel = V - np.asarray(eye, np.float64)
    zc = rel @ fwd
    focal = (W / 2) / math.tan(math.radians(cam.fov_deg) / 2)
    with np.errstate(divide='ignore', invalid='ignore'):
        us = W / 2 + focal * (rel @ right) / zc
        vs = H / 2 - focal * (rel @ up) / zc + cam.shift_y * H
    img = np.repeat(np.repeat(WALL[None, None, :], H, 0), W, 1).astype(np.float32)
    zbuf = np.full((H, W), 1e18, np.float32)
    inst = np.zeros((H, W), np.int32)
    light = np.array([0.4, 0.75, 0.5], np.float64)
    light /= np.linalg.norm(light)
    order = np.argsort(-zc[F].mean(axis=1))            # дальние раньше
    for idx in order:
        a, b, c = F[idx]
        if min(zc[a], zc[b], zc[c]) <= 5:
            continue
        xs = np.array([us[a], us[b], us[c]])
        ys = np.array([vs[a], vs[b], vs[c]])
        x0, x1 = int(max(0, xs.min())), int(min(W - 1, xs.max()) + 1)
        y0, y1 = int(max(0, ys.min())), int(min(H - 1, ys.max()) + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        det = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(det) < 1e-9:
            continue
        gy, gx = np.mgrid[y0:y1, x0:x1]
        w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / det
        w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / det
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        z = w0 * zc[a] + w1 * zc[b] + w2 * zc[c]
        sub = zbuf[y0:y1, x0:x1]
        upd = inside & (z < sub)
        if not upd.any():
            continue
        sub[upd] = z[upd]
        n = np.cross(V[b] - V[a], V[c] - V[a])
        ln = np.linalg.norm(n)
        lam = abs(float(n @ light) / ln) if ln > 1e-9 else 0.5
        shade = 0.62 + 0.38 * lam
        img[y0:y1, x0:x1][upd] = np.clip(C[idx] * shade, 0, 255)
        inst[y0:y1, x0:x1][upd] = ids[idx]
    # Карта глубины той же сцены: ближе — светлее. Отдаём её модели пятой картинкой как подсказку
    # о пространстве (у семейства GPT-4o есть задачи пространственного контроля по глубине).
    fin = np.isfinite(zbuf) & (zbuf < 1e17)
    depth = np.zeros_like(zbuf)
    if fin.any():
        lo, hi = float(np.percentile(zbuf[fin], 1)), float(np.percentile(zbuf[fin], 99))
        depth = np.clip((zbuf - lo) / max(hi - lo, 1e-6), 0, 1)
        depth[~fin] = 1.0
    dep_img = Image.fromarray(((1 - depth) * 255).astype(np.uint8))
    return Image.fromarray(img.astype(np.uint8)), inst, dep_img


def draw_callouts(img: Image.Image, inst: np.ndarray, names, by, nums) -> Image.Image:
    """Выноски НАД предметом: номер и габариты сверху, тонкая линия внутрь. Предмет не закрываем."""
    d = ImageDraw.Draw(img, 'RGBA')
    f_num = ImageFont.truetype(FONT, 30)
    f_dim = ImageFont.truetype(FONT, 22)
    W, H = img.size
    used: list[tuple[float, float]] = []
    for sid, role in sorted(names.items(), key=lambda kv: kv[1]):
        mask = inst == sid
        if mask.sum() < 200 or role not in by or by[role].item is None:
            continue
        num = nums.get(role)
        if not num:
            continue
        ys, xs = np.nonzero(mask)
        cx, top = float(xs.mean()), float(ys.min())
        my = max(top - 64, 78)      # выноска ВЫШЕ предмета; 78 — чтобы подпись не ушла за край
        mx = min(max(cx, 46), W - 46)
        for _ in range(16):
            if all(abs(my - uy) > 50 or abs(mx - ux) > 150 for ux, uy in used):
                break
            my -= 50
            if my < 78:
                my = max(top - 64, 78)
                mx += 90
        used.append((mx, my))
        near = np.argmin((ys - float(ys.mean())) ** 2 + (xs - cx) ** 2)
        d.line([mx, my + 19, float(xs[near]), float(ys[near])], fill=(200, 30, 30, 190), width=2)
        d.ellipse([float(xs[near]) - 5, float(ys[near]) - 5, float(xs[near]) + 5,
                   float(ys[near]) + 5], fill=(200, 30, 30, 230))
        d.ellipse([mx - 19, my - 19, mx + 19, my + 19], fill=(200, 30, 30, 240),
                  outline=(255, 255, 255, 255), width=3)
        d.text((mx, my), str(num), fill=(255, 255, 255), font=f_num, anchor='mm')
        it = by[role].item
        dims = f'{int(it.w_cm)}×{int(it.d_cm)}×{int(it.h_cm or 0)}'
        tw = d.textlength(dims, font=f_dim)
        mx = min(max(mx, tw / 2 + 12), W - tw / 2 - 12)     # подпись целиком в кадре
        ty = my - 19 - 28
        d.rectangle([mx - tw / 2 - 6, ty - 3, mx + tw / 2 + 6, ty + 25],
                    fill=(200, 30, 30, 215), outline=(255, 255, 255, 235), width=2)
        d.text((mx, ty + 11), dims, fill=(255, 255, 255), font=f_dim, anchor='mm')
    return img


def main() -> None:
    n = int(sys.argv[1])
    cams = (sys.argv[sys.argv.index('--cams') + 1].split(',')
            if '--cams' in sys.argv else ['C1', 'C2'])
    from viz_marks import numbering
    nums = numbering(n, tuple(cams))
    for cam_name in cams:
        fr = os.path.join(SCENE_DIR, f'scene{n}-{cam_name}-frame.json')
        only = set(json.load(open(fr))['visible']) if os.path.exists(fr) else None
        room, placements, V, F, C, ids, names = scene_geometry(n, only)
        by = {p.role: p for p in placements}
        all_cams = {c.name: c for c in cameras_for(room, placements)}
        img, inst, dep = render(all_cams[cam_name], V, F, C, ids)
        dep.save(f'{os.path.join(SCENE_DIR, f"scene{n}-{cam_name}")}-schema-depth.png')
        plain = f'{os.path.join(SCENE_DIR, f"scene{n}-{cam_name}")}-schema3d.jpg'
        img.save(plain, quality=94)
        # ОДИН ИСТОЧНИК ПРАВДЫ О КАДРЕ. Раньше «что в кадре» считалось в двух местах по-разному:
        # компилятор (доля кадра) и разметка (доля самого предмета). Схема показывала лампу,
        # которую список объявлял отсутствующей (владелец, 2026-08-05). Пишем, что реально видит
        # камера схемы, и этим же питаем список предметов.
        vis = {}
        total = float(inst.size)
        for s_id, r_name in names.items():
            px = int((inst == s_id).sum())
            if px:
                vis[r_name] = {'px': px, 'share_frame': round(px / total, 4)}
        json.dump(vis, open(f'{os.path.join(SCENE_DIR, f"scene{n}-{cam_name}")}-schema-vis.json',
                            'w'), ensure_ascii=False, indent=1)
        marked = draw_callouts(img.copy(), inst, names, by, nums)
        dst = f'{os.path.join(SCENE_DIR, f"scene{n}-{cam_name}")}-schema3d-marked.jpg'
        marked.save(dst, quality=94)
        print(f'{cam_name}: предметов в кадре {len(set(inst.ravel()) - {0})} → {dst}', flush=True)


if __name__ == '__main__':
    main()

"""Зеркало прихожей на серверном кадре (T-20261106-73, план hall-demo-01 этап 2). Без сети, базы и мешей.

Зеркало — стратегия ассета `procedural_plane` (`rules/asset-strategies.json`): плоскость на стене по месту солвера (стена,
разворот, высота подвеса `elev`), не clay-коробка и не меш. Проверки:
  1) геометрия лицевой стороны: на какой стене, куда смотрит, на какой высоте — то же правило, что у живой сцены
     (`lib/viewer3d/kits/wall-plane.ts:wallPlaneFace`, юнит-тест `tests/unit/wall-plane.test.ts`);
  2) признак плоскости — стратегия и геометрия: ковёр той же стратегии лежит (своим путём), мебель — нет;
  3) кадр `scene3d_frame` по набору `compose_hall` (банк стенда T-61, сканди): зеркало нарисовано плоскостью, в clay его нет,
     центр полотна в кадре — на проекции высоты солвера; шкаф перед зеркалом его закрывает (z-буфер честный).
    ~/venvs/scout/bin/python tools/scout/tests/test_wall_plane.py
    ~/venvs/scout/bin/python tools/scout/tests/test_wall_plane.py --bank <bank-hall.json> --shots <новая папка>   # + кадры"""
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
fails = 0


def check(name, cond, info=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {info}' if info and not cond else ''))
    fails += 0 if cond else 1


import numpy as np  # noqa: E402

import draft_render as DR  # noqa: E402
import scene_mesh as SM  # noqa: E402
from planner.models import Item, Placement  # noqa: E402
from planner.scene import Camera  # noqa: E402


def mirror(x, y, rot, w=56.0, d=3.0, h=72.0, elev=114.0, role='зеркало'):
    return Placement(role=role, x=x, y=y, rot=rot, elev_cm=elev, item=Item(role=role, w_cm=w, d_cm=d, h_cm=h))


# 1) геометрия
q = DR.wall_plane_quads(mirror(1.5, 28, 90))
f = DR.wall_plane_frame_cm(56, 72)
check('запад (rot 90): лицом на +x', q['normal'] == (1.0, 0.0), str(q['normal']))
check('запад: полотно в 3,2 см от стены (след 3 см + зазор)', all(abs(c[0] - 3.2) < 1e-6 for c in q['outer'] + q['inner']))
check('высота: рама от подвеса до подвес + высота', abs(min(c[1] for c in q['outer']) - 114) < 1e-6
      and abs(max(c[1] for c in q['outer']) - 186) < 1e-6)
check('полотно внутри рамы на ширину рамы', abs(min(c[1] for c in q['inner']) - (114 + f)) < 1e-6
      and abs(max(c[2] for c in q['inner']) - min(c[2] for c in q['inner']) - (56 - 2 * f)) < 1e-6)
check('вдоль стены — вокруг центра следа', abs(sum(c[2] for c in q['outer']) / 4 - 28) < 1e-6)
check('восток (rot 270): лицом на −x', DR.wall_plane_quads(mirror(151.5, 30, 270))['normal'] == (-1.0, 0.0))
check('юг (rot 0): лицом на +y', DR.wall_plane_quads(mirror(80, 1.5, 0))['normal'] == (0.0, 1.0))
check('север (rot 180): лицом на −y', DR.wall_plane_quads(mirror(80, 618.5, 180))['normal'] == (0.0, -1.0))
check('рама: 6 % меньшей стороны в 1,5…4 см', DR.wall_plane_frame_cm(20, 30) == 1.5 and abs(DR.wall_plane_frame_cm(60, 120) - 3.6) < 1e-9
      and DR.wall_plane_frame_cm(100, 200) == 4.0)

# 2) признак плоскости
it = lambda r, w, d, h: Item(role=r, w_cm=w, d_cm=d, h_cm=h)  # noqa: E731
check('зеркало и картина — плоскость', DR.is_wall_plane('зеркало', it('зеркало', 56, 3, 72))
      and DR.is_wall_plane('картина 2', it('картина', 50, 2, 70)))
check('ковёр (лежит) — не настенная плоскость', not DR.is_wall_plane('ковёр', it('ковёр', 200, 140, 1)))
check('мебель с мешем — не плоскость', not DR.is_wall_plane('обувница', it('обувница', 60, 35, 113))
      and not DR.is_wall_plane('шкаф-купе', it('шкаф-купе', 180, 60, 220)))
check('без товара — не плоскость', not DR.is_wall_plane('зеркало', None))

# 3) кадр по набору compose_hall (банк стенда T-61, «сканди комфорт»)
HALL = {'w': 153, 'd': 620, 'openings': [
    {'kind': 'door', 'wall': 'south', 'offset_cm': 31, 'width_cm': 90, 'swing_cm': 0},
    {'kind': 'door', 'wall': 'west', 'offset_cm': 160, 'width_cm': 85, 'swing_cm': 0},
    {'kind': 'door', 'wall': 'west', 'offset_cm': 420, 'width_cm': 85, 'swing_cm': 0},
    {'kind': 'door', 'wall': 'north', 'offset_cm': 20, 'width_cm': 70, 'swing_cm': 70}]}
ITEMS = [
    {'role': 'шкаф-купе', 'x': 123.0, 'y': 530.0, 'rot': 270, 'w': 180.0, 'd': 60.0, 'h': 220.0},
    {'role': 'обувница', 'x': 135.5, 'y': 110.0, 'rot': 270, 'w': 60.0, 'd': 35.0, 'h': 113.0},
    {'role': 'банкетка', 'x': 130.5, 'y': 185.0, 'rot': 270, 'w': 90.0, 'd': 45.0, 'h': 45.0},
    {'role': 'вешалка', 'x': 144.5, 'y': 23.0, 'rot': 270, 'w': 46.0, 'd': 17.0, 'h': 92.0},
    {'role': 'зеркало', 'x': 1.5, 'y': 28.0, 'rot': 90, 'w': 56.0, 'd': 3.0, 'h': 72.0, 'elev': 114.0},
]
EYE = (120.0, 150.0, 200.0)
CAM = Camera(name='C1', eye=EYE, target=(0.0, 150.0, 28.0), fov_deg=70.0, width=672, height=448)


def frame(items):
    room, placements, _ = DR.scene_from_request({'room': HALL, 'items': items})
    img, diag = DR.scene3d_frame(room, placements, CAM, {}, {})
    return np.asarray(img).astype(np.float32), diag, placements


img, diag, pls = frame(ITEMS)
used, clay = diag.get('мешей') or [], diag.get('clay') or []
check('зеркало нарисовано плоскостью', 'зеркало (зеркало-плоскость)' in used, str(diag))
check('зеркала нет среди clay-форм', 'зеркало' not in clay, str(clay))
check('зеркало не меш (заказа модели нет): sid не спрашивали', 'зеркало' not in used)
mp = next(p for p in pls if p.role == 'зеркало')
qq = DR.wall_plane_quads(mp)
ctr = tuple(sum(c[i] for c in qq['inner']) / 4 for i in range(3))
pt = SM.project_pts(CAM, [ctr], CAM.width, CAM.height)
cx, cy = int(round(float(pt[0][0]))), int(round(float(pt[0][1])))
px = img[cy, cx]
check('центр полотна в кадре — светлое холодное стекло', px.mean() > 185 and px[2] >= px[0], f'{px} @ {cx},{cy}')
# высота: проекция низа рамы ниже центра, верх — выше (кадр не перевёрнут, подвес — от солвера)
lo = SM.project_pts(CAM, [(ctr[0], 114.0, ctr[2])], CAM.width, CAM.height)
hi = SM.project_pts(CAM, [(ctr[0], 186.0, ctr[2])], CAM.width, CAM.height)
check('низ рамы ниже центра, верх выше', float(lo[0][1]) > cy > float(hi[0][1]))
# под рамой (на стене ниже подвеса) — не стекло
by = int(round(float(lo[0][1]))) + 6
check('ниже подвеса — стена, не стекло', abs(float(img[by, cx].mean()) - float(px.mean())) > 4 or img[by, cx][2] < img[by, cx][0],
      f'{img[by, cx]} vs {px}')
# шкаф прямо перед зеркалом (между камерой и стеной) — зеркало закрыто: z-буфер честный
block = ITEMS[:4] + [ITEMS[4], {'role': 'шкаф', 'x': 40.0, 'y': 60.0, 'rot': 90, 'w': 120.0, 'd': 40.0, 'h': 220.0}]
img2, diag2, _ = frame(block)
check('шкаф перед зеркалом его закрывает', np.abs(img2[cy, cx] - px).max() > 12, f'{img2[cy, cx]} vs {px}')


def shots(bank_path: str, out: str) -> None:
    """Кадры сервера по наборам банка прихожей: те же два ракурса на зеркало, что у стенда живой сцены
    (`tools/flat3d/hall-snap.mjs:facePose`), через `cams_from_request` (поза v2). Папка — новая."""
    import json
    if os.path.exists(out):
        raise SystemExit(f'папка уже есть: {out} — кадры только в новую')
    os.makedirs(out)
    bank = json.load(open(bank_path, encoding='utf-8'))
    for s in (bank if isinstance(bank, list) else bank['sets']):
        lay = s['layout']
        r = lay['_room']
        items = [{'role': k, 'x': p['x'], 'y': p['z'], 'rot': p['rot'], 'w': p['w'], 'd': p['d'], 'h': p['h'],
                  'elev': p.get('elev') or 0} for k, p in lay.items() if not k.startswith('_')]
        m = next((it for it in items if it['role'].startswith('зеркало')), None)
        if m is None:
            continue
        cams = [face_pose(r, m, 170, 'C1'), face_pose(r, m, 320, 'C2')]
        room, placements, _ = DR.scene_from_request({'room': {'w': r['w'], 'd': r['d'], 'openings': r['openings']}, 'items': items})
        for cam in DR.cams_from_request(room, placements, {'cams': cams}):
            img, diag = DR.scene3d_frame(room, placements, cam, {}, {})
            img.save(os.path.join(out, f"{s['style']}.{cam.name}.server.jpg"), quality=90)
            print(s['style'], cam.name, diag.get('мешей'), 'clay:', diag.get('clay'))


def face_pose(r: dict, m: dict, dist: float, name: str) -> dict:
    """Как `hall-snap.mjs:facePose`: в `dist` по нормали и на 40 см вдоль стены к середине, лицом к зеркалу."""
    a = math.radians(m['rot'])
    nx, ny, ux, uy = math.sin(a), math.cos(a), math.cos(a), -math.sin(a)
    d2 = lambda s: (m['x'] + ux * s - r['w'] / 2) ** 2 + (m['y'] + uy * s - r['d'] / 2) ** 2  # noqa: E731
    side = 40 if d2(40) < d2(-40) else -40
    x = min(max(m['x'] + nx * dist + ux * side, 25), r['w'] - 25)
    y = min(max(m['y'] + ny * dist + uy * side, 25), r['d'] - 25)
    rot = (math.degrees(math.atan2(m['x'] - x, -(m['y'] - y))) + 360) % 360
    return {'name': name, 'x': round(x), 'y': round(y), 'rot': round(rot), 'fov': 70, 'pose': 2}


if '--shots' in sys.argv:
    shots(sys.argv[sys.argv.index('--bank') + 1], sys.argv[sys.argv.index('--shots') + 1])

print('итого:', 'OK' if not fails else f'{fails} FAIL')
sys.exit(1 if fails else 0)

"""`scene3d_frame(preview=False)` (T-20261118-09/1): выгрузка сцены для Blender картинку кадра не берёт — рисование превью пропускается, а то, что выгрузка
подменяет и читает (отбор предметов, разведение коллизий, вызовы записчиков ковра/плоскости), остаётся тем же. Без сети, базы и мешей.
    ~/venvs/scout/bin/python tools/scout/tests/test_scene3d_nopreview.py"""
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


import draft_render as DR  # noqa: E402
import scene_mesh as SM  # noqa: E402
from planner.scene import Camera  # noqa: E402

HALL = {'w': 153, 'd': 620, 'openings': [{'kind': 'door', 'wall': 'south', 'offset_cm': 31, 'width_cm': 90, 'swing_cm': 0},
                                         {'kind': 'door', 'wall': 'north', 'offset_cm': 20, 'width_cm': 70, 'swing_cm': 70}]}
ITEMS = [
    {'role': 'шкаф-купе', 'x': 123.0, 'y': 530.0, 'rot': 270, 'w': 180.0, 'd': 60.0, 'h': 220.0},
    {'role': 'ковёр', 'x': 76.0, 'y': 300.0, 'rot': 0, 'w': 120.0, 'd': 200.0, 'h': 1.0},
    {'role': 'зеркало', 'x': 1.5, 'y': 28.0, 'rot': 90, 'w': 56.0, 'd': 3.0, 'h': 72.0, 'elev': 114.0},
    {'role': 'картина', 'x': 151.5, 'y': 300.0, 'rot': 270, 'w': 50.0, 'd': 2.0, 'h': 70.0, 'elev': 130.0},
]
CAM = Camera(name='C1', eye=(120.0, 150.0, 200.0), target=(0.0, 150.0, 28.0), fov_deg=70.0, width=672, height=448)


def run(preview):
    log = {'rug': [], 'plane': [], 'push': [], 'compile': 0, 'mesh': []}
    o = (DR._paste_rug, DR._paint_wall_plane, DR._push_from_supports, DR.compile_scene)
    o_r = SM.raster_mesh
    # как в выгрузке (`export_scene.py`): растеризатор мешей подменён записью, картинку не рисует
    SM.raster_mesh = lambda img, zbuf, parts, place, cam, W, Hpx, yaw, name2h=None, inst_buf=None, inst_id=0, mirror=False: log['mesh'].append((place.role, round(place.x, 2), round(place.y, 2), place.rot, W, Hpx))
    DR._paste_rug = lambda canvas, zbuf, place, cam, W, H, ph: log['rug'].append((place.role, round(place.x, 2), round(place.y, 2), place.rot, W, H)) or True
    DR._paint_wall_plane = lambda canvas, zbuf, place, cam, W, H, mirror, ph=None: log['plane'].append((place.role, round(place.x, 2), round(place.y, 2), bool(mirror), W, H)) or True

    def push(mp, others, room):
        r = o[2](mp, others, room)
        log['push'].append((len(mp), len(others), r))
        return r

    def comp(*a, **k):
        log['compile'] += 1
        return o[3](*a, **k)
    DR._push_from_supports, DR.compile_scene = push, comp
    try:
        room, placements, _ = DR.scene_from_request({'room': HALL, 'items': ITEMS})
        img, diag = DR.scene3d_frame(room, placements, CAM, {}, {}, preview=preview)
    finally:
        DR._paste_rug, DR._paint_wall_plane, DR._push_from_supports, DR.compile_scene = o
        SM.raster_mesh = o_r
    return img, diag, log


img1, diag1, log1 = run(True)
img0, diag0, log0 = run(False)
check('с превью — картинка кадра, clay-сцена строилась', img1 is not None and log1['compile'] == 1)
check('без превью — картинки нет, clay-сцена не строилась', img0 is None and log0['compile'] == 0)
check('отбор предметов (мешей/clay) тот же', diag0 == diag1, f'{diag0} vs {diag1}')
check('вызовы записчиков мешей, ковра и плоскостей — те же, с теми же размерами кадра', log0['rug'] == log1['rug'] and log0['plane'] == log1['plane'] and log0['mesh'] == log1['mesh'] and log0['plane'] and log0['mesh'], f'{log0} vs {log1}')
check('разведение коллизий выполняется и без превью', log0['push'] == log1['push'] and len(log0['push']) == 2, str(log0['push']))
print('итого:', 'OK' if not fails else f'ПРОВАЛЕНО {fails}')
sys.exit(1 if fails else 0)

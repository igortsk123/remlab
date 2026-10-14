"""Вырез стены на серверном кадре (план demo-04 п.3): стена вокруг проёма — прямоугольниками, как в браузере
(`lib/viewer3d/rooms.ts:wallRects`), за проёмом — плоскость «снаружи». Силуэт проёма на всех четырёх стенах (north/west
зеркалят отступ) совпадает с проекцией выреза из общего описания с допуском 1 px. Описания берём из эталона, который
строит браузерный генератор (`tests/fixtures/opening-golden.json`, `tools/assets/opening_golden.py`)."""
import json
import os

import numpy as np

from planner.models import Room
from planner.scene import SEMANTIC, Camera, _project, compile_scene, wall_rects

GOLDEN = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tests', 'fixtures', 'opening-golden.json')


def _cases():
    return [c for c in json.load(open(GOLDEN, encoding='utf-8'))['cases'] if not c['open']]


def _wall_point(w, d, wall, u, v):
    # тот же отсчёт u, что у браузера (`rooms.ts:frameOf`): south — от запада, north — от востока, west — от севера, east — от юга
    return {'south': (u, v, 0.0), 'north': (w - u, v, d), 'west': (0.0, v, d - u), 'east': (w, v, u)}[wall]


def test_wall_rects_like_browser():
    # окно 50..170 с подоконником 85 и верхом 225 на стене 400×270 — те же куски, что у `rooms.ts:wallRects`
    rects = wall_rects(400, 270, [(50, 170, 85, 225)])
    assert rects == [(0.0, 50, 0.0, 270), (50, 170, 0.0, 85), (50, 170, 225, 270), (170, 400, 0.0, 270)]
    assert wall_rects(400, 270, [(0, 90, 0, 205)]) == [(0, 90, 205, 270), (90, 400, 0.0, 270)]   # дверь у угла


def test_cut_silhouette_on_every_wall():
    walls = set()
    for c in _cases():
        w, d = c['room']['w'], c['room']['d']
        irs = [{'wall': o['wall'], 'ir': {'kind': o['kind'], 'cut': o['cut']}} for o in c['openings']]
        room = Room(width_cm=w, depth_cm=d, openings_ir=irs)
        wall = c['openings'][0]['wall']
        walls.add(wall)
        tgt = _wall_point(w, d, wall, (w if wall in ('north', 'south') else d) / 2, 140.0)
        opp = {'south': (w / 2, 140.0, d - 20), 'north': (w / 2, 140.0, 20.0), 'west': (w - 20, 140.0, d / 2),
               'east': (20.0, 140.0, d / 2)}[wall]
        cam = Camera(name='t', eye=opp, target=tgt, fov_deg=90)
        sc = compile_scene(room, [], cam)
        for o in c['openings']:
            cut = o['cut']
            top = min(cut['top'], 270.0)
            corners = np.array([_wall_point(w, d, wall, u, v) for u in (cut['u0'], cut['u1'])
                                for v in (cut['bottom'], top)], float)
            u, v, _ = _project(cam, corners)
            sem_id = SEMANTIC['window' if o['kind'] in ('window', 'balcony') else 'door']
            # маска своего проёма — внутри его проекции (на стене два проёма разных видов или далеко друг от друга)
            x0, x1, y0, y1 = int(np.floor(u.min())), int(np.ceil(u.max())), int(np.floor(v.min())), int(np.ceil(v.max()))
            sub = sc['semantic'][max(0, y0 - 3):y1 + 3, max(0, x0 - 3):x1 + 3] == sem_id
            ys, xs = np.nonzero(sub)
            assert len(xs), f"{c['name']}: проём {o['kind']} не вырезан"
            got = (xs.min() + max(0, x0 - 3), xs.max() + max(0, x0 - 3), ys.min() + max(0, y0 - 3), ys.max() + max(0, y0 - 3))
            want = (u.min(), u.max(), v.min(), v.max())
            for g, wv, name in zip(got, want, ('лево', 'право', 'верх', 'низ')):
                assert abs(g - wv) <= 1.5, f"{c['name']} {o['kind']}: край «{name}» {g} против {wv:.1f}"
            # за проёмом — дальше стены: рама и стекло из описания встанут перед этой плоскостью
            cy, cx = int((v.min() + v.max()) / 2), int((u.min() + u.max()) / 2)
            dist = float(np.dot(np.array(tgt) - np.array(opp), cam.basis()[1]))
            assert sc['depth'][cy, cx] > dist + 5, f"{c['name']} {o['kind']}: за вырезом стена"
    assert walls == {'south', 'north', 'west', 'east'}


def test_no_ir_wall_stays_whole():
    room = Room(width_cm=400, depth_cm=300)
    cam = Camera(name='t', eye=(200.0, 140.0, 280.0), target=(200.0, 140.0, 0.0), fov_deg=90)
    sem = compile_scene(room, [], cam)['semantic']
    assert not (sem == SEMANTIC['window']).any() and not (sem == SEMANTIC['door']).any()

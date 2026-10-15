"""Цвет стены и пола на серверном кадре = паспорт отделки (план demo-04, критерий ΔE ≤ 5 в калибровочном режиме: без света,
тона по глубине и контуров). Браузерная сторона — тот же паспорт в материалах (`tests/unit/demo-scene.test.ts`)."""
import json
import os

import numpy as np

from planner.models import Room
from planner.scene import SEMANTIC, Camera, clay_render, compile_scene

GOLDEN = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'tests', 'fixtures', 'opening-golden.json')


def _lab(rgb):
    c = np.asarray(rgb, float) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    xyz = c @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz = xyz / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.array([116 * f[1] - 16, 500 * (f[0] - f[1]), 200 * (f[1] - f[2])])


def _hex(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def test_wall_and_floor_match_passport():
    case = [c for c in json.load(open(GOLDEN, encoding='utf-8'))['cases'] if c['name'] == 'south'][0]
    irs = [{'wall': o['wall'], 'ir': {'kind': o['kind'], 'cut': o['cut']}} for o in case['openings']]
    finish = {'wall': {'colorHex': '#e8e2d6'}, 'floor': {'colorHex': '#a07850'}, 'ceiling': {'colorHex': '#fafafa'}}
    room = Room(width_cm=case['room']['w'], depth_cm=case['room']['d'], openings_ir=irs, finish=finish)
    cam = Camera(name='t', eye=(200.0, 135.0, 280.0), target=(200.0, 110.0, 0.0), fov_deg=72)
    out = compile_scene(room, [], cam)
    out['calibrate'] = True
    img = clay_render(out).reshape(-1, 3).astype(float)
    sem = out['semantic'].reshape(-1)
    for name in ('wall', 'floor'):
        med = np.median(img[sem == SEMANTIC[name]], axis=0)
        de = float(np.linalg.norm(_lab(med) - _lab(_hex(finish[name]['colorHex']))))
        assert de <= 5, f'{name}: ΔE {de:.1f} между кадром {med} и паспортом {finish[name]["colorHex"]}'


def test_without_passport_frame_keeps_browser_defaults():
    case = [c for c in json.load(open(GOLDEN, encoding='utf-8'))['cases'] if c['name'] == 'south'][0]
    irs = [{'wall': o['wall'], 'ir': {'kind': o['kind'], 'cut': o['cut']}} for o in case['openings']]
    room = Room(width_cm=400, depth_cm=300, openings_ir=irs)
    cam = Camera(name='t', eye=(200.0, 135.0, 280.0), target=(200.0, 110.0, 0.0), fov_deg=72)
    out = compile_scene(room, [], cam)
    out['calibrate'] = True
    img = clay_render(out).reshape(-1, 3).astype(float)
    med = np.median(img[out['semantic'].reshape(-1) == SEMANTIC['wall']], axis=0)
    assert np.linalg.norm(_lab(med) - _lab(_hex('#f2f0ed'))) <= 5   # `finish-passport.ts:DEFAULT_FINISH.wall`

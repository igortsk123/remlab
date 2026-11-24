"""T-20261124-18 шаг 3: развязка наклона оси камеры и el (pose_fit.cam_tilt / project / vertical_axis). Без тяжёлого: python tools/scout/salad/trellis/tests_pose_vertical.py"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import pose_fit as PF  # noqa: E402

CAM = {'az': 154.3, 'el': 3.6, 'd': 2.3, 'f': 1.97, 'cx': 0.512, 'cy': 0.487}
RNG = np.random.default_rng(7)
PTS = RNG.uniform(-0.5, 0.5, (400, 3))


def _old_project(P, cam):
    a, e = np.radians(cam['az']), np.radians(cam['el'])
    C = cam['d'] * np.array([np.sin(a) * np.cos(e), np.sin(e), np.cos(a) * np.cos(e)])
    fwd = -C / cam['d']
    right = np.array([np.cos(a), 0.0, -np.sin(a)])
    up = np.cross(right, fwd)
    rel = P - C
    Z = rel @ fwd
    return cam['cx'] + cam['f'] * (rel @ right) / Z, cam['cy'] - cam['f'] * (rel @ up) / Z, Z


def test_project_without_vk_is_old():
    x, y, Z = PF.project(PTS, CAM)
    xo, yo, Zo = _old_project(PTS, CAM)
    assert np.array_equal(x, xo) and np.array_equal(y, yo) and np.array_equal(Z, Zo), 'без vk проекция должна быть прежней побитово'


def test_vk_equal_look_at_is_old():
    cam = {**CAM, 'vk': float(np.tan(np.radians(CAM['el'])) / CAM['f'])}          # наклон оси = el → «взгляд в центр»
    assert abs(PF.cam_tilt(cam)) < 1e-9
    x, y, _ = PF.project(PTS, cam)
    xo, yo, _ = _old_project(PTS, CAM)
    assert np.allclose(x, xo, atol=1e-12) and np.allclose(y, yo, atol=1e-12)


def test_vk_zero_straightens_verticals_and_keeps_center():
    cam = {**CAM, 'vk': 0.0}
    assert abs(PF.cam_tilt(cam) - CAM['el']) < 1e-9
    for xw in (-0.3, 0.0, 0.3):                                                     # вертикали параллельны при любом x и любой глубине
        P = np.array([[xw, -0.2, 0.1], [xw, 0.25, 0.1]])
        x, y, _ = PF.project(P, cam)
        assert abs(x[1] - x[0]) < 1e-9, (xw, x)
    x, y, _ = PF.project(np.zeros((1, 3)), cam)                                     # центр предмета остаётся в (cx, cy)
    assert abs(x[0] - CAM['cx']) < 1e-9 and abs(y[0] - CAM['cy']) < 1e-9, (x, y)
    xo, yo, _ = PF.project(PTS, CAM)                                                # прежняя камера: вертикали сходятся
    P = np.array([[0.3, -0.2, 0.1], [0.3, 0.25, 0.1]])
    xs, _, _ = PF.project(P, CAM)
    assert abs(xs[1] - xs[0]) > 1e-4


def test_pixel_attrs_use_tilt():
    cam = {**CAM, 'vk': 0.0}
    C, right, up, fwd = PF.cam_basis(cam['az'], cam['el'], cam['d'], PF.cam_tilt(cam))
    assert abs(fwd[1]) < 1e-9, 'ось горизонтальна'
    assert abs(np.dot(right, up)) < 1e-9 and abs(np.dot(fwd, up)) < 1e-9


def _photo(kappa, nlines=9, lines=True):
    import cv2
    H, W = 800, 600
    img = np.full((H, W, 4), 0, np.uint8)
    img[100:700, 150:450, :3] = 200
    img[100:700, 150:450, 3] = 255
    cv = PF.photo_canvas(img[..., 3] > 127)
    if lines:
        for xp in np.linspace(180, 420, nlines):
            xf = (xp - cv['x0']) / cv['side']
            t = kappa * (0.5 - xf)                                                  # tilt(x) = −κ·(x − 0,5): b = −κ
            dx, dy = np.sin(t) * 220, np.cos(t) * 220
            cv2.line(img, (int(round(xp - dx)), int(round(400 - dy))), (int(round(xp + dx)), int(round(400 + dy))), (40, 40, 40, 255), 3, cv2.LINE_AA)
    return img, cv


def test_vertical_axis_parallel():
    img, cv = _photo(0.0)
    r = PF.vertical_axis(img, img[..., 3] > 127, cv)
    assert r['measured'] and abs(r['kappa']) < 0.004, r


def test_vertical_axis_converging():
    for k in (0.03, -0.03):
        img, cv = _photo(k)
        r = PF.vertical_axis(img, img[..., 3] > 127, cv)
        assert r['measured'] and abs(r['kappa'] - k) < 0.25 * abs(k) + 0.004, (k, r)


def test_vertical_axis_parallel_flag():
    img, cv = _photo(0.0)
    r = PF.vertical_axis(img, img[..., 3] > 127, cv)
    assert r['parallel'] and abs(r['conv_deg']) <= 0.3, r
    img, cv = _photo(0.03)
    r = PF.vertical_axis(img, img[..., 3] > 127, cv)
    assert not r['parallel'] and abs(r['conv_deg']) > 0.3, r


def test_vertical_axis_no_lines_not_measured():
    img, cv = _photo(0.0, lines=False)
    r = PF.vertical_axis(img, img[..., 3] > 127, cv)
    assert not r['measured'] and r['kappa'] is None and r['reason'], r


if __name__ == '__main__':
    for n, f in sorted(globals().items()):
        if n.startswith('test_') and callable(f):
            f()
            print('ok', n)
    print('все проверки пройдены')

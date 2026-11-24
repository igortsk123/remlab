"""T-20261124-18: стык «фронт|бок» (junction.py) — мерка и спасатель на синтетическом ящике. Без тяжёлого: python tools/scout/salad/trellis/tests_junction.py"""
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))
import junction as J  # noqa: E402
import pose_fit as PF  # noqa: E402

LO, HI = np.array([-0.44, -0.5, -0.13]), np.array([0.44, 0.5, 0.13])        # коробчатая форма 0,88 × 1,0 × 0,26 (Монблан)
TRUE = {'az': 20.0, 'el': 3.0, 'd': 3.0, 'f': 2.4, 'cx': 0.5, 'cy': 0.5}
S = 800
CV = {'x0': 0.0, 'y0': 0.0, 'side': float(S)}
N = 256


def _face(axis, val, other):
    a, b = np.meshgrid(np.linspace(LO[other[0]], HI[other[0]], 220), np.linspace(LO[other[1]], HI[other[1]], 220))
    P = np.zeros((a.size, 3))
    P[:, axis] = val
    P[:, other[0]] = a.ravel()
    P[:, other[1]] = b.ravel()
    return P


def _photo(cam):
    """Ящик с камеры: фронт (z = +hi, тон 150) и видимая боковина (x = ±hi, тон 205) на светлом фоне; альфа — объединение."""
    C = PF.cam_basis(cam['az'], cam['el'], cam['d'])[0]
    img = np.full((S, S, 3), 235, np.uint8)
    al = np.zeros((S, S), np.uint8)
    faces = [(_face(2, HI[2] if C[2] > 0 else LO[2], (0, 1)), 150)]
    if abs(C[0]) > 0.05:                                                            # камера по x внутри габарита — боковина не видна
        faces.append((_face(0, HI[0] if C[0] > 0 else LO[0], (2, 1)), 205))
    for P, tone in faces:
        m = PF.splat_mask(P, cam, S)
        m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8)) > 0
        img[m] = tone
        al[m] = 255
    return np.dstack([img, al])


def test_box_geometry():
    g = J.box_geometry(LO, HI)
    assert g['boxy'] and g['depth_axis'] == 2 and g['width_axis'] == 0 and abs(g['aspect'] - 0.88 / 0.26) < 0.01
    g2 = J.box_geometry(np.array([-0.3, -0.5, -0.3]), np.array([0.3, 0.5, 0.3]))
    assert not g2['boxy'], g2


def test_gap_small_at_true_camera():
    photo = _photo(TRUE)
    tg = J.photo_targets(photo)
    fe = J.front_edge(PF, TRUE, J.box_geometry(LO, HI), CV, tg)
    assert fe['measured'] and fe['has_edge'] and fe['gap_px'] <= 3.0, fe
    assert fe['kind']['l'] == 'кромка' or fe['kind']['r'] == 'кромка'


def test_gap_large_at_wrong_camera():
    photo = _photo(TRUE)
    tg = J.photo_targets(photo)
    wrong = {**TRUE, 'az': -20.0}                                                  # зеркальный ракурс: боковина с другой стороны
    fe = J.front_edge(PF, wrong, J.box_geometry(LO, HI), CV, tg)
    assert fe['measured'] and fe['gap_px'] > 20.0, fe


def test_not_boxy_not_measured():
    photo = _photo(TRUE)
    tg = J.photo_targets(photo)
    fe = J.front_edge(PF, TRUE, J.box_geometry(np.array([-0.3, -0.5, -0.3]), np.array([0.3, 0.5, 0.3])), CV, tg)
    assert not fe['measured'] and fe['reason'], fe
    assert J.overlay(photo, tg, fe).size > 0                                       # кадр «не измерено» рисуется


def test_no_interior_edge_not_measured():
    photo = _photo({**TRUE, 'az': 0.0})                                            # строго спереди: боковины нет, внутренней кромки нет → не измерено, не «прошёл»
    tg = J.photo_targets(photo)
    fe = J.front_edge(PF, {**TRUE, 'az': 0.0}, J.box_geometry(LO, HI), CV, tg)
    assert not fe['measured'] and 'кромки' in fe['reason'], fe


def test_rescue_noop_when_ok():
    photo = _photo(TRUE)
    tg = J.photo_targets(photo)
    Mp = cv2.resize(photo[..., 3], (N, N), interpolation=cv2.INTER_AREA) > 127
    V = np.concatenate([_face(2, HI[2], (0, 1)), _face(2, LO[2], (0, 1)), _face(0, HI[0], (2, 1)), _face(0, LO[0], (2, 1))])
    pick = {'cam': dict(TRUE), 'iou': 0.99}
    p2, info = J.rescue(PF, V, pick, [], J.box_geometry(LO, HI), tg, Mp, N, CV, log=lambda *a: None)
    assert p2 is pick and not info['applied'] and info['tried'] == 0, info          # зазор в норме → камера побитово та же


def test_rescue_heals_wrong_family():
    photo = _photo(TRUE)
    tg = J.photo_targets(photo)
    Mp = cv2.resize(photo[..., 3], (N, N), interpolation=cv2.INTER_AREA) > 127
    V = np.concatenate([_face(2, HI[2], (0, 1)), _face(2, LO[2], (0, 1)), _face(0, HI[0], (2, 1)), _face(0, LO[0], (2, 1))])
    start = {**TRUE, 'az': 4.0, 'd': 2.0, 'f': 1.6}                                # почти фронт d≈2: боковины на форме нет, силуэт близок
    iou0 = PF.iou(PF.splat_mask(V, start, N), Mp)
    p2, info = J.rescue(PF, V, {'cam': start, 'iou': iou0}, [], J.box_geometry(LO, HI), tg, Mp, N, CV, log=lambda *a: None)
    assert info['before']['gap_px'] > 3.0, info['before']
    assert info['healable'] and info['applied'], info
    assert info['after']['gap_px'] <= 3.0 and info['iou_after'] >= iou0 - 0.005, info


def test_rescue_probe_does_not_change_pick():
    photo = _photo(TRUE)
    tg = J.photo_targets(photo)
    Mp = cv2.resize(photo[..., 3], (N, N), interpolation=cv2.INTER_AREA) > 127
    V = np.concatenate([_face(2, HI[2], (0, 1)), _face(2, LO[2], (0, 1)), _face(0, HI[0], (2, 1)), _face(0, LO[0], (2, 1))])
    start = {**TRUE, 'az': 4.0, 'd': 2.0, 'f': 1.6}
    pick = {'cam': start, 'iou': 0.9}
    p2, info = J.rescue(PF, V, pick, [], J.box_geometry(LO, HI), tg, Mp, N, CV, log=lambda *a: None, apply=False)
    assert p2 is pick and not info['applied'] and info['healable'], info


if __name__ == '__main__':
    for n, f in sorted(globals().items()):
        if n.startswith('test_') and callable(f):
            f()
            print('ok', n)
    print('все проверки пройдены')

"""Пустое окно и подпись за краем листа (T-20261110-06): OpenCV 5 на массиве нулевой площади роняет процесс
(connectedComponents* — segfault) или бросает cv2.error — гипотеза должна отказать с причиной, процесс — жить."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
import fpcore as fc  # noqa: E402
import openroom  # noqa: E402
import repair as rp  # noqa: E402

PPM = 20.0
T = 6


def room_with_gap():
    """Комната 3×3 м с проёмом 0,6 м (как test_recompute_closes_missing_room) → (State, Ctx)."""
    H, W = 120, 120
    final = np.zeros((H, W), np.uint8)
    cv2.rectangle(final, (20, 20), (20 + 60 + 2 * T - 1, 20 + 60 + 2 * T - 1), 1, -1)
    final[20 + T:20 + T + 60, 20 + T:20 + T + 60] = 0
    final[20 + T + 24:20 + T + 36, 20:20 + T] = 0
    lab = np.zeros((H, W), np.int32)
    gray = np.full((H, W), 255, np.uint8)
    gray[final > 0] = 0
    st = rp.State(lab, final, [], np.zeros((H, W), np.uint8))
    ctx = rp.Ctx(gray=gray, ev=final > 0, wp=rp.wall_prob(gray), ppm=PPM, t_int=T, fams=[0.0], conv=('p95', 0))
    return st, ctx


@pytest.mark.parametrize('shape', [(0, 5), (5, 0), (0, 0)])
def test_empty_img(shape):
    assert fc.empty_img(np.zeros(shape, np.uint8))
    assert fc.empty_img(np.zeros((4, 4), np.uint8), np.zeros(shape, bool))
    assert not fc.empty_img(np.zeros((1, 1), np.uint8), np.zeros((3, 2), bool))
    assert fc.empty_img(None)


@pytest.mark.parametrize('pt', [(-300.0, 50.0), (50.0, 900.0), (500.0, -1.0), (120.0, 50.0)])
def test_recompute_label_off_sheet_refuses(pt):
    st, ctx = room_with_gap()
    l = rp.Label('Room', pt, (3.0, 3.0))
    for dom in (False, True, 'faint'):
        rp._SKIPS.clear()
        assert rp.hyp_recompute(st, 0, [l], ctx, np.zeros(st.lab.shape, bool), 1.0, dom) is None
        assert rp._SKIPS[-1] == 'точка подписи вне листа'


def test_recompute_zero_width_window_refuses():
    # точка на листе, но окно вырождено (мерка с минусом: half < 0 → окно нулевой ширины)
    st, ctx = room_with_gap()
    l = rp.Label('Room', (56.0, 56.0), (-3.0, -3.0))
    rp._SKIPS.clear()
    assert rp.hyp_recompute(st, 0, [l], ctx, np.zeros(st.lab.shape, bool), 1.0, False) is None
    assert rp._SKIPS[-1] == 'пустое окно'


def test_enclose_label_off_sheet_refuses():
    st, ctx = room_with_gap()
    l = rp.Label('Room', (-400.0, 50.0), (3.0, 3.0))
    for mode in ('box', 'lines'):
        rp._SKIPS.clear()
        assert rp.hyp_enclose(st, 0, [l], ctx, mode) is None
        assert rp._SKIPS[-1] in ('пустое окно', 'подпись вне здания (выноска)')


def test_run_survives_label_off_sheet():
    # весь круг починки с подписью за краем листа: не падает, подпись остаётся «не найдена»
    st, ctx = room_with_gap()
    labels = [rp.Label('Room', (56.0, 56.0), (3.0, 3.0)), rp.Label('Far', (-500.0, 60.0), (4.0, 4.0))]
    st2, journal = rp.run(st, labels, ctx, np.zeros(st.lab.shape, bool), budget_s=10.0)
    t = rp.topology(st2, labels, PPM)
    assert t['own'][1] is None
    assert any(e.get('label') == 'Far' and e.get('why') == 'точка подписи вне листа' for e in journal)


def test_on_sheet_drops_with_reason():
    labels = [rp.Label('In', (10.0, 10.0), (3.0, 3.0)), rp.Label('Out', (10.0, 130.0), (3.0, 3.0)),
              rp.Label('Edge', (119.9, 0.0), None, 'vlm-space'), rp.Label('Neg', (-0.5, 5.0), (2.0, 2.0))]
    keep, off = rp.on_sheet(labels, (120, 120))
    assert [l.name for l in keep] == ['In', 'Edge']
    assert [e['label'] for e in off] == ['Out', 'Neg']
    assert all(e['kind'] == 'skip' and e['why'] == 'точка подписи вне листа панели' for e in off)


def test_empty_window_helpers_do_not_call_opencv():
    z = np.zeros((0, 7), np.uint8)
    assert fc.remove_small(z, 10).shape == (0, 7)
    comp, lab = openroom.seed_component(z.astype(bool), (0, 0), 3)
    assert comp is None and lab.shape == (0, 7)
    assert openroom.attached_lines(z.astype(bool), z).shape == (0, 7)
    for f in (openroom.enclose_box, ):
        assert f(z, z.astype(np.int32), [], z, (0, 0), (3.0, 3.0), PPM, [0.0], 255.0, [], T)[0] is None
    assert openroom.enclose_lines(z, z.astype(np.int32), [], z, (0, 0), (3.0, 3.0), PPM, [0.0], 255.0, [], None)[0] is None
    m, body, thin = rp.protrusion(z.astype(bool), PPM)
    assert m == 0.0 and body is None
    st, ctx = room_with_gap()
    assert rp.pixel_cost(st, ctx, (50, 50, 50, 80)) == 0.0          # окно нулевой ширины

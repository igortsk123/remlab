"""door_evidence после векторизации (T-20261126-169/2): результат побайтно как у эталона до правки (`door_evidence_ref`).

Синтетика: разрывы стены с дугой створки, двойной дугой, створкой-линией, мусором-штриховкой, у края листа, с заштрихованным полом;
все варианты вызова (по умолчанию, want_px, want_how, pure_check=False, wall=…, step_deg). Ускорение — в `tools/floorplan/fpcore.py`
(точки всех положений петли и радиусов одной стороны — одним массивом); вызов с `tangent_only` код не меняет, но тоже сверяется."""
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools' / 'floorplan'))
sys.path.insert(1, str(ROOT / 'tests' / 'floorplan'))
import fpcore as fc  # noqa: E402
from door_evidence_ref import door_evidence_ref  # noqa: E402


def sheet(rng, kind):
    """тонкая графика 260×300 + маска стен + разрыв (c, u, n, L, depth)."""
    H, W = 260, 300
    thin = np.zeros((H, W), np.uint8)
    wall = np.zeros((H, W), np.uint8)
    ang = float(rng.choice([0.0, 90.0, 180.0, 270.0, rng.uniform(0, 360)]))
    a = np.radians(ang)
    u = np.array([np.cos(a), np.sin(a)])
    n = np.array([-u[1], u[0]])
    L = float(rng.uniform(22, 60))
    depth = float(rng.uniform(6, 14))
    c = np.array([rng.uniform(40, W - 40), rng.uniform(40, H - 40)])
    if kind == 'edge':
        c = np.array([rng.uniform(2, 20), rng.uniform(2, 20)])
    p1, p2 = c - u * (L / 2 + 40), c - u * L / 2
    p3, p4 = c + u * L / 2, c + u * (L / 2 + 40)
    for p, q in ((p1, p2), (p3, p4)):
        cv2.line(wall, tuple(int(round(v)) for v in p), tuple(int(round(v)) for v in q), 1, int(depth))
    s = n if rng.random() < 0.5 else -n
    hinge = c - u * L / 2 + s * depth / 2
    if kind in ('arc', 'edge', 'hatch'):
        start = np.degrees(np.arctan2(u[1], u[0]))
        sgn = 1 if (u[0] * s[1] - u[1] * s[0]) > 0 else -1
        a0, a1 = (start, start + 90 * sgn) if sgn > 0 else (start + 90 * sgn, start)
        cv2.ellipse(thin, tuple(int(round(v)) for v in hinge), (int(L), int(L)), 0, a0, a1, 255, 1)
    if kind == 'double':
        for h, d in ((c - u * L / 2 + s * depth / 2, u), (c + u * L / 2 + s * depth / 2, -u)):
            start = np.degrees(np.arctan2(d[1], d[0]))
            sgn = 1 if (d[0] * s[1] - d[1] * s[0]) > 0 else -1
            a0, a1 = (start, start + 90 * sgn) if sgn > 0 else (start + 90 * sgn, start)
            cv2.ellipse(thin, tuple(int(round(v)) for v in h), (int(L / 2), int(L / 2)), 0, a0, a1, 255, 1)
    if kind == 'leaf':
        tip = hinge + s * L
        cv2.line(thin, tuple(int(round(v)) for v in hinge), tuple(int(round(v)) for v in tip), 255, 1)
        start = np.degrees(np.arctan2(u[1], u[0]))
        cv2.ellipse(thin, tuple(int(round(v)) for v in hinge), (int(L), int(L)), 0, start - 45, start + 20, 255, 1)
    if kind == 'junk':
        for _ in range(30):
            p = c + rng.uniform(-L * 1.5, L * 1.5, 2)
            q = p + rng.uniform(-14, 14, 2)
            cv2.line(thin, tuple(int(round(v)) for v in p), tuple(int(round(v)) for v in q), 255, 1)
    if kind == 'hatch':
        for k in range(-300, 300, 6):
            cv2.line(thin, (0, k), (W, k + 120), 255, 1)
    thin |= (wall * 255).astype(np.uint8) if kind == 'wallink' else 0
    return thin, wall, c, u, n, L, depth


KINDS = ['arc', 'arc', 'double', 'leaf', 'junk', 'hatch', 'edge', 'wallink']


@pytest.mark.parametrize('seed', range(16))
def test_door_evidence_vec_equals_reference(seed):
    rng = np.random.default_rng(1000 + seed)
    thin, wall, c, u, n, L, depth = sheet(rng, KINDS[seed % len(KINDS)])
    for kw in ({}, {'want_px': True}, {'want_how': True}, {'pure_check': False}, {'wall': wall}, {'wall': wall, 'want_how': True},
               {'step_deg': 10}, {'tangent_only': True}):
        ref = door_evidence_ref(thin, c, u, n, L, depth, **kw)
        new = fc.door_evidence(thin, c, u, n, L, depth, **kw)
        assert new == ref and type(new) is type(ref), (seed, kw, ref, new)


def test_door_evidence_vec_finds_a_drawn_arc():
    """смысл не потерян: нарисованная дуга двери даёт высокую долю, пустой разрыв — нулевую."""
    rng = np.random.default_rng(5)
    thin, wall, c, u, n, L, depth = sheet(rng, 'arc')
    assert fc.door_evidence(thin, c, u, n, L, depth) >= 0.75
    empty = np.zeros_like(thin)
    assert fc.door_evidence(empty, c, u, n, L, depth) == 0.0

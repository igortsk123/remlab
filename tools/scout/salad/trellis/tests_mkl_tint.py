#!/usr/bin/env python3
"""Тесты MKL-переноса цвета (`mkl_tint.py`, T-20261119-88) на синтетике: ковариация источника становится ковариацией цели, среднее совпадает, маска уважается, кластерный режим, L* и гамма.

  python tools/scout/salad/trellis/tests_mkl_tint.py   # numpy, scipy, opencv, pillow
"""
from __future__ import annotations

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkl_tint as M  # noqa: E402


def _cloud(seed, mean, cov, n=20000):
    return np.random.RandomState(seed).multivariate_normal(mean, cov, n)


def t_covariance_matches():
    src = _cloud(1, [50, 5, 10], [[100, 20, -10], [20, 30, 5], [-10, 5, 20]])
    ref = _cloud(2, [62, -3, 25], [[40, -8, 6], [-8, 60, 12], [6, 12, 45]])
    Tm, ms, mr = M.mkl_transform(src, ref)
    out = (src - ms) @ Tm.T + mr
    assert np.abs(out.mean(0) - ref.mean(0)).max() < 1e-6                                    # среднее = среднее цели
    assert np.abs(np.cov(out.T) - np.cov(ref.T)).max() < 0.05 * np.abs(np.cov(ref.T)).max()  # ковариация = ковариация цели (до EPS)
    assert np.abs(Tm - Tm.T).max() < 1e-9                                                     # T симметрична (форма Pitié)


def t_identity_when_same():
    x = _cloud(3, [50, 0, 0], np.diag([80, 20, 20]))
    Tm, ms, mr = M.mkl_transform(x, x)
    assert np.abs(Tm - np.eye(3)).max() < 1e-3 and np.abs(ms - mr).max() < 1e-9


def _tex(n=64, rgb=(180, 120, 80)):
    t = np.zeros((n, n, 3), np.uint8)
    t[...] = rgb
    t += np.random.RandomState(5).randint(0, 12, t.shape).astype(np.uint8)
    return t


def t_apply_all_moves_mean_to_target():
    import pattern_metric as PM
    tex = _tex()
    lab = PM.rgb_to_lab(tex).reshape(-1, 3).astype(np.float64)
    tgt = _cloud(4, [lab[:, 0].mean() + 8, lab[:, 1].mean() - 6, lab[:, 2].mean() - 10], np.diag([30, 10, 10]), 5000)
    tr = M.mkl_transform(lab, tgt)
    new, info = M.apply_mkl(tex, [tr])
    lab2 = PM.rgb_to_lab(new).reshape(-1, 3)
    assert np.abs(lab2.mean(0) - tgt.mean(0)).max() < 2.0, (lab2.mean(0), tgt.mean(0))      # допуск — округление в 8 бит и гамма
    assert 'dL_texels' in info and info['gamut_clipped_share'] < 0.2


def t_mask_is_respected():
    """Статистики берутся только по маске: фон (чёрный) в маску не входит и на преобразование не влияет."""
    import pattern_metric as PM
    n = 64
    tex = _tex(n)
    lab_t = PM.rgb_to_lab(tex).astype(np.float64)
    frame_r = np.zeros((n, n, 3), np.float64)
    frame_r[:] = lab_t
    frame_r[:32] = (0.0, 0.0, 0.0)                                                    # верхняя половина «фон» с нулевым Lab
    mask = np.zeros((n, n), bool)
    mask[32:] = True
    ys, xs = np.nonzero(mask)
    with_mask = M.mkl_transform(frame_r[ys, xs], frame_r[ys, xs] + [5, 0, 0])
    no_mask = M.mkl_transform(frame_r.reshape(-1, 3), frame_r.reshape(-1, 3) + [5, 0, 0])
    assert np.abs(with_mask[1] - lab_t[32:].reshape(-1, 3).mean(0)).max() < 1e-6, 'среднее источника только по маске'
    assert np.abs(with_mask[1] - no_mask[1]).max() > 5, 'без маски среднее тянет фон — тест должен это видеть'


def t_clusters_blend_two_materials():
    """Два материала с разными целями: кластерный режим сдвигает каждый к своей цели, режим «всё» — оба к общей."""
    import a1_tone as A
    import pattern_metric as PM
    n = 64
    tex = np.zeros((n, n, 3), np.uint8)
    tex[:32] = (200, 140, 90)            # тёплое дерево (верхняя половина)
    tex[32:] = (90, 100, 140)            # холодная ткань (нижняя половина)
    lab = PM.rgb_to_lab(tex).reshape(-1, 3).astype(np.float64)
    cent = A.find_clusters(lab[:, 1:])
    assert len(cent) == 2, cent
    lab_l, lab_r = lab[: len(lab) // 2], lab[len(lab) // 2:]
    # цель: верхний материал светлее на 6, нижний темнее на 6 (с небольшим разбросом, чтобы ковариации были невырожденными)
    tl = lab_l + np.random.RandomState(1).randn(*lab_l.shape) * [1.0, 0.5, 0.5] + [6, 0, 0]
    tr_ = lab_r + np.random.RandomState(2).randn(*lab_r.shape) * [1.0, 0.5, 0.5] + [-6, 0, 0]
    trs = []
    for k in range(2):
        mine_l, mine_r = (lab_l, tl) if np.linalg.norm(lab_l.mean(0)[1:] - cent[k]) < np.linalg.norm(lab_r.mean(0)[1:] - cent[k]) else (lab_r, tr_)
        trs.append(M.mkl_transform(mine_l + np.random.RandomState(9).randn(*mine_l.shape) * [1.0, 0.5, 0.5], mine_r))
    new, _ = M.apply_mkl(tex, trs, cent)
    l0 = PM.rgb_to_lab(tex)[..., 0]
    l1 = PM.rgb_to_lab(new)[..., 0]
    assert abs(float((l1[:32] - l0[:32]).mean()) - 6) < 1.5, (l1[:32] - l0[:32]).mean()
    assert abs(float((l1[32:] - l0[32:]).mean()) + 6) < 1.5, (l1[32:] - l0[32:]).mean()


def main() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith('t_') and callable(v)]
    for t in tests:
        t()
        print('ok', t.__name__)
    print('all ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())

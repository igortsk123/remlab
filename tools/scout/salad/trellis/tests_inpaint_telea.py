#!/usr/bin/env python3
"""Тесты `inpaint_telea.py` на синтетике (T-20261119-88): тексели вне маски не меняются, дыра заполняется цветом окружения, маска из карты заливки читается верно.

  python tools/scout/salad/trellis/tests_inpaint_telea.py   # numpy, opencv, pillow
"""
from __future__ import annotations

import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import inpaint_telea as I  # noqa: E402


def t_hole_filled_outside_untouched():
    tex = np.zeros((64, 64, 3), np.uint8)
    tex[...] = (200, 150, 100)
    hole = np.zeros((64, 64), bool)
    hole[24:40, 24:40] = True
    tex[hole] = (0, 0, 0)                                           # «чёрная россыпь»
    out = I.telea(tex, hole, 3)
    assert (out[~hole] == tex[~hole]).all(), 'вне маски ничего не меняется'
    assert np.abs(out[hole].astype(int) - np.array([200, 150, 100])).max() <= 8, out[32, 32]


def t_mask_from_fillmap():
    from PIL import Image
    im = np.full((8, 8, 3), 90, np.uint8)
    im[1, 1] = (255, 0, 0)      # залито
    im[2, 2] = (255, 220, 0)    # смешано
    im[3, 3] = (0, 90, 255)     # отказ — не маска
    d = tempfile.mkdtemp()
    p = os.path.join(d, 'f.png')
    Image.fromarray(im).save(p)
    m = I.mask_from_fillmap(p)
    assert m[1, 1] and m[2, 2] and not m[3, 3] and m.sum() == 2


def main() -> int:
    for t in (t_hole_filled_outside_untouched, t_mask_from_fillmap):
        t()
        print('ok', t.__name__)
    print('all ok')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Карта «номер кирпича» (`material_from_cc0.brick_ids`, разнотон кладки в рендере): шов — 0, кирпич — один номер, а кирпич, разрезанный краем
бесшовного тайла, получает ОДИН номер с обеих сторон. Запуск: ~/venvs/scout/bin/python tools/assets/tests/test_brick_ids.py"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import material_from_cc0 as C  # noqa: E402

h = np.zeros((60, 100), np.uint8)
h[5:25, 10:45] = 200      # кирпич целиком
h[5:25, 55:90] = 200      # второй
h[35:55, 0:20] = 200      # разрезан краем тайла: левая часть
h[35:55, 80:100] = 200    # и правая — один кирпич
ids = C.brick_ids(h, seed=3)
assert ids.shape == h.shape and ids.dtype == np.uint8
assert ids[0, 0] == 0 and ids[30, 50] == 0, "шов — 0"
a, b, l, r = ids[15, 25], ids[15, 70], ids[45, 5], ids[45, 90]
assert min(a, b, l) >= 40, "кирпич — номер 40..255"
assert l == r, "кирпич через край тайла — один номер"
assert len({int(a), int(b), int(l)}) == 3, "разные кирпичи — разные номера"
print("test_brick_ids: ок")

#!/usr/bin/env python3
"""«Фронт сплошной» (tools/assets/front_continuity.py, T-20261124-18) на заглушках: ровный фронт проходит; полоса чужого тона ≥5 % ширины (вертикальная и горизонтальная) и тёмные пятна валят; тонкий шов 1 % проходит;
то, что есть и на фото (ящик другой отделки), разрывом не считается; в коде чисел порогов нет (data/flat3d/front-continuity.json). Запуск: python tools/assets/tests/test_front_continuity.py (numpy + scipy + Pillow)"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, '..')
sys.path.insert(0, ASSETS)
import numpy as np  # noqa: E402
import front_continuity as FC  # noqa: E402

FAIL = 0
RNG = np.random.default_rng(11)


def ok(c, msg):
    global FAIL
    print(('ok   ' if c else 'FAIL ') + msg)
    if not c:
        FAIL += 1


N = 420
M = np.zeros((N, N), bool); M[40:400, 60:360] = True


def front(tone=(120, 128, 130)):
    img = np.full((N, N, 3), 255, np.uint8)
    img[M] = np.clip(np.array(tone) + RNG.normal(0, 2, (int(M.sum()), 3)), 0, 255).astype(np.uint8)
    return img


def strip(img, orient, pct, dL=-55):
    out = img.copy(); m = np.zeros((N, N), bool)
    if orient == 'v':
        w = max(1, int(300 * pct / 100)); a = 60 + 150 - w // 2; m[40:400, a:a + w] = True
    else:
        w = max(1, int(360 * pct / 100)); a = 40 + 180 - w // 2; m[a:a + w, 60:360] = True
    m &= M
    out[m] = np.clip(out[m].astype(int) + dL, 0, 255)
    return out


def blots(img, n=40):
    out = img.copy(); ys, xs = np.mgrid[0:N, 0:N]
    for _ in range(n):
        cy, cx = int(RNG.integers(70, 370)), int(RNG.integers(90, 330))
        m = ((ys - cy) ** 2 + (xs - cx) ** 2 < 6 ** 2) & M
        out[m] = np.clip(out[m].astype(int) - 40, 0, 255)
    return out


P = FC.load_rules()
base = front()
r0 = FC.front_continuity(base, M, base, M)
ok(r0['ok'] is True and r0['r'] <= 1, f"ровный фронт проходит (r={r0['r']})")
r0n = FC.front_continuity(base, M)
ok(r0n['ok'] is True, 'без фото ровный фронт тоже проходит')
for orient, nm in (('v', 'вертикальная'), ('h', 'горизонтальная')):
    for pct in (5, 8):
        r = FC.front_continuity(strip(base, orient, pct), M, base, M)
        ok(r['ok'] is False, f"{nm} полоса чужого тона {pct} % ширины фронта валит (r={r['r']}, {r['why']})")
    r = FC.front_continuity(strip(base, orient, 1), M, base, M)
    ok(r['ok'] is True, f"{nm} тонкий шов 1 % проходит (r={r['r']})")
    sb = strip(base, orient, 8)
    r = FC.front_continuity(sb, M, sb, M)
    ok(r['ok'] is True, f"{nm} полоса 8 %, которая есть и на фото (ящик другой отделки), не разрыв (r={r['r']})")
def chroma_strip(img, pct):
    out = img.copy(); w = max(1, int(300 * pct / 100)); a = 60 + 150 - w // 2; m = np.zeros((N, N), bool); m[40:400, a:a + w] = True; m &= M
    out[m] = np.clip(out[m].astype(int) + np.array([45, 0, -45]), 0, 255)                   # тон другой по цвету, яркость почти та же: пятнами не поймать — только полосой
    return out


rc = FC.front_continuity(chroma_strip(base, 8), M, base, M)
ok(rc['ok'] is False and rc['why'].startswith('полоса') and rc['strip']['run_pct'] > 0, f"полоса другого ЦВЕТА при той же яркости 8 % валит именно как полоса (run {rc['strip']['run_pct']} %, r={rc['r']})")
rc1 = FC.front_continuity(chroma_strip(base, 1), M, base, M)
ok(rc1['ok'] is True, f"тонкий шов другого цвета 1 % проходит (r={rc1['r']})")
rb = FC.front_continuity(blots(base), M, base, M)
ok(rb['ok'] is False and rb['spot']['excess_pct'] > P['spot_excess_pct'], f"тёмные пятна (как ромбы ISLAND) валят: превышение {rb['spot']['excess_pct']} п.п. > {P['spot_excess_pct']}")
rs = FC.front_continuity(base, np.zeros((N, N), bool))
ok(rs['ok'] is None, 'пустая маска — «не измерено», а не ✓')
src = open(os.path.join(ASSETS, 'front_continuity.py'), encoding='utf-8').read()
ok(not re.search(r'112923_|99272_|114667_', src), 'в коде нет ID товаров')
nums = [x for x in re.findall(r'(?<![\w.\[])\d+\.\d+(?![\w])', re.sub(r'#.*|\"\"\"[\s\S]*?\"\"\"', '', src))]
nums = [x for x in nums if x not in ('0.0', '1.0', '100.0')]                       # 0, 1 и 100 % — не пороги, а границы шкалы
ok(not nums, f'в коде нет дробных порогов: {nums}')
print('FAIL' if FAIL else 'OK', FAIL)
sys.exit(1 if FAIL else 0)

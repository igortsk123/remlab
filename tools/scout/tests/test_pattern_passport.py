#!/usr/bin/env python3
"""T-99/12 шаг 1: «паспорт рисунка» (Fable 19 §2) — pattern_passport.py. Синтетика, ID товаров нет.
Запуск: python tools/scout/tests/test_pattern_passport.py   (numpy, opencv)"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import pattern_passport as PP  # noqa: E402

FAILS = []


def ok(cond, msg):
    print(('ok: ' if cond else 'FAIL: ') + msg)
    if not cond:
        FAILS.append(msg)


R = PP.load_rules()
src = open(os.path.join(HERE, '..', 'pattern_passport.py'), encoding='utf-8').read()
ok('112923' not in src, 'в коде нет ID товаров')
ok(R['targets']['clarity'] == 0.8 and R['targets']['stroke'] == 0.6 and R['targets']['coarse'] == 0.6, 'цели Fable 19: 0,8 / 0,6 / 0,6')
PPC = 9.2
H = W = 400
rng = np.random.default_rng(3)
m = np.ones((H, W), bool)


def lines(len_px, sig_across=1.2, amp=10.0):
    """Волокно по горизонтали: шум, вытянутый вдоль x (len_px) и узкий поперёк."""
    n = rng.standard_normal((H, W)).astype(np.float32)
    n = cv2.GaussianBlur(n, (0, 0), sigmaX=len_px, sigmaY=sig_across)
    return 60 + amp * n / n.std()


def blobs(sig_px, amp=10.0):
    n = rng.standard_normal((H, W)).astype(np.float32)
    n = cv2.GaussianBlur(n, (0, 0), sig_px)
    return 60 + amp * n / n.std()


good = lines(40.0)                           # длинные чёткие линии (≈4 см штрих)
dull = blobs(1.0)                            # мелкая рябь без направления
p_g, p_d = PP.passport(good, m, PPC, 0.0, R), PP.passport(dull, m, PPC, 0.0, R)
ok(p_g is not None and p_d is not None, 'паспорт считается на синтетике')
ok(p_g['clarity'] > p_d['clarity'] + 0.2, 'ясность: линии %.2f > рябь %.2f' % (p_g['clarity'], p_d['clarity']))
ok(p_g['stroke_cm'] > 2 * p_d['stroke_cm'], 'штрих: линии %.2f см > рябь %.2f см' % (p_g['stroke_cm'], p_d['stroke_cm']))
ok(p_g['stroke_cm'] > p_g['stroke_across_cm'], 'у линий вдоль длиннее, чем поперёк')
big = blobs(12.0)                            # крупные пятна: σ≈1,3 см
p_b = PP.passport(big, m, PPC, 0.0, R)
ok(p_b['coarse'] > p_d['coarse'] + 0.4, 'доля крупного: пятна %.2f > рябь %.2f' % (p_b['coarse'], p_d['coarse']))
a = PP.dominant_angle(good, cv2.erode(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool), R)[0]
ok(min(a, 180 - a) < 10, 'угол волокна горизонтальных линий ≈ 0° (вышло %.0f°)' % a)
# размеры в сантиметрах: тот же рисунок при вдвое большем масштабе кадра — тот же паспорт в см
big_res = cv2.resize(good, (2 * W, 2 * H), interpolation=cv2.INTER_CUBIC)
p2 = PP.passport(big_res, np.ones((2 * H, 2 * W), bool), 2 * PPC, 0.0, R)
ok(abs(p2['stroke_cm'] - p_g['stroke_cm']) <= max(0.5, 0.35 * p_g['stroke_cm']), 'штрих в см не зависит от разрешения кадра (%.2f и %.2f)' % (p_g['stroke_cm'], p2['stroke_cm']))
# маска: мало пикселей → None, не «ок»
ok(PP.passport(good, np.zeros((H, W), bool), PPC, 0.0, R) is None, 'мало пикселей грани → None')
rt = PP.ratios(p_d, p_g)
v = PP.verdict(rt, R)
ok(v['ok'] is False and not v['parts']['clarity'], 'рябь против линий: вердикт «не ок» по ясности')
ok(PP.verdict(PP.ratios(p_g, p_g), R)['ok'] is True, 'образец против себя: все три числа 1,0 → ок')
ok(PP.verdict(None, R)['ok'] is None, 'нет паспорта → None, не «ок»')
ok(PP.distance(p_g, p_g, R) == 0.0 and PP.distance(p_g, p_d, R) > 0.5, 'расстояние паспортов: 0 с собой, заметное с рябью')
print('ИТОГО: %d провалов' % len(FAILS))
sys.exit(1 if FAILS else 0)

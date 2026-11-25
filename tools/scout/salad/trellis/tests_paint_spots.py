#!/usr/bin/env python3
"""Тесты мерки пятен покраски (paint_spots.py, T-20261125-92, цикл 2): синтетика (чисто / пятно / на грани / гладкая белая часть / порог в единицах разброса фото / деталь на ненадёжном / граница групп) и стол r0/r1 (фикстура 2 МБ).
Допуск директора: мерка бракует r0 и r1; не бракует чистую перекладину r1 и белую столешницу; ненадёжное не равно «чисто». Запуск: python tools/scout/salad/trellis/tests_paint_spots.py"""
import os
import re
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE]
import paint_spots as PS  # noqa: E402

FAILS = []


def check(name, cond):
    print(('ok   ' if cond else 'FAIL ') + name)
    if not cond:
        FAILS.append(name)


def _tex(shape, rng, base, amp, sigma):
    """Правдоподобная «текстура»: базовый цвет + сглаженный шум (узор дерева), amp — размах."""
    import cv2
    n = rng.standard_normal(shape[:2]).astype(np.float32)
    n = cv2.GaussianBlur(n, (0, 0), sigma)
    n /= max(float(n.std()), 1e-6)
    return np.clip(np.asarray(base, np.float32)[None, None, :] + amp * n[..., None], 0, 255).astype(np.uint8)


def _scene(amp=6.0, seed=3, size=300):
    rng = np.random.default_rng(seed)
    P = _tex((size, size, 3), rng, (180, 150, 120), amp, 2.0)
    A = np.clip(P.astype(np.float32) + rng.standard_normal(P.shape).astype(np.float32) * 1.0, 0, 255).astype(np.uint8)     # альбедо повторяет фото с небольшой разницей
    valid = np.zeros((size, size), bool)
    valid[20:-20, 20:-20] = True
    return A, P, valid, np.zeros((size, size), np.int32)


def _patch(A, x0, y0, x1, y1, dv):
    B = A.copy().astype(np.int16)
    B[y0:y1, x0:x1] += dv
    return np.clip(B, 0, 255).astype(np.uint8)


# --- синтетика, класс 1 «пятно против фото»
A, P, valid, grp = _scene()
r = PS.measure(A, P, valid, grp)
check('чисто: альбедо ≈ фото → вердикт «чисто», брака нет', r['verdict'] == 'чисто' and r['n_bad'] == 0)

Ap = _patch(A, 140, 100, 154, 170, -40)                      # тёмная полоса 14×70 (как пятно у ножки), на фото её нет
r = PS.measure(Ap, P, valid, grp)
check('пятно: тёмная полоса, которой нет на фото → «брак»', r['verdict'] == 'брак' and r['n_bad'] >= 1)
bb = r['spots'][0]['bbox']
check('пятно: габарит найденного места накрывает полосу', bb[0] <= 154 and bb[2] >= 140 and bb[1] <= 170 and bb[3] >= 100)

Af = _patch(A, 140, 100, 154, 170, -40)
Pf_ = _patch(P, 140, 100, 154, 170, -40)                     # то же пятно есть и на фото (настоящий узор) → не брак
r = PS.measure(Af, Pf_, valid, grp)
check('узор есть и на фото (то же место, тот же контраст) → не «брак»', r['verdict'] != 'брак')

# порог в единицах разброса фото: у зернистой фото-части то же пятно слабее по баллу, чем у гладкой
Ag, Pg, valid, grp = _scene(amp=20.0, seed=7)
r_g = PS.measure(_patch(Ag, 140, 100, 154, 170, -25), Pg, valid, grp)
As, Ps, _v, _g = _scene(amp=2.0, seed=7)
r_s = PS.measure(_patch(As, 140, 100, 154, 170, -25), Ps, valid, grp)
check('порог — в единицах разброса фото: то же пятно −25 на зернистой части слабее по баллу, чем на гладкой', r_g['worst_z'] < r_s['worst_z'])
check('гладкая часть: пятно −25 → «брак»', r_s['verdict'] == 'брак')

# белая гладкая часть: шум 1 и пятно
rng = np.random.default_rng(11)
W = np.full((300, 300, 3), 250, np.uint8)
Wp = np.clip(W.astype(np.float32) + rng.standard_normal(W.shape).astype(np.float32) * 0.6, 0, 255).astype(np.uint8)
r = PS.measure(W, Wp, valid, grp)
check('белая столешница: шум фото ±0,6 → «чисто» (пол разброса не даёт ложного брака)', r['verdict'] == 'чисто')
r = PS.measure(_patch(W, 100, 100, 112, 112, -22), Wp, valid, grp)
check('белая столешница: серое пятно 12×12 (−22) → «брак»', r['verdict'] == 'брак')

# на грани: берём пик пятна и ставим порог так, чтобы пик был на 10 % ниже порога
Ap = _patch(A, 140, 100, 154, 170, -40)
A0_, P0_, valid, grp = _scene()
pk = PS.measure(Ap, P0_, valid, grp, {'k': 0.5})['worst_z']      # k малый — только чтобы место попало в список и дало пик
r = PS.measure(Ap, P0_, valid, grp, {'k': pk / 0.9})
check('на грани: пик на 10 %% ниже порога → «на грани» (пик %.2f, k %.2f)' % (pk, pk / 0.9), r['verdict'] == 'на грани' and r['n_bad'] == 0)
r = PS.measure(Ap, P0_, valid, grp, {'k': pk / 0.7})
check('пик на 30 % ниже порога → «чисто»', r['verdict'] == 'чисто')

# вне valid мерка (без vis) не читает кадры
Ax = Ap.copy()
Ax[:20] = 0
Px = P0_.copy()
Px[:, :20] = 255
r1_ = PS.measure(Ap, P0_, valid, grp)
r2_ = PS.measure(Ax, Px, valid, grp)
check('вне valid кадры не читаются: мусор за пределами → тот же худший балл', abs(r1_['worst_z'] - r2_['worst_z']) < 0.3)

# разбиение части по цвету фото
Mx = np.zeros((300, 300, 3), np.uint8)
rng = np.random.default_rng(2)
Mx[:150] = 250
Mx[150:] = _tex((150, 300, 3), rng, (180, 150, 120), 8.0, 2.0)
gg = PS.split_by_color(PS._lab(Mx), np.zeros((300, 300), np.int32), valid, PS.R)
check('одна метка части: белое и дерево делятся на 2 группы по цвету фото', len(np.unique(gg[valid])) == 2)
gg1 = PS.split_by_color(PS._lab(P0_), np.zeros((300, 300), np.int32), valid, PS.R)
check('один цвет — не делится', len(np.unique(gg1[valid])) == 1)

# --- класс 2 «деталь на ненадёжном»: справа полоса, где фото не судья (valid=False, vis=True); тон там должен быть ровным
A, P, valid, grp = _scene(amp=6.0, seed=3)
vis = np.zeros_like(valid)
vis[20:-20, 20:-20] = True
valid = vis.copy()
valid[:, 240:] = False                                          # ненадёжная полоса x ≥ 240
Pj = P.copy()
Pj[:, 240:] = 255                                               # фото в ненадёжном — мусор: на результат влиять не должно
r = PS.measure(A, Pj, valid, grp, vis=vis)
check('класс 2: ровный тон на ненадёжном (как на надёжном) → «чисто», деталей нет', r['verdict'] != 'брак' and r['n_bad_unreliable'] == 0 and r['n_bad'] == 0)
Au = _patch(A, 250, 100, 264, 160, -45)                         # деталь 14×60 на ненадёжной полосе
r = PS.measure(Au, Pj, valid, grp, vis=vis)
check('класс 2: контрастная деталь на ненадёжном (фото там мусор) → «брак», класс «деталь на ненадёжном»', r['verdict'] == 'брак' and r['n_bad_unreliable'] >= 1 and r['n_bad'] == 0)
bb = r['spots_unreliable'][0]['bbox']
check('класс 2: габарит накрывает деталь', bb[0] <= 264 and bb[2] >= 250 and bb[1] <= 160 and bb[3] >= 100)
check('класс 2: доля ненадёжного считается', r['unreliable_px'] > 0 and r['vis_px'] == int(vis.sum()))
r0_ = PS.measure(Au, Pj, valid, grp)                            # без vis класса 2 нет (ненадёжное — «не наблюдаемо», а не «чисто»: поле unreliable_px отсутствует)
check('без vis класс 2 не считается и доля ненадёжного не заявляется', 'unreliable_px' not in r0_ and 'spots_unreliable' not in r0_)

# --- класс 3 «граница групп»: на фото белое (подкладка), в альбедо — дерево
rng = np.random.default_rng(4)
Pb = np.zeros((300, 300, 3), np.uint8)
Pb[:150] = 250
Pb[150:] = _tex((150, 300, 3), rng, (180, 150, 120), 8.0, 2.0)
Ab = Pb.copy()
Ab[120:150, 100:114] = (182, 150, 118)                          # дерево в альбедо там, где на фото белое (рассовмещение границы групп)
vb = np.zeros((300, 300), bool)
vb[20:-20, 20:-20] = True
r = PS.measure(Ab, Pb, vb, np.zeros((300, 300), np.int32))
check('граница групп: белое на фото / дерево в альбедо → отдельный класс, не «пятно»', r['n_bad'] == 0 and len(r['spots_boundary']) >= 1 and r['spots_boundary'][0]['group_mismatch_share'] >= 0.5)
Ab2 = Pb.copy()
Ab2[200:215, 100:150] = np.clip(Ab2[200:215, 100:150].astype(np.int16) - 45, 0, 255).astype(np.uint8)         # настоящее пятно на дереве
r = PS.measure(Ab2, Pb, vb, np.zeros((300, 300), np.int32))
check('настоящее пятно на дереве при двух цветах в части — «пятно», не «граница»', r['n_bad'] >= 1 and r['verdict'] == 'брак')

# --- стол r0/r1 (фикстура: Pf — только на надёжном, A — на всём видимом)
FX = os.path.join(HERE, '..', '..', 'tests', 'fixtures', 'paint_spots_table.npz')
f = np.load(FX)
K = PS.R['k']
grp_t, valid_t, vis_t, Pf_t = f['grp'].astype(np.int32), f['valid'], f['vis'], f['Pf']
r0 = PS.measure(f['A0'], Pf_t, valid_t, grp_t, vis=vis_t)
r1 = PS.measure(f['A1'], Pf_t, valid_t, grp_t, vis=vis_t)
share = float(valid_t.sum()) / float(vis_t.sum())
check('столешница (группа 2.1): надёжных текселей < 40 %% — тон «не проверен» (tone_checked False), а не «чисто»', r1['unreliable_groups']['2.1']['tone_checked'] is False)
check('доля надёжного у стола (%.0f %% видимого): ненадёжного больше трети — мерка это заявляет, не молчит' % (100 * share), 0.3 < share < 0.7 and r0['unreliable_px'] == int((vis_t & ~valid_t).sum()))
check('стол r0 (забракован глазом): «брак» классом 1 (пятно против фото, балл %.1f)' % r0['worst_z'], r0['verdict'] == 'брак' and r0['n_bad'] >= 1 and r0['worst_z'] >= K)
check('стол r0: и классом 2 (деталь на ненадёжном, балл %.1f, мест %d)' % (r0['worst_z_unreliable'], r0['n_bad_unreliable']), r0['n_bad_unreliable'] >= 1)
check('стол r1 (забракован глазом): «брак» (класс 2: балл %.1f, мест %d)' % (r1['worst_z_unreliable'], r1['n_bad_unreliable']), r1['verdict'] == 'брак' and r1['n_bad_unreliable'] >= 1)
check('r1: верх ножек у царги/столешницы (y 225–265) — отдельный класс «граница групп» (стык белого низа столешницы и дерева), в брак пятен/деталей не смешан', any(s['peak_z'] >= K and 225 <= (s['bbox'][1] + s['bbox'][3]) // 2 <= 265 for s in r1['spots_boundary']) and not any(225 <= (s['bbox'][1] + s['bbox'][3]) // 2 <= 265 for s in r1['spots_unreliable'] if s['peak_z'] >= K))
check('r1: низ ближней ножки (x 520–600, y ≥ 1100) — деталь на ненадёжном, класс 2 (тёмный ровный блок тона; пятно владельца)', any(s['peak_z'] >= K and s['area_px'] >= PS.R['min_area_px'] and s['bbox'][1] >= 1100 and 520 <= s['bbox'][0] <= 600 for s in r1['spots_unreliable']))
z0 = np.maximum(r0['maps']['z'], r0['maps']['zu'])
z1 = np.maximum(r1['maps']['z'], r1['maps']['zu'])
cb = (slice(415, 460), slice(800, 900))                        # перекладина справа: у r0 пятна, у r1 чистая
check('чистая перекладина r1: оба класса ниже порога (%.2f < %.1f)' % (z1[cb].max(), K), z1[cb].max() < K)
check('перекладина r0 с пятнами: балл ≥ порога (%.2f)' % z0[cb].max(), z0[cb].max() >= K)
top = (slice(140, 215), slice(350, 1100))                      # белая столешница изнутри (вскользь, cos≈0,15 — ненадёжное, класс 2)
from scipy import ndimage as _ndi  # noqa: E402


def _max_blob(z):
    lab, n = _ndi.label(z[top] >= K)
    return int(np.bincount(lab.ravel())[1:].max()) if n else 0


check('белая столешница (ненадёжное, класс 2): нет места ≥ порога площадью ≥ %d px ни у r0 (%d), ни у r1 (%d)' % (PS.R['min_area_px'], _max_blob(z0), _max_blob(z1)),
      _max_blob(z0) < PS.R['min_area_px'] and _max_blob(z1) < PS.R['min_area_px'])
check('порог не подогнан: r0 — брак при k=3, 4, 6; r1 — брак при k=3 и 4 (при k=6 его единственный брак — деталь z 4,2 — уходит: так и сказано в отчёте)',
      all(PS.measure(f['A0'], Pf_t, valid_t, grp_t, {'k': kk}, vis=vis_t)['verdict'] == 'брак' for kk in (3.0, 4.0, 6.0))
      and all(PS.measure(f['A1'], Pf_t, valid_t, grp_t, {'k': kk}, vis=vis_t)['verdict'] == 'брак' for kk in (3.0, 4.0)))

# ID товаров в коде и правилах не вшиты
src = open(os.path.join(HERE, 'paint_spots.py'), encoding='utf-8').read() + open(os.path.join(HERE, '..', '..', 'rules', 'paint-spots.json'), encoding='utf-8').read()
check('ID товаров в коде и правилах не вшиты', re.search(r'\d{5,}_\d{10,}', src) is None)

print('FAIL: %d' % len(FAILS) if FAILS else 'all ok')
sys.exit(1 if FAILS else 0)

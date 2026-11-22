"""ПЕРЕКРАСКА ГОТОВОГО МЕША ПО ЦВЕТУ ФОТО (`salad/recolor_lp.py`, T-20261118-52/3/1 → 52/4): правила на синтетике, без мешей, сети и GPU.
Проверяем: ① нейтральная цель — сдвиг хромы полный (иначе остаётся «синяя боковина»); у цветной тёмной цели — ослаблен;
② охрана фурнитуры — ручка иного цвета, чем фасад, не меняется, а без охраны менялась бы; металл по карте — не трогаем;
③ предфильтр: тёмная текстура — отказ; ④ вердикт `judge`: самопроверка отказывает при росте насыщенности и ΔE, «сомнительно» при слабом
улучшении или поплывшем рисунке, «ok»/«частично» по доле правимого; ⑤ доводка рамки фото по силуэту.
    python tools/scout/tests/test_recolor_lp.py   (нужны numpy, PIL, scipy, opencv-python-headless)"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'salad'))
sys.path.insert(0, os.path.join(HERE, '..'))
import recolor_lp as R  # noqa: E402
import color_o2 as CO  # noqa: E402

fails = []


def check(name, cond, extra=''):
    print(('OK   ' if cond else 'FAIL ') + name + (f'  [{extra}]' if extra else ''))
    if not cond:
        fails.append(name)


S = 160                                     # сторона кадра
rng = np.random.default_rng(7)


def scene(facade_mesh, facade_photo, handle_rgb, handle_w=5):
    """Кадр рендера «было» и «фото»: фасад (≈ 92 %) + ручка-полоска справа; тот же шум в обоих. → (base, prgb, ralpha, pmask, tm)."""
    ralpha = np.zeros((S, S), bool)
    ralpha[8:S - 8, 8:S - 8] = True
    handle = np.zeros((S, S), bool)
    handle[8:S - 8, S - 8 - handle_w:S - 8] = True
    noise = rng.normal(0, 1.0, (S, S, 1))

    def paint(fr):
        img = np.zeros((S, S, 3), np.float32)
        img[ralpha] = fr
        img[handle] = handle_rgb
        return np.clip(img + noise * ralpha[..., None], 0, 255).astype(np.uint8)
    base, prgb = paint(facade_mesh), paint(facade_photo)
    part = np.where(ralpha, 0, -1).astype(np.int16)
    tm = (part, np.zeros((S, S), np.int32), np.zeros((S, S), np.int32))
    return base, prgb, ralpha, ralpha.copy(), tm, handle


def lab_of(rgb):
    return R.lab_f(np.array([[rgb]], np.uint8))[0, 0]


# ── ① нейтральная цель: полный сдвиг хромы ─────────────────────────────────────────────────────────────────────────
BLUE, GRAPHITE, HANDLE = (92, 102, 132), (62, 62, 64), (66, 54, 38)
base, prgb, ra, pm, tm, handle = scene(BLUE, GRAPHITE, HANDLE)
fld, rep, why, cover, _ = R.build_field(base, ra, prgb, pm, tm, [None])
fz = [z for z in rep if z.get('shift')]
check('нейтральная цель: правимый участок найден', fld is not None and len(fz) == 1 and why is None, str([(z['st'], z.get('why')) for z in rep]))
z = fz[0]
full = np.array(z['target'][1:]) - np.array(z['mesh'][1:])
got = np.array(z['shift'][1:])
check('нейтральная цель (хрома фото ≤ 8): сдвиг хромы полный, как «фото − меш»', np.abs(got - full).max() <= 1.0 and np.abs(full).max() > 5, f'full={full.round(1)} got={got.round(1)}')

WARM = (150, 70, 40)                        # цветная цель (хрома > 8) и не светлая: сдвиг хромы ослаблен
base2, prgb2, ra2, pm2, tm2, _ = scene((70, 60, 58), (92, 40, 24), HANDLE)
fld2, rep2, _, _, _ = R.build_field(base2, ra2, prgb2, pm2, tm2, [None])
z2 = [z_ for z_ in rep2 if z_.get('shift')][0]
full2 = np.hypot(*(np.array(z2['target'][1:]) - np.array(z2['mesh'][1:])))
check('цветная тёмная цель: хрома правится осторожнее (< 80 % от «фото − меш»)', np.hypot(*z2['shift'][1:]) < 0.8 * full2, f'full={full2:.1f} got={np.hypot(*z2["shift"][1:]):.1f}')

# ── ② охрана фурнитуры ─────────────────────────────────────────────────────────────────────────────────────────────
hz = [z_ for z_ in rep if z_['st'] == 'мелкий']
check('ручка (мелкий участок иного цвета) охраняется, фасад — нет', len(hz) == 1 and hz[0]['protect'] and not z['protect'] and len(fld.PC) == 1, str([(z_['st'], z_['protect']) for z_ in rep]))

tex = np.zeros((128, 128, 3), np.uint8)
tex[:] = BLUE
tex[:, 110:] = HANDLE
tex = np.clip(tex.astype(np.int16) + rng.integers(-2, 3, tex.shape), 0, 255).astype(np.uint8)
new, ex = R.recolor_texture(tex, fld)
r = ex['ratio']
facade_dev = float(np.abs(r[:, :100] - 1).mean())
handle_dev = float(np.abs(r[:, 114:] - 1).mean())
free = R.Field(fld.C, fld.sig, fld.sh)                        # то же поле, но без охраны
_, ex0 = R.recolor_texture(tex, free)
handle_dev0 = float(np.abs(ex0['ratio'][:, 114:] - 1).mean())
check('фасад по тексту правится заметно', facade_dev > 0.08, f'{facade_dev:.3f}')
check('ручка с охраной почти не меняется (< 3 %)', handle_dev < 0.03, f'{handle_dev:.3f}')
check('без охраны ручка менялась бы заметнее, чем с охраной (охрана действует)', handle_dev0 > 0.005 and handle_dev0 > 4 * handle_dev, f'без={handle_dev0:.4f} с={handle_dev:.4f}')

metal = np.zeros((128, 128), np.float32)
metal[:, 60:90] = 1.0                                           # полоса «металла» посреди фасада: тот же цвет, но металл
_, exm = R.recolor_texture(tex, free, metal)
check('металл по карте: тексели не правятся (множитель = 1)', float(np.abs(exm['ratio'][:, 66:84] - 1).max()) < 1e-3, f"{float(np.abs(exm['ratio'][:, 66:84] - 1).max()):.4f}")
check('вне металла фасад правится', float(np.abs(exm['ratio'][:, :50] - 1).mean()) > 0.08)

# нулевое поле не меняет текстуру (деталь переносится как есть)
f0 = R.Field(np.array([lab_of(BLUE)]), np.array([20.0]), np.array([[0.0, 0.0, 0.0]]))
n0, _ = R.recolor_texture(tex, f0)
check('нулевой сдвиг — текстура та же (≤ 1 уровень)', int(np.abs(n0.astype(int) - tex.astype(int)).max()) <= 1)

# ── ③ предфильтр: тёмная текстура — отказ без правок ───────────────────────────────────────────────────────────────
bd, pd_, rad, pmd, tmd, _ = scene((10, 10, 12), (16, 16, 18), (60, 60, 62), handle_w=0)   # фото рядом по светлоте — иначе «не тот материал»
fd, repd, whyd, coverd, _ = R.build_field(bd, rad, pd_, pmd, tmd, [None])
check('тёмная текстура (L меша < DARK_L): поля нет, причина названа', fd is None and any('тёмная' in (z_.get('why') or '') for z_ in repd), str([z_.get('why') for z_ in repd]))

# ── ④ вердикт по числам ────────────────────────────────────────────────────────────────────────────────────────────
W = {'de_med': 15.0, 'reg_dC_med': 2.0}
good = {'de_med': 4.0, 'reg_dC_med': 2.5}
check('вердикт: хорошо и всё правимо → ok', R.judge(W, good, 0.98, 0.9, True) == 'ok')
check('вердикт: хорошо, но правимо 50 % → частично', R.judge(W, good, 0.98, 0.5, True).startswith('частично'))
check('вердикт: предфильтр не пустил → отказ предфильтра', R.judge(W, good, 0.98, 0.1, False, [{'why': 'металл (…)'}]).startswith('отказ предфильтра (металл'))
check('самопроверка: насыщенность выросла (2 → 12) → отказ', R.judge(W, {'de_med': 10.0, 'reg_dC_med': 12.0}, 0.98, 0.9, True).startswith('отказ: самопроверка — насыщенность'))
check('самопроверка: насыщенность 0,7 → 3,9 (до 8) — не отказ (подушка №41)', R.judge({'de_med': 11.0, 'reg_dC_med': 0.7}, {'de_med': 6.0, 'reg_dC_med': 3.9}, 0.98, 0.9, True) == 'ok')
check('самопроверка: ΔE выросла → отказ', R.judge(W, {'de_med': 16.0, 'reg_dC_med': 2.0}, 0.98, 0.9, True).startswith('отказ: самопроверка — ΔE00'))
check('слабое улучшение (19 → 17) → сомнительно', R.judge({'de_med': 19.0, 'reg_dC_med': 2.0}, {'de_med': 17.0, 'reg_dC_med': 2.0}, 0.98, 0.9, True).startswith('сомнительно: ΔE00'))
check('улучшение до ≤ 5 слабым не считается, даже если не вдвое', R.judge({'de_med': 6.0, 'reg_dC_med': 2.0}, {'de_med': 5.0, 'reg_dC_med': 2.0}, 0.98, 0.9, True) == 'ok')
check('рисунок поплыл (корреляция 0,6) → сомнительно', R.judge(W, good, 0.6, 0.9, True).startswith('сомнительно: рисунок'))

# ── ⑤ доводка рамки фото по силуэту ────────────────────────────────────────────────────────────────────────────────
ral = np.zeros((120, 120), bool)
ral[30:90, 25:95] = True
pmk = np.zeros((120, 120), bool)
pmk[34:94, 29:99] = True                                       # силуэт фото сдвинут на 4 px
prgb_s = np.zeros((120, 120, 3), np.uint8)
prgb_s[pmk] = (200, 100, 50)
_, m2, al = R.refine_align(prgb_s, pmk, ral)
check('доводка: IoU силуэта вырос', al['iou'] > al['iou0'] and al['iou'] > 0.9, str(al))

print('---', 'FAIL: ' + ', '.join(fails) if fails else 'всё OK')
sys.exit(1 if fails else 0)

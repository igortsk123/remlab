#!/usr/bin/env python3
"""Автооценка «со всех сторон» (tools/assets/sides_eval.py, T-20261123-37) на заглушках: синтетические листы (фото + 6 видов), без Chromium и без товаров.
Проверяет: чистый лист проходит все 5 признаков; каждый брак из правил валит свой признак на своей стороне; «глина» убирает тень формы, но не заплатку;
в коде нет ID товаров и чисел порогов (они в data/flat3d/sides-eval.json). Запуск: python tools/assets/tests/test_sides_eval.py      (numpy + scipy + Pillow)"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, '..')
sys.path.insert(0, ASSETS)
import numpy as np  # noqa: E402
import sides_eval as SE  # noqa: E402
sys.path.append(os.path.join(HERE, "..", "..", "scout"))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use("test_sides_eval")

R = SE.load_rules()
SR = SE.load_sheet_rules()
S, HP = int(SR['size']), int(SR['header_px'])
NAMES = [v['name'] for v in SR['views']]
FAIL = 0
RNG = np.random.default_rng(7)


def ok(cond, name):
    global FAIL
    print(('  ✓ ' if cond else '  ✗ ') + name)
    FAIL += 0 if cond else 1


def blob_mask():
    yy, xx = np.mgrid[0:S, 0:S]
    return (np.abs(xx - S / 2) < 95) & (np.abs(yy - S / 2) < 105)


def put(cell_rgb, base, mask, fn=None):
    img = cell_rgb.copy()
    col = np.empty((S, S, 3))
    col[:] = base
    if fn:
        col = fn(col)
    img[mask] = np.clip(col, 0, 255).astype(np.uint8)[mask]
    return img


def sheet(photo_fn=None, view_fns=None, base=(170, 140, 100)):
    m = blob_mask()
    white = np.full((S, S, 3), 255, np.uint8)
    photo = np.full((S, S, 3), 245, np.uint8)
    cells = [put(photo, base, m, photo_fn)]
    for i in range(len(NAMES)):
        fn = (view_fns or {}).get(NAMES[i])
        cells.append(put(white, base, m, fn))
    row = np.concatenate(cells, axis=1)
    out = np.full((S + HP, row.shape[1], 3), 255, np.uint8)
    out[HP:] = row
    return out


def noise(sd, scale=1):
    def f(c):
        n = RNG.normal(0, sd, (S // scale, S // scale, 3))
        n = np.kron(n, np.ones((scale, scale, 1)))
        return c + n
    return f


def split_tone(dc):
    def f(c):
        c = c.copy()
        c[:, S // 2:, :] += np.array(dc)
        return c
    return f


def feats(res, view):
    return res['views'][view]


# 1. правила и код: чисел порогов и ID в коде нет
src = open(os.path.join(ASSETS, 'sides_eval.py'), encoding='utf-8').read()
ok(not re.search(r'\b\d{5,}_\d{6,}\b', src) and not re.search(r"'(112923|114082|99272|114667)", src), 'в коде нет ID товаров')
ok(all(k in R for k in ('patches', 'sharpness', 'uniform', 'pattern', 'underpaint', 'palette', 'albedo', 'geometry')) and len(SR['views']) == 6, 'правила: 5 признаков + палитра + albedo в sides-eval.json')
ok(not re.search(r'(patch_dE|share_max|edges_max|ratio_min|jump_dab)\s*=\s*\d', src), 'в коде нет присвоенных порогов (читаются из правил)')

# 2. чистый лист — проходит
good = SE.eval_sheet(sheet(), R, SR)
ok(good['ok'] and good['score'] is not None and good['score'] > 0.5, f"чистый лист: проходит все признаки (score {good['score']})")
ok(set(good['views'].keys()) == set(NAMES), 'оценены все 6 сторон')

# 3. заплатка: половина стороны другого тона → patches на этой стороне
bad = SE.eval_sheet(sheet(view_fns={'зад': split_tone((-60, 25, 40))}), R, SR)
ok(not feats(bad, 'зад')['patches']['ok'] and bad['views']['перед']['patches']['ok'] and not bad['ok'], 'заплатка на заду: валит patches именно заду, перед цел')
ok(bad['worst'] is not None and bad['worst']['view'] == 'зад', 'worst-first указывает на зад')

# 4. однотонно: фото однотонное, сторона пятнистая крупными пятнами
mott = SE.eval_sheet(sheet(view_fns={'бок': noise(14, 28)}), R, SR)
ok(feats(mott, 'бок')['uniform']['ok'] is False, 'пятнистость там, где на фото однотонно: валит uniform')

# 5. рисунок: на фото полосы, на стороне ровно → pattern; на другой стороне полосы есть → pattern ок
def stripes(c):
    c = c.copy()
    c[:, ::6, :] -= 35
    return c


pat = SE.eval_sheet(sheet(photo_fn=stripes, view_fns={'зад': None, 'бок': stripes}), R, SR)
ok(feats(pat, 'зад')['pattern']['ok'] is False and feats(pat, 'бок')['pattern']['ok'] is True, 'рисунок: на фото полосы — на ровном заду не перенесён, на боку перенесён')

# 6. недокрас: серый по умолчанию на стороне, на фото такого нет
grey = SE.eval_sheet(sheet(view_fns={'др. бок': lambda c: np.full_like(c, 128.0)}), R, SR)
ok(feats(grey, 'др. бок')['underpaint']['ok'] is False, 'серая заливка вместо тона: валит underpaint')

# 7. чёткость лица: на фото мелкая фактура, лицо размыто
def fine(c):
    return c + RNG.normal(0, 18, (S, S, 1))


from scipy import ndimage as ndi  # noqa: E402


def blur(c):
    return ndi.gaussian_filter(fine(c), (3, 3, 0))


sh = SE.eval_sheet(sheet(photo_fn=fine, view_fns={'перед': blur}), R, SR)
ok(feats(sh, 'перед')['sharpness']['ok'] is False and 'sharpness' not in feats(sh, 'зад'), 'размытое лицо при резком фото: валит sharpness (только у перед)')

# 8. тень формы: градиент яркости на стороне — без глины он путается с тоном, с глиной — нет
def shade(c):
    g = np.linspace(0.45, 1.0, S)[None, :, None]
    return c * g


def clay_sheet(gradient=True):
    m = blob_mask()
    cl = np.full((S + HP, S * 7, 3), 255, np.uint8)
    for i in range(1, 7):
        cell = np.full((S, S, 3), 255, np.uint8)
        gr = np.linspace(0.45, 1.0, S)[None, :, None] * np.ones((S, S, 1)) if gradient else np.ones((S, S, 1))
        cell[m] = np.clip(255 * gr * np.ones((S, S, 3)), 0, 255).astype(np.uint8)[m]
        cl[HP:, i * S:(i + 1) * S] = cell
    return cl


shaded = sheet(view_fns={n: shade for n in NAMES})
with_clay = SE.eval_sheet(shaded, R, SR, clay_rgb=clay_sheet())
ok(with_clay['albedo_scale'] is not None and with_clay['ok'], f"тень формы при глине (та же форма): не брак, тон ровный (score {with_clay['score']})")
patched = sheet(view_fns={n: (lambda c: shade(split_tone((-60, 25, 40))(c))) for n in NAMES})
pc = SE.eval_sheet(patched, R, SR, clay_rgb=clay_sheet())
ok(not pc['ok'], 'заплатка тона при глине: всё равно валится (тень формы её не маскирует)')

# 9. мелкая сторона без предмета — n/a, не падение
tiny = sheet()
tiny[HP:, 2 * S:3 * S] = 255
res = SE.eval_sheet(tiny, R, SR)
ok('na' in res['views']['3/4'], 'сторона без предмета: n/a')

# 10. сводка: общий % и порядок worst-first
import tempfile  # noqa: E402
from PIL import Image  # noqa: E402

with tempfile.TemporaryDirectory() as t:
    Image.fromarray(sheet()).save(os.path.join(t, 'a_good.png'))
    Image.fromarray(sheet(view_fns={'зад': split_tone((-60, 25, 40))})).save(os.path.join(t, 'b_bad.png'))
    out = SE.batch(t, os.path.join(t, 'out'))
    sm = out['summary']
    ok(sm['items'] == 2 and sm['passed_all'] == 1 and sm['passed_all_pct'] == 50.0 and sm['worst_first'][0] == 'b_bad', 'сводка: 1 из 2 прошёл (50 %), худший первый')
    ok(os.path.exists(os.path.join(t, 'out', 'eval.json')) and json.load(open(os.path.join(t, 'out', 'summary.json')))['passed_all'] == 1, 'eval.json и summary.json записаны')

print('FAIL' if FAIL else 'OK', FAIL)
sys.exit(1 if FAIL else 0)

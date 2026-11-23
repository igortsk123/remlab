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
ok(all(k in R for k in ('patches', 'sharpness', 'uniform', 'pattern', 'underpaint', 'palette', 'albedo', 'geometry', 'back_tone')) and len(SR['views']) == 6, 'правила: 5 признаков + back_tone (наблюдение) + палитра + albedo в sides-eval.json')
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

# 11. предохранитель ракурса: «перед» листа = сторона с наибольшей долей известного с фото; развёрнут — пересчёт сторон на 180°
def box4():
    V, F, UV = [], [], []
    quads = [((-1, 0, 1), (1, 0, 1)), ((1, 0, 1), (1, 0, -1)), ((1, 0, -1), (-1, 0, -1)), ((-1, 0, -1), (-1, 0, 1))]   # +Z, +X, -Z, -X
    for i, (a, b) in enumerate(quads):
        o = len(V)
        for (x, y, z), (u, v) in ((a, (0, 0)), (b, (1, 0)), (b, (1, 1)), (a, (0, 1))):
            V.append((x, -1.0 if v == 0 else 1.0, z))
            UV.append((i / 4 + u / 4, v))
        F += [(o, o + 1, o + 2), (o, o + 2, o + 3)]
    return np.array(V, float), np.array(F), np.array(UV, float)


V4, F4, UV4 = box4()
kn = np.zeros((100, 400), np.uint8)
kn[:, 200:300] = 255                               # известна грань −Z (третья)
sh0 = SE.front_shares(V4, F4, UV4, kn, 0.0, R)
sh180 = SE.front_shares(V4, F4, UV4, kn, 180.0, R)
ok(sh0['зад'] == 1.0 and sh0['перед'] == 0.0 and SE.front_flipped(sh0, R), f'ракурс: камера на +Z, известно на −Z → развёрнут ({sh0})')
ok(sh180['перед'] == 1.0 and not SE.front_flipped(sh180, R), 'ракурс: камера на −Z (там известно) → не развёрнут')
ok(not SE.front_flipped({'перед': 0.30, 'зад': 0.32}, R) and not SE.front_flipped({'перед': None, 'зад': 0.5}, R), 'ракурс: разница меньше margin или нет данных → молчит')
sheet_c = np.full((S + HP, S * 7, 3), 255, np.uint8)
for i in range(1, 7):
    sheet_c[HP:, i * S:(i + 1) * S] = (i * 30, 10, 10)
fl = SE.flip_sheet(sheet_c, S, HP)
c = lambda im, i: tuple(im[HP + 5, i * S + 5])
ok(c(fl, 1) == c(sheet_c, 4) and c(fl, 4) == c(sheet_c, 1) and c(fl, 3) == c(sheet_c, 5) and c(fl, 5) == c(sheet_c, 3) and c(fl, 6) == c(sheet_c, 6) and c(fl, 2) == (255, 255, 255), 'поворот листа: перед↔зад, бок↔др. бок, верх на месте, 3/4 пустой')
badback = sheet(view_fns={'зад': split_tone((-60, 25, 40))})
nf = SE.eval_sheet(badback, R, SR)
yf = SE.eval_sheet(badback, R, SR, flip=True)
ok(not nf['views']['зад']['patches']['ok'] and not yf['views']['перед']['patches']['ok'] and yf['views']['зад']['patches']['ok'] and yf['flipped'] and 'na' in yf['views']['3/4'], 'пересчёт с поворотом: заплатка с «зад» переехала на «перед»')

# 12. рисунок по ТИПУ (T-47/3, paint.hidden_pattern паспорта): continue / body / same_fabric / plain / unknown / not_applicable
def stripes_p(period, amp=35):
    def f(c):
        c = c.copy()
        c[:, ::period, :] -= amp
        return c
    return f


def pr(res, view):
    return feats(res, view)['pattern']


E = lambda sh, hp: SE.eval_sheet(sh, R, SR, hidden_pattern=hp)
st6 = stripes_p(6)
# continue: рисунок продолжается — «ровный зад при узорном фото = брак» только здесь; масштаб рисунка обязателен
c_same = E(sheet(photo_fn=st6, view_fns={'зад': st6, 'бок': st6}), 'continue')
c_flat = E(sheet(photo_fn=st6, view_fns={'зад': None, 'бок': st6}), 'continue')
c_big = E(sheet(photo_fn=st6, view_fns={'зад': stripes_p(12), 'бок': st6}), 'continue')           # клетка/полоса крупнее (или мельче) в 2 раза — масштаб не тот
ok(pr(c_same, 'зад')['ok'] is True, 'continue: тот же рисунок и масштаб на заду — проходит')
ok(pr(c_flat, 'зад')['ok'] is False and pr(c_flat, 'бок')['ok'] is True, 'continue: ровный зад при узорном фото — брак (бок с рисунком цел)')
ok(pr(c_big, 'зад')['ok'] is False and pr(c_big, 'бок')['ok'] is True and pr(c_big, 'зад')['r'] > 1, f"continue: энергия есть, но размер рисунка вдвое другой — брак по масштабу (r {pr(c_big, 'зад')['r']})")
# body: рисунок фасада — на перёд/3/4; зад/бока/верх ровные; рисунок на заду = брак (front_on_back)
b_ok = E(sheet(photo_fn=st6, view_fns={'перед': st6, '3/4': st6, 'зад': None, 'бок': None, 'др. бок': None, 'верх': None}), 'body')
b_bad = E(sheet(photo_fn=st6, view_fns={'перед': st6, '3/4': st6, 'зад': st6, 'бок': None, 'др. бок': None, 'верх': None}), 'body')
ok(all(pr(b_ok, v)['ok'] for v in ('перед', '3/4', 'зад', 'бок', 'др. бок', 'верх')), 'body: рисунок на фасаде, ровные зад/бока/верх — проходит (ровный зад — НЕ брак)')
ok(pr(b_bad, 'зад')['ok'] is False and pr(b_bad, 'бок')['ok'] is True and pr(b_bad, 'перед')['ok'] is True, 'body: рисунок фасада на заду (front_on_back) — брак, остальное цело')
ok(E(sheet(photo_fn=st6, view_fns={'зад': None}), None)['views']['зад']['pattern']['ok'] is False, 'без типа (старая общая мерка): ровный зад при узорном фото — брак, как раньше')
# same_fabric: фактура ткани как на фото; ровно или крупные пятна — отклонение
fab = noise(30)
sf_ok = E(sheet(photo_fn=fab, view_fns={'зад': fab, 'бок': fab}), 'same_fabric')
sf_flat = E(sheet(photo_fn=fab, view_fns={'зад': None, 'бок': fab}), 'same_fabric')
sf_big = E(sheet(photo_fn=fab, view_fns={'зад': lambda c: fab(noise(40, 30)(c)), 'бок': fab}), 'same_fabric')
ok(pr(sf_ok, 'зад')['ok'] is True and pr(sf_ok, 'бок')['ok'] is True, 'same_fabric: та же фактура ткани сзади и сбоку — проходит')
ok(pr(sf_flat, 'зад')['ok'] is False, 'same_fabric: зад гладкий при фактурной ткани на фото — не та ткань')
ok(pr(sf_big, 'зад')['ok'] is False, 'same_fabric: на заду крупные детали/пятна поверх ткани — брак')
# plain: ровно везде; рисунок на стороне = брак
pl_ok = E(sheet(photo_fn=None, view_fns={}), 'plain')
pl_bad = E(sheet(photo_fn=None, view_fns={'зад': st6}), 'plain')
ok(all(pr(pl_ok, v)['ok'] for v in NAMES if 'r' in pr(pl_ok, v) and pr(pl_ok, v)['r'] is not None) and pr(pl_ok, 'зад')['ok'] is True, 'plain: ровная вещь — проходит')
ok(pr(pl_bad, 'зад')['ok'] is False and pr(pl_bad, 'бок')['ok'] is True, 'plain: рисунок на стороне ровной вещи — брак')
# unknown / not_applicable: «не оценено» — ни брак, ни проход
for hp in ('unknown', 'not_applicable'):
    u = E(sheet(photo_fn=st6, view_fns={'зад': None}), hp)
    ok(pr(u, 'зад')['r'] is None and pr(u, 'зад')['ok'] is None and 'не оценено' in pr(u, 'зад')['why'], f'{hp}: признак «рисунок перенесён» — не оценено (не брак и не проход)')
# eval_one: тип и digest попадают в eval.json
with tempfile.TemporaryDirectory() as t2:
    Image.fromarray(sheet(photo_fn=st6, view_fns={'зад': st6})).save(os.path.join(t2, 'x.png'))
    r2 = SE.batch(t2, os.path.join(t2, 'o'), items={'x': {'id': 'x', 'hidden_pattern': 'continue', 'passport_digest': 'abc123'}})
    ok(r2['eval']['x']['hidden_pattern'] == 'continue' and r2['eval']['x']['passport_digest'] == 'abc123', 'eval.json: тип рисунка и digest паспорта записаны')

# 13. парные тесты правила R-SIDES-EVAL-TYPE (rule-registry.json: test_positive / test_negative) и запись extra.rules[]
import mesh_type_passports as MTP  # noqa: E402
import shutil  # noqa: E402


def test_sides_eval_type_positive():
    """Комод (тип с hidden_pattern=body из паспорта): на фото узор фасада, зад ровный — НЕ брак; рисунок фасада на заду — брак (front_on_back)."""
    pol = MTP.paint_policy('комод')
    flat_back = SE.eval_sheet(sheet(photo_fn=st6, view_fns={'перед': st6, '3/4': st6, 'зад': None, 'бок': None, 'др. бок': None, 'верх': None}), R, SR, hidden_pattern=pol['hidden_pattern'])
    ok(pol['hidden_pattern'] == 'body' and flat_back['views']['зад']['pattern']['ok'] is True, 'комод (body): ровный зад при узорном фото — не брак')


def test_sides_eval_type_negative():
    """Ваза (hidden_pattern=continue из паспорта): на фото клетка/полоса, зад ровный — брак; рисунок вдвое крупнее — тоже брак (масштаб)."""
    pol = MTP.paint_policy('ваза')
    flat_back = SE.eval_sheet(sheet(photo_fn=st6, view_fns={'зад': None, 'бок': st6}), R, SR, hidden_pattern=pol['hidden_pattern'])
    ok(pol['hidden_pattern'] == 'continue' and flat_back['views']['зад']['pattern']['ok'] is False and flat_back['views']['бок']['pattern']['ok'] is True, 'ваза (continue): ровный зад при узорном фото — брак')


test_sides_eval_type_positive()
test_sides_eval_type_negative()
with tempfile.TemporaryDirectory() as t3:
    Image.fromarray(sheet(photo_fn=st6, view_fns={'зад': st6})).save(os.path.join(t3, 'a.png'))
    shutil.copy(os.path.join(t3, 'a.png'), os.path.join(t3, 'a2.png'))
    shutil.copy(os.path.join(t3, 'a.png'), os.path.join(t3, 'a3.png'))
    its = {'a': {'id': 'a', 'hidden_pattern': 'continue', 'role': 'ваза'},
           'a2': {'id': 'a2', 'hidden_pattern': 'unknown', 'role': 'пуф', 'policy_reason': 'mode_observe'},
           'a3': {'id': 'a3', 'hidden_pattern': 'unknown', 'policy_reason': 'no_type'}}
    r3 = SE.batch(t3, os.path.join(t3, 'o'), items=its)['eval']
    e1, e2, e3 = (r3[k]['extra']['rules'][0] for k in ('a', 'a2', 'a3'))
    want = MTP.paint_policy('ваза')
    ok(e1 == {'rule_id': 'R-SIDES-EVAL-TYPE', 'type': 'ваза', 'digest': want['digest'], 'applied': True}, 'extra.rules[]: применено — запись rule_record.entry (тип, digest паспорта, applied)')
    ok(e2['abstain'] == 'mode_observe' and 'applied' not in e2 and e2['digest'] == MTP.paint_policy('пуф')['digest'], 'extra.rules[]: observe — abstain с причиной, не applied')
    ok(e3['type'] is None and e3['digest'] is None and 'no_type' in e3['abstain'], 'extra.rules[]: нет типа — запись abstain «no_type», не пустой охват')

# 14. T-34/4: правки оценщика рисунка по типу и тон тыла
# А. размер элемента рисунка — пик спектра с интерполяцией: ответ не прыгает ступеньками шага корзины (раньше 12 и 13 px давали одно число, 18 и 20 — тоже)
PS = {**R['pattern'], **R['pattern_by_type']['scale']}
YY, XX = np.mgrid[0:S, 0:S]


def wave_lab(wl):
    lab = np.zeros((S, S, 3))
    lab[..., 0] = 60 + 15 * np.sin(2 * np.pi * XX / wl)
    return lab


wls = [6, 7, 8, 9, 10, 11, 12, 13, 14, 16, 18, 20, 24]
est = [SE.pattern_scale(wave_lab(w), blob_mask(), PS) for w in wls]
ok(all(e is not None for e in est) and all(b > a for a, b in zip(est, est[1:])), f'масштаб рисунка: растёт строго вместе с периодом, без ступенек (12→{est[6]:.2f}, 13→{est[7]:.2f}, 18→{est[10]:.2f}, 20→{est[11]:.2f})')
ok(all(abs(e / w - 1) <= 0.08 for e, w in zip(est, wls) if e is not None), 'масштаб рисунка: ошибка периода не больше 8 % на 6–24 px')

# Б. «размер не измерен» не равно «размер сошёлся»: группу судит одна энергия, в отчёте — scale_na
_orig_scale = SE.pattern_scale
SE.pattern_scale = lambda *a, **k: None
try:
    n_good = E(sheet(photo_fn=st6, view_fns={'зад': st6}), 'continue')
    n_flat = E(sheet(photo_fn=st6, view_fns={'зад': None}), 'continue')
finally:
    SE.pattern_scale = _orig_scale
ok(pr(n_good, 'зад')['ok'] is True and pr(n_good, 'зад').get('scale_na'), 'continue, размер не измерен, энергия рисунка есть: проходит по энергии, группа записана в scale_na (не молчаливо)')
ok(pr(n_flat, 'зад')['ok'] is False and pr(n_flat, 'зад').get('scale_na'), 'continue, размер не измерен, рисунок потерян: None НЕ проходит молча — брак по энергии')

# В1. plain: группа стороны без пары на фото сравнивается с самой рябой группой фото, а не с полом rel_max
def lab_noise(sd, seed):
    lab = np.zeros((S, S, 3))
    lab[..., 0] = 60 + np.random.default_rng(seed).normal(0, sd, (S, S))
    return lab


full = np.ones((S, S), bool)
left, right = XX < S // 2, XX >= S // 2
lab_p = lab_noise(5.0, 1)
lab_s = np.where(left[..., None], lab_noise(5.0, 2), lab_noise(14.0, 3))
rel = lambda lab, gm: (lambda x: x[0] / x[1])(SE.group_pattern(lab, gm, R['pattern']))
T_PL = R['pattern_by_type']['plain']
ctx = {'s': (None, None, {0: left, 1: right}), 'p': (None, None, {0: full}), 'hp': 'plain', 'view': 'зад'}
r_pl, det_pl = SE.f_pattern_typed(lab_s, full, lab_p, full, R, ctx)
want = rel(lab_s, right) / max(T_PL['rel_max'], T_PL['photo_k'] * rel(lab_p, full))
floor_r = rel(lab_s, right) / T_PL['rel_max']
ok(abs(r_pl - want) < 0.05 * want and r_pl < floor_r, f'plain: группа без пары на фото — опора самая рябая группа фото (r {r_pl:.2f}, было бы по полу {floor_r:.2f})')
ok(r_pl > 1, 'plain: та же группа, втрое рябее фото — всё равно брак')

# В2. тон тыла ≈ тон лица: наблюдение (enforce=false) — r пишется, ok и оценку не трогает; лицевые стороны не оцениваются
def dark_band(frac):
    def f(c):
        c = c.copy()
        c[:, S // 2 - 95: S // 2 - 95 + int(190 * frac), :] = (25, 25, 25)             # доля ширины предмета (маска blob_mask: 190 px)
        return c
    return f


bt = SE.eval_sheet(sheet(photo_fn=dark_band(0.15), view_fns={'перед': dark_band(0.6), 'зад': dark_band(0.6), 'бок': dark_band(0.15)}), R, SR)
b_back, b_side, b_face = bt['views']['зад']['back_tone'], bt['views']['бок']['back_tone'], bt['views']['перед']['back_tone']
ok(b_back['r'] is not None and b_back['r'] > 1 and b_back.get('would_fail') is True and b_back['ok'] is None and b_back['score'] is None, f"back_tone: тёмного тыла втрое больше, чем на фото — r {b_back['r']} (>1), записано would_fail, но ok/score пусты (наблюдение)")
ok(b_side['r'] is not None and b_side['r'] <= 1 and b_face['r'] is None, 'back_tone: тот же тон, что на фото — r ≤ 1; лицевая сторона (перед) не оценивается')
ok(bt['views']['зад']['back_tone'].get('observe') is True and (bt['worst'] is None or bt['worst']['feature'] != 'back_tone'), 'back_tone: не попадает в worst и в общий ok, пока enforce=false')

print('FAIL' if FAIL else 'OK', FAIL)
sys.exit(1 if FAIL else 0)

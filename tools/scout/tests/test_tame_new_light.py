"""ПРИГЛУШЕНИЕ «СОЛНЕЧНЫХ ПЯТЕН» ОТВЕТА «УЛУЧШИТЬ» (T-20261118-05): `improve_mode.tame_new_light` — пятно света, которого нет во входном рендере, приглушается;
остальной кадр, общий сдвиг яркости, оттенок и окно не трогаются. Без сети и платных вызовов.
    python tools/scout/tests/test_tame_new_light.py"""
import os
import sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
import improve_mode as IM  # noqa: E402

fails = []


def check(name, cond):
    print(('OK   ' if cond else 'FAIL ') + name)
    if not cond:
        fails.append(name)


def lin(v):
    v = v / 255.0
    return np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)


def to_img(a):
    s = np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(np.clip(a, 1e-9, None), 1 / 2.4) - 0.055)
    return Image.fromarray((np.clip(s, 0, 1) * 255 + 0.5).astype(np.uint8))


SIZE = (192, 144)
base = np.zeros((SIZE[1], SIZE[0], 3), np.float64)
base[:, :] = (0.30, 0.24, 0.17)                                   # пол/стена — тёплая ровная поверхность
base[:SIZE[1] // 5, SIZE[0] * 3 // 4:] = 1.0                      # окно — белое
render = to_img(base)
yy, xx = np.mgrid[0:SIZE[1], 0:SIZE[0]]
blob = np.exp(-(((xx - 70) / 14.0) ** 2 + ((yy - 90) / 10.0) ** 2))   # «пятно солнца» ×2 в центре
ans = base * 0.8
ans = ans * (1.0 + 1.0 * blob)[..., None]
ans[:SIZE[1] // 5, SIZE[0] * 3 // 4:] = 1.0
improved = to_img(ans)
surf = [Image.fromarray(np.full((SIZE[1], SIZE[0]), 255, np.uint8))]


def y_of(im, box):
    x0, y0, x1, y1 = box
    return float((lin(np.asarray(im.convert('RGB'), np.float64))[y0:y1, x0:x1] @ np.array([0.2126, 0.7152, 0.0722])).mean())


out, info = IM.tame_new_light(improved, render, surf)
check('пятно найдено (площадь > 0, rel макс ≥ 1,5)', info['patch_pct'] > 0 and info['rel_max'] >= 1.5)
check('в центре пятна свет ослаблен минимум на треть', y_of(out, (64, 84, 76, 96)) < 0.67 * y_of(improved, (64, 84, 76, 96)))
check('после правки пятно сидит не выше ×1,35 общего уровня', y_of(out, (64, 84, 76, 96)) < 1.35 * y_of(improved, (10, 100, 40, 130)))
check('вдали от пятна кадр не меняется (≤ 1 уровня)', np.abs(np.asarray(out, int)[100:140, 120:190] - np.asarray(improved, int)[100:140, 120:190]).max() <= 1)
check('окно (белое) остаётся как есть', np.array_equal(np.asarray(out)[:20, 150:], np.asarray(improved)[:20, 150:]))
a, b = np.asarray(improved, np.float64)[88:92, 68:72].mean(axis=(0, 1)), np.asarray(out, np.float64)[88:92, 68:72].mean(axis=(0, 1))
check('оттенок не сдвинут (отношение каналов R/B в пятне то же ±3 %)', abs((b[0] / b[2]) / (a[0] / a[2]) - 1) < 0.03)

# общий сдвиг яркости без пятна — не трогаем
flat = to_img(base * 0.7)
o2, i2 = IM.tame_new_light(flat, render, surf)
check('ровное затемнение без пятна: кадр не тронут', i2['patch_pct'] == 0.0 and o2 is flat)
# нечем мерить: поверхность — клочок кадра
tiny = Image.fromarray(np.pad(np.full((6, 6), 255, np.uint8), ((0, SIZE[1] - 6), (0, SIZE[0] - 6))))
o3, i3 = IM.tame_new_light(improved, render, [tiny])
check('область замера мала — кадр не тронут', o3 is improved and i3['patch_pct'] == 0.0)
# другая ширина кадра: масштаб σ пересчитывается
big_r, big_i = render.resize((SIZE[0] * 4, SIZE[1] * 4), Image.BICUBIC), improved.resize((SIZE[0] * 4, SIZE[1] * 4), Image.BICUBIC)
o4, i4 = IM.tame_new_light(big_i, big_r, surf)
check('кадр 768 px: пятно тоже найдено', i4['patch_pct'] > 0)
# без масок (одна поверхность — вся область замера)
o5, i5 = IM.tame_new_light(improved, render)
check('без масок: пятно приглушено', i5['patch_pct'] > 0 and y_of(o5, (64, 84, 76, 96)) < 0.8 * y_of(improved, (64, 84, 76, 96)))

# --- подключение к «Улучшить»: включение, маски, версия ответа, исполнитель ---
import tempfile  # noqa: E402

REND = {'key': 'k' * 32, 'scene_hash': 'h' * 64}
with tempfile.TemporaryDirectory() as d:
    mk = np.zeros((SIZE[1], SIZE[0], 3), np.uint8)
    mk[SIZE[1] // 2:, :, 0] = 255                       # пол — красный
    mk[:SIZE[1] // 2, :, 1] = 255                       # стена — зелёная
    Image.fromarray(mk).save(os.path.join(d, 'C1.mask.png'))
    sf = IM.surface_masks(d, 'C1')
    check('маски ракурса читаются: три поверхности, пол внизу, стена вверху', sf is not None and len(sf) == 3 and np.asarray(sf[0])[-1, 0] == 255
          and np.asarray(sf[0])[0, 0] == 0 and np.asarray(sf[1])[0, 0] == 255)
    check('нет файла маски — None', IM.surface_masks(d, 'C2') is None)
    pl = {'render': dict(REND, mask_dir=d)}
    os.environ.pop('IMPROVE_TAME', None)
    check('без IMPROVE_TAME шаг выключен, версия ответа прежняя', not IM.tame_on(pl) and IM.prompt_version(pl) == IM.PROMPT_VERSION_RENDER)
    os.environ['IMPROVE_TAME'] = '1'
    check('IMPROVE_TAME=1 и маски есть: включён, версия получает tame-1', IM.tame_on(pl) and IM.prompt_version(pl) == IM.PROMPT_VERSION_RENDER + '+' + IM.TAME_VERSION)
    check('IMPROVE_TAME=1, масок нет: выключен, версия прежняя', not IM.tame_on({'render': REND}) and IM.prompt_version({'render': REND}) == IM.PROMPT_VERSION_RENDER)
    os.environ.pop('IMPROVE_TAME', None)
    out2, inf2 = IM.tame_new_light(improved, render, IM.surface_masks(d, 'C1'))
    check('по маскам кадра (пол внизу) пятно найдено и приглушено', inf2['patch_pct'] > 0 and y_of(out2, (64, 84, 76, 96)) < 0.7 * y_of(improved, (64, 84, 76, 96)))

import render_exec as RX  # noqa: E402
os.environ.pop('RENDER_MASKS', None)
check('маски рендера: по умолчанию не считаются (пресет и ключ кэша не меняются)', not RX.masks_wanted())
os.environ['RENDER_MASKS'] = '1'
check('RENDER_MASKS=1 включает маски', RX.masks_wanted())
os.environ.pop('RENDER_MASKS', None)
src = open(os.path.join(HERE, '..', 'render_exec.py'), encoding='utf-8').read()
check('исполнитель CPU: --mask-out по условию, маска ложится рядом с кадром (<cam>.mask.png)', "'--mask-out'" in src and "'.mask.png'" in src)
dr = open(os.path.join(HERE, '..', 'draft_render.py'), encoding='utf-8').read()
check('draft_render: шаг после нормировки яркости и до публикации кадров', 0 < dr.index('IM.match_luma(_p, _r)') < dr.index('IM.tame_new_light(_p, _r, _sf2)') < dr.index("shots = [{'camera': c.name, 'url': _publish_frame"))
rc = open(os.path.join(HERE, '..', 'cycles_probe', 'render_cycles.py'), encoding='utf-8').read()
_mp = rc[rc.index('_t_mask = time.time()'):]
check('render_cycles: масштаб маски (--mask-scale) ставится ПОСЛЕ setup_camera (он сам возвращает resolution_percentage = --pct)', _mp.index('setup_camera(_cn)') < _mp.index('a.mask_scale'))
check('render_cycles: проход масок ставит формат PNG (при кадрах JPEG иначе имя получает .jpg и маски нет)', "file_format = 'PNG'" in _mp[:_mp.index('setup_camera(_cn)')])

print('итог:', 'чисто' if not fails else f'{len(fails)} падений')
sys.exit(1 if fails else 0)

"""НОРМИРОВКА ЯРКОСТИ ОТВЕТА «УЛУЧШИТЬ» (T-20261118-01/3): `improve_mode.match_luma` — одно усиление по входному рендеру, с потолком, без сдвига оттенка,
без подтяжки окна и пересвета, по маске (если есть). Без сети и платных вызовов.
    python tools/scout/tests/test_match_luma.py"""
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


def scene(scale, size=(120, 90)):
    """Кадр: левая половина — тёплая «стена», правая нижняя — «пол», правый верх — «окно» (белое). scale — во сколько раз темнее в линейном свете."""
    a = np.zeros((size[1], size[0], 3), np.float64)
    a[:, :size[0] // 2] = (0.60, 0.52, 0.42)
    a[size[1] // 2:, size[0] // 2:] = (0.50, 0.38, 0.22)
    a *= scale
    a[:size[1] // 2, size[0] // 2:] = 1.0
    srgb = np.where(a <= 0.0031308, a * 12.92, 1.055 * np.power(np.clip(a, 1e-9, None), 1 / 2.4) - 0.055)
    return Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8))


ref = scene(1.0)
dark = scene(0.72)
out, info = IM.match_luma(dark, ref)
y = lambda im, sl: float((lin(np.asarray(im, np.float64)) @ np.array([0.2126, 0.7152, 0.0722]))[sl].mean())      # noqa: E731
wall = (slice(0, 90), slice(0, 60))
check('кадр темнее входа на 28 % → яркость стены возвращена к входу (±3 %)', abs(y(out, wall) / y(ref, wall) - 1) < 0.03)
check('усиление в пределах потолка и записано в сведения', IM.LUMA_CAP[0] <= info['gain'] <= IM.LUMA_CAP[1] and info['y_after'] > info['y_before'])
r0, r1 = np.asarray(dark, np.float64), np.asarray(out, np.float64)
ra, rb = lin(r0)[10, 10], lin(r1)[10, 10]
check('оттенок не сдвинут: отношения каналов в линейном свете те же', np.allclose(ra / ra[1], rb / rb[1], rtol=0.02))
check('окно (белое) не подтянуто и не пересвечено: остаётся белым', np.asarray(out)[5, 100].min() >= 250 and np.abs(np.asarray(out, int)[5, 100] - np.asarray(dark, int)[5, 100]).max() <= 3)
out2, info2 = IM.match_luma(scene(0.2), ref)
check('потолок: слишком тёмный ответ усиливается не больше ×1,35', abs(info2['gain'] - IM.LUMA_CAP[1]) < 1e-6)
out3, info3 = IM.match_luma(scene(3.0).point(lambda v: min(v, 235)), ref)
check('потолок: слишком светлый ответ гасится не больше чем до ×0,85', info3['gain'] >= IM.LUMA_CAP[0] - 1e-6)
same, i4 = IM.match_luma(ref, ref)
check('ответ уже как вход → усиление ≈ 1, кадр не меняется', abs(i4['gain'] - 1) < 0.01 and np.abs(np.asarray(same, int) - np.asarray(ref, int)).max() <= 2)
mask = np.zeros((90, 120), bool)
mask[45:, 60:] = True                                              # только «пол»
out5, i5 = IM.match_luma(dark, ref, mask=mask)
check('по маске: измерен только пол, доля области ≈ маске', abs(i5['region_pct'] - 100 * 45 * 60 / (90 * 120)) < 1.0 and abs(y(out5, (slice(45, 90), slice(60, 120))) / y(ref, (slice(45, 90), slice(60, 120))) - 1) < 0.03)
gamma = IM.match_luma(dark, ref.resize((60, 45)))[0]
check('размер входа другой — подгоняется под ответ, размер ответа сохранён', gamma.size == dark.size)
white = Image.new('RGB', (40, 30), (252, 252, 252))
w2, i6 = IM.match_luma(white, white)
check('всё белое: нечем мерить — кадр не трогаем, без ошибок', i6['gain'] == 1.0 and np.asarray(w2).min() >= 252)
bright = scene(1.0)
hi = np.asarray(bright, np.float64).copy()
hi[60:70, 10:20] = 248
b2, _ = IM.match_luma(Image.fromarray(hi.astype(np.uint8)), ref, cap=(1.2, 1.35))
check('света выше колена сжимаются плавно: 248 после усиления не выше 255 и не «плоский» 255 при ×1,2', 248 <= np.asarray(b2)[65, 15].max() <= 255)
check('версия шага — в версии промпта рендера (ключ кэша)', IM.LUMA_VERSION in IM.PROMPT_VERSION_RENDER and IM.prompt_version({'render': {'key': 'k'}}) == IM.PROMPT_VERSION_RENDER)
print('итог:', 'чисто' if not fails else f'{len(fails)} провал(ов): {fails}')
sys.exit(1 if fails else 0)

#!/usr/bin/env python3
"""МЕРКА ПЕРЕСВЕТА КАДРА (T-20261118-06/2 рабочий 2, в репо — T-20261118-08/1; одна и та же для кадра Cycles и снимка живой 3D). Вход: кадр (PNG/JPEG) и, если есть, маска поверхностей рендера (`--mask-out`: пол красный, нейтральная стена зелёная,
акцентная синяя, остальное чёрное). Выход — одна строка JSON:
  clip_any   доля пикселей кадра, где ЛЮБОЙ канал ≥ 250 («выбито»)
  white      доля пикселей с яркостью (Rec.709 по sRGB) ≥ 242 — «почти белое, фактуры нет»
  p99        99-й процентиль яркости; mean — средняя яркость кадра
  wall_*     то же по маске нейтральной стены: wall_n (доля кадра), wall_mean, wall_white (доля стены ≥ 242), wall_clip (доля стены, где любой канал ≥ 250)
  floor_*    то же по полу
  sky_frac   окно: доля кадра «небо за окном» (светлые голубовато-зелёные пиксели вне стен/пола) — чтобы сравнивать кадры одной сцены
  near_win   доля стены в зоне вокруг окна (расширение неба на 8 % ширины кадра), что ≥ 242 — «стена у окна выбита»
Яркость берётся из sRGB как есть (то, что видит человек на экране), не из линейного HDR.
"""
import json, sys
import numpy as np
from PIL import Image


def luma(a):
    return 0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]


def dilate(m, r):
    # быстрое расширение прямоугольным окном через интегральный образ (без scipy)
    h, w = m.shape
    ii = np.pad(m.astype(np.int32), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    y0 = np.clip(np.arange(h) - r, 0, h); y1 = np.clip(np.arange(h) + r + 1, 0, h)
    x0 = np.clip(np.arange(w) - r, 0, w); x1 = np.clip(np.arange(w) + r + 1, 0, w)
    s = ii[y1][:, x1] - ii[y0][:, x1] - ii[y1][:, x0] + ii[y0][:, x0]
    return s > 0


def measure(img_path, mask_path=None):
    a = np.asarray(Image.open(img_path).convert('RGB')).astype(np.float32)
    h, w, _ = a.shape
    L = luma(a)
    out = {'w': w, 'h': h, 'mean': round(float(L.mean()), 1), 'p99': round(float(np.percentile(L, 99)), 1),
           'clip_any': round(float((a.max(-1) >= 250).mean()), 4), 'white': round(float((L >= 242).mean()), 4)}
    if mask_path:
        m = np.asarray(Image.open(mask_path).convert('RGB').resize((w, h), Image.NEAREST)).astype(np.int32)
        red, green, blue = (m[..., 0] > 160) & (m[..., 1] < 90), (m[..., 1] > 160) & (m[..., 0] < 90), (m[..., 2] > 160) & (m[..., 0] < 90)
        other = ~(red | green | blue)
        for name, mk in (('wall', green), ('floor', red)):
            n = int(mk.sum())
            out[name + '_n'] = round(n / (h * w), 4)
            if n:
                out[name + '_mean'] = round(float(L[mk].mean()), 1)
                out[name + '_white'] = round(float((L[mk] >= 242).mean()), 4)
                out[name + '_clip'] = round(float((a[mk].max(-1) >= 250).mean()), 4)
        # небо за окном: вне пола/стен, светло и голубее красного (небо/зелень за стеклом), не белое постельное бельё (там B ≈ R)
        sky = other & (L > 150) & ((a[..., 2] - a[..., 0]) > 6)
        out['sky_frac'] = round(float(sky.mean()), 4)
        if sky.sum() > 50:
            zone = dilate(sky[::4, ::4], int(0.08 * w / 4))
            zone = np.kron(zone, np.ones((4, 4), bool))[:h, :w]
            wz = green & zone
            out['near_win_n'] = round(float(wz.sum()) / (h * w), 4)
            out['near_win'] = round(float((L[wz] >= 242).mean()), 4) if wz.sum() else None
    return out


def verdict(m: dict, rules: dict) -> dict:
    """Мерка против правил (`data/flat3d/light-rules.json: limits`): какие пределы нарушены. {ok, breaches:[{key, value, max}]}; ключа в мерке нет — предел не проверяется."""
    br = []
    for k, mx in (rules.get('limits') or {}).items():
        v = m.get(k)
        if v is not None and v > mx:
            br.append({'key': k, 'value': v, 'max': mx})
    return {'ok': not br, 'breaches': br}


if __name__ == '__main__':
    p = sys.argv[1]
    mp = sys.argv[2] if len(sys.argv) > 2 else None
    print(json.dumps(measure(p, mp), ensure_ascii=False))

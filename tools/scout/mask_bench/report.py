"""Итоговый разбор: честные метрики + контактные листы с зумом на тонкие детали.

Эталонной разметки нет, поэтому ни одна метрика тут не «истина». Считаем две независимые вещи:
  * расхождение с консенсусом вариантов — ловит выброс (вариант, который один видит иначе);
  * удержание тонких деталей — по «свидетельству» с белой карточки, откуда ВЫЧТЕНЫ тень
    (пиксели ниже нижней кромки товара в своём столбце, бесцветные) и ватермарка.
Решение владелец принимает глазами; числа только подсказывают, куда смотреть.
"""
import json
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

ROOT = os.path.dirname(os.path.abspath(__file__))
VARIANTS = ['A-now', 'B-heavy2k', 'C-matte2k', 'D-bria2', 'E-hybrid']
TITLES = {'A-now': 'A · Как сейчас', 'B-heavy2k': 'B · BiRefNet Heavy 2K',
          'C-matte2k': 'C · BiRefNet Matting 2K', 'D-bria2': 'D · BRIA RMBG 2.0',
          'E-hybrid': 'E · Наш гибрид'}
CONSENSUS = ['A-now', 'C-matte2k', 'D-bria2']       # B исключён: доказанный выброс


def font(sz, bold=False):
    p = ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold
         else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    return ImageFont.truetype(p, sz) if os.path.exists(p) else ImageFont.load_default()


def checker(size, step=11):
    w, h = size
    y, x = np.mgrid[0:h, 0:w]
    c = np.where(((x // step + y // step) % 2) == 0, 238, 206).astype(np.uint8)
    return Image.fromarray(np.dstack([c, c, c]), 'RGB')


def on_checker(rgba):
    bg = checker(rgba.size)
    bg.paste(rgba, (0, 0), rgba)
    return bg


def alpha_of(vid, iid, size):
    p = os.path.join(ROOT, vid, iid + '.png')
    im = Image.open(p).convert('RGBA')
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    return im, np.asarray(im)[..., 3].astype(np.float32) / 255.0


def evidence(rgb, solid):
    """Что на белой карточке заведомо является товаром: не фон, не тень, не ватермарка."""
    h, w = rgb.shape[:2]
    b = max(2, int(min(h, w) * 0.04))
    band = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    med = np.median(band, axis=0)
    p99 = float(np.percentile(np.linalg.norm(band - med, axis=1), 99))
    uniform = p99 < 30 and float(np.linalg.norm(med - 255)) < 60
    if not uniform:
        return None, None
    vis = np.linalg.norm(rgb - med, axis=2) > max(p99 * 1.6, 12)
    # тень: ниже нижней кромки товара в своём столбце и бесцветная
    col_has = solid.any(axis=0)
    col_bottom = np.where(col_has, solid.shape[0] - 1 - solid[::-1].argmax(axis=0), -1)
    yy = np.arange(h)[:, None]
    chroma = rgb.max(axis=2) - rgb.min(axis=2)
    shadow = (yy > col_bottom[None, :]) & col_has[None, :] & (chroma < 18)
    vis = vis & ~ndimage.binary_dilation(shadow, np.ones((3, 3)))
    # ватермарка/подпись: мелкие кляксы вдали от главного объекта
    lab, n = ndimage.label(vis)
    if not n:
        return None, None
    sizes = np.bincount(lab.ravel())[1:]
    main = lab == (np.argmax(sizes) + 1)
    near = ndimage.binary_dilation(main, np.ones((3, 3)), iterations=8)
    obj = vis & (near | main)
    return obj, med


def analyse():
    items = json.load(open(os.path.join(ROOT, 'set.json')))
    out = {}
    for it in items:
        iid = it['id']
        src = Image.open(os.path.join(ROOT, 'src', iid + '.jpg')).convert('RGB')
        rgb = np.asarray(src).astype(np.float32)
        al = {}
        for v in VARIANTS:
            al[v] = alpha_of(v, iid, src.size)[1]
        cons = np.median(np.stack([al[v] for v in CONSENSUS]), axis=0)
        cs = cons > 0.5
        obj, med = evidence(rgb, cs)
        row = {'uniform_bg': obj is not None}
        for v in VARIANTS:
            a = al[v]
            f = a > 0.5
            inter = (f & cs).sum()
            union = (f | cs).sum()
            r = {'iou_consensus': round(float(inter / max(union, 1)), 4),
                 'coverage': round(100 * float(f.mean()), 2),
                 'soft_edge': round(100 * float(((a > 0.04) & (a < 0.96)).mean()), 3)}
            lab, n = ndimage.label(f)
            r['components'] = int((np.bincount(lab.ravel())[1:] > 0.002 * max(f.sum(), 1)).sum()) if n else 0
            if obj is not None:
                dt = ndimage.distance_transform_edt(obj)
                thin = obj & (dt <= 2.0)
                r['thin_keep'] = round(100 * float((thin & (a >= 0.16)).sum() / max(thin.sum(), 1)), 1)
                r['lost'] = round(100 * float((obj & (a < 0.16)).sum() / max(obj.sum(), 1)), 2)
                bgm = np.linalg.norm(rgb - med, axis=2) <= max(
                    float(np.percentile(np.linalg.norm(rgb - med, axis=2), 5)) + 8, 12)
                r['bg_leak'] = round(100 * float((f & bgm).sum() / max(f.sum(), 1)), 2)
            row[v] = r
        out[iid] = {'meta': it, 'v': row}
    json.dump(out, open(os.path.join(ROOT, 'report.json'), 'w'), ensure_ascii=False, indent=1)
    return out


def thin_crop(rgb, obj, size=150):
    """Окно вокруг самой тонкой заметной детали — туда и надо смотреть."""
    if obj is None or not obj.any():
        h, w = rgb.shape[:2]
        return (max(0, w // 2 - size), max(0, h // 2 - size),
                min(w, w // 2 + size), min(h, h // 2 + size))
    dt = ndimage.distance_transform_edt(obj)
    thin = obj & (dt <= 2.0)
    dens = ndimage.uniform_filter(thin.astype(np.float32), 45)
    y, x = np.unravel_index(np.argmax(dens), dens.shape)
    h, w = rgb.shape[:2]
    x0, y0 = max(0, x - size), max(0, y - size)
    return x0, y0, min(w, x0 + 2 * size), min(h, y0 + 2 * size)


def sheets(rep):
    os.makedirs(os.path.join(ROOT, 'final'), exist_ok=True)
    f_t, f_s = font(17, True), font(14)
    CELL, ZOOM = 260, 260
    for iid, r in rep.items():
        it = r['meta']
        src = Image.open(os.path.join(ROOT, 'src', iid + '.jpg')).convert('RGB')
        rgb = np.asarray(src).astype(np.float32)
        cons = np.median(np.stack([alpha_of(v, iid, src.size)[1] for v in CONSENSUS]), axis=0)
        obj, _ = evidence(rgb, cons > 0.5)
        box = thin_crop(rgb, obj)
        n = len(VARIANTS) + 1
        sheet = Image.new('RGB', (CELL * n, 34 + CELL + ZOOM + 46), (255, 255, 255))
        d = ImageDraw.Draw(sheet)
        d.text((8, 8), f"{it['role']} · {it['name']}   [{it['shop']} · {it['w']}×{it['h']}]",
               fill=(20, 20, 20), font=f_t)

        def place(col, img, label, sub=''):
            im = img.copy()
            im.thumbnail((CELL - 8, CELL - 8), Image.LANCZOS)
            sheet.paste(im, (col * CELL + (CELL - im.width) // 2, 34 + (CELL - im.height) // 2))
            zm = img.crop(box)
            zm = zm.resize((ZOOM - 8, int((ZOOM - 8) * zm.height / max(zm.width, 1))), Image.NEAREST)
            sheet.paste(zm, (col * CELL + 4, 34 + CELL + 4))
            d.text((col * CELL + 6, 34 + CELL + ZOOM + 6), label, fill=(20, 20, 20), font=f_s)
            if sub:
                d.text((col * CELL + 6, 34 + CELL + ZOOM + 24), sub, fill=(110, 110, 110), font=f_s)

        place(0, src, 'Исходник', f"{it['w']}×{it['h']} px")
        for i, v in enumerate(VARIANTS, start=1):
            im, _ = alpha_of(v, iid, src.size)
            m = r['v'][v]
            sub = (f"тонкое {m['thin_keep']}%  фон {m['bg_leak']}%"
                   if 'thin_keep' in m else f"IoU {m['iou_consensus']:.3f}")
            place(i, on_checker(im), TITLES[v], sub)
        for i in range(1, n):
            d.line([(i * CELL, 34), (i * CELL, 34 + CELL + ZOOM)], fill=(215, 215, 215))
        d.line([(0, 34 + CELL + 2), (CELL * n, 34 + CELL + 2)], fill=(215, 215, 215))
        sheet.save(os.path.join(ROOT, 'final', iid + '.jpg'), quality=82)


def summary(rep):
    print(f"{'вариант':24}{'тонкое,%':>10}{'потери,%':>10}{'фон в маске,%':>15}"
          f"{'IoU конс.':>11}{'провалов':>10}")
    for v in VARIANTS:
        tk, ls, bl, iou, bad = [], [], [], [], 0
        for r in rep.values():
            m = r['v'][v]
            iou.append(m['iou_consensus'])
            if 'thin_keep' in m:
                tk.append(m['thin_keep'])
                ls.append(m['lost'])
                bl.append(m['bg_leak'])
                if m['lost'] > 8:
                    bad += 1
        print(f'{TITLES[v]:24}{np.median(tk):10.1f}{np.median(ls):10.2f}'
              f'{np.median(bl):15.2f}{np.median(iou):11.3f}{bad:10d}')


if __name__ == '__main__':
    rep = analyse()
    summary(rep)
    sheets(rep)
    print('листы:', len(os.listdir(os.path.join(ROOT, 'final'))))

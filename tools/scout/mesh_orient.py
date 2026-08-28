#!/usr/bin/env python3
"""Калибровка ФРОНТА меша по фото товара — каскад со статусами (план viz-mesh-orientation, q22).

Каскад (не произведение скоров): геометрия ракурса (IoU силуэтов) → перед/зад по
ПРОСТРАНСТВЕННОЙ СЕТКЕ ЦВЕТА (средний RGB не отличает; сетка 4×4 видит сиденье стула) →
отрыв top1−top2. Статусы: confident | unobservable | symmetric | mesh_invalid.
«symmetric» — только по НЕЗАВИСИМОЙ проверке симметрии самого меша (силуэт yaw против yaw+180),
а не по ровным плохим скорам (это unobservable). Зеркала нет (ломает left/right SKU).
"""
import json
import os
import sys

import numpy as np
from PIL import Image

import mesh_render as MR

ORIENT_VERSION = 1
YAWS = (0, 90, 180, 270)


def photo_mask(ph: Image.Image):
    """Маска товара на фото: сперва честная вырезка фона (viz_paste.cutout — карточки часто с
    интерьерным фоном, белый порог там бесполезен), затем фолбэк на белый порог."""
    try:
        import tempfile
        from viz_paste import cutout, trim_alpha
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            ph.convert('RGB').save(f.name, quality=92)
            cut = trim_alpha(cutout(f.name))
        os.unlink(f.name)
        ca = np.asarray(cut)
        if ca.shape[2] == 4 and (ca[..., 3] > 90).sum() > 400:
            m = ca[..., 3] > 90
            return m, ca[..., :3].astype(int) * 0 + np.asarray(cut.convert('RGB'))
    except Exception:  # noqa: BLE001 — вырезка недоступна: белый порог
        pass
    a = np.asarray(ph.convert('RGB')).astype(int)
    m = ~((a.sum(axis=2) > 738) & (np.abs(a.max(axis=2) - a.min(axis=2)) < 16))
    ys, xs = np.where(m)
    if not len(ys):
        return None, None
    box = (ys.min(), ys.max() + 1, xs.min(), xs.max() + 1)
    return m[box[0]:box[1], box[2]:box[3]], np.asarray(ph.convert('RGB'))[box[0]:box[1],
                                                                          box[2]:box[3]]


def _fit(mask, col, size=96):
    im = Image.fromarray(mask.astype(np.uint8) * 255).resize((size, size))
    ic = Image.fromarray(col.astype(np.uint8)).resize((size, size))
    return np.asarray(im) > 127, np.asarray(ic).astype(int)


def _grid_sim(m1, c1, m2, c2, cells=4) -> float:
    """Сходство сетки цвета по пересечению масок: 1 − нормированная средняя дистанция."""
    inter = m1 & m2
    if inter.sum() < 40:
        return 0.0
    size = m1.shape[0]
    step = size // cells
    ds, n = 0.0, 0
    for i in range(cells):
        for j in range(cells):
            sl = np.s_[i * step:(i + 1) * step, j * step:(j + 1) * step]
            ii = inter[sl]
            if ii.sum() < 8:
                continue
            d = np.abs(c1[sl][ii].mean(axis=0) - c2[sl][ii].mean(axis=0)).mean()
            ds += d
            n += 1
    if not n:
        return 0.0
    return max(0.0, 1.0 - (ds / n) / 120.0)


def _thin(parts, max_faces=50000):
    """Прореживание для КОНТРОЛЬНЫХ рендеров: у Hunyuan-мешей сотни тысяч граней, питон-
    растеризатор жуёт их часами (зависание 28.08). Силуэту/аспекту хватает подвыборки —
    bbox-метрики к дыркам нечувствительны."""
    import numpy as _np
    import trimesh as _tm
    total = sum(len(m.faces) for m in parts)
    if total <= max_faces:
        return parts
    out = []
    for m in parts:
        k = max(1, int(len(m.faces) * max_faces / total))
        idx = _np.random.default_rng(7).choice(len(m.faces), size=min(k, len(m.faces)),
                                               replace=False)
        out.append(_tm.Trimesh(vertices=m.vertices, faces=_np.asarray(m.faces)[idx],
                               process=False))
    return out


def render_sil(parts, yaw, size=420):
    r = MR.render(_thin(parts), yaw_deg=yaw, pitch_deg=8.0, size=(size, size))
    a = np.asarray(r)
    m = a[..., 3] > 0
    ys, xs = np.where(m)
    if not len(ys):
        return None, None
    box = np.s_[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    return m[box], a[..., :3][box]


def mesh_symmetric(parts) -> bool:
    """Независимая симметрия: силуэт спереди совпадает с силуэтом сзади (IoU>0.97)."""
    m0, _ = render_sil(parts, 0)
    m180, _ = render_sil(parts, 180)
    if m0 is None or m180 is None:
        return False
    a, _ = _fit(m0, np.zeros((*m0.shape, 3)))
    b, _ = _fit(np.fliplr(m180), np.zeros((*m180.shape, 3)))
    return float((a & b).sum()) / max((a | b).sum(), 1) > 0.97


def calibrate(glb_path: str, photo: Image.Image, tiebreak=None) -> dict:
    """`tiebreak(render_a, render_b, photo) -> 0|1` — зрячий судья перед/зад, зовётся ТОЛЬКО
    при неразличимости цветом (margin < порога); результат кэшируется вызывающим кодом."""
    """→ {front_yaw, status, top1, margin, metrics}."""
    try:
        parts = MR.load_parts(glb_path)
    except Exception as e:  # noqa: BLE001
        return {'status': 'mesh_invalid', 'error': str(e)[:120], 'version': ORIENT_VERSION}
    pm, pc = photo_mask(photo)
    if pm is None:
        return {'status': 'unobservable', 'reason': 'фото без силуэта',
                'version': ORIENT_VERSION}
    pmf, pcf = _fit(pm, pc)
    scored = []
    for yaw in YAWS:
        mm, mc = render_sil(parts, yaw)
        if mm is None:
            continue
        mmf, mcf = _fit(mm, mc)
        iou = float((mmf & pmf).sum()) / max((mmf | pmf).sum(), 1)
        col = _grid_sim(mmf, mcf, pmf, pcf)
        scored.append({'yaw': yaw, 'iou': round(iou, 3), 'col': round(col, 3)})
    if not scored:
        return {'status': 'mesh_invalid', 'reason': 'пустые рендеры', 'version': ORIENT_VERSION}
    # каскад: геометрией отбираем ракурсы (перед/зад силуэтом не различимы — берём допуск),
    # затем перед/зад решает СЕТКА ЦВЕТА
    best_iou = max(s['iou'] for s in scored)
    geo_ok = [s for s in scored if s['iou'] >= best_iou - 0.08]
    geo_ok.sort(key=lambda s: -s['col'])
    top1 = geo_ok[0]
    margin = top1['col'] - (geo_ok[1]['col'] if len(geo_ok) > 1 else 0.0)
    col_flat = margin < 0.06 and len(geo_ok) > 1   # порог вызова судьи: стул был 0.03–0.06
    # материал для судьи готовит вызывающий код: СЦЕН-КАДРЫ (front_probe) различают перед/зад
    # куда грубее орто-рендеров (стул с высокой спинкой в орто путал даже зрячую модель)
    used_judge = False
    if col_flat and tiebreak is not None:
        # цвет не различил ПЕРЕД/ЗАД — судья выбирает строго между yaw и yaw+180 (пара
        # «топ-2 по цвету» могла быть 180 и 270 — это спор об ОСИ, а не о переде/заде)
        y0 = top1['yaw']
        y1 = (y0 + 180) % 360
        try:
            pick = tiebreak(y0, y1, photo)     # судье передаются УГЛЫ — кадры он строит сам
            if pick in (0, 1):
                chosen = y0 if pick == 0 else y1
                top1 = next((s2 for s2 in scored if s2['yaw'] == chosen),
                            {'yaw': chosen, 'iou': top1['iou'], 'col': top1['col']})
                margin = 0.0
                used_judge = True
        except Exception:  # noqa: BLE001 — судья упал: остаёмся на цвете
            pass
    if mesh_symmetric(parts) and col_flat:
        status = 'symmetric'
    elif top1['iou'] < 0.45:
        status = 'unobservable'
    elif margin >= 0.06:
        status = 'confident'
    else:
        status = 'unobservable'      # ТЕНЕВОЙ судья (q23): выбор пишем, confident НЕ даём
    return {'front_yaw': top1['yaw'], 'status': status, 'top1': top1,
            'judge_shadow': used_judge,
            'margin': round(margin, 3), 'scored': scored, 'version': ORIENT_VERSION}


if __name__ == '__main__':
    import io
    import urllib.request
    glb, url = sys.argv[1], sys.argv[2]
    ph = Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=60).read()))
    print(json.dumps(calibrate(glb, ph), ensure_ascii=False, indent=1))

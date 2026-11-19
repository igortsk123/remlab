#!/usr/bin/env python3
"""T-20261119-05/1, этап 3 (ПРИЁМКА пробы `pixal3d-tex`): совпал ли РИСУНОК краски с фото, или вышел «двойной узор» (рельеф формы один, краска другая).
Бесплатно, на процессоре. Для каждого GLB: камера по силуэту (как у `photo_project.py`), рендер без света в кадре фото, метрика `pattern_grad_ncc` (`tools/scout/pattern_metric.py`,
T-20261119-04/1) по маске «фасад» (почти плоские куски, смотрящие в камеру), ΔE00 до фото, и кадры: фото | каждый GLB — фасад 0° и 45° (приближение фасада 2×).
Читать так: `median`/`p10` pattern_grad_ncc → 1 — рисунок краски повторяет фото; ~0 — несвязанный (двойной узор или промах); сравнивать с контролем (исходный `clean.glb`
TRELLIS.2: его краска уже есть — это «было») и между вариантами (fit / official / fit+g3 / fit+s60). Порог «рисунок совпал» ставит приёмка, здесь только числа; глазами смотреть кадры.

  ~/venvs/scout/bin/python score_pixal_tex.py <photo.rgba.png> <out_dir> <model1.glb> [<model2.glb> ...]      → <out_dir>/score.json, frames-az000.png, frames-az045.png
  ~/venvs/scout/bin/python score_pixal_tex.py --selftest
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path[:0] = [SCOUT, os.path.join(SCOUT, 'salad')]
# `recolor_lp.py` (его берёт photo_project) есть только в main, на ветке пробы его нет: запасной путь — основная копия (`SCORE_EXTRA_PATH` меняет); ветка пробы после вливания main в нём не нуждается
sys.path.append(os.environ.get('SCORE_EXTRA_PATH', '/home/pakar/igor/remlab/tools/scout/salad'))

ZOOM = 2.0          # приближение фасада в кадре, раз
SIZE = 1024         # сторона кадра, пикселей


def score_one(glb: str, photo_rgba: str, yaw_pitch: tuple | None = None, size: int = SIZE) -> dict:
    """Числа по одному GLB (камера — по силуэту фото, либо заданная `yaw_pitch`, чтобы у всех вариантов кадр был ОДИН и тот же)."""
    import numpy as np
    import color_o2 as CO
    import color_steps as CS
    import mesh_render as MR
    import pattern_metric as PM
    import photo_project as PP
    import recolor_lp as RL
    P_in = CS.rgba(photo_rgba)
    r: dict = {'glb': glb}
    if yaw_pitch is None:
        pose = CS.best_pose(glb, P_in[..., 3] > 128)
        yaw, pitch = pose['yaw'], pose['pitch']
        r['pose_iou'] = pose['iou']
    else:
        yaw, pitch = yaw_pitch
    r.update(yaw=yaw, pitch=pitch)
    parts = MR.load_parts(glb)
    P = PP.projection(parts, yaw, pitch)
    G = PP.gather(parts, P, size)
    ids, _zb = PP.raster_ids(G, size)
    ralpha = ids >= 0
    prgb0, pmask0 = CO.align_photo(P_in, ralpha)
    prgb, pmask, al = RL.refine_align(prgb0, pmask0, ralpha)
    r['align'] = al
    if al['iou'] < RL.IOU_MIN:
        r['status'] = 'отказ: силуэт фото не совпал с рендером (IoU %.2f < %.2f)' % (al['iou'], RL.IOU_MIN)
        return r
    allowed, pinfo = PP.planar_mask(ids, G, size)
    fmask = allowed & CO.erode(ralpha) & CO.erode(pmask)
    ys, xs = np.nonzero(ralpha)
    facade = np.zeros_like(ralpha)
    facade[ys, xs] = G['cos'][ids[ys, xs]] >= PP.FACADE_COS
    now = np.asarray(RL.render_unlit(glb, yaw, pitch, size))
    r['de'] = PP.de_report(now[..., :3], now[..., 3] > 128, prgb, pmask, facade)
    r['pattern_grad_ncc'] = PM.pattern_grad_ncc(now[..., :3], prgb, fmask)
    r['facade_px'] = int(fmask.sum())
    r['planar_info'] = pinfo
    r['status'] = 'ok'
    r['_photo'] = (prgb, pmask)
    return r


def frames(glbs: list, yaw: float, pitch: float, photo, size: int = SIZE):
    """Строка кадров для одного ракурса: фото | каждый GLB (обычный Ламберт, как `lit_row`) — приближение фасада ZOOM раз по центру силуэта."""
    import numpy as np
    import mesh_render as MR
    from PIL import Image
    cells = []
    for src in [None] + list(glbs):
        if src is None:
            img = np.where(photo[1][..., None], photo[0], 255).astype(np.uint8)
        else:
            im = np.asarray(MR.render(MR.load_parts(src), yaw, pitch, (size, size)).convert('RGBA'))
            im = np.where(im[..., 3:4] > 0, im[..., :3], 255).astype(np.uint8)         # фон — белый, как у кадра фото
            img = im
        h, w = img.shape[:2]
        ch, cw = int(h / ZOOM), int(w / ZOOM)
        y0, x0 = (h - ch) // 2, (w - cw) // 2
        cells.append(np.asarray(Image.fromarray(img[y0:y0 + ch, x0:x0 + cw]).resize((cw, ch))))
    return np.concatenate(cells, 1)


def main(argv: list) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    from PIL import Image
    photo_png, out = argv[0], argv[1]
    glbs = argv[2:]
    os.makedirs(out, exist_ok=True)
    res = []
    base_pose = None
    ph = None
    for g in glbs:
        r = score_one(g, photo_png, base_pose)
        if base_pose is None and r.get('status') == 'ok':
            base_pose = (r['yaw'], r['pitch'])                       # камера первого GLB (контроль) — одна на всех
        photo = r.pop('_photo', None)
        res.append(r)
        pm = r.get('pattern_grad_ncc') or {}
        print(os.path.basename(g), r.get('status'), 'pattern median', pm.get('median'), 'p10', pm.get('p10'), 'de_med', (r.get('de') or {}).get('de_med'), flush=True)
        if photo is not None and ph is None:
            ph = photo
    json.dump(res, open(os.path.join(out, 'score.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
    if base_pose is not None and ph is not None:
        for name, dy in (('az000', 0.0), ('az045', 45.0)):
            Image.fromarray(frames(glbs, base_pose[0] + dy, base_pose[1], ph)).save(os.path.join(out, f'frames-{name}.png'))
    return 0


def selftest() -> int:
    """Без внешних файлов: переводы чисел в кадр и склейка (без рендера — он на pakardev)."""
    import numpy as np
    ok = True
    try:
        import mesh_render  # noqa: F401
    except ImportError:
        print('SKIP: нет mesh_render (проверяется на pakardev)')
        return 0
    ph = (np.zeros((SIZE, SIZE, 3), np.uint8), np.ones((SIZE, SIZE), bool))
    print('OK   модуль грузится', ph[0].shape)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(selftest() if sys.argv[1:] == ['--selftest'] else main(sys.argv[1:]))

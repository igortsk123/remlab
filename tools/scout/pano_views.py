#!/usr/bin/env python3
"""Три обычных кадра (налево / прямо / направо) ИЗ ОДНОЙ панорамы.

Владелец: «нельзя ли попросить 3 фотки за один запрос, тогда будут в одном стиле?»
Просить бесполезно — модель отдаёт варианты одного и того же вида. Но панорама УЖЕ снята одной
генерацией, поэтому три кадра можно не генерировать, а вырезать из неё с правильной перспективой:
стиль, свет и материалы совпадают по построению, и это бесплатно.

  ~/venvs/scout/bin/python pano_views.py 21                    # ±45°, объектив 65°
  ~/venvs/scout/bin/python pano_views.py 21 --yaw 55 --fov 70
"""
import json
import math
import os
import sys

import numpy as np
from PIL import Image

SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
NAMES = {-1: 'left', 0: 'center', 1: 'right'}
RU = {-1: 'налево', 0: 'прямо', 1: 'направо'}


def sample(pano: np.ndarray, cols: np.ndarray, rows: np.ndarray) -> np.ndarray:
    """Билинейная выборка из панорамы по дробным координатам."""
    H, W = pano.shape[:2]
    c0 = np.clip(np.floor(cols).astype(int), 0, W - 1)
    r0 = np.clip(np.floor(rows).astype(int), 0, H - 1)
    c1, r1 = np.clip(c0 + 1, 0, W - 1), np.clip(r0 + 1, 0, H - 1)
    fc, fr = (cols - c0)[..., None], (rows - r0)[..., None]
    top = pano[r0, c0] * (1 - fc) + pano[r0, c1] * fc
    bot = pano[r1, c0] * (1 - fc) + pano[r1, c1] * fc
    return (top * (1 - fr) + bot * fr).astype(np.uint8)


def crop_view(pano: np.ndarray, pano_fov: float, yaw_deg: float, fov_deg: float,
              size: tuple[int, int], nearest: bool = False) -> Image.Image:
    """Перспективный кадр с поворотом yaw из цилиндрической панорамы."""
    H, W = pano.shape[:2]
    ow, oh = size
    fv_pano = W / math.radians(pano_fov)          # пикселей на радиан — как при рендере карты
    f_out = (ow / 2) / math.tan(math.radians(fov_deg) / 2)
    xs, ys = np.meshgrid(np.arange(ow), np.arange(oh))
    dx = (xs - ow / 2) / f_out                    # направление луча в системе выходного кадра
    dy = (oh / 2 - ys) / f_out
    ang = np.arctan2(dx, 1.0) + math.radians(yaw_deg)
    horiz = np.hypot(dx, 1.0)
    cols = W / 2 + ang * fv_pano
    rows = H / 2 - fv_pano * dy / horiz
    if nearest:                                   # для масок: id нельзя усреднять
        H, W = pano.shape[:2]
        c = np.clip(np.round(cols).astype(int), 0, W - 1)
        r = np.clip(np.round(rows).astype(int), 0, H - 1)
        return Image.fromarray(pano[r, c])
    return Image.fromarray(sample(pano, cols, rows))


def main() -> None:
    n = int(sys.argv[1])
    yaw = float(sys.argv[sys.argv.index('--yaw') + 1]) if '--yaw' in sys.argv else 45.0
    fov = float(sys.argv[sys.argv.index('--fov') + 1]) if '--fov' in sys.argv else 65.0
    prefix = os.path.join(SCENE_DIR, f'scene{n}-P')
    meta = json.load(open(f'{prefix}-frame.json'))
    pano = np.asarray(Image.open(f'{prefix}-base-sdxl.jpg').convert('RGB'))
    out_w = int(pano.shape[1] * fov / meta['camera']['fov'])
    out_h = int(out_w * 2 / 3)
    for k, name in NAMES.items():
        img = crop_view(pano, meta['camera']['fov'], yaw * k, fov, (out_w, out_h))
        dst = f'{prefix}-{name}.jpg'
        img.save(dst, quality=92)
        print(f'{dst}  ({img.width}×{img.height}, взгляд {RU[k]})')


if __name__ == '__main__':
    main()

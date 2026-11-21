#!/usr/bin/env python3
"""T-20261119-88/2: ПАПКА `stages/` ДЛЯ ПРОИЗВОЛЬНОГО GLB НА ПРОЦЕССОРЕ (без видеокарты и без MV-Adapter) — вход цепочки «вариант 9» на HD-форме.

`photo_front.py` / `chain_v9.py` берут из `stages/` только кадр вида 0 (`render_view0/`: `mask.png`, `aoi_cos16.png`, `uv.npz`, `normal_cam.png`), `manifest.json` и `stage_loss.json` (регистрация фото → кадр).
Раньше эту папку писал воркер MV-Adapter (`worker_trellis.py: keep_stages`, nvdiffrast); для формы, у которой её нет (HD-форма TRELLIS.2), кадр строится здесь:
ортографическая камера вида 0 (как в воркере: окно ±ortho/2, элевация 0, кадр `--px`), форма вращается вокруг вертикали на `--yaw` градусов (поворот формы в кадр «спереди»; для комода 180, для дивана 0 — из
сводки/manifest прежнего прогона, параметр, а не код под товар), растеризация — стеклом в порядке глубины (`cv2.fillConvexPoly` с субпикселем): грань с номером на пиксель → барицентры → UV, сглаженная нормаль,
cos угла обзора. Регистрация фото → кадр — `stage_loss.register_photo` (по силуэту, ECC), как в `stage_loss.analyze`.

  stages_cpu.py --glb <GLB с UV> --photo <фото .rgba.png> --out-run <папка> [--yaw N] [--px 1536] [--ortho 1.1] [--uv-size 4096]
  → <out-run>/stages/{manifest.json, render_view0/{mask.png, aoi_cos16.png, normal_cam.png, uv.npz}}, <out-run>/stage_loss.json (регистрация)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.normpath(os.path.join(HERE, '..', '..')))

SHIFT = 4          # субпиксель fillConvexPoly: координаты ×2^SHIFT


def load_geom(glb: str) -> dict:
    """Одна геометрия GLB (как `tex_coverage.load_geoms`: трансформы сцены применены, вершины не сливаются): вершины, грани, UV, сглаженные нормали вершин (по площади граней)."""
    import tex_coverage as TC
    geo = TC.load_geoms(glb)
    if len(geo) != 1:
        raise ValueError(f'ожидалась одна геометрия, найдено {len(geo)}')
    V, F = np.asarray(geo[0]['V'], np.float64), np.asarray(geo[0]['F'], np.int64)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])          # длина = 2·площадь: взвешивание по площади
    N = np.zeros_like(V)
    for k in range(3):
        np.add.at(N, F[:, k], fn)
    N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
    return {'V': V, 'F': F, 'UV': np.asarray(geo[0]['UV'], np.float64), 'N': N}


def render(geo: dict, yaw: float = 0.0, px: int = 1536, ortho: float = 1.1) -> dict:
    """Кадр вида 0 — как у воркера: форма в куб `worker_trellis.to_cube(V, yaw)` (поворот, центр габарита в ноль, наибольшая сторона 1), камера вида 0 ортографическая ±ortho/2, смотрит на сторону +Z, вверх +Y,
    вправо +X (`worker_trellis.mv_ortho_uv`). Результат: id грани на пиксель (−1 — фон), UV (u, v_flipped), сглаженная нормаль в камере, cos = |n_z| (порядок обхода граней у сеток TRELLIS не всегда «наружу»,
    видимая поверхность по построению смотрит в камеру — как в `tex_coverage`)."""
    import cv2
    import worker_trellis as W
    P, _c, _s, R = W.to_cube(geo['V'], yaw)
    V = P
    N = geo['N'] @ R.T
    F = geo['F']
    sx = (V[:, 0] + ortho / 2) / ortho * px          # пиксель кадра: столбец
    sy = (ortho / 2 - V[:, 1]) / ortho * px          # строка (0 — верх)
    z = V[:, 2]
    tri = np.stack([sx[F], sy[F]], -1)               # (nF, 3, 2)
    depth = z[F].mean(1)
    order = np.argsort(depth, kind='stable')         # дальние (z меньше) первыми, ближние рисуются поверх
    ids = np.full((px, px), -1, np.int32)
    k = float(1 << SHIFT)
    pts = np.round(tri * k - 0.5 * k).astype(np.int32)   # центр пикселя — (x+0.5): смещение под сетку пикселей fillConvexPoly
    for f in order:
        cv2.fillConvexPoly(ids, pts[f], int(f), lineType=cv2.LINE_8, shift=SHIFT)
    mask = ids >= 0
    ys, xs = np.nonzero(mask)
    f = ids[ys, xs].astype(np.int64)
    a, b, c = F[f, 0], F[f, 1], F[f, 2]
    A_, B_, C_ = np.stack([sx[a], sy[a]], 1), np.stack([sx[b], sy[b]], 1), np.stack([sx[c], sy[c]], 1)
    p = np.stack([xs + 0.5, ys + 0.5], 1)
    den = (B_[:, 0] - A_[:, 0]) * (C_[:, 1] - A_[:, 1]) - (B_[:, 1] - A_[:, 1]) * (C_[:, 0] - A_[:, 0])
    den = np.where(np.abs(den) < 1e-12, 1e-12, den)
    wa = ((B_[:, 0] - p[:, 0]) * (C_[:, 1] - p[:, 1]) - (B_[:, 1] - p[:, 1]) * (C_[:, 0] - p[:, 0])) / den
    wb = ((C_[:, 0] - p[:, 0]) * (A_[:, 1] - p[:, 1]) - (C_[:, 1] - p[:, 1]) * (A_[:, 0] - p[:, 0])) / den
    wc = 1.0 - wa - wb
    wa, wb, wc = (np.clip(w, 0.0, 1.0) for w in (wa, wb, wc))     # пиксель на границе грани: субпиксельный допуск fillConvexPoly
    s = wa + wb + wc
    wa, wb, wc = wa / s, wb / s, wc / s
    UV = geo['UV']
    u = wa * UV[a, 0] + wb * UV[b, 0] + wc * UV[c, 0]
    v = wa * UV[a, 1] + wb * UV[b, 1] + wc * UV[c, 1]
    uv = np.zeros((px, px, 2), np.float32)
    uv[ys, xs, 0] = u
    uv[ys, xs, 1] = 1.0 - v                                       # v_flipped: строка карты = v_flipped·размер (как uv.npz воркера)
    n = wa[:, None] * N[a] + wb[:, None] * N[b] + wc[:, None] * N[c]
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    ncam = np.zeros((px, px, 3), np.float32)
    ncam[ys, xs] = n * np.where(n[:, 2:3] < 0, -1.0, 1.0)            # к камере (см. docstring)
    cos = np.clip(np.abs(ncam[..., 2]), 0.0, 1.0)
    return {'ids': ids, 'mask': mask, 'uv': uv, 'normal': ncam, 'cos': cos}


def write_stages(r: dict, out_run: str, photo_path: str | None, yaw: float, px: int, ortho: float, uv_size: int, glb: str) -> dict:
    from PIL import Image
    import stage_loss as SL
    st = os.path.join(out_run, 'stages')
    rd = os.path.join(st, 'render_view0')
    os.makedirs(rd, exist_ok=True)
    Image.fromarray(r['mask'].astype(np.uint8) * 255).save(os.path.join(rd, 'mask.png'))
    Image.fromarray(((r['normal'] * 0.5 + 0.5).clip(0, 1) * 255 * r['mask'][..., None]).round().astype(np.uint8)).save(os.path.join(rd, 'normal_cam.png'))
    Image.fromarray((r['cos'] * 65535).round().astype(np.uint16)).save(os.path.join(rd, 'aoi_cos16.png'))
    np.savez_compressed(os.path.join(rd, 'uv.npz'), uv=r['uv'], mask=r['mask'])
    man = {'uv_size': uv_size, 'render_px': px, 'yaw_deg': yaw, 'camera': {'view': 0, 'elevation_deg': 0, 'ortho': ortho, 'distance': 1.0}, 'uv_flip_v': True,
           'uv_note': 'uv.npz: uv[y,x]=(u, v_flipped) — столбец u·размер, строка v_flipped·размер (строка 0 — верх картинки карты)', 'source': 'stages_cpu.py (CPU, без MV-Adapter)', 'glb': glb}
    json.dump(man, open(os.path.join(st, 'manifest.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    reg = None
    if photo_path:
        photo = SL.read_rgba(photo_path)
        reg = SL.register_photo(photo[..., 3] > 127, r['mask'])
        sl = {'photo': photo_path, 'stages_dir': st, 'frame_px': px,
              'registration': {k: (v if k != 'P' else [round(float(x), 6) for x in np.asarray(v).ravel()]) for k, v in reg.items()}}
        json.dump(sl, open(os.path.join(out_run, 'stage_loss.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return {'stages': st, 'registration': None if reg is None else {k: v for k, v in reg.items() if k != 'P'}, 'mask_px': int(r['mask'].sum())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb', required=True)
    ap.add_argument('--photo', default=None)
    ap.add_argument('--out-run', required=True)
    ap.add_argument('--yaw', type=float, default=0.0)
    ap.add_argument('--px', type=int, default=1536)
    ap.add_argument('--ortho', type=float, default=1.1)
    ap.add_argument('--uv-size', type=int, default=4096)
    a = ap.parse_args()
    r = render(load_geom(a.glb), a.yaw, a.px, a.ortho)
    print(json.dumps(write_stages(r, a.out_run, a.photo, a.yaw, a.px, a.ortho, a.uv_size, a.glb), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())

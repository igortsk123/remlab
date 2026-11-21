#!/usr/bin/env python3
"""Сторож палитры итоговой текстуры (T-20261121-174/1): «малиновая заглушка» вне палитры фото.

ЗАЧЕМ. Покраска (StableGen/Qwen) красит невидимое «служебной заливкой» — сплошным малиновым («Replace all solid magenta areas…», `stablegen/sg_views.py`).
Если модель заливку не заменила, малиновое проецируется в атлас и покупатель видит розовую панель (кровать №4 страницы compare-paint-1120: правая панель
каркаса и торец изголовья). Сторож ВИДОВ (`stablegen/sg_guard.py`, T-154/1) смотрит кадры до проекции; итоговый атлас никто не мерил, а этап 9 ловил только
«чёрное/белое» (`tex_coverage`). Этот модуль меряет то, что видно покупателю, на ИТОГОВОМ GLB: долю ПЛОЩАДИ поверхности, чей тексель — малиновая заглушка.

ЧТО ДЕЛАЕТ. `texel_mask` — оттенок «R и B заметно выше G, G мал, насыщенно»: после проекции и запекания заливка темнеет и плывёт ((158,11,115) вместо (255,0,255)),
поэтому тест по оттенку, а не по точному цвету. `surface_share` — для каждой грани текстура берётся в центре грани по UV (повтор — по модулю 1), вес грани — её
площадь. `photo_share` — доля тех же малиновых пикселей на фото товара (розовый диван — законный цвет): допуск = порог + доля на фото. Пороги — `rules/stablegen-view-guard.json`
(блоки `magenta` и `magenta_baked`: ОДИН файл и один порог доли для видов до проекции и для атласа после; данные, не код). Идентификаторов товаров нет: правило на любой товар и любой будущий прогон.

  paint_palette.py <glb> [фото.png]     напечатать долю (для разбора)
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np


HERE = os.path.dirname(os.path.abspath(__file__))


def load_guard(path: str | None = None) -> dict:
    """Общие правила малинового (`stablegen-view-guard.json`) — тот же файл, что читает сторож видов `stablegen/sg_guard.py`."""
    return json.load(open(path or os.path.join(HERE, 'rules', 'stablegen-view-guard.json'), encoding='utf-8'))


def thresholds(guard: dict) -> tuple[float, float]:
    """(жёсткий порог доли площади, мягкий): жёсткий — `magenta.obj_frac_max` (один на виды и атлас), мягкий — `magenta_baked.soft_frac`."""
    return float(guard['magenta']['obj_frac_max']), float(guard['magenta_baked']['soft_frac'])


def texel_mask(rgb: np.ndarray, p: dict) -> np.ndarray:
    """Малиновая заглушка по оттенку (`p` — блок `magenta_baked` общих правил): R и B выше G, G мал относительно меньшего из R/B, достаточно ярко."""
    a = rgb[..., :3].astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return ((r > p['r_min']) & (b > p['b_min']) & (g < p['g_ratio_max'] * np.minimum(r, b))
            & (r - g > p['rg_min']) & (b - g > p['bg_min']) & (a.max(-1) > p['v_min']))


def photo_share(photo: str | None, p: dict) -> float:
    """Доля малиновых пикселей среди пикселей ПРЕДМЕТА на фото (прозрачное и почти белый фон — не считаем). Нет фото/не читается — 0 (допуска нет)."""
    if not photo or not os.path.exists(photo):
        return 0.0
    from PIL import Image
    try:
        im = Image.open(photo)
        rgba = np.asarray(im.convert('RGBA'))
    except OSError:
        return 0.0
    obj = rgba[..., 3] > 128
    if not obj.any():
        return 0.0
    m = texel_mask(rgba[..., :3], p)
    return float((m & obj).sum() / obj.sum())


def surface_share(glb: str, p: dict) -> dict:
    """Доля площади поверхности с малиновым тексельем: {share, atlas_share, rgb}. Текстуры нет — share None (не измерено)."""
    import trimesh
    sc = trimesh.load(glb, force='scene')
    tot = mag = 0.0
    atlas, rgb = [], None
    for g in sc.geometry.values():
        vis = g.visual
        mat = getattr(vis, 'material', None)
        im = getattr(mat, 'baseColorTexture', None) if mat is not None else None
        uv = getattr(vis, 'uv', None)
        if im is None or uv is None:
            continue
        a = np.asarray(im.convert('RGB'))
        m = texel_mask(a, p)
        atlas.append(float(m.mean()))
        if m.any() and rgb is None:
            rgb = a[m].reshape(-1, 3).mean(0).round().astype(int).tolist()
        h, w = m.shape
        c = uv[g.faces].mean(1) % 1.0
        x = np.clip((c[:, 0] * w).astype(int), 0, w - 1)
        y = np.clip(((1.0 - c[:, 1]) * h).astype(int), 0, h - 1)
        area = g.area_faces
        tot += float(area.sum())
        mag += float(area[m[y, x]].sum())
    if not tot:
        return {'share': None, 'atlas_share': None, 'rgb': None}
    return {'share': mag / tot, 'atlas_share': max(atlas), 'rgb': rgb}


def run_palette(glb: str, photo: str | None, guard: dict) -> dict:
    """Измерение для этапа 9: {share, photo_share, atlas_share, rgb}. `guard` — общие правила малинового (`load_guard()`)."""
    p = guard['magenta_baked']
    r = surface_share(glb, p)
    r['photo_share'] = photo_share(photo, p)
    return r


if __name__ == '__main__':
    here = os.path.dirname(os.path.abspath(__file__))
    out = run_palette(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None, load_guard())
    print(json.dumps(out, ensure_ascii=False))

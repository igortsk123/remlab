#!/usr/bin/env python3
"""T-93: сырая маска модели → ТА ЖЕ цепочка после сети, что в боевом `_cut_chain` (гибрид → components.clean/fill_holes/prune_attached) → чистка островков.
Сравнение моделей ПОД гибридом на HD-фото (диван, комод). Печатает метрики и пишет розовые кадры низа."""
import sys

import numpy as np
from PIL import Image
from scipy import ndimage

sys.path.insert(0, '/home/pakar/igor/remlab/.claude/worktrees/input-1119/tools/scout/salad')
sys.path.insert(0, '/home/pakar/igor/remlab/.claude/worktrees/input-1119/tools/scout/salad/trellis/t93_input')
import components  # noqa: E402
import hybrid_mask  # noqa: E402
from clean_islands import clean_islands  # noqa: E402

ROOT = '/home/pakar/remlab-logs/t93-1119'
ROLE = {'114667_11634594969038554503': 'диван', '112923_13224664101879413845': 'комод'}
MODELS = ['birefnet_stretch_B1024', 'ben2_stretch_B1024', 'birefnet_hr_stretch_B2048']
PINK = np.array([255, 0, 170], np.float32)


def chain(src, mask, role):
    cut = src.convert('RGBA')
    cut.putalpha(mask.resize(src.size) if mask.size != src.size else mask)
    refined, info = hybrid_mask.refine(src, cut, role=role)
    a = np.asarray(refined)[..., 3].astype(np.float32) / 255.0
    cleaned, _ = components.clean(a)
    cleaned, _ = components.fill_holes_unlike_bg(cleaned, np.asarray(src), role=role)
    cleaned, _ = components.prune_attached(cleaned, role=role)
    out = Image.fromarray(np.dstack([np.asarray(refined)[..., :3], (np.clip(cleaned, 0, 1) * 255).astype(np.uint8)]), 'RGBA')
    return out, info


def metrics(rgba, src):
    a = np.asarray(rgba)[..., 3].astype(np.float32) / 255.0
    rgb = np.asarray(src).astype(np.float32)
    lab, n = ndimage.label(a > 0.04, structure=np.ones((3, 3)))
    sizes = ndimage.sum(np.ones_like(a), lab, range(1, n + 1)) if n else [0]
    body = lab == (1 + int(np.argmax(sizes)))
    ys = np.where(body.any(axis=1))[0]
    y0, y1 = int(ys.min()), int(ys.max())
    band = np.zeros_like(body)
    band[int(y1 - 0.12 * (y1 - y0)):y1 + 1] = True
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    pale = band & (a > 0.5) & ((mx - mn) < 22) & (mx > 150)
    return {'solid': int((a > 0.5).sum()), 'semi%': round(float(((a > 0.04) & (a < 0.96)).sum() / max((a > 0.04).sum(), 1)) * 100, 2),
            'comps': int(n), 'outside': int(((a > 0.04) & ~body).sum()), 'pale_bottom': int(pale.sum())}


for key, role in ROLE.items():
    src = None
    for e in ('jpg', 'png', 'webp'):
        try:
            src = Image.open(f'{ROOT}/photos/{key}/B_original_picture.{e}').convert('RGB')
            break
        except FileNotFoundError:
            pass
    print('==', key, role, src.size)
    for m in MODELS:
        mask = Image.open(f'{ROOT}/masks/{m}/{key}.mask.png').convert('L')
        raw = src.convert('RGBA')
        raw.putalpha(mask.resize(src.size))
        out, info = chain(src, mask, role)
        out2, rep = clean_islands(out)
        r0, r1, r2 = metrics(raw, src), metrics(out, src), metrics(out2, src)
        print(f'{m:28s} сырая {r0}\n{"":28s} +гибрид/компоненты {r1}\n{"":28s} +чистка островков {r2} (срезано {len(rep["removed"])}) uniform_bg={info.get("uniform_bg")} err={info.get("hybrid_error")}')
        a = np.asarray(out2)[..., 3:4].astype(np.float32) / 255.0
        comp = (np.asarray(out2)[..., :3] * a + PINK * (1 - a)).clip(0, 255).astype(np.uint8)
        ys = np.where(a[..., 0] > 0.5)[0]
        h = ys.max() - ys.min()
        Image.fromarray(comp[max(0, int(ys.max() - 0.3 * h)):ys.max() + 30]).save(f'{ROOT}/cut/{key}_{m}_UNDERHYBRID_bottom.png')

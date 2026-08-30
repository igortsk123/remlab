#!/usr/bin/env python3
"""Чистка текстуры внутри GLB: крапинки вне палитры доливаются соседями.

Диван 114667 (владелец 30.08): белые крапинки на обивке. Это не вырезка (она чистая), а
покраска: 6 видов не докрашивают складки и стыки развёртки — текселя остаются цвета
подложки (белые), швы UV подтекают. Правило то же, что у фильтра обломков: чинится только
то, что резко ВНЕ палитры товара и мелко; белая мебель защищена доминантой (там «крапинки»
и есть цвет товара — фильтр молчит).
"""
import io

import numpy as np
from PIL import Image


def despeckle_glb(glb_path: str) -> int:
    """Возвращает число закрашенных пикселей по всем текстурам GLB."""
    import cv2
    from pygltflib import GLTF2
    g = GLTF2().load(glb_path)
    if not g.images:
        return 0
    # ТОЛЬКО baseColor (Codex q26): проход по всем картинкам портил normal и metallic —
    # inpaint по карте нормалей это геометрический брак, хоть и невидимый в списке файлов.
    base_idx = set()
    for mat in g.materials or []:
        pmr = getattr(mat, 'pbrMetallicRoughness', None)
        bct = getattr(pmr, 'baseColorTexture', None) if pmr else None
        if bct is not None and bct.index is not None:
            src = g.textures[bct.index].source
            if src is not None:
                base_idx.add(src)
    blob = g.binary_blob()
    total = 0
    new_chunks = {}
    for idx, img in enumerate(g.images):
        if idx not in base_idx:
            continue
        if img.bufferView is None:
            continue
        bv = g.bufferViews[img.bufferView]
        raw = blob[bv.byteOffset:bv.byteOffset + bv.byteLength]
        try:
            pil = Image.open(io.BytesIO(raw)).convert('RGB')
        except Exception:  # noqa: BLE001
            continue
        a = np.asarray(pil).astype(np.float32)
        h, w = a.shape[:2]
        # доминанта по несветлым пикселям; если товар сам белый — чинить нечего
        flat = a.reshape(-1, 3)
        dom = np.median(flat, axis=0)
        if float(np.linalg.norm(dom - 255)) < 60:
            continue
        dist = np.linalg.norm(a - dom, axis=2)
        near_white = (a.min(axis=2) > 205) & (dist > 90)
        if not near_white.any():
            continue
        # только МЕЛКИЕ пятна: большое белое — законная деталь (подушка, ножка)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(near_white.astype(np.uint8), 8)
        mask = np.zeros((h, w), np.uint8)
        cap = 0.001 * h * w                        # пятно крупнее 0.1% кадра не трогаем
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] > cap:
                continue
            # кольцо вокруг пятна должно быть ОДНОРОДНЫМ и в палитре: иначе это стык
            # UV-островов или легальная белая деталь — не трогаем (Codex q26)
            x, y, ww, hh = stats[i, cv2.CC_STAT_LEFT], stats[i, cv2.CC_STAT_TOP], stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
            pad2 = 4
            y0, y1 = max(0, y - pad2), min(h, y + hh + pad2)
            x0, x1 = max(0, x - pad2), min(w, x + ww + pad2)
            ring = a[y0:y1, x0:x1][~(lab[y0:y1, x0:x1] == i)]
            if len(ring) < 8:
                continue
            ring_std = float(ring.std(axis=0).max())
            ring_dist = float(np.linalg.norm(np.median(ring, axis=0) - dom))
            if ring_std < 35 and ring_dist < 70:
                mask[lab == i] = 255
        if not mask.any():
            continue
        fixed = cv2.inpaint(a.astype(np.uint8), mask, 3, cv2.INPAINT_TELEA)
        total += int((mask > 0).sum())
        buf = io.BytesIO()
        Image.fromarray(fixed).save(buf, format='PNG')
        new_chunks[idx] = buf.getvalue()
    if not new_chunks:
        return 0
    # пересборка бинарного блоба: заменённые картинки кладём в конец, остальное не трогаем
    blob = bytearray(blob)
    for idx, data in new_chunks.items():
        bv = g.bufferViews[g.images[idx].bufferView]
        off = len(blob)
        pad = (4 - off % 4) % 4
        blob.extend(b'\x00' * pad)
        off = len(blob)
        blob.extend(data)
        bv.byteOffset, bv.byteLength = off, len(data)
        g.images[idx].mimeType = 'image/png'
    g.buffers[0].byteLength = len(blob)
    g.set_binary_blob(bytes(blob))
    g.save(glb_path)
    return total

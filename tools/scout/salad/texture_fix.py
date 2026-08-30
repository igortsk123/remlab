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


def repaint_cut_edge(glb_path: str, seam_frac: float = 0.08) -> int:
    """Закраска кромки среза (владелец 30.08: «сгладить, закрасить поровнее»).

    Срез плиты открывает грани, чья развёртка попала в белую подложку покраски или в
    тень — по низу модели идёт рваная светлая полоса с чёрными пятнами. Берём UV-текселя
    граней нижней зоны (низ < seam_frac высоты), считаем медианный цвет обивки по валидным
    текселям зоны и перекрашиваем ВЫБРОСЫ (сильно светлее/темнее/дальше от медианы) в эту
    медиану, затем лёгкое сглаживание внутри зоны. Выше зоны не трогаем ни пикселя.
    Возвращает число перекрашенных пикселей."""
    import cv2
    import trimesh
    from pygltflib import GLTF2
    m = trimesh.load(glb_path, force='mesh')
    uv = getattr(m.visual, 'uv', None)
    if uv is None or not len(uv):
        return 0
    V, F = np.asarray(m.vertices), np.asarray(m.faces)
    lo, hi = V.min(axis=0), V.max(axis=0)
    ext = max(float(hi[1] - lo[1]), 1e-6)
    low = F[V[F][:, :, 1].max(axis=1) < lo[1] + seam_frac * ext]
    if not len(low):
        return 0
    g = GLTF2().load(glb_path)
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
        if idx not in base_idx or img.bufferView is None:
            continue
        bv = g.bufferViews[img.bufferView]
        raw = blob[bv.byteOffset:bv.byteOffset + bv.byteLength]
        try:
            pil = Image.open(io.BytesIO(raw)).convert('RGB')
        except Exception:  # noqa: BLE001
            continue
        a = np.asarray(pil).astype(np.float32)
        h, w = a.shape[:2]
        px = np.stack([np.clip(np.asarray(uv)[:, 0] % 1.0 * (w - 1), 0, w - 1),
                       np.clip(np.asarray(uv)[:, 1] % 1.0 * (h - 1), 0, h - 1)], axis=1)
        zone = np.zeros((h, w), np.uint8)
        tris = px[low].astype(np.int32)          # (nF,3,2) в пикселях текстуры
        cv2.fillPoly(zone, list(tris), 1)
        zone = cv2.dilate(zone, np.ones((3, 3), np.uint8))
        zm = zone.astype(bool)
        if not zm.any():
            continue
        zone_px = a[zm]
        dom = np.median(a.reshape(-1, 3), axis=0)
        dist_dom = np.linalg.norm(zone_px - dom, axis=1)
        valid = zone_px[dist_dom < 80]
        med = np.median(valid, axis=0) if len(valid) > 50 else dom
        if float(np.linalg.norm(med - 255)) < 60:
            continue                              # белая мебель: «выбросы» и есть её цвет
        dist = np.linalg.norm(a - med, axis=2)
        outlier = zm & ((dist > 85) | (a.min(axis=2) > 205) | (a.max(axis=2) < 45))
        if outlier.any():
            a[outlier] = med
            total += int(outlier.sum())
        sm = cv2.GaussianBlur(a, (5, 5), 0)
        a[zm] = sm[zm]                            # приглаживаем только зону кромки
        buf = io.BytesIO()
        Image.fromarray(a.astype(np.uint8)).save(buf, format='PNG')
        new_chunks[idx] = buf.getvalue()
    if not new_chunks:
        return 0
    blob = bytearray(blob)
    for idx, data in new_chunks.items():
        bv = g.bufferViews[g.images[idx].bufferView]
        pad = (4 - len(blob) % 4) % 4
        blob.extend(b'\x00' * pad)
        off = len(blob)
        blob.extend(data)
        bv.byteOffset, bv.byteLength = off, len(data)
        g.images[idx].mimeType = 'image/png'
    g.buffers[0].byteLength = len(blob)
    g.set_binary_blob(bytes(blob))
    g.save(glb_path)
    return total


def match_photo_color(glb_path: str, cutout_png: str) -> float:
    """Цвет меша к цвету фото (владелец 30.08: «модель искажает цвета — сделай, если можно»).

    Покраска Hunyuan уводит тон (синее→фиолетовое, матовое→глянцевый блик). Классический
    перенос статистики Рейнхарда в LAB: хром (a, b) текстуры приводится к хрому вырезки
    полностью, светлота — только средним и вполсилы (запечённые тени/блики не трогаем).
    Сдвиг каждого канала ограничен, при малом расхождении (ΔE<6) не делаем ничего.
    Возвращает применённый средний сдвиг ΔE (0 — не трогали)."""
    import cv2
    from pygltflib import GLTF2
    cut = np.asarray(Image.open(cutout_png).convert('RGBA')).astype(np.float32)
    m = cut[..., 3] > 150
    if m.sum() < 500:
        return 0.0
    photo_lab = cv2.cvtColor(cut[..., :3].astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    pm, ps = photo_lab[m].mean(axis=0), photo_lab[m].std(axis=0) + 1e-3
    g = GLTF2().load(glb_path)
    base_idx = set()
    for mat in g.materials or []:
        pmr = getattr(mat, 'pbrMetallicRoughness', None)
        bct = getattr(pmr, 'baseColorTexture', None) if pmr else None
        if bct is not None and bct.index is not None:
            src = g.textures[bct.index].source
            if src is not None:
                base_idx.add(src)
    import base64
    blob = g.binary_blob()
    new_chunks = {}
    data_uris = {}
    applied = 0.0
    for idx, img in enumerate(g.images):
        if idx not in base_idx:
            continue
        # конвертер покраски кладёт карты как data:URI, ножи (trimesh) — как bufferView;
        # поддерживаем оба, иначе фикc молча пропускает свежие модели
        raw = None
        if img.bufferView is not None:
            bv = g.bufferViews[img.bufferView]
            raw = blob[bv.byteOffset:bv.byteOffset + bv.byteLength]
        elif (img.uri or '').startswith('data:image'):
            raw = base64.b64decode(img.uri.split(',', 1)[1])
        if raw is None:
            continue
        try:
            pil = Image.open(io.BytesIO(raw)).convert('RGB')
        except Exception:  # noqa: BLE001
            continue
        a = np.asarray(pil).astype(np.uint8)
        lab = cv2.cvtColor(a, cv2.COLOR_RGB2LAB).astype(np.float32)
        tm = a.max(axis=2) > 15                          # пустоту развёртки не считаем
        if tm.sum() < 500:
            continue
        # СВЕТЛОТА — гистограммным сведением к фото (тумба 112923_813…, владелец 30.08:
        # «сильно тёмное»): сдвиг среднего не лечит запечённые тени — их ДОЛЯ больше, чем
        # на фото. Квантильное отображение переносит весь профиль света (тени, средние,
        # света) на фотографический; предел ±35 L на тексель защищает блики и глубокие
        # складки от переворота.
        q = np.linspace(0, 1, 256)
        src_q = np.quantile(lab[tm][:, 0], q)
        ph_q = np.quantile(photo_lab[m][:, 0], q)
        l0 = lab[..., 0]
        lab[..., 0] = np.clip(np.interp(l0, src_q, ph_q), l0 - 50, l0 + 50)
        lshift = float(np.abs(lab[tm][:, 0] - l0[tm]).mean())
        tmean, tstd = lab[tm].mean(axis=0), lab[tm].std(axis=0) + 1e-3
        de = float(np.linalg.norm(tmean - pm))
        if de < 6 and lshift < 3:            # и хром, и свет уже совпадают — не трогаем
            continue
        out = lab.copy()
        # хром (a, b) — перенос статистики Рейнхарда; светлота уже сведена выше
        for c, (w, cap) in ((1, (1.0, 22)), (2, (1.0, 22))):
            shift = np.clip((pm[c] - tmean[c]) * w, -cap, cap)
            k = float(np.clip(ps[c] / tstd[c], 0.6, 1.6))
            out[..., c] = (lab[..., c] - tmean[c]) * k + tmean[c] + shift
        fixed = cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
        fixed = np.where(tm[..., None], fixed, a)
        applied = de
        buf = io.BytesIO()
        Image.fromarray(fixed).save(buf, format='PNG')
        if g.images[idx].bufferView is not None:
            new_chunks[idx] = buf.getvalue()
        else:
            data_uris[idx] = buf.getvalue()
    if not new_chunks and not data_uris:
        return 0.0
    for idx, data in data_uris.items():
        g.images[idx].uri = 'data:image/png;base64,' + base64.b64encode(data).decode()
    if new_chunks:
        blob = bytearray(blob)
        for idx, data in new_chunks.items():
            bv = g.bufferViews[g.images[idx].bufferView]
            blob.extend(b'\x00' * ((4 - len(blob) % 4) % 4))
            off = len(blob)
            blob.extend(data)
            bv.byteOffset, bv.byteLength = off, len(data)
            g.images[idx].mimeType = 'image/png'
        g.buffers[0].byteLength = len(blob)
        g.set_binary_blob(bytes(blob))
    g.save(glb_path)
    return round(applied, 1)

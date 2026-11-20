"""Сторож вида StableGen до проекции (T-20261120-154/1; Codex 20.11 `~/remlab-logs/t154-1120/answer.md`). Чистые функции (numpy; без bpy) — проверяются в unittest.

Зачем: служебная заливка «не покрашено» (малиновая) протекает через Qwen на задних видах; плохой вид проецируется и становится контекстом следующих (кровать 0/3,6/31/42 %).
Что делает: по готовой картинке вида считает долю «малинового» по предмету + крупный связный кусок (широкий тест оттенка, не точное (255,0,255)),
сверяет цвет вида с принятым соседним видом и с цветом каталога. Пороги и справочник цветов — данные `rules/stablegen-view-guard.json`; ни ID товаров, ни правил «если шкаф» тут нет."""
from __future__ import annotations

import io
import json
import math
import os

import numpy as np

RULES_PATH = os.environ.get('SG_VIEW_GUARD_RULES') or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'rules', 'stablegen-view-guard.json')


def load_rules(path: str | None = None) -> dict:
    with open(path or RULES_PATH, encoding='utf-8') as fh:
        return json.load(fh)


def _decode_png(png: bytes) -> np.ndarray:
    """Минимальный разбор PNG (8 бит, без чересстрочности: так отдаёт ComfyUI) — в Blender нет Pillow, а bpy.data.images искажает цветовое пространство."""
    import struct
    import zlib
    if png[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError('не PNG')
    pos, idat, hdr = 8, b'', None
    while pos < len(png):
        ln, typ = struct.unpack('>I4s', png[pos:pos + 8])
        data = png[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b'IHDR':
            hdr = struct.unpack('>IIBBBBB', data)
        elif typ == b'IDAT':
            idat += data
        elif typ == b'IEND':
            break
    w, h, depth, ctype, _c, _f, interlace = hdr
    if depth != 8 or interlace != 0 or ctype not in (0, 2, 4, 6):
        raise ValueError(f'PNG не поддержан: глубина {depth}, тип {ctype}, чересстрочность {interlace}')
    ch = {0: 1, 2: 3, 4: 2, 6: 4}[ctype]
    raw = np.frombuffer(zlib.decompress(idat), dtype=np.uint8)
    stride = w * ch
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = np.zeros(stride, dtype=np.int32)
    p = 0
    for y in range(h):
        f = raw[p]
        line = raw[p + 1:p + 1 + stride].astype(np.int32)
        p += 1 + stride
        if f == 0:
            cur = line
        elif f == 1:                                            # Sub
            cur = line.copy()
            for i in range(ch, stride):
                cur[i] = (cur[i] + cur[i - ch]) & 255
        elif f == 2:                                            # Up
            cur = (line + prev) & 255
        elif f == 3:                                            # Average
            cur = line.copy()
            for i in range(stride):
                left = cur[i - ch] if i >= ch else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 255
        else:                                                   # Paeth
            cur = line.copy()
            for i in range(stride):
                a_ = cur[i - ch] if i >= ch else 0
                c_ = prev[i - ch] if i >= ch else 0
                b_ = prev[i]
                pa, pb, pc = abs(b_ - c_), abs(a_ - c_), abs(a_ + b_ - 2 * c_)
                pr = a_ if (pa <= pb and pa <= pc) else (b_ if pb <= pc else c_)
                cur[i] = (cur[i] + pr) & 255
        out[y] = cur
        prev = cur
    img = out.reshape(h, w, ch)
    if ch in (1, 2):
        return np.repeat(img[..., :1], 3, axis=2)
    return img[..., :3]


def decode(png: bytes) -> np.ndarray:
    """PNG-байты → uint8 RGB (H, W, 3). Pillow, если есть; иначе OpenCV (его импортирует сам аддон — он есть в Blender); иначе свой (медленный) разбор."""
    try:
        from PIL import Image
        return np.array(Image.open(io.BytesIO(png)).convert('RGB'))
    except ImportError:
        pass
    try:
        import cv2
        a = cv2.imdecode(np.frombuffer(png, dtype=np.uint8), cv2.IMREAD_COLOR)
        if a is not None:
            return a[..., ::-1].copy()
    except ImportError:
        pass
    return _decode_png(png)


def object_mask(rgb: np.ndarray, rules: dict) -> np.ndarray:
    """Предмет = пиксели, заметно отличные от фона; фон — медиана по рамке картинки (виды Qwen идут на сером/белом фоне)."""
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]]).astype(np.float32)
    bg = np.median(border, axis=0)
    d = np.sqrt(((rgb.astype(np.float32) - bg) ** 2).sum(axis=2))
    return d > rules['magenta']['background_dist']


def magenta_mask(rgb: np.ndarray, rules: dict) -> np.ndarray:
    m = rules['magenta']
    r, g, b = (rgb[..., i].astype(np.int32) for i in range(3))
    return (r > m['r_min']) & (b > m['b_min']) & (g < m['g_ratio_max'] * np.minimum(r, b))


def largest_component_frac(mask: np.ndarray, rules: dict) -> float:
    """Площадь наибольшего связного куска маски как доля площади картинки (сетка grid×grid, 8-связность — быстро и без scipy: в Blender его нет)."""
    n = int(rules['magenta']['grid'])
    h, w = mask.shape
    gh, gw = max(1, min(n, h)), max(1, min(n, w))
    ys, xs = np.linspace(0, h, gh + 1).astype(int), np.linspace(0, w, gw + 1).astype(int)
    cell = np.zeros((gh, gw), bool)
    for i in range(gh):
        row = mask[ys[i]:ys[i + 1]]
        for j in range(gw):
            blk = row[:, xs[j]:xs[j + 1]]
            cell[i, j] = blk.size > 0 and blk.mean() > 0.3
    seen = np.zeros_like(cell)
    best = 0
    for i in range(gh):
        for j in range(gw):
            if cell[i, j] and not seen[i, j]:
                stack, size = [(i, j)], 0
                seen[i, j] = True
                while stack:
                    y, x = stack.pop()
                    size += 1
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            yy, xx = y + dy, x + dx
                            if 0 <= yy < gh and 0 <= xx < gw and cell[yy, xx] and not seen[yy, xx]:
                                seen[yy, xx] = True
                                stack.append((yy, xx))
                best = max(best, size)
    return best / float(gh * gw)


def srgb_to_lab(rgb) -> np.ndarray:
    """sRGB (…,3) в 0..255 → CIE Lab (D65)."""
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def delta_e(lab1, lab2, rules: dict) -> float:
    """ΔE76 с ослабленным весом яркости: свет вида не равен цвету предмета."""
    w = float(rules['colour']['L_weight'])
    d = np.asarray(lab1, dtype=np.float64) - np.asarray(lab2, dtype=np.float64)
    return float(math.sqrt((w * d[0]) ** 2 + d[1] ** 2 + d[2] ** 2))


def view_stats(rgb: np.ndarray, rules: dict) -> dict:
    """Числа вида: доля предмета в кадре, доля малинового по предмету, наибольший малиновый кусок (доля кадра), медианный Lab предмета (None — предмет слишком мал)."""
    obj = object_mask(rgb, rules)
    mag = magenta_mask(rgb, rules)
    obj_frac = float(obj.mean())
    out = {'obj_frac': round(obj_frac, 4), 'mag_frac': 0.0, 'comp_frac': 0.0, 'lab': None}
    if obj.sum() > 0:
        out['mag_frac'] = round(float((mag & obj).sum() / obj.sum()), 4)
    out['comp_frac'] = round(largest_component_frac(mag, rules), 4) if mag.any() else 0.0
    if obj_frac >= rules['colour']['min_object_frac']:
        clean = obj & ~mag                                      # цвет предмета — без малинового, иначе сбой одного сторожа маскирует другой
        px = rgb[clean] if clean.sum() > 0 else rgb[obj]
        out['lab'] = [round(float(v), 2) for v in np.median(srgb_to_lab(px), axis=0)]
    return out


def judge_magenta(stats: dict, rules: dict, baseline: float = 0.0, exempt: bool = False) -> tuple[bool, str]:
    """(годен, причина). Порог по доле предмета ИЛИ по крупному куску; у товара, у которого розовый/фиолетовый — цвет каталога (exempt), допускается доля вида-зерна (baseline) + запас."""
    m = rules['magenta']
    limit = m['obj_frac_max'] + ((baseline + m['pink_exempt_extra_frac']) if exempt else 0.0)
    if stats['mag_frac'] > limit:
        return False, f"малиновое {stats['mag_frac'] * 100:.1f} % предмета (порог {limit * 100:.1f} %)"
    if stats['comp_frac'] > m['component_img_frac_max'] and not exempt:
        return False, f"крупный малиновый кусок {stats['comp_frac'] * 100:.2f} % кадра (порог {m['component_img_frac_max'] * 100:.2f} %)"
    return True, ''


def is_pink_colour(word: str | None, rules: dict) -> bool:
    return bool(word) and word.casefold() in {w.casefold() for w in rules['pink_words']}


def catalog_lab(word: str | None, rules: dict):
    rgb = (rules.get('catalog_rgb') or {}).get(word or '')
    return srgb_to_lab(rgb) if rgb else None


def judge_colour(stats: dict, rules: dict, neighbour_lab=None, catalog=None) -> tuple[bool, str, dict]:
    """Сверка цвета вида: с ближайшим принятым соседом (перекрытие) и с цветом каталога. Нет данных (предмет мал, нет соседа/слова цвета) — проверка пропущена, не провал."""
    info = {}
    if stats.get('lab') is None:
        return True, '', info
    if neighbour_lab is not None:
        info['dE_neighbour'] = round(delta_e(stats['lab'], neighbour_lab, rules), 1)
        if info['dE_neighbour'] > rules['colour']['overlap_max']:
            return False, f"цвет ушёл от соседнего вида: ΔE {info['dE_neighbour']} > {rules['colour']['overlap_max']}", info
    if catalog is not None:
        info['dE_catalog'] = round(delta_e(stats['lab'], catalog, rules), 1)
        if info['dE_catalog'] > rules['colour']['catalog_max']:
            return False, f"цвет далёк от каталога: ΔE {info['dE_catalog']} > {rules['colour']['catalog_max']}", info
    return True, '', info


def repair_magenta(rgb: np.ndarray, rules: dict, fill_lab) -> np.ndarray:
    """Крайний случай (вид отклонён после повторов): малиновые пиксели предмета → медианный цвет принятого соседа. Не «починка текстуры», а чтобы заливка не попала в проекцию."""
    from_lab = np.asarray(fill_lab, dtype=np.float64)
    # Lab → sRGB (обратное преобразование)
    fy = (from_lab[0] + 16) / 116
    fx, fz = fy + from_lab[1] / 500, fy - from_lab[2] / 200
    f = np.array([fx, fy, fz])
    xyz = np.where(f ** 3 > 216 / 24389, f ** 3, (116 * f - 16) / (24389 / 27)) * np.array([0.95047, 1.0, 1.08883])
    m_inv = np.linalg.inv(np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]))
    lin = np.clip(m_inv @ xyz, 0, 1)
    srgb = np.where(lin > 0.0031308, 1.055 * lin ** (1 / 2.4) - 0.055, 12.92 * lin)
    out = rgb.copy()
    out[magenta_mask(rgb, rules)] = (srgb * 255).round().astype(np.uint8)
    return out


def encode_png(rgb: np.ndarray) -> bytes:
    """uint8 RGB → PNG-байты (zlib, без фильтров) — без Pillow/OpenCV."""
    import struct
    import zlib
    h, w, _ = rgb.shape
    raw = b''.join(b'\x00' + rgb[y].tobytes() for y in range(h))

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 3)) + chunk(b'IEND', b'')

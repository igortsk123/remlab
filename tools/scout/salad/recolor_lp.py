#!/usr/bin/env python3
"""T-20261118-52/2/1: ПРОТОТИП «перекрасить ГОТОВЫЙ меш по цвету фото, сохранив текстуру» — на процессоре, 0 ₽, в конвейер НЕ встроен.

Схема (Codex 18.11, `_intake/codex/2026-11-18-mesh-recolor-answer.md`, «основной вариант»):
  1. Поза камеры фото — подбор по силуэту (`color_steps.best_pose`) + доводка фото к силуэту рендера (масштаб/сдвиг по IoU).
     IoU силуэта < IOU_MIN — модель НЕ трогаем (камера ненадёжна).
  2. Соответствие «пиксель кадра → тексель» (`color_o2.texel_map`, тот же растеризатор, что `mesh_render.render`); участки цвета
     рендера без света (кластеры Lab, `color_o2.zones`) → цель участка = обрезанная медиана Lab ФОТО на тех же пикселях.
     Не трогаем: мелкие участки, «нет пары на фото», металл, «не тот материал» (|нужно| > 3 ступеней — сеть покрасила не тем).
     Сдвиг участка (ΔL, Δa, Δb) ограничен (MAX_DL, MAX_DAB).
  3. Текстура T0 (линейный свет) делится на НИЗКИЕ частоты B0 (двусторонний фильтр на уменьшенной копии — с сохранением границ) и
     ДЕТАЛЬ D = T0 / B0 (мультипликативный остаток). Правится только B0: B1 = B0 + мягкий сдвиг Lab (вес — близость ЦВЕТА B0 к
     участку, σ = разброс участка; далёкие цвета не двигаются — швов нет). T1 = T0 · (B1 / B0): деталь переносится как есть.
  4. Запись — хирургическая: заменяется только картинка baseColor внутри GLB (`pygltflib`, как `texture_fix.match_photo_color`),
     геометрия, UV, MR, нормали, коэффициенты материала не трогаются. НЕ `color_o2.write_glb` (он переэкспортирует сцену trimesh).
  5. Мерка: ΔE00 «было/стало» в том же кадре (по пикселям: медиана, p90; по областям фото — медиана областей), ΔL, хрома;
     сохранность детали: корреляция и SSIM высокочастотного остатка логарифма яркости, отношение энергий, доля «обрезанных»
     текселей; на рендере — корреляция остатка. В листе — «фото | было | стало» без света, полного размера, по кадру на модель.

  ~/venvs/scout/bin/python recolor_lp.py run <jobs52.json> <папка> [--only ПОДСТРОКА] [--shift-scale K]
  ~/venvs/scout/bin/python recolor_lp.py --selftest

Живые меши не трогает: берёт копию-чтение `v2/<gen>/model.glb`, пишет только в <папка>/glb/.
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]
import color_o2 as CO  # noqa: E402
import color_steps as CS  # noqa: E402

ROOT = os.path.expanduser('~/scout-scenes/meshes-hunyuan/meshes/hunyuan21')
IOU_MIN = 0.60          # ниже — камере фото не верим, меш не трогаем (Codex: 0,6–0,65)
MAX_DL = 45.0           # предел сдвига светлоты Lab участка
MAX_DAB = 35.0          # предел сдвига цветности (длина вектора a, b)
WORK = 512              # сторона рабочей копии текстуры для низких частот
BIL_ITERS = 3           # проходов двустороннего фильтра
BIL_COLOR = 10.0        # σ по цвету (единицы Lab)
BIL_SPACE = 5.0         # σ по пространству (пиксели рабочей копии)
RATIO_MIN, RATIO_MAX = 0.2, 5.0
HP_SIGMA = 3.0          # σ размытия при выделении высокочастотного остатка (пиксели полной текстуры)
DARK_L = 12.0           # участок темнее (Lab L меша) — отказ: в текстуре нет сигнала, множитель усиливает шум (проба 1: тумба 17 → пятна)
MATE_AREA_MIN = 0.5     # пара кластеров фото должна накрывать ≥ 50 % пикселей участка меша (белое снаружи ≠ серое нутро, тумба 11)
MATE_L_TOL = 15.0       # пиксели фото под участком: светлота в пределах ±15 от медианы…
MATE_HOMOG = 0.65       # …у ≥ 65 % пикселей, иначе под участком на фото два разных места — цель неоднозначна
COVER_OK, COVER_MIN = 0.80, 0.30   # покрыто участками: ≥0,8 — «ok», 0,3–0,8 — «частично», <0,3 — «отказ»
ELIGIBLE = ('правим', 'рисунок')   # статусы `color_o2.zones`, которые правим (рисунок — тоже: деталь сохраняется)
FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
FONT_S = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)


# ── цвет ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def lab_f(rgb: np.ndarray) -> np.ndarray:
    """sRGB 0–255 (uint8 или float) → Lab D65, float32 (та же формула, что `color_o2.lab`)."""
    return CO.lab(np.asarray(rgb, np.float32))


def lab_to_lin(Lab: np.ndarray) -> np.ndarray:
    """Lab → линейный RGB 0–1 (без округления и без обрезки до 8 бит; обрезка — только в [0, 1])."""
    fy = (Lab[..., 0] + 16) / 116
    xyz = np.stack([CO._finv(fy + Lab[..., 1] / 500), CO._finv(fy), CO._finv(fy - Lab[..., 2] / 200)], -1) * CO._WHITE
    lin = xyz @ np.linalg.inv(CO._M).T.astype(np.float32)
    return np.clip(lin, 0.0, 1.0).astype(np.float32)


def s2l(rgb8: np.ndarray) -> np.ndarray:
    return CO.s2l(np.asarray(rgb8, np.float32) / 255.0)


def l2s8(lin: np.ndarray) -> np.ndarray:
    return np.clip(np.round(CO.l2s(lin) * 255.0), 0, 255).astype(np.uint8)


def de2000(l1: np.ndarray, l2: np.ndarray) -> np.ndarray:
    """CIEDE2000 (Sharma 2005), векторно; Lab → разница по последней оси."""
    L1, a1, b1 = (l1[..., i].astype(np.float64) for i in range(3))
    L2, a2, b2 = (l2[..., i].astype(np.float64) for i in range(3))
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hbp = np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2))
    hbp = np.where(C1p * C2p == 0, hs, hbp)
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dth = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh)).astype(np.float32)


def tmed(lab: np.ndarray, lo: float = 10, hi: float = 90) -> np.ndarray:
    """Обрезанная медиана Lab по набору пикселей: берём пиксели, чья L между перцентилями lo..hi (убирает блики и глубокие тени)."""
    if len(lab) < 20:
        return np.median(lab, 0)
    a, b = np.percentile(lab[:, 0], [lo, hi])
    k = (lab[:, 0] >= a) & (lab[:, 0] <= b)
    return np.median(lab[k], 0) if k.sum() >= 10 else np.median(lab, 0)


# ── камера и фото ──────────────────────────────────────────────────────────────────────────────────────────────────

def _iou(a: np.ndarray, b: np.ndarray) -> float:
    return float((a & b).sum() / max((a | b).sum(), 1))


def refine_align(prgb: np.ndarray, pmask: np.ndarray, ralpha: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict]:
    """Фото, уже вписанное рамкой в силуэт рендера (`color_o2.align_photo`), доводится небольшим масштабом и сдвигом по IoU силуэтов
    (перспектива фото против ортографического рендера: рамка не равна силуэту). Возвращает (rgb, mask, {iou0, iou, s, dx, dy})."""
    import cv2
    h, w = ralpha.shape
    cy, cx = np.array(np.where(ralpha)).mean(1)
    best = (_iou(pmask, ralpha), 1.0, 0.0, 0.0)
    iou0 = best[0]
    pm8 = pmask.astype(np.uint8) * 255
    for s in (0.94, 0.97, 1.0, 1.03, 1.06):
        for dy in (-0.04, -0.02, 0, 0.02, 0.04):
            for dx in (-0.04, -0.02, 0, 0.02, 0.04):
                M = np.array([[s, 0, cx - s * cx + dx * w], [0, s, cy - s * cy + dy * h]], np.float32)
                m = cv2.warpAffine(pm8, M, (w, h), flags=cv2.INTER_NEAREST) > 127
                v = _iou(m, ralpha)
                if v > best[0] + 1e-6:
                    best = (v, s, dx, dy)
    v, s, dx, dy = best
    M = np.array([[s, 0, cx - s * cx + dx * w], [0, s, cy - s * cy + dy * h]], np.float32)
    rgb = cv2.warpAffine(prgb, M, (w, h), flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(pm8, M, (w, h), flags=cv2.INTER_NEAREST) > 127
    return rgb, mask, {'iou0': round(iou0, 3), 'iou': round(v, 3), 's': s, 'dx': dx, 'dy': dy}


# ── низкие частоты, поле поправки, применение к текстуре ───────────────────────────────────────────────────────────

def lowpass(tex8: np.ndarray) -> tuple[np.ndarray, tuple[int, int]]:
    """Низкие частоты текстуры: уменьшенная рабочая копия (площадь), двусторонний фильтр по Lab (с сохранением границ).
    Возвращает (B0 Lab float32 рабочего размера, (h, w) рабочего размера)."""
    import cv2
    h, w = tex8.shape[:2]
    k = min(1.0, WORK / max(h, w))
    sw, sh = max(8, int(round(w * k))), max(8, int(round(h * k)))
    small = cv2.resize(tex8, (sw, sh), interpolation=cv2.INTER_AREA) if k < 1 else tex8.copy()
    Lab = lab_f(small)
    for _ in range(BIL_ITERS):
        Lab = cv2.bilateralFilter(Lab.astype(np.float32), 0, BIL_COLOR, BIL_SPACE)
    return Lab.astype(np.float32), (sh, sw)


class Field:
    """Поправка цвета: участки (центр Lab, σ, сдвиг Lab). Вес текселя — близость цвета НИЗКИХ частот к центру участка;
    как в `color_o2.soft_lg`: знаменатель не меньше веса на 2,5σ — далёкие цвета плавно уходят к нулю."""

    def __init__(self, C: np.ndarray, sig: np.ndarray, shifts: np.ndarray):
        self.C, self.sig, self.sh = C.astype(np.float32), np.maximum(sig, CO.SIGMA_DE).astype(np.float32), shifts.astype(np.float32)

    def shift_at(self, Lab: np.ndarray) -> np.ndarray:
        if not len(self.C):
            return np.zeros(Lab.shape, np.float32)
        x = Lab.reshape(-1, 3)
        d2 = ((x[:, None, :] - self.C[None]) ** 2).sum(-1)
        wk = np.exp(-d2 / (2 * self.sig[None] ** 2))
        w0 = math.exp(-2.5 ** 2 / 2)
        out = (wk[:, :, None] * self.sh[None]).sum(1) / np.maximum(wk.sum(1), w0)[:, None]
        return out.reshape(Lab.shape).astype(np.float32)


def recolor_texture(tex8: np.ndarray, fld: Field) -> tuple[np.ndarray, dict]:
    """T1 = T0 · (B1 / B0), B1 = B0 + сдвиг Lab (линейный свет, мультипликативная деталь). → (новая текстура uint8, служебное)."""
    import cv2
    alpha = None
    if tex8.ndim == 3 and tex8.shape[2] == 4:
        alpha = tex8[..., 3]
        tex8 = tex8[..., :3]
    B0, _ = lowpass(tex8)
    S = fld.shift_at(B0)
    B1 = B0 + S
    eps = 0.003
    r = (lab_to_lin(B1) + eps) / (lab_to_lin(B0) + eps)
    r = np.clip(r, RATIO_MIN, RATIO_MAX)
    dark = B0[..., 0] < 3.0                                  # пустота развёртки и глухая тень — без поправки
    r[dark] = 1.0
    h, w = tex8.shape[:2]
    rf = cv2.resize(r.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR) if r.shape[:2] != (h, w) else r
    T0 = s2l(tex8)
    T1 = np.clip(T0 * rf, 0.0, 1.0)
    out = l2s8(T1)
    clipped = float(np.mean(((T0 * rf) > 1.0).any(-1) & ~(T0 >= 0.999).any(-1)))
    changed = (np.abs(rf - 1.0) > 0.02).any(-1)
    if alpha is not None:
        out = np.dstack([out, alpha])
    return out, {'changed_share': round(float(changed.mean()), 4), 'clipped_share': round(clipped, 5), 'ratio': rf, 'T0': T0}


# ── сохранность детали ─────────────────────────────────────────────────────────────────────────────────────────────

def _hp(Y: np.ndarray) -> np.ndarray:
    import cv2
    ly = np.log(Y + 0.01).astype(np.float32)
    return ly - cv2.GaussianBlur(ly, (0, 0), HP_SIGMA)


def _ssim(a: np.ndarray, b: np.ndarray, m: np.ndarray) -> float:
    import cv2
    rng = float(max(a[m].max() - a[m].min(), 1e-3)) if m.any() else 1.0
    c1, c2 = (0.01 * rng) ** 2, (0.03 * rng) ** 2
    g = lambda x: cv2.GaussianBlur(x, (0, 0), 1.5)               # noqa: E731
    ma, mb = g(a), g(b)
    va, vb, cab = g(a * a) - ma * ma, g(b * b) - mb * mb, g(a * b) - ma * mb
    s = ((2 * ma * mb + c1) * (2 * cab + c2)) / ((ma * ma + mb * mb + c1) * (va + vb + c2))
    return float(s[m].mean())


def detail_metrics(tex0: np.ndarray, tex1: np.ndarray, extra: dict) -> dict:
    """Остаток высоких частот логарифма яркости: корреляция, SSIM, отношение энергий; на «изменённых» текселях (где поправка > 2 %)."""
    import cv2
    t0, t1 = tex0[..., :3], tex1[..., :3]
    Y = np.array([0.2126, 0.7152, 0.0722], np.float32)
    h0, h1 = _hp(s2l(t0) @ Y), _hp(s2l(t1) @ Y)
    cover = t0.max(-1) > 15
    cover = cv2.erode(cover.astype(np.uint8), np.ones((9, 9), np.uint8)).astype(bool)         # край развёртки не считаем
    chg = (np.abs(extra['ratio'] - 1.0) > 0.02).any(-1) & cover
    m = chg if chg.sum() > 500 else cover
    a, b = h0[m], h1[m]
    corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 1e-6 and b.std() > 1e-6 else 1.0
    return {'hp_corr': round(corr, 4), 'hp_ssim': round(_ssim(h0, h1, m), 4), 'hp_std0': round(float(a.std()), 4),
            'hp_energy': round(float(b.std() / max(a.std(), 1e-9)), 3), 'px_measured': int(m.sum()),
            'clipped': extra['clipped_share'], 'changed': extra['changed_share']}


# ── GLB: хирургическая замена baseColor ────────────────────────────────────────────────────────────────────────────

def _png(arr: np.ndarray) -> bytes:
    b = io.BytesIO()
    Image.fromarray(arr).save(b, format='PNG')
    return b.getvalue()


def rewrite_glb(src: str, dst: str, fn) -> list[dict]:
    """Каждая картина baseColor GLB → `fn(массив RGB(A) uint8)` → (новый массив | None, служебное). Только эти байты; всё прочее —
    как было (геометрия, UV, MR, нормали, множители материала). Картины внутри буфера или как data:URI — оба пути."""
    from pygltflib import GLTF2
    g = GLTF2().load(src)
    base_idx = set()
    for mat in g.materials or []:
        pmr = getattr(mat, 'pbrMetallicRoughness', None)
        bct = getattr(pmr, 'baseColorTexture', None) if pmr else None
        if bct is not None and bct.index is not None and g.textures[bct.index].source is not None:
            base_idx.add(g.textures[bct.index].source)
    blob = g.binary_blob()
    new_chunks, data_uris, infos = {}, {}, []
    for idx, img in enumerate(g.images):
        if idx not in base_idx:
            continue
        raw = None
        if img.bufferView is not None:
            bv = g.bufferViews[img.bufferView]
            raw = blob[bv.byteOffset:bv.byteOffset + bv.byteLength]
        elif (img.uri or '').startswith('data:image'):
            raw = base64.b64decode(img.uri.split(',', 1)[1])
        if raw is None:
            continue
        pil = Image.open(io.BytesIO(raw))
        arr = np.asarray(pil.convert('RGBA') if 'A' in pil.mode else pil.convert('RGB'))
        new, info = fn(arr)
        info = dict(info or {}, image=idx, size=list(arr.shape[:2]))
        infos.append(info)
        if new is None:
            continue
        data = _png(new)
        if img.bufferView is not None:
            new_chunks[idx] = data
        else:
            data_uris[idx] = data
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
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    g.save(dst)
    return infos


# ── один меш ───────────────────────────────────────────────────────────────────────────────────────────────────────

def build_field(base, ralpha, prgb, pmask, tm, metals, shift_scale: float = 1.0):
    """Участки по рендеру без света → поле поправки. → (Field | None, список участков для отчёта, причина отказа | None)."""
    P_lab = lab_f(prgb)
    pvis = CO.erode(pmask, 2)
    PC = CO.kmeans(P_lab[pvis], CO.K_PHOTO, seed=2)
    pcl = np.full(pmask.shape, -1, np.int32)
    pcl[pmask] = CO.assign(P_lab[pmask], PC)
    C, info, cl = CO.zones(base, ralpha, prgb, pmask, pcl, tm, metals)
    both = CO.erode(ralpha) & CO.erode(pmask)
    R_lab = lab_f(base)
    cs, sg, sh, rep = [], [], [], []
    cover = 0.0
    for z in info:
        i = z['i']
        row = {'i': i, 'area': z['area'], 'st': z['st'], 'lab': z['lab'], 'need_stops': z.get('need')}
        why = None
        if z['st'] not in ELIGIBLE:
            why = None if z['st'] == 'мелкий' else z['st']                    # «не тот материал», «нет пары на фото», металл… — не правим
        elif z['lab'][0] < DARK_L:
            why = 'тёмная текстура (L меша %.0f < %.0f): сигнала нет, усилится шум' % (z['lab'][0], DARK_L)
        if z['st'] in ELIGIBLE and why is None:
            reg = both & (cl == i) & np.isin(pcl, z.get('mates') or [])
            zpx = int((both & (cl == i)).sum())
            if reg.sum() < 50:
                why = 'нет пары на фото'
            elif reg.sum() < MATE_AREA_MIN * zpx:
                why = 'пара покрывает %.0f %% участка (< %.0f %%)' % (100 * reg.sum() / max(zpx, 1), 100 * MATE_AREA_MIN)
            else:
                Lp = P_lab[reg][:, 0]
                homog = float(np.mean(np.abs(Lp - np.median(Lp)) <= MATE_L_TOL))
                if homog < MATE_HOMOG:
                    why = 'на фото под участком разные светлоты (согласие %.0f %% < %.0f %%) — пара неоднозначна' % (100 * homog, 100 * MATE_HOMOG)
        if why:
            row['why'] = why
        if z['st'] in ELIGIBLE and why is None:
            if True:
                tp, tm_ = tmed(P_lab[reg]), tmed(R_lab[reg])
                d = tp - tm_
                dl = float(np.clip(d[0], -MAX_DL, MAX_DL))
                dab = d[1:]
                n = float(np.hypot(*dab))
                if n > MAX_DAB:
                    dab = dab * (MAX_DAB / n)
                # цветность целится осторожнее: у тёмной цели (L* < 40) оттенок на фото ненадёжен (шум, потеря сигнала в тенях), у малых участков
                # (ручки, ножки < 12 % видимого) один сдвиг не должен менять оттенок — иначе чёрная ручка становится оливковой (проба 1, комод)
                fade = float(np.clip((tp[0] - 15.0) / 25.0, 0.0, 1.0)) * (1.0 if z['area'] >= 0.12 else 0.4)
                s = np.array([dl, dab[0] * fade, dab[1] * fade], np.float32) * shift_scale
                cs.append(np.asarray(C[i], np.float32)); sg.append(z.get('spread') or CO.SIGMA_DE); sh.append(s)
                cover += float(z['area'])
                row.update(target=[round(float(v), 1) for v in tp], mesh=[round(float(v), 1) for v in tm_],
                           shift=[round(float(v), 1) for v in s], capped=bool(abs(d[0]) > MAX_DL or n > MAX_DAB))
        rep.append(row)
    if not cs:
        return None, rep, 'нет участков для поправки', 0.0
    return Field(np.array(cs), np.array(sg), np.array(sh)), rep, None, cover


def region_metrics(rgb: np.ndarray, ralpha: np.ndarray, prgb: np.ndarray, pmask: np.ndarray) -> dict:
    """Мерка в кадре: пиксельная ΔE00 (медиана, p90), по областям фото (кластеры Lab ≥ 3 %): медиана ΔE00 областей, ΔL, ΔC*."""
    both = CO.erode(ralpha) & CO.erode(pmask)
    R, P = lab_f(rgb), lab_f(prgb)
    de = de2000(R[both], P[both])
    pc = CO.kmeans(P[both], CO.K_PHOTO, seed=2)
    cl = CO.assign(P[both], pc)
    regs = []
    for j in range(len(pc)):
        k = cl == j
        if k.sum() < 0.03 * both.sum():
            continue
        mr, mp = np.median(R[both][k], 0), np.median(P[both][k], 0)
        regs.append({'share': float(k.sum() / both.sum()), 'de': float(de2000(mr[None], mp[None])[0]),
                     'dL': float(mr[0] - mp[0]), 'dC': float(np.hypot(mr[1], mr[2]) - np.hypot(mp[1], mp[2]))})
    ws = np.array([r['share'] for r in regs]) if regs else np.array([1.0])

    def wmed(key):
        v = np.array([abs(r[key]) for r in regs]) if regs else np.array([0.0])
        o = np.argsort(v)
        c = np.cumsum(ws[o])
        return float(v[o][np.searchsorted(c, c[-1] / 2)])
    return {'de_med': round(float(np.median(de)), 2), 'de_p90': round(float(np.percentile(de, 90)), 2),
            'reg_de_med': round(wmed('de'), 2), 'reg_dL_med': round(wmed('dL'), 1), 'reg_dC_med': round(wmed('dC'), 1),
            'reg_de_max8': round(max([r['de'] for r in regs if r['share'] >= 0.08] or [0.0]), 2), 'n_regions': len(regs)}


def render_unlit(glb: str, yaw: float, pitch: float, size: int) -> Image.Image:
    import mesh_render as MR
    prev = os.environ.get('UNLIT')
    os.environ['UNLIT'] = '1'
    try:
        return MR.render(MR.load_parts(glb), yaw_deg=yaw, pitch_deg=pitch, size=(size, size))
    finally:
        if prev is None:
            os.environ.pop('UNLIT', None)
        else:
            os.environ['UNLIT'] = prev


def process(sku: str, gen: str, role: str, out: str, k: int, shift_scale: float = 1.0) -> dict:
    import mesh_render as MR
    sid = sku.replace(':', '_')
    d = f'{ROOT}/v2/{sid}/{gen}'
    glb, cut = f'{d}/model.glb', f'{d}/cutout.png'
    r: dict = {'sku': sku, 'role': role, 'gen': gen}
    t0 = time.time()
    P = CS.rgba(cut)
    pose = CS.best_pose(glb, P[..., 3] > 128)
    yaw, pitch = pose['yaw'], pose['pitch']
    r.update(yaw=yaw, pitch=pitch, pose_iou=pose['iou'])
    parts = MR.load_parts(glb)
    tm = CO.texel_map(parts, yaw, pitch, CS.FINAL_PX)
    texs = [MR.texture_of(p)[0] for p in parts]
    metals = [CO.metallic_of(p) for p in parts]
    ralpha = tm[0] >= 0
    base = CO.from_map(tm, texs)
    prgb0, pmask0 = CO.align_photo(P, ralpha)
    prgb, pmask, al = refine_align(prgb0, pmask0, ralpha)
    r['align'] = al
    if al['iou'] < IOU_MIN:
        r.update(status='отказ: силуэт фото не совпал с рендером (IoU %.2f < %.2f) — камере не верим' % (al['iou'], IOU_MIN))
        return r
    fld, zrep, why, cover = build_field(base, ralpha, prgb, pmask, tm, metals, shift_scale)
    r['zones'] = zrep
    r['cover'] = round(cover, 3)
    r['was'] = region_metrics(base, ralpha, prgb, pmask)
    if fld is None or cover < COVER_MIN:
        whys = '; '.join(sorted({z['why'].split(' (')[0].split(':')[0] for z in zrep if z.get('why') and z['area'] >= 0.1}))
        r.update(status='отказ: правимых участков %.0f %% < %.0f %% (%s)' % (100 * cover, 100 * COVER_MIN, whys or 'нет'))
        frame(out, k, sku, role, glb, None, yaw, pitch, P, r)
        return r
    dst = f'{out}/glb/{k:02d}_{sid}.glb'
    details = []

    def fn(arr):
        new, ex = recolor_texture(arr, fld)
        dm = detail_metrics(arr, new, ex)
        details.append(dm)
        return new, dm
    infos = rewrite_glb(glb, dst, fn)
    r['detail'] = details
    r['glb'] = dst
    # то же — в кадре: рендер без света «стало» против фото
    parts1 = MR.load_parts(dst)
    tm1 = CO.texel_map(parts1, yaw, pitch, CS.FINAL_PX)
    base1 = CO.from_map(tm1, [MR.texture_of(p)[0] for p in parts1])
    r['now'] = region_metrics(base1, tm1[0] >= 0, prgb, pmask)
    both = CO.erode(ralpha) & CO.erode(pmask)
    Y = np.array([0.2126, 0.7152, 0.0722], np.float32)
    h0, h1 = _hp(s2l(base) @ Y), _hp(s2l(base1) @ Y)
    r['render_hp_corr'] = round(float(np.corrcoef(h0[both], h1[both])[0, 1]), 4)
    if r['now']['de_med'] > r['was']['de_med'] + 0.5:
        r['status'] = 'отказ: самопроверка — ΔE00 стало хуже (%s → %s), результат не принимать' % (r['was']['de_med'], r['now']['de_med'])
    elif cover >= COVER_OK:
        r['status'] = 'ok'
    else:
        r['status'] = 'частично (правим %.0f %% видимого)' % (100 * cover)
    r['secs'] = round(time.time() - t0, 1)
    # кадр «фото | было | стало»
    frame(out, k, sku, role, glb, dst, yaw, pitch, P, r)
    if k in LIT_ROWS:
        lit_frame(out, k, sku, role, glb, dst, yaw, pitch)
    return r


# ── лист: один кадр на модель, полный размер ──────────────────────────────────────────────────────────────────────

def frame(out: str, k: int, sku: str, role: str, was: str, now: str, yaw: float, pitch: float, P: np.ndarray, r: dict) -> None:
    S = 720
    imw = render_unlit(was, yaw, pitch, S)
    imn = render_unlit(now, yaw, pitch, S) if now else None
    ralpha = np.asarray(imw)[..., 3] > 128
    prgb, pmask = CO.align_photo(P, ralpha)
    al = r['align']
    import cv2
    h, w = ralpha.shape
    cy, cx = np.array(np.where(ralpha)).mean(1)
    s, dx, dy = al['s'], al['dx'], al['dy']
    M = np.array([[s, 0, cx - s * cx + dx * w], [0, s, cy - s * cy + dy * h]], np.float32)
    prgb = cv2.warpAffine(prgb, M, (w, h), flags=cv2.INTER_LINEAR)
    pmask = cv2.warpAffine(pmask.astype(np.uint8) * 255, M, (w, h), flags=cv2.INTER_NEAREST) > 127

    def onbg(a_rgb, a_mask):
        bg = np.full((S, S, 3), 236, np.uint8)
        bg[a_mask] = a_rgb[a_mask]
        return Image.fromarray(bg)

    def rn(im):
        a = np.asarray(im)
        return onbg(a[..., :3], a[..., 3] > 128)
    pn = rn(imn) if imn is not None else Image.new('RGB', (S, S), (236, 236, 236))
    ph, pw_ = onbg(prgb, pmask), rn(imw)
    W, H = 3 * S + 4 * 16, S + 176
    sh = Image.new('RGB', (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(sh)
    dr.text((16, 8), f'{sku} · {role} · поза yaw {yaw}° pitch {pitch}° · IoU силуэта {al["iou"]} · {r["status"]}', font=FONT, fill=(0, 0, 0))
    third = 'стало (перекраска низких частот)' if imn is not None else 'стало — НЕ ВЫПОЛНЕНО (отказ)'
    for i, (im, name) in enumerate(((ph, 'фото (вырезка)'), (pw_, 'было (живой меш, без света)'), (pn, third))):
        sh.paste(im, (16 + i * (S + 16), 40)); dr.text((16 + i * (S + 16), 40 + S + 4), name, font=FONT, fill=(0, 0, 0))
    wsm, nsm = r['was'], r.get('now')
    dt = r['detail'][0] if r.get('detail') else {}
    if nsm:
        t1 = (f'ΔE00 по пикселям: медиана {wsm["de_med"]}→{nsm["de_med"]}, p90 {wsm["de_p90"]}→{nsm["de_p90"]} · по областям: {wsm["reg_de_med"]}→{nsm["reg_de_med"]}, '
              f'|ΔL| {wsm["reg_dL_med"]}→{nsm["reg_dL_med"]}, |ΔC*| {wsm["reg_dC_med"]}→{nsm["reg_dC_med"]}')
        t2 = (f'деталь (остаток высоких частот): корреляция {dt.get("hp_corr")}, SSIM {dt.get("hp_ssim")}, энергия ×{dt.get("hp_energy")}, обрезано {dt.get("clipped")}, '
              f'изменено текселей {dt.get("changed")}; на рендере корреляция {r.get("render_hp_corr")}')
    else:
        t1 = f'ΔE00 «было»: по пикселям медиана {wsm["de_med"]}, p90 {wsm["de_p90"]}; по областям {wsm["reg_de_med"]}, |ΔL| {wsm["reg_dL_med"]}, |ΔC*| {wsm["reg_dC_med"]}'
        t2 = 'причины отказа по участкам: ' + ('; '.join(f'{z["lab"]} ({z["area"]:.0%}): {z["why"]}' for z in r['zones'] if z.get('why') and z['area'] >= 0.1) or '—')
    dr.text((16, 40 + S + 34), t1, font=FONT_S, fill=(0, 0, 0))
    dr.text((16, 40 + S + 60), t2[:260], font=FONT_S, fill=(0, 0, 0))
    zs = '; '.join(f'{z["lab"]}→сдвиг {z["shift"]}' for z in r['zones'] if z.get('shift'))
    dr.text((16, 40 + S + 86), 'сдвиги участков (L,a,b): ' + (zs or '—'), font=FONT_S, fill=(60, 60, 60))
    ref = '; '.join(f'{z["lab"][0]:.0f}/{z["area"]:.0%}: {z["why"][:70]}' for z in r['zones'] if z.get('why') and nsm and z['area'] >= 0.1)
    if ref:
        dr.text((16, 40 + S + 112), 'не правили: ' + ref[:240], font=FONT_S, fill=(120, 0, 0))
    os.makedirs(f'{out}/frames', exist_ok=True)
    sh.save(f'{out}/frames/{k:02d}_{sku.replace(":", "_")}.png')


LIT_ROWS: set = set()    # номера моделей (по порядку таблицы), для которых делается кадр в свету с других ракурсов (--lit 1,6,13)


def lit_frame(out: str, k: int, sku: str, role: str, was: str, now: str, yaw: float, pitch: float) -> None:
    """Рендер С освещением (обычный `mesh_render.render`, без UNLIT), три ракурса: поза фото, +45°, −45°; верх — «было», низ — «стало»."""
    import mesh_render as MR
    S = 600
    pt = max(float(pitch), 10.0)
    prev = os.environ.pop('UNLIT', None)
    try:
        angs = [(yaw, pitch, 'поза фото'), (yaw + 45, pt, '+45°'), (yaw - 45, pt, '−45°')]
        rows_im = []
        for glb in (was, now):
            parts = MR.load_parts(glb)
            rows_im.append([MR.render(parts, yaw_deg=a, pitch_deg=p, size=(S, S)) for a, p, _ in angs])
    finally:
        if prev is not None:
            os.environ['UNLIT'] = prev
    W, H = 3 * S + 4 * 16, 2 * S + 40 + 2 * 36
    sh = Image.new('RGB', (W, H), (255, 255, 255))
    dr = ImageDraw.Draw(sh)
    dr.text((16, 8), f'{sku} · {role} · В СВЕТУ (обычный рендер), ракурсы: поза фото, +45°, −45° · верх — было, низ — стало', font=FONT, fill=(0, 0, 0))
    for ri, (name, ims) in enumerate((('было', rows_im[0]), ('стало', rows_im[1]))):
        y0 = 40 + ri * (S + 36)
        for ci, im in enumerate(ims):
            bg = Image.new('RGB', (S, S), (236, 236, 236))
            a = im if im.mode == 'RGBA' else im.convert('RGBA')
            bg.paste(a, (0, 0), a)
            sh.paste(bg, (16 + ci * (S + 16), y0))
            dr.text((16 + ci * (S + 16), y0 + S + 4), f'{name} · {angs[ci][2]}', font=FONT, fill=(0, 0, 0))
    os.makedirs(f'{out}/lit', exist_ok=True)
    sh.save(f'{out}/lit/{k:02d}_{sku.replace(":", "_")}_lit.png')


# ── запуск ────────────────────────────────────────────────────────────────────────────────────────────────────────

def table(rows: list[dict]) -> str:
    L = ['| № | sku | роль | IoU | покрыто | ΔE00 мед. пикс. было→стало | p90 | по областям | \\|ΔL\\| обл. | \\|ΔC*\\| обл. | деталь corr / SSIM / энергия | обрезано | статус |',
         '|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for i, r in enumerate(rows, 1):
        w, n = r.get('was'), r.get('now')
        if not n:
            wtxt = f'{w["de_med"]} → —' if w else '—'
            L.append(f'| {i} | {r["sku"]} | {r["role"]} | {r.get("align", {}).get("iou", "—")} | {r.get("cover", "—")} | {wtxt} | — | — | — | — | — | — | {r.get("status")} |')
            continue
        d = (r['detail'] or [{}])[0]
        L.append(f'| {i} | {r["sku"]} | {r["role"]} | {r["align"]["iou"]} | {r.get("cover")} | {w["de_med"]} → {n["de_med"]} | {w["de_p90"]} → {n["de_p90"]} | {w["reg_de_med"]} → {n["reg_de_med"]} '
                 f'| {w["reg_dL_med"]} → {n["reg_dL_med"]} | {w["reg_dC_med"]} → {n["reg_dC_med"]} | {d.get("hp_corr")} / {d.get("hp_ssim")} / ×{d.get("hp_energy")} | {d.get("clipped")} | {r.get("status")} |')
    return '\n'.join(L)


def selftest() -> int:
    ok = True
    # ΔE00: контрольные пары Sharma 2005 (таблица данных)
    pairs = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425), ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
             ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492), ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644)]
    for a, b, want in pairs:
        got = float(de2000(np.array([a], np.float32), np.array([b], np.float32))[0])
        print('ΔE00', a, b, got, want, 'OK' if abs(got - want) < 0.01 else 'НЕТ')
        ok &= abs(got - want) < 0.01
    # тождество: нулевой сдвиг не меняет текстуру (деталь = 1.0)
    rng = np.random.default_rng(1)
    tex = (rng.integers(60, 200, (300, 300, 3))).astype(np.uint8)
    tex[:150] = (tex[:150] * 0.5 + 100).astype(np.uint8)
    f0 = Field(np.array([[50.0, 5.0, 5.0]]), np.array([20.0]), np.array([[0.0, 0.0, 0.0]]))
    new, ex = recolor_texture(tex, f0)
    dm = float(np.abs(new.astype(int) - tex.astype(int)).max())
    print('тождество: макс. отличие', dm, 'OK' if dm <= 1 else 'НЕТ'); ok &= dm <= 1
    # сдвиг L +10: деталь сохраняется
    f1 = Field(np.array([np.median(lab_f(tex).reshape(-1, 3), 0)]), np.array([40.0]), np.array([[10.0, 0.0, 0.0]]))
    new, ex = recolor_texture(tex, f1)
    dm = detail_metrics(tex, new, ex)
    dL = float(np.median(lab_f(new)[..., 0] - lab_f(tex)[..., 0]))
    print('сдвиг +10 L: фактически', round(dL, 2), dm, 'OK' if dm['hp_corr'] > 0.97 and 5 < dL < 15 else 'НЕТ'); ok &= dm['hp_corr'] > 0.97 and 5 < dL < 15
    print('selftest', 'OK' if ok else 'FAIL')
    return 0 if ok else 1


def main() -> int:
    if '--selftest' in sys.argv:
        return selftest()
    if len(sys.argv) < 4 or sys.argv[1] != 'run':
        print(__doc__); return 2
    jobs = json.load(open(sys.argv[2], encoding='utf-8'))
    out = sys.argv[3]
    only = sys.argv[sys.argv.index('--only') + 1] if '--only' in sys.argv else None
    ss = float(sys.argv[sys.argv.index('--shift-scale') + 1]) if '--shift-scale' in sys.argv else 1.0
    if '--lit' in sys.argv:
        LIT_ROWS.update(int(x) for x in sys.argv[sys.argv.index('--lit') + 1].split(','))
    seen, rows = set(), []
    os.makedirs(out, exist_ok=True)
    for j in jobs:
        if j['sku'] in seen or (only and only not in j['sku']):
            continue
        seen.add(j['sku'])
        k = len(rows) + 1
        try:
            r = process(j['sku'], j['_t85']['v2_gen'], j.get('role', ''), out, k, ss)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            r = {'sku': j['sku'], 'role': j.get('role', ''), 'status': 'ошибка: ' + repr(e)[:200]}
        r['control_in_t52'] = j['sku'] in [x['sku'] for x in jobs if x.get('_t52') == 'base']
        rows.append(r)
        print(k, j['sku'], r.get('status'), flush=True)
        json.dump(rows, open(f'{out}/results.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    open(f'{out}/table.md', 'w', encoding='utf-8').write(table(rows) + '\n')
    print(table(rows))
    return 0


if __name__ == '__main__':
    sys.exit(main())

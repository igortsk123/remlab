#!/usr/bin/env python3
"""T-20261119-47/1, п.2 (шаг А0 плана `mesh-photo-projection-01`): ГДЕ краска MV-Adapter теряет резкость и контраст против каталожного фото. CPU, бесплатно.

Вход — папка `stages/` товара (её кладёт драйвер из `stages.zip`, см. `worker_trellis.py: MVRunner.keep_stages`, опция `mv_keep_stages=1`) и фото товара (`<магазин_товар>.rgba.png`, настоящая альфа).
Стадии, все в камере вида 0 (одна и та же ортокамера, пиксель в пиксель):
  v_gen     вид MV после генерации (768²)                      `views_768/v0.png`
  v_up      тот же вид после RealESRGAN ×2 (1536²)             `views_<N>/v0.png`
  r_from0   рендер формы с картой, запечённой ТОЛЬКО из вида 0 `render_view0/r4096_from0.png`
  r_lossless рендер карты из 6 видов, до JPEG апстрима          `render_view0/r4096_lossless.png`
  r_from6   рендер карты из 6 видов, как лежит в GLB (после JPEG) `render_view0/r4096_from6.png`
  r_final   рендер итоговой карты 2048                         `render_view0/r2048.png`
Шаги, на которых меряется потеря: generation (фото → v_gen), upscale (v_gen → v_up, справочно), baking (v_up → r_from0), blending (r_from0 → r_lossless), jpeg (r_lossless → r_from6), downsample (r_from6 → r_final).

РЕГИСТРАЦИЯ ОДНА НА ТОВАР: фото → кадр вида 0 по силуэту (альфа фото против маски силуэта формы `render_view0/mask.png`): старт — рамки, затем ECC (аффинное преобразование, расстояние со знаком,
три масштаба); принимается, только если IoU силуэтов вырос. Фиксируется один раз и применяется ко всем стадиям (фото переносится в кадр стадии, стадии не двигаются). Только контур силуэта: внутренние кромки
формы в регистрации НЕ участвуют (каталожное фото плотно текстурировано — кромки узора принимались бы за кромки формы). `pattern_grad_ncc` зовётся только с `register=None`.
Общая маска фасада: силуэт формы ∩ силуэт фото ∩ (cos угла к камере ≥ 0,5), съеденная на 2 % ширины. Одна на товар; на других размерах — её уменьшение (в маске остаются только пиксели, целиком внутри).

Метрики на стадии (в маске, фото — в том же размере кадра):
  hf[σ]       энергия высоких частот L*: среднее (L − размытие σ)² в маске (размытие с нормировкой по маске, чтобы край маски не подмешивал фон); σ = 0,5 %, 1 %, 2 % ширины фасада; ratio = к фото;
  sigmaL      σ L* к фото (стандартное отклонение светлоты в маске, стадия/фото);
  dE00_lf     медиана ΔE00 к фото по низким частотам (размытие 3 % ширины каждого канала Lab);
  ncc         `pattern_metric.pattern_grad_ncc(register=None)`: median, p10.
Размеры: «common» — все стадии, уменьшенные до размера вида v_gen (для честного сравнения); «native» — каждая стадия в своём размере (v_up и рендеры).
Фото каталога маленькое (сотни пикселей): оно физически не содержит мелких деталей, поэтому ratio > 1 возможно (стадия мельче фото) — это не ошибка; читать как «стадия против фото».
Плотность текселей: по UV кадра вида 0 (`render_view0/uv.npz`), якобиан UV→экран, пересчёт в пиксели ФОТО (одна регистрация даёт масштаб), патчи 32×32 пикселя фото: медиана и p10 по патчам.

  stage_loss.py --stages <папка stages/> --photo <фото.rgba.png> [--out <json>]
  stage_loss.py --batch <OUT> --inputs <папка inputs30>      по каждому <OUT>/<магазин_товар>/stages/ → stage_loss.json + <OUT>/stage_loss_table.md
  stage_loss.py --selftest
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.normpath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, SCOUT)
import pattern_metric as PM  # noqa: E402

BANDS = (0.005, 0.01, 0.02)            # σ полос высоких частот, доля ширины фасада
MAIN_BAND = '1%'                       # полоса, по которой считается «потеря» в таблице
LF_SIGMA = 0.03                        # σ низких частот для ΔE00, доля ширины фасада
AOI_MIN = 0.5                          # cos угла к камере: фасад смотрит в камеру не круче ≈ 60°
ERODE_FRAC = 0.02                      # сколько срезать с края общей маски, доля ширины
PATCH_PHOTO_PX = 32                    # патч плотности текселей, пикселей фото
IOU_OK = 0.8                           # ниже — регистрации не верим (статус reg_poor), числа всё равно считаются
STEPS = ('generation', 'upscale', 'baking', 'blending', 'jpeg', 'downsample')
STEP_DEFS = {                          # шаг: (стадия до, стадия после, размер замера: common/native)
    'generation': (None, 'v_gen', 'common'), 'upscale': ('v_gen', 'v_up', 'common'), 'baking': ('v_up', 'r_from0', 'native'),
    'blending': ('r_from0', 'r_lossless', 'native'), 'jpeg': ('r_lossless', 'r_from6', 'native'), 'downsample': ('r_from6', 'r_final', 'native')}
STAGE_ORDER = ('v_gen', 'v_up', 'r_from0', 'r_lossless', 'r_from6', 'r_final')
RENDER_FILES = {'r_from0': 'render_view0/r4096_from0.png', 'r_lossless': 'render_view0/r4096_lossless.png', 'r_from6': 'render_view0/r4096_from6.png', 'r_final': 'render_view0/r2048.png'}


# ——— чтение ———
def read_rgb(path: str) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(path).convert('RGB'), dtype=np.uint8).copy()


def read_rgba(path: str) -> np.ndarray:
    from PIL import Image
    return np.asarray(Image.open(path).convert('RGBA'), dtype=np.uint8).copy()


def find_views(stages: str) -> tuple[str | None, str | None]:
    """(кадры генерации, кадры после апскейла): папки `views_<N>`, меньший N — генерация, больший — апскейл."""
    ds = sorted((int(os.path.basename(p)[6:]), p) for p in glob.glob(os.path.join(stages, 'views_[0-9]*')) if os.path.basename(p)[6:].isdigit())
    f = lambda d: os.path.join(d, 'v0.png') if d and os.path.exists(os.path.join(d, 'v0.png')) else None  # noqa: E731
    return (f(ds[0][1]) if ds else None), (f(ds[-1][1]) if len(ds) > 1 else None)


def load_stages(stages: str) -> dict:
    """{имя стадии: RGB uint8}; отсутствующих нет в словаре."""
    out = {}
    g, u = find_views(stages)
    if g:
        out['v_gen'] = read_rgb(g)
    if u:
        out['v_up'] = read_rgb(u)
    for k, rel in RENDER_FILES.items():
        p = os.path.join(stages, rel)
        if os.path.exists(p):
            out[k] = read_rgb(p)
    return out


# ——— геометрия и регистрация ———
def _bbox(m: np.ndarray):
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def iou(a: np.ndarray, b: np.ndarray) -> float:
    u = float((a | b).sum())
    return float((a & b).sum()) / u if u else 0.0


def sdf(mask: np.ndarray, clip: float = 48.0) -> np.ndarray:
    """Расстояние со знаком до границы (внутри +), в [−1, 1] по clip пикселей, слегка размытое: гладкая цель для ECC."""
    import cv2
    m = mask.astype(np.uint8)
    d = cv2.distanceTransform(m, cv2.DIST_L2, 3) - cv2.distanceTransform(1 - m, cv2.DIST_L2, 3)
    return cv2.GaussianBlur(np.clip(d, -clip, clip).astype(np.float32) / clip, (0, 0), 2.0)


def warp_inv(img: np.ndarray, P: np.ndarray, size: tuple[int, int], interp=None):
    """Кадр размера size (w, h) по обратной карте P (3×3: пиксель кадра → пиксель источника): `img(P·x)`; вне источника — 0."""
    import cv2
    return cv2.warpAffine(img, np.asarray(P, np.float64)[:2], size, flags=(interp if interp is not None else cv2.INTER_LINEAR) | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def register_photo(photo_alpha: np.ndarray, frame_mask: np.ndarray, scales=(0.25, 0.5, 1.0), iters: int = 150) -> dict:
    """Фото → кадр вида 0 по силуэту. Возвращает {'P': 3×3 (кадр → фото), 'iou_init', 'iou', 'method', 'cc'}. P — обратная карта: `photo(P·x_кадра)`."""
    import cv2
    A, S = photo_alpha.astype(bool), frame_mask.astype(bool)
    pb, fb = _bbox(A), _bbox(S)
    if pb is None or fb is None:
        raise ValueError('пустой силуэт: у фото нет альфы или у формы нет маски')
    h, w = S.shape
    sx, sy = (pb[2] - pb[0]) / (fb[2] - fb[0]), (pb[3] - pb[1]) / (fb[3] - fb[1])
    P0 = np.array([[sx, 0, pb[0] - sx * fb[0]], [0, sy, pb[1] - sy * fb[1]], [0, 0, 1]], np.float64)
    A0 = warp_inv(A.astype(np.float32), P0, (w, h)) > 0.5
    res = {'P': P0, 'iou_init': round(iou(A0, S), 4), 'iou': round(iou(A0, S), 4), 'method': 'bbox', 'cc': None}
    tmpl, inp = sdf(S), sdf(A0)
    Wm = np.eye(2, 3, dtype=np.float32)                       # кадр → кадр, остаточный сдвиг от ECC
    try:
        for s in scales:
            Ws = Wm.copy()
            Ws[:, 2] *= s
            sz = (max(8, int(w * s)), max(8, int(h * s)))
            a, b = cv2.resize(tmpl, sz, interpolation=cv2.INTER_AREA), cv2.resize(inp, sz, interpolation=cv2.INTER_AREA)
            cc, Ws = cv2.findTransformECC(a, b, Ws, cv2.MOTION_AFFINE, (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iters, 1e-6), None, 5)
            Wm = Ws.copy()
            Wm[:, 2] /= s
        W3 = np.vstack([Wm.astype(np.float64), [0, 0, 1]])
        P1 = P0 @ W3
        A1 = warp_inv(A.astype(np.float32), P1, (w, h)) > 0.5
        i1 = iou(A1, S)
        if i1 > res['iou']:
            res.update(P=P1, iou=round(i1, 4), method='bbox+ecc_affine', cc=round(float(cc), 4))
    except cv2.error as e:
        res['ecc_error'] = str(e)[:120]
    return res


def common_mask(S: np.ndarray, A: np.ndarray, aoi: np.ndarray | None) -> tuple[np.ndarray, float]:
    """Общая маска фасада в кадре и её ширина (пикселей)."""
    import cv2
    sil = S & A
    bb = _bbox(sil)
    if bb is None:
        return np.zeros_like(S), 0.0
    r = max(2, int(round(ERODE_FRAC * (bb[2] - bb[0]))))
    m = sil & (aoi >= AOI_MIN) if aoi is not None else sil
    m = cv2.erode(m.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
    mb = _bbox(m)
    return m, float(mb[2] - mb[0]) if mb else 0.0


def resize_mask(m: np.ndarray, n: int) -> np.ndarray:
    import cv2
    if m.shape[0] == n:
        return m
    return cv2.resize(m.astype(np.float32), (n, n), interpolation=cv2.INTER_AREA) > 0.999


# ——— метрики ———
def masked_blur(x: np.ndarray, m: np.ndarray, sigma: float) -> np.ndarray:
    import cv2
    mf = m.astype(np.float32)
    return cv2.GaussianBlur(x * mf, (0, 0), sigma) / np.maximum(cv2.GaussianBlur(mf, (0, 0), sigma), 1e-6)


def hf_energy(L: np.ndarray, m: np.ndarray, sigma: float) -> float:
    hp = L - masked_blur(L, m, sigma)
    return float((hp ** 2 * m).sum() / max(m.sum(), 1))


def de2000(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000, векторно (Sharma, Wu, Dalal 2005); входы (N, 3)."""
    L1, a1, b1 = lab1[:, 0].astype(np.float64), lab1[:, 1].astype(np.float64), lab1[:, 2].astype(np.float64)
    L2, a2, b2 = lab2[:, 0].astype(np.float64), lab2[:, 1].astype(np.float64), lab2[:, 2].astype(np.float64)
    C1, C2 = np.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p, h2p = np.degrees(np.arctan2(b1, a1p)) % 360, np.degrees(np.arctan2(b2, a2p)) % 360
    dL, dC = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dH = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh) / 2)
    Lb, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hb = np.where(C1p * C2p == 0, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    T = 1 - 0.17 * np.cos(np.radians(hb - 30)) + 0.24 * np.cos(np.radians(2 * hb)) + 0.32 * np.cos(np.radians(3 * hb + 6)) - 0.20 * np.cos(np.radians(4 * hb - 63))
    dth = 30 * np.exp(-(((hb - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25.0 ** 7))
    Sl = 1 + 0.015 * (Lb - 50) ** 2 / np.sqrt(20 + (Lb - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dL / Sl) ** 2 + (dC / Sc) ** 2 + (dH / Sh) ** 2 + Rt * (dC / Sc) * (dH / Sh))


def stage_metrics(img: np.ndarray, photo: np.ndarray, mask: np.ndarray, width: float, ncc: bool = True) -> dict:
    """Метрики одной стадии против фото (оба RGB uint8 одного размера) в маске."""
    m = mask.astype(np.float32)
    n = int(mask.sum())
    if n < 64 or width < 8:
        return {'n_px': n, 'error': 'маска слишком мала'}
    li, lp = PM.rgb_to_lab(img), PM.rgb_to_lab(photo)
    out: dict = {'n_px': n, 'width_px': round(width, 1), 'hf': {}}
    for fr in BANDS:
        sg = max(fr * width, 0.7)
        es, ep = hf_energy(li[..., 0], m, sg), hf_energy(lp[..., 0], m, sg)
        out['hf'][f'{fr * 100:g}%'] = {'sigma_px': round(sg, 2), 'stage': round(es, 3), 'photo': round(ep, 3), 'ratio': round(es / ep, 4) if ep > 1e-9 else None}
    sd = lambda L: float(np.sqrt(max(((L - (L * m).sum() / n) ** 2 * m).sum() / n, 0)))  # noqa: E731
    si, sp = sd(li[..., 0]), sd(lp[..., 0])
    out['sigmaL'] = {'stage': round(si, 3), 'photo': round(sp, 3), 'ratio': round(si / sp, 4) if sp > 1e-9 else None}
    sg = max(LF_SIGMA * width, 1.0)
    bi = np.stack([masked_blur(li[..., c], m, sg) for c in range(3)], -1)
    bp = np.stack([masked_blur(lp[..., c], m, sg) for c in range(3)], -1)
    ys, xs = np.nonzero(mask)
    sel = slice(None, None, max(1, len(xs) // 60000))
    out['dE00_lf_median'] = round(float(np.median(de2000(bi[ys[sel], xs[sel]], bp[ys[sel], xs[sel]]))), 3)
    if ncc:
        r = PM.pattern_grad_ncc(img, photo, mask.astype(bool), register=None)      # регистрация — ОДНА, до метрики; своя ECC метрики выключена
        out['ncc'] = {'median': r.get('median'), 'p10': r.get('p10'), 'share_good': r.get('share_good'), 'n_patches': r.get('n_patches')}
    return out


def texel_density(uv_npz: str, uv_size: int, mask: np.ndarray, P: np.ndarray, patch_photo_px: int = PATCH_PHOTO_PX) -> dict:
    """Тексели развёртки на пиксель фото: якобиан (u, v)·uv_size по пикселям кадра, пересчёт через масштаб регистрации, медиана по патчам 32×32 px фото (медиана и p10 по патчам)."""
    d = np.load(uv_npz)
    uv, vm = d['uv'].astype(np.float64), d['mask'].astype(bool)
    ux, uy = uv[..., 0] * uv_size, uv[..., 1] * uv_size
    dux_dy, dux_dx = np.gradient(ux)
    duy_dy, duy_dx = np.gradient(uy)
    lin = np.sqrt(np.abs(dux_dx * duy_dy - dux_dy * duy_dx))                  # тексель на пиксель кадра (по линейному размеру)
    detP = abs(P[0, 0] * P[1, 1] - P[0, 1] * P[1, 0])                         # (пикселей фото на пиксель кадра)²
    if detP <= 0:
        return {'error': 'вырожденная регистрация'}
    per_photo = lin / np.sqrt(detP)
    ok = mask & vm & (lin < 50) & (np.hypot(dux_dx, dux_dy) < 50) & (np.hypot(duy_dx, duy_dy) < 50)      # швы развёртки: скачок UV даёт «бесконечный» якобиан — не считаем
    pf = max(4, int(round(patch_photo_px / np.sqrt(detP))))
    vals = []
    h, w = mask.shape
    for y in range(0, h - pf + 1, pf):
        for x in range(0, w - pf + 1, pf):
            blk = ok[y:y + pf, x:x + pf]
            if blk.mean() >= 0.8 and mask[y:y + pf, x:x + pf].mean() >= 0.8:
                vals.append(float(np.median(per_photo[y:y + pf, x:x + pf][blk])))
    if not vals:
        return {'n_patches': 0, 'note': 'нет патчей в маске'}
    v = np.array(vals)
    return {'texels_per_photo_px': {'median': round(float(np.median(v)), 3), 'p10': round(float(np.percentile(v, 10)), 3)}, 'texels_per_frame_px_median': round(float(np.median(lin[ok])), 3),
            'n_patches': len(vals), 'patch_frame_px': pf, 'uv_size': uv_size, 'photo_px_per_frame_px': round(float(np.sqrt(detP)), 4)}


# ——— по товару ———
def analyze(stages: str, photo_path: str, ncc_native: bool = True) -> dict:
    """Весь разбор одного товара → словарь (его пишут в JSON)."""
    import cv2
    man = json.load(open(os.path.join(stages, 'manifest.json'), encoding='utf-8')) if os.path.exists(os.path.join(stages, 'manifest.json')) else {}
    S = np.asarray(__import__('PIL.Image', fromlist=['Image']).open(os.path.join(stages, 'render_view0', 'mask.png')).convert('L')) > 127
    aoi16 = os.path.join(stages, 'render_view0', 'aoi_cos16.png')
    aoi = (np.asarray(__import__('PIL.Image', fromlist=['Image']).open(aoi16)).astype(np.float32) / 65535.0) if os.path.exists(aoi16) else None
    photo = read_rgba(photo_path)
    A_src = photo[..., 3] > 127
    reg = register_photo(A_src, S)
    P = reg['P']
    fh, fw = S.shape
    A_fr = warp_inv(A_src.astype(np.float32), P, (fw, fh)) > 0.5
    cm, width = common_mask(S, A_fr, aoi)
    st = load_stages(stages)
    res: dict = {'photo': photo_path, 'stages_dir': stages, 'frame_px': fh,
                 'registration': {k: (v if k != 'P' else [round(float(x), 6) for x in np.asarray(P).ravel()]) for k, v in reg.items()},
                 'mask': {'px': int(cm.sum()), 'width_px': round(width, 1), 'aoi_min': AOI_MIN, 'erode_frac': ERODE_FRAC}, 'stages': {}, 'status': 'ok'}
    if reg['iou'] < IOU_OK:
        res['status'] = 'reg_poor'
        res['note'] = f'IoU силуэтов после регистрации {reg["iou"]} < {IOU_OK}: фото и вид 0 не совпали по силуэту, числа ориентировочные'
    if width < 16:
        res['status'] = 'no_facade'
        res['note'] = 'общая маска фасада пуста'
        return res
    n_common = st['v_gen'].shape[0] if 'v_gen' in st else fh

    def photo_at(n: int) -> np.ndarray:
        if n < fh:                      # меньше кадра: фото в кадр, затем усреднение по площади, как у стадий (иначе точечная выборка даёт ложный «звон» и расхождение полос)
            full = np.clip(warp_inv(photo[..., :3], P, (fh, fh), cv2.INTER_LINEAR), 0, 255).astype(np.uint8)
            return cv2.resize(full, (n, n), interpolation=cv2.INTER_AREA)
        k = fh / n
        return np.clip(warp_inv(photo[..., :3], P @ np.diag([k, k, 1.0]), (n, n), cv2.INTER_LINEAR), 0, 255).astype(np.uint8)

    def at_size(img: np.ndarray, n: int) -> np.ndarray:
        return img if img.shape[0] == n else cv2.resize(img, (n, n), interpolation=cv2.INTER_AREA)
    for name in STAGE_ORDER:
        if name not in st:
            continue
        img = st[name]
        nat = img.shape[0]
        r: dict = {'native_px': nat}
        for tag, n in (('common', n_common), ('native', nat)):
            if tag == 'native' and n == n_common:
                r['native'] = '= common'
                continue
            m = resize_mask(cm, n)
            r[tag] = stage_metrics(at_size(img, n), photo_at(n), m, width * n / fh, ncc=(tag == 'common' or ncc_native))
        res['stages'][name] = r
    uvp = os.path.join(stages, 'render_view0', 'uv.npz')
    if os.path.exists(uvp) and man.get('uv_size'):
        res['density'] = texel_density(uvp, int(man['uv_size']), cm, P)
    res['steps'] = steps_table(res['stages'])
    res['biggest'] = biggest_step(res['steps'])
    for k in ('yaw_deg', 'uv_size', 'texture_size', 'jpeg_mae_255'):
        if k in man:
            res.setdefault('manifest', {})[k] = man[k]
    return res


def _ratio(stage_rec: dict | None, tag: str, band: str = MAIN_BAND):
    if not stage_rec:
        return None
    m = stage_rec.get(tag)
    if m == '= common':
        m = stage_rec.get('common')
    try:
        return m['hf'][band]['ratio']
    except (KeyError, TypeError):
        return None


def _ncc(stage_rec: dict | None, tag: str):
    if not stage_rec:
        return None
    m = stage_rec.get(tag)
    if m == '= common':
        m = stage_rec.get('common')
    try:
        return m['ncc']['median']
    except (KeyError, TypeError):
        return None


def steps_table(stages: dict) -> dict:
    """По шагам: ratio высоких частот (полоса MAIN_BAND) до и после, потеря в % (отрицательная — «прибавка»), изменение pattern_grad_ncc. Нет стадии — шаг None."""
    out = {}
    for step, (a, b, tag) in STEP_DEFS.items():
        rb = _ratio(stages.get(b), tag)
        ra = 1.0 if a is None else _ratio(stages.get(a), tag)
        if rb is None or ra is None or ra <= 0:
            out[step] = None
            continue
        row = {'size': tag, 'hf_ratio_before': ra, 'hf_ratio_after': rb, 'loss_pct': round((1 - rb / ra) * 100, 1)}
        for band in BANDS:
            bn = f'{band * 100:g}%'
            xa, xb = (1.0 if a is None else _ratio(stages.get(a), tag, bn)), _ratio(stages.get(b), tag, bn)
            row['loss_pct_' + bn] = round((1 - xb / xa) * 100, 1) if xa and xb is not None else None
        na, nb = (None if a is None else _ncc(stages.get(a), tag)), _ncc(stages.get(b), tag)
        row['ncc_after'] = nb
        row['ncc_delta'] = round(nb - na, 3) if na is not None and nb is not None else None
        out[step] = row
    fin = stages.get('r_final')
    if fin:
        out['cumulative'] = {'hf_ratio_final_common': _ratio(fin, 'common'), 'ncc_final_common': _ncc(fin, 'common')}
    return out


def biggest_step(steps: dict) -> str | None:
    cand = {k: v['loss_pct'] for k, v in steps.items() if k in STEPS and k != 'upscale' and isinstance(v, dict) and v.get('loss_pct') is not None}
    return max(cand, key=cand.get) if cand else None


def table_md(results: dict) -> str:
    """Таблица по набору: потеря высоких частот (% по полосе MAIN_BAND) на каждом шаге, плотность текселей, где теряется больше всего."""
    names = ('generation', 'baking', 'blending', 'jpeg', 'downsample')
    lines = ['| товар | статус | генерация | запекание (1 вид) | смешивание 6 видов | JPEG | уменьшение 4096→2048 | текселей/пикс. фото (медиана / p10) | больше всего теряется |', '|---|---|---|---|---|---|---|---|---|']
    tot: dict = {n: [] for n in names}
    for key, r in results.items():
        if not isinstance(r, dict) or 'steps' not in r:
            lines.append(f'| {key} | {(r or {}).get("status", "нет данных")} | | | | | | | |')
            continue
        cells = []
        for n in names:
            v = (r['steps'].get(n) or {}).get('loss_pct')
            cells.append('—' if v is None else f'{v:+.0f} %')
            if v is not None:
                tot[n].append(v)
        d = (r.get('density') or {}).get('texels_per_photo_px') or {}
        lines.append(f'| {key} | {r["status"]} | ' + ' | '.join(cells) + f' | {d.get("median", "—")} / {d.get("p10", "—")} | {r.get("biggest") or "—"} |')
    med = ' | '.join(('—' if not tot[n] else f'{float(np.median(tot[n])):+.0f} %') for n in names)
    lines.append(f'| **медиана по набору** | | {med} | | |')
    lines.append('')
    lines.append(f'Потеря = 1 − (отношение энергии высоких частот L* «стадия / фото» после шага) / (до шага), полоса σ = {MAIN_BAND} ширины фасада; «+» — потеряно, «−» — прибавилось. Шаги меряются в своих размерах: '
                 'генерация — в размере вида 768, остальные — в 1536 (родной размер рендера).')
    return '\n'.join(lines)


def batch(out_root: str, inputs: str, ncc_native: bool = True) -> dict:
    res = {}
    for d in sorted(glob.glob(os.path.join(out_root, '*', 'stages'))):
        key = os.path.basename(os.path.dirname(d))
        photo = os.path.join(inputs, key + '.rgba.png')
        if not os.path.exists(photo):
            res[key] = {'status': 'нет фото: ' + photo}
            continue
        try:
            res[key] = analyze(d, photo, ncc_native)
        except Exception as e:  # noqa: BLE001 — один товар не роняет набор
            res[key] = {'status': f'ошибка {type(e).__name__}: {str(e)[:200]}'}
        json.dump(res[key], open(os.path.join(os.path.dirname(d), 'stage_loss.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(key, res[key].get('status'), res[key].get('biggest'), flush=True)
    open(os.path.join(out_root, 'stage_loss_table.md'), 'w', encoding='utf-8').write(table_md(res))
    json.dump(res, open(os.path.join(out_root, 'stage_loss_all.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


# ——— самотест на синтетике ———
def _synth(dst: str, blur_from: str | None, frame: int = 384, uv_size: int = 192, blur_sigma: float = 3.0, rot_deg: float = 0.0) -> tuple[str, dict]:
    """Синтетический товар: шахматка (клетка 6 px на «фото» 260×230, альфа — прямоугольник) → кадр вида 0 (масштаб ×1,2, сдвиг) — «идеальные» стадии = фото в кадре. С `blur_from` стадия с этим именем
    и ВСЕ следующие по цепочке размыты гауссом σ = blur_sigma px (кадра; на виде 768/2 — вдвое меньше). Возвращает (папка stages, истинная карта фото→кадр)."""
    import cv2
    from PIL import Image
    chain = ['v_gen', 'v_up', 'r_from0', 'r_lossless', 'r_from6', 'r_final']
    stages = os.path.join(dst, 'stages')
    os.makedirs(os.path.join(stages, 'render_view0'), exist_ok=True)
    ph, pw = 230, 260
    cell = 6
    yy, xx = np.mgrid[0:ph, 0:pw]
    chk = (((yy // cell) + (xx // cell)) % 2).astype(np.float32)
    photo = np.stack([60 + 130 * chk, 60 + 110 * chk, 60 + 90 * chk], -1).astype(np.uint8)
    alpha = np.zeros((ph, pw), np.uint8)
    alpha[15:ph - 15, 15:pw - 15] = 255
    Image.fromarray(np.dstack([photo, alpha])).save(os.path.join(dst, 'photo.rgba.png'))
    k, tx, ty = 1.2, 30.0, 25.0
    P_true = np.array([[1 / k, 0, -tx / k], [0, 1 / k, -ty / k], [0, 0, 1]], np.float64)           # кадр → фото
    c = np.array([frame / 2, frame / 2])
    if rot_deg:                                                    # силуэт формы повёрнут относительно фото: проверка ECC
        R = cv2.getRotationMatrix2D((float(c[0]), float(c[1])), rot_deg, 1.0)
        R3 = np.vstack([R, [0, 0, 1]])
        P_view = P_true @ np.linalg.inv(R3)
    else:
        P_view = P_true
    F = np.clip(warp_inv(photo, P_view, (frame, frame), cv2.INTER_LINEAR), 0, 255).astype(np.uint8)
    S = warp_inv(alpha.astype(np.float32), P_view, (frame, frame)) > 127
    F[~S] = 128
    Image.fromarray((S * 255).astype(np.uint8)).save(os.path.join(stages, 'render_view0', 'mask.png'))
    Image.fromarray(np.full((frame, frame), int(0.9 * 65535), np.uint16)).save(os.path.join(stages, 'render_view0', 'aoi_cos16.png'))
    gy, gx = np.mgrid[0:frame, 0:frame].astype(np.float32)
    np.savez_compressed(os.path.join(stages, 'render_view0', 'uv.npz'), uv=np.stack([gx / frame, gy / frame], -1), mask=np.ones((frame, frame), bool))
    json.dump({'uv_size': uv_size, 'render_px': frame}, open(os.path.join(stages, 'manifest.json'), 'w'))
    cur_blur = False
    for name in chain:
        if blur_from == name:
            cur_blur = True
        img = F.copy()
        if name == 'v_gen':
            img = cv2.resize(img, (frame // 2, frame // 2), interpolation=cv2.INTER_AREA)
        if cur_blur:
            img = cv2.GaussianBlur(img, (0, 0), blur_sigma / (2 if name == 'v_gen' else 1))
        if name == 'v_gen':
            os.makedirs(os.path.join(stages, f'views_{frame // 2}'), exist_ok=True)
            Image.fromarray(img).save(os.path.join(stages, f'views_{frame // 2}', 'v0.png'))
        elif name == 'v_up':
            os.makedirs(os.path.join(stages, f'views_{frame}'), exist_ok=True)
            Image.fromarray(img).save(os.path.join(stages, f'views_{frame}', 'v0.png'))
        else:
            Image.fromarray(img).save(os.path.join(stages, RENDER_FILES[name]))
    return stages, {'P_true': P_view, 'frame': frame, 'k': k}


def selftest() -> int:
    import tempfile
    fails = []

    def check(n, c, e=''):
        print(('OK   ' if c else 'FAIL ') + n + (f'  [{e}]' if e else ''))
        if not c:
            fails.append(n)
    # 1) регистрация: повёрнутый на 2° силуэт формы — ECC должна сойтись лучше рамок
    d0 = tempfile.mkdtemp(prefix='sl-')
    stages, info = _synth(d0, None, rot_deg=2.0)
    S = np.asarray(__import__('PIL.Image', fromlist=['Image']).open(os.path.join(stages, 'render_view0', 'mask.png'))) > 127
    A = read_rgba(os.path.join(d0, 'photo.rgba.png'))[..., 3] > 127
    reg = register_photo(A, S)
    check('регистрация: ECC поднимает IoU силуэтов выше рамок и до ≥ 0,97', reg['method'] == 'bbox+ecc_affine' and reg['iou'] > reg['iou_init'] and reg['iou'] >= 0.97, str({k: v for k, v in reg.items() if k != 'P'}))
    # 2) ни одного вызова pattern_grad_ncc с совмещением внутри метрики
    calls = []
    orig = PM.pattern_grad_ncc

    def spy(*a, **kw):
        calls.append(kw.get('register', 'homography'))
        return orig(*a, **kw)
    PM.pattern_grad_ncc = spy
    # 3) потеря на ОДНОМ шаге: размытие стадии и всех следующих → наибольшая потеря именно на этом шаге
    want = {'generation': 'v_gen', 'baking': 'r_from0', 'blending': 'r_lossless', 'jpeg': 'r_from6', 'downsample': 'r_final'}
    try:
        for step, st in want.items():
            d = tempfile.mkdtemp(prefix='sl-')
            stages, info = _synth(d, st)
            r = analyze(stages, os.path.join(d, 'photo.rgba.png'), ncc_native=False)
            row = r['steps'].get(step) or {}
            others = [v['loss_pct'] for k, v in r['steps'].items() if k in STEPS and k not in (step, 'upscale') and isinstance(v, dict)]
            check(f'размытие на шаге «{step}»: потеря именно там (> 35 %), на остальных шагах < 15 %, biggest = {step}', r['biggest'] == step and row.get('loss_pct', 0) > 35 and all(abs(x) < 15 for x in others),
                  str({'biggest': r['biggest'], 'steps': {k: (v or {}).get('loss_pct') for k, v in r['steps'].items() if k in STEPS}}))
        d = tempfile.mkdtemp(prefix='sl-')
        stages, info = _synth(d, None)
        r = analyze(stages, os.path.join(d, 'photo.rgba.png'), ncc_native=False)
        losses = {k: v['loss_pct'] for k, v in r['steps'].items() if k in STEPS and isinstance(v, dict)}
        check('контроль без размытия: ни на одном шаге потери больше 15 %, фото регистрируется (IoU ≥ 0,97), статус ok', all(abs(x) < 15 for x in losses.values()) and r['registration']['iou'] >= 0.97 and r['status'] == 'ok', str((losses, r['registration']['iou'])))
        ncc_c = r['stages']['r_final']['common']['ncc']['median']
        check('контроль: pattern_grad_ncc ≈ 1 (рисунок совпал с фото)', ncc_c is not None and ncc_c > 0.85, str(ncc_c))
        check('регистрация фиксируется ОДИН раз: у всех стадий один набор из registration; pattern_grad_ncc всегда с register=None', bool(calls) and all(c is None for c in calls), str(set(calls)))
        dd = r['density']['texels_per_photo_px']
        check('плотность текселей: UV кадр/2 → 0,5 текселя на пиксель кадра, фото в 1,2 раза грубее → 0,6 на пиксель фото (±5 %)', abs(dd['median'] - 0.6) < 0.03 and abs(dd['p10'] - 0.6) < 0.05, str(r['density']))
        check('ΔE00 по низким частотам у контроля мал (< 3), σL ≈ фото (0,8…1,2)', r['stages']['r_final']['common']['dE00_lf_median'] < 3 and 0.8 < r['stages']['r_final']['common']['sigmaL']['ratio'] < 1.2, str(r['stages']['r_final']['common']['dE00_lf_median']))
        # 4) таблица по набору
        md = table_md({'a_1': r, 'b_2': {'status': 'нет фото'}})
        check('таблица по набору: строка товара, строка без данных, медиана, пояснение', '| a_1 |' in md and '| b_2 |' in md and 'медиана по набору' in md and 'Потеря = 1' in md)
    finally:
        PM.pattern_grad_ncc = orig
    # 5) ΔE00: эталонные пары Sharma, Wu, Dalal (2005), таблица 1 (пары 1, 2, 3)
    ref = [((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425), ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615), ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412)]
    got = de2000(np.array([r_[0] for r_ in ref]), np.array([r_[1] for r_ in ref]))
    check('ΔE00 совпадает с эталонными парами Sharma-Wu-Dalal (±0,001)', all(abs(g - r_[2]) < 1e-3 for g, r_ in zip(got, ref)), str(got))
    print('\nПРОВАЛЕНО: ' + ', '.join(fails) if fails else '\nвсё прошло')
    return 1 if fails else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--stages')
    ap.add_argument('--photo')
    ap.add_argument('--out')
    ap.add_argument('--batch', help='папка прогона OUT: по каждому <OUT>/<магазин_товар>/stages/')
    ap.add_argument('--inputs', help='папка с <магазин_товар>.rgba.png (inputs30)')
    ap.add_argument('--no-ncc-native', action='store_true', help='не считать pattern_grad_ncc в родном размере 1536 (быстрее)')
    ap.add_argument('--selftest', action='store_true')
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.batch:
        if not a.inputs:
            print('--batch требует --inputs')
            return 2
        batch(a.batch, a.inputs, not a.no_ncc_native)
        return 0
    if not (a.stages and a.photo):
        print(__doc__)
        return 2
    r = analyze(a.stages, a.photo, not a.no_ncc_native)
    txt = json.dumps(r, ensure_ascii=False, indent=1)
    if a.out:
        open(a.out, 'w', encoding='utf-8').write(txt)
    print(txt)
    return 0


if __name__ == '__main__':
    sys.exit(main())

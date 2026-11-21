#!/usr/bin/env python3
"""T-20261119-88 (план `mesh-photo-projection-01`, шаг 2 цепочки «вариант 9»): пиксели фото на ВИДИМУЮ СТОРОНУ готовой карты краски, форма и развёртка не меняются.

ИДЕЯ. У пробы А0 для каждого товара сохранён кадр вида 0 (`stages/render_view0/`: для каждого пикселя кадра 1536² — точка развёртки `uv.npz`, видимость `mask.png`, cos угла обзора
`aoi_cos16.png`, нормаль в камере `normal_cam.png`), а `stage_loss.json` даёт регистрацию фото → этот кадр (одна на товар). Значит фото можно положить в карту НАПРЯМУЮ: пиксель кадра →
его тексель → цвет фото. Своей перспективной камеры и повторной видимости не нужно (старый `photo_project.py` считал их заново и ошибался; см. ниже).

  1. Вес пикселя (уверенность) = вес по углу × гейт «двойного узора» × растушёвка по поверхности × внутренность силуэта.
     • угол: `clip((cos − COS_LO)/(COS_HI − COS_LO), 0, 1)²`: 0 у касательных, 1 у фронтальных (идея `cos^k` у смешивания видов в Hunyuan3D-Paint, `bake_exp = 4`; здесь степень 2 — вид ОДИН).
     • силуэт: маска вида ∩ маска фото в кадре, съеденная на `EDGE_ERODE` — на краю фото смешано с фоном.
     • гейт (главная защита от двойного узора — см. ниже): по участкам.
     • растушёвка: вес плавно падает от 1 до 0 у границы зоны «можно класть» — расстояние в КАДРЕ среди ВИДИМЫХ пикселей (не по текселям: у невидимых текселей точки нет — так была
       ошибка `fade_weight` в `photo_project.py`: P3 = 0, FID = −1), домноженное на локальный множитель 1/cos (сглажен) — длина вдоль поверхности, а не проекция (грубо, без учёта кривизны).
       Радиус — доля ширины фасада (`FADE_FRAC`), а не текселя UV (вторая ошибка: `LP_SIGMA` в текселях на дробной развёртке: размер тексель плавает).
  2. Свет: блики и тени фото не переносим как есть: широкие градиенты L* фото (σ = `LIGHT_FRAC` ширины фасада) заменены широкими градиентами рендера карты-входа (MV/А1), мелкие детали L* фото
     остаются; a*b* — фото. Режим `--light raw` — сырое фото (для сравнения).
  3. Фото → карта: пиксель кадра рассыпается на 4 соседних текселя (билинейно; вес = уверенность), накопления сглаживаются (σ = `SPLAT_SIGMA` текселей: плотность текселей выше плотности пикселей),
     итог = карта·(1 − w) + фото·w, w — средняя уверенность по накопленной массе, там, где масса накопления ≥ `COVER_MIN`. Остальные тексели (невидимые с вида 0) — как были.

ГЕЙТ «РЕЛЬЕФ ≠ ФОТО → НЕ КЛАСТЬ» (упрощённая версия А2-lite). Двойной узор: форма (придуманный генератором рельеф) не совпадает с раскладкой на фото, и фото ложится на рельеф со сдвигом.
По участкам размера `PATCH_FRAC`·ширина (и по пикселям внутри участка):
  • рельеф есть — доля пикселей с резким наклоном поверхности ≥ `REL_T` ≥ `REL_FRAC`; наклон — по ГЛУБИНЕ кадра: 3D-точка каждого текселя (барицентры грани, `texel_positions`) → кадр через `uv.npz`
    → плоскость кадра регрессией → остаток вдоль её нормали (`frame_depth`, `depth_edges`). Нормали `normal_cam` не годятся: у плоских плит с узором листьев поворот нормали почти нулевой;
  • совпадение — доля кромок РЕЛЬЕФА, рядом с которыми (≤ `TOL_FRAC` ширины) есть кромка ФОТО (сильные градиенты L* фото без низких частот), с поправкой на случайные попадания
    (доля площади участка рядом с кромкой фото): (сырое − случайное) / (1 − случайное) — плотные кромки фото иначе совпадают «сами»;
  • решение: нет рельефа → класть (риск двойного узора нулевой); рельеф есть и совпадение ≥ `AGREE_MIN` → класть; иначе — не класть (остаётся MV).
Доля отказанных пикселей — в json. Периодичность (повторяющийся узор с неоднозначным совпадением) — НЕ проверяется (отступление: см. отчёт T-88).

  photo_front.py --glb <GLB с картой> --stages <папка stages/ товара> --photo <фото .rgba.png> --out-dir <папка> --stem <имя> [--light lp|raw] [--out-size 4096]
  → <out-dir>/<stem>-photo.glb, <stem>.photo.json, <stem>.view0_{in,photo}.png, <stem>.photo-conf.png (уверенность в кадре), <stem>.photo-gate.png, <stem>.photo-layer.png
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
import a1_tone as A  # noqa: E402
import ab_tint as T  # noqa: E402
import pattern_metric as PM  # noqa: E402
import stage_loss as SL  # noqa: E402

COS_LO, COS_HI = 0.30, 0.80       # вес по углу: 0 при cos ≤ COS_LO, 1 при cos ≥ COS_HI (квадратичный подъём между)
EDGE_ERODE_FRAC = 0.004           # эрозия маски силуэта, доля ширины фасада (≥ 3 px)
FADE_FRAC = 0.012                 # радиус растушёвки по поверхности, доля ширины фасада
LIGHT_FRAC = 0.03                 # σ «широких» частот L*, доля ширины фасада
PATCH_FRAC = 0.06                 # сторона участка гейта, доля ширины фасада
TOL_FRAC = 0.006                  # допуск «кромка рельефа рядом с кромкой фото», доля ширины фасада
REL_T = 0.15                      # порог «кромка рельефа»: наклон поверхности dz/dx по глубине кадра (ступеньки плит дают ≫ 1)
REL_FRAC = 0.02                   # рельеф есть, если резких пикселей в участке не меньше этой доли его площади
AGREE_MIN = 0.50                  # совпадение кромок для разрешения класть: (доля кромок рельефа рядом с кромкой фото − доля «случайных попаданий») / (1 − доля случайных)
PHOTO_EDGE_PCT = 92.0             # кромка фото — градиент L* выше этого процентиля внутри маски
REL_MED_K = 12.0                  # порог кромки рельефа не ниже стольких медиан наклона предмета (см. relief_threshold)
GATE_SMOOTH_FRAC = 0.02           # σ сглаживания решения гейта (чтобы не было швов по границам участков), доля ширины
SPLAT_SIGMA = 1.2                 # минимальная σ сглаживания накоплений в текселях
SPLAT_SIGMA_K = 0.55              # σ не меньше этого × √(текселей на пиксель кадра)
COVER_MIN = 0.25                  # тексель покрыт, если масса накопления ≥ этой доли типичной (медианной) массы
CONF_MIN = 0.02
FLOW_WIN_FRAC, FLOW_MAX_FRAC, FLOW_SMOOTH_FRAC = 0.05, 0.025, 0.02   # нежёсткая подгонка (--flow): окно потока, предел сдвига, сглаживание — доли ширины фасада
EDGE_MIN_LEN = 0.02               # длинные кромки для совпадения: компоненты не короче доли ширины фасада (T-112; 0 — как раньше)
REG_MIN = 0.50                    # фото кладём, только если после ECC совпадение кромок фото↔база не ниже этого (иначе — только MV)
COLOR_T0 = 7.0                    # цветовой гейт: расхождение a*b* фото и базы (после вычета общего сдвига оттенка) ниже — класть полностью
COLOR_T1 = 16.0                   # выше — не класть (фото другого материала: серое поверх дерева); между — плавно
BASE_EDGE_T = 0.5                 # «рельеф» гейта по базе: кромки рендера базы заданы как 0/1


def smooth(x: np.ndarray, sigma: float) -> np.ndarray:
    import cv2
    return cv2.GaussianBlur(x.astype(np.float32), (0, 0), max(sigma, 0.3))


def masked_blur(x: np.ndarray, m: np.ndarray, sigma: float) -> np.ndarray:
    """Гауссово размытие внутри маски (фон не подмешивается): blur(x·m) / blur(m)."""
    mf = m.astype(np.float32)
    return smooth(x * mf, sigma) / np.maximum(smooth(mf, sigma), 1e-4)


def angle_weight(cos: np.ndarray) -> np.ndarray:
    t = np.clip((cos - COS_LO) / (COS_HI - COS_LO), 0, 1)
    return (t * t).astype(np.float32)


def texel_positions(V: np.ndarray, F: np.ndarray, UV: np.ndarray, T: int) -> tuple[np.ndarray, np.ndarray]:
    """3D-точка каждого текселя карты T×T (барицентры грани; строки — v_flipped, как `uv.npz`) и маска «тексель внутри островка». Растеризатор — `tex_coverage.raster`."""
    import tex_coverage as TC
    V, F, UV = np.asarray(V, np.float64), np.asarray(F, np.int64), np.asarray(UV, np.float64)
    xy = np.stack([UV[:, 0] * T, (1.0 - UV[:, 1]) * T], 1)
    ids, _ = TC.raster(xy, F, T)
    ti = np.nonzero(ids >= 0)[0]
    f = ids[ti].astype(np.int64)
    a_, b_, c_ = F[f, 0], F[f, 1], F[f, 2]
    px, py = (ti % T) + 0.5, (ti // T) + 0.5
    A_, B_, C_ = xy[a_], xy[b_], xy[c_]
    ar = (B_[:, 0] - A_[:, 0]) * (C_[:, 1] - A_[:, 1]) - (B_[:, 1] - A_[:, 1]) * (C_[:, 0] - A_[:, 0])
    wa = ((B_[:, 0] - px) * (C_[:, 1] - py) - (B_[:, 1] - py) * (C_[:, 0] - px)) / ar
    wb = ((C_[:, 0] - px) * (A_[:, 1] - py) - (C_[:, 1] - py) * (A_[:, 0] - px)) / ar
    Q = wa[:, None] * V[a_] + wb[:, None] * V[b_] + (1.0 - wa - wb)[:, None] * V[c_]
    pos = np.zeros((T * T, 3), np.float32)
    pos[ti] = Q
    valid = np.zeros(T * T, bool)
    valid[ti] = True
    return pos.reshape(T, T, 3), valid.reshape(T, T)


def frame_depth(pos: np.ndarray, valid: np.ndarray, uv: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, float]:
    """Глубина кадра вида 0 (ортографика): 3D-точка пикселя = `pos` в его текселе (`uv.npz`); камера не нужна — линейная регрессия 3D-точки на (x, y) пикселя даёт плоскость кадра, остаток вдоль
    её нормали — глубина (единицы формы). Возвращает глубину (кадр, 0 вне маски) и 3D-длину одного пикселя (для наклонов)."""
    import cv2
    T = pos.shape[0]
    mx, my = uv[..., 0].astype(np.float32) * T - 0.5, uv[..., 1].astype(np.float32) * T - 0.5
    P3 = np.stack([cv2.remap(pos[..., c], mx, my, cv2.INTER_NEAREST) for c in range(3)], -1)
    ok = mask & (cv2.remap(valid.astype(np.uint8), mx, my, cv2.INTER_NEAREST) > 0)
    ys, xs = np.nonzero(ok)
    X = np.stack([xs.astype(np.float64), ys.astype(np.float64), np.ones(len(xs))], 1)
    C, *_ = np.linalg.lstsq(X, P3[ys, xs].astype(np.float64), rcond=None)
    nrm = np.cross(C[0], C[1])
    nrm /= max(np.linalg.norm(nrm), 1e-12)
    depth = np.zeros(mask.shape, np.float32)
    depth[ys, xs] = ((P3[ys, xs] - X @ C) @ nrm).astype(np.float32)
    px_len = float(0.5 * (np.linalg.norm(C[0]) + np.linalg.norm(C[1])))
    return depth, px_len


def depth_edges(depth: np.ndarray, mask: np.ndarray, px_len: float) -> np.ndarray:
    """Наклон поверхности по глубине (dz/dx, без размерности): √(gx²+gy²)/длина пикселя; ступеньки плит и кромки рельефа дают большие значения. Глубина сглажена на 1 px."""
    import cv2
    d = smooth(depth, 0.8)
    gx, gy = cv2.Sobel(d, cv2.CV_32F, 1, 0, ksize=3) / 8.0, cv2.Sobel(d, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    return np.where(mask, np.hypot(gx, gy) / max(px_len, 1e-12), 0.0).astype(np.float32)


def relief_threshold(rel: np.ndarray, mask: np.ndarray) -> float:
    """Порог «кромка рельефа» для предмета: не ниже `REL_T` и не ниже `REL_MED_K` медиан наклона. У гладкой плиты медиана ≈ 0 → работает `REL_T`; у мягкой мебели геометрия шумная (медиана наклона
    в десятки раз выше) — абсолютный порог объявил бы «рельефом» всю поверхность и гейт отказал бы всё."""
    med = float(np.median(rel[mask])) if mask.any() else 0.0
    return max(REL_T, REL_MED_K * med)


def photo_edges(L_photo: np.ndarray, mask: np.ndarray, width: float) -> np.ndarray:
    """Кромки фото (bool): градиент L* после снятия низких частот выше процентиля внутри маски."""
    import cv2
    hf = L_photo - masked_blur(L_photo, mask, LIGHT_FRAC * width)
    h = smooth(hf, 1.0)
    g = np.hypot(cv2.Sobel(h, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(h, cv2.CV_32F, 0, 1, ksize=3))
    thr = np.percentile(g[mask], PHOTO_EDGE_PCT) if mask.any() else 1e9
    return (g > thr) & mask


def gate_map(rel: np.ndarray, ph_edge: np.ndarray, mask: np.ndarray, width: float, rel_t: float | None = None) -> tuple[np.ndarray, dict]:
    """Гейт по участкам → вес 0..1 в кадре (сглажен) и счётчики. Нет рельефа — 1; есть рельеф и кромки совпали — 1; иначе 0."""
    from scipy.ndimage import distance_transform_edt
    H, W = mask.shape
    P = max(16, int(round(PATCH_FRAC * width)))
    tol = max(2.0, TOL_FRAC * width)
    d_ph = distance_transform_edt(~ph_edge)
    rel_t = REL_T if rel_t is None else rel_t
    rel_px = (rel >= rel_t) & mask
    match_px = rel_px & (d_ph <= tol)
    ny, nx = -(-H // P), -(-W // P)
    pad = lambda a: np.pad(a.astype(np.float32), ((0, ny * P - H), (0, nx * P - W)))  # noqa: E731
    blk = lambda a: pad(a).reshape(ny, P, nx, P).sum((1, 3))  # noqa: E731
    area, nrel, nmatch = blk(mask), blk(rel_px), blk(match_px)
    present = (area >= 0.2 * P * P) & (nrel >= REL_FRAC * np.maximum(area, 1))
    near = blk((d_ph <= tol) & mask) / np.maximum(area, 1)              # доля площади участка рядом с кромкой фото — «случайные попадания»
    raw = nmatch / np.maximum(nrel, 1)
    agree = np.where(nrel > 0, (raw - near) / np.maximum(1.0 - near, 1e-3), 1.0)
    ok = np.where(present, agree >= AGREE_MIN, True)
    gate = np.kron(ok.astype(np.float32), np.ones((P, P), np.float32))[:H, :W]
    gate = np.clip(smooth(gate, GATE_SMOOTH_FRAC * width), 0, 1)
    gate_hard = np.kron(ok.astype(np.float32), np.ones((P, P), np.float32))[:H, :W] > 0.5
    valid = area >= 0.2 * P * P
    st = {'patch_px': P, 'tol_px': round(tol, 2), 'patches_with_mask': int(valid.sum()), 'patches_with_relief': int((present & valid).sum()),
          'patches_refused': int((present & ~ok & valid).sum()), 'patches_accepted_relief': int((present & ok & valid).sum()),
          'mask_share_refused': round(float((~gate_hard & mask).sum() / max(mask.sum(), 1)), 4),
          'relief_edge_px_share': round(float(rel_px.sum() / max(mask.sum(), 1)), 4),
          'relief_edges_matched_share': round(float(match_px.sum() / max(rel_px.sum(), 1)), 4)}
    return gate, st


def long_edges(e: np.ndarray, min_len: float) -> np.ndarray:
    """Оставляет связные кромки длиннее `min_len` px (по числу пикселей компоненты): рябь текстуры (крапины, шум) — короткие обрывки, стыки, швы и контуры узора — длинные."""
    import cv2
    if min_len <= 0 or not e.any():
        return e
    n, lab, stats, _ = cv2.connectedComponentsWithStats(e.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= min_len
    return keep[lab]


def _agree(ea: np.ndarray, eb: np.ndarray, mask: np.ndarray, tol: float) -> tuple:
    from scipy.ndimage import distance_transform_edt
    out = []
    for e1, e2 in ((ea, eb), (eb, ea)):
        near = distance_transform_edt(~e2) <= tol
        chance = float((near & mask).sum() / max(mask.sum(), 1))
        raw = float((e1 & near).sum() / max(e1.sum(), 1))
        out.append((raw - chance) / max(1.0 - chance, 1e-3))
    return out


def edge_agreement(L_a: np.ndarray, L_b: np.ndarray, mask: np.ndarray, width: float, min_len_frac: float = 0.0) -> dict:
    """Совпадение кромок двух кадров (a — фото, b — рендер базы) внутри маски, с поправкой на случайные попадания: для каждой стороны доля её кромок, рядом с которыми (≤ `TOL_FRAC`·ширина) есть
    кромка другой, минус доля площади «рядом с кромкой другой» (chance), делённая на (1 − chance). Итог — среднее двух сторон (симметрично: плотные кромки одной стороны не дают «совпадения сами»).
    `min_len_frac` > 0 (T-112): те же расчёты ещё и по длинным кромкам (компоненты не короче доли ширины) — в `agree` идёт он, прежнее число — `agree_raw`: рябь текстуры базы (крапины)
    даёт «лишние» кромки и занижает совпадение, хотя стыки и контуры лежат ровно."""
    ea, eb = photo_edges(L_a, mask, width), photo_edges(L_b, mask, width)
    tol = max(2.0, TOL_FRAC * width)
    raw = _agree(ea, eb, mask, tol)
    res = {'agree': round(float(np.mean(raw)), 4), 'photo_to_base': round(raw[0], 4), 'base_to_photo': round(raw[1], 4), 'tol_px': round(tol, 2)}
    if min_len_frac > 0:
        ml = min_len_frac * width
        lg = _agree(long_edges(ea, ml), long_edges(eb, ml), mask, tol)
        res.update({'agree_raw': res['agree'], 'agree': round(float(np.mean(lg)), 4), 'photo_to_base': round(lg[0], 4), 'base_to_photo': round(lg[1], 4), 'min_len_px': round(ml, 1)})
    return res


def _ecc_features(L: np.ndarray, mask: np.ndarray, width: float) -> np.ndarray:
    """Признак для ECC: модуль градиента L* без низких частот, сглаженный; вне маски 0; нормирован по 99-му процентилю."""
    import cv2
    hf = L - masked_blur(L, mask, LIGHT_FRAC * width)
    h = smooth(hf, max(1.0, 0.002 * width))
    g = np.hypot(cv2.Sobel(h, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(h, cv2.CV_32F, 0, 1, ksize=3)) * mask
    return (g / max(float(np.percentile(g[mask], 99)) if mask.any() else 1.0, 1e-6)).astype(np.float32)


def register_to_base(L_ph: np.ndarray, L_base: np.ndarray, mask_base: np.ndarray, mask_ph: np.ndarray, width: float, levels: int = 3, iters: int = 200) -> tuple[np.ndarray, dict]:
    """Уточнение регистрации фото → рендер базы (mv12 на той же форме): ECC (cv2.findTransformECC) по признакам кромок внутри маски фасада, от тождества (фото уже в кадре по регистрации А0).
    Сначала аффинная модель по пирамиде (грубо → точно), затем гомография на двух верхних уровнях. Возвращает H (3×3, такую, что cv2.warpPerspective(фото, H, …, WARP_INVERSE_MAP) кладёт фото на базу)
    и статистику: до/после совпадение кромок, сходимость каждого шага. Не сошлось/хуже — тождество."""
    import cv2
    er = max(3, int(round(0.01 * width)))
    k = np.ones((2 * er + 1, 2 * er + 1), np.uint8)
    mb = cv2.erode(mask_base.astype(np.uint8), k) > 0
    mp = cv2.erode(mask_ph.astype(np.uint8), k) > 0
    tmpl, inp = _ecc_features(L_base, mb, width), _ecc_features(L_ph, mp, width)
    H, W = tmpl.shape
    st = {'steps': []}
    Hm = np.eye(3, dtype=np.float64)

    def at(level):
        sc = 1.0 / (2 ** level)
        return sc, (cv2.resize(tmpl, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA), cv2.resize(inp, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA),
                    (cv2.resize(mb.astype(np.uint8), None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST) > 0))
    crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, iters, 1e-6)
    for motion, name, lv_list in ((cv2.MOTION_AFFINE, 'affine', list(range(levels - 1, -1, -1))), (cv2.MOTION_HOMOGRAPHY, 'homography', [1, 0])):
        for lv in lv_list:
            sc, (t, i, m) = at(lv)
            S = np.diag([sc, sc, 1.0])
            Hs = S @ Hm @ np.linalg.inv(S)
            wm = Hs[:2].astype(np.float32) if motion == cv2.MOTION_AFFINE else Hs.astype(np.float32)
            try:
                cc, wm = cv2.findTransformECC(t, i, wm, motion, crit, m.astype(np.uint8), 5)
            except cv2.error as e:
                st['steps'].append({'model': name, 'level': lv, 'error': str(e)[:120]})
                continue
            Hs = np.vstack([wm, [0, 0, 1]]) if motion == cv2.MOTION_AFFINE else wm.astype(np.float64)
            Hm = np.linalg.inv(S) @ Hs @ S
            st['steps'].append({'model': name, 'level': lv, 'cc': round(float(cc), 4)})
    return Hm, st


def flow_refine(L_ph: np.ndarray, L_base: np.ndarray, mask_base: np.ndarray, mask_ph: np.ndarray, width: float) -> np.ndarray:
    """Нежёсткая подгонка после ECC (T-112): гладкий плотный поток (Farneback) между признаками кромок фото и рендера базы. Нужна, когда геометрия базы (MV) лишь похожа на предмет с фото:
    стыки и контуры узора смещены на единицы процентов ширины, одной гомографией не лечится. Поток ограничен `FLOW_MAX_FRAC`·ширина и сильно сглажен (`FLOW_SMOOTH_FRAC`), чтобы не гнуть прямые.
    Возвращает поток (H, W, 2): кадр(x) = фото(x + поток(x)) — для `cv2.remap`."""
    import cv2
    er = max(3, int(round(0.01 * width)))
    k = np.ones((2 * er + 1, 2 * er + 1), np.uint8)
    mb, mp = cv2.erode(mask_base.astype(np.uint8), k) > 0, cv2.erode(mask_ph.astype(np.uint8), k) > 0
    sg = 0.004 * width
    ft = cv2.GaussianBlur(_ecc_features(L_base, mb, width), (0, 0), sg)
    fi = cv2.GaussianBlur(_ecc_features(L_ph, mp, width), (0, 0), sg)
    t8, i8 = np.clip(ft * 255, 0, 255).astype(np.uint8), np.clip(fi * 255, 0, 255).astype(np.uint8)
    flow = cv2.calcOpticalFlowFarneback(t8, i8, None, 0.5, 4, int(FLOW_WIN_FRAC * width) | 1, 5, 7, 1.5, 0)
    mag = np.hypot(flow[..., 0], flow[..., 1])
    flow *= np.minimum(1.0, FLOW_MAX_FRAC * width / np.maximum(mag, 1e-6))[..., None]
    return cv2.GaussianBlur(flow, (0, 0), FLOW_SMOOTH_FRAC * width).astype(np.float32)


def apply_flow(img: np.ndarray, flow: np.ndarray, interp=None) -> np.ndarray:
    import cv2
    h, w = flow.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    return cv2.remap(img, gx + flow[..., 0], gy + flow[..., 1], cv2.INTER_LINEAR if interp is None else interp, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def warp_by(H: np.ndarray, img: np.ndarray, size: tuple[int, int], interp=None) -> np.ndarray:
    import cv2
    return cv2.warpPerspective(img, H, size, flags=(cv2.INTER_LINEAR if interp is None else interp) | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_CONSTANT, borderValue=0)


def color_gate(ph: np.ndarray, r_in: np.ndarray, mask: np.ndarray, width: float) -> tuple[np.ndarray, dict]:
    """Попиксельный гейт «тот же материал»: расхождение a*b* между фото и рендером базы (оба слегка сглажены), за вычетом общего (медианного) сдвига оттенка — глобальную разницу правит шаг 3.
    Остаточное расхождение больше `COLOR_T1` = фото другого материала в этом месте (узор сдвинут: серое поверх дерева и наоборот) → вес 0; меньше `COLOR_T0` → 1; между — плавно.
    Узор фото и базы без сдвига — гейт не срабатывает; общее правило, без геометрии и без ID."""
    lp = PM.rgb_to_lab(ph).astype(np.float32)[..., 1:]
    lb = PM.rgb_to_lab(r_in).astype(np.float32)[..., 1:]
    s = max(1.0, 0.002 * width)
    d = np.stack([smooth(lp[..., c], s) - smooth(lb[..., c], s) for c in range(2)], -1)
    med = np.array([np.median(d[..., c][mask]) for c in range(2)]) if mask.any() else np.zeros(2)
    e = np.hypot(d[..., 0] - med[0], d[..., 1] - med[1])
    t = np.clip((e - COLOR_T0) / (COLOR_T1 - COLOR_T0), 0, 1)
    g = 1.0 - t * t * (3 - 2 * t)
    g = np.where(mask, g, 1.0).astype(np.float32)
    return g, {'median_shift_ab': [round(float(v), 2) for v in med], 'mask_share_refused': round(float(((g < 0.5) & mask).sum() / max(mask.sum(), 1)), 4)}


def surface_fade(ok: np.ndarray, cos: np.ndarray, width: float) -> np.ndarray:
    """Растушёвка к границе зоны «можно класть»: расстояние в кадре среди видимых пикселей × локальный множитель 1/cos (длина вдоль поверхности), от 0 на границе до 1 на `FADE_FRAC`·ширина."""
    from scipy.ndimage import distance_transform_edt
    R = max(2.0, FADE_FRAC * width)
    d = distance_transform_edt(ok)
    stretch = smooth(1.0 / np.maximum(cos, 0.3), R)
    t = np.clip(d * stretch / R, 0, 1)
    return (t * t * (3 - 2 * t)).astype(np.float32)


def light_layer(ph: np.ndarray, r_in: np.ndarray, mask: np.ndarray, width: float, mode: str) -> np.ndarray:
    """Цвет «слоя фото» в кадре (uint8): lp — L* = мелкие детали фото + широкие частоты рендера входа, a*b* фото; raw — фото как есть."""
    if mode == 'raw':
        return ph
    lab_p, lab_r = PM.rgb_to_lab(ph).astype(np.float32), PM.rgb_to_lab(r_in).astype(np.float32)
    s = LIGHT_FRAC * width
    low_p, low_r = masked_blur(lab_p[..., 0], mask, s), masked_blur(lab_r[..., 0], mask, s)
    lab = lab_p.copy()
    lab[..., 0] = np.clip(lab_p[..., 0] - low_p + low_r, 0, 100)
    rgb, _ = A.lab_to_rgb(lab)
    return np.round(rgb).astype(np.uint8)


def texels_per_pixel(uv: np.ndarray, size: int, mask: np.ndarray) -> float:
    """Медианное число текселей карты на один пиксель кадра (якобиан развёртки uv(x, y)·size) внутри маски; ≥ 1."""
    ux, uy = np.gradient(uv[..., 0].astype(np.float64) * size, axis=(1, 0))
    vx, vy = np.gradient(uv[..., 1].astype(np.float64) * size, axis=(1, 0))
    det = np.abs(ux * vy - uy * vx)
    ok = mask & np.isfinite(det) & (det > 1e-6)
    return float(max(1.0, np.median(det[ok]))) if ok.any() else 1.0


def splat(uv: np.ndarray, size: int, mask: np.ndarray, color: np.ndarray, conf: np.ndarray) -> dict:
    """Пиксели кадра → карта: билинейное рассыпание на 4 тексела; накопления: масса A, уверенность·масса Wm, цвет·уверенность·масса C; сглажены (SPLAT_SIGMA)."""
    ys, xs = np.nonzero(mask & (conf > 0))
    u = uv[ys, xs, 0].astype(np.float64) * size - 0.5
    v = uv[ys, xs, 1].astype(np.float64) * size - 0.5
    x0, y0 = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
    fx, fy = u - x0, v - y0
    cf = conf[ys, xs].astype(np.float64)
    col = color[ys, xs].astype(np.float64)
    A_, Wm, C = (np.zeros(size * size, np.float32) for _ in range(3))
    Cc = np.zeros((size * size, 3), np.float32)
    for dx, dy, w in ((0, 0, (1 - fx) * (1 - fy)), (1, 0, fx * (1 - fy)), (0, 1, (1 - fx) * fy), (1, 1, fx * fy)):
        xi, yi = np.clip(x0 + dx, 0, size - 1), np.clip(y0 + dy, 0, size - 1)
        idx = yi * size + xi
        A_ += np.bincount(idx, weights=w, minlength=size * size).astype(np.float32)
        Wm += np.bincount(idx, weights=w * cf, minlength=size * size).astype(np.float32)
        for c in range(3):
            Cc[:, c] += np.bincount(idx, weights=w * cf * col[:, c], minlength=size * size).astype(np.float32)
    A_, Wm = A_.reshape(size, size), Wm.reshape(size, size)
    Cc = Cc.reshape(size, size, 3)
    r = texels_per_pixel(uv, size, mask)
    sg = max(SPLAT_SIGMA, SPLAT_SIGMA_K * float(np.sqrt(r)))           # карта плотнее кадра: масса пикселя (1) размазывается на r текселей, σ растёт вместе с √r
    Ab, Wb = smooth(A_, sg), smooth(Wm, sg)
    Cb = np.stack([smooth(Cc[..., c], sg) for c in range(3)], -1)
    ref = float(np.median(Ab[Ab > 0])) if (Ab > 0).any() else 1.0       # типичная плотность массы там, куда легли пиксели кадра
    return {'A': Ab, 'W': Wb, 'C': Cb, 'ref': ref, 'texels_per_pixel': r, 'sigma': sg}


def photo_weight(sp: dict) -> tuple[np.ndarray, np.ndarray]:
    """Вес фото на тексель карты (0…1) и маска покрытия: то, чем фото-слой перекрывает базу в `apply_photo` (0 — тексель остаётся базой, 1 — целиком из фото)."""
    cover = sp['A'] >= COVER_MIN * sp.get('ref', 1.0)                  # покрытие — относительно типичной плотности (на карте плотнее кадра абсолютный порог не набирается)
    w = np.where(cover, np.clip(sp['W'] / np.maximum(sp['A'], 1e-6), 0, 1), 0.0)
    return np.where(w < CONF_MIN, 0.0, w).astype(np.float32), cover


def apply_photo(tex: np.ndarray, sp: dict) -> tuple[np.ndarray, dict]:
    w, cover = photo_weight(sp)
    colour = sp['C'] / np.maximum(sp['W'], 1e-6)[..., None]
    w = w[..., None]
    out = np.clip(np.round(tex.astype(np.float32) * (1 - w) + colour * w), 0, 255).astype(np.uint8)
    return out, {'texels_covered': int(cover.sum()), 'texels_changed_share': round(float((w[..., 0] > 0.05).mean()), 5), 'mean_weight_on_covered': round(float(w[..., 0][cover].mean()) if cover.any() else 0.0, 4)}


def run(glb: str, stages: str, photo_path: str, out_dir: str, stem: str, light: str = 'lp', out_size: int = 0, register: str = 'ecc', flow: bool = False) -> dict:
    import cv2
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    sl = json.load(open(os.path.join(os.path.dirname(stages.rstrip('/')), 'stage_loss.json'), encoding='utf-8'))
    P = np.array(sl['registration']['P'], np.float64).reshape(3, 3)
    rd = os.path.join(stages, 'render_view0')
    S = np.asarray(Image.open(os.path.join(rd, 'mask.png')).convert('L')) > 127
    aoi = np.asarray(Image.open(os.path.join(rd, 'aoi_cos16.png'))).astype(np.float32) / 65535.0
    uvd = np.load(os.path.join(rd, 'uv.npz'))
    uv = uvd['uv']
    photo = SL.read_rgba(photo_path)
    fh, fw = S.shape
    A_fr = SL.warp_inv((photo[..., 3] > 127).astype(np.float32), P, (fw, fh)) > 0.5
    cm, width = SL.common_mask(S, A_fr, aoi)
    ph = np.clip(SL.warp_inv(photo[..., :3], P, (fw, fh), cv2.INTER_LINEAR), 0, 255).astype(np.uint8)
    j0, b0 = A.read_glb(glb)
    tex = T.read_texture(j0, b0)
    tex_in_size = tex.shape[0]
    if out_size and out_size != tex.shape[0]:                        # итог крупнее входа (mv12: карта 2048 → 4096): база растягивается, фото-слой кладётся уже в новую сетку
        tex = cv2.resize(tex, (out_size, out_size), interpolation=cv2.INTER_CUBIC if out_size > tex.shape[0] else cv2.INTER_AREA)
    size = tex.shape[0]
    r_in = A.render_view0(tex, uvd)

    wa = angle_weight(aoi)
    L_ph = PM.rgb_to_lab(ph)[..., 0].astype(np.float32)
    L_base = PM.rgb_to_lab(r_in)[..., 0].astype(np.float32)
    reg = {'mode': register}
    lay_photo = True
    if register == 'ecc':
        reg['before'] = edge_agreement(L_ph, L_base, S & A_fr, width, EDGE_MIN_LEN)
        Hm, rst = register_to_base(L_ph, L_base, S, A_fr, width)
        ph_r = warp_by(Hm, ph, (fw, fh))
        A_r = warp_by(Hm, A_fr.astype(np.uint8), (fw, fh), cv2.INTER_NEAREST) > 0
        L_r = PM.rgb_to_lab(ph_r)[..., 0].astype(np.float32)
        reg['after'] = edge_agreement(L_r, L_base, S & A_r, width, EDGE_MIN_LEN)
        reg['H'] = [round(float(v), 6) for v in Hm.ravel()]
        reg['ecc'] = rst['steps']
        if reg['after']['agree'] > reg['before']['agree']:
            ph, A_fr, L_ph = ph_r, A_r, L_r
            cm, width = SL.common_mask(S, A_fr, aoi)
            reg['used'] = True
        else:
            reg['used'] = False
        cur = reg['after' if reg['used'] else 'before']
        if flow:                                                           # нежёсткая подгонка поверх ECC: берём, только если кромки совпали лучше
            fl = flow_refine(L_ph, L_base, S, A_fr, width)
            ph_f, A_f = apply_flow(ph, fl), apply_flow(A_fr.astype(np.uint8), fl, cv2.INTER_NEAREST) > 0
            L_f = PM.rgb_to_lab(ph_f)[..., 0].astype(np.float32)
            reg['after_flow'] = edge_agreement(L_f, L_base, S & A_f, width, EDGE_MIN_LEN)
            reg['flow_max_px'] = round(float(np.hypot(fl[..., 0], fl[..., 1])[S & A_f].max()), 1)
            reg['flow_used'] = bool(reg['after_flow']['agree'] > cur['agree'])
            if reg['flow_used']:
                np.savez_compressed(os.path.join(out_dir, f'{stem}.reg-flow.npz'), flow=fl.astype(np.float16))
                reg['flow_file'] = f'{stem}.reg-flow.npz'
                ph, A_fr, L_ph = ph_f, A_f, L_f
                cm, width = SL.common_mask(S, A_fr, aoi)
                cur = reg['after_flow']
                reg['used'] = True
        lay_photo = cur['agree'] >= REG_MIN
        reg['photo_laid'] = bool(lay_photo)
    er = max(3, int(round(EDGE_ERODE_FRAC * width)))
    inner = cv2.erode((S & A_fr).astype(np.uint8), np.ones((2 * er + 1, 2 * er + 1), np.uint8)) > 0
    import tex_coverage as TC
    geo = TC.load_geoms(glb)
    if len(geo) != 1:
        raise ValueError('ожидалась одна геометрия')
    dz = os.path.join(rd, 'depth.npz')
    if os.path.exists(dz):                                                      # перспективный кадр (pose_fit.py): глубина и длина пикселя посчитаны камерой, регрессия плоскости годится только для ортографики
        dd = np.load(dz)
        depth, px_len = dd['depth'].astype(np.float32), float(dd['px_len'])
    else:
        pos, valid = texel_positions(geo[0]['V'], geo[0]['F'], geo[0]['UV'], 2048)
        depth, px_len = frame_depth(pos, valid, uv, S)
    rel = depth_edges(depth, inner, px_len)
    rel_t = relief_threshold(rel, inner)
    ph_edge = photo_edges(L_ph, inner, width)
    gate, gst = gate_map(rel, ph_edge, inner, width, rel_t)
    gst['rel_threshold'] = round(rel_t, 4)
    base_edge = photo_edges(L_base, inner, width).astype(np.float32)           # страховка «фото ≠ база»: кромки рендера базы (MV на той же форме) должны найти кромки фото рядом
    gate_b, gbst = gate_map(base_edge, ph_edge, inner, width, BASE_EDGE_T)
    gate = gate * gate_b
    gst['base_gate'] = gbst
    gate_c, gcst = color_gate(ph, r_in, inner, width)
    gate = gate * gate_c
    gst['color_gate'] = gcst
    if not lay_photo:
        gate = gate * 0.0                                                      # регистрация не сошлась: фото на этот товар не кладём целиком (только MV)
    zone = inner & (wa * gate > 0.5)
    fade = surface_fade(zone, aoi, width)
    conf = (wa * gate * fade * inner).astype(np.float32)
    conf[conf < CONF_MIN] = 0.0
    layer = light_layer(ph, r_in, inner, width, light)

    sp = splat(uv, size, inner, layer, conf)
    new, apinfo = apply_photo(tex, sp)
    wmap, _ = photo_weight(sp)
    Image.fromarray(np.round(wmap * 255).astype(np.uint8)).save(os.path.join(out_dir, f'{stem}.uvmap-confidence.png'))      # вес фото на тексель (карта той же сетки, что итог); читает uv_maps.py
    r_out = A.render_view0(new, uvd)

    jn, bn = A.swap_texture(j0, b0, A.png_bytes(new))
    p_out = os.path.join(out_dir, f'{stem}-photo.glb')
    A.write_glb(p_out, jn, bn)
    g = A.geometry_guard(*A.read_glb(glb), *A.read_glb(p_out))

    met = {}
    for name, img in (('in', r_in), ('photo', r_out)):
        met[name] = SL.stage_metrics(img, ph, cm, width, ncc=True)
        Image.fromarray(img).save(os.path.join(out_dir, f'{stem}.view0_{name}.png'))
    pick = lambda m: {'hf_1%': m['hf']['1%']['ratio'], 'sigmaL': m['sigmaL']['ratio'], 'dE00_lf': m['dE00_lf_median'], 'ncc': (m.get('ncc') or {}).get('median'), 'ncc_p10': (m.get('ncc') or {}).get('p10')}  # noqa: E731
    table = {k: pick(v) for k, v in met.items()}
    Image.fromarray((np.clip(conf, 0, 1) * 255).astype(np.uint8)).save(os.path.join(out_dir, f'{stem}.photo-conf.png'))
    gv = np.zeros(S.shape + (3,), np.uint8)
    gv[..., 1] = (np.clip(gate, 0, 1) * 160).astype(np.uint8)
    gv[..., 0] = (np.clip(rel / (3 * rel_t), 0, 1) * 255).astype(np.uint8)
    gv[ph_edge] = (60, 60, 255)
    gv[~inner] = 0
    Image.fromarray(gv).save(os.path.join(out_dir, f'{stem}.photo-gate.png'))
    Image.fromarray(layer).save(os.path.join(out_dir, f'{stem}.photo-layer.png'))
    cm_n = max(int(cm.sum()), 1)
    res = {'glb_in': glb, 'stem': stem, 'light': light, 'tex_size_in': tex_in_size, 'tex_size': list(tex.shape[:2]), 'width_px': round(float(width), 1),
           'params': {'COS_LO': COS_LO, 'COS_HI': COS_HI, 'FADE_FRAC': FADE_FRAC, 'LIGHT_FRAC': LIGHT_FRAC, 'PATCH_FRAC': PATCH_FRAC, 'TOL_FRAC': TOL_FRAC, 'REL_T': REL_T, 'REL_FRAC': REL_FRAC,
                      'AGREE_MIN': AGREE_MIN, 'PHOTO_EDGE_PCT': PHOTO_EDGE_PCT},
           'gate': gst, 'frame': {'mask_px': cm_n, 'conf_gt_0.5_share': round(float(((conf > 0.5) & cm).sum() / cm_n), 4), 'conf_gt_0_share': round(float(((conf > 0) & cm).sum() / cm_n), 4)},
           'registration_refine': reg, 'apply': apinfo, 'table': table, 'guard': g, 'files': {'photo': p_out, 'photo_mb': round(os.path.getsize(p_out) / 2 ** 20, 2)}, 'registration': sl['registration']}
    json.dump(res, open(os.path.join(out_dir, f'{stem}.photo.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb')
    ap.add_argument('--stages')
    ap.add_argument('--photo')
    ap.add_argument('--out-dir')
    ap.add_argument('--stem')
    ap.add_argument('--light', choices=('lp', 'raw'), default='lp')
    ap.add_argument('--out-size', type=int, default=0, help='размер карты результата (0 — как у входа)')
    ap.add_argument('--register', choices=('ecc', 'none'), default='ecc', help='уточнение регистрации фото → база (ECC) перед проекцией')
    ap.add_argument('--flow', action='store_true', help='нежёсткая подгонка (гладкий поток) поверх ECC; берётся, если кромки совпали лучше')
    ap.add_argument('--rel-t', type=float, default=None, help='порог поворота нормали (REL_T)')
    ap.add_argument('--rel-frac', type=float, default=None, help='доля рельефных пикселей в участке (REL_FRAC)')
    ap.add_argument('--agree-min', type=float, default=None, help='минимум совпадения кромок (AGREE_MIN)')
    a = ap.parse_args()
    g = globals()
    for k, v in (('REL_T', a.rel_t), ('REL_FRAC', a.rel_frac), ('AGREE_MIN', a.agree_min)):
        if v is not None:
            g[k] = v
    if not all([a.glb, a.stages, a.photo, a.out_dir, a.stem]):
        ap.error('нужны --glb --stages --photo --out-dir --stem')
    r = run(a.glb, a.stages, a.photo, a.out_dir, a.stem, a.light, a.out_size, a.register, a.flow)
    print(json.dumps({k: r[k] for k in ('stem', 'light', 'width_px', 'registration_refine', 'gate', 'frame', 'apply', 'table', 'guard')}, ensure_ascii=False, indent=1))
    return 0 if r['guard']['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())

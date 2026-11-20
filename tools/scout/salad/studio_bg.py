"""«Известный студийный фон» (T-20261119-104/5, Ч.1): у фото с ровным белым краем кадра цвет фона известен — по нему чистим край вырезки.

Беда (владелец 20.11, №22 торшер): у тонких трубок по кромке остаются белые «бусины» — пиксели чистого фона внутри маски. Рождаются в
`components.close_edge_gaps` (закрытие щелей склеивает крупу фона), потом чистильщики видят грязь, но откатываются по своим потолкам.
Решение по ответу Codex (`.memory_bank/_intake/codex/2026-11-20-white-cut-answer.md`), три части, все без ID и ролей:
  A. Признак «ровный белый фон» — СТРОГИЙ, по кольцу 4 % кадра (`detect`): B = медиана кольца, min(B) ≥ 245, разброс каналов ≤ 5,
     процентили Δ∞ кольца p80/p90/p95 ≤ 6/10/18, ≥ 70 % периметра «как фон». Градиент/виньетка — пропуск (net_only), не гадаем.
     Порог адаптивный: t_core = clip(max(6, 3·MAD), 6, 10), t_soft = min(t_core + 10, 20).
  B. Rcore / Rsoft — заливка от рамки кадра по пикселям Δ∞ ≤ t_core / ≤ t_soft (`regions`): это точно фон, связанный с краем.
     • `subtract` — ПОСЛЕДНИЙ шаг после всех растущих: из маски убираются пиксели Rcore в полосе ≤ 2 px внутрь от кромки. Товар цвета фона
       (‖F−B‖∞ < 20) и снос > 3 % тела — не трогаем (причина — в info).
     • `soft_alpha` — аналитический мягкий край: α = min(α, clamp((I−B)·(F−B)/(‖F−B‖²+ε))) в полосе кромки; цвет там — F (ближайшее уверенное
       тело), без подмешанного белого. F ≈ B (< 20) — α сети не трогаем.
  C. Сторож `close_edge_gaps(rcore=…)`: добавки внутри Rcore запрещены; шаг откатывается целиком, если добавка > 1 % тела И > 20 % добавок в Rcore.
Тело правило НЕ добавляет (возврат потерянных светлых частей — Ч.2, отдельная задача). Выключатель: env `CUTOUT_STUDIO_BG=0`.
Не трогает `salad/preprocess._cut_chain` (меши)."""
import os

import numpy as np
from scipy import ndimage as ndi

RING = 0.04             # доля меньшей стороны — кольцо кадра, по которому судим о фоне
MIN_B = 245.0           # фон достаточно белый
SPREAD_MAX = 5.0        # разброс каналов цвета фона
P_LIMITS = (6.0, 10.0, 18.0)   # p80/p90/p95 отклонения кольца от B
PERIM_MIN = 0.70        # доля внешнего периметра «как фон»
BAND_CORE = 2           # вычитатель: ≤ 2 px внутрь от кромки
SUBTRACT_MAX_SHARE = 0.03   # снос больше 3 % тела — это белый товар, а не крупа: откат
F_MIN_DIST = 20.0       # ‖F−B‖∞ меньше — товар цвета фона, α сети не трогаем
CONF_DIST = 40.0        # пиксель дальше этого от B — уверенное тело (для тонких трубок, где «внутри» нет)
SOFT_MAX_SHARE = 0.03   # мягкий край снёс (α<0,5) больше 3 % тела — откат


def enabled() -> bool:
    return os.environ.get('CUTOUT_STUDIO_BG', '1') != '0'


def bg_distance(rgb, bg):
    return np.abs(rgb.astype(np.float32) - np.asarray(bg, np.float32)).max(axis=2)


def detect(rgb):
    """Строгий признак ровного белого фона. Возвращает (bg_rgb | None, stats); stats всегда с 'reason' при отказе и порогами при успехе."""
    h, w = rgb.shape[:2]
    r = max(3, int(round(min(h, w) * RING)))
    f = rgb.astype(np.float32)
    ring = np.concatenate([f[:r].reshape(-1, 3), f[-r:].reshape(-1, 3), f[r:-r, :r].reshape(-1, 3), f[r:-r, -r:].reshape(-1, 3)])
    B = np.median(ring, axis=0)
    d = np.abs(ring - B).max(axis=1)
    p80, p90, p95 = (float(np.percentile(d, q)) for q in (80, 90, 95))
    mad = float(np.median(np.abs(d - np.median(d))))
    t_core = float(np.clip(max(6.0, 3 * mad), 6.0, 10.0))
    t_soft = float(min(t_core + 10.0, 20.0))
    per = np.concatenate([f[0], f[-1], f[1:-1, 0], f[1:-1, -1]])
    perim = float((np.abs(per - B).max(axis=1) <= t_core).mean())
    spread = float(B.max() - B.min())
    st = {'bg': [round(float(v), 1) for v in B], 'spread': round(spread, 1), 'p80': round(p80, 1), 'p90': round(p90, 1), 'p95': round(p95, 1),
          'perim': round(perim, 3), 't_core': round(t_core, 1), 't_soft': round(t_soft, 1)}
    why = None
    if float(B.min()) < MIN_B:
        why = f'фон не белый (min {B.min():.0f} < {MIN_B:.0f})'
    elif spread > SPREAD_MAX:
        why = f'цветной фон (разброс каналов {spread:.0f})'
    elif p80 > P_LIMITS[0] or p90 > P_LIMITS[1] or p95 > P_LIMITS[2]:
        why = f'фон не ровный (p80/p90/p95 = {p80:.0f}/{p90:.0f}/{p95:.0f})'
    elif perim < PERIM_MIN:
        why = f'товар у рамки (фон лишь на {perim:.0%} периметра)'
    if why:
        st['reason'] = why
        return None, st
    return B, st


def reach_from_border(bgpix):
    """Пиксели «как фон», связанные (4-связность) с рамкой кадра."""
    lab, _ = ndi.label(bgpix)
    ids = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    return np.isin(lab, ids[ids > 0])


def regions(rgb, bg, t_core, t_soft):
    """(Rcore, Rsoft): заливка от рамки по Δ∞ ≤ t_core / ≤ t_soft."""
    d = bg_distance(rgb, bg)
    return reach_from_border(d <= t_core), reach_from_border(d <= t_soft)


def pollution(alpha, rcore, thr=0.5):
    """Сколько пикселей маски лежит на фоне, связанном с краем (Rcore) — «загрязнение» шага."""
    return int(((alpha > thr) & rcore).sum())


def subtract(alpha, rgb, bg, rcore, thr=0.5):
    """Убрать из маски пиксели Rcore в полосе ≤ BAND_CORE px внутрь от кромки. Возвращает (alpha2, info)."""
    mask = alpha > thr
    if not mask.any():
        return alpha, {}
    inner = ndi.binary_erosion(mask, iterations=3)
    pix = rgb[inner] if inner.any() else rgb[mask]
    F = np.median(pix.astype(np.float32), axis=0)
    if float(np.abs(F - np.asarray(bg, np.float32)).max()) < F_MIN_DIST:
        return alpha, {'subtract_skipped': 'товар цвета фона (‖F−B‖ < 20) — маску сети не трогаем'}
    depth = ndi.distance_transform_edt(mask)
    rm = mask & rcore & (depth <= BAND_CORE)
    n = int(rm.sum())
    if not n:
        return alpha, {'subtract_px': 0}
    if n > SUBTRACT_MAX_SHARE * mask.sum():
        return alpha, {'subtract_skipped': f'снести пришлось бы {n} px (> {int(SUBTRACT_MAX_SHARE * 100)} % тела) — белый товар, не трогаем'}
    out = alpha.copy()
    out[rm] = 0.0
    return out, {'subtract_px': n}


def soft_alpha(alpha, rgb, bg, rsoft, thr=0.5):
    """Аналитический мягкий край по известному фону. Возвращает (alpha2, rgb2, info). Только уменьшает α в полосе кромки."""
    mask = alpha > thr
    if not mask.any():
        return alpha, rgb, {}
    B = np.asarray(bg, np.float32)
    f = rgb.astype(np.float32)
    d = np.abs(f - B).max(axis=2)
    depth = ndi.distance_transform_edt(mask)
    # «уверенное тело» (откуда берём цвет F): глубже кромки или локальный максимум удаления от фона (для тонкой трубки, где «глубже» нет;
    # смешанные пиксели кромки по удалению от фона слабее соседнего чистого тела)
    peak = d >= ndi.maximum_filter(d, size=5) - 8.0
    conf = mask & ((depth > BAND_CORE + 1) | ((d >= CONF_DIST) & peak)) & ~rsoft
    # переходная полоса: пиксели маски у кромки, рядом (≤ 2 px) с фоном Rsoft — тени и прочее не «фон», их не трогаем
    band = mask & (depth <= BAND_CORE) & ~conf & ndi.binary_dilation(rsoft, iterations=BAND_CORE)
    if not band.any():
        return alpha, rgb, {'soft_px': 0}
    if not conf.any():
        return alpha, rgb, {'soft_skipped': 'нет уверенного тела для цвета F'}
    _, (iy, ix) = ndi.distance_transform_edt(~conf, return_indices=True)
    F = f[iy, ix]
    FB = F - B
    nrm2 = (FB * FB).sum(axis=2)
    ac = np.clip(((f - B) * FB).sum(axis=2) / (nrm2 + 1e-3), 0.0, 1.0)
    similar = np.abs(FB).max(axis=2) < F_MIN_DIST           # F ≈ B: объект цвета фона — α сети не трогаем
    act = band & ~similar & (ac < alpha)
    if not act.any():
        return alpha, rgb, {'soft_px': 0}
    new = np.where(act, ac, alpha)
    dropped = int((act & (ac < thr)).sum())
    if dropped > SOFT_MAX_SHARE * mask.sum():
        return alpha, rgb, {'soft_skipped': f'мягкий край снёс бы {dropped} px (> {int(SOFT_MAX_SHARE * 100)} % тела) — откат'}
    new[new < 0.04] = 0.0
    out_rgb = np.where(act[..., None] & (new[..., None] > 0), np.clip(F, 0, 255), f).astype(rgb.dtype)
    return new.astype(alpha.dtype), out_rgb, {'soft_px': int(act.sum()), 'soft_dropped_px': dropped}

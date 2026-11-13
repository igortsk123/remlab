"""ПОПРАВКА СВЕТЛОТЫ ВИДОВ СЕТИ ДО ЗАПЕКАНИЯ (план mesh-color-03, опыт 2 круга 2; T-20261112-49/3).

ЗАЧЕМ. Сеть видов Hunyuan3D-paint тянет крайние тона к середине: графит выходит серым, белое — сероватым, тёмное
дерево — светлым. Множитель атласа после запекания (А/А-L) двигает всё одной ручкой — владелец назвал это «заливкой»;
одна кривая по всему атласу (K0, круг 1) испортила дерево комода 634079, потому что тона атласа ≠ тонам фото. Здесь
поправка ставится РАНЬШЕ: на шесть видов альбедо, которые сеть выдала, до увеличения RealESRGAN и запекания в UV, и
не одна на весь товар, а ПО УЧАСТКАМ — у каждого крупного цветового участка фото своя монотонная кривая светлоты.

КАК.
  1. Соответствие «фронтальный вид ↔ фото»: силуэты совмещаются по рамкам (сеть видит фото, сжатое в 512×512 без
     сохранения пропорций, вид — ортокамера по нормализованному мешу, поэтому масштаб по x и y — свой). Края силуэтов
     отрезаются (эрозия), совпадение силуэтов (IoU) ниже порога — поправки нет: фото снято не спереди или форма другая.
  2. Участки: k-средних (до 3) по Lab ФОТО на парах пикселей; мелкие (< MIN_SHARE) и близкие (ΔE < MERGE_DE) сливаются.
  3. Кривая участка: квантили L вида → квантили L фото (2…98 %), монотонная, наклон в [SLOPE_MIN, SLOPE_MAX], сдвиг не
     больше MAX_DL. Квантили, а не попиксельная регрессия: совмещение силуэтов приблизительное, порядок тонов — нет.
  4. Применение ко ВСЕМ видам: пиксель вида относится к участкам мягко — по близости его Lab к центру участка в
     цветах ВИДА; далёкий от всех участков (материал, которого на фото нет: задник, дно) остаётся почти как есть.
     Меняется только L; a и b не трогаются (круг 1: общий сдвиг ab посинил белый корпус 007531).

Только numpy и PIL (есть в образе) — модуль проверяется на CPU по сохранённым видам О0 (`dbg-mv-albedo-*`).
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

K_MAX = 3
MIN_SHARE = 0.10          # участок меньше 10 % пар сливается с ближайшим
MERGE_DE = 10.0           # центры фото ближе — один участок
MIN_PAIRS = 1500          # на вид 512×512; на другом размере — пропорционально площади
MIN_IOU = 0.60
MAX_DL = 40.0             # графит 936236: вид светлее фото на 38 L — при 30 недобор
SLOPE_MIN, SLOPE_MAX = 0.4, 2.5
QS = (2, 10, 25, 50, 75, 90, 98)
L_WEIGHT = 0.7            # вес L в расстоянии до центра участка (L вида и есть то, что врёт)
SIGMA_MIN, SIGMA_MAX = 8.0, 16.0
# Вес участка — «плоский» exp(-(d/σ)^4/2): внутри участка почти 1, за его краем быстро 0; поправка «как есть» весит как
# участок на расстоянии FAR_DE. С гауссом (первый вариант) дерево боковин 634079 (нет на фронте) брало кривую серо-голубого
# фасада и темнело — тот же провал, что K0 в круге 1.
FAR_DE = 22.0
ERODE_FRAC = 0.03
AB_MAX = 15.0             # цветность пар фото и вида участка расходится больше — пары с чужого материала, без поправки
# ОПОРА УЧАСТКА (T-20261112-49/4, утечка). Сеть видов рисует узкие полосы цвета соседнего участка там, где его нет: у
# 634079 бледно-серая полоса по дереву боковины (вид 270°) и у левого края фронта. По цвету это «фасад», и кривая фасада
# (−11 L) делала из бледной полосы тёмную — на листе ракурсов круга 2 тёмная полоса сбоку, худшая область фронта 6 → 26.
# Поэтому участок правит только там, где он лежит ПЯТНОМ: морфологическое открытие маски участка окном SUPPORT_FRAC от
# размера силуэта вида убирает полосы и крапины уже окна; дыры фактуры (щели жалюзи, сучки, волокна) до этого заливает
# закрытие тем же окном. Края настоящих панелей открытие не сдвигает (в отличие от размытия — без светлой каймы по краю).
# Стенд на CPU, 12 мешей О0 (стенд утечки в `~/remlab-logs/t49-1112/tools/`, итог `leak-2245`): 0,06 убирает полосу 634079
# (боковые виды 3,3 % → 0 % тронутых); закрытие в четверть окна давало пятна на дереве 007531 — поэтому полное.
# Цена: мелкие детали уже окна (ручки 570973) остаются без поправки.
SUPPORT_FRAC = 0.06
CLOSE_K = 1.0             # окно закрытия (заливка дыр фактуры) — доля окна открытия
CORE_W = 0.5              # пиксель «в участке», если его вес участка выше
# Участки — по цветам ВИДА (а не фото): ими же пиксели всех шести видов относятся к участкам. По фото (вариант
# 'photo') проверено на 12 мешах О0 на CPU: где сеть слила два тона фото в один, мягкая разметка смешивала кривые
# и 007531/721606 становились хуже (`~/remlab-logs/t49-1112/1553-cal`).
REGION_SPACE = 'view'


# ---------- цвет ----------
def _srgb_to_lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def _lin_to_srgb(c):
    c = np.clip(c, 0.0, 1.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * np.power(c, 1 / 2.4) - 0.055)


_M = np.array([[0.4124564, 0.3575761, 0.1804375],
               [0.2126729, 0.7151522, 0.0721750],
               [0.0193339, 0.1191920, 0.9503041]])
_MI = np.linalg.inv(_M)
_WP = np.array([0.95047, 1.0, 1.08883])


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """uint8/float 0..255 (…, 3) → Lab (…, 3)."""
    lin = _srgb_to_lin(np.asarray(rgb, dtype=np.float64) / 255.0)
    xyz = lin @ _M.T / _WP
    e = 216 / 24389
    f = np.where(xyz > e, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def lab_to_rgb(lab: np.ndarray) -> np.ndarray:
    """Lab → uint8 0..255."""
    fy = (lab[..., 0] + 16) / 116
    fx, fz = fy + lab[..., 1] / 500, fy - lab[..., 2] / 200
    e = 6 / 29
    f = np.stack([fx, fy, fz], -1)
    xyz = np.where(f > e, f ** 3, 3 * e * e * (f - 4 / 29)) * _WP
    rgb = _lin_to_srgb(xyz @ _MI.T)
    return np.clip(np.round(rgb * 255), 0, 255).astype(np.uint8)


# ---------- маски и совмещение ----------
def mask_from_normal(cond: Image.Image, size: int) -> np.ndarray:
    """Карта нормалей рендера: фон белый (255,255,255), у единичной нормали такого цвета не бывает."""
    a = np.asarray(cond.convert('RGB').resize((size, size), Image.NEAREST)).astype(np.int16)
    return ~np.all(a >= 250, axis=-1)


def _bbox(m: np.ndarray):
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


def _erode(m: np.ndarray, r: int) -> np.ndarray:
    if r <= 0:
        return m
    im = Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(2 * r + 1))
    return np.asarray(im) > 127


def pairs(photo_rgb: np.ndarray, photo_alpha: np.ndarray, view_rgb: np.ndarray, view_mask: np.ndarray):
    """Пары пикселей «вид ↔ фото» внутри обоих силуэтов. Возвращает (Lab вида, Lab фото, info)."""
    bp, bv = _bbox(photo_alpha > 128), _bbox(view_mask)
    if bp is None or bv is None:
        return None, None, {'skip': 'пустой силуэт'}
    h, w = view_mask.shape
    ys, xs = np.mgrid[0:h, 0:w]
    sx = (bp[2] - bp[0]) / max(bv[2] - bv[0], 1)
    sy = (bp[3] - bp[1]) / max(bv[3] - bv[1], 1)
    px = np.clip(np.round(bp[0] + (xs - bv[0] + 0.5) * sx - 0.5).astype(int), 0, photo_alpha.shape[1] - 1)
    py = np.clip(np.round(bp[1] + (ys - bv[1] + 0.5) * sy - 0.5).astype(int), 0, photo_alpha.shape[0] - 1)
    pm = photo_alpha[py, px] > 128
    inter, union = np.logical_and(pm, view_mask).sum(), np.logical_or(pm, view_mask).sum()
    iou = float(inter / max(union, 1))
    r = max(2, int(round(ERODE_FRAC * max(bv[2] - bv[0], bv[3] - bv[1]))))
    pe = _erode(photo_alpha > 250, max(1, int(round(r * max(sx, sy)))))
    sel = _erode(view_mask, r) & pe[py, px]
    info = {'iou': round(iou, 3), 'pairs': int(sel.sum()), 'erode_px': r}
    if iou < MIN_IOU:
        info['skip'] = f'IoU {iou:.2f} < {MIN_IOU}'
        return None, None, info
    need = max(20, int(MIN_PAIRS * h * w / 512 ** 2))
    if sel.sum() < need:
        info['skip'] = f'пар {int(sel.sum())} < {need}'
        return None, None, info
    return rgb_to_lab(view_rgb[sel]), rgb_to_lab(photo_rgb[py[sel], px[sel]]), info


# ---------- участки и кривые ----------
def _kmeans(x: np.ndarray, k: int, it: int = 20) -> np.ndarray:
    """Детерминированный k-средних: старт — квантили L (без случайности: один и тот же вид → один и тот же ответ)."""
    order = np.argsort(x[:, 0])
    c = np.stack([x[order[int((i + 0.5) / k * (len(x) - 1))]] for i in range(k)])
    for _ in range(it):
        lab = np.argmin(((x[:, None, :] - c[None]) ** 2).sum(-1), 1)
        nc = np.stack([x[lab == j].mean(0) if np.any(lab == j) else c[j] for j in range(k)])
        if np.allclose(nc, c, atol=1e-3):
            break
        c = nc
    return np.argmin(((x[:, None, :] - c[None]) ** 2).sum(-1), 1)


def regions(lab_p: np.ndarray, k: int = K_MAX) -> np.ndarray:
    """Номер участка у каждой пары: k-средних по Lab фото, потом слияние мелких и близких."""
    if len(lab_p) > 20000:            # k-средних на подвыборке, разметка — всех ближайшим центром
        idx = np.linspace(0, len(lab_p) - 1, 20000).astype(int)
        sub = _kmeans(lab_p[idx], k)
        cents = [lab_p[idx][sub == j].mean(0) for j in range(k) if np.any(sub == j)]
    else:
        sub = _kmeans(lab_p, k)
        cents = [lab_p[sub == j].mean(0) for j in range(k) if np.any(sub == j)]
    cents = np.stack(cents)
    while True:
        lab = np.argmin(((lab_p[:, None, :] - cents[None]) ** 2).sum(-1), 1)
        share = np.bincount(lab, minlength=len(cents)) / len(lab)
        if len(cents) == 1:
            return lab
        d = np.sqrt(((cents[:, None] - cents[None]) ** 2).sum(-1)) + np.eye(len(cents)) * 1e9
        i, j = np.unravel_index(np.argmin(d), d.shape)
        small = int(np.argmin(share))
        if share[small] < MIN_SHARE:
            cents = np.delete(cents, small, 0)
        elif d[i, j] < MERGE_DE:
            cents = np.delete(cents, max(i, j), 0)
        else:
            return lab


def curve(lv: np.ndarray, lp: np.ndarray) -> np.ndarray:
    """LUT 0..100 (шаг 0,1) светлоты вида → светлота фото: квантили, монотонность, ограничения наклона и сдвига."""
    xs = np.linspace(0, 100, 1001)
    qv, qp = np.percentile(lv, QS), np.percentile(lp, QS)
    if qv[-1] - qv[0] < 3:                         # однотонный участок: только сдвиг по медиане
        y = xs + (qp[3] - qv[3])
    else:
        # Близкие квантили вида (сеть сгладила участок в узкую полосу) — один узел со средним фото, а не выброс узлов:
        # 634079 — 25…98 % вида в 78,1…79,2, отброс «лишних» узлов убрал медиану, и кривая ушла на −21 вместо −11.
        gv, gp, cur = [], [], [0]
        for i in range(1, len(qv) + 1):
            if i == len(qv) or qv[i] - qv[cur[0]] >= 1.0:
                gv.append(float(np.mean(qv[cur])))
                gp.append(float(np.mean(qp[cur])))
                cur = [i]
            else:
                cur.append(i)
        qv, qp = np.array(gv), np.maximum.accumulate(np.array(gp))
        y = np.interp(xs, qv, qp)
        y = np.where(xs < qv[0], qp[0] + (xs - qv[0]), y)
        y = np.where(xs > qv[-1], qp[-1] + (xs - qv[-1]), y)
    dx = xs[1] - xs[0]
    dy = np.clip(np.diff(y), SLOPE_MIN * dx, SLOPE_MAX * dx)
    y2 = np.concatenate([[0.0], np.cumsum(dy)])
    m = int(np.argmin(np.abs(xs - np.median(lv))))
    y2 += float(np.median(lp)) - y2[m]              # якорь: медиана вида → медиана фото (точно)
    y2 = xs + np.clip(y2 - xs, -MAX_DL, MAX_DL)
    return np.clip(np.maximum.accumulate(y2), 0, 100)


def fit(photo_rgb, photo_alpha, view_rgb, view_mask) -> tuple[dict | None, dict]:
    """Модель поправки по фронтальному виду. (None, info) — поправки нет (причина в info['skip'])."""
    lv, lp, info = pairs(np.asarray(photo_rgb), np.asarray(photo_alpha), np.asarray(view_rgb), np.asarray(view_mask))
    if lv is None:
        return None, info
    lab = regions(lv * [L_WEIGHT, 1, 1]) if REGION_SPACE == 'view' else regions(lp)
    regs = []
    for j in range(lab.max() + 1):
        s = lab == j
        if not np.any(s):
            continue
        cv = lv[s].mean(0)
        dv = np.sqrt((((lv[s] - cv) * [L_WEIGHT, 1, 1]) ** 2).sum(-1))
        lut = curve(lv[s, 0], lp[s, 0])
        # пары участка взяты не с того материала (тонкие ножки при IoU 0,74: розовые ножки вида против серого корпуса
        # фото у 398240, T-49/4) — цвет пар фото не похож на цвет вида; кривая была бы чужой → участок оставить как есть
        dab = float(np.hypot(*(np.median(lp[s, 1:], 0) - np.median(lv[s, 1:], 0))))
        if dab > AB_MAX:
            lut = np.linspace(0, 100, 1001)
        regs.append({'share': round(float(s.mean()), 3), 'photo_lab': np.round(lp[s].mean(0), 1).tolist(),
                     'dab': round(dab, 1), 'keep': dab > AB_MAX,
                     'view_lab': np.round(cv, 1).tolist(),
                     'sigma': float(np.clip(2.0 * np.median(dv), SIGMA_MIN, SIGMA_MAX)),
                     'dL_med': round(float(np.median(lp[s, 0]) - np.median(lv[s, 0])), 1),
                     'lut': lut})
    info['regions'] = [{k: v for k, v in r.items() if k != 'lut'} for r in regs]
    return {'regions': regs}, info


def _box_sum(m: np.ndarray, r: int) -> np.ndarray:
    """Сумма по окну (2r+1)² с нулями за краем — через интегральное изображение (быстро при любом r)."""
    a = np.pad(np.asarray(m, np.float64), r + 1)
    c = a.cumsum(0).cumsum(1)
    k, (h, w) = 2 * r + 1, np.shape(m)
    return (c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k])[:h, :w]


def _dilate(m: np.ndarray, r: int) -> np.ndarray:
    return _box_sum(m, r) > 0.5 if r > 0 else np.asarray(m, bool)


def _erode_sq(m: np.ndarray, r: int) -> np.ndarray:
    return _box_sum(m, r) > (2 * r + 1) ** 2 - 0.5 if r > 0 else np.asarray(m, bool)


def support(core: np.ndarray, r: int) -> np.ndarray:
    """0..1: где участок лежит пятном шире окна 2r+1. Закрытие r/4 (дыры фактуры) → открытие r → мягкий край r/4."""
    if r <= 0 or not np.any(core):
        return np.asarray(core, np.float64)
    rc = max(1, int(round(r * CLOSE_K)))
    m = _erode_sq(_dilate(core, rc), rc)
    rc = max(1, r // 4)
    m = _dilate(_erode_sq(m, r), r)
    return _box_sum(m, rc) / (2 * rc + 1) ** 2


def apply(model: dict, view_rgb: np.ndarray, mask: np.ndarray | None = None, stats: dict | None = None) -> np.ndarray:
    """Применить поправку к одному виду (uint8 H×W×3). Меняется только L, только внутри маски (если дана); участок
    правит только там, где у него есть опора (`support`) — узкие полосы его цвета остаются как есть."""
    rgb = np.asarray(view_rgb)
    sel = np.ones(rgb.shape[:2], bool) if mask is None else np.asarray(mask, bool)
    if not np.any(sel):
        return rgb.copy()
    lab = rgb_to_lab(rgb)
    L = lab[..., 0]
    xs_idx = np.clip(np.round(L * 10).astype(int), 0, 1000)
    sig = float(np.mean([r['sigma'] for r in model['regions']]))
    w0 = np.full(L.shape, np.exp(-0.5 * (FAR_DE / sig) ** 4))
    num, den = w0 * L, w0.copy()
    bb = _bbox(sel)
    rad = 0 if SUPPORT_FRAC <= 0 else max(1, int(round(SUPPORT_FRAC * max(bb[2] - bb[0], bb[3] - bb[1]) / 2)))
    for k, r in enumerate(model['regions']):
        d = np.sqrt((((lab - r['view_lab']) * [L_WEIGHT, 1, 1]) ** 2).sum(-1))
        w = np.exp(-0.5 * (d / r['sigma']) ** 4) * sel
        core = w > CORE_W
        g = support(core, rad)
        if stats is not None:
            n = int(core.sum())
            stats.setdefault('regions', []).append({'core_px': n, 'kept': round(float(g[core].mean()), 3) if n else None})
        w = w * g
        num += w * r['lut'][xs_idx]
        den += w
    lab[..., 0] = num / den
    out = rgb.copy()
    out[sel] = lab_to_rgb(lab[sel])
    if stats is not None:
        stats['radius_px'] = rad
    return out


def apply_views(model: dict, views: list, masks: list) -> list:
    """Список PIL видов → список PIL с поправкой (размеры и режим сохраняются)."""
    res = []
    for im, m in zip(views, masks):
        a = np.asarray(im.convert('RGB'))
        mm = m if m is None or m.shape == a.shape[:2] else \
            np.asarray(Image.fromarray(m.astype(np.uint8) * 255).resize(a.shape[1::-1], Image.NEAREST)) > 127
        res.append(Image.fromarray(apply(model, a, mm)).convert(im.mode))
    return res


def photo_for_net(paint_image, size: int = 512) -> tuple[np.ndarray, np.ndarray]:
    """То, что видит сеть: фото сжато в size×size БЕЗ сохранения пропорций (апстрим `image.resize((512, 512))`),
    прозрачное — на белом. Плюс альфа той же геометрии (нет альфы — силуэт по «не белому»)."""
    im = Image.open(paint_image) if isinstance(paint_image, str) else paint_image
    im = im.resize((size, size))
    if im.mode == 'RGBA':
        alpha = np.asarray(im.getchannel('A'))
        bg = Image.new('RGB', im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel('A'))
        return np.asarray(bg), alpha
    rgb = np.asarray(im.convert('RGB'))
    return rgb, np.where(np.all(rgb >= 248, -1), 0, 255).astype(np.uint8)

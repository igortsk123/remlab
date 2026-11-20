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
Ч.2 (T-104/5, «щит изголовья»): `detect` принимает фон и когда товар заходит в кольцо 4 %, но линия рамки на ≥ 90 % ровно белая (`ring_relaxed`);
`propose` осторожно возвращает КРУПНОЕ потерянное тело (кандидат вне Rsoft и α сети < 0.15, примыкает к телу, ≥ 0.25 % кадра и ≥ 2 % тела, не у рамки,
не «тень на полу», ≤ 15 % кадра и ≤ 50 % тела; шов 1–2 px у стыка закрывается замыканием 5×5).
Ч.3 (T-104/6, №1/№2): `contrast_cut` — у ТЁМНОГО тела бесцветное светлое у кромки (цвет ≈ фону либо продолжение тени снаружи маски) — фон, срезаем;
светлое тело (шкафы, одеяло) правило не трогает (доля тёмного тела в окне ≥ 70 %); `local_thr` — для светлого в целом товара локальный порог 45.
Выключатель: env `CUTOUT_STUDIO_BG=0`.
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
F_MIN_DIST = 20.0       # ‖F−B‖∞ меньше — товар (в целом) цвета фона, шаги не трогают маску сети
LOCAL_F_MIN = F_MIN_DIST  # ЛОКАЛЬНЫЙ цвет тела у кромки ближе этого к фону (белая ткань на белом, 104/5 правки): край сети не трогаем — ни вычитать, ни α. Тот же порог 20, что у «товар цвета фона»; 40 оставлял грязь у светлых тел (80 фото вместо 18)
SOFT_DROP_BELOW = 0.3   # ac ниже — пиксель по цвету почти чистый фон: можно срезать; выше — только смягчить (α ≥ 0.5)
SOFT_KEEP_FLOOR = 0.6    # нижняя граница α у пикселей, которые не срезаем (строго выше порога маски 0.5)
SOFT_SMOOTH = 5         # окно сглаживания ac вдоль кромки (px)
PERIM_RELAX = 0.90      # Ч.2: кольцо 4 % не прошло (товар вплотную к рамке), но САМА линия рамки на ≥ 90 % — один и тот же белый: фон ровный, B — по линии рамки
PROP_RAW_MAX = 0.15     # Ч.2: кандидат на пропавшее тело — «не фон» (вне Rsoft) там, где сеть почти не видела товар (α < 0.15)
PROP_MIN_FRAME = 0.0025  # компонент кандидата ≥ 0.25 % кадра …
PROP_MIN_FG = 0.02      # … и ≥ 2 % текущего тела
PROP_MAX_FRAME = 0.15   # всего добавлено ≤ 15 % кадра …
PROP_MAX_FG = 0.50      # … и ≤ 50 % текущего тела
PROP_PERIM_MAX = 0.20   # компонент касается ≤ 20 % периметра кадра
PROP_TOUCH_ITER = 3     # должен примыкать (≤ 3 px) к текущему телу
PROP_EDGE_STEP = 10.0   # у настоящего тела переход к фону РЕЗКИЙ (щит 228 → 255 за пиксель), у тени — плавный градиент: медиана скачка через границу с фоном ≥ 10
PROP_SHADOW_SHARE = 0.5  # больше половины — «тень на полу» (ниже низа тела в столбце, бесцветная, темнее фона) — отклоняем
CC_BAND = 8             # Ч.3: «контрастное тело»: полоса у кромки, где ищем островки цвета фона (px)
CC_F_MIN = 80.0         # локальный цвет тела ≥ 80 от фона (тёмное/серое тело) — иначе правило не работает (светлую ткань защищает Ч.1)
CC_REL = 0.45           # пиксель ближе к фону, чем 0.45·‖F−B‖ (но не дальше CC_ABS), и бесцветный как фон
CC_ABS = 80.0
CC_CHROMA = 16.0        # размах каналов пикселя ≤ 16 (фон нейтральный; дерево/кожа/цвет — не трогаем)
CC_CONT = 14.0          # или: цвет пикселя ≈ цвету ближайшего пикселя СНАРУЖИ маски (≤ 14) — кромка сети режет плавную тень-градиент, а не край тела
CC_SHARE = 0.70         # доля «тёмного» уверенного тела в окне 21×21
CC_MAX_SHARE = 0.03     # всего срезать ≤ 3 % тела
PROP_THIN_R = 6.0       # T-104/7: добавка, ПРИЛЕГАЮЩАЯ к рамке кадра, с вписанным радиусом < 6 px (≈ 12 px толщины) — провод/нить, не тело
HW_D = 130.0            # T-104/7: «клин под телом» — бесцветное (размах ≤ 16) серое не темнее 125 (Δ от фона ≤ 130) НЕ считается плотным телом и лежит ниже самого низкого плотного (тёмного/цветного) пикселя столбца …
HW_CHROMA = 16.0
HW_MIN_PX = 300         # … компонент ≥ 300 px, касается кромки маски, примыкает к плотному телу сверху, с обеих сторон — плотное тело (ножки), опускающееся ниже клина
HW_ASPECT = 1.5          # T-104/7: клин пологий — ширина ≥ 1,5 высоты и ≥ HW_MIN_W px (полосы столбцов в светлом теле — не клин)
HW_MIN_W = 40
HW_MAX_SHARE = 0.05     # всего срезать ≤ 5 % тела
LIGHT_PRODUCT = 45.0    # Ч.2: товар в целом светлый (медиана тела ‖F−B‖ < 45, белый шкаф с рельефом: канавки 225 vs фон 255) — локальный порог 45, иначе рельеф принимается за контраст и край рвётся (T-104/5)
LOCAL_F_WIN = 9         # окно (px) усреднения цвета уверенного тела вокруг пикселя кромки
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
        # товар вплотную к рамке: кольцо 4 % захватило товар (медиана/процентили врут), но сама линия рамки ровно белая — фон ровный (Ч.2)
        Bp = np.median(per, axis=0)
        dp = np.abs(per - Bp).max(axis=1)
        madp = float(np.median(np.abs(dp - np.median(dp))))
        tcp = float(np.clip(max(6.0, 3 * madp), 6.0, 10.0))
        perim_p = float((dp <= tcp).mean())
        spread_p = float(Bp.max() - Bp.min())
        if float(Bp.min()) >= MIN_B and spread_p <= SPREAD_MAX and perim_p >= PERIM_RELAX:
            st.update({'bg': [round(float(v), 1) for v in Bp], 'spread': round(spread_p, 1), 'perim': round(perim_p, 3),
                       't_core': round(tcp, 1), 't_soft': round(min(tcp + 10.0, 20.0), 1), 'ring_relaxed': True, 'ring_why': why})
            return Bp, st
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


def confident_body(mask, d, rsoft, depth):
    """Уверенное тело: глубже кромки или локальный максимум удаления от фона (тонкая трубка), не фон Rsoft."""
    peak = d >= ndi.maximum_filter(d, size=5) - 8.0
    return mask & ((depth > BAND_CORE + 1) | ((d >= CONF_DIST) & peak)) & ~rsoft


def local_fg(conf, f, win=LOCAL_F_WIN):
    """Локальный цвет тела вокруг каждого пикселя (нормированное усреднение по уверенному телу в окне win×win). Возвращает (F, есть_ли_тело_рядом)."""
    w = conf.astype(np.float32)
    num = np.stack([ndi.uniform_filter(f[..., c] * w, size=win, mode='constant') for c in range(3)], axis=2)
    den = ndi.uniform_filter(w, size=win, mode='constant')
    ok = den > 1e-4
    return num / np.maximum(den, 1e-4)[..., None], ok


def local_state(conf, f, B, thr=None):
    """(F, похоже_на_фон, есть_тело_рядом): F — среднее уверенного тела в окне (нет — ближайший пиксель тела); «похоже на фон» — если близко к B
    ИЛИ среднее по окну, ИЛИ ближайший пиксель тела (консервативно: край светлой ткани лучше оставить, чем стесать)."""
    Fw, ok = local_fg(conf, f)
    _, (iy, ix) = ndi.distance_transform_edt(~conf, return_indices=True)
    Fn = f[iy, ix]
    F = np.where(ok[..., None], Fw, Fn)
    thr = LOCAL_F_MIN if thr is None else thr
    near = (np.abs(Fw - B).max(axis=2) < thr) | (np.abs(Fn - B).max(axis=2) < thr)
    return F, near, ok


def local_thr(mask, rgb, bg):
    """Порог «локальный цвет тела близок к фону»: 20 (LOCAL_F_MIN) для обычного товара, LIGHT_PRODUCT для светлого в целом (белый шкаф с рельефом)."""
    inner = ndi.binary_erosion(mask, iterations=3)
    pix = rgb[inner] if inner.any() else rgb[mask]
    if not len(pix):
        return LOCAL_F_MIN
    F = np.median(pix.astype(np.float32), axis=0)
    return LIGHT_PRODUCT if float(np.abs(F - np.asarray(bg, np.float32)).max()) < LIGHT_PRODUCT else LOCAL_F_MIN


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
    if rm.any():
        # локальный цвет тела у кромки: если он близок к фону (белая ткань на белом) — край сети не трогаем (T-104/5 правки директора)
        f = rgb.astype(np.float32)
        dd = np.abs(f - np.asarray(bg, np.float32)).max(axis=2)
        conf = confident_body(mask, dd, rcore, depth)
        if conf.any():
            _, near, ok = local_state(conf, f, np.asarray(bg, np.float32), local_thr(mask, rgb, bg))
            kept = rm & (near | ~ok)
        else:
            kept = rm
        rm &= ~kept
        nk = int(kept.sum())
    else:
        nk = 0
    n = int(rm.sum())
    if not n:
        return alpha, ({'subtract_px': 0, 'subtract_local_kept_px': nk} if nk else {'subtract_px': 0})
    if n > SUBTRACT_MAX_SHARE * mask.sum():
        return alpha, {'subtract_skipped': f'снести пришлось бы {n} px (> {int(SUBTRACT_MAX_SHARE * 100)} % тела) — белый товар, не трогаем'}
    out = alpha.copy()
    out[rm] = 0.0
    return out, ({'subtract_px': n, 'subtract_local_kept_px': nk} if nk else {'subtract_px': n})


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
    conf = confident_body(mask, d, rsoft, depth)
    # переходная полоса: пиксели маски у кромки, рядом (≤ 2 px) с фоном Rsoft — тени и прочее не «фон», их не трогаем
    band = mask & (depth <= BAND_CORE) & ~conf & ndi.binary_dilation(rsoft, iterations=BAND_CORE)
    if not band.any():
        return alpha, rgb, {'soft_px': 0}
    if not conf.any():
        return alpha, rgb, {'soft_skipped': 'нет уверенного тела для цвета F'}
    F, similar, _ = local_state(conf, f, B, local_thr(mask, rgb, bg))
    FB = F - B
    nrm2 = (FB * FB).sum(axis=2)
    ac = np.clip(((f - B) * FB).sum(axis=2) / (nrm2 + 1e-3), 0.0, 1.0)
    act = band & ~similar & (ac < alpha)
    if not act.any():
        return alpha, rgb, {'soft_px': 0}
    # слоями (T-104/5, правки): второй слой кромки трогаем, только если внешний слой реально срезан (α<0.5). Светлый блик/ребро ярче тела
    # (рама картины, верх шкафа) — не смесь с фоном: без этого во втором ряду появлялась щель-«лесенка» между рядами.
    L1 = act & (depth <= 1.0 + 1e-3)
    drop1 = L1 & (ac < thr)
    outer_gone = ndi.binary_dilation(drop1 | (~mask), structure=np.ones((3, 3), bool))
    act = L1 | (act & ~L1 & outer_gone)
    if not act.any():
        return alpha, rgb, {'soft_px': 0}
    # ac по кромке шумит вокруг порога 0.5 (текстура, блики) — граница α>0.5 получается зубчатой; усредняем по соседним пикселям кромки (окно 5×5)
    w = act.astype(np.float32)
    nb = ndi.uniform_filter(w, size=SOFT_SMOOTH, mode='constant')
    acs = ndi.uniform_filter(ac * w, size=SOFT_SMOOTH, mode='constant') / np.maximum(nb, 1e-4)
    ac = np.where(act & (nb > 1e-4), acs, ac)
    # геометрию (α>0.5) мягкий край меняет только там, где пиксель явно фон (ac < SOFT_DROP_BELOW); у остальных α не ниже 0.5 — светлая кайма ковра/блик
    # не «пилится» шумом ac вокруг порога
    ac = np.where(ac < SOFT_DROP_BELOW, ac, np.maximum(ac, SOFT_KEEP_FLOOR))
    new = np.where(act, ac, alpha)
    dropped = int((act & (ac < thr)).sum())
    if dropped > SOFT_MAX_SHARE * mask.sum():
        return alpha, rgb, {'soft_skipped': f'мягкий край снёс бы {dropped} px (> {int(SOFT_MAX_SHARE * 100)} % тела) — откат'}
    new[new < 0.04] = 0.0
    out_rgb = np.where(act[..., None] & (new[..., None] > 0), np.clip(F, 0, 255), f).astype(rgb.dtype)
    return new.astype(alpha.dtype), out_rgb, {'soft_px': int(act.sum()), 'soft_dropped_px': dropped}


def propose(alpha, raw, rgb, bg, rsoft, thr=0.5):
    """Ч.2 (T-104/5): осторожно вернуть крупное тело, которое сеть потеряла (белый щит изголовья на белом фоне).
    Кандидат P = (~Rsoft) & (raw < 0.15) & не в маске. Компонент (8-связность) принимается, только если: примыкает к телу (≤ 3 px), крупный
    (≥ 0.25 % кадра и ≥ 2 % тела), не упирается в рамку (≤ 20 % периметра), не «тень на полу»; в сумме ≤ 15 % кадра и ≤ 50 % тела.
    Дыры внутри принятого заливаются. α = 1 (край потом смягчает soft_alpha, если цвет не близок к фону). Возвращает (alpha2, info)."""
    mask = alpha > thr
    fg = int(mask.sum())
    h, w = mask.shape
    if not fg:
        return alpha, {}
    P = (~rsoft) & (raw < PROP_RAW_MAX) & ~mask
    lab, n = ndi.label(P, structure=np.ones((3, 3), int))
    if n == 0:
        return alpha, {'prop_px': 0}
    area = np.bincount(lab.ravel(), minlength=n + 1)
    sup = ndi.binary_dilation(mask, np.ones((3, 3), bool), iterations=PROP_TOUCH_ITER)
    touch = np.zeros(n + 1, bool)
    touch[np.unique(lab[sup & P])] = True
    frame = np.zeros((h, w), bool)
    frame[0], frame[-1], frame[:, 0], frame[:, -1] = True, True, True, True
    per_len = float(frame.sum())
    pcount = np.bincount(lab[frame & P], minlength=n + 1)
    f = rgb.astype(np.float32)
    col_has = mask.any(axis=0)
    col_bottom = np.where(col_has, h - 1 - mask[::-1].argmax(axis=0), -1)
    below = (np.arange(h)[:, None] > col_bottom[None, :]) & col_has[None, :]
    mx, mn = f.max(axis=2), f.min(axis=2)
    shadowish = below & ((mx - mn) < 18) & (mx < float(np.asarray(bg).max()))
    sc = np.bincount(lab[shadowish & P], minlength=n + 1)
    # резкость границы с фоном: для каждого пикселя кандидата, соседнего (4-связность) с фоном Rsoft, скачок цвета до соседа-фона
    step = np.zeros((h, w), np.float32)
    nb = np.zeros((h, w), bool)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        q = np.roll(rsoft, (dy, dx), axis=(0, 1))
        fq = np.roll(f, (dy, dx), axis=(0, 1))
        dd = np.abs(f - fq).max(axis=2)
        m_ = P & q
        step = np.where(m_ & (dd > step), dd, step)
        nb |= m_
    min_area = max(PROP_MIN_FRAME * h * w, PROP_MIN_FG * fg)
    out = alpha.copy()
    added = 0
    acc, rej = [], []
    for i in np.argsort(-area[1:]) + 1:
        a = int(area[i])
        if a < min_area:
            break
        why = None
        if not touch[i]:
            why = 'не примыкает к телу'
        elif pcount[i] / per_len > PROP_PERIM_MAX:
            why = 'упирается в рамку'
        elif sc[i] / a > PROP_SHADOW_SHARE:
            why = 'тень на полу'
        elif pcount[i] > 0 and float(ndi.distance_transform_edt(lab == i).max()) < PROP_THIN_R:
            why = 'тонкая добавка у рамки (провод)'
        elif not (lab == i)[nb].any() or float(np.median(step[(lab == i) & nb])) < PROP_EDGE_STEP:
            why = 'плавная граница (тень/градиент)'
        elif added + a > PROP_MAX_FRAME * h * w or added + a > PROP_MAX_FG * fg:
            why = 'сверх лимита добавки'
        if why:
            rej.append((a, why))
            continue
        c = ndi.binary_fill_holes(lab == i) & (raw < PROP_RAW_MAX) & ~mask
        out[c] = 1.0
        added += int(c.sum())
        acc.append(a)
    if added:
        # шов 1–2 px внутри/на стыке со старым телом (ободок сети вокруг подушек, α 0.15–0.5 в кандидаты не попал) — закрываем замыканием 5×5,
        # но только рядом (≤ 12 px) с добавкой и только «не фон» (вне Rsoft)
        new_part = (out > thr) & ~mask
        cl = ndi.binary_closing(np.pad(out > thr, 3), np.ones((5, 5), bool))[3:-3, 3:-3]
        near = ndi.binary_dilation(new_part, np.ones((3, 3), bool), iterations=12)
        seam = cl & ~(out > thr) & near & ~rsoft
        out[seam] = 1.0
        added += int(seam.sum())
    info = {'prop_px': added, 'prop_comps': len(acc)}
    if rej:
        info['prop_rejected'] = [f'{a} px: {w_}' for a, w_ in rej[:4]]
    return out, info


def contrast_cut(alpha, rgb, bg, rsoft, thr=0.5):
    """Ч.3 (T-104/5, замечание владельца №1/№2): у ТЁМНОГО/серого тела белый островок цвета фона у кромки — это фон, без исключений. Тени-градиенты
    (светло-серые 224–250, сеть их удержала) не доходят до `subtract` (не в Rcore — отделены тенью от рамки). Правило: пиксель маски в полосе ≤ 8 px
    от кромки, у которого локальный цвет тела F далёк от фона (‖F−B‖ ≥ 80), сам ближе к фону, чем 0.45·‖F−B‖ (≤ 80) ИЛИ того же цвета, что ближайший пиксель снаружи маски (тень-градиент, ≤ 14), бесцветный (размах ≤ 16),
    — срезаем; только компоненты, касающиеся кромки; всего ≤ 3 % тела. Светлое тело на белом (F ≈ B) правило не касается. Возвращает (alpha2, info)."""
    mask = alpha > thr
    fg = int(mask.sum())
    if not fg:
        return alpha, {}
    B = np.asarray(bg, np.float32)
    f = rgb.astype(np.float32)
    d = np.abs(f - B).max(axis=2)
    depth = ndi.distance_transform_edt(mask)
    conf = confident_body(mask, d, rsoft, depth)
    dark = conf & (d >= CC_F_MIN)                        # «тёмное» тело: от него считаем F; светлая бахрома у кромки (она и есть кандидат) в F не входит
    if not dark.any():
        return alpha, {'cc_px': 0}
    F, ok = local_fg(dark, f, 21)
    # тело вокруг должно БЫТЬ тёмным в целом (≥ 70 % уверенного тела окна далеко от фона), а не светлым с тёмными пятнами (ручки, канавки, ножки)
    deep = conf & (depth > CC_BAND)                      # судим по глубокому телу (глубже полосы кромки): светлая бахрома шириной ≤ 8 px сюда не попадает
    share = ndi.uniform_filter((deep & dark).astype(np.float32), size=21, mode='constant') / np.maximum(
        ndi.uniform_filter(deep.astype(np.float32), size=21, mode='constant'), 1e-4)
    ok &= share >= CC_SHARE
    fd = np.abs(F - B).max(axis=2)
    chroma = f.max(axis=2) - f.min(axis=2)
    _, (iy, ix) = ndi.distance_transform_edt(mask, return_indices=True)
    cont = np.abs(f - f[iy, ix]).max(axis=2) <= CC_CONT
    near_bg = d <= np.minimum(CC_REL * fd, CC_ABS)
    shadow_cont = cont & (d < 0.8 * fd)
    cand = mask & (depth <= CC_BAND) & ok & (fd >= CC_F_MIN) & (near_bg | shadow_cont) & (chroma <= CC_CHROMA)
    if not cand.any():
        return alpha, {'cc_px': 0}
    lab, n = ndi.label(cand, structure=np.ones((3, 3), int))
    edge = np.unique(lab[cand & (depth <= 1.5)])
    keep = np.isin(lab, edge[edge > 0])
    n_px = int(keep.sum())
    if n_px > CC_MAX_SHARE * fg:
        return alpha, {'cc_px': 0, 'cc_skipped': f'срез {n_px} px > {int(CC_MAX_SHARE * 100)} % тела'}
    out = alpha.copy()
    out[keep] = 0.0
    return out, {'cc_px': n_px}


def hang_wedge(alpha, rgb, bg, rsoft, thr=0.5):
    """T-104/7 (клин под телом, кровать №29): светлое бесцветное пятно ниже самого низкого плотного (тёмного/цветного) пикселя своих столбцов, между
    ножками (плотное тело слева и справа опускается ниже клина), примыкающее сверху к плотному телу и касающееся кромки маски — это пол/фон между ножками.
    Компонент ≥ 300 px; всего срезать ≤ 5 % тела. Светлое тело без плотного в столбце (белый шкаф) правило не касается. Возвращает (alpha2, info)."""
    mask = alpha > thr
    fg = int(mask.sum())
    if not fg:
        return alpha, {}
    B = np.asarray(bg, np.float32)
    f = rgb.astype(np.float32)
    d = np.abs(f - B).max(axis=2)
    chroma = f.max(axis=2) - f.min(axis=2)
    depth = ndi.distance_transform_edt(mask)
    conf = confident_body(mask, d, rsoft, depth)
    solid = conf & (d >= CC_F_MIN) & ((chroma > HW_CHROMA) | (d > HW_D))     # бесцветное серое (грани тени/пола) плотным телом не считаем
    if not solid.any():
        return alpha, {'hw_px': 0}
    h, w = mask.shape
    has = solid.any(axis=0)
    bot = np.where(has, h - 1 - solid[::-1].argmax(axis=0), -1)
    below = (np.arange(h)[:, None] > bot[None, :]) & has[None, :]
    cand = mask & below & (d <= HW_D) & (chroma <= HW_CHROMA)
    if not cand.any():
        return alpha, {'hw_px': 0}
    lab, n = ndi.label(cand, structure=np.ones((3, 3), int))
    area = np.bincount(lab.ravel(), minlength=n + 1)
    keep = np.zeros_like(mask)
    for i in range(1, n + 1):
        if area[i] < HW_MIN_PX:
            continue
        c = lab == i
        cont = ndi.binary_dilation(c, np.ones((3, 3), bool), iterations=3) & solid
        if not (c & (depth <= 1.5)).any() or not cont.any():
            continue
        ys, xs = np.where(c)
        # клин между ножками — пологий (шире своей высоты ≥ 1,5 раза); узкая высокая полоса столбцов — светлое тело (кровать/шкаф/ящики), не клин
        if (xs.max() - xs.min() + 1) < HW_ASPECT * (ys.max() - ys.min() + 1) or (xs.max() - xs.min() + 1) < HW_MIN_W:
            continue
        # плотное тело примыкает только СВЕРХУ (верхние 30 % высоты клина); панель между ножками (примыкает по бокам на всю высоту) — тело, не трогаем
        if np.where(cont)[0].max() > ys.min() + 0.3 * (ys.max() - ys.min()) + 3:
            continue
        x0, x1, yb = int(xs.min()), int(xs.max()), int(ys.max())
        span = max(w // 2, 3 * (x1 - x0 + 1))        # плотное тело-ножки ищем по сторонам на полкадра
        left = bot[max(0, x0 - span):x0]
        right = bot[x1 + 1:x1 + 1 + span]
        if left.size and right.size and left.max() > yb + 2 and right.max() > yb + 2:
            keep |= c
    n_px = int(keep.sum())
    if not n_px:
        return alpha, {'hw_px': 0}
    if n_px > HW_MAX_SHARE * fg:
        return alpha, {'hw_px': 0, 'hw_skipped': f'срез {n_px} px > {int(HW_MAX_SHARE * 100)} % тела'}
    out = alpha.copy()
    out[keep] = 0.0
    return out, {'hw_px': n_px}

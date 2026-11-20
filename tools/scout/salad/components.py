"""Отбраковка кусков фона, оставшихся в маске отдельными пятнами.

Зачем. На фото-коллаже (баннер магазина: плашка с названием, текст, интерьерная сцена) сеть
иногда оставляет обрывок плашки — у стула Wishbone это зелёный хвост в верхнем углу. Для
картинки это косметика, для генератора 3D — нет: он честно строит по маске и превращает
обрывок в геометрию.

Почему не «удалять мелкое по площади». Так уходят настоящие отдельные части: второй стул в
комплекте, ножка, просвет спинки. Признак не размер, а СВЯЗЬ с товаром — кусок фона лежит
сам по себе и обычно упирается в край кадра, а часть товара либо примыкает к главному телу,
либо сопоставима с ним по размеру.

Возвращает не только очищенную маску, но и повод: крупная отброшенная область — это не
успех очистки, а сигнал, что фото вообще не карточка товара, и SKU надо смотреть глазами.
"""
import numpy as np
from scipy import ndimage

NEAR_PX = 6          # насколько «рядом с товаром» ещё считается частью товара
BIG_SHARE = 0.25     # доля от главного тела, при которой отдельный кусок считаем деталью
SUSPECT_SHARE = 0.02 # сколько отброшенного уже требует человеческого взгляда


# Роли со СПЛОШНЫМ силуэтом: у вазы, кашпо и статуэтки сквозных просветов нет, а прозрачность
# есть — сквозь стекло видна карточка, сеть честно ставит альфу к нулю, и от вазы остаётся
# ободок. Генератору меша нужна ЗАНЯТОСТЬ, а не оптическая прозрачность, поэтому здесь дырки
# заливаются независимо от того, что внутри. Мебель (стеллаж, витрина, стул) сюда не входит:
# там просветы настоящие, и заливка превратила бы предмет в глухой ящик.
SOLID_SILHOUETTE_ROLES = {'ваза', 'кашпо', 'статуэтка'}


def fill_holes_unlike_bg(alpha, rgb, thr=0.5, max_hole_share=0.25, role=None):
    """Залить дырки в маске, ВНУТРИ которых не фон.

    Зачем понадобилось (наблюдение владельца 29.08): у ковра сеть уверенно держит узор и теряет
    основу — маска рассыпается на острова, а между ними «дырки», в которых на самом деле лежит
    тот же ковёр. То же бывает с серыми предметами на светлой карточке.

    Почему нельзя просто `binary_fill_holes` (урок 307): у проволочного основания и реечной
    спинки просветы — НАСТОЯЩИЕ, заливка превратит стул в фанерный щит. Разница видна по
    содержимому дырки: у проволоки внутри просвета — фон карточки, у ковра — сам ковёр.
    Поэтому заливаем только те дырки, чей цвет НЕ похож на фон.

    Крупные дырки (> `max_hole_share` площади товара) не трогаем вовсе: это уже не «потерянная
    основа», а либо настоящий просвет мебели, либо ошибка сети, которую заливкой не лечат.
    """
    fg = alpha > thr
    if not fg.any():
        return alpha, {'filled_px': 0, 'filled_holes': 0}
    filled = ndimage.binary_fill_holes(fg)
    holes = filled & ~fg
    if not holes.any():
        return alpha, {'filled_px': 0, 'filled_holes': 0}

    rgb = rgb.astype(np.float32)
    h, w = fg.shape
    b = max(2, int(min(h, w) * 0.04))
    band = np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])
    bg = np.median(band, axis=0)
    bg_tol = max(float(np.percentile(np.linalg.norm(band - bg, axis=1), 99)) * 1.4, 24.0)
    dist = np.linalg.norm(rgb - bg, axis=2)

    lab, n = ndimage.label(holes)
    out = alpha.copy()
    filled_px = filled_holes = 0
    area = float(fg.sum())
    for i in range(1, n + 1):
        m = lab == i
        if m.sum() > max_hole_share * area:
            continue
        # У ролей со сплошным силуэтом содержимое дырки не спрашиваем: сквозь стекло видно
        # ровно фон, и условие «не фон» заблокировало бы именно тот случай, ради которого
        # заливка тут и нужна.
        if role not in SOLID_SILHOUETTE_ROLES:
            # доля пикселей дырки, НЕ похожих на фон: >70% → внутри товар, а не просвет
            if float((dist[m] > bg_tol).mean()) < 0.7:
                continue
        out[m] = np.maximum(out[m], 1.0)
        filled_px += int(m.sum())
        filled_holes += 1
    return out, {'filled_px': filled_px, 'filled_holes': filled_holes}


def clean(alpha, thr=0.5, eight=True):
    """alpha: float 0..1. → (очищенная alpha, отчёт)."""
    fg = alpha > thr
    rep = {'dropped_share': 0.0, 'dropped_components': 0, 'components': 0, 'suspect': False}
    # T-99/3: 8-связность (раньше по умолчанию 4): диагональный трос/провод шириной 1–2 px при 4-связности рассыпается на одиночные пиксели,
    # которые не примыкают к телу и срезались как мусор — от тросов люстры оставались огрызки у плафона и кольца (99272_11551104666593844009).
    lab, n = ndimage.label(fg, structure=np.ones((3, 3)) if eight else None)      # eight=False — прежнее поведение (только для сравнения в пробах)
    rep['components'] = int(n)
    if n <= 1:
        return alpha, rep

    sizes = np.bincount(lab.ravel())[1:]
    main_i = int(np.argmax(sizes)) + 1
    main = lab == main_i
    near = ndimage.binary_dilation(main, np.ones((3, 3)), iterations=NEAR_PX)

    border = np.zeros(fg.shape, bool)
    border[0], border[-1], border[:, 0], border[:, -1] = 1, 1, 1, 1

    keep = main.copy()
    dropped = 0
    for i in range(1, n + 1):
        if i == main_i:
            continue
        m = lab == i
        if (m & near).any():                       # примыкает к товару — его часть
            keep |= m
            continue
        if sizes[i - 1] >= BIG_SHARE * sizes[main_i - 1] and not (m & border).any():
            keep |= m                              # крупная самостоятельная деталь не у края
            continue
        dropped += int(sizes[i - 1])
        rep['dropped_components'] += 1

    out = np.where(keep, alpha, 0.0)
    rep['dropped_share'] = round(float(dropped / max(fg.sum(), 1)), 4)
    rep['suspect'] = rep['dropped_share'] > SUSPECT_SHARE
    return out, rep


# Роли для среза прилипших хвостов: массивные мягкие, у которых тонкая структура — не
# природа предмета. Люстры/торшеры/стеллажи/столы НЕ включать (владелец 30.08: «не
# почикай тонкие элементы, лучше не делать, если риск»): у люстры потолочный диск на
# тонкой штанге при открытии уцелел бы отдельным куском и был бы отрезан.
ATTACHED_PRUNE_ROLES = {'диван', 'кровать', 'кресло', 'банкетка', 'пуф'}


def prune_attached(alpha, role=None, thr=0.5, bridge_px=4,
                   max_cut_share=0.08, min_open_share=0.60):
    """Хвосты, ПРИЛИПШИЕ к товару тонкой перемычкой (тень/артефакт у пола) — `clean`
    их не видит: компонент один. Подтверждено владельцем 30.08: артефакт у ножки на
    фото дивана 114667_514… дал белый обломок-призрак в меше.

    Механика: морфологическое открытие рвёт перемычки тоньше bridge_px; каждый пиксель
    маски приписывается к БЛИЖАЙШЕМУ уцелевшему куску — тонкие детали товара (ножки),
    стёртые открытием, приписываются обратно к телу (они к нему ближе всего). Куски,
    приписанные не к главному телу, отрезаются.

    Пояса безопасности (владелец: «если риск — лучше не делать»):
    1) только роли из ATTACHED_PRUNE_ROLES (белый список массивных);
    2) срезается только кусок ЦЕЛИКОМ в нижних 40% bbox маски (артефакты пола/тени);
    3) открытая маска <60% исходной (весь предмет тонкий) — не трогаем ничего;
    4) суммарный срез >8% маски — не трогаем ничего.
    """
    import numpy as np
    from scipy import ndimage
    base = (role or '').split()[0] if role else ''
    if base not in ATTACHED_PRUNE_ROLES:
        return alpha, {}
    fg = alpha > thr
    if fg.sum() < 400:
        return alpha, {}
    k = np.ones((3, 3), bool)
    opened = ndimage.binary_erosion(fg, k, iterations=bridge_px)
    opened = ndimage.binary_dilation(opened, k, iterations=bridge_px) & fg
    if opened.sum() < min_open_share * fg.sum():
        return alpha, {'attached_skip': 'open_share'}
    lab, n = ndimage.label(opened)
    if n < 2:
        return alpha, {}
    sizes = np.bincount(lab.ravel())[1:]
    main_i = int(np.argmax(sizes)) + 1
    _, (ni, nj) = ndimage.distance_transform_edt(lab == 0, return_indices=True)
    owner = lab[ni, nj]
    ys, xs = np.where(fg)
    y_lo = ys.min() + 0.60 * (ys.max() - ys.min())     # нижние 40% bbox маски
    cut = np.zeros_like(fg)
    pruned = 0
    for i in range(1, n + 1):
        if i == main_i:
            continue
        piece = fg & (owner == i)
        if not piece.any():
            continue
        if np.where(piece)[0].min() < y_lo:            # выше нижней зоны — не трогаем
            continue
        cut |= piece
        pruned += 1
    share = float(cut.sum()) / float(fg.sum())
    if not cut.any() or share > max_cut_share:
        return alpha, {'attached_skip': 'cut_share', 'attached_share': round(share, 4)}
    return np.where(cut, 0.0, alpha), {'attached_pruned': pruned,
                                       'attached_share': round(share, 4)}


# ЗАЗОРЫ 1–2 px У КРОМКИ (T-20261119-104/2). У светлого товара на белом фоне сеть рвёт верхнюю кромку «пунктиром»: края тела почти
# равны фону, и в маске остаются щели шириной в 1–2 пикселя (шкаф, комод, спинка дивана). Правило ОДНО для всех товаров, без ID:
# морфологическое закрытие 3×3 (закрывает щели шириной ≤ 2 px; пустоты от 3 px — ножки, ручки, просветы реек — не закрывает) и
# только в полосе EDGE_ZONE_PX от внешнего фона: внутренние дырки и мелкая сетка не трогаются. Цвет добавленных пикселей — от
# ближайшего пикселя товара (не белый фон, чтобы не рисовать светлую крапинку на тёмном краю).
EDGE_GAP_PX = int(__import__('os').environ.get('CUTOUT_EDGE_GAP_PX', '2'))   # 0 — выключено
EDGE_ZONE_PX = 4


def close_edge_gaps(alpha, rgb, thr=0.5, gap_px=None, zone_px=EDGE_ZONE_PX):
    """Закрыть щели шириной ≤ `gap_px` у внешней кромки маски. Возвращает (alpha2, rgb2, info): info — `edge_gap_closed` (пикселей) и, если выключено, пометку."""
    gap_px = EDGE_GAP_PX if gap_px is None else gap_px
    if gap_px <= 0:
        return alpha, rgb, {'edge_gap_closed': 0, 'edge_gap_off': True}
    b = alpha > thr
    if not b.any():
        return alpha, rgb, {'edge_gap_closed': 0}
    it = max(1, (gap_px + 1) // 2)                       # 3×3 за проход закрывает щель в 2 px
    pad = it + 1
    bp = np.pad(b, pad)                                  # рамка кадра — фон: закрытие не «съедает» товар у края кадра
    closed = ndimage.binary_closing(bp, structure=np.ones((3, 3), bool), iterations=it)[pad:-pad, pad:-pad]
    gaps = closed & ~b
    if not gaps.any():
        return alpha, rgb, {'edge_gap_closed': 0}
    lab, _ = ndimage.label(~b)                           # внешний фон — компонента, достающая до рамки кадра
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    ext = np.isin(lab, border[border > 0])
    near_ext = ndimage.distance_transform_edt(~ext) <= zone_px
    add = gaps & near_ext
    n = int(add.sum())
    if not n:
        return alpha, rgb, {'edge_gap_closed': 0}
    _, (iy, ix) = ndimage.distance_transform_edt(~b, return_indices=True)
    a2 = np.where(add, 1.0, alpha).astype(alpha.dtype)
    rgb2 = np.where(add[..., None], rgb[iy, ix], rgb)
    return a2, rgb2, {'edge_gap_closed': n}

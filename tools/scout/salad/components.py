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


def clean(alpha, thr=0.5):
    """alpha: float 0..1. → (очищенная alpha, отчёт)."""
    fg = alpha > thr
    rep = {'dropped_share': 0.0, 'dropped_components': 0, 'components': 0, 'suspect': False}
    lab, n = ndimage.label(fg)
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

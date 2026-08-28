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

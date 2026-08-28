"""Отличить карточку товара от рекламного коллажа — до всякой вырезки и без денег.

Зачем отдельным шагом. Обрывок фона в маске можно вычистить (`components.clean`), но у коллажа
беда глубже: в кадре плашка с названием, список свойств текстом, интерьерная сцена со своим
светом и нередко ВТОРАЯ копия товара с другого ракурса. Вычистка тут лечит симптом — на входе
генератора всё равно оказывается сцена, а не товар. Такие SKU дешевле не отдавать на меш.

Признаки (каждый сам по себе слабый, решает сумма):
  * фон не ровный — по пограничной полосе большой разброс;
  * широкая полоса ОДНОГО насыщенного цвета у края — плашка баннера;
  * текст — много мелких тёмных пятен, выстроенных в горизонтальные строки;
  * плотность краёв высокая по всему кадру — признак сцены, а не предмета на фоне.
"""
import numpy as np
from scipy import ndimage


def _band(rgb, frac=0.04):
    h, w = rgb.shape[:2]
    b = max(2, int(min(h, w) * frac))
    return np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[:, :b].reshape(-1, 3), rgb[:, -b:].reshape(-1, 3)])


def features(rgb):
    rgb = rgb.astype(np.float32)
    h, w = rgb.shape[:2]
    band = _band(rgb)
    med = np.median(band, axis=0)
    # Не квантиль расстояния, а ДОЛЯ пограничных пикселей, непохожих на фон. Квантиль ловит
    # сам товар, залезший в полосу (широкий комод во всю ширину кадра давал «разброс 312»
    # на чистой белой карточке), доля — устойчива: товар занимает малую часть полосы.
    p99 = float((np.linalg.norm(band - med, axis=1) > 25).mean())

    # Плашка баннера: насыщенная область, которая УПИРАЕТСЯ В КРАЙ кадра и залита РОВНО.
    # Без этих двух условий за плашку принимается сам товар — зелёная тв-тумба на белой
    # карточке давала «плашку 0.32» и уезжала в коллажи.
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    sat = (mx - mn) > 45
    plate = 0.0
    if sat.any():
        lab, n = ndimage.label(sat)
        edge = np.zeros((h, w), bool)
        edge[0], edge[-1], edge[:, 0], edge[:, -1] = 1, 1, 1, 1
        for i in range(1, n + 1):
            m = lab == i
            share = float(m.sum() / (h * w))
            if share < 0.01 or not (m & edge).any():
                continue
            flat = float(rgb[m].std(axis=0).mean())     # заливка → разброс цвета почти нулевой
            if flat < 18 and share > plate:
                plate = share

    # текст: мелкие тёмные пятна, собранные в строки
    grey = rgb.mean(axis=2)
    dark = grey < (float(np.median(grey)) - 35)
    lab, n = ndimage.label(dark)
    rows = 0.0
    if n:
        sizes = np.bincount(lab.ravel())[1:]
        small = np.where((sizes > 4) & (sizes < 0.0016 * h * w))[0] + 1
        if len(small) > 12:
            ys = np.array([ndimage.center_of_mass(lab == i)[0] for i in small[:400]])
            hist, _ = np.histogram(ys, bins=max(6, h // 24), range=(0, h))
            rows = float((hist >= 4).sum())

    # плотность краёв — насколько «занят» весь кадр
    gy, gx = np.gradient(grey)
    edges = float((np.hypot(gx, gy) > 22).mean())

    return {'bg_spread': round(p99, 4), 'plate': round(plate, 4),
            'text_rows': rows, 'edges': round(edges, 4)}


def is_collage(rgb):
    """→ (вердикт, причины, признаки). Порог намеренно консервативный: лучше пропустить
    сомнительный коллаж в очередь, где его поймает гейт маски, чем выбросить живую карточку."""
    f = features(rgb)
    if f['bg_spread'] <= 0.12:
        return False, [], f     # ровный фон — это карточка, дальше можно не смотреть
    why = ['фон не ровный']
    if f['plate'] > 0.02:
        why.append('цветная плашка')
    if f['text_rows'] >= 3:
        why.append('текст строками')
    if f['edges'] > 0.10:
        why.append('кадр занят сценой')
    # Неровный фон сам по себе — это может быть честная интерьерная съёмка. Коллаж выдаёт
    # ВТОРОЙ признак: плашка, текст или забитый кадр.
    return (len(why) >= 2), why, f

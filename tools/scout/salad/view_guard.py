"""Сторож пустых видов покраски (план mesh-grey-top-01, T-20261118-04/13): без GPU, чистый numpy.

ЧТО ЛОМАЛОСЬ. Сеть видов Hunyuan3D 2.1 (paint) иногда отдаёт вид сверху (elev +90) ПУСТЫМ: тонкая кромка и серый фон
(128,128,128) там, где по рендеру геометрии крышка стола. `bake_from_multiview` (ревизия образа 82920d643c0d,
`hy3dpaint/utils/pipeline_utils.py`) доверие к пикселю считает по ГЕОМЕТРИИ (косинус нормали, видимость, граница) и НИКАК
не смотрит на картинку: серый вид «виден» → в маске UV крышка помечена увиденной → `texture_inpaint` её не трогает →
верх (128,128,128), MR 0,5/0,5. Лечение — выбросить такой вид из bake (и для альбедо, и для MR): тексели, которые
видел только он, станут невидимыми и дорисуются, а не останутся серыми.

КАК УЗНАЁМ. По каждому виду: силуэт — из карты нормалей рендера геометрии (фон белый), цвет фона — медиана ВНЕ силуэта
в самой картинке сети. Вид пуст, если внутри силуэта почти все пиксели совпадают с фоном (каждый канал в пределах
TOL), то есть сеть внутри предмета не нарисовала ничего. Настоящий серый материал так не совпадает: он затенён и
отличается от фона. Силуэт, занимающий почти весь кадр (фон не измерить), или совсем крошечный — не судим.
"""
import numpy as np
from PIL import Image, ImageFilter

TOL = 5                 # |пиксель − фон| по каждому каналу, уровней из 255
EMPTY_FRAC = 0.95       # доля пикселей силуэта «как фон», с которой вид считается пустым
MIN_INSIDE_FRAC = 0.004  # силуэт меньше 0,4 % кадра — не судим
MIN_OUTSIDE_FRAC = 0.03  # фона меньше 3 % кадра — не измерить, не судим
BG_MIN, BG_MAX = 112, 144  # фон видов сети — (128,128,128) ± шум; вне полосы эталон — сам серый пустого вида
EMPTY_GREY = (128, 128, 128)  # цвет, которым сеть закрашивает недорисованное
ERODE_PX = 3            # кромку силуэта отступаем: на границе цвета смешиваются с фоном


def silhouette(cond: Image.Image, size: tuple[int, int]) -> np.ndarray:
    """Карта нормалей рендера: фон белый (255,255,255); у единичной нормали такого цвета не бывает."""
    a = np.asarray(cond.convert('RGB').resize(size, Image.NEAREST)).astype(np.int16)
    return ~np.all(a >= 250, axis=-1)


def _morph(m: np.ndarray, r: int, grow: bool) -> np.ndarray:
    if r <= 0:
        return m
    f = ImageFilter.MaxFilter(2 * r + 1) if grow else ImageFilter.MinFilter(2 * r + 1)
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(f)) > 127


def judge(view: Image.Image, cond: Image.Image) -> dict:
    """Вердикт по одному виду: {'judged', 'empty', 'frac', 'bg', 'inside_px', 'reason'}."""
    rgb = np.asarray(view.convert('RGB')).astype(np.int16)
    h, w = rgb.shape[:2]
    sil = silhouette(cond, (w, h))
    inside = _morph(sil, ERODE_PX, grow=False)
    outside = ~_morph(sil, ERODE_PX + 1, grow=True)
    out = {'judged': False, 'empty': False, 'frac': None, 'bg': None, 'inside_px': int(inside.sum())}
    if inside.sum() < MIN_INSIDE_FRAC * h * w:
        out['reason'] = 'силуэт мал'
        return out
    if outside.sum() < MIN_OUTSIDE_FRAC * h * w:
        out['reason'] = 'фона нет'
        return out
    bg = np.median(rgb[outside], axis=0)
    if bg.min() < BG_MIN or bg.max() > BG_MAX:
        # Вокруг не серый фон (кадр залит корпусом, чёрные виды; 617634 на пробе 18.11: сеть дорисовала тёмные пятна ВНЕ
        # силуэта, а крышку внутри оставила пустой). Тогда «пустой» — только внутренность цвета пустого вида сети, 128:
        # светлый корпус и чёрный вид под это не попадают, ложных срабатываний нет.
        out['bg_other'] = [int(x) for x in bg]
        bg = np.array(EMPTY_GREY, dtype=float)
    near = np.all(np.abs(rgb[inside] - bg) <= TOL, axis=-1)
    frac = float(near.mean())
    out.update(judged=True, frac=round(frac, 4), bg=[int(x) for x in bg], empty=frac >= EMPTY_FRAC)
    return out


def judge_views(views, conds) -> list[dict]:
    """По списку видов (PIL) и такому же списку карт нормалей. Любой сбой одного вида — не судим (не выбрасываем)."""
    res = []
    for i, v in enumerate(views):
        try:
            r = judge(v, conds[i])
        except Exception as e:  # noqa: BLE001 — сторож не должен ронять покраску
            r = {'judged': False, 'empty': False, 'frac': None, 'bg': None, 'inside_px': 0,
                 'reason': f'{type(e).__name__}: {str(e)[:80]}'}
        r['view'] = i
        res.append(r)
    return res


def keep_lists(bad: set[int], n: int, *lists):
    """Списки bake без пустых видов. Если выбросить пришлось бы все виды или длины не сходятся — без изменений."""
    keep = [i for i in range(n) if i not in bad]
    if not bad or not keep or any(len(x) != n for x in lists):
        return lists
    return tuple([x[i] for i in keep] for x in lists)

#!/usr/bin/env python3
"""Подготовка ЦВЕТА фотографии перед покраской Hunyuan3D.

Зачем. Промптом покраске цвет не задать: `prompt` в `hy3dpaint/textureGenPipeline.py`
выбрасывается (UNet при `use_learned_text_clip=True` подставляет обученные токены), цвет
модель берёт ТОЛЬКО с референс-фото. Значит единственный рычаг — само фото.

Что мерили (01.09, 191 модель): врёт не оттенок, а СВЕТЛОТА — отклонение цветности
медиана 3/255, а по светлоте |ΔL|>40 у четверти моделей, в обе стороны (тёмно-серая
тумба вышла чёрной, серый комод — почти белым). Причина в том, что покраска сама
«снимает свет» с фотографии, а сколько там света — угадывает каждый раз заново.

Отсюда стратегия: отдать модели фотографию, с которой свет уже снят — тогда угадывать
почти нечего. Три шага, каждый обратим и виден глазами на странице «было/стало»:
  1) баланс белого по фону студии (фон-развёртка = бесплатный эталон белого);
  2) гашение бликов (глянцевый отлив читается моделью как «много света» → уводит в чёрный);
  3) снятие света: делим яркость на её же сильно размытую копию — уходит перепад
     освещения, фактура остаётся.
Шаг 4 (нормализация экспозиции к точке равновесия L≈145) — под флагом и ВЫКЛЮЧЕН:
он требует обратного умножения альбедо после генерации, иначе всё съедет в середину.

Ничего из этого не трогает готовый меш — это подготовка ВХОДА.
"""
import os

import numpy as np
from PIL import Image

# точка, в которой покраска ничего не сдвигает (замер 01.09 по 191 модели: альбедо ≈
# 0.69·фото + 48 → неподвижная точка L≈154 в атласе и ≈145 по рендерам)
PIVOT_L = 145.0


def _lab(rgb: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.cvtColor(rgb.astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)


def _rgb(lab: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.cvtColor(np.clip(lab, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)


def white_balance(rgb: np.ndarray, mask: np.ndarray,
                  source: Image.Image | None) -> tuple[np.ndarray, dict]:
    """Баланс белого по фону исходного фото.

    Фон каталожной съёмки — светлая развёртка, то есть эталон нейтрали, который достался
    нам даром. Если он уехал в тёплое/холодное, покраска честно скопирует этот завал в
    товар. Берём рамку по краю кадра (там заведомо фон), считаем поканальные
    коэффициенты до нейтрали и применяем к товару. Коэффициент ограничен ±12%: сильнее —
    значит это не фон-развёртка, а цветная сцена, и трогать нельзя.
    """
    if source is None:
        return rgb, {'wb': 'нет исходного фото'}
    a = np.asarray(source.convert('RGB')).astype(np.float32)
    h, w = a.shape[:2]
    b = max(4, int(min(h, w) * 0.04))
    frame = np.concatenate([a[:b].reshape(-1, 3), a[-b:].reshape(-1, 3),
                            a[:, :b].reshape(-1, 3), a[:, -b:].reshape(-1, 3)])
    med = np.median(frame, axis=0)
    if med.mean() < 200 or med.std() > 12:
        return rgb, {'wb': f'фон не белая развёртка (яркость {med.mean():.0f}, разброс {med.std():.1f})'}
    g = med.mean() / np.maximum(med, 1e-3)
    g = np.clip(g, 0.88, 1.12)
    out = np.clip(rgb * g[None, None, :], 0, 255)
    return out, {'wb': [round(float(x), 3) for x in g], 'wb_bg': [int(x) for x in med]}


def clip_specular(rgb: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, dict]:
    """Гашение бликов: верхушку светлоты поджимаем к 95-му процентилю.

    Именно отлив на тёмной матовой поверхности заставляет покраску решить «здесь много
    света» и увести фасад в чёрный (витрина 112923:4922… — графитовые дверцы стали
    чисто чёрными). Гасим только СВЕТ, цветность не трогаем.
    """
    lab = _lab(rgb)
    L = lab[..., 0]
    if mask.sum() < 200:
        return rgb, {'spec': 'мало пикселей'}
    p95, p99 = np.percentile(L[mask], 95), np.percentile(L[mask], 99)
    if p99 - p95 < 12:
        return rgb, {'spec': 'бликов нет'}
    hi = L > p95
    L[hi] = p95 + (L[hi] - p95) * 0.45          # мягкое колено, а не срез
    lab[..., 0] = L
    return _rgb(lab).astype(np.float32), {'spec': {'p95': round(float(p95), 1),
                                                   'p99': round(float(p99), 1),
                                                   'доля': round(float((hi & mask).mean()), 3)}}


def delight(rgb: np.ndarray, mask: np.ndarray, strength: float = 1.0) -> tuple[np.ndarray, dict]:
    """Снятие света: яркость делим на её же сильно размытую копию.

    Крупный градиент (одна сторона освещена, другая в тени) — это свет, а не цвет вещи.
    Размытие берём широкое (треть размера товара), поэтому фактура и рисунок остаются:
    делится только медленная составляющая. Правка ограничена коридором ×0.7…×1.5 —
    иначе глубокие складки выворачивает наизнанку.

    Размытие СЧИТАЕМ ТОЛЬКО ПО ТОВАРУ (нормализованная свёртка: размываем и яркость, и
    саму маску, потом делим). Иначе прозрачный фон затекает в края и по контуру появляется
    ложная «тень», которую мы бы тут же и «сняли».
    """
    import cv2
    lab = _lab(rgb)
    L = lab[..., 0]
    ys, xs = np.where(mask)
    if len(ys) < 200:
        return rgb, {'delight': 'мало пикселей'}
    size = max(np.ptp(ys), np.ptp(xs))     # np.ptp, а не .ptp(): в numpy 2 метод убрали
    sigma = max(6.0, size * 0.33)
    m = mask.astype(np.float32)
    num = cv2.GaussianBlur(L * m, (0, 0), sigma)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    field = num / np.maximum(den, 1e-3)
    base = float(np.median(L[mask]))
    ratio = np.clip(base / np.maximum(field, 1e-3), 0.7, 1.5)
    ratio = 1.0 + (ratio - 1.0) * float(strength)
    lab[..., 0] = np.clip(L * ratio, 0, 255)
    return _rgb(lab).astype(np.float32), {
        'delight': {'sigma': round(sigma, 1),
                    'разброс_света': round(float(np.percentile(field[mask], 90)
                                                 - np.percentile(field[mask], 10)), 1),
                    'правка_медиана': round(float(np.median(ratio[mask])), 3)}}


def set_exposure(rgb: np.ndarray, mask: np.ndarray,
                 target: float = PIVOT_L) -> tuple[np.ndarray, dict]:
    """Нормализация экспозиции к точке равновесия покраски. ПОД ФЛАГОМ.

    Возвращает и применённый коэффициент: без обратного умножения альбедо после
    генерации включать нельзя — иначе тёмное и светлое сойдутся в середину.
    """
    lab = _lab(rgb)
    med = float(np.median(lab[..., 0][mask]))
    k = float(np.clip(target / max(med, 1e-3), 0.6, 1.7))
    lab[..., 0] = np.clip(lab[..., 0] * k, 0, 255)
    return _rgb(lab).astype(np.float32), {'exposure': {'было': round(med, 1), 'k': round(k, 3)}}


def srgb_to_lin(x: np.ndarray) -> np.ndarray:
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(y: np.ndarray) -> np.ndarray:
    return np.where(y <= 0.0031308, y * 12.92, 1.055 * np.maximum(y, 0) ** (1 / 2.4) - 0.055)


def luminance(img: Image.Image) -> float:
    """Медианная ЛИНЕЙНАЯ яркость товара (по альфе). В стопах разница читается как log2."""
    a = np.asarray(img.convert('RGBA')).astype(np.float32)
    m = a[..., 3] > 128
    if m.sum() < 50:
        return 0.0
    lin = srgb_to_lin(a[..., :3][m] / 255.0)
    y = lin @ np.array([0.2126, 0.7152, 0.0722], np.float32)
    return float(np.median(y))


def shift_exposure(img: Image.Image, stops: float) -> tuple[Image.Image, dict]:
    """Сдвиг экспозиции входного фото на `stops` ступеней — в ЛИНЕЙНОМ RGB.

    Codex 01.09: множить яркость в sRGB или Lab — это не экспозиция; физически честно
    только в линейном пространстве. Света уводим мягким коленом, а не срезом: срезанное
    в белое обратно уже не достанешь, а именно светлые товары мы и просим темнее.

    Цель сдвига — НЕ сделать фото красивее. Фото намеренно уезжает от натурального вида,
    чтобы скомпенсировать systematic промах покраски; судить его надо по тому, не сломалось
    ли оно (нет выжженных пятен и увода цвета), а не по красоте.
    """
    a = np.asarray(img.convert('RGBA')).astype(np.float32)
    rgb, alpha = a[..., :3] / 255.0, a[..., 3:4]
    lin = srgb_to_lin(rgb) * (2.0 ** stops)
    knee = 0.8
    hi = lin > knee
    lin = np.where(hi, knee + (1 - knee) * np.tanh((lin - knee) / (1 - knee)), lin)
    out = np.clip(lin_to_srgb(lin), 0, 1) * 255.0
    m = alpha[..., 0] > 128
    return (Image.fromarray(np.dstack([out, alpha]).astype(np.uint8), 'RGBA'),
            {'stops': round(float(stops), 2),
             'в_колене': round(float(hi.any(axis=2)[m].mean()) if m.any() else 0.0, 3)})


def fix(img: Image.Image, source: Image.Image | None = None,
        expose: bool | None = None) -> tuple[Image.Image, dict]:
    """RGBA-вырезка → RGBA с подготовленным цветом + отчёт по шагам.

    Падать не имеет права: цвет — улучшение, а не условие задания. Любой сбой →
    возвращаем исходную картинку и пишем причину в отчёт.
    """
    try:
        im = img.convert('RGBA')
        arr = np.asarray(im).astype(np.float32)
        rgb, alpha = arr[..., :3], arr[..., 3]
        mask = alpha > 128
        if mask.sum() < 200:
            return img, {'skip': 'маска пустая'}
        rep = {}
        rgb, r = white_balance(rgb, mask, source); rep.update(r)
        rgb, r = clip_specular(rgb, mask); rep.update(r)
        rgb, r = delight(rgb, mask); rep.update(r)
        if expose if expose is not None else os.environ.get('PAINT_EXPOSURE') == '1':
            rgb, r = set_exposure(rgb, mask); rep.update(r)
        out = np.dstack([np.clip(rgb, 0, 255), alpha]).astype(np.uint8)
        return Image.fromarray(out, 'RGBA'), rep
    except Exception as e:  # noqa: BLE001 — вход важнее украшательства
        return img, {'error': f'{type(e).__name__}: {str(e)[:120]}'}

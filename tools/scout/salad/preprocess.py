"""Подготовка входного фото: вырезка фона локально, снятие каймы, белая подложка.

Раньше вырезку делал fal (`birefnet/v2`). fal из конвейера убран решением владельца, поэтому
BiRefNet едет в образе и считается на той же карте — это ноль дополнительных денег и минус
одна внешняя зависимость на каждое задание.

`defringe` и `trim_alpha` — портированы из `tools/scout/viz_paste.py` без изменений логики:
они чистые (numpy/PIL) и уже отлажены на нашем каталоге. Дублирование сознательное: контейнер
обязан быть самодостаточным, тянуть в него весь scout ради двух функций неразумно.
"""
import io
import os
import urllib.request

import numpy as np
import torch
from PIL import Image

import collage
import components
import hybrid_mask

# Версия оценщика: измерения кэшируются по (байты фото, версия). Меняешь цепочку вырезки или
# набор метрик — поднимай, иначе старые замеры выдадут себя за новые.
ASSESSOR_VERSION = 'a1'

_MODEL = None
_TF = None


def _birefnet():
    """Модель грузится один раз на процесс и остаётся в VRAM: она маленькая (~1 ГБ) рядом с
    Hunyuan, а перезагрузка на каждое задание съедала бы секунды на ровном месте."""
    global _MODEL, _TF
    if _MODEL is None:
        from torchvision import transforms
        from transformers import AutoModelForImageSegmentation
        path = os.path.join(os.environ.get('WEIGHTS_DIR', '/opt/weights'), 'birefnet')
        _MODEL = AutoModelForImageSegmentation.from_pretrained(path, trust_remote_code=True)
        _MODEL.to('cuda').eval().half()
        _TF = transforms.Compose([
            transforms.Resize((1024, 1024)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])
    return _MODEL, _TF


def fetch(url: str, timeout: int = 120) -> bytes:
    """Схема у ссылок каталога бывает опущена (`//imgng...`) — иначе urlopen падает."""
    if url.startswith('//'):
        url = 'https:' + url
    req = urllib.request.Request(url, headers={'User-Agent': 'remlab-mesh/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def cutout(img: Image.Image) -> Image.Image:
    model, tf = _birefnet()
    src = img.convert('RGB')
    with torch.no_grad():
        x = tf(src).unsqueeze(0).to('cuda').half()
        pred = model(x)[-1].sigmoid().cpu()[0].squeeze()
    mask = Image.fromarray((pred.numpy() * 255).astype(np.uint8)).resize(src.size)
    out = src.convert('RGBA')
    out.putalpha(mask)
    return out


def defringe(img: Image.Image) -> Image.Image:
    """Снимает светлую кайму: у полупрозрачных пикселей вычитаем подмешанный фон карточки.

    Иначе вместе с товаром уезжает белый ободок, и предмет выглядит наклеенным — а генератор
    честно превращает этот ободок в геометрию.
    """
    a = np.asarray(img).astype(np.float32)
    rgb, alpha = a[..., :3], a[..., 3:4] / 255.0
    corners = np.concatenate([a[:4, :4, :3].reshape(-1, 3), a[:4, -4:, :3].reshape(-1, 3),
                              a[-4:, :4, :3].reshape(-1, 3), a[-4:, -4:, :3].reshape(-1, 3)])
    bg = corners.mean(axis=0)
    soft = (alpha > 0.02) & (alpha < 0.98)
    fixed = np.where(soft, np.clip((rgb - bg * (1 - alpha)) / np.maximum(alpha, 0.02), 0, 255), rgb)
    return Image.fromarray(np.concatenate([fixed, alpha * 255], axis=2).astype(np.uint8), 'RGBA')


def trim_alpha(img: Image.Image, pad: int = 8) -> Image.Image:
    """Обрезка по непрозрачному: генератор тратит разрешение на поля, если их не убрать."""
    a = np.asarray(img)[..., 3]
    ys, xs = np.where(a > 8)
    if not len(ys):
        return img
    y0, y1 = max(0, ys.min() - pad), min(img.height, ys.max() + pad + 1)
    x0, x1 = max(0, xs.min() - pad), min(img.width, xs.max() + pad + 1)
    return img.crop((x0, y0, x1, y1))


def mask_verdict(cut: Image.Image) -> dict:
    """Проверка КАЖДОЙ вырезки перед тратой GPU.

    «Режем заново» не значит «режем хорошо»: сеть иногда не отделяет фон вовсе (тогда карточка
    целиком станет геометрией — коробка вместо стула) или, наоборот, стирает товар. Оба случая
    молча дают мусорный меш, и узнать об этом на приёмке — значит заплатить за генерацию зря.

    Меряем три вещи, каждая ловит свой отказ:
      * покрытие — доля непрозрачного. ~100% = фон не отделён, ~0% = товар стёрт;
      * касание рамки — доля непрозрачных пикселей по краю кадра. У вырезанного товара край
        пустой; заполненный край означает, что маска накрыла всю карточку;
      * средняя альфа полупрозрачных — если почти вся маска «мягкая», сеть не уверена нигде.
    """
    a = np.asarray(cut)[..., 3].astype(np.float32) / 255.0
    solid = a >= 0.5
    coverage = float(solid.mean())
    border = np.concatenate([solid[0], solid[-1], solid[:, 0], solid[:, -1]])
    border_share = float(border.mean())
    soft_share = float(((a > 0.05) & (a < 0.95)).sum()) / max(float((a > 0.05).sum()), 1.0)

    info = {'coverage': round(coverage, 3), 'border': round(border_share, 3),
            'soft_share': round(soft_share, 3), 'verdict': 'ok', 'reason': None}
    if coverage < 0.02:
        info.update(verdict='bad', reason='товар стёрт: непрозрачного почти нет')
    elif coverage > 0.97 or border_share > 0.6:
        info.update(verdict='bad', reason='фон не отделён: маска накрыла карточку целиком')
    elif border_share > 0.25:
        info.update(verdict='suspect', reason='маска заметно касается рамки кадра')
    elif soft_share > 0.5:
        info.update(verdict='suspect', reason='маска почти вся полупрозрачная')
    return info


class BadCutout(Exception):
    """Вырезка непригодна — генерацию не запускаем, деньги не тратим."""


def _paint_crop(rgba: Image.Image, margin: float = 0.18) -> Image.Image:
    """Кроп по товару с полем — для стадии ПОКРАСКИ.

    Форма и покраска ведут себя по-разному: `ImageProcessorV2.recenter()` перед формой сам
    кропает по альфе и добавляет поле, а `hy3dpaint` вход только ужимает до 512 и не центрирует.
    Значит покраске нужен уже кропнутый кадр, иначе половина её разрешения уходит на пустоту.
    """
    a = np.asarray(rgba)[..., 3]
    ys, xs = np.where(a > 8)
    if not len(ys):
        return rgba
    h, w = a.shape
    pad = int(max(ys.max() - ys.min(), xs.max() - xs.min()) * margin)
    box = (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad),
           min(w, int(xs.max()) + pad + 1), min(h, int(ys.max()) + pad + 1))
    crop = rgba.crop(box)
    # ПОДЛОЖКА — ДОМИНАНТНЫЙ ЦВЕТ ТОВАРА, не белая. Покраска не достаёт до складок и стыков
    # развёртки, и недокрашенные текселя остаются цвета подложки: на белой это крапинки
    # (диван 114667, владелец 30.08), на доминантной — сливаются с обивкой. Швы UV подтекают
    # тем же цветом. Профилактика причины; чистка текстуры остаётся страховкой.
    arr = np.asarray(crop).astype(np.float32)
    al = arr[..., 3:4] / 255.0
    opaque = arr[al[..., 0] > 0.6]
    dom = tuple(int(x) for x in np.median(opaque[:, :3], axis=0)) if len(opaque) else (255, 255, 255)
    bg = Image.new('RGBA', crop.size, dom + (255,))
    bg.alpha_composite(crop)
    return bg


def _cut_chain(image_url: str, role: str | None = None) -> tuple[Image.Image, Image.Image, str, dict]:
    """Общая часть: фото → (RGBA на полном холсте, обрезанная копия, хеш входа, отчёт).

    Вынесено из `prepare`, чтобы ТУ ЖЕ цепочку можно было прогнать в режиме оценки фото
    (`assess`) без генерации меша. Иначе, чтобы узнать «стоит ли делать меш», пришлось бы
    сначала оплатить меш — а именно этого мы и избегаем.

    **Контракт входа Hunyuan — RGBA, а не RGB на белом (ADR-0133).** Апстрим
    `hy3dshape/preprocessors.py::ImageProcessorV2.recenter()` берёт альфу как маску товара, а при
    RGB строит СИНТЕТИЧЕСКУЮ маску из одних 255: генератор считает объектом весь кадр, не
    центрирует товар и тратит mask-канал кондишенинга на пустое поле. Композит на белое здесь
    ровно и уничтожал маску; апстрим сам делает `αF+(1−α)white`, сохраняя альфу отдельно.
    Урок 149 («вход только на белом») касался `convert('RGB')`, из-за которого прозрачность
    становилась ЧЁРНОЙ и запекалась в текстуру, — честный RGBA этому не противоречит.

    `trim_alpha` для формы НЕ применяем: кроп и поле делает сам `recenter`, а наша обрезка по
    слабой альфе могла срезать проволоку, после чего апстрим кропал уже испорченный кадр второй
    раз (двойной кроп). Обрезанная копия остаётся только для просмотра человеком.

    Вырезку с альфой возвращаем ИЗ ЭТОГО ЖЕ прохода, а не режем повторно: второй проход стоил
    бы ещё одного прогона сети и мог бы дать другую маску — тогда владелец смотрел бы не на то,
    что реально ушло в генератор.

    Хеш считается по ИСХОДНЫМ байтам, а не по результату вырезки: вырезка детерминирована при
    фиксированных весах, а исходник — то, что реально задаёт задание.

    ГИБРИД ОБЯЗАТЕЛЕН, а не «улучшение по возможности»: вырезка — вход генератора, срезанное
    с фото не появится в меше. Замер 28.08 на 36 товарах: чистая сеть держит 79% деталей
    толщиной 1–2 px, гибрид — 95%; потери от эталонной маски падают с 2.90% до 1.56%.
    """
    import hashlib
    raw = fetch(image_url)
    input_hash = hashlib.sha256(raw).hexdigest()[:16]
    src = Image.open(io.BytesIO(raw)).convert('RGB')
    net = cutout(src)
    full_wh = list(src.size)
    try:
        refined, mask_info = hybrid_mask.refine(src, net, role=role)
    except Exception as e:  # noqa: BLE001 — гибрид не должен ронять задание; факт отказа виден
        refined, mask_info = net, {'hybrid_error': f'{type(e).__name__}: {str(e)[:120]}'}

    # Обрывок фона (плашка баннера, ватермарка) для картинки — косметика, для генератора —
    # геометрия из ниоткуда: он честно строит по маске. Поймано владельцем на стуле Wishbone.
    a = np.asarray(refined)[..., 3].astype(np.float32) / 255.0
    cleaned, comp = components.clean(a)
    cleaned, holes = components.fill_holes_unlike_bg(cleaned, np.asarray(src), role=role)
    comp.update(holes)
    mask_info['components'] = comp
    refined = Image.fromarray(
        np.dstack([np.asarray(refined)[..., :3],
                   (np.clip(cleaned, 0, 1) * 255).astype(np.uint8)]), 'RGBA')

    # Коллаж вычисткой не лечится: в кадре плашка, свойства текстом, интерьерная сцена и нередко
    # ВТОРАЯ копия товара. Проверяем только здесь — детектору нужна настоящая маска, без неё
    # фактура самого товара читается как текст.
    is_col, why, feats = collage.is_collage(np.asarray(src).astype(np.float32), cleaned)
    mask_info['collage'] = {'verdict': bool(is_col), 'why': why, 'features': feats}

    shape_img = defringe(refined)            # полный холст: кроп и поле сделает recenter
    cut = trim_alpha(shape_img)              # обрезанная копия — человеку на просмотр
    mask_info.update(mask_verdict(cut))
    if is_col:
        mask_info.update(verdict='bad', reason='фото-коллаж: ' + ', '.join(why))
    # Размеры нужны политике пригодности: жёсткие ворота по ширине кадра выкосили бы весь пул
    # (все фото фида 450 px), а вот КАКУЮ ДОЛЮ кадра занимает товар — различает карточку и баннер.
    mask_info['photo'] = {
        'frame_wh': full_wh, 'object_wh': list(cut.size),
        'object_share': round(float(cut.size[0] * cut.size[1]) / max(full_wh[0] * full_wh[1], 1), 4),
        # Длинная сторона относительно длинной стороны кадра. Короткая сторона мерой быть не
        # может: у торшера и стеллажа она мала по природе предмета, а не из-за плохого кадра.
        'object_rel_side': round(float(max(cut.size)) / max(max(full_wh), 1), 3),
        'object_min_side': int(min(cut.size)),
    }
    return shape_img, cut, input_hash, mask_info


def assess(image_url: str, role: str | None = None) -> tuple[str, dict]:
    """Оценка пригодности фото БЕЗ генерации: хеш входа + все измерения и вердикт.

    Не бросает на браке — брак и есть результат оценки.
    """
    _, _, input_hash, info = _cut_chain(image_url, role=role)
    return input_hash, info


def prepare(image_url: str, role: str | None = None) -> tuple[Image.Image, Image.Image, Image.Image, str, dict]:
    """Фото → (RGBA для формы, RGBA для покраски, вырезка на просмотр, хеш входа, отчёт)."""
    shape_img, cut, input_hash, mask_info = _cut_chain(image_url, role=role)
    if mask_info['verdict'] == 'bad':
        # Останавливаемся ДО генерации: мусорный вход даёт мусорный меш, а платим одинаково.
        raise BadCutout(mask_info['reason'])
    return shape_img, _paint_crop(shape_img), cut, input_hash, mask_info

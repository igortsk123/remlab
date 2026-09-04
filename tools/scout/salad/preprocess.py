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


# Кэш последних ответов по URL (04.09): фото качалось ДВАЖДЫ на задание (`prepare` и
# `source.jpg` в воркере) — вторая закачка идёт отсюда, без сети, теми же байтами (идентичность
# входа: sha считается от того, что реально пошло в генератор).
import collections as _collections
_FETCHED: "_collections.OrderedDict[str, bytes]" = _collections.OrderedDict()
_FETCH_CACHE_N = 4
# Повторы (04.09): за сутки 03.09 — 27 отказов «network unreachable», 10 таймаутов, 6 SSL EOF на
# ВХОДЕ, и каждый ронял задание без единой повторной попытки. 404/410 НЕ повторяем — сервер
# ответил, фото мёртвое, повтор только жжёт время ноды.
FETCH_RETRIES = (2, 5, 10)
_UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) '
       'Chrome/126.0 Safari/537.36')


def fetch(url: str, timeout: int = 120) -> bytes:
    """Схема у ссылок каталога бывает опущена (`//imgng...`) — иначе urlopen падает.
    Повторы с паузами 2/5/10 с на сетевых сбоях; 404/410 — сразу наверх (вина товара)."""
    import time as _time
    import urllib.error as _ue
    if url.startswith('//'):
        url = 'https:' + url
    if url in _FETCHED:
        _FETCHED.move_to_end(url)
        return _FETCHED[url]
    last: Exception | None = None
    for i, pause in enumerate((0,) + FETCH_RETRIES):
        if pause:
            _time.sleep(pause)
        try:
            req = urllib.request.Request(url, headers={'User-Agent': _UA, 'Accept': 'image/*,*/*;q=0.8'})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if not data:
                raise ValueError('пустой ответ')
            _FETCHED[url] = data
            while len(_FETCHED) > _FETCH_CACHE_N:
                _FETCHED.popitem(last=False)
            return data
        except _ue.HTTPError as e:
            if e.code in (404, 410, 403):          # сервер ответил: фото мёртвое/закрыто — не повторяем
                raise
            last = e
        except Exception as e:  # noqa: BLE001 — сеть, TLS, таймаут: повтор
            last = e
    raise last  # type: ignore[misc]


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


# Гейт вырезки БРАКОВАЛ товар до генерации. Владелец 01.09 запретил отдавать это решение
# скрипту — по умолчанию только диагностика. CUTOUT_GATE=1 возвращает блокировку.
CUTOUT_GATE = os.environ.get('CUTOUT_GATE', '0') == '1'


class BadCutout(Exception):
    """Вырезка непригодна — генерацию не запускаем, деньги не тратим."""


def _pick_main_object(cut: Image.Image) -> tuple[Image.Image, dict]:
    """Карточки часто показывают ПАРУ одинаковых предметов (стулья). Меш нужен ОДНОМУ.

    Признак пары: два крупных компонента маски сопоставимой площади (меньший ≥40% большего),
    их bbox-ы почти не пересекаются по X. Оставляем БОЛЬШИЙ (обычно передний). Порог
    сознательно строгий: диван из-за просветов не должен резаться пополам — его куски
    пересекаются по X или сильно различаются площадью.
    """
    from scipy import ndimage
    a = np.asarray(cut)[..., 3] > 40
    lab, n = ndimage.label(a)
    if n < 2:
        return cut, {}
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    order = np.argsort(sizes)[::-1]
    if len(order) < 2 or sizes[order[1]] < 0.40 * sizes[order[0]]:
        return cut, {}
    boxes = ndimage.find_objects(lab)
    b1, b2 = boxes[order[0]], boxes[order[1]]
    x1a, x1b = b1[1].start, b1[1].stop
    x2a, x2b = b2[1].start, b2[1].stop
    overlap = max(0, min(x1b, x2b) - max(x1a, x2a)) / max(1, min(x1b - x1a, x2b - x2a))
    if overlap > 0.25:
        return cut, {}
    keep = int(order[0]) + 1
    arr = np.asarray(cut).copy()
    arr[..., 3] = np.where(lab == keep, arr[..., 3], 0)
    return Image.fromarray(arr, 'RGBA'), {'dual_object_trimmed': True,
                                          'second_share': round(float(sizes[order[1]] / sizes[order[0]]), 2)}


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
    # ПОД ФЛАГОМ (Codex q26): официальная покраска сама композитит RGBA на белый, наша
    # непрозрачная цветная подложка обходит эту нормализацию и может сдвинуть цвет всего
    # товара. До paint-A/B (white vs dominant, ΔE к фото, крапинки) — дефолт белый.
    if os.environ.get('PAINT_BG', 'white') == 'dominant':
        arr = np.asarray(crop).astype(np.float32)
        al = arr[..., 3:4] / 255.0
        opaque = arr[al[..., 0] > 0.6]
        dom = tuple(int(x) for x in np.median(opaque[:, :3], axis=0)) if len(opaque) else (255, 255, 255)
        bg = Image.new('RGBA', crop.size, dom + (255,))
        bg.alpha_composite(crop)
        return bg
    return crop


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
    # хвосты, прилипшие тонкой перемычкой (артефакт у пола → обломок-призрак в меше);
    # внутри белый список массивных ролей и нижняя зона — люстры/тонкое не трогаются
    cleaned, att = components.prune_attached(cleaned, role=role)
    comp.update(att)
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
    # Пары «два предмета в кадре»: срез второго одобрен владельцем ТОЛЬКО для стульев
    # (30.08, после проверки /test/pair-fix/); прочим ролям детектор не доверяем
    # (самовольный кроп люстры). До 30.08 здесь была NameError: вызов детектора потерялся
    # при коммите, и свежие ноды валили КАЖДОЕ задание в input_failed.
    dual = {}
    if (role or '').split()[0:1] == ['стул']:
        shape_img, dual = _pick_main_object(shape_img)
    cut = trim_alpha(shape_img)              # обрезанная копия — человеку на просмотр
    mask_info.update(dual)
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
        # РЕШЕНИЕ ВЛАДЕЛЬЦА 01.09: не блокируем. Он посмотрел вырезку стола из коллажа
        # («тут только кусок стола остался — пусть модель делает такое») и постановил
        # генерировать, а происхождение из коллажа ПОМЕЧАТЬ в базе, чтобы потом отсортировать.
        # Вернуть прежнее поведение: CUTOUT_GATE=1 в окружении воркера.
        if CUTOUT_GATE:
            raise BadCutout(mask_info['reason'])
        print(f'диагноз вырезки (не блокирует): {mask_info["reason"]}', flush=True)
    return shape_img, _paint_crop(shape_img), cut, input_hash, mask_info

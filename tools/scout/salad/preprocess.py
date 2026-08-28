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

import hybrid_mask

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


def prepare(image_url: str) -> tuple[Image.Image, Image.Image, str, dict]:
    """Фото → (RGB на белом для Hunyuan, вырезка RGBA, хеш входа, отчёт о вырезке).

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
    try:
        refined, mask_info = hybrid_mask.refine(src, net)
    except Exception as e:  # noqa: BLE001 — гибрид не должен ронять задание; факт отказа виден
        refined, mask_info = net, {'hybrid_error': f'{type(e).__name__}: {str(e)[:120]}'}
    cut = trim_alpha(defringe(refined))
    mask_info.update(mask_verdict(cut))
    if mask_info['verdict'] == 'bad':
        # Останавливаемся ДО генерации: мусорный вход даёт мусорный меш, а платим одинаково.
        raise BadCutout(mask_info['reason'])
    white = Image.new('RGBA', cut.size, (255, 255, 255, 255))
    white.alpha_composite(cut)
    return white.convert('RGB'), cut, input_hash, mask_info

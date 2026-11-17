"""Общая заготовка тестов тарифа фото (T-20261117-03, план photo-tariff-mass-01): заказ автофото тура в виде, как его шлёт приложение (комната,
камеры, предметы, декор, два кадра из 3D), и сборка входов платного вызова `improve_mode.build_from_views` БЕЗ сети: кадры и фото товаров —
синтетические (цвет по хешу ссылки), публикация исходников — пустая. Тесты берут отсюда `payload()` и `build()`; ID сцен реальных туров не используются."""
import hashlib
import io
import os
import sys
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..'))
sys.path.insert(0, os.path.join(HERE, '..', '..', '..', 'services', 'planner-solver'))
from PIL import Image  # noqa: E402

import draft_render as DR  # noqa: E402
import improve_mode as IM  # noqa: E402

FRAME_IDS = ('a' * 64, 'b' * 64)


def _colour(key: str) -> tuple:
    h = hashlib.md5(key.encode()).digest()
    return (60 + h[0] % 150, 60 + h[1] % 150, 60 + h[2] % 150)


def fake_photo(url):
    """Фото товара: однотонная карточка 600×600 с полосой — цвет по ссылке, без сети."""
    if not url:
        return None
    im = Image.new('RGB', (600, 600), _colour(url))
    im.paste(Image.new('RGB', (600, 120), _colour(url + 'x')), (0, 240))
    return im


def fake_frame(fid: str) -> Image.Image:
    """Кадр из 3D: 2048×1489, как у страницы (ширина 2048); у C1 и C2 свой цвет."""
    return Image.new('RGB', (2048, 1489), _colour(fid))


def payload(with_decor: bool = True, window: bool = True, art_in_scene: bool = False) -> dict:
    """Гостиная с диваном, столиком, ТВ; два кадра; камеры C1 (взгляд на север) и C2 (взгляд на восток); окно на западной стене."""
    ops = [{'kind': 'door', 'wall': 'east', 'offset_cm': 120, 'width_cm': 90, 'swing_cm': 90, 'hinge': 'left'}]
    if window:
        ops.append({'kind': 'window', 'wall': 'west', 'offset_cm': 60, 'width_cm': 150, 'sill_cm': 85, 'height_cm': 150})
    items = [
        {'role': 'диван', 'name': 'Диван тестовый серый', 'img': 'https://x.test/sofa.jpg', 'x': 220, 'y': 300, 'rot': 180, 'w': 220, 'd': 95},
        {'role': 'столик', 'name': 'Столик тестовый дуб', 'img': 'https://x.test/table.jpg', 'x': 220, 'y': 190, 'rot': 0, 'w': 90, 'd': 50},
        {'role': 'тв', 'name': 'ТВ-тумба тестовая', 'img': 'https://x.test/tv.jpg', 'x': 220, 'y': 20, 'rot': 0, 'w': 150, 'd': 40},
    ]
    decor = []
    if with_decor:
        decor = [
            {'role': 'картина', 'strategy': 'procedural_plane', 'shown': art_in_scene, 'sku': {'name': 'Картина тестовая', 'img': 'https://x.test/art.jpg'}},
            {'role': 'плед', 'strategy': 'textile_abstract', 'shown': False,
             'place': {'kind': 'throw', 'parent': 'seat.sofa#0', 'edge': 'arm', 'elev_cm': 48},
             'look': {'hex': '#cdb89a', 'from': 'name:бежевый', 'sheer': False},
             'sku': {'name': 'Плед тестовый бежевый', 'img': 'https://x.test/throw.jpg'}},
        ]
    return {'room': {'w': 440, 'd': 330, 'kind': 'living', 'title': 'Гостиная тестовая', 'openings': ops},
            'cams': [{'name': 'C1', 'x': 380, 'y': 20, 'rot': 330, 'fov': 90}, {'name': 'C2', 'x': 40, 'y': 200, 'rot': 90, 'fov': 90}],
            'style': 'сканди', 'items': items, 'decor': decor, 'decor_known': True,
            'views': [{'camera': 'C1', 'id': FRAME_IDS[0]}, {'camera': 'C2', 'id': FRAME_IDS[1]}], 'trial': 'T' * 22}


def build(pl: dict | None = None, **kw) -> dict:
    """Входы платного вызова без сети: `build_from_views(pl, style, **kw)`."""
    pl = pl or payload()
    with mock.patch.object(IM, 'load_frame', fake_frame), mock.patch.object(DR, 'photo', fake_photo), \
            mock.patch.object(DR, '_publish_sources', lambda *a, **k: None):
        return IM.build_from_views(pl, pl.get('style') or '', **kw)


def inputs_of(built: dict) -> list:
    """Картинки, что уйдут в `gpt_edit`, в том же порядке и по тому же правилу, что в `draft_render.render`."""
    sheet, ident = built['sheet'], built.get('ident')
    imgs = [sheet] + ([ident] if ident is not None else [])
    if built.get('dsheet') is not None and 'IMAGE 3' in built['prompt']:
        imgs = [sheet, ident if ident is not None else Image.new('RGB', (64, 64), (255, 255, 255)), built['dsheet']]
    return imgs


def png_sha(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.convert('RGB').save(buf, 'PNG')              # как `gpt_edit`: вход уходит PNG
    return hashlib.sha256(buf.getvalue()).hexdigest()[:20]


def fingerprint(built: dict) -> dict:
    """Что нужно знать о входах: отпечаток текста, размеры и отпечатки PNG-входов."""
    imgs = inputs_of(built)
    return {'prompt_sha': hashlib.sha256(built['prompt'].encode()).hexdigest()[:20], 'prompt_len': len(built['prompt']),
            'sizes': [list(im.size) for im in imgs], 'png': [png_sha(im) for im in imgs], 'size': built['size']}

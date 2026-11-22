"""Общие настройки кадра, которые читают и выгрузчик сцены (`cycles_probe/export_scene.py`), и платное «Улучшить» (`improve_mode.py`).
Отдельный маленький модуль без зависимостей (T-20261119-100/2, план `render-key-01`): выгрузчик сцены раньше брал размер из `improve_mode` и тащил за ним ленту, цены, банк и каталог
в `renderer_digest`. Теперь размер кадра живёт здесь; `improve_mode.SIZE` берёт его отсюда (значение и поведение «Улучшить» те же), а значение попадает в ключ кадра
(`render_input.renderer_parts['frame_size']`)."""
import os

SIZE_ENV = 'IMPROVE_SIZE'
DEFAULT_SIZE = '2048x3072'     # замер: принимается шлюзом


def frame_size() -> str:
    """Размер кадра `<ширина>x<высота_всего>`: из `IMPROVE_SIZE`, иначе по умолчанию. Читает окружение при каждом вызове (ключ кадра и выгрузчик видят одно и то же значение)."""
    return os.environ.get(SIZE_ENV, DEFAULT_SIZE)


def frame_wh(size: str | None = None) -> tuple:
    """(ширина, высота_всего) из строки размера."""
    w, h = (int(x) for x in (size or frame_size()).split('x'))
    return w, h

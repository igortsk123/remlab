#!/usr/bin/env python3
"""Кэш 3D-моделей товаров: фото карточки → GLB, один раз на товар.

Модель делается для тех предметов, кому плоское фото врёт (`mesh_need.py`). Файл кладётся рядом
со сценами под именем товара, поэтому второй комплект с тем же диваном ничего не стоит.

ВАЖНО: вход генератора — на БЕЛОМ фоне. Прозрачную вырезку при переводе в RGB библиотека делает
чёрной, и генератор запекает черноту в текстуру (урок 149).

  ~/venvs/scout/bin/python mesh_make.py 21 --roles столик,пуф,кашпо
"""
import os
import re
import sys
import time
import urllib.request

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
SCENE_DIR = os.environ.get('SCENE_DIR', os.path.expanduser('~/scout-scenes'))
MESH_DIR = os.path.join(SCENE_DIR, 'meshes')
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '../../services/planner-solver'))

from viz_base import fal_key, fal_run, uri_from_image  # noqa: E402
from viz_objects import product  # noqa: E402
from viz_paste import cutout, trim_alpha  # noqa: E402


def mesh_path(it: dict) -> str:
    """Имя файла — по товару, а не по комплекту: модель переиспользуется во всех сценах."""
    k = re.sub(r'[^A-Za-z0-9]', '_', f"{it.get('mid', '?')}-{it.get('eid', '?')}")[:60]
    return os.path.join(MESH_DIR, f'{k}.glb')


def ensure_mesh(n: int, role: str, key: str | None = None) -> str | None:
    """GLB товара: из кэша или сгенерировать. None — если фото нет."""
    os.makedirs(MESH_DIR, exist_ok=True)
    it, photo = product(n, role)
    dst = mesh_path(it)
    if os.path.exists(dst):
        return dst
    if not os.path.exists(photo):
        return None
    cut = trim_alpha(cutout(photo))
    white = Image.new('RGBA', cut.size, (255, 255, 255, 255))
    white.alpha_composite(cut)
    t0 = time.time()
    res = fal_run('fal-ai/trellis', {'image_url': uri_from_image(white.convert('RGB'))},
                  key or fal_key(), timeout=900)
    url = (res.get('model_mesh') or {}).get('url')
    if not url:
        return None
    # Скачиваем через временный файл: оборванная закачка иначе оставляет в кэше пустой GLB,
    # и все следующие прогоны честно берут из кэша битую модель.
    with urllib.request.urlopen(url, timeout=600) as r:
        open(dst + '.tmp', 'wb').write(r.read())
    os.replace(dst + '.tmp', dst)
    print(f'{role}: модель за {time.time() - t0:.0f} с → {dst}', flush=True)
    return dst


def main() -> None:
    n = int(sys.argv[1])
    roles = sys.argv[sys.argv.index('--roles') + 1].split(',') if '--roles' in sys.argv else []
    key = fal_key()
    for role in roles:
        try:
            p = ensure_mesh(n, role, key)
            print(f'{role}: {p or "нет фото"}', flush=True)
        except Exception as e:  # noqa: BLE001 — один сбойный товар не должен ронять пакет
            print(f'{role}: ошибка {str(e)[:120]}', flush=True)


if __name__ == '__main__':
    main()

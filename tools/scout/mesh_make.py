#!/usr/bin/env python3
"""Кэш 3D-моделей товаров: фото карточки → GLB, один раз на товар.

Модель делается для тех предметов, кому плоское фото врёт (`mesh_need.py`). Файл кладётся рядом
со сценами под именем товара, поэтому второй комплект с тем же диваном ничего не стоит.

ВАЖНО: вход генератора — на БЕЛОМ фоне. Прозрачную вырезку при переводе в RGB библиотека делает
чёрной, и генератор запекает черноту в текстуру (урок 149).

  ~/venvs/scout/bin/python mesh_make.py 21 --roles столик,пуф,кашпо
"""
import json
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


def mesh_trusted(path: str, photo: str, min_iou: float = 0.6) -> bool:
    """Модель обязана совпасть с карточкой, из которой сделана — иначе она бракованная.

    Проверка без человека: рендерим модель В ТОМ ЖЕ ракурсе, что и фото (разворот 0), и сравниваем
    силуэты. У люстры генератор слепил рожки в мятую железку — силуэт разошёлся, и такую модель
    подставлять нельзя (владелец, 2026-08-05). Вердикт кэшируется рядом с моделью.
    """
    import numpy as np
    from PIL import Image

    verdict = os.path.splitext(path)[0] + '-check.json'
    # ВЕРДИКТ НЕ ПЕРЕЖИВАЕТ ЗАМЕНУ МОДЕЛИ (q21/q22, 28.08): Hunyuan-фолбэк копировался поверх
    # GLB, а старый отрицательный check.json оставался — mesh_trusted() вечно возвращал false.
    if os.path.exists(verdict) and os.path.getmtime(verdict) < os.path.getmtime(path):
        os.remove(verdict)
    if os.path.exists(verdict):
        try:
            return bool(json.load(open(verdict))['ok'])
        except Exception:  # noqa: BLE001 — битый вердикт пересчитаем
            pass
    from mesh_render import load_parts, render
    from viz_paste import cutout, trim_alpha
    parts = load_parts(path)
    card = trim_alpha(cutout(photo))
    size = (256, 256)
    b = np.asarray(card.resize(size, Image.LANCZOS))[..., 3] > 90
    # Карточку снимают не строго в лоб, а «в три четверти» и чуть сверху (замер магазинов —
    # `measure_angle.py`). Поэтому ищем ЛУЧШЕЕ совпадение по нескольким правдоподобным ракурсам:
    # иначе честная модель проваливает проверку из-за чужого угла съёмки.
    iou = 0.0
    for yaw in (0.0, -20.0, 20.0):
        for pitch in (0.0, 12.0, 22.0):
            shot = trim_alpha(render(parts, yaw, pitch, size=(500, 500)))
            a = np.asarray(shot.resize(size, Image.LANCZOS))[..., 3] > 90
            union = float((a | b).sum())
            iou = max(iou, float((a & b).sum()) / union if union else 0.0)
    # ЦВЕТ ТОЖЕ СВЕРЯЕМ. Силуэт может совпасть, а текстура выйти чёрной — так диван с белой
    # обивкой приехал в кадр с чёрной спинкой и прошёл проверку на 88% (владелец, 2026-08-05).
    shot = trim_alpha(render(parts, 0.0, 12.0, size=(500, 500)))
    sa = np.asarray(shot.resize(size, Image.LANCZOS))
    ca = np.asarray(card.resize(size, Image.LANCZOS))
    sm = sa[..., 3] > 90
    cm = ca[..., 3] > 90 if ca.shape[2] > 3 else np.ones(size, bool)
    if sm.sum() > 50 and cm.sum() > 50:
        dcol = float(np.linalg.norm(sa[..., :3][sm].mean(axis=0) - ca[..., :3][cm].mean(axis=0)))
    else:
        dcol = 0.0
    ok = iou >= min_iou and dcol <= 55.0
    json.dump({'iou': round(iou, 3), 'colour_dist': round(dcol, 1), 'ok': ok, 'min_iou': min_iou},
              open(verdict, 'w'), ensure_ascii=False)
    print(f'  самопроверка модели {os.path.basename(path)}: силуэт {iou:.0%}, расхождение цвета '
          f'{dcol:.0f} → {"годится" if ok else "брак, работаем по фото"}', flush=True)
    return ok


def ensure_mesh(n: int, role: str, key: str | None = None, model: str = 'fal-ai/trellis') -> str | None:
    """GLB товара: из кэша или сгенерировать. None — если фото нет.

    `model` — генератор: дефолт Trellis; фолбэк — Hunyuan3D (А6: хвост брака приёмки — это
    в основном роли, где Trellis-меш не проходит самопроверку; по сверке с рынком 2026-08
    Hunyuan3D точнее на мебели). Кэш — на пару (товар, генератор).
    """
    os.makedirs(MESH_DIR, exist_ok=True)
    it, photo = product(n, role)
    dst = mesh_path(it)
    if model != 'fal-ai/trellis':
        dst = dst[:-4] + '-' + re.sub(r'[^a-z0-9]+', '_', model) + '.glb'
    if os.path.exists(dst):
        return dst
    if not os.path.exists(photo):
        return None
    cut = trim_alpha(cutout(photo))
    white = Image.new('RGBA', cut.size, (255, 255, 255, 255))
    white.alpha_composite(cut)
    t0 = time.time()
    uri = uri_from_image(white.convert('RGB'))
    payload = ({'image_url': uri} if model == 'fal-ai/trellis'
               else {'input_image_url': uri, 'textured_mesh': True})
    res = fal_run(model, payload, key or fal_key(), timeout=900)
    url = ((res.get('model_mesh') or {}).get('url')
           or (res.get('model_glb') or {}).get('url')
           or (res.get('model_glb_pbr') or {}).get('url'))
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

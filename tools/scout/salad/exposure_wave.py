#!/usr/bin/env python3
"""Волна опыта с экспозицией: готовит сдвинутые фото и файл заданий для генератора.

Почему через ФОТО, а не через настройку ноды. Перепокраска готовой формы дешевле, но
требует пересборки образа (новый эндпоинт воркера). Опыт «реагирует ли покраска на
экспозицию входа» можно поставить сегодня и без неё: подаём генератору то же фото со
сдвинутой экспозицией товара, на белом фоне — обычная карточка, только светлее/темнее.
Плата за скорость — заново считается и форма (189 с против 79 с), и геометрия может
слегка разойтись; если приём сработает, дальше делаем правильный путь — перепокраску.

Сдвиг берём из `exposure_plan.json` (замер: рендер без света против фото, потолок 0.45
по решению владельца). Фото публикуются на наш же сайт, потому что нода скачивает вход
по URL и никакого другого канала передачи картинки у неё нет.

  ~/venvs/scout/bin/python exposure_wave.py            # готовит фото + jobs-файл
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.expanduser('~/scout-scenes/mesh-color/ev')
BASE = 'https://remont-lab.online/test/mesh-color/ev'
JOBS = os.path.join(HERE, '..', 'mesh-exposure-jobs.json')


def main() -> None:
    import numpy as np
    from PIL import Image
    import photo_color as PC
    from color_test_page import newest_dirs, read_marks
    plan = json.load(open(os.path.join(HERE, 'exposure_plan.json'), encoding='utf-8'))
    # «переделать» — брак формы (приросшая плита), к цвету отношения не имеет: в цветовой
    # опыт не берём, иначе непонятно, что мы вообще проверяем.
    marks = read_marks(sys.argv[1] if len(sys.argv) > 1 else None)
    best = newest_dirs()
    os.makedirs(OUT, exist_ok=True)
    jobs, skipped = [], []
    for sku, p in plan.items():
        if marks.get(sku) == 'redo':
            skipped.append(sku)
            continue
        stops = float(p.get('stops') or 0.0)
        if abs(stops) < 0.05:
            skipped.append(sku)            # сдвигать нечего — задание не тратим
            continue
        d, man = best.get(sku, (None, None))
        if not d:
            continue
        shifted, _ = PC.shift_exposure(Image.open(os.path.join(d, 'cutout.png')), stops)
        # На БЕЛОЕ, а не с альфой: нода скачает картинку и сама снимет фон. PNG с
        # прозрачностью она бы превратила в RGB с ЧЁРНЫМ фоном (урок 149) — и запекла
        # чёрный в текстуру, то есть опыт про светлоту сломался бы на ровном месте.
        a = np.asarray(shifted).astype(np.float32)
        al = a[..., 3:4] / 255.0
        rgb = a[..., :3] * al + 255.0 * (1 - al)
        name = f"{sku.replace(':', '_')}.jpg"
        Image.fromarray(rgb.astype('uint8'), 'RGB').save(os.path.join(OUT, name), quality=95)
        inp = man.get('input') or {}
        jobs.append({'sku': sku, 'role': man.get('role'), 'image_url': f'{BASE}/{name}',
                     'dims_cm': inp.get('dims_cm'), 'seed': int(man.get('seed') or 0),
                     'params': {}, 'ev_stops': stops})
    json.dump(jobs, open(JOBS, 'w'), ensure_ascii=False, indent=1)
    print(f'заданий: {len(jobs)} (без сдвига пропущено {len(skipped)}) → {JOBS}')
    print(f'фото: {OUT} → публиковать на {BASE}/')


if __name__ == '__main__':
    main()

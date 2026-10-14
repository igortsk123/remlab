#!/usr/bin/env python3
"""НАБОР «ВИД ИЗ ОКНА» ПО УМОЛЧАНИЮ (план demo-04 п.5): город днём и вечером, двор, парк.

Застройщик может дать свой вид (с этажа, по сторонам света); пока его нет — эти картинки. Делаем их сами генерацией
(fal, flux): чужих прав в них нет, стоят доли цента. Правило «сначала проба» (урок про платное): `--only city-day` —
одна картинка, смотрим глазами, потом остальные. Каждая неудача считается и печатается; молча не глотаем.

Картинка — фото «за стеклом» для квартиры на 5–9 этаже: горизонт посередине кадра, без рамы окна, подоконника, людей
крупно и текста. Сохраняется в `public/scene/views/<id>.webp` (1600×1067, ~150 КБ).

  ~/venvs/scout/bin/python tools/scene/window_views.py --only city-day
  ~/venvs/scout/bin/python tools/scene/window_views.py            # все, кроме уже готовых
"""
from __future__ import annotations

import io
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools', 'scout'))

from falmini import fal_key, fal_run  # noqa: E402
from PIL import Image  # noqa: E402

OUT = os.path.join(ROOT, 'public', 'scene', 'views')
MODEL = 'fal-ai/flux/dev'
# слово «окно» в описании рисует раму по краям (проба 14.10) — описываем сам вид с высоты 7 этажа, лето и зелень
BASE = ('wide landscape photograph of a city view from the height of a 7th floor, camera level, horizon in the middle of '
        'the frame, full frame scene edge to edge, summer, lush green trees, sunny, natural colors, realistic, 35mm, '
        'no text, no people in close-up')
VIEWS = {
    'city-day': 'modern Russian residential district, light mid-rise apartment blocks, young trees along a street, clear '
                'daytime sky with light clouds',
    'city-evening': 'evening at blue hour after sunset, modern residential district, warm lights glowing in many distant '
                    'windows, street lamps on, deep blue evening sky with a warm glow at the horizon',
    'yard': 'green courtyard of a new residential complex, playground and trees below, neighbouring light buildings',
    'park': 'park with mature trees and a pond below, city skyline far away, daytime',
}


def main() -> int:
    only = sys.argv[sys.argv.index('--only') + 1].split(',') if '--only' in sys.argv else list(VIEWS)
    os.makedirs(OUT, exist_ok=True)
    key = fal_key()
    made, failed = 0, 0
    for vid in only:
        dst = os.path.join(OUT, vid + '.webp')
        if os.path.exists(dst) and '--force' not in sys.argv:
            print(f'{vid}: уже есть')
            continue
        try:
            base = BASE.replace('sunny, ', '') if 'evening' in vid else BASE   # «солнечно» перебивало вечер (проба 14.10)
            r = fal_run(MODEL, {'prompt': f'{base}, {VIEWS[vid]}', 'image_size': {'width': 1600, 'height': 1072},
                                'num_inference_steps': 28, 'num_images': 1}, key)
            url = r['images'][0]['url']
            img = Image.open(io.BytesIO(urllib.request.urlopen(url, timeout=120).read())).convert('RGB')
            img.save(dst, 'WEBP', quality=80, method=6)
            made += 1
            print(f'{vid}: {img.size[0]}×{img.size[1]}, {os.path.getsize(dst) // 1024} КБ → {dst}')
        except Exception as e:  # noqa: BLE001 — неудача считается и печатается
            failed += 1
            print(f'{vid}: НЕ ВЫШЛО — {str(e)[:200]}')
    print(f'итог: сделано {made}, не вышло {failed}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

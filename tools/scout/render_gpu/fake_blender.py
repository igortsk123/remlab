#!/usr/bin/env python3
"""Подмена Blender для тестов воркера (T-20261117-24/2): разбирает флаги как `render_cycles.py`, печатает те же строки (DEVICE_USED, RENDER_SEC) и
пишет кадры. Режимы — переменная FAKE_BLENDER: ok | cpu | fail | slow."""
import os
import sys
import time

a = sys.argv[sys.argv.index('--') + 1:]
cams = a[a.index('--cam') + 1].split(',')
out = a[a.index('--out') + 1]
mode = os.environ.get('FAKE_BLENDER', 'ok')
print('DEVICE_USED ' + ('CPU (GPU не найден, запасной путь)' if mode == 'cpu' else 'CUDA (NVIDIA GeForce RTX 4090)'), flush=True)
if mode == 'fail':
    print('Traceback: boom', flush=True)
    sys.exit(1)
from PIL import Image  # noqa: E402  (в тестах PIL есть; воркер на машине эту подмену не запускает)
for i, c in enumerate(cams):
    time.sleep(float(os.environ.get('FAKE_FRAME_S', '0.3')) if mode != 'slow' else 60)
    im = Image.new('RGB', (64, 48), (40 + i * 60, 90, 140))
    if '--jpeg-quality' in a:            # T-24/11: как render_cycles.py — JPEG нужного качества; --also-png — ещё и PNG из того же результата
        im.save(out.replace('{cam}', c), 'JPEG', quality=int(a[a.index('--jpeg-quality') + 1]))
        if '--also-png' in a:
            im.save(a[a.index('--also-png') + 1].replace('{cam}', c), 'PNG')
    else:
        im.save(out.replace('{cam}', c))
    print(f'RENDER_SEC {1.5 + i:.1f} cam {c} frame {i + 1}/{len(cams)} samples 64 pct 75 device CUDA threads 4', flush=True)
if '--mask-out' in a:                                    # T-20261118-05/3: проход масок поверхностей после кадров, как render_cycles.py (FAKE_MASKS: ok | none | bad)
    mm = os.environ.get('FAKE_MASKS', 'ok')
    sc = float(a[a.index('--mask-scale') + 1]) if '--mask-scale' in a else 1.0
    w_, h_ = max(8, int(64 * sc)), max(8, int(48 * sc))
    for c in cams:
        if mm == 'none':
            break
        p = a[a.index('--mask-out') + 1].replace('{cam}', c)
        if mm == 'bad':
            open(p, 'wb').write(b'not a png')
            continue
        mk = Image.new('RGB', (w_, h_), (0, 0, 0))
        for y in range(h_):
            for x in range(w_):
                mk.putpixel((x, y), (255, 0, 0) if y > h_ * 0.6 else (0, 255, 0) if y < h_ * 0.4 else (130, 125, 0))      # пол внизу, стена вверху, полоса сглаживания между ними
        mk.save(p, 'PNG')
    print(f'MASK_SEC 0.4 cams {len(cams)}', flush=True)

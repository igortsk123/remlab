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
    Image.new('RGB', (64, 48), (40 + i * 60, 90, 140)).save(out.replace('{cam}', c))
    print(f'RENDER_SEC {1.5 + i:.1f} cam {c} frame {i + 1}/{len(cams)} samples 64 pct 75 device CUDA threads 4', flush=True)

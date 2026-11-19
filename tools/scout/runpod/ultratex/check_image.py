#!/usr/bin/env python3
"""Проверка образа UltraTex БЕЗ видеокарты (зовёт сборка Actions): импорт воркера и вшитого ultratex_core, EGL-контекст moderngl (llvmpipe),
импорт кода авторов (модулей, которым не нужна карта на импорте). Печатает по строке на проверку; код выхода ≠ 0, если что-то не встало."""
import importlib
import os
import sys

sys.path.insert(0, '/app')
sys.path.insert(0, os.environ.get('ULTRATEX_DIR', '/opt/UltraTex'))
bad = []
for m in ('worker_ultratex', 'ultratex_core.render', 'ultratex_core.prep', 'ultratex_core.bake',
          'ultratex.backbones.flux2.util', 'ultratex.backbones.flux2.model', 'train_flux2', 'inference_flux2'):
    try:
        importlib.import_module(m)
        print('импорт ок:', m)
    except Exception as exc:                                   # noqa: BLE001
        bad.append(m)
        print('ИМПОРТ УПАЛ:', m, type(exc).__name__, str(exc)[:300])
try:
    import moderngl
    ctx = moderngl.create_standalone_context(require=330, backend='egl')
    print('EGL-контекст:', ctx.info['GL_RENDERER'])
except Exception as exc:                                       # noqa: BLE001
    bad.append('egl')
    print('EGL УПАЛ:', type(exc).__name__, str(exc)[:300])
# два «задания» подряд в РАЗНЫХ потоках (воркер берёт каждое в новом потоке): контекст EGL привязан к потоку — на RunPod 19.11 2-е задание
# падало «cannot create program» (T-90/2). Строим программу и рисуем крошечную сетку в каждом потоке.
import threading
import numpy as np
from ultratex_core.render import GLRenderer


def one_job(res):
    try:
        v = np.array([[-1, -1, 0], [1, -1, 0], [0, 1, 0]], dtype='f8')
        n = np.tile([0, 0, 1.0], (3, 1))
        f = np.array([[0, 1, 2]])
        with GLRenderer(v, n, f) as r:
            r._render(16, np.eye(4, dtype='f4'), np.eye(4, dtype='f4'), 0)
        res.append('ok')
    except Exception as exc:                                   # noqa: BLE001
        res.append(f'{type(exc).__name__}: {str(exc)[:200]}')


for i in (1, 2, 3):
    res = []
    t = threading.Thread(target=one_job, args=(res,))
    t.start()
    t.join()
    print(f'задание-поток {i}:', res[0])
    if res[0] != 'ok':
        bad.append(f'thread-job-{i}')
sys.exit(1 if bad else 0)

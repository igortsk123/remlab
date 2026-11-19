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
sys.exit(1 if bad else 0)

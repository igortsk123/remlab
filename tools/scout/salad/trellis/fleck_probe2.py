#!/usr/bin/env python3
"""Крапинки гибрида, часть 2: что лежит в текстурах (альбедо, металл-шероховатость): перцентили яркости, доля текселей почти чёрных/пустых.
Запуск: ~/venvs/scout/bin/python fleck_probe2.py <гибрид.glb>   Только чтение."""
import json
import sys

import numpy as np
import trimesh

sc = trimesh.load(sys.argv[1], force='scene')
for g in sc.geometry.values():
    m = g.visual.material
    print('материал', type(m).__name__, 'metallic', getattr(m, 'metallicFactor', None), 'rough', getattr(m, 'roughnessFactor', None), 'emissive', getattr(m, 'emissiveFactor', None))
    for nm in ('baseColorTexture', 'metallicRoughnessTexture', 'normalTexture', 'emissiveTexture', 'occlusionTexture'):
        im = getattr(m, nm, None)
        if im is None:
            print(' ', nm, '— нет')
            continue
        a = np.asarray(im.convert('RGB')).astype(float)
        lum = a.mean(axis=2)
        print(' ', nm, im.size, 'ярк. p1/p50/p99/max:', [round(float(np.percentile(lum, p)), 1) for p in (1, 50, 99)], round(float(lum.max()), 1),
              'доля <8:', round(float((lum < 8).mean()), 4), 'доля >200:', round(float((lum > 200).mean()), 4))
        if nm == 'metallicRoughnessTexture':
            print('    G(шероховатость) p1/p50/p99:', [round(float(np.percentile(a[..., 1], p)), 1) for p in (1, 50, 99)], ' B(металл) p1/p50/p99:', [round(float(np.percentile(a[..., 2], p)), 1) for p in (1, 50, 99)])

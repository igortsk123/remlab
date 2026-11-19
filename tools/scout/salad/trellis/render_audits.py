#!/usr/bin/env python3
"""Кадры az045 по аудит-GLB пробы правила плиты (`slab_probe.py`): python3 render_audits.py <папка пробы> <метка.вариант> ..."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, '..', '..', '..', '..'))
BLENDER = os.path.expanduser('~/opt/blender-4.5.9/blender')
d = sys.argv[1]
for name in sys.argv[2:]:
    out = os.path.join(d, 'frames', name)
    os.makedirs(out, exist_ok=True)
    cmd = [os.path.join(REPO, 'tools/ops/heavy-slot.sh'), f'p91-slab-{name[:20]}', '--cores', '4', '--min-gb', '3', '--timeout', '1500', '--',
           BLENDER, '-b', '-P', os.path.join(HERE, 'render_stand.py'), '--', '--glb', os.path.join(d, name + '.audit.glb'), '--out', out, '--samples', '24', '--modes', 'tex', '--only', 'az045']
    with open(os.path.join(d, 'render.log'), 'a') as f:
        rc = subprocess.call(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=REPO)
    print(name, rc, flush=True)

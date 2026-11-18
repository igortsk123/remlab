#!/usr/bin/env python3
"""ОДНОРАЗОВО (T-20261117-22): render_cycles.py — несколько ракурсов в одном процессе Blender.
Камерный блок (от «# ---- камера» до «# ---- свет») превращается в функцию setup_camera(name), блок DoF — в dof_current(),
рендер — в цикл по ракурсам. Остальной код не трогается. Запуск: python3 patch_multicam.py <путь к render_cycles.py>"""
import re
import sys

p = sys.argv[1]
L = open(p, encoding='utf-8').read().split('\n')


def find(prefix, start=0):
    for i in range(start, len(L)):
        if L[i].startswith(prefix):
            return i
    raise SystemExit(f'не нашёл строку: {prefix}')


i0 = find('# ---------------- камера')
i1 = find('# ---------------- свет')
blk = L[i0 + 1:i1]
text = '\n'.join(blk)
assert "a.cam)" in text, 'нет ожидаемого a.cam в блоке камеры'
text = text.replace("c['name'] == a.cam)", "c['name'] == cam_name)")
body = ['    ' + ln if ln.strip() else ln for ln in text.split('\n')]
head = [L[i0],
        'def setup_camera(cam_name):',
        '    """Ракурс `cam_name` целиком (поза, правила позы «Б», объектив) — глобальные cd/cam/co/right/up/fwd/pose_b обновляются."""',
        '    global cd, pose_b, cam, co, right, up, fwd, rot, mat4, _wins',
        ]
new_blk = head + body + ['', '']
L[i0:i1] = new_blk

# DoF-блок: от «if a.dof > 0:» до строки перед «os.makedirs(os.path.dirname(os.path.abspath(a.out))»
d0 = find('if a.dof > 0:')
d1 = find('os.makedirs(os.path.dirname(os.path.abspath(a.out))', d0)
dof = L[d0:d1]
dof_f = ['def dof_current():'] + ['    ' + ln if ln.strip() else ln for ln in dof] + ['']
L[d0:d1] = dof_f

# хвост: рендер
r0 = find('os.makedirs(os.path.dirname(os.path.abspath(a.out))')
tail_old = L[r0:]
tail_new = '''CAMS = [c.strip() for c in a.cam.split(',') if c.strip()]
if len(CAMS) > 1 and '{cam}' not in a.out:
    raise SystemExit('несколько ракурсов: в --out нужен шаблон {cam}, например /x/frame-{cam}.png')
print(f'SCENE_BUILD_SEC {time.time() - T_START:.1f}', flush=True)
for _i, _cn in enumerate(CAMS):
    setup_camera(_cn)
    dof_current()
    _out = a.out.replace('{cam}', _cn)
    os.makedirs(os.path.dirname(os.path.abspath(_out)), exist_ok=True)
    sc.render.filepath = _out
    t0 = time.time()
    bpy.ops.render.render(write_still=True)
    print(f'RENDER_SEC {time.time() - t0:.1f} cam {_cn} frame {_i + 1}/{len(CAMS)} samples {a.samples} pct {a.pct} device {DEVICE_USED} threads {a.threads}', flush=True)
'''.split('\n')
L[r0:] = tail_new
open(p, 'w', encoding='utf-8').write('\n'.join(L))
print('ok: камера', i0, '-', i1, 'dof', d0, '-', d1, 'хвост', r0)

#!/usr/bin/env python3
"""Тест pose_job.py (T-185/1): запуск pose_fit → camera_check одной командой. Поддельные pose_fit.py/camera_check.py рядом с копией pose_job.py — проверяем порядок, аргументы, коды выхода и check.json."""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0


def ok(cond, name, extra=''):
    global fails
    print(('  ✓ ' if cond else '  ✗ ') + name + ('' if cond else f' — {extra}'))
    fails += 0 if cond else 1


FIT = ("import sys, os, json\na = sys.argv[1:]\nout = a[a.index('--out-run') + 1]\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calls.txt'), 'a').write('fit ' + ' '.join(a) + '\\n')\n"
       "if os.environ.get('FAKE_FIT_RC'):\n    sys.exit(int(os.environ['FAKE_FIT_RC']))\nos.makedirs(out, exist_ok=True)\njson.dump({'camera': {'az': 1}}, open(os.path.join(out, 'pose.json'), 'w'))\n")
CHK = ("import sys, os, json\na = sys.argv[1:]\nrun = a[a.index('--run') + 1]\nopen(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calls.txt'), 'a').write('check ' + ' '.join(a) + '\\n')\n"
       "if os.environ.get('FAKE_NO_CHECK'):\n    sys.exit(0)\nos.makedirs(os.path.join(run, '04-camera'), exist_ok=True)\n"
       "json.dump({'passed': False, 'reason': 'низ не проходит'}, open(os.path.join(run, '04-camera', 'check.json'), 'w'))\nsys.exit(1)\n")


def mk():
    d = tempfile.mkdtemp(prefix='pj-')
    shutil.copy(os.path.join(HERE, 'pose_job.py'), d)
    open(os.path.join(d, 'pose_fit.py'), 'w').write(FIT)
    open(os.path.join(d, 'camera_check.py'), 'w').write(CHK)
    return d


def run(d, extra, env=None):
    out = os.path.join(d, 'out')
    p = subprocess.run([sys.executable, os.path.join(d, 'pose_job.py'), '--glb', '/g.glb', '--photo', '/p.png', '--out-run', out, *extra], capture_output=True, text=True, env={**os.environ, **(env or {})})
    return p, out


d = mk()
p, out = run(d, ['--device', 'cuda'])
calls = open(os.path.join(d, 'calls.txt')).read().splitlines()
ok(p.returncode == 0, 'вердикт «не прошёл» — результат, а не отказ: код 0', p.stderr[-200:])
ok(len(calls) == 2 and calls[0].startswith('fit ') and calls[1].startswith('check '), 'порядок: сначала pose_fit, потом camera_check', str(calls))
ok('--device cuda' in calls[0] and '--glb /g.glb' in calls[0] and f'--out-run {out}' in calls[0] and f'--run {out} --photo /p.png' in calls[1], 'аргументы доехали: устройство, форма, папка выхода, фото', str(calls))
ok(json.load(open(os.path.join(out, 'check.json')))['passed'] is False and os.path.isfile(os.path.join(out, 'pose.json')), 'в выходе: pose.json и check.json (копия 04-camera/check.json)')
d = mk()
p, out = run(d, [], {'FAKE_FIT_RC': '3'})
ok(p.returncode == 3 and len(open(os.path.join(d, 'calls.txt')).read().splitlines()) == 1, 'pose_fit упал (код 3) → код 3, camera_check не запускался', str((p.returncode, p.stderr[-120:])))
d = mk()
p, out = run(d, [], {'FAKE_NO_CHECK': '1'})
ok(p.returncode != 0 and not os.path.exists(os.path.join(out, 'check.json')), 'camera_check не оставил check.json → отказ (код ≠ 0)', str(p.returncode))
p = subprocess.run([sys.executable, os.path.join(d, 'pose_job.py'), '--glb', 'g', '--photo', 'p', '--out-run', 'o', '--device', 'tpu'], capture_output=True, text=True)
ok(p.returncode == 2, 'неизвестное устройство — отказ разбора аргументов (код 2)')
print('ИТОГО: ' + ('всё в норме' if not fails else f'провалов {fails}'))
sys.exit(1 if fails else 0)

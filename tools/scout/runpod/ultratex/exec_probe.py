#!/usr/bin/env python3
"""Проверка без сети и GPU: воркер, запущенный командой из salad_trial.worker_command (код в env), стартует и отвечает на /health с root_gb и cuda.
Запуск: ~/venvs/scout/bin/python exec_probe.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import salad_trial as S  # noqa: E402

cmd, z = S.worker_command(os.path.join(HERE, 'worker_ultratex.py'))
root = tempfile.mkdtemp(prefix='utroot-')
open(os.path.join(root, 'x.bin'), 'wb').write(b'0' * (3 * 2 ** 20))
env = {**os.environ, 'KIT_WORKER_Z': z, 'PORT': '18123', 'ULTRATEX_ROOT': root, 'HF_TOKEN': 'bad', 'MAX_LIFETIME_S': '120'}
p = subprocess.Popen([sys.executable if cmd[0] == 'python' else cmd[0]] + cmd[1:], env=env, cwd=tempfile.gettempdir(),
                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)       # не из папки кода: модули набора обязаны прийти из KIT_WORKER_Z
ok = False
try:
    for _ in range(40):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen('http://127.0.0.1:18123/health', timeout=3) as r:
                h = json.loads(r.read())
                print('health', json.dumps({k: h.get(k) for k in ('phase', 'version', 'root_gb', 'cuda', 'uptime_s')}, ensure_ascii=False))
                ok = h.get('phase') in ('weights', 'loading', 'ready', 'broken') and h.get('root_gb') is not None and 'cuda' in h
                break
        except Exception:                                    # noqa: BLE001
            if p.poll() is not None:
                break
finally:
    p.terminate()
    try:
        out = p.communicate(timeout=10)[0].decode('utf-8', 'replace')
    except Exception:                                        # noqa: BLE001
        p.kill()
        out = ''
if not ok:
    print(out[-1500:])
print('ИТОГ:', 'ВСЁ ЗЕЛЁНОЕ' if ok else 'ПАДЕНИЕ')
sys.exit(0 if ok else 1)

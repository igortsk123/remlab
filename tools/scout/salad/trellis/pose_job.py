#!/usr/bin/env python3
"""ЗАДАНИЕ «КАМЕРА ПО ФОТО» (этап 04) одной командой для воркера Salad (T-185/1): `pose_fit.py` → `camera_check.py` в одной папке выхода. Логики здесь нет — только запуск двух наших
CLI подряд (из того же среза кода, что и этот файл), чтобы воркеру хватило одной команды из whitelist, а результат совпал с локальным: `pose.json`, `stage_loss.json`, `stages/…`, `04-camera/check.json`.
Использование: pose_job.py --glb <форма.glb> --photo <фото-RGBA.png> --out-run <папка> [--device numpy|cpu|cuda] [--yaw 0].
Код выхода: 0 — обе команды отработали (вердикт `camera_check` — РЕЗУЛЬТАТ, в `<out>/check.json`, не отказ); иначе код упавшей команды. `<out>/check.json` — копия `04-camera/check.json`
(воркер берёт из него `passed`/`reason` для метрик задания)."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def run(cmd: list[str]) -> int:
    print('$', ' '.join(cmd), flush=True)
    return subprocess.run(cmd).returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--glb', required=True)
    ap.add_argument('--photo', required=True)
    ap.add_argument('--out-run', required=True)
    ap.add_argument('--device', choices=('numpy', 'cpu', 'cuda'), default='numpy')
    ap.add_argument('--yaw', type=float, default=0.0)
    a = ap.parse_args(argv)
    py = sys.executable
    os.makedirs(a.out_run, exist_ok=True)
    rc = run([py, '-I', os.path.join(HERE, 'pose_fit.py'), '--glb', a.glb, '--photo', a.photo, '--out-run', a.out_run, '--yaw', str(a.yaw), '--device', a.device])
    if rc != 0:
        print(f'pose_fit: код {rc}', file=sys.stderr)
        return rc
    rc = run([py, '-I', os.path.join(HERE, 'camera_check.py'), '--run', a.out_run, '--photo', a.photo])
    chk = os.path.join(a.out_run, '04-camera', 'check.json')
    if not os.path.isfile(chk):
        print(f'camera_check: код {rc}, нет {chk}', file=sys.stderr)
        return rc or 2
    shutil.copyfile(chk, os.path.join(a.out_run, 'check.json'))
    c = json.load(open(chk, encoding='utf-8'))
    print(json.dumps({'passed': c.get('passed'), 'reason': str(c.get('reason') or '')[:160]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())

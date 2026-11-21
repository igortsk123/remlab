#!/bin/bash
# Локальная перепроекция StableGen без пода: sg_reproject.sh <session.blend прогона> <config.json>   (скрипт — sg_reproject.py; слот общий, приоритет 0 — платные впереди, ADR-0453)
set -u
SG=${SG_HOME:-$HOME/remlab-logs/t90-1119/sg}
HERE=$(cd "$(dirname "$0")" && pwd)
export BLENDER_USER_RESOURCES=$SG/home PYTHONPATH=$SG/deps
exec "$HERE/../../ops/heavy-slot.sh" t90-sg-reproject --prio 0 --min-gb 3 --cores 3 --timeout 2400 -- \
  "$HERE/xvfb_run.sh" -a -s "-screen 0 1280x1024x24" nice -n 10 "${BLENDER:-$HOME/opt/blender-4.5.9/blender}" "$1" -t 3 --factory-startup --python-use-system-env --python "$HERE/sg_reproject.py" -- "$2"

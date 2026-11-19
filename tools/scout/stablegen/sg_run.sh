#!/bin/bash
# Запуск драйвера StableGen в Blender 4.5.9 под xvfb: sg_run.sh <config.json>   (аддон и зависимости — ~/remlab-logs/t90-1119/sg, установка — README.md)
set -u
SG=${SG_HOME:-$HOME/remlab-logs/t90-1119/sg}
HERE=$(cd "$(dirname "$0")" && pwd)
export BLENDER_USER_RESOURCES=$SG/home PYTHONPATH=$SG/deps
exec xvfb-run -a -s "-screen 0 1280x1024x24" nice -n 10 "${BLENDER:-$HOME/opt/blender-4.5.9/blender}" -t "${SG_THREADS:-4}" --factory-startup --python-use-system-env --python "$HERE/sg_drive.py" -- "$1"

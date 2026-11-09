#!/bin/bash
# Установка юнита воркера пробы для агентов на DEV (pakardev, пользователь pakar). Только КОПИРУЕТ файл юнита
# в ~/.config/systemd/user/ и проверяет окружение; включение — командами, которые скрипт печатает (решает ведущий).
#   tools/floorplan/worker_install.sh           # копия + проверки + подсказка
#   tools/floorplan/worker_install.sh --check   # только проверки, ничего не копирует
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
UNIT=remlab-trial-worker.service
SRC=$HERE/systemd/$UNIT
DST=$HOME/.config/systemd/user/$UNIT
PY=$HOME/venvs/scout/bin/python
ENVF=$HOME/.config/remlab/env
ok=1

say() { printf '%s\n' "$*"; }
[ -x "$PY" ] || { say "НЕТ: $PY"; ok=0; }
for b in pdfinfo pdftoppm prlimit timeout; do
  command -v "$b" >/dev/null || { say "НЕТ: $b (poppler-utils / util-linux / coreutils)"; ok=0; }
done
# токен: только факт наличия строки, значение не читаем и не печатаем
if [ -f "$ENVF" ] && grep -q '^TRIAL_WORKER_TOKEN=.' "$ENVF"; then
  say "токен: строка TRIAL_WORKER_TOKEN в $ENVF есть"
else
  say "НЕТ: строки TRIAL_WORKER_TOKEN=… в $ENVF (тот же, что TRIAL_WORKER_TOKEN прода)"; ok=0
fi
[ "$REPO" = "$HOME/igor/remlab" ] || say "внимание: юнит запускает основную копию $HOME/igor/remlab, а скрипт лежит в $REPO"
"$PY" -c 'import cv2, numpy, PIL' 2>/dev/null || { say "НЕТ: cv2/numpy/PIL в $PY"; ok=0; }

if [ "${1:-}" = "--check" ]; then
  [ $ok = 1 ] && say "проверки: чисто" || say "проверки: есть НЕТ — см. выше"
  exit 0
fi
[ $ok = 1 ] || { say "не копирую: сперва исправить НЕТ выше"; exit 1; }

mkdir -p "$(dirname "$DST")" "$HOME/remlab-logs/trial" "$HOME/remlab-scratch/tmp"
if [ -f "$DST" ] && cmp -s "$SRC" "$DST"; then
  say "юнит уже на месте: $DST (без изменений)"
else
  [ -f "$DST" ] && cp -p "$DST" "$DST.bak-$(date +%Y%m%d-%H%M%S)"
  cp "$SRC" "$DST"
  say "скопирован: $DST"
fi
cat <<EOF
Дальше (ведущий, руками):
  systemctl --user daemon-reload
  (cd $HOME/igor/remlab && set -a && . $ENVF && set +a && $PY tools/floorplan/worker.py --check)
  systemctl --user enable --now $UNIT
  tail -f $HOME/remlab-logs/trial/worker.log
Откат: systemctl --user disable --now $UNIT
EOF

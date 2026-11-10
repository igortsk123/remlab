#!/bin/sh
# Шаг remlab общей автоочистки pakardev (T-20261110-30). Вызов из /usr/local/sbin/disk-hygiene.sh (root, таймер 04:30) — строка
# там ставится ведущим после слова владельца, в стиле шага sup2 6b:
#   # 6c. remlab: влитые рабочие копии, кэши стенда планов, старые поколения мешей, тома и контейнеры стендов БД — по воскресеньям.
#   [ "$(date +%u)" = 7 ] && /home/pakar/igor/remlab/tools/ops/remlab-hygiene.sh
# Сам ничего не решает: правила и одобрение — tools/scout/rules/dev-disk-clean.json (approved), логика — tools/ops/disk_clean.py.
# --apply удаляет ТОЛЬКО по правилам с approved=true (сейчас — ни одного: включает владелец). Работает от pakar (git-копии,
# /proc и журнал — его), не от root. Ручной прогон без удалений: remlab-hygiene.sh --proba
# Журнал — ~/remlab-logs/disk-clean/ (pakar); итог одной строкой — в journalctl -u disk-hygiene.
set -u
U=pakar
R=$(cd "$(dirname "$0")/../.." && pwd) || exit 0     # копия, из которой вызван (на машине — /home/pakar/igor/remlab)
PY=/home/pakar/venvs/scout/bin/python
MODE=--apply
[ "${1:-}" = "--proba" ] && MODE=
run() {
  if [ "$(id -un)" = "$U" ]; then "$@"; else sudo -u "$U" -H "$@"; fi
}
cd "$R" || exit 0
OUT=$(run nice -n 15 ionice -c3 "$PY" tools/ops/disk_clean.py $MODE --digest 2>&1)
RC=$?
if printf '%s\n' "$OUT" | grep -q '^DIGEST:'; then
  printf '%s\n' "$OUT" | sed -n 's/^DIGEST:/remlab: /p; /^WARN:/p; /^не удалено:/p'
else   # упал — громко, не молча (общий скрипт идёт дальше по своим шагам)
  echo "remlab: уборка не отработала (код $RC): $(printf '%s\n' "$OUT" | tail -1 | cut -c1-300)"
fi
exit 0

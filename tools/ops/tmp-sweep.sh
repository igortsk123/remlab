#!/usr/bin/env bash
# НОЧНАЯ ЧИСТКА /tmp НА DEV (план b2b-09, «Добавлено 16.10»). /tmp — tmpfs ~788 МБ с квотой; забитый, он ронял headless-браузер
# живых проверок («Target crashed») и однажды шелл агента. Удаляем ТОЛЬКО свои временные файлы конвейера в корне /tmp старше
# `sweep_older_h` (rules/dev-tmp.json): вырезки tmp*-cut.png, временные tmp*.jpg/png/obj/json/glb, пробы llm-probe.*.
# Каталоги сессий агентов (claude-*), snap/systemd и всё чужое — не трогаем.
#   bash tools/ops/tmp-sweep.sh          # чистка
#   bash tools/ops/tmp-sweep.sh --dry    # только показать
set -uo pipefail
RULES="$(dirname "$0")/../scout/rules/dev-tmp.json"
H=$(python3 -c "import json,sys;print(int(json.load(open(sys.argv[1])).get('sweep_older_h',24)))" "$RULES" 2>/dev/null || echo 24)
DRY=0; [ "${1:-}" = "--dry" ] && DRY=1
n=0; kb=0
while IFS= read -r -d '' f; do
  s=$(du -k "$f" | cut -f1); kb=$((kb + s)); n=$((n + 1))
  [ "$DRY" = 1 ] && echo "  удалю: $f (${s} КБ)" || rm -f -- "$f"
done < <(find /tmp -maxdepth 1 -type f -user "$(id -u)" -mmin +$((H * 60)) \
           \( -name 'tmp*-cut.png' -o -name 'tmp*.jpg' -o -name 'tmp*.png' -o -name 'tmp*.obj' -o -name 'tmp*.json' \
              -o -name 'tmp*.glb' -o -name 'llm-probe.*' \) -print0)
echo "чистка /tmp: файлов $n, $((kb / 1024)) МБ (старше ${H} ч)$([ "$DRY" = 1 ] && echo ' — сухой прогон')"

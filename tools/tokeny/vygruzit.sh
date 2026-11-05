#!/usr/bin/env bash
# Ночная выгрузка токенов Claude этой машины (tokeny-mashiny/1): сутки по Лондону (по умолчанию вчера) →
# <проект>/data/logs/tokeny/<hostname>-<ГГГГ-ММ-ДД>.json в общей папке проекта (на common и algor — sshfs с pakardev).
# Запуск — таймер tokeny-vygruzka-<проект> (tools/tokeny/systemd/, ставит tools/tokeny/postavit_taymer.sh), вручную:
#   tools/tokeny/vygruzit.sh [ГГГГ-ММ-ДД]
# Файл кладётся атомарно (.tmp → mv). Код 3 — сверка с журналами не сошлась: файл всё равно кладётся (в нём
# "sverka": false, сводка скажет об этом). Иной код — файла нет, сводка скажет «нет данных». В выгрузке — и последний
# замер недели учётки машины (журнал statusline `~/.claude/usage-log.jsonl`, только чтение).
# Строка в <папка>/vygruzka-<машина>.log (свой у каждой машины: дозапись по sshfs не атомарна): время UTC ⇥ машина ⇥
# сутки ⇥ код ⇥ вывод tokeny.py. Папка данных — $STATE_ROOT/data, по умолчанию <TOKENY_PROEKTY>/<проект>/data (каноничное
# дерево, и из worktree). Журналы Claude только читаются. Для проверок: TOKENY_PAPKA (куда класть), TOKENY_KOREN (корень
# журналов), TOKENY_PROEKT (по умолчанию — имя папки репозитория), TOKENY_PROEKTY (папка проектов, /home/pakar/igor).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
KORNI="${TOKENY_PROEKTY:-/home/pakar/igor}"
PROEKT="${TOKENY_PROEKT:-$(basename "${REPO%%/.claude/worktrees/*}")}"
STATE_ROOT="${STATE_ROOT:-$KORNI/$PROEKT}"
PAPKA="${TOKENY_PAPKA:-$STATE_ROOT/data/logs/tokeny}"
DEN="${1:-$(TZ=Europe/London date -d yesterday +%F)}"
MASHINA="$(hostname)"
[[ "$DEN" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "сутки — ГГГГ-ММ-ДД, а не «$DEN»" >&2; exit 2; }
mkdir -p "$PAPKA" || exit 2
[ -e "$PAPKA/.gitignore" ] || printf '*\n' > "$PAPKA/.gitignore"  # выгрузки — не в git проекта
cel="$PAPKA/$MASHINA-$DEN.json"
tmp="$cel.tmp"
koren=()
[ -n "${TOKENY_KOREN:-}" ] && koren=(--koren "$TOKENY_KOREN")
vyvod="$(python3 -B "$(dirname "$0")/tokeny.py" --proekt "$PROEKT" "${koren[@]}" \
         --s "$DEN" --po "$DEN" --json "$tmp" 2>&1)"
kod=$?
if [ -s "$tmp" ] && { [ "$kod" = 0 ] || [ "$kod" = 3 ]; }; then
    mv -f -- "$tmp" "$cel" || kod=4
else
    rm -f -- "$tmp"
fi
printf '%s\t%s\t%s\t%s\t%s\n' "$(date -u +%FT%TZ)" "$MASHINA" "$DEN" "$kod" \
    "$(printf '%s' "$vyvod" | tr '\t\n' '  ' | cut -c1-500)" >> "$PAPKA/vygruzka-$MASHINA.log"
echo "$MASHINA $PROEKT $DEN: код $kod; $vyvod"
exit "$kod"

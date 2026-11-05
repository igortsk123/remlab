#!/usr/bin/env bash
# Сводка токенов проекта со всех машин (tokeny-mashiny/1): склейка выгрузок <проект>/data/logs/tokeny/<машина>-<сутки>.json
# → текст в stdout и файл <проект>/data/otchety/tokeny/svodka-<сутки>.txt. Запускается на любой машине (папки проектов на
# common и algor — sshfs с pakardev, выгрузки общие):
#   tools/tokeny/svodka.sh [--proekt X] [ГГГГ-ММ-ДД]      # по умолчанию — свой проект и вчера по Лондону
# В сводке: токены и $ по прайсу API по машинам, % недели учётки каждой машины, строка «Память», напоминание о замере пользы.
# Машина без выгрузки — явно «нет данных с <машина>» (список — TOKENY_MASHINY). Сбой tokeny.py — файл всё равно есть, с кодом
# и ошибкой (отправка в Telegram не промолчит). Путь файла и число выгрузок — в stderr.
# Переменные: TOKENY_PROEKTY (папка проектов, /home/pakar/igor), TOKENY_PROEKT, TOKENY_PAPKA (выгрузки), TOKENY_VYHOD
# (папка сводки), TOKENY_MASHINY (через запятую), TOKENY_ZAMERY (журнал замеров памяти), STATE_ROOT (данные своего проекта).
set -uo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
KORNI="${TOKENY_PROEKTY:-/home/pakar/igor}"
SVOY="$(basename "${REPO%%/.claude/worktrees/*}")"  # из worktree — имя основного дерева
PROEKT="${TOKENY_PROEKT:-$SVOY}"
DEN=""
while [ $# -gt 0 ]; do
    case "$1" in
        --proekt) [ $# -ge 2 ] || { echo "--proekt без имени" >&2; exit 2; }; PROEKT="$2"; shift 2 ;;
        --proekt=*) PROEKT="${1#--proekt=}"; shift ;;
        -h|--help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) [ -z "$DEN" ] || { echo "лишний аргумент: $1" >&2; exit 2; }; DEN="$1"; shift ;;
    esac
done
[[ "$PROEKT" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || { echo "проект — имя папки в $KORNI, а не «$PROEKT»" >&2; exit 2; }
DEN="${DEN:-$(TZ=Europe/London date -d yesterday +%F)}"
[[ "$DEN" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || { echo "сутки — ГГГГ-ММ-ДД, а не «$DEN»" >&2; exit 2; }
if [ "$PROEKT" = "$SVOY" ] && [ -n "${STATE_ROOT:-}" ]; then STATE="$STATE_ROOT"; else STATE="$KORNI/$PROEKT"; fi
[ -d "$STATE" ] || { echo "нет папки проекта $STATE" >&2; exit 2; }
PAPKA="${TOKENY_PAPKA:-$STATE/data/logs/tokeny}"
VYHOD="${TOKENY_VYHOD:-$STATE/data/otchety/tokeny}"
ZAMERY="${TOKENY_ZAMERY:-$STATE/.memory_bank/changelog/memory-eval.log}"
MASHINY="${TOKENY_MASHINY:-common,algor,pakardev}"
mkdir -p "$VYHOD" || exit 2
[ -e "$VYHOD/.gitignore" ] || printf '*\n' > "$VYHOD/.gitignore"  # сводки — не в git проекта
fayly=()
for f in "$PAPKA"/*-"$DEN".json; do
    [ -f "$f" ] && fayly+=("$f")
done
cel="$VYHOD/svodka-$DEN.txt"
tmp="$cel.tmp"
python3 -B "$(dirname "$0")/tokeny.py" --proekt "$PROEKT" --sobrat "${fayly[@]}" --svodka --data "$DEN" \
    --ozhidaem "$MASHINY" --zamery "$ZAMERY" --doska "$STATE/.memory_bank/plans/README.md" > "$tmp" 2> "$tmp.err"
kod=$?
if [ "$kod" != 0 ]; then
    { echo "Сводка токенов $PROEKT за $DEN не собрана: tokeny.py, код $kod."; tail -n 5 "$tmp.err"; } > "$tmp"
fi
rm -f -- "$tmp.err"
mv -f -- "$tmp" "$cel" || exit 4
cat -- "$cel"
echo "$cel (выгрузок: ${#fayly[@]}, код $kod)" >&2
exit "$kod"

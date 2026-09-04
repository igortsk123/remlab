#!/usr/bin/env bash
# РАСПИСАНИЕ ДЕШЁВОГО ТАРИФА: поднимать batch-группы только в окно, где они реально работают.
#
# ЗАЧЕМ (владелец 04.09: «поднимать около 09:00 и гасить к 15:00»). Разбор журнала за 01–03.09
# показал у тарифа `batch` устойчивое суточное окно — доля УСПЕШНО ЗАКРЫТЫХ заданий по часам:
#     04ч 86% · 10ч 81% · 12ч 79% · 09ч 64% · 14ч 59% · 11ч 51%
#     15ч  0% · 16ч  5% · 18ч  9% · 23ч  0%
# Картина держится в разные дни и на разных образах, то есть это не артефакт одного прогона:
# 15–16ч дали 0% и 6% первого числа и 0%/0% третьего. Машины Salad — чужие домашние компьютеры;
# днём хозяева на работе и отдают их нам, вечером забирают обратно — задание рвётся посреди
# генерации («нет маркера в выводе»).
#
# ЦЕНА БЕЗ РАСПИСАНИЯ (замер 03.09, 17:44–21:22): 57 машин прошло через две batch-группы,
# каждая прогрелась — и НИ ОДНА не отдала меша. 17.2 нодо-часа, 134 ₽ впустую; цена меша по
# пулу выросла с 2.45 до 3.04 ₽. То есть платили ровно за прогревы.
#
# Время на этой машине — UTC (`timedatectl`). Окно 09–15 UTC = 12–18 МСК.
#
#   batch_window.sh up     # поднять batch-группы
#   batch_window.sh down   # погасить их (low не трогаем — они работают круглосуточно)
set -euo pipefail

# Список групп с окном — из ОДНОГО источника (rules/salad-groups.json через salad_groups.py);
# MESH_BATCH_GROUPS — только переопределение для ручных опытов.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${MESH_PY:-$HOME/venvs/scout/bin/python}"
GROUPS="${MESH_BATCH_GROUPS:-$("$PY" "$HERE/salad_groups.py" --windowed 2>/dev/null)}"
[ -n "$GROUPS" ] || { echo "нет групп с окном ни в rules/salad-groups.json, ни в MESH_BATCH_GROUPS" >&2; exit 2; }
BASE="https://api.salad.com/api/public/organizations/prodstore/projects/dmodel/containers"
LOG="${MESH_BATCH_LOG:-$HOME/igor/remlab/.memory_bank/_intake/batch-window.log}"
HALT="$HOME/scout-scenes/mesh-group-halt.json"

# shellcheck disable=SC1090
set -a && . "$HOME/scout-scenes/salad.env" && set +a

say() { echo "$(date '+%d.%m %H:%M') $*" | tee -a "$LOG"; }

action="${1:-}"
case "$action" in
  up)
    # СТОП-ФАЙЛ СИЛЬНЕЕ РАСПИСАНИЯ. Если сторож денег погасил пул, значит он не отдавал меши;
    # поднимать по будильнику, не разобравшись, — ровно то, из-за чего 03.09 ноды семь часов
    # крутились впустую (ADR-0174).
    if [ -f "$HALT" ]; then
      say "ПОДЪЁМ ОТМЕНЁН: есть запрет сторожа денег ($HALT) — сперва разберись, почему не было мешей"
      bash "$HERE/../alert.sh" "Меши: окно дешёвого тарифа открылось, но стоит запрет сторожа — batch-группы НЕ подняты. Сними запрет (rm $HALT), разобравшись в причине." || true
      exit 0
    fi
    # ПОДНИМАЕМ ТОЛЬКО ПРИ ЖИВОМ КОНВЕЙЕРЕ (04.09): без него машины прогреются и через 20 минут
    # их погасит idle_guard — деньги на прогрев впустую, а окно схлопнется до этих 20 минут.
    if ! pgrep -f "[b]atch_show.py" >/dev/null; then
      say "ПОДЪЁМ ОТМЕНЁН: конвейера (batch_show.py) нет — поднимать некому раздавать"
      bash "$HERE/../alert.sh" "Меши: окно дешёвого тарифа открылось, а конвейер не работает — batch-группы НЕ подняты. Запусти конвейер, он поднимет их сам." || true
      exit 0
    fi
    for g in $GROUPS; do
      code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Salad-Api-Key: $SALAD_API_KEY" \
             -d '' "$BASE/$g/start" || echo 000)
      say "старт $g: HTTP $code"      # 400 = уже запущена, это не ошибка
    done
    ;;
  down)
    for g in $GROUPS; do
      code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Salad-Api-Key: $SALAD_API_KEY" \
             -d '' "$BASE/$g/stop" || echo 000)
      say "стоп $g: HTTP $code"
    done
    ;;
  *)
    echo "использование: $0 up|down" >&2
    exit 2
    ;;
esac

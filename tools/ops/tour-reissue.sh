#!/usr/bin/env bash
# АВТОПЕРЕВЫПУСК ТУРОВ ПОСЛЕ ВЫКЛАДКИ ДЕМО (T-20261112-92, план `plans/tour-auto-reissue-01.md`; владелец 12.11 TG 873: «Поправил
# тумбу — это должно везде автоматически работать»). Все живые туры агентов пересобираются «как есть» (выбор мебели и правки агента
# сохраняются, `tools/floorplan/reissue.py`) и закрепляются на ТЕКУЩЕЙ витрине /demo. Зовут: ночь — шаг `tour_reissue` в
# `tools/scout/refresh_daily.sh` сразу после `flat215_publish`; день — хук в конце `tools/scout/publish_demo.sh` (фоном, своим юнитом).
#
#   tools/ops/tour-reissue.sh [--why <причина>] [--dry-run] [--days N]
#
# Что делает:
#   • замок `~/.remlab-tour-reissue.lock`: второй запуск во время прохода не идёт параллельно, а ставит отметку «ещё проход» —
#     по окончании проход повторяется (три выкладки подряд = два прохода; не больше 3 проходов на запуск);
#   • окружение воркера (`~/.config/remlab/env`, файл не печатается; урок 608) + адрес и папка, как в юните remlab-trial-worker;
#   • очередь тяжёлых прогонов DEV один раз на весь проход: `--cores 4` (подбор ракурсов идёт 4 процессами node и вложенную очередь
#     не ждёт), `--min-gb 1` (замер 12.11: сборщик 0,14 ГБ + ракурсы 4×node ≤ 0,36 ГБ), долгий (nice 10), приоритет обычный;
#   • `reissue.py --days 60 --cards batch`: снимки карточек — одной службой после прохода и только у туров, где что-то поменялось;
#   • проверка «демо и туры одинаковы» (`tools/ops/tour_reissue_check.py` + имя витрины `tools/ops/demo-release-hash.mjs`);
#   • итог: строки `tour_reissue: …` и `DIGEST:` (ночная сводка), отказ/сбой/расхождение — `WARN:tour_reissue: …` с id туров; днём
#     такой итог уходит тревогой (`tools/scout/alert.sh`), ночью — важной строкой сводки `DIGEST:!`; каждый проход — строка в
#     `~/remlab-logs/trial/reissue.log`. Код выхода 1 — был отказ/сбой или проход не дождался очереди (как у reissue.py).
# Подмены для самопроверки (`tools/ops/tour-reissue-selftest.sh`): TOUR_REISSUE_CMD (вместо reissue.py), TOUR_REISSUE_HASH_CMD,
# TOUR_REISSUE_ALERT, TOUR_REISSUE_ENV, TOUR_REISSUE_LOGS, TOUR_REISSUE_LOCK, TOUR_REISSUE_NO_SLOT=1, TOUR_REISSUE_DEMO_URL.
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)

WHY=ручной; DAYS=60; DRY=()
while [ $# -gt 0 ]; do
  case "$1" in
    --why) WHY=${2:-ручной}; shift 2 ;;
    --dry-run) DRY=(--dry-run); shift ;;
    --days) DAYS=${2:?}; shift 2 ;;
    *) echo "tour-reissue: неизвестный ключ $1 (есть --why, --dry-run, --days)"; exit 2 ;;
  esac
done

PY=${TOUR_REISSUE_PY:-$HOME/venvs/scout/bin/python}
NODE_BIN=$(command -v node 2>/dev/null || true)
[ -z "$NODE_BIN" ] && [ -x /usr/local/bin/node ] && NODE_BIN=/usr/local/bin/node   # в кроне PATH короткий
LOGS=${TOUR_REISSUE_LOGS:-$HOME/remlab-logs/trial}
LOCK=${TOUR_REISSUE_LOCK:-$HOME/.remlab-tour-reissue.lock}
AGAIN="$LOCK.again"
DEMO_URL=${TOUR_REISSUE_DEMO_URL:-https://remont-lab.online/demo/}
ENVF=${TOUR_REISSUE_ENV:-$HOME/.config/remlab/env}
ALERT=${TOUR_REISSUE_ALERT:-$ROOT/tools/scout/alert.sh}
NIGHT=${TOUR_REISSUE_NIGHT:-0}
PASSES=${TOUR_REISSUE_PASSES:-0}            # сколько проходов уже было у этого запуска (повтор после замка — exec сам себя)

exec 9>>"$LOCK"
if ! flock -n 9; then
  : > "$AGAIN"
  echo "tour_reissue: проход уже идёт — после него будет ещё один (повод: $WHY)"
  exit 0
fi

if [ -f "$ENVF" ]; then set -a; . "$ENVF"; set +a; fi
export TRIAL_API_URL=${TRIAL_API_URL:-https://remont-lab.online} TRIAL_WORK_DIR=${TRIAL_WORK_DIR:-$HOME/remlab-logs/trial}
export PYTHONUNBUFFERED=1 TMPDIR=${TOUR_REISSUE_TMP:-$HOME/remlab-scratch/tmp}
mkdir -p "$TMPDIR" "$LOGS/reissue"

if [ -n "${TOUR_REISSUE_CMD:-}" ]; then REISSUE=("$TOUR_REISSUE_CMD"); else REISSUE=("$PY" -u "$ROOT/tools/floorplan/reissue.py"); fi
if [ "${TOUR_REISSUE_NO_SLOT:-0}" = 1 ]; then SLOT=()
else SLOT=(bash "$HERE/heavy-slot.sh" tour-reissue --min-gb 1 --cores 4 --long --timeout 7200 --); fi
if [ -n "${TOUR_REISSUE_HASH_CMD:-}" ]; then HASH=("$TOUR_REISSUE_HASH_CMD"); else HASH=("${NODE_BIN:-node}" "$HERE/demo-release-hash.mjs" --url); fi

worst=0
while :; do
  PASSES=$((PASSES + 1))
  rm -f "$AGAIN"
  RUN="$LOGS/reissue/$(date +%Y%m%d-%H%M%S)-auto"
  mkdir -p "$RUN"
  t0=$(date +%s)
  "${SLOT[@]}" "${REISSUE[@]}" --days "$DAYS" --cards batch "${DRY[@]}" --out "$RUN" > "$RUN/pass.log" 2>&1
  rc=$?
  sec=$(( $(date +%s) - t0 ))
  expect=$("${HASH[@]}" "$DEMO_URL" 2>>"$RUN/pass.log") || expect=-
  [[ "$expect" =~ ^[0-9a-f]{32}$ ]] || expect=-
  out=$("$PY" "$HERE/tour_reissue_check.py" --run "$RUN" --expect "$expect" --demo-data "${DEMO_URL}demo-data.json" 2>&1)
  [ "$rc" = 124 ] && out+=$'\n'"WARN:tour_reissue: очередь тяжёлых прогонов не дала места за 2 ч — туры не перевыпущены"
  [ "$expect" = - ] && [ ${#DRY[@]} = 0 ] && out+=$'\n'"WARN:tour_reissue: имя витрины /demo не получено — «демо = туры» по странице не сверено"
  head=$(printf '%s\n' "$out" | grep -m1 '^tour_reissue:' || echo "tour_reissue: отчёта прохода нет (код $rc)")
  head="$head · ${sec} с · повод: $WHY${DRY:+ · сухой прогон}"
  printf '%s\n' "$out" | grep -v '^tour_reissue:'
  echo "$head"
  echo "DIGEST:$head"
  echo "$(date '+%F %T') $head · $RUN" >> "$LOGS/reissue.log"
  warns=$(printf '%s\n' "$out" | grep '^WARN:' || true)
  if [ -n "$warns" ]; then
    n=$(printf '%s\n' "$warns" | grep -c .)
    first=$(printf '%s\n' "$warns" | head -1 | sed 's/^WARN:tour_reissue: //')
    if [ "$NIGHT" = 1 ]; then echo "DIGEST:!Туры после выкладки демо: $n замечаний, первое — $first"
    else bash "$ALERT" "Туры после выкладки демо: $head. Замечаний $n, первое — $first. Отчёт: $RUN" >/dev/null 2>&1 || true; fi
  fi
  [ "$rc" != 0 ] && worst=1
  { [ -f "$AGAIN" ] && [ "$PASSES" -lt 3 ]; } || break
  echo "tour_reissue: пока шёл проход, демо выложили ещё раз — повторный проход"
done

exec 9>&-
# отметка могла появиться между последней проверкой и снятием замка — не теряем выкладку
if [ -f "$AGAIN" ] && [ "$PASSES" -lt 3 ]; then
  TOUR_REISSUE_PASSES=$PASSES exec bash "${BASH_SOURCE[0]}" --why "$WHY (повтор)" --days "$DAYS" "${DRY[@]}"
fi
exit "$worst"

#!/usr/bin/env bash
# АВТОПЕРЕВЫПУСК ТУРОВ ПОСЛЕ ВЫКЛАДКИ ДЕМО (T-20261112-92, план `plans/tour-auto-reissue-01.md`; владелец 12.11 TG 873: «Поправил
# тумбу — это должно везде автоматически работать»). Все живые туры агентов пересобираются «как есть» (выбор мебели и правки агента
# сохраняются, `tools/floorplan/reissue.py`) и закрепляются на ТЕКУЩЕЙ витрине /demo. Зовут ФОНОМ (`--bg`): ночь — шаг `tour_reissue`
# в `tools/scout/refresh_daily.sh` сразу после `flat215_publish`; день — хук в конце `tools/scout/publish_demo.sh`. Ни ночь, ни
# выкладка не ждут прохода (ожидание очереди тяжёлых прогонов — до 2 ч, проход — десятки минут).
#
#   tools/ops/tour-reissue.sh [--bg] [--why <причина>] [--dry-run] [--days N]
#
# Что делает:
#   • `--bg` — запускает сам себя отдельным юнитом `systemd-run --user` (`remlab-tour-reissue-<время>`; переживает закрытие сессии,
#     виден в `systemctl --user list-units 'remlab-tour-reissue*'`), без systemd — через setsid; печатает «запущен» и выходит;
#   • замок `~/.remlab-tour-reissue.lock`: второй запуск во время прохода не идёт параллельно, а ставит отметку «ещё проход» —
#     по окончании проход повторяется (три выкладки подряд = два прохода; не больше 3 проходов на запуск). Дескриптор замка
#     дочерним процессам НЕ передаётся (`9>&-`): зависший потомок не держит замок и не останавливает будущие перевыпуски;
#   • окружение воркера (`~/.config/remlab/env`, файл не печатается; урок 608) + адрес и папка, как в юните remlab-trial-worker;
#   • очередь тяжёлых прогонов DEV один раз на весь проход: `--cores 4` (подбор ракурсов идёт 4 процессами node и вложенную очередь
#     не ждёт), `--min-gb 1` (замер 12.11: пик дерева 0,29 ГБ, RSS 0,38), долгий (nice 10), приоритет обычный;
#   • `reissue.py --days 60 --cards batch`: снимки карточек — одной службой после прохода и только у туров, где что-то поменялось;
#   • проверка «демо и туры одинаковы» (`tools/ops/tour_reissue_check.py` + имя витрины `tools/ops/demo-release-hash.mjs`);
#   • итог: строки `tour_reissue: …`; каждый проход — строка в `~/remlab-logs/trial/reissue.log` (поля через TAB: время, ok|warn,
#     итог, первое замечание, папка прохода) — ночная сводка (`tools/scout/refresh_digest.py:tour_passes`) берёт оттуда проходы за
#     сутки; отказ/сбой/расхождение — `WARN:tour_reissue: …` с id туров, днём ещё и тревога (`tools/scout/alert.sh`), ночной проход
#     тревогу не шлёт — его замечания уходят важной строкой в сводку следующей ночи. Код выхода 1 — был отказ/сбой или проход не
#     дождался очереди (как у reissue.py).
# Подмены для самопроверки (`tools/ops/tour-reissue-selftest.sh`): TOUR_REISSUE_CMD (вместо reissue.py), TOUR_REISSUE_HASH_CMD,
# TOUR_REISSUE_ALERT, TOUR_REISSUE_ENV, TOUR_REISSUE_LOGS, TOUR_REISSUE_LOCK, TOUR_REISSUE_NO_SLOT=1, TOUR_REISSUE_DEMO_URL,
# TOUR_REISSUE_NO_SYSTEMD=1 (`--bg` — сразу через setsid).
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd "$HERE/../.." && pwd)
SELF="$HERE/$(basename "${BASH_SOURCE[0]}")"

WHY=ручной; DAYS=60; DRY=(); BG=0
while [ $# -gt 0 ]; do
  case "$1" in
    --bg) BG=1; shift ;;
    --why) WHY=${2:-ручной}; shift 2 ;;
    --dry-run) DRY=(--dry-run); shift ;;
    --days) DAYS=${2:?}; shift 2 ;;
    *) echo "tour-reissue: неизвестный ключ $1 (есть --bg, --why, --dry-run, --days)"; exit 2 ;;
  esac
done

LOGS=${TOUR_REISSUE_LOGS:-$HOME/remlab-logs/trial}

if [ "$BG" = 1 ]; then
  ARGS=(--why "$WHY" --days "$DAYS" "${DRY[@]}")
  if [ "${TOUR_REISSUE_NO_SYSTEMD:-0}" != 1 ]; then
    export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}   # из крона без него systemd-run --user не находит менеджер
    unit="remlab-tour-reissue-$(date +%Y%m%d-%H%M%S)"
    E=()   # юнит окружение не наследует: передаём только заданные TOUR_REISSUE_* (ночной режим, подмены)
    for n in $(compgen -e | grep '^TOUR_REISSUE_' || true); do E+=(-E "$n"); done
    if systemd-run --user --collect --quiet --unit "$unit" --nice=10 "${E[@]}" -- bash "$SELF" "${ARGS[@]}" 2>/dev/null; then
      echo "tour_reissue: проход запущен в фоне ($unit; итог — $LOGS/reissue.log, повод: $WHY)"
      exit 0
    fi
  fi
  mkdir -p "$LOGS" 2>/dev/null || true
  setsid nohup bash "$SELF" "${ARGS[@]}" >> "$LOGS/reissue-bg.log" 2>&1 < /dev/null &
  echo "tour_reissue: проход запущен в фоне без systemd (журнал $LOGS/reissue-bg.log, итог — $LOGS/reissue.log, повод: $WHY)"
  exit 0
fi

PY=${TOUR_REISSUE_PY:-$HOME/venvs/scout/bin/python}
NODE_BIN=$(command -v node 2>/dev/null || true)
[ -z "$NODE_BIN" ] && [ -x /usr/local/bin/node ] && NODE_BIN=/usr/local/bin/node   # в кроне PATH короткий
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
  RUN="$LOGS/reissue/$(date +%Y%m%d-%H%M%S)-$$-auto"   # номер процесса: два прохода в одну секунду — разные папки
  mkdir -p "$RUN"
  t0=$(date +%s)
  # 9>&- у КАЖДОГО дочернего: замок держит только этот процесс, потомки (браузеры, node, службы карточек) его не наследуют
  "${SLOT[@]}" "${REISSUE[@]}" --days "$DAYS" --cards batch "${DRY[@]}" --out "$RUN" > "$RUN/pass.log" 2>&1 9>&-
  rc=$?
  sec=$(( $(date +%s) - t0 ))
  expect=$("${HASH[@]}" "$DEMO_URL" 2>>"$RUN/pass.log" 9>&-) || expect=-
  [[ "$expect" =~ ^[0-9a-f]{32}$ ]] || expect=-
  out=$("$PY" "$HERE/tour_reissue_check.py" --run "$RUN" --expect "$expect" --demo-data "${DEMO_URL}demo-data.json" 2>&1 9>&-)
  [ "$rc" = 124 ] && out+=$'\n'"WARN:tour_reissue: очередь тяжёлых прогонов не дала места за 2 ч — туры не перевыпущены"
  [ "$expect" = - ] && [ ${#DRY[@]} = 0 ] && out+=$'\n'"WARN:tour_reissue: имя витрины /demo не получено — «демо = туры» по странице не сверено"
  head=$(printf '%s\n' "$out" | grep -m1 '^tour_reissue:' || echo "tour_reissue: отчёта прохода нет (код $rc)")
  head="$head · ${sec} с · повод: $WHY${DRY:+ · сухой прогон}"
  printf '%s\n' "$out" | grep -v '^tour_reissue:'
  echo "$head"
  warns=$(printf '%s\n' "$out" | grep '^WARN:' || true)
  n=0; first=''
  if [ -n "$warns" ]; then
    n=$(printf '%s\n' "$warns" | grep -c .)
    first=$(printf '%s\n' "$warns" | head -1 | sed 's/^WARN:tour_reissue: //' | tr '\t' ' ')
    [ "$NIGHT" = 1 ] || bash "$ALERT" "Туры после выкладки демо: $head. Замечаний $n, первое — $first. Отчёт: $RUN" >/dev/null 2>&1 9>&- || true
  fi
  printf '%s\t%s\t%s\t%s\t%s\n' "$(date '+%F %T')" "$([ "$n" = 0 ] && echo ok || echo warn)" "$head" \
    "${first:+замечаний $n, первое — $first}" "$RUN" >> "$LOGS/reissue.log"
  [ "$rc" != 0 ] && worst=1
  { [ -f "$AGAIN" ] && [ "$PASSES" -lt 3 ]; } || break
  echo "tour_reissue: пока шёл проход, демо выложили ещё раз — повторный проход"
done

exec 9>&-
# отметка могла появиться между последней проверкой и снятием замка — не теряем выкладку
if [ -f "$AGAIN" ] && [ "$PASSES" -lt 3 ]; then
  TOUR_REISSUE_PASSES=$PASSES exec bash "$SELF" --why "$WHY (повтор)" --days "$DAYS" "${DRY[@]}"
fi
exit "$worst"

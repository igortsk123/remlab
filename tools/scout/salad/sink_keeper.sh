#!/usr/bin/env bash
# СТОРОЖ ПРИЁМНИКА — очистка транзита, когда конвейера нет.
#
# ЗАЧЕМ (04.09, инцидент 18:10 UTC). Вся цепочка очистки жила ТОЛЬКО внутри `batch_show`
# (`post_steps()`), в кроне её не было. Получался замкнутый круг: приёмник переполнился →
# сторож денег погасил группы (стоп-файл) → конвейер вышел → чистка ушла вместе с ним →
# приёмник остался полным. Разрывал круг только человек, руками. Этот скрипт — подмена
# конвейера в той самой дыре.
#
# ПОЧЕМУ НЕ ПАРАЛЛЕЛЬНО С КОНВЕЙЕРОМ. Когда `batch_show` жив, он чистит сам, теми же шагами.
# Второй исполнитель принёс бы гонки: `drain.sh` отпускает свой замок ДО записи в базу, а
# `ingest_registry`/`mesh_bind` пишут отдельными транзакциями (разбор Codex 04.09). Поэтому
# здесь простое правило: конвейер жив — выходим молча. Никакой общей блокировки не требуется.
#
# ПОРЯДОК ШАГОВ — КАК У КОНВЕЙЕРА, И ОН ОБЯЗАТЕЛЕН (правило владельца 01.09: копирование →
# база → сверка → удаление). Пропуск «приёмки» (`apply_repairs`) ломает всю цепочку: без её
# вердикта база не проставляет `mesh_status`, а `receiver_purge` удаляет только помеченное —
# и честно удаляет НОЛЬ (поймано 04.09: «нет в базе 161»).
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${MESH_PY:-$HOME/venvs/scout/bin/python}"
ENVFILE="${MESH_ENV:-$HOME/scout-scenes/salad.env}"
LOG="${MESH_KEEPER_LOG:-$HOME/scout-scenes/sink-keeper.log}"
LOCK="$HOME/scout-scenes/.sink_keeper.lock"
# С какого размера каталога начинаем уборку на ЗЕЛЁНОМ приёмнике. Тот же порог, при котором
# `receiver_purge` снимает срок хранения (`MESH_RECV_DIR_TIGHT_GB`). Вынесен в переменную,
# чтобы поведение можно было проверить, не дожидаясь настоящего переполнения.
TRIGGER_GB="${MESH_KEEPER_DIR_GB:-6.0}"

# Токен приёмника берётся из переменных группы Salad (`sink_health.sink_token`), а ключ и имя
# группы — отсюда. Без них удаление через API невозможно.
[ -f "$ENVFILE" ] && { set -a; . "$ENVFILE"; set +a; }

say() { printf '%s %s\n' "$(date -u '+%F %T')" "$*" >>"$LOG"; }

# ОДИН СТОРОЖ НА МАШИНУ. Не ждём: следующий тик через 15 минут, копить очередь незачем.
exec 9>"$LOCK"
flock -n 9 || exit 0

# КОНВЕЙЕР ЖИВ — НЕ ЛЕЗЕМ. `[b]atch_show` в шаблоне, чтобы grep не нашёл сам себя.
if pgrep -f '[b]atch_show\.py' >/dev/null 2>&1; then
  exit 0
fi

# Дальше зовём `sink_health` как модуль — он лежит рядом, поэтому работаем из своего каталога.
cd "$HERE" || exit 0

BEFORE="$("$PY" -c "import sink_health,json;r=sink_health.check();print(json.dumps({'ok':r['ok'],'dir':r['dir_gb']}))" 2>/dev/null)"
case "$BEFORE" in
  *'"ok": true'*|*'"ok":true'*)
    # Зелёный приёмник — чистим только если каталог уже подрос: держим кэш «уже сделано»,
    # он экономит GPU на повторах. Порог — тот же, при котором purge снимает срок хранения.
    DIR="$(printf '%s' "$BEFORE" | sed -n 's/.*"dir": *\([0-9.]*\).*/\1/p')"
    awk -v d="${DIR:-0}" -v t="$TRIGGER_GB" 'BEGIN{exit !(d+0 >= t+0)}' || exit 0
    ;;
esac

say "старт (приёмник: ${BEFORE:-неизвестно})"
FAIL=0
run() {  # run <имя> <дедлайн_сек> <команда...>
  local name="$1" deadline="$2"; shift 2
  local out
  out="$(nice -n 10 ionice -c3 timeout "$deadline" "$@" 2>&1 | tail -3)"
  local rc=$?
  say "  $name: rc=$rc ${out//$'\n'/ | }"
  [ "$rc" -ne 0 ] && FAIL=1
  return 0
}

run "стаскиваю"        1200 bash "$HERE/drain.sh" --keep
run "реестр"            600 "$PY" "$HERE/ingest_registry.py"
run "приёмка"          1800 "$PY" "$HERE/apply_repairs.py"
run "пометка в базе"    600 "$PY" "$HERE/../mesh_bind.py"
run "чистка приёмника"  900 "$PY" "$HERE/receiver_purge.py" --apply

AFTER="$("$PY" -c "import sink_health,json;r=sink_health.check();print(json.dumps({'ok':r['ok'],'dir':r['dir_gb']}))" 2>/dev/null)"
say "финиш (приёмник: ${AFTER:-неизвестно}, сбоев шагов: $FAIL)"

# Тревога — только когда после уборки приёмник ВСЁ ЕЩЁ красный: это значит, что автоматика
# исчерпала свои средства и дальше нужен человек. Недоставка тревоги не должна валить скрипт.
case "$AFTER" in
  *'"ok": false'*|*'"ok":false'*)
    bash "$HERE/../alert.sh" "Меши: приёмник красный ПОСЛЕ уборки сторожем ($AFTER). Конвейера нет, сам себя не вылечит — нужен разбор." || true
    ;;
esac
exit 0

#!/usr/bin/env bash
# Публикация демо планировщика на прод-статик. Живой путь — /opt/remlab/demo (08.09, план
# demo-permalink: демо уехало из служебной /test в свою папку, адрес — /demo).
#
#   publish_demo.sh                    — опубликовать сборку (перед этим на сервере копия прежней: <папка>.prev-<метка>)
#   publish_demo.sh --list             — какие копии есть
#   publish_demo.sh --rollback [метка] — вернуть копию (без метки — самую свежую обычную; повтор — ещё на шаг назад);
#                                        то, что было до отката, ложится в `<папка>.prev-<метка>-undo` — отмена отката —
#                                        `--rollback <метка>-undo`, он её напечатает
# Настройки (окружение): PUB_DIR — папка на сервере, `demo` (по умолчанию) или `test/<имя>` для пробы; PUB_SRC — что
# публиковать (по умолчанию ~/scout-scenes/flat215-demo); PUB_KEEP — сколько копий хранить (3). Для самопроверки —
# PUB_ROOT, PUB_RTMP, PUB_CHOWN, PUB_URL (`tests/test_publish_demo.py`, ssh/scp/curl подменены).
#
# ТОП-СПРАЙТЫ ПЕРЕЖИВАЮТ ПУБЛИКАЦИЮ (01.09). `rm -rf flat215-demo` чистил и `topsprites/`,
# а туда виды сверху приезжают ОТДЕЛЬНО, прямым scp из мешевого конвейера
# (`salad/batch_show.py`, шаг «ориент-паблиш»), и в локальной сборке их всегда меньше:
# на замере 01.09 локально лежало 123 спрайта против 271 на проде — публикация стёрла бы 148,
# включая только что отрисованные. Та же болезнь, что у реестров (`salad/publish_merge.py`):
# частичная локальная копия ложится поверх более полной удалённой. Поэтому спрайты уносим в
# сторону, каталог обновляем начисто (чтобы удалённые файлы кода не оставались), и возвращаем
# спрайты объединением — свежая версия побеждает, старые не теряются.
# КАТАЛОГ ОБНОВЛЯЕМ НА МЕСТЕ, НЕ ПОДМЕНЯЕМ (08.09). `rm -rf demo && mv` менял inode каталога, а он
# смонтирован в контейнер Caddy (`./demo:/srv/demo:ro`): контейнер продолжал держать УДАЛЁННЫЙ
# каталог и отдавал 404, пока его не перезапустишь. rsync правит содержимое внутри той же точки
# монтирования. `--delete` убирает файлы, исчезнувшие из сборки, а `topsprites` исключены: виды
# сверху приезжают ОТДЕЛЬНО из мешевого конвейера (`salad/batch_show.py`), и локально их меньше.
#
# КОПИЯ ПРЕЖНЕЙ ВЕРСИИ И ОТКАТ (T-20261105-59). Раньше плохая ночная сборка ложилась поверх живого демо
# `rsync --delete`, и пути назад не было. Теперь перед rsync на сервере — полная копия текущей папки (без topsprites:
# они не наши и их не откатываем) в `<папка>.prev-<метка UTC>` рядом, вне точки монтирования; хранятся PUB_KEEP
# последних, старшие скрипт убирает сам — только папки по точному шаблону `<имя>.prev-ГГГГММДД-ЧЧММСС`.
# Копия полная, не жёсткими ссылками: файл живой папки, переписанный на месте (`cp` поверх, scp), поменял бы и копию.
# ОТКАТ — ПЕРЕНОСОМ (mv), НЕ rsync ПОВЕРХ, НО ВНУТРИ ТОЙ ЖЕ ПАПКИ: сам каталог `demo` подменять нельзя (inode и
# монтирование Caddy, абзац выше). Поэтому переставляем его СОДЕРЖИМОЕ: файл копии встаёт на место живого одним
# rename (атомарно, без мгновения «файла нет»); живой перед этим уходит жёсткой ссылкой в новую копию «до отката»;
# подпапки — двумя rename. Данные не копируются, откат занимает доли секунды и сам обратим.
# Публикация и откат одной папки не идут одновременно — flock на сервере.
set -euo pipefail
HOST=root@89.167.127.0
PORT=22222
PUB_DIR=${PUB_DIR:-demo}
PUB_SRC=${PUB_SRC:-$HOME/scout-scenes/flat215-demo}
PUB_KEEP=${PUB_KEEP:-3}
PUB_ROOT=${PUB_ROOT:-/opt/remlab}
PUB_RTMP=${PUB_RTMP:-/tmp}
PUB_CHOWN=${PUB_CHOWN-1000:1000}
# куда можно: главная витрина или папка проб под /test/ — ничего другого скрипт не трогает (Caddy, приложение, VPN-нода)
[[ "$PUB_DIR" =~ ^(demo|test/[A-Za-z0-9][A-Za-z0-9._-]*)$ ]] && [[ "$PUB_DIR" != *..* ]] \
  || { echo "PUB_DIR=$PUB_DIR: можно только demo или test/<имя>"; exit 2; }
[[ "$PUB_KEEP" =~ ^[1-9][0-9]?$ ]] || { echo "PUB_KEEP=$PUB_KEEP: число 1..99"; exit 2; }
for v in "$PUB_ROOT" "$PUB_RTMP" "$PUB_CHOWN"; do   # идут в командную строку ssh — только простые символы
  [[ "$v" =~ ^[A-Za-z0-9/._:-]*$ ]] || { echo "недопустимые символы в настройке: $v"; exit 2; }
done
if [ -z "${PUB_URL:-}" ]; then
  if [ "$PUB_DIR" = demo ]; then PUB_URL=https://remont-lab.online/demo/; else PUB_URL="https://remont-lab.online/$PUB_DIR/"; fi
fi
SSH=(ssh -p "$PORT" -o StrictHostKeyChecking=no "$HOST")

# Серверная часть — одним скриптом через stdin (аргументы позиционные, без подстановки в текст команды).
remote() {  # remote <действие> [метка]
  "${SSH[@]}" "bash -s -- '$1' '${2:-}' '$PUB_ROOT' '$PUB_DIR' '$PUB_KEEP' '$PUB_CHOWN' '$PUB_RTMP'" <<'REMOTE'
set -euo pipefail
ACT=$1 ARG=$2 ROOT=$3 DIR=$4 KEEP=$5 OWN=$6 RTMP=$7
LIVE="$ROOT/$DIR"; PAR=$(dirname "$LIVE"); NAME=$(basename "$LIVE")
STAGE="$PAR/.$NAME-new"; TGZ="$RTMP/remlab-pub-$NAME.tgz"
NAME_RE=$(printf '%s' "$NAME" | sed 's/[.]/\\./g')
mkdir -p "$PAR"
exec 9>"$PAR/.$NAME.publish.lock"
flock -w 600 9 || { echo "папка $DIR занята другой публикацией/откатом дольше 10 мин"; exit 1; }
stamp() { date -u +%Y%m%d-%H%M%S; }
# копии: `<имя>.prev-<метка>` — перед публикацией; `<имя>.prev-<метка>-undo` — «до отката» (откат без метки их не берёт,
# поэтому второй --rollback подряд уходит ещё на шаг назад, а не возвращает плохую версию)
KIND_RE='^[0-9]{8}-[0-9]{6}$'; UNDO_RE='^[0-9]{8}-[0-9]{6}-undo$'
prevs() {  # prevs reg|undo|all — копии этой папки, старые → новые (только точный шаблон)
  local d b t
  for d in "$PAR/$NAME".prev-*; do
    b=$(basename "$d"); t=${b#"$NAME".prev-}
    [ -d "$d" ] && [[ "$b" =~ ^${NAME_RE}\.prev- ]] || continue
    case "$1" in
      reg) [[ "$t" =~ $KIND_RE ]] || continue ;;
      undo) [[ "$t" =~ $UNDO_RE ]] || continue ;;
      *) [[ "$t" =~ $KIND_RE || "$t" =~ $UNDO_RE ]] || continue ;;
    esac
    echo "$d"
  done | sort   # (`continue` последним — код 0: под pipefail ложная проверка в конце цикла валила бы скрипт)
}
prune() {  # хранить KEEP обычных и KEEP «до отката»; старшие — убрать (только по точному шаблону из prevs)
  local k n
  for k in reg undo; do
    n=$(prevs "$k" | wc -l)
    [ "$n" -gt "$KEEP" ] || continue
    prevs "$k" | head -n $((n - KEEP)) | while read -r d; do rm -rf -- "$d"; echo "убрана старая копия: $(basename "$d")"; done
  done
}
newprev() {  # newprev [суффикс] — свободное имя копии «сейчас» (две операции в одну секунду — ждём следующую)
  local t; t=$(stamp)
  while [ -e "$PAR/$NAME.prev-$t${1:-}" ] || [ -e "$PAR/$NAME.prev-$t${1:-}.part" ]; do sleep 1; t=$(stamp); done
  echo "$PAR/$NAME.prev-$t${1:-}"
}
own() { [ -z "$OWN" ] || chown -R "$OWN" "$1"; }
case "$ACT" in
  publish)
    rm -rf -- "$STAGE" && mkdir -p "$STAGE" "$LIVE"
    tar xzf "$TGZ" -C "$STAGE" --strip-components=1
    [ -f "$STAGE/index.html" ] || { echo "в архиве нет index.html — не публикуем"; rm -rf -- "$STAGE" "$TGZ"; exit 1; }
    if [ -f "$LIVE/index.html" ]; then
      P=$(newprev)
      rsync -a --exclude topsprites/ "$LIVE/" "$P.part/"
      mv -T "$P.part" "$P"
      echo "копия прежней версии: $(basename "$P")"
    else
      echo "прежней версии нет (первая публикация) — копию не делаем"
    fi
    # --checksum: сверка по содержимому, не «размер+время» — файл того же размера, записанный в ту же секунду, иначе
    # остался бы старым (поймано сухим прогоном T-59 на /test/: lib/scene.js не обновился); витрина без topsprites ~70 МБ
    rsync -a --checksum --delete --exclude topsprites/ "$STAGE/" "$LIVE/"
    rm -rf -- "$STAGE" "$TGZ"
    own "$LIVE"
    prune
    ;;
  rollback)
    if [ -n "$ARG" ]; then
      [[ "$ARG" =~ $KIND_RE || "$ARG" =~ $UNDO_RE ]] || { echo "метка $ARG: нужен вид ГГГГММДД-ЧЧММСС[-undo]"; exit 2; }
      SRC="$PAR/$NAME.prev-$ARG"
    else
      SRC=$(prevs reg | tail -n 1)
    fi
    [ -n "$SRC" ] && [ -d "$SRC" ] || { echo "копии ${ARG:-любой} нет — откатывать не на что"; prevs all | sed 's|.*/|  есть: |'; exit 1; }
    [ -f "$SRC/index.html" ] || { echo "в копии $(basename "$SRC") нет index.html — не откатываем"; exit 1; }
    [ -d "$LIVE" ] || mkdir -p "$LIVE"
    U=$(newprev -undo); mkdir "$U.part"
    isdir() { [ -d "$1" ] && [ ! -L "$1" ]; }
    shopt -s dotglob nullglob
    declare -A INSRC=()
    for e in "$SRC"/*; do INSRC[$(basename "$e")]=1; done
    # 1) живые файлы → копия «до отката» жёсткой ссылкой: на месте они остаются до своей подмены (подпапки — в шаге 2)
    for e in "$LIVE"/*; do
      b=$(basename "$e"); [ "$b" = topsprites ] && continue
      isdir "$e" || ln -- "$e" "$U.part/$b"
    done
    # 2) содержимое копии → на место: файл — одним rename поверх живого; живую подпапку — сперва в копию «до»
    for e in "$SRC"/*; do
      b=$(basename "$e"); [ "$b" = topsprites ] && continue
      if isdir "$LIVE/$b"; then mv -T -- "$LIVE/$b" "$U.part/$b"
      elif isdir "$e" && [ -e "$LIVE/$b" -o -L "$LIVE/$b" ]; then rm -f -- "$LIVE/$b"   # файл на месте папки: он уже в «до»
      fi
      mv -T -- "$e" "$LIVE/$b"
    done
    # 3) чего в копии не было — из живой папки уходит (подпапка — переносом в «до», файл там уже есть ссылкой)
    for e in "$LIVE"/*; do
      b=$(basename "$e"); [ "$b" = topsprites ] && continue
      [ -n "${INSRC[$b]:-}" ] && continue
      if isdir "$e"; then mv -T -- "$e" "$U.part/$b"; else rm -f -- "$e"; fi
    done
    shopt -u dotglob nullglob
    rmdir -- "$SRC" 2>/dev/null || echo "WARN: в копии $(basename "$SRC") осталось лишнее — папка не убрана"
    mv -T "$U.part" "$U"
    own "$LIVE"
    echo "откат на $(basename "$SRC") сделан; копия того, что было до отката: $(basename "$U")"
    echo "отменить откат: publish_demo.sh --rollback ${U##*.prev-}"
    prune
    ;;
  list)
    prevs all | while read -r d; do echo "$(basename "$d")  $(du -sh "$d" | cut -f1)"; done
    ;;
  *) echo "неизвестное действие $ACT"; exit 2 ;;
esac
REMOTE
}

check_http() {
  local code
  code=$(curl -s -o /dev/null -m 25 -w '%{http_code}' "${PUB_URL}?v=$(date +%s)") || true
  [ "$code" = 200 ] || { echo "страница не подтвердилась: HTTP $code ($PUB_URL)"; return 1; }
}

case "${1:-}" in
  --list) remote list; exit 0 ;;
  --rollback)
    [[ -z "${2:-}" || "$2" =~ ^[0-9]{8}-[0-9]{6}(-undo)?$ ]] || { echo "метка $2: нужен вид ГГГГММДД-ЧЧММСС[-undo]"; exit 2; }
    remote rollback "${2:-}"
    check_http || { echo "после отката страница не отвечает — смотри сервер"; exit 1; }
    echo "демо после отката: $PUB_URL"; exit 0 ;;
  "") ;;
  *) echo "неизвестный ключ $1 (есть: --list, --rollback [метка])"; exit 2 ;;
esac

[ -f "$PUB_SRC/index.html" ] || { echo "нет $PUB_SRC/index.html — сборка не выполнялась"; exit 1; }
TGZ=$(mktemp "${TMPDIR:-/tmp}/flat215-demo.XXXX.tgz")
trap 'rm -f "$TGZ"' EXIT
tar czf "$TGZ" -C "$(dirname "$PUB_SRC")" "$(basename "$PUB_SRC")"
scp -P "$PORT" -o StrictHostKeyChecking=no "$TGZ" "$HOST:$PUB_RTMP/remlab-pub-$(basename "$PUB_DIR").tgz"
remote publish
check_http || { echo "публикация не подтвердилась. Вернуть прежнюю версию: PUB_DIR=$PUB_DIR $0 --rollback"; exit 1; }
echo "демо опубликовано: $PUB_URL"

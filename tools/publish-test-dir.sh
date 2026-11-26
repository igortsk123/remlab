#!/usr/bin/env bash
# ВЫКЛАДКА СТРАНИЦЫ-ПАПКИ НА https://remont-lab.online/test/<имя>/ (П1.159; `publish-test.sh` кладёт только плоские файлы,
# `publish_demo.sh` требует demo-data.json — страницы проверок со своими картинками и моделями раньше везли руками).
#
#   publish-test-dir.sh <имя> <папка> [--dry]   — выложить папку (в ней index.html) как /test/<имя>/
#   publish-test-dir.sh --selftest              — сухой прогон БЕЗ сервера: подменённые ssh/scp/curl, «сервер» — временная папка
#
# Порядок: имя и папка (локально) → место и «такого имени ещё нет» на сервере → tgz → scp → распаковка во временную папку
# `.pub-tmp-<имя>` рядом, chown, один `mv -T` на место → проверка по сайту (код 200, index.html байт в байт, самый большой файл
# тем же размером). Существующую папку НЕ перезаписывает (нужно новое имя — или убрать старую руками на сервере). Сбой на сервере —
# временная папка и архив убираются сами; уже выложенное не трогается. --dry: только локальные проверки, сервера не касается.
# Сервер — по known_hosts (ключ хоста должен быть записан заранее: `ssh -p 22222 root@89.167.127.0` один раз руками), проверку
# ключа не отключаем. Настройки для самопроверки: PTD_HOST PTD_PORT PTD_BASE PTD_RTMP PTD_SITE PTD_OWNER PTD_TMP PTD_MAX_MB
# и подмены команд PTD_SSH PTD_SCP PTD_CURL.
set -Eeuo pipefail
HOST=${PTD_HOST:-root@89.167.127.0}
PORT=${PTD_PORT:-22222}
BASE=${PTD_BASE:-/opt/remlab/test}
RTMP=${PTD_RTMP:-/tmp}
SITE=${PTD_SITE:-https://remont-lab.online}
OWNER=${PTD_OWNER-1000:1000}
TMPD=${PTD_TMP:-$HOME/.cache/remlab-publish}
MAX_MB=${PTD_MAX_MB:-400}
PTD_SSH=${PTD_SSH:-ssh -p $PORT -o BatchMode=yes -o StrictHostKeyChecking=yes}
PTD_SCP=${PTD_SCP:-scp -q -P $PORT -o BatchMode=yes -o StrictHostKeyChecking=yes}
PTD_CURL=${PTD_CURL:-curl -s --max-time 180}
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RESERVED=" rt share status book referee acceptance-plans style-bench demo "
TGZ=""

die() { echo "publish-test-dir: $*" >&2; exit "${2:-1}"; }

# --- куски, которые бегут НА СЕРВЕРЕ (аргументы — позиционные; одинарных кавычек внутри нет) -----------------------------
REMOTE_PRE='name=$1; base=$2; need=$3
[ -d "$base" ] || { echo "REMOTE_ERR: нет папки $base"; exit 11; }
[ ! -e "$base/$name" ] || { echo "REMOTE_ERR: $base/$name уже есть — не перезаписываю"; exit 12; }
free=$(df -Pm "$base" | awk "NR==2{print \$4}")
echo "FREE_MB=${free:-0}"
[ "${free:-0}" -ge "$need" ] || { echo "REMOTE_ERR: мало места: свободно ${free:-0} МБ, нужно ~$need МБ"; exit 13; }'
REMOTE_PUT='name=$1; base=$2; tgz=$3; owner=$4
tmp="$base/.pub-tmp-$name"
[ ! -e "$base/$name" ] || { echo "REMOTE_ERR: $base/$name уже есть — не перезаписываю"; rm -f -- "$tgz"; exit 12; }
[ ! -e "$tmp" ] || { echo "REMOTE_ERR: $tmp уже есть (чужая выкладка?) — не трогаю"; exit 14; }
trap "rc=\$?; rm -f -- \"$tgz\"; if [ \$rc -ne 0 ]; then rm -rf -- \"$tmp\"; fi" EXIT
mkdir "$tmp"
tar xzf "$tgz" -C "$tmp"
if [ -n "$owner" ]; then chown -R "$owner" "$tmp"; fi
mv -T "$tmp" "$base/$name"
echo REMOTE_OK'

check_name() {
  local n=$1
  [[ "$n" =~ ^[a-z0-9][a-z0-9._-]{0,59}$ ]] && [[ "$n" != *..* ]] || die "имя «$n»: можно a-z 0-9 . _ - (с буквы или цифры, до 60 знаков, без «..»)" 2
  case "$RESERVED" in *" $n "*) die "имя «$n» занято служебной папкой /test/$n" 2;; esac
}

check_dir() {
  local d=$1
  [ -d "$d" ] || die "нет папки $d" 2
  [ -f "$d/index.html" ] || die "нет $d/index.html — нечего открывать"
  [ -z "$(find "$d" -type l -print -quit)" ] || die "в $d есть симлинк ($(find "$d" -type l -print -quit)) — не выкладываем"
  local bad
  bad=$(cd "$d" && find . -type f -printf '%P\n' | grep -vE '^[A-Za-z0-9._/-]+$' | head -1 || true)
  [ -z "$bad" ] || die "в $d файл с недопустимым именем «$bad» (можно A-Za-z0-9 . _ - /)"
  bad=$(cd "$d" && find . -type f -printf '%P\n' | grep -E '(^|/)\.' | head -1 || true)
  [ -z "$bad" ] || die "в $d скрытый файл «$bad» (.env, .git …) — не выкладываем"
}

publish() {
  local name=$1 dir=$2 dry=${3:-0}
  check_name "$name"
  dir=$(cd "$dir" 2>/dev/null && pwd) || die "нет папки $2" 2
  check_dir "$dir"
  local mb files
  mb=$(du -sm "$dir" | cut -f1)
  files=$(find "$dir" -type f | wc -l)
  [ "$mb" -le "$MAX_MB" ] || die "папка $mb МБ > потолка $MAX_MB МБ (PTD_MAX_MB) — не выкладываем"
  echo "папка $dir: $files файлов, $mb МБ → $SITE/test/$name/"
  mkdir -p "$TMPD"
  local free_local
  free_local=$(PATH=/usr/bin:/bin df -Pm "$TMPD" | awk 'NR==2{print $4}')   # настоящий df: в самопроверке «сервер» подменяет df в PATH
  [ "${free_local:-0}" -ge $((mb + 20)) ] || die "мало места под архив в $TMPD: свободно ${free_local:-?} МБ, нужно ~$((mb + 20)) МБ"
  if [ "$dry" = 1 ]; then
    echo "--dry: локальные проверки пройдены; сервера не касались, архив не делали"
    return 0
  fi
  local SSH=($PTD_SSH) SCP=($PTD_SCP) CURL=($PTD_CURL)
  local need=$((mb * 2 + 100))      # распакованное + архив на том же диске + запас
  local out
  out=$(printf '%s\n' "$REMOTE_PRE" | "${SSH[@]}" "$HOST" "bash -s -- '$name' '$BASE' '$need'") \
    || { echo "$out"; die "сервер отказал до загрузки (строка REMOTE_ERR выше); ничего не загружено"; }
  echo "сервер: ${out//$'\n'/ }"
  TGZ=$(mktemp "$TMPD/ptd-$name.XXXXXX.tgz")
  trap 'rm -f -- "${TGZ:-}"' EXIT
  tar czf "$TGZ" -C "$dir" .
  echo "архив: $(du -m "$TGZ" | cut -f1) МБ"
  "${SCP[@]}" "$TGZ" "$HOST:$RTMP/ptd-$name.tgz" || die "scp не удался; на сервере папка не создана"
  out=$(printf '%s\n' "$REMOTE_PUT" | "${SSH[@]}" "$HOST" "bash -s -- '$name' '$BASE' '$RTMP/ptd-$name.tgz' '$OWNER'") \
    || { echo "$out"; die "распаковка на сервере не удалась (временная папка и архив убраны); страница не выложена"; }
  case "$out" in *REMOTE_OK*) ;; *) die "сервер не подтвердил распаковку: $out";; esac
  # проверка по сайту: index байт в байт и самый большой файл — тем же размером
  local url="$SITE/test/$name" got code size tmpf
  tmpf=$(mktemp "$TMPD/ptd-idx.XXXXXX")
  got=$("${CURL[@]}" -o "$tmpf" -w '%{http_code} %{size_download}' "$url/index.html" || true)
  code=${got%% *}
  [ "$code" = 200 ] || { rm -f -- "$tmpf"; die "сайт отдал $code на $url/index.html. Откатить: ssh -p $PORT $HOST \"rm -rf $BASE/$name\""; }
  cmp -s "$tmpf" "$dir/index.html" || { rm -f -- "$tmpf"; die "index.html на сайте не совпал с локальным. Откатить: ssh -p $PORT $HOST \"rm -rf $BASE/$name\""; }
  rm -f -- "$tmpf"
  local big
  big=$(cd "$dir" && find . -type f -printf '%s %P\n' | sort -rn | head -1)
  got=$("${CURL[@]}" -o /dev/null -w '%{http_code} %{size_download}' "$url/${big#* }" || true)
  code=${got%% *}; size=${got##* }
  { [ "$code" = 200 ] && [ "$size" = "${big%% *}" ]; } \
    || die "самый большой файл ${big#* } на сайте: код $code, байт $size (нужно ${big%% *}). Откатить: ssh -p $PORT $HOST \"rm -rf $BASE/$name\""
  echo "выложено: $url/  (index.html совпал, ${big#* } ${big%% *} Б — 200)"
}

# --- самопроверка: сервер — временная папка, ssh/scp/curl подменены; настоящий сервер не трогается ---------------------
selftest() {
  set +e
  local ROOT="${REMLAB_TMP:-$HOME/.cache/remlab-selftest}/ptd.$$"
  mkdir -p "$ROOT/bin" "$ROOT/srv/base" "$ROOT/srv/tmp" "$ROOT/work" "$ROOT/tmp"
  local fails=0 rc out
  ok() { echo "  ok  $1"; }
  bad() { echo "  FAIL $1"; fails=$((fails + 1)); }
  expect() { # <описание> <ожидаемый rc> <rc>
    if [ "$3" = "$2" ]; then ok "$1 (rc=$3)"; else bad "$1: ожидал rc=$2, получил $3"; fi
  }
  # подмены: ssh исполняет последний аргумент локально (stdin — скрипту), scp копирует, curl отдаёт файлы «сервера»
  printf '%s\n' '#!/usr/bin/env bash' 'echo ssh >> "$FAKE_LOG"' 'cmd="${!#}"' 'exec bash -c "$cmd"' > "$ROOT/bin/ssh-fake"
  printf '%s\n' '#!/usr/bin/env bash' 'echo scp >> "$FAKE_LOG"' '[ -z "${FAKE_SCP_FAIL:-}" ] || exit 1' \
    'src="${@: -2:1}"; dst="${@: -1}"; dst="${dst#*:}"; cp -- "$src" "$dst"' > "$ROOT/bin/scp-fake"
  printf '%s\n' '#!/usr/bin/env bash' 'echo curl >> "$FAKE_LOG"' 'out=""; url=""' \
    'while [ $# -gt 0 ]; do case "$1" in -o) out=$2; shift 2;; -w|--max-time) shift 2;; -*) shift;; *) url=$1; shift;; esac; done' \
    'f="$FAKE_BASE/${url#*/test/}"; code=200; [ -f "$f" ] || code=404; [ -z "${FAKE_CURL_CODE:-}" ] || code=$FAKE_CURL_CODE' \
    'size=0; [ -f "$f" ] && size=$(stat -c %s "$f")' \
    'if [ -n "$out" ]; then if [ -f "$f" ]; then cp -- "$f" "$out"; else : > "$out"; fi; [ -z "${FAKE_CURL_TAMPER:-}" ] || echo x > "$out"; fi' \
    'echo "$code $size"' > "$ROOT/bin/curl-fake"
  printf '%s\n' '#!/usr/bin/env bash' 'echo "Filesystem 1M-blocks Used Available Capacity Mounted"' \
    'echo "x 100000 1 ${FAKE_FREE_MB:-90000} 1% /"' > "$ROOT/bin/df"
  chmod +x "$ROOT/bin/ssh-fake" "$ROOT/bin/scp-fake" "$ROOT/bin/curl-fake" "$ROOT/bin/df"
  export FAKE_LOG="$ROOT/log" FAKE_BASE="$ROOT/srv/base"
  : > "$FAKE_LOG"
  # хороший образец: index + картинка + «модель» побольше
  local PG="$ROOT/work/page"
  mkdir -p "$PG/img" "$PG/models"
  printf '%s\n' '<!doctype html><title>t</title><p>проба</p>' > "$PG/index.html"
  printf 'IMG' > "$PG/img/a.webp"
  head -c 300000 /dev/zero | tr '\0' 'm' > "$PG/models/big.glb"
  run() { # env подменён; вызов самого скрипта
    PTD_SSH="$ROOT/bin/ssh-fake" PTD_SCP="$ROOT/bin/scp-fake" PTD_CURL="$ROOT/bin/curl-fake" PTD_BASE="$ROOT/srv/base" \
      PTD_RTMP="$ROOT/srv/tmp" PTD_OWNER="" PTD_TMP="$ROOT/tmp" PATH="$ROOT/bin:$PATH" bash "$HERE/publish-test-dir.sh" "$@" 2>&1
  }
  echo "publish-test-dir selftest:"
  # 1. плохие имена — до всякого сервера
  local n
  for n in "../x" "A b" "-x" "rt" "share" "a..b" "$(printf 'a%.0s' $(seq 1 61))"; do
    out=$(run "$n" "$PG"); rc=$?
    expect "плохое имя «${n:0:12}»" 2 "$rc"
  done
  [ ! -s "$FAKE_LOG" ] && ok "плохие имена: ни ssh, ни scp, ни curl" || bad "плохие имена дошли до сервера"
  # 2. папка без index, с симлинком, со скрытым файлом, с пробелом в имени
  mkdir -p "$ROOT/work/noidx" "$ROOT/work/lnk" "$ROOT/work/hid" "$ROOT/work/sp"
  printf 'x' > "$ROOT/work/noidx/a.txt"
  printf 'x' > "$ROOT/work/lnk/index.html"; ln -s /etc/hostname "$ROOT/work/lnk/h"
  printf 'x' > "$ROOT/work/hid/index.html"; printf 'S=1' > "$ROOT/work/hid/.env"
  printf 'x' > "$ROOT/work/sp/index.html"; printf 'x' > "$ROOT/work/sp/a b.png"
  for n in noidx lnk hid sp; do out=$(run "t-$n" "$ROOT/work/$n"); rc=$?; expect "папка $n отклонена" 1 "$rc"; done
  out=$(run "t-nodir" "$ROOT/work/net-takoy"); rc=$?; expect "нет папки" 2 "$rc"
  # 3. потолок размера
  out=$(PTD_MAX_MB=0 run "t-big" "$PG"); rc=$?; expect "папка больше потолка" 1 "$rc"
  # 4. --dry: ни ssh, ни scp, архив не делается
  out=$(run "t-dry" "$PG" --dry); rc=$?; expect "--dry" 0 "$rc"
  [ ! -s "$FAKE_LOG" ] && [ ! -e "$ROOT/srv/base/t-dry" ] && ok "--dry сервера не касался" || bad "--dry дошёл до сервера"
  # 5. мало места на сервере: ничего не загружено
  out=$(FAKE_FREE_MB=5 run "t-full" "$PG"); rc=$?; expect "мало места на сервере" 1 "$rc"
  [ ! -e "$ROOT/srv/base/t-full" ] && [ -z "$(ls -A "$ROOT/srv/tmp")" ] && ok "при нехватке места ничего не загружено" || bad "при нехватке места что-то осталось"
  # 6. имя занято: чужая папка не тронута
  mkdir -p "$ROOT/srv/base/t-busy"; printf 'OLD' > "$ROOT/srv/base/t-busy/index.html"
  out=$(run "t-busy" "$PG"); rc=$?; expect "имя занято" 1 "$rc"
  [ "$(cat "$ROOT/srv/base/t-busy/index.html")" = OLD ] && ok "занятая папка не изменилась" || bad "занятая папка изменена"
  # 7. scp упал: папки нет, локальный архив убран
  out=$(FAKE_SCP_FAIL=1 run "t-scp" "$PG"); rc=$?; expect "scp упал" 1 "$rc"
  [ ! -e "$ROOT/srv/base/t-scp" ] && [ -z "$(ls -A "$ROOT/tmp")" ] && ok "после сбоя scp: нет папки, нет локального архива" || bad "после сбоя scp остались следы"
  # 8. боевой путь: папка на месте точь-в-точь, временных остатков нет
  out=$(run "t-ok" "$PG"); rc=$?; expect "выкладка" 0 "$rc"
  diff -r "$PG" "$ROOT/srv/base/t-ok" > /dev/null && ok "папка на «сервере» совпала с локальной" || bad "папка не совпала"
  [ -z "$(ls -A "$ROOT/srv/tmp")" ] && [ -z "$(ls -A "$ROOT/tmp")" ] && [ ! -e "$ROOT/srv/base/.pub-tmp-t-ok" ] \
    && ok "архивы и .pub-tmp убраны" || bad "остались архив или .pub-tmp"
  case "$out" in *"выложено:"*"/test/t-ok/"*) ok "печатает адрес";; *) bad "нет строки с адресом: $out";; esac
  # 9. повтор того же имени — отказ, выложенное цело
  out=$(run "t-ok" "$PG"); rc=$?; expect "повтор имени" 1 "$rc"
  diff -r "$PG" "$ROOT/srv/base/t-ok" > /dev/null && ok "после повтора выложенное цело" || bad "повтор испортил выложенное"
  # 10. сайт не подтвердил: код ≠ 200 и подмена index — отказ с подсказкой отката
  out=$(FAKE_CURL_CODE=404 run "t-c404" "$PG"); rc=$?; expect "сайт отдал 404" 1 "$rc"
  case "$out" in *"Откатить"*) ok "подсказка отката";; *) bad "нет подсказки отката: $out";; esac
  out=$(FAKE_CURL_TAMPER=1 run "t-tamper" "$PG"); rc=$?; expect "index на сайте не совпал" 1 "$rc"
  # 11. ключ хоста не отключается (ни в коде, ни в подменах по умолчанию)
  local k="StrictHostKeyChecking"; k="${k}=no"
  [ "$(grep -c -- "$k" "$HERE/publish-test-dir.sh")" = 0 ] && ok "проверка ключа хоста нигде не отключена" || bad "в скрипте есть отключение проверки ключа хоста"
  grep -q "StrictHostKeyChecking=yes" "$HERE/publish-test-dir.sh" && ok "ssh/scp по умолчанию — known_hosts" || bad "нет StrictHostKeyChecking=yes"
  echo "publish-test-dir selftest: провалов $fails"
  if [ "$fails" = 0 ]; then rm -rf -- "$ROOT"; else echo "оставлено для разбора: $ROOT"; fi
  [ "$fails" = 0 ]
}

case "${1:-}" in
  --selftest) selftest; exit $? ;;
  ""|-h|--help) sed -n 2,19p "$0"; exit 0 ;;
esac
[ $# -ge 2 ] || die "нужно: <имя> <папка> [--dry]" 2
DRY=0
[ "${3:-}" = "--dry" ] && DRY=1
[ $# -le 2 ] || [ "$3" = "--dry" ] || die "лишний аргумент «$3»" 2
publish "$1" "$2" "$DRY"

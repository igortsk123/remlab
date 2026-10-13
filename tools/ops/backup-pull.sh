#!/usr/bin/env bash
# Копия ночного дампа прод-базы ВНЕ сервера (план b2b-09, ADR-0266): DEV забирает свежий дамп
# /opt/remlab/backups/db-*.sql.gz и держит 14 последних в ~/remlab-backups. Сервер умрёт целиком — база
# не потеряна. Проверка: дамп не старше 30 ч, gzip целый, размер не меньше половины прошлого.
# Крон DEV: 15 4 * * *  (дамп на сервере — 03:30 UTC). Сбой — тревога через tools/scout/alert.sh.
set -uo pipefail
SRV=${SRV:-root@89.167.127.0}
DST=${DST:-$HOME/remlab-backups}
ALERT="$(dirname "$0")/../scout/alert.sh"
mkdir -p "$DST"
fail() { echo "$(date -u +%FT%TZ) FAIL $1" >> "$DST/pull.log"; bash "$ALERT" "🔴 бэкап прод-базы не скопирован на DEV: $1" || true; exit 1; }

latest=$(ssh -o ConnectTimeout=20 -p 22222 "$SRV" 'ls -t /opt/remlab/backups/db-*.sql.gz 2>/dev/null | head -1') || fail "сервер не ответил"
[ -n "$latest" ] || fail "на сервере нет дампов"
age_h=$(ssh -p 22222 "$SRV" "echo \$(( (\$(date +%s) - \$(stat -c %Y $latest)) / 3600 ))") || fail "не прочитал возраст дампа"
[ "${age_h:-99}" -le 30 ] || fail "свежему дампу на сервере $age_h ч (ночной бэкап не идёт?)"
name=$(basename "$latest")
if [ ! -s "$DST/$name" ]; then
  scp -q -P 22222 "$SRV:$latest" "$DST/$name.part" || fail "scp $name"
  mv "$DST/$name.part" "$DST/$name"
fi
gzip -t "$DST/$name" 2>/dev/null || { rm -f "$DST/$name"; fail "$name битый (gzip -t)"; }
prev=$(ls -t "$DST"/db-*.sql.gz | sed -n 2p)
if [ -n "$prev" ]; then
  a=$(stat -c %s "$DST/$name"); b=$(stat -c %s "$prev")
  [ $(( a * 2 )) -ge "$b" ] || fail "$name вдвое меньше прошлого ($a против $b байт)"
fi
ls -t "$DST"/db-*.sql.gz | tail -n +15 | xargs -r rm -f
echo "$(date -u +%FT%TZ) ok $name $(du -h "$DST/$name" | cut -f1)" >> "$DST/pull.log"

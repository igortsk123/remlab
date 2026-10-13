#!/usr/bin/env bash
# Снаружи, после каждого деплоя (план b2b-01): то, что было открыто 13.10, закрыто и сейчас.
# Только чтение и безвредные POST; лимиты частоты здесь не гоняем — они съели бы квоту людей.
#   tools/security-smoke.sh https://remont-lab.online
set -uo pipefail
BASE=${1:-https://remont-lab.online}
fail=0
check() {  # $1 — что проверяем, $2 — ожидание, $3 — факт
  if [ "$2" = "$3" ]; then echo "OK   $1 ($3)"; else echo "FAIL $1: ждали $2, получили $3"; fail=1; fi
}
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@"; }

check "папка очереди подборок закрыта" 404 "$(code "$BASE/test/share/_queue/")"
check "внутренняя ручка снаружи не видна" 404 "$(code -X POST -H 'content-type: application/json' -d '{}' "$BASE/api/internal/share-request")"
check "вебхук ЮKassa с чужого адреса" 403 "$(code -X POST -H 'content-type: application/json' -d '{"event":"payment.succeeded","object":{"id":"x"}}' "$BASE/api/pay/yookassa/webhook")"
check "разбор трейса без пароля" 403 "$(code "$BASE/api/trace/1")"
check "разбор трейса с паролем в адресе" 403 "$(code "$BASE/api/trace/1?token=guess")"
check "Telegram-вебхук без секрета" 401 "$(code -X POST -H 'content-type: application/json' -d '{}' "$BASE/api/leads/tg-admin")"

for path in / /demo/ /flat; do
  h=$(curl -sI --max-time 15 "$BASE$path" | tr -d '\r')
  check "frame-ancestors на $path" yes "$(grep -qi "^content-security-policy:.*frame-ancestors 'self'" <<<"$h" && echo yes || echo no)"
  check "nosniff на $path" yes "$(grep -qi '^x-content-type-options: nosniff' <<<"$h" && echo yes || echo no)"
done

check "CORS рендера не раздаётся чужим" no "$(curl -s -D - -o /dev/null --max-time 15 -X OPTIONS -H 'Origin: https://evil.example' "$BASE/api/share" | grep -qi '^access-control-allow-origin' && echo yes || echo no)"

exit $fail

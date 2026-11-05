#!/usr/bin/env bash
# САМОПРОВЕРКА общей очереди тяжёлых прогонов (`tools/ops/heavy-slot.sh` / `heavy_slot.py`, T-20261105-57): во временной
# папке (свой замок, свой журнал, подменённый /proc/meminfo) — настоящую очередь машины и чужие процессы не трогает.
# Проверяет: два держателя идут по очереди; смерть держателя освобождает (и пока жива команда-потомок — нет);
# порог памяти ждёт; rc пробрасывается; --timeout → 124; вложенный вызов не ждёт сам себя; --no-slot обходит; питон и shell —
# одна очередь; чужой HEAVY_SLOT_HELD не пропускает. Временная папка остаётся (несколько КБ) — путь в конце.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$DIR/heavy-slot.sh"
T=$(mktemp -d "${TMPDIR:-/tmp}/heavy-slot-selftest.XXXXXX")
export HEAVY_SLOT_DIR="$T/slot" HEAVY_SLOT_LOG="$T/heavy-slot.log" HEAVY_SLOT_MEMINFO="$T/meminfo" HEAVY_SLOT_POLL=0.1 HEAVY_SLOT_REPORT=0
unset HEAVY_SLOT_HELD
fails=0
ok() { if [ "$2" = 0 ]; then echo "  [ ok ] $1"; else echo "  [FAIL] $1"; fails=$((fails + 1)); fi; }
yes_if() { if eval "$1"; then echo 0; else echo 1; fi; }
mem() { printf 'MemTotal:       16000000 kB\nMemAvailable:   %d kB\n' "$(( $1 * 1048576 ))" > "$HEAVY_SLOT_MEMINFO"; }
until_held() { for _ in $(seq 1 50); do "$S" --status | grep -q '^ДЕРЖИТ' && return 0; sleep 0.1; done; return 1; }
mem 8

"$S" t-rc -- sh -c 'exit 7'; rc=$?
ok "rc команды пробрасывается (7)" "$(yes_if '[ $rc = 7 ]')"
"$S" t-sig -- sh -c 'kill -9 $$'; rc=$?
ok "команду убили сигналом 9 → 137, как в shell" "$(yes_if '[ $rc = 137 ]')"

"$S" a -- sh -c "echo 'start a' >> $T/order; sleep 0.6; echo 'end a' >> $T/order" &
pa=$!
"$S" b -- sh -c "echo 'start b' >> $T/order; sleep 0.6; echo 'end b' >> $T/order" &
pb=$!
wait $pa $pb
o=$(tr '\n' '|' < "$T/order")
ok "два держателя параллельно — по очереди, без наложения ($o)" \
  "$(yes_if '[ "$o" = "start a|end a|start b|end b|" ] || [ "$o" = "start b|end b|start a|end a|" ]')"

"$S" hold -- sleep 4 &
ph=$!
until_held
"$S" waiter -- true &
pw=$!
sleep 0.4
st=$("$S" --status)
ok "--status: кто держит (метка, pid, с какого времени) и кто ждёт" \
  "$(yes_if 'grep -q "^ДЕРЖИТ: hold · pid $ph · работает с " <<<"$st" && grep -q "^ЖДУТ: 1" <<<"$st" && grep -q "waiter · pid $pw · очередь" <<<"$st"')"
"$S" t-to --timeout 0.5 -- sh -c "echo ran >> $T/timeout-ran"; rc=$?
ok "--timeout: не дождался → 124, команда не запускалась" "$(yes_if '[ $rc = 124 ] && [ ! -e $T/timeout-ran ]')"
HEAVY_SLOT_HELD=$ph "$S" t-leak --timeout 0.5 -- true; rc=$?
ok "чужой HEAVY_SLOT_HELD (держатель — не предок) очередь не обходит" "$(yes_if '[ $rc = 124 ]')"
t0=$(date +%s%N)
"$S" t-free --no-slot -- true; rc=$?
ok "--no-slot: сразу, мимо очереди, строка в журнал" \
  "$(yes_if '[ $rc = 0 ] && [ $(( ($(date +%s%N) - t0) / 1000000 )) -lt 1000 ] && grep -q "t-free .*БЕЗ ОЧЕРЕДИ" "$HEAVY_SLOT_LOG"')"
wait $ph $pw

"$S" outer -- "$S" inner --timeout 2 -- sh -c 'exit 3'; rc=$?
ok "вложенный вызов под слотом не ждёт сам себя (rc изнутри — 3)" \
  "$(yes_if '[ $rc = 3 ] && grep -q "inner .*вложенный вызов" "$HEAVY_SLOT_LOG"')"

"$S" dying -- sleep 30 &
pd=$!
until_held
child=$(ps -o pid= --ppid "$pd" | tr -d ' ')
kill -9 "$pd"; wait "$pd" 2>/dev/null
st=$("$S" --status)
ok "обёртку убили, команда жива — очередь всё ещё занята, видно, кто держит" \
  "$(yes_if 'grep -q "процесса уже нет" <<<"$st" && grep -q "pid $child " <<<"$st"')"
kill -9 "$child"
sleep 0.2
"$S" after --timeout 3 -- true; rc=$?
ok "смерть держателя освобождает очередь (следующий взял)" "$(yes_if '[ $rc = 0 ] && grep -q "after .*взял" "$HEAVY_SLOT_LOG"')"

mem 1
"$S" t-mem --min-gb 2 -- sh -c "echo ran > $T/mem-ran" &
pm=$!
sleep 0.6
st=$("$S" --status)
ok "порог: при 1 ГБ < 2 команда не стартует, держатель — «память»" \
  "$(yes_if '[ ! -e $T/mem-ran ] && grep -q "^ДЕРЖИТ: t-mem .* память с " <<<"$st"')"
mem 3
wait $pm; rc=$?
ok "порог: память освободилась (3 ГБ) — команда пошла, ожидание в журнале" \
  "$(yes_if '[ $rc = 0 ] && [ -e $T/mem-ran ] && grep -q "t-mem .*ждёт память: свободно 1.0 ГБ < 2" "$HEAVY_SLOT_LOG"')"
mem 8

"$S" sh-holder -- sleep 1 &
ps1=$!
until_held
out=$(python3 - "$DIR" <<'EOF'
import sys, time
sys.path.insert(0, sys.argv[1])
from heavy_slot import heavy_slot, SlotTimeout
try:
    with heavy_slot('py-short', timeout=0.3):
        print('short-ran')
except SlotTimeout:
    print('short-timeout')
t = time.time()
with heavy_slot('py-step', min_gb=1, timeout=10) as i:
    print('step-ran', round(time.time() - t, 1) >= 0.3, i['free_gb'] >= 1)
EOF
)
wait $ps1
ok "питон и shell — одна очередь: with heavy_slot ждёт держателя shell, таймаут — SlotTimeout" \
  "$(yes_if '[ "$out" = "short-timeout
step-ran True True" ]')"
st=$("$S" --status)
ok "после всех: очередь свободна, ожидающих нет" "$(yes_if 'grep -q "^СВОБОДНО" <<<"$st" && grep -q "^ЖДУТ: 0" <<<"$st"')"

echo "временная папка: $T"
if [ "$fails" = 0 ]; then echo "heavy-slot selftest: OK"; exit 0; fi
echo "heavy-slot selftest: $fails FAIL"; exit 1

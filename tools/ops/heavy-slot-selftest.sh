#!/usr/bin/env bash
# САМОПРОВЕРКА общей очереди тяжёлых прогонов (`tools/ops/heavy-slot.sh` / `heavy_slot.py`, T-20261105-57): во временной
# папке (свой замок, свой журнал, подменённый /proc/meminfo) — настоящую очередь машины и чужие процессы не трогает.
# Проверяет: два держателя идут по очереди; смерть держателя освобождает (и пока жива команда-потомок — нет);
# порог памяти ждёт; rc пробрасывается; --timeout → 124; вложенный вызов не ждёт сам себя; --no-slot обходит; питон и shell —
# одна очередь; чужой HEAVY_SLOT_HELD не пропускает. T-57/2: три ожидающих — строго по порядку прихода (и так же в --status);
# отпустивший и тут же вернувшийся не обгоняет ждущего; умерший ожидающий выбывает сам; уступка по памяти маленькой задаче
# и защита большой от голодания (после K уступок ждёт, держа очередь). T-57/3: ожидающий старой версии (без билета) получает
# билет-заместитель по времени прихода и никого не обгоняет; два слота — второй только при памяти (порог держателя + свой +
# запас, запас ≥ 10 % MemTotal), при нехватке — по одному; освободился первый при идущем втором — ждёт память на обоих;
# HEAVY_SLOT_SLOTS=1 — по одному при любой памяти, --status как прежде. T-74: допуск без двойного счёта (Σ max(порог − память
# дерева, 0) + свой + запас; одиночный — свой порог без запаса), три слота, порог по замеру (≥ 3 замера типа → min(объявл., 1,5 × пик)),
# сторож (свободно < запаса — никого нового, идущий доживает), замер пика памяти дерева и WARN долгого держания, --stats.
# Временная папка остаётся (несколько КБ) — путь в конце.
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
memt() { awk -v t="$1" -v a="$2" 'BEGIN{printf "MemTotal: %d kB\nMemAvailable: %d kB\n", t*1048576, a*1048576}' > "$HEAVY_SLOT_MEMINFO"; }
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
"$S" t-mem --min-gb 2 --timeout 10 -- sh -c "echo ran > $T/mem-ran" &
pm=$!
sleep 0.6
st=$("$S" --status)
ok "порог: при 1 ГБ < 2 команда не стартует, держатель — «память»" \
  "$(yes_if '[ ! -e $T/mem-ran ] && grep -q "^ДЕРЖИТ: t-mem .* память с " <<<"$st"')"
mem 3
wait $pm; rc=$?
ok "порог: память освободилась (3 ГБ ≥ 2; одиночный — без запаса) — команда пошла; в журнале сторож (1 < запаса 1,5)" \
  "$(yes_if '[ $rc = 0 ] && [ -e $T/mem-ran ] && grep -q "t-mem .*ждёт память: сторож: свободно 1.0 ГБ < запаса 1.5" "$HEAVY_SLOT_LOG"')"
mem 8
"$S" t-lone --min-gb 7 --timeout 2 -- true; rc=$?
ok "одиночный — как до T-74, без запаса: порог 7 при свободных 8 — идёт сразу" \
  "$(yes_if '[ $rc = 0 ] && grep -q "t-lone .*взял: ждал 0" "$HEAVY_SLOT_LOG"')"
mem 2
"$S" t-lone2 --min-gb 2.5 --timeout 0.5 -- true; rc=$?
ok "одиночный: 2 < 2,5 — ждёт, в журнале «одиночный — без запаса»" \
  "$(yes_if '[ $rc = 124 ] && grep -q "t-lone2 .*ждёт память: свободно 2.0 ГБ < свой 2.5 (одиночный — без запаса)" "$HEAVY_SLOT_LOG"')"
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
with heavy_slot('py-step', min_gb=2, timeout=10) as i:   # 6 + 2 + запас 1,5 > 8 — второй слот не дают, ждёт
    print('step-ran', round(time.time() - t, 1) >= 0.3, i['free_gb'] >= 2)
EOF
)
wait $ps1
ok "питон и shell — одна очередь: with heavy_slot ждёт держателя shell, таймаут — SlotTimeout" \
  "$(yes_if '[ "$out" = "short-timeout
step-ran True True" ]')"
# --- T-57/2: строгий порядок прихода (билеты), повторный захват, умерший ожидающий, уступка по памяти
"$S" q-hold -- sleep 1.5 &
pq=$!
until_held
for w in w1 w2 w3; do "$S" "$w" -- sh -c "echo $w >> $T/order3" & eval "p_$w=$!"; sleep 0.3; done
st=$("$S" --status)
ok "--status: очередь по порядку прихода (1. w1, 2. w2, 3. w3)" \
  "$(yes_if 'grep -q "^ЖДУТ: 3 (по порядку прихода)" <<<"$st" && grep -q "^  1\. w1 " <<<"$st" && grep -q "^  2\. w2 " <<<"$st" && grep -q "^  3\. w3 " <<<"$st"')"
wait $pq $p_w1 $p_w2 $p_w3
o=$(tr '\n' '|' < "$T/order3")
ok "три ожидающих проходят строго по порядку прихода ($o)" "$(yes_if '[ "$o" = "w1|w2|w3|" ]')"

python3 - "$DIR" "$T/regrab" <<'EOF' &
import sys, time
sys.path.insert(0, sys.argv[1])
from heavy_slot import heavy_slot
for i in range(2):                      # длинный цикл берёт слот на шаг и сразу просит снова
    with heavy_slot('loop', min_gb=1):
        open(sys.argv[2], 'a').write(f'loop{i}\n')
        time.sleep(0.8)
EOF
pl=$!
sleep 0.3
"$S" w-regrab --min-gb 7 -- sh -c "echo w >> $T/regrab"   # 7 + (1 − память loop) + запас 1,5 > 8 — не вторым слотом
wait $pl
o=$(tr '\n' '|' < "$T/regrab")
ok "отпустивший и тут же вернувшийся не обгоняет ждущего ($o)" "$(yes_if '[ "$o" = "loop0|w|loop1|" ]')"

"$S" d-hold -- sleep 1.2 &
pdh=$!
until_held
"$S" d-dead -- sh -c "echo dead >> $T/dead" &
pdd=$!
sleep 0.3
"$S" d-next --timeout 5 -- sh -c "echo next >> $T/dead" &
pdn=$!
sleep 0.2
kill -9 "$pdd"; wait "$pdd" 2>/dev/null
wait $pdh $pdn; rc=$?
ok "умерший ожидающий выбывает сам: следующий за ним прошёл (rc $rc)" "$(yes_if '[ $rc = 0 ] && [ "$(cat $T/dead)" = next ]')"

mem 3
HEAVY_SLOT_YIELD=0.5 HEAVY_SLOT_MAX_YIELDS=1 "$S" big --min-gb 4 -- sh -c "echo big >> $T/yield" &
pbig=$!
until_held
"$S" small1 --min-gb 2 -- sh -c "echo small1 >> $T/yield" &
ps1=$!
wait $ps1
ok "уступка: большая ждёт память дольше HEAVY_SLOT_YIELD — маленькая с меньшим порогом прошла" \
  "$(yes_if '[ "$(cat $T/yield)" = small1 ] && grep -q "big .*уступил очередь: .* small1 .* встаю в конец (уступка 1 из 1)" "$HEAVY_SLOT_LOG"')"
for _ in $(seq 1 50); do "$S" --status | grep -q '^ДЕРЖИТ: big .*уступок 1' && break; sleep 0.1; done
"$S" small2 --min-gb 2 -- sh -c "echo small2 >> $T/yield" &
ps2=$!
sleep 1.5
ok "защита от голодания: после K уступок большая ждёт память, держа очередь — вторая маленькая не прошла" \
  "$(yes_if '[ "$(tr "\n" "|" < $T/yield)" = "small1|" ] && grep -q "big .*уступок 1 из 1 — дальше жду память, держа очередь" "$HEAVY_SLOT_LOG"')"
mem 5
wait $pbig $ps2
o=$(tr '\n' '|' < "$T/yield")
ok "память пришла: большая, затем вторая маленькая ($o)" "$(yes_if '[ "$o" = "small1|big|small2|" ]')"
mem 8

# --- T-57/3: ожидающий без билета (процесс старой версии: `wait/<pid>`, опрос замка раз в 1 с, билетов не знает)
cat > "$T/old_waiter.py" <<'OLDW'
import fcntl, os, sys, time
d, lab, out = os.environ['HEAVY_SLOT_DIR'], sys.argv[1], sys.argv[2]
def kv(p, x):
    t = f'{p}.tmp-{os.getpid()}'
    open(t, 'w').write(''.join(f'{k}={v}\n' for k, v in x.items()))
    os.replace(t, p)
me = dict(label=lab, pid=os.getpid(), since=int(time.time()), min_gb=6, cmd='old')
w = os.path.join(d, 'wait', str(os.getpid()))
kv(w, dict(me, stage='очередь'))
fd = os.open(os.path.join(d, 'slot.lock'), os.O_RDWR | os.O_CREAT, 0o644)
while True:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except BlockingIOError:
        time.sleep(1.0)
os.unlink(w)
kv(os.path.join(d, 'holder'), dict(me, stage='работает'))
open(out, 'a').write(lab + '\n')
time.sleep(0.2)
os.unlink(os.path.join(d, 'holder'))
OLDW
export HEAVY_SLOT_HEAD_POLL=0.005
# (двое старых между собой порядок не держат — билетов не читают; поэтому в каждом случае старый один)
"$S" o-hold -- sleep 1.5 &
poh=$!
until_held
"$S" n1 -- sh -c "echo n1 >> $T/order4" & pn1=$!; sleep 0.3
python3 "$T/old_waiter.py" o1 "$T/order4" & po1=$!; sleep 0.3
"$S" n2 -- sh -c "echo n2 >> $T/order4" & pn2=$!; sleep 0.3
st=$("$S" --status)
ok "--status: пришедший без билета получил билет по времени прихода (n1, o1, n2)" \
  "$(yes_if 'grep -q "^ЖДУТ: 3 " <<<"$st" && grep -q "^  1\. n1 " <<<"$st" && grep -q "^  2\. o1 .*за старую версию" <<<"$st" && grep -q "^  3\. n2 " <<<"$st" && ! grep -q "без билета$" <<<"$st"')"
wait $poh $pn1 $po1 $pn2
o=$(tr '\n' '|' < "$T/order4")
ok "без билета не обгоняет пришедшего раньше и не голодает: строго по приходу ($o)" "$(yes_if '[ "$o" = "n1|o1|n2|" ]')"
"$S" o-hold2 -- sleep 1 &
poh=$!
until_held
python3 "$T/old_waiter.py" o0 "$T/order5" & po0=$!; sleep 0.3
"$S" n3 -- sh -c "echo n3 >> $T/order5" & pn3=$!
wait $poh $po0 $pn3
o=$(tr '\n' '|' < "$T/order5")
ok "без билета, пришедший раньше, получает билет до нового и идёт первым ($o)" \
  "$(yes_if '[ "$o" = "o0|n3|" ] && [ -z "$(ls $HEAVY_SLOT_DIR/wait)" ]')"
unset HEAVY_SLOT_HEAD_POLL

pair() {   # <файл> <метка1> <порог1> <метка2> <порог2> → порядок start/end двух задач по 0,8 с; --status — в <файл>.st
  local f="$T/$1"
  "$S" "$2" --min-gb "$3" -- sh -c "echo s$2 >> $f; sleep 0.8; echo e$2 >> $f" & local p1=$!
  until_held
  "$S" "$4" --min-gb "$5" -- sh -c "echo s$4 >> $f; sleep 0.8; echo e$4 >> $f" & local p2=$!
  sleep 0.4
  "$S" --status > "$f.st"
  wait $p1 $p2
  tr '\n' '|' < "$f"
}
mem 14
o=$(pair two c1 4 c2 4)
ok "два слота: памяти хватает (14 ≥ 4 + (4 − память c1) + запас 1,5 — 10 % от 15,3 ГБ) — второй идёт параллельно ($o)" \
  "$(yes_if '[ "$o" = "sc1|sc2|ec1|ec2|" ] && grep -q "c2 .*взял: .*слот 2: свободно 14.0 ГБ ≥ свой 4 + держатели c1 4−0.0=4.0 + запас 1.5" "$HEAVY_SLOT_LOG"')"
ok "--status: оба держателя (второй — «слот 2») и число слотов" \
  "$(yes_if 'grep -q "^ДЕРЖИТ: c1 · pid .* работает с " "$T/two.st" && grep -q "^ДЕРЖИТ: c2 · pid .* работает с .* · слот 2$" "$T/two.st" && grep -q "^СЛОТОВ: 3 .*запас 1.5 ГБ" "$T/two.st" && ! grep -q "^СВОБОДНО" "$T/two.st"')"
mem 8
o=$(pair short c3 4 c4 4)
ok "два слота: памяти мало (8 < 4 + 4 + 1,5) — строго по одному ($o)" "$(yes_if '[ "$o" = "sc3|ec3|sc4|ec4|" ]')"
memt 40 11
o=$(pair res c5 4 c6 4)
ok "запас не меньше 10 % памяти: при 40 ГБ запас 4 — 11 < 4 + 4 + 4, по одному (при 5 % пошли бы вдвоём) ($o)" \
  "$(yes_if '[ "$o" = "sc5|ec5|sc6|ec6|" ] && grep -q "^СЛОТОВ: 3 .*запас 4.0 ГБ" "$T/res.st"')"
mem 14
o=$(HEAVY_SLOT_SLOTS=1; export HEAVY_SLOT_SLOTS; pair one c7 4 c8 4)
ok "HEAVY_SLOT_SLOTS=1: по одному даже при лишней памяти, --status без строки слотов ($o)" \
  "$(yes_if '[ "$o" = "sc7|ec7|sc8|ec8|" ] && ! grep -q "СЛОТОВ\|слот 2" "$T/one.st" && [ $(grep -c "^ДЕРЖИТ" "$T/one.st") = 1 ]')"

"$S" f1 --min-gb 4 -- sh -c "echo sf1 >> $T/free1; sleep 0.5; echo ef1 >> $T/free1" & pf1=$!
until_held
"$S" f2 --min-gb 4 -- sh -c "echo sf2 >> $T/free1; sleep 2; echo ef2 >> $T/free1" & pf2=$!
sleep 0.3
"$S" f3 --min-gb 10 -- sh -c "echo sf3 >> $T/free1" & pf3=$!
wait $pf1 $pf2 $pf3
o=$(tr '\n' '|' < "$T/free1")
ok "первый слот освободился при идущем втором — следующий ждёт память на обоих (14 < 10 + 4 + 1,5), идёт после ($o)" \
  "$(yes_if '[ "$o" = "sf1|sf2|ef1|ef2|sf3|" ] && grep -q "f3 .*ждёт память: свободно 14.0 ГБ < свой 10 + держатели f2 4−0.0=4.0 + запас 1.5" "$HEAVY_SLOT_LOG"')"
mem 8

# --- T-74: допуск без двойного счёта, три слота, порог по замеру, сторож, замер пика, долгое держание, --stats
export HEAVY_SLOT_MEM_STUB="$T/memstub"
: > "$HEAVY_SLOT_MEM_STUB"
mem 8
echo "dc-h 5" >> "$HEAVY_SLOT_MEM_STUB"           # держатель уже занял 5 из своих 6 — они уже вычтены из свободных 8
o=$(pair dbl dc-h 6 dc-x 4)
ok "без двойного счёта: держатель 6 ГБ уже взял 5 → 8 ≥ (6 − 5) + 4 + 1,5 — второй идёт параллельно ($o)" \
  "$(yes_if '[ "$o" = "sdc-h|sdc-x|edc-h|edc-x|" ] && grep -q "dc-x .*взял: .*слот 2: свободно 8.0 ГБ ≥ свой 4 + держатели dc-h 6−5.0=1.0 + запас 1.5" "$HEAVY_SLOT_LOG"')"
echo "dc-h2 1" >> "$HEAVY_SLOT_MEM_STUB"          # взял только 1 из 6 — ещё 5 может взять: 5 + 4 + 1,5 > 8
o=$(pair dbl2 dc-h2 6 dc-y 4)
ok "без двойного счёта, обратная сторона: держатель взял 1 из 6 — 8 < 5 + 4 + 1,5, по одному ($o)" "$(yes_if '[ "$o" = "sdc-h2|edc-h2|sdc-y|edc-y|" ]')"

mem 14
printf 's3-a 3.5\ns3-b 3.5\ns3-c 3.5\n' >> "$HEAVY_SLOT_MEM_STUB"
# детерминированно (T-74/3: на занятой машине снимок по sleep мигал): каждая команда ставит флаг «стартовала» и держит слот,
# пока нет флага «отпускай»; снимок --status — когда трое стартовали и четвёртый стоит первым в очереди
until_f() { for _ in $(seq 1 200); do eval "$1" && return 0; sleep 0.05; done; return 1; }
hold3() { echo "echo s$1 >> $T/$2; touch $T/up-$2-$1; while [ ! -e $T/go-$2 ]; do sleep 0.05; done; echo e$1 >> $T/$2"; }
for x in a b c d; do
  "$S" "s3-$x" --min-gb 4 -- sh -c "$(hold3 $x three)" & eval "p3_$x=$!"
  [ $x = d ] || until_f "[ -e $T/up-three-$x ]"
done
until_f '"$S" --status | grep -q "^  1\. s3-d "'
"$S" --status > "$T/three.st"
d_early=$([ -e "$T/up-three-d" ] && echo 1 || echo 0)
touch "$T/go-three"
wait $p3_a $p3_b $p3_c $p3_d
o=$(tr '\n' '|' < "$T/three")
ok "три слота: 14 ≥ 0,5 + 0,5 + 4 + 1,5 — трое параллельно, четвёртый ждёт слот ($o)" \
  "$(yes_if '[ $d_early = 0 ] && [[ "$o" =~ ^sa\|sb\|sc\|(e[abc]\|)+sd\| ]] && [ $(grep -c "^ДЕРЖИТ" "$T/three.st") = 3 ] && grep -q "^ДЕРЖИТ: s3-c .* · слот 3$" "$T/three.st" && grep -q "^  1\. s3-d " "$T/three.st"')"
export HEAVY_SLOT_SLOTS=2
for x in a b c; do
  "$S" "s3-$x" --min-gb 4 -- sh -c "$(hold3 $x two3)" & eval "q_$x=$!"
  [ $x = c ] || until_f "[ -e $T/up-two3-$x ]"
done
until_f '"$S" --status | grep -q "^  1\. s3-c "'
c_early=$([ -e "$T/up-two3-c" ] && echo 1 || echo 0)
touch "$T/go-two3"
wait $q_a $q_b $q_c
unset HEAVY_SLOT_SLOTS
o=$(tr '\n' '|' < "$T/two3")
ok "HEAVY_SLOT_SLOTS=2: та же память — третий ждёт, пока не отпустит первый ($o)" "$(yes_if '[ $c_early = 0 ] && [[ "$o" =~ ^sa\|sb\|(e[ab]\|)+sc\| ]]')"

mem 3
"$S" m-old --min-gb 6 --timeout 1 -- true; rc=$?
ok "без замеров — объявленный порог: 3 < 6, не дождался (124)" "$(yes_if '[ $rc = 124 ]')"
P="$HEAVY_SLOT_DIR/peaks.tsv"
for v in 0.3 0.5; do printf '2026-11-06 10:00:00\tparity\tparity-x\t%s\t%s\t100.0\t6\t6\n' $v $v >> "$P"; done
"$S" parity-a --min-gb 6 --timeout 1 -- true; rc=$?
ok "два замера — мало: порог объявленный, 124" "$(yes_if '[ $rc = 124 ] && ! grep -q "parity-a .*порог по замеру" "$HEAVY_SLOT_LOG"')"
printf '2026-11-06 10:00:00\tparity\tparity-y\t0.4\t0.4\t5.0\t6\t6\n' >> "$P"   # держал 5 с < 30 — не засчитан
"$S" parity-b --min-gb 6 --timeout 1 -- true; rc=$?
ok "короткое держание (< 30 с) в замеры не идёт: по-прежнему 124" "$(yes_if '[ $rc = 124 ]')"
printf '2026-11-06 10:00:00\tparity\tparity-z\t0.4\t0.4\t200.0\t6\t6\n' >> "$P"
"$S" parity-c --min-gb 6 --timeout 3 -- true; rc=$?
ok "три замера parity, пик 0,5 → порог min(6, 0,75): 3 ≥ 0,75 — пошла" \
  "$(yes_if '[ $rc = 0 ] && grep -q "parity-c .*порог по замеру: объявлен 6, тип parity, замеров 3, наибольший пик 0.50 ГБ → 0.75" "$HEAVY_SLOT_LOG"')"
mem 8
echo "parity-h 0.2" >> "$HEAVY_SLOT_MEM_STUB"
o=$(pair eff parity-h 6 e-x 5.5)
ok "доля держателя — по ЕГО эффективному порогу: 8 ≥ (0,75 − 0,2) + 5,5 + 1,5 — параллельно; --status: «по замеру 0.75» ($o)" \
  "$(yes_if '[ "$o" = "sparity-h|se-x|eparity-h|ee-x|" ] && grep -q "^ДЕРЖИТ: parity-h .*порог 6.0 ГБ (по замеру 0.75)" "$T/eff.st"')"
for v in 0.01 0.02 0.01; do printf '2026-11-06 10:00:00\tcutout\tt9-cutout\t%s\t%s\t100.0\t4\t4\n' $v $v >> "$P"; done
"$S" cutout-f --min-gb 4 -- true
ok "пол порога по замеру 0,5 ГБ (дерево не видит память контейнеров)" "$(yes_if 'grep -q "cutout-f .*порог по замеру: .* → 0.50" "$HEAVY_SLOT_LOG"')"

mem 8
"$S" g-run --min-gb 2 -- sh -c "sleep 0.8; echo done >> $T/guard" & pg=$!
until_held
mem 1
"$S" g-new --min-gb 0 --timeout 1 -- sh -c "echo new >> $T/guard"; rc=$?
wait $pg; rcg=$?
ok "сторож: свободно 1 < запаса 1,5 — новый (даже с порогом 0) не пущен, идущий доработал" \
  "$(yes_if '[ $rc = 124 ] && [ $rcg = 0 ] && [ "$(cat $T/guard)" = done ] && grep -q "g-new .*сторож: свободно 1.0 ГБ < запаса 1.5" "$HEAVY_SLOT_LOG"')"
"$S" g-lone --min-gb 0.5 --timeout 0.5 -- true; rc=$?
ok "сторож и для одиночного: 1 ≥ порога 0,5, но < запаса 1,5 — не пущен" "$(yes_if '[ $rc = 124 ] && grep -q "g-lone .*сторож" "$HEAVY_SLOT_LOG"')"
mem 8

unset HEAVY_SLOT_MEM_STUB
HEAVY_SLOT_SAMPLE=0.1 HEAVY_SLOT_LONG_S=0.4 HEAVY_SLOT_MEASURE_MIN_S=0 \
  "$S" t74-build-real --min-gb 1 -- python3 -c "import time; b = bytearray(300 << 20); b[::4096] = b'x' * len(b[::4096]); time.sleep(0.9)"
ln=$(grep "t74-build-real .*отпустил" "$HEAVY_SLOT_LOG")
pk=$(sed -n 's/.*пик памяти дерева \([0-9.]*\) ГБ.*/\1/p' <<<"$ln")
ok "замер: пик памяти дерева с потомком (300 МБ) — ${pk} ГБ, тип build; WARN долгого держания в журнале; строка в peaks.tsv" \
  "$(yes_if 'awk -v p="$pk" "BEGIN{exit !(p >= 0.28 && p < 1)}" && grep -q "тип build" <<<"$ln" && grep -q "WARN: держание дольше" <<<"$ln" && grep -q "t74-build-real .*WARN: держит слот дольше" "$HEAVY_SLOT_LOG" && grep -q "	build	t74-build-real	" "$P"')"
st=$(HEAVY_SLOT_LONG_S=0.4 "$S" --stats)
ok "--stats: строка на тип (parity — 6 записей, засчитано 3 по ≥ 30 с, 6 → 0.75), build, долгие" \
  "$(yes_if 'grep -q "^parity .* 6 ( 3) .*6 → 0.75" <<<"$st" && grep -q "^build " <<<"$st" && grep -q "^ДОЛГИЕ" <<<"$st"')"
ok "тип задачи по метке" "$(yes_if '[ "$(python3 -c "import sys; sys.path.insert(0, \"$DIR\"); from heavy_slot import task_type as t; print(\" \".join(t(x) for x in [\"parity-72\", \"parity-hall-exam\", \"t73-build\", \"t69-live\", \"parity-living-demo\", \"t51-look\", \"t73-hall-snap2\"]))")" = "parity exam build live parity look hall-snap" ]')"

st=$("$S" --status)
ok "после всех: очередь свободна, ожидающих нет" "$(yes_if 'grep -q "^СВОБОДНО" <<<"$st" && grep -q "^ЖДУТ: 0" <<<"$st"')"

echo "временная папка: $T"
if [ "$fails" = 0 ]; then echo "heavy-slot selftest: OK"; exit 0; fi
echo "heavy-slot selftest: $fails FAIL"; exit 1

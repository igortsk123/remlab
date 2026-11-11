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
# дерева, 0) + свой + запас; одиночный — свой порог без запаса), три слота, порог по замеру (T-91: с 1 замера типа →
# min(объявл., k × пик), k = 2 при 1–2 замерах, 1,5 при 3+; превысивший порог держатель — доля max(объявл., пик) − память),
# сторож (свободно < запаса — никого нового, идущий доживает), замер пика памяти дерева и WARN долгого держания, --stats.
# T-79: обгон — голова не проходит по памяти, следующий проходящий берёт свободный слот; голова ждёт дольше
# HEAVY_SLOT_BACKFILL_MIN — обгон закрыт; одиночный — как прежде. T-20261109-31: приоритет интерактивных (--prio /
# HEAVY_SLOT_PRIO: 2 раньше 1 раньше 0, внутри класса — по приходу, видно в --status); порог памяти не обходит; держатель, ещё
# ждущий память, отдаёт слот старшему классу сразу и возвращается со своим билетом; ждущий дольше
# HEAVY_SLOT_PRIO_AGE_MIN — старший класс (голодания нет); класс вне 0…2 — отказ / в границы. T-20261110-29: резерв пробы
# (HEAVY_SLOT_PRIO_SLOTS) — класс ≥ 1 идёт сразу при занятых обычных слотах, обычный ждёт; `waiting(1)` — только класс ≥ 1.
# Временная папка — в REMLAB_TMP на диске (T-20261107-13: в /tmp их скопилось 25); успех — удаляется, провал или
# REMLAB_KEEP_TMP=1 — остаётся, путь в конце.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
S="$DIR/heavy-slot.sh"
. "$DIR/remlab-tmp.sh"
T=$(remlab_tmp_dir heavy-slot-selftest) || { echo "heavy-slot selftest: нет временной папки в $REMLAB_TMP"; exit 1; }
remlab_tmp_trap "$T"
export HEAVY_SLOT_DIR="$T/slot" HEAVY_SLOT_LOG="$T/heavy-slot.log" HEAVY_SLOT_MEMINFO="$T/meminfo" HEAVY_SLOT_POLL=0.1 HEAVY_SLOT_REPORT=0
unset HEAVY_SLOT_HELD
fails=0
ok() { if [ "$2" = 0 ]; then echo "  [ ok ] $1"; else echo "  [FAIL] $1"; fails=$((fails + 1)); fi; }
yes_if() { if eval "$1"; then echo 0; else echo 1; fi; }
# подмена /proc/meminfo — подменой файла (T-80): `>` сперва обнуляет, и ожидающий под нагрузкой читал пустой файл → «нет MemAvailable»
mem() { printf 'MemTotal:       16000000 kB\nMemAvailable:   %d kB\n' "$(( $1 * 1048576 ))" > "$HEAVY_SLOT_MEMINFO.tmp" && mv -f "$HEAVY_SLOT_MEMINFO.tmp" "$HEAVY_SLOT_MEMINFO"; }
memt() { awk -v t="$1" -v a="$2" 'BEGIN{printf "MemTotal: %d kB\nMemAvailable: %d kB\n", t*1048576, a*1048576}' > "$HEAVY_SLOT_MEMINFO.tmp" && mv -f "$HEAVY_SLOT_MEMINFO.tmp" "$HEAVY_SLOT_MEMINFO"; }
until_held() { for _ in $(seq 1 50); do "$S" --status | grep -q '^ДЕРЖИТ' && return 0; sleep 0.1; done; return 1; }
until_f() { for _ in $(seq 1 200); do eval "$1" && return 0; sleep 0.05; done; return 1; }
holdp() { echo "echo s$1 >> $T/$2; touch $T/$2.up-$1; while [ ! -e $T/$2.go-$1 ]; do sleep 0.05; done; echo e$1 >> $T/$2"; }
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

# T-97: --no-slot наследуется потомками — шаги команды, пущенной мимо очереди, сами в очередь не встают (очередь при этом занята)
"$S" ns-hold -- sleep 5 &
pnh=$!
until_held
t0=$(date +%s%N)
"$S" ns-outer --no-slot -- "$S" ns-mid --timeout 2 -- "$S" ns-deep --timeout 2 -- sh -c 'exit 4'; rc=$?
ok "вложенные под --no-slot (два уровня) не ждут занятую очередь (rc изнутри — 4), строка «без очереди по предку»" \
  "$(yes_if '[ $rc = 4 ] && [ $(( ($(date +%s%N) - t0) / 1000000 )) -lt 1500 ] && grep -q "ns-mid .*без очереди по предку pid=" "$HEAVY_SLOT_LOG" && grep -q "ns-deep .*без очереди по предку pid=" "$HEAVY_SLOT_LOG"')"
HEAVY_SLOT_NOSLOT=$pnh "$S" ns-fake --timeout 0.5 -- true; rc=$?
ok "чужой HEAVY_SLOT_NOSLOT (pid — не предок) очередь не обходит" "$(yes_if '[ $rc = 124 ] && ! grep -q "ns-fake .*без очереди" "$HEAVY_SLOT_LOG"')"
HEAVY_SLOT_NOSLOT=junk "$S" ns-junk --timeout 0.5 -- true; rc=$?
ok "мусор в HEAVY_SLOT_NOSLOT — как без признака (ждёт)" "$(yes_if '[ $rc = 124 ]')"
wait $pnh
"$S" ns-outer2 --no-slot -- sh -c 'printf %s "${HEAVY_SLOT_NOSLOT:-}" > '"$T"'/ns-env'; rc=$?
ok "признак потомкам выставлен на время команды и снят после (в env обёртки снаружи его нет)" \
  "$(yes_if '[ $rc = 0 ] && [ -s $T/ns-env ] && [ -z "${HEAVY_SLOT_NOSLOT:-}" ]')"
r=$(python3 -c "
import os, sys; sys.path.insert(0, '$DIR'); import heavy_slot as H
os.environ.pop('HEAVY_SLOT_NOSLOT', None)
with H.heavy_slot('ns-py', no_slot=True) as a:
    inside = os.environ.get('HEAVY_SLOT_NOSLOT') == str(os.getpid())
    with H.heavy_slot('ns-py-in', timeout=0.5) as b:
        nested = b.get('no_slot_parent') == os.getpid()
print(int(inside and nested and 'HEAVY_SLOT_NOSLOT' not in os.environ))")
ok "питон: with heavy_slot(no_slot=True) — вложенный with без очереди, после выхода признак снят" "$(yes_if '[ "$r" = 1 ]')"

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

# --- T-20261109-31: приоритет интерактивных — класс билета (2 «Обустроить», 1 загрузка тура, 0 обычный) меняет ТОЛЬКО очередь
mem 8
gate() { echo "while [ ! -e $T/$1 ]; do sleep 0.05; done"; }
"$S" p-hold -- sh -c "$(gate p-go)" &
pph=$!
until_held
"$S" p-n1 -- sh -c "echo n1 >> $T/order-p1" & pn1=$!; sleep 0.3
"$S" p-u1 --prio 1 -- sh -c "echo u1 >> $T/order-p1" & pu1=$!; sleep 0.3
HEAVY_SLOT_PRIO=2 "$S" p-r1 -- sh -c "echo r1 >> $T/order-p1" & pr1=$!; sleep 0.3
"$S" p-u2 --prio 1 -- sh -c "echo u2 >> $T/order-p1" & pu2=$!; sleep 0.3
"$S" p-r2 --prio 2 -- sh -c "echo r2 >> $T/order-p1" & pr2=$!; sleep 0.3
st=$("$S" --status)
touch "$T/p-go"
wait $pph $pn1 $pu1 $pr1 $pu2 $pr2
ok "--status: порядок выдачи — класс, потом приход (r1, r2, u1, u2, n1), класс виден" \
  "$(yes_if 'grep -q "^ЖДУТ: 5 (по порядку выдачи: приоритет, потом приход)" <<<"$st" && grep -q "^  1\. p-r1 .*приоритет 2" <<<"$st" && grep -q "^  2\. p-r2 .*приоритет 2" <<<"$st" && grep -q "^  3\. p-u1 .*приоритет 1" <<<"$st" && grep -q "^  4\. p-u2 " <<<"$st" && grep -q "^  5\. p-n1 " <<<"$st" && ! grep -q "p-n1 .*приоритет" <<<"$st"')"
o=$(tr '\n' '|' < "$T/order-p1")
ok "приоритет: «Обустроить» (2, флаг и переменная) раньше загрузки тура (1), обе раньше обычной; внутри класса — по приходу ($o)" \
  "$(yes_if '[ "$o" = "r1|r2|u1|u2|n1|" ] && grep -q "p-r1 .*взял: .*приоритет 2" "$HEAVY_SLOT_LOG" && grep -q "p-u1 .*ждёт очередь: .*приоритет 1" "$HEAVY_SLOT_LOG"')"

# приоритет не обходит порог памяти: «Обустроить» с порогом 7 при 5 ГБ берёт очередь первым и ждёт память (обычный с порогом 1
# сзади тоже не стартует: доля держателя 7 не оставляет места); память освободилась — идёт он, потом обычный
mem 5
"$S" m-hold --min-gb 4 -- sh -c "$(gate m-go)" &
pmh=$!
until_held
"$S" m-n --min-gb 1 -- sh -c "echo n >> $T/order-p2" & pmn=$!; sleep 0.3
"$S" m-r --min-gb 7 --prio 2 -- sh -c "echo r >> $T/order-p2" & pmr=$!; sleep 0.3
touch "$T/m-go"
wait $pmh
until_f '"$S" --status | grep -q "^ДЕРЖИТ: m-r .* память "'; held_mem=$?
sleep 0.6
early=$([ -s "$T/order-p2" ] && echo 1 || echo 0)
mem 8
wait $pmn $pmr
o=$(tr '\n' '|' < "$T/order-p2")
ok "приоритет не обходит порог памяти: при 5 ГБ «Обустроить» (порог 7) держит очередь в ожидании памяти, никто не запущен; 8 ГБ — он, потом обычный ($o)" \
  "$(yes_if '[ $held_mem = 0 ] && [ $early = 0 ] && [ "$o" = "r|n|" ] && grep -q "m-r .*держит очередь, ждёт память" "$HEAVY_SLOT_LOG"')"

# держатель, ещё ждущий память, отдаёт слот пришедшему старшего класса сразу и встаёт со СВОИМ билетом: при 5 ГБ обычный y-h
# (порог 7) держит слот в ожидании памяти, за ним обычный y-n (порог 1); пришёл y-r (2, порог 1) — идёт сразу; дальше голова
# снова y-h (номер раньше y-n): y-n при 5 ГБ не стартует; 8 ГБ — y-h, потом y-n. Встань y-h в конец — было бы r|n|h
mem 5
"$S" y-h --min-gb 7 -- sh -c "echo h >> $T/order-p4" & pyh=$!
until_f '"$S" --status | grep -q "^ДЕРЖИТ: y-h .* память "'; yh_mem=$?
"$S" y-n --min-gb 1 -- sh -c "echo n >> $T/order-p4" & pyn=$!; sleep 0.3
"$S" y-r --min-gb 1 --prio 2 -- sh -c "echo r >> $T/order-p4" & pyr=$!
wait $pyr
sleep 0.8
early=$(tr '\n' '|' < "$T/order-p4")
until_f '"$S" --status | grep -q "^ДЕРЖИТ: y-h .* память "'; yh_back=$?
mem 8
wait $pyh $pyn
o=$(tr '\n' '|' < "$T/order-p4")
ok "держатель, ждущий память, сразу отдал слот «Обустроить» и вернулся со своим билетом впереди равных (до 8 ГБ: $early; итог $o)" \
  "$(yes_if '[ $yh_mem = 0 ] && [ $yh_back = 0 ] && [ "$early" = "r|" ] && [ "$o" = "r|h|n|" ] && grep -q "y-h .*отдал слот старшему классу: y-r .*приоритет 2.*своим билетом" "$HEAVY_SLOT_LOG"')"

# защита от голодания: ждущий дольше HEAVY_SLOT_PRIO_AGE_MIN — старший класс; приоритетный, пришедший позже, его не обгоняет
export HEAVY_SLOT_PRIO_AGE_MIN=0.0002             # 12 мс: обычный «состарился» ещё до прихода приоритетного
"$S" a-hold -- sh -c "$(gate a-go)" &
pah=$!
until_held
"$S" a-n -- sh -c "echo n >> $T/order-p3" & pan=$!; sleep 0.3
"$S" a-r --prio 2 -- sh -c "echo r >> $T/order-p3" & par=$!; sleep 0.3
touch "$T/a-go"
wait $pah $pan $par
unset HEAVY_SLOT_PRIO_AGE_MIN
o=$(tr '\n' '|' < "$T/order-p3")
ok "защита от голодания: обычный, ждущий дольше HEAVY_SLOT_PRIO_AGE_MIN, идёт раньше пришедшего позже приоритетного ($o)" \
  "$(yes_if '[ "$o" = "n|r|" ]')"

# T-20261110-29: резерв пробы — обычные держат ВСЕ обычные слоты (2), памяти много; задание класса 1 идёт в резерв сразу,
# обычный ждёт; без резерва (HEAVY_SLOT_PRIO_SLOTS=0) класс 1 при занятых слотах ждёт (таймаут → 124)
mem 16
export HEAVY_SLOT_SLOTS=2
"$S" v-h1 --min-gb 1 -- sh -c "$(gate v-go)" & pv1=$!
until_held
"$S" v-h2 --min-gb 1 -- sh -c "$(gate v-go)" & pv2=$!
until_f '"$S" --status | grep -q "^ДЕРЖИТ: v-h2 .* · слот 2$"'; v2_up=$?
"$S" v-n --min-gb 1 -- sh -c "echo n >> $T/order-v" & pvn=$!; sleep 0.3
HEAVY_SLOT_PRIO_SLOTS=0 "$S" v-x --min-gb 1 --prio 1 --timeout 1 -- sh -c "echo x >> $T/order-v"; rc_x=$?
"$S" v-u --min-gb 1 --prio 1 -- sh -c "echo u >> $T/order-v" & pvu=$!
wait $pvu
early=$(tr '\n' '|' < "$T/order-v")
st=$("$S" --status)
touch "$T/v-go"
wait $pv1 $pv2 $pvn
unset HEAVY_SLOT_SLOTS
o=$(tr '\n' '|' < "$T/order-v")
ok "резерв пробы: оба обычных слота заняты — класс 1 идёт в резерв (слот 3) сразу, обычный ждёт; без резерва класс 1 ждёт (rc $rc_x) ($early → $o)" \
  "$(yes_if '[ $v2_up = 0 ] && [ $rc_x = 124 ] && [ "$early" = "u|" ] && [ "$o" = "u|n|" ] && grep -q "v-u .*взял: .*приоритет 1; слот 3" "$HEAVY_SLOT_LOG" && grep -q "^СЛОТОВ: 2 .*резерв пробы 1" <<<"$st"')"
wv() { python3 -c "import sys; sys.path.insert(0, '$DIR'); import heavy_slot as h; print(h.waiting($1))"; }
mem 8                                              # 8 < 6 + 6 + запас: дополнительные слоты не открываются, оба ждут
"$S" w-h -- sh -c "$(gate w-go)" & pwh=$!
until_held
"$S" w-n -- true & pwn=$!
"$S" w-u --prio 1 -- true & pwu=$!
until_f '[ "$(wv 0)" = 2 ]'; w_all=$?
w_cls=$(wv 1)
touch "$T/w-go"
wait $pwh $pwn $pwu
ok "waiting(1) считает только ждущих класса ≥ 1 (предохранитель воркера пробы): всех 2, класса ≥ 1 — $w_cls" \
  "$(yes_if '[ $w_all = 0 ] && [ "$w_cls" = 1 ]')"

"$S" bad-prio --prio 5 -- true 2>"$T/bad-prio.err"; rc=$?
pv() { HEAVY_SLOT_PRIO="$1" python3 -c "import sys; sys.path.insert(0, '$DIR'); from heavy_slot import prio_env; print(prio_env())"; }
ok "класс вне 0…2: --prio 5 → rc 2 с подсказкой; HEAVY_SLOT_PRIO=abc → 0, 9 → 2, -1 → 0" \
  "$(yes_if '[ $rc = 2 ] && grep -q "нужно 0…2" "$T/bad-prio.err" && [ "$(pv abc) $(pv 9) $(pv -1)" = "0 2 0" ]')"

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

# держатель отпускает слот только ПОСЛЕ убийства ожидающего (файл-сигнал), а не через фиксированную паузу: под нагрузкой
# старт питона ожидающих дольше 1,2 с — держатель уходил раньше, «умерший» успевал взять слот и выполниться (T-20261106-95)
"$S" d-hold -- sh -c "while [ ! -e $T/dead-killed ]; do sleep 0.05; done" &
pdh=$!
until_held
"$S" d-dead -- sh -c "echo dead >> $T/dead" &
pdd=$!
sleep 0.3
"$S" d-next --timeout 5 -- sh -c "echo next >> $T/dead" &
pdn=$!
sleep 0.2
kill -9 "$pdd"; wait "$pdd" 2>/dev/null; touch "$T/dead-killed"
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

pair() {   # <файл> <метка1> <порог1> <метка2> <порог2> → порядок start/end двух задач; --status — в <файл>.st
  # детерминированно (T-80; было sleep 0,4 / 0,8 — мигало под нагрузкой): команда держит слот до своего флага «отпускай»;
  # снимок --status — когда второй стартовал или, попробовав допуск, встал ждать («ждёт очередь» пишется после первой
  # неудачной попытки; память подменена и не меняется — дальше так же); отпускаем по одному: сперва первый, потом второй
  local f="$T/$1"
  "$S" "$2" --min-gb "$3" -- sh -c "$(holdp "$2" "$1")" & local p1=$!
  until_f "[ -e $f.up-$2 ]"
  "$S" "$4" --min-gb "$5" -- sh -c "$(holdp "$4" "$1")" & local p2=$!
  until_f "[ -e $f.up-$4 ] || grep -q ' $4 pid=[0-9]* ждёт очередь' '$HEAVY_SLOT_LOG'"
  "$S" --status > "$f.st"
  touch "$f.go-$2"
  until_f "grep -qx 'e$2' '$f'"
  touch "$f.go-$4"
  wait $p1 $p2
  tr '\n' '|' < "$f"
}
mem 14
o=$(pair two c1 4 c2 4)
ok "два слота: памяти хватает (14 ≥ 4 + (4 − память c1) + запас 1,5 — 10 % от 15,3 ГБ) — второй идёт параллельно ($o)" \
  "$(yes_if '[ "$o" = "sc1|sc2|ec1|ec2|" ] && grep -q "c2 .*взял: .*слот 2: свободно 14.0 ГБ ≥ свой 4 + держатели c1 4−0.0=4.0 + запас 1.5" "$HEAVY_SLOT_LOG"')"
ok "--status: оба держателя (второй — «слот 2») и число слотов" \
  "$(yes_if 'grep -q "^ДЕРЖИТ: c1 · pid .* работает с " "$T/two.st" && grep -q "^ДЕРЖИТ: c2 · pid .* работает с .* · слот 2$" "$T/two.st" && grep -q "^СЛОТОВ: 5 .*запас 1.5 ГБ" "$T/two.st" && ! grep -q "^СВОБОДНО" "$T/two.st"')"
mem 8
o=$(pair short c3 4 c4 4)
ok "два слота: памяти мало (8 < 4 + 4 + 1,5) — строго по одному ($o)" "$(yes_if '[ "$o" = "sc3|ec3|sc4|ec4|" ]')"
memt 40 11
o=$(pair res c5 4 c6 4)
ok "запас не меньше 10 % памяти: при 40 ГБ запас 4 — 11 < 4 + 4 + 4, по одному (при 5 % пошли бы вдвоём) ($o)" \
  "$(yes_if '[ "$o" = "sc5|ec5|sc6|ec6|" ] && grep -q "^СЛОТОВ: 5 .*запас 4.0 ГБ" "$T/res.st"')"
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
printf 's3-a 3.5\ns3-b 3.5\ns3-c 3.5\ns3-d 3.5\ns3-e 3.5\n' >> "$HEAVY_SLOT_MEM_STUB"
# детерминированно (T-74/3: на занятой машине снимок по sleep мигал): каждая команда ставит флаг «стартовала» и держит слот,
# пока нет флага «отпускай»; снимок --status — когда пятеро стартовали и шестой стоит первым в очереди.
# Слотов по умолчанию 5 (владелец 11.11, T-20261111-07; было 3 — T-74)
hold3() { echo "echo s$1 >> $T/$2; touch $T/up-$2-$1; while [ ! -e $T/go-$2 ]; do sleep 0.05; done; echo e$1 >> $T/$2"; }
for x in a b c d e f; do
  "$S" "s3-$x" --min-gb 4 -- sh -c "$(hold3 $x three)" & eval "p3_$x=$!"
  [ $x = f ] || until_f "[ -e $T/up-three-$x ]"
done
until_f '"$S" --status | grep -q "^  1\. s3-f "'
"$S" --status > "$T/three.st"
f_early=$([ -e "$T/up-three-f" ] && echo 1 || echo 0)
touch "$T/go-three"
wait $p3_a $p3_b $p3_c $p3_d $p3_e $p3_f
o=$(tr '\n' '|' < "$T/three")
ok "пять слотов (по умолчанию): 14 ≥ 4 × 0,5 + 4 + 1,5 — пятеро параллельно, шестой ждёт слот ($o)" \
  "$(yes_if '[ $f_early = 0 ] && [[ "$o" =~ ^sa\|sb\|sc\|sd\|se\|(e[abcde]\|)+sf\| ]] && [ $(grep -c "^ДЕРЖИТ" "$T/three.st") = 5 ] && grep -q "^ДЕРЖИТ: s3-e .* · слот 5$" "$T/three.st" && grep -q "^  1\. s3-f " "$T/three.st"')"
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
# T-91: порог по замеру — с 1 засчитанного замера; множитель 2 при 1–2 замерах, 1,5 при 3+
printf '2026-11-06 10:00:00\tparity\tparity-x\t0.3\t0.3\t100.0\t6\t6\n' >> "$P"
"$S" parity-a --min-gb 6 --timeout 3 -- true; rc=$?
ok "один замер parity (пик 0,3) → порог min(6, 2 × 0,3) = 0,6: 3 ≥ 0,6 — пошла" \
  "$(yes_if '[ $rc = 0 ] && grep -q "parity-a .*порог по замеру: объявлен 6, тип parity, замеров 1, наибольший пик 0.30 ГБ × 2 → 0.60" "$HEAVY_SLOT_LOG"')"
printf '2026-11-06 10:00:00\tparity\tparity-x\t0.5\t0.5\t100.0\t6\t6\n' >> "$P"
printf '2026-11-06 10:00:00\tparity\tparity-y\t0.4\t0.4\t5.0\t6\t6\n' >> "$P"   # держал 5 с < 30 — не засчитан
"$S" parity-b --min-gb 6 --timeout 3 -- true; rc=$?
ok "два замера (короткое держание < 30 с не в счёт) → 2 × 0,5 = 1,0" \
  "$(yes_if '[ $rc = 0 ] && grep -q "parity-b .*порог по замеру: объявлен 6, тип parity, замеров 2, наибольший пик 0.50 ГБ × 2 → 1.00" "$HEAVY_SLOT_LOG"')"
printf '2026-11-06 10:00:00\tparity\tparity-z\t0.4\t0.4\t200.0\t6\t6\n' >> "$P"
"$S" parity-c --min-gb 6 --timeout 3 -- true; rc=$?
ok "три замера parity, пик 0,5 → множитель 1,5: порог min(6, 0,75): 3 ≥ 0,75 — пошла" \
  "$(yes_if '[ $rc = 0 ] && grep -q "parity-c .*порог по замеру: объявлен 6, тип parity, замеров 3, наибольший пик 0.50 ГБ × 1.5 → 0.75" "$HEAVY_SLOT_LOG"')"
# множитель решает допуск: gates, пик 1,0 — при 2 замерах порог 2,0 (> 1,8 свободных — 124), при 3 — 1,5 (пошла)
memt 15.26 1.8                                     # запас — 10 % от 15,26 = 1,53 < 1,8: сторож пускает
for v in 0.6 1.0; do printf '2026-11-06 10:00:00\tgates\tt9-gates\t%s\t%s\t100.0\t3\t3\n' $v $v >> "$P"; done
"$S" t91-gates --min-gb 3 --timeout 1 -- true; rc=$?
ok "два замера gates (пик 1,0) → 2 × 1,0 = 2,0 > 1,8 свободных — не дождался (124)" \
  "$(yes_if '[ $rc = 124 ] && grep -q "t91-gates .*замеров 2, наибольший пик 1.00 ГБ × 2 → 2.00" "$HEAVY_SLOT_LOG"')"
printf '2026-11-06 10:00:00\tgates\tt9-gates\t0.9\t0.9\t100.0\t3\t3\n' >> "$P"
HEAVY_SLOT_LOG="$T/gates-b.log" "$S" t91-gates --min-gb 3 --timeout 3 -- true; rc=$?
ok "третий замер gates → 1,5 × 1,0 = 1,5 ≤ 1,8 — пошла" \
  "$(yes_if '[ $rc = 0 ] && grep -q "t91-gates .*замеров 3, наибольший пик 1.00 ГБ × 1.5 → 1.50" "$T/gates-b.log"')"
ok "eff_threshold напрямую: 0 замеров — объявленный; 1 → ×2; 2 → ×2; 3+ → ×1,5; пол 0,5; не выше объявленного" \
  "$(yes_if '[ "$(python3 -c "
import sys; sys.path.insert(0, \"$DIR\"); import heavy_slot as H
r = lambda *p: [dict(type=\"t\", peak_gb=x, hold_s=100.0) for x in p]
print(*[round(H.eff_threshold(\"\", \"t\", 6, x)[0], 2) for x in (r(), r(1), r(1, 1.2), r(1, 1.2, 0.8), r(0.1), r(5))], *[H.eff_mult(n) for n in (0, 1, 2, 3, 10)])
")" = "6 2.0 2.4 1.8 0.5 6 0.0 2.0 2.0 1.5 1.5" ]')"
mem 8
echo "parity-h 0.2" >> "$HEAVY_SLOT_MEM_STUB"
o=$(pair eff parity-h 6 e-x 5.5)
ok "доля держателя — по ЕГО эффективному порогу: 8 ≥ (0,75 − 0,2) + 5,5 + 1,5 — параллельно; --status: «по замеру 0.75» ($o)" \
  "$(yes_if '[ "$o" = "sparity-h|se-x|eparity-h|ee-x|" ] && grep -q "^ДЕРЖИТ: parity-h .*порог 6.0 ГБ (по замеру 0.75)" "$T/eff.st"')"
# T-91: превышение — держатель взял больше своего порога по замеру; без защиты его доля 0 (память уже вычтена) — пустили бы
echo "parity-ov 2" >> "$HEAVY_SLOT_MEM_STUB"
o=$(pair ovr parity-ov 6 ov-x 4)
ok "превышение: parity (порог по замеру 0,75) взял 2 → доля max(6, 2) − 2 = 4: 8 < 4 + 4 + 1,5 — по одному (без защиты 0 + 4 + 1,5 ≤ 8 — пустили бы) ($o)" \
  "$(yes_if '[ "$o" = "sparity-ov|eparity-ov|sov-x|eov-x|" ] && grep -q "держатели могут взять ещё 4.0 ГБ" "$T/ovr.st" && grep -q "parity-ov .*WARN: превысил свой порог 0.75 ГБ (пик 2.00)" "$HEAVY_SLOT_LOG"')"
# пик прогона выше, чем память сейчас (память скачет): доля — от пика, который замер записал в запись держателя
echo "parity-pk 2" >> "$HEAVY_SLOT_MEM_STUB"
"$S" parity-pk --min-gb 6 -- sh -c "$(holdp parity-pk pk)" & ppk=$!
until_f "[ -e $T/pk.up-parity-pk ]"
until_f 'grep -q "^peak_gb=2" "$HEAVY_SLOT_DIR/holder"'; pk_w=$?
echo "parity-pk 0.3" >> "$HEAVY_SLOT_MEM_STUB"     # сейчас 0,3 — по старому правилу доля 0,75 − 0,3 = 0,45, пустили бы 4
"$S" pk-x --min-gb 4 -- sh -c "$(holdp pk-x pk)" & ppx=$!
until_f "[ -e $T/pk.up-pk-x ] || grep -q ' pk-x pid=[0-9]* ждёт очередь' '$HEAVY_SLOT_LOG'"
"$S" --status > "$T/pk.st"
touch "$T/pk.go-parity-pk"; until_f "grep -qx 'eparity-pk' '$T/pk'"; touch "$T/pk.go-pk-x"
wait $ppk $ppx
o=$(tr '\n' '|' < "$T/pk")
ok "превышение по пику: пик прогона 2 записан, сейчас 0,3 → доля max(6, 2) − 0,3 = 5,7 — по одному; --status: «превысил порог: пик 2.00» ($o)" \
  "$(yes_if '[ $pk_w = 0 ] && [ "$o" = "sparity-pk|eparity-pk|spk-x|epk-x|" ] && grep -q "держатели могут взять ещё 5.7 ГБ" "$T/pk.st" && grep -q "^ДЕРЖИТ: parity-pk .*(по замеру 0.75) · превысил порог: пик 2.00 ГБ — доля по факту" "$T/pk.st"')"
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

# --- T-79: обгон головы (backfill) и защита головы от голодания; детерминированно — флаги «стартовал»/«отпускай», без sleep
mem 7
echo "bf-h 2" >> "$HEAVY_SLOT_MEM_STUB"          # держатель 4 ГБ уже взял 2: место следующим 7 − (4 − 2) − 1,5 = 3,5
bf_case() {   # <имя>: bf-h (порог 4) держит до флага go-<имя>; голова <имя>-a (6) встала первой; хвост <имя>-b (2) — за ней
  local f=$1
  "$S" bf-h --min-gb 4 -- sh -c "$(hold3 h "$f")" & eval "pbh_$f=$!"
  until_f "[ -e $T/up-$f-h ]"
  "$S" "$f-a" --min-gb 6 -- sh -c "echo sa >> $T/$f" & eval "pba_$f=$!"
  until_f '"$S" --status | grep -q "^  1\. '"$f"'-a "'
  "$S" "$f-b" --min-gb 2 -- sh -c "$(hold3 b "$f")" & eval "pbb_$f=$!"
}
bf_case bfo
until_f "[ -e $T/up-bfo-b ]"; tail_up=$?
"$S" --status > "$T/bfo.st"
a_early=$(grep -q '^sa$' "$T/bfo" && echo 1 || echo 0)
touch "$T/go-bfo"
wait $pbh_bfo $pba_bfo $pbb_bfo
o=$(tr '\n' '|' < "$T/bfo")
ok "обгон: голова 6 не проходит (7 < 2 + 6 + 1,5), хвост 2 проходит (место 3,5) — идёт при держателе, голова после ($o)" \
  "$(yes_if '[ $tail_up = 0 ] && [ $a_early = 0 ] && [[ "$o" =~ ^sh\|sb\|e[hb]\|e[hb]\|sa\|$ ]] && grep -q "bfo-b .*взял: .*слот 2: обогнал голову bfo-a (порог 6 не проходит: место 3.5 ГБ" "$HEAVY_SLOT_LOG"')"
ok "--status: у обогнавшего «обогнал голову», строка «ОБГОН: открыт»" \
  "$(yes_if 'grep -q "^ДЕРЖИТ: bfo-b · .* · обогнал голову bfo-a · слот 2$" "$T/bfo.st" && grep -q "^ОБГОН: открыт — голова bfo-a ждёт 0 мин из 20" "$T/bfo.st"')"
export HEAVY_SLOT_BACKFILL_MIN=0.0002             # 12 мс: голова ждёт дольше ещё до прихода хвоста
bf_case bfc
until_f 'grep -q "bfc-b .*обгон закрыт: голова bfc-a ждёт" "$HEAVY_SLOT_LOG"'; closed=$?
"$S" --status > "$T/bfc.st"
b_early=$([ -e "$T/up-bfc-b" ] && echo 1 || echo 0)
touch "$T/go-bfc"
wait $pbh_bfc $pba_bfc $pbb_bfc
unset HEAVY_SLOT_BACKFILL_MIN
o=$(tr '\n' '|' < "$T/bfc")
ok "защита головы: голова ждёт дольше HEAVY_SLOT_BACKFILL_MIN — хвост не обгоняет, идёт после неё ($o)" \
  "$(yes_if '[ $closed = 0 ] && [ $b_early = 0 ] && [ "$o" = "sh|eh|sa|sb|eb|" ] && grep -q "^ОБГОН: обгон закрыт: голова bfc-a ждёт 0 мин (≥ 0.0002)" "$T/bfc.st" && ! grep -q "обогнал голову" "$T/bfc.st"')"
"$S" bf-solo --min-gb 6 -- true; rc=$?
ok "одиночный — как раньше: 7 ≥ 6 сразу, без обгона" \
  "$(yes_if '[ $rc = 0 ] && grep -q "bf-solo .*взял: ждал 0" "$HEAVY_SLOT_LOG" && ! grep -q "bf-solo .*обг" "$HEAVY_SLOT_LOG"')"
mem 8

unset HEAVY_SLOT_MEM_STUB
HEAVY_SLOT_SAMPLE=0.1 HEAVY_SLOT_LONG_S=0.4 HEAVY_SLOT_MEASURE_MIN_S=0 \
  "$S" t74-build-real --min-gb 1 -- python3 -c "import time; b = bytearray(300 << 20); b[::4096] = b'x' * len(b[::4096]); time.sleep(0.9)"
ln=$(grep "t74-build-real .*отпустил" "$HEAVY_SLOT_LOG")
pk=$(sed -n 's/.*пик памяти дерева \([0-9.]*\) ГБ.*/\1/p' <<<"$ln")
ok "замер: пик памяти дерева с потомком (300 МБ) — ${pk} ГБ, тип build; WARN долгого держания в журнале; строка в peaks.tsv" \
  "$(yes_if 'awk -v p="$pk" "BEGIN{exit !(p >= 0.28 && p < 1)}" && grep -q "тип build" <<<"$ln" && grep -q "WARN: держание дольше" <<<"$ln" && grep -q "t74-build-real .*WARN: держит слот дольше" "$HEAVY_SLOT_LOG" && grep -q "	build	t74-build-real	" "$P"')"
printf '2026-11-06 10:00:00\tshadow\tt56-shadow\t0.78\t0.78\t900.0\t5\t5\n' >> "$P"
st=$(HEAVY_SLOT_LONG_S=0.4 "$S" --stats)
ok "--stats: множитель на тип — parity 3 засчитано: 6 → 0.75 (× 1,5); shadow 1 замер: 5 → 1.56 (× 2); build (держал < 30 с) — нет засчитанных; долгие" \
  "$(yes_if 'grep -q "^parity .* ( 3) .*6 → 0.75  (× 1.5)" <<<"$st" && grep -q "^shadow .* 1 ( 1) .*5 → 1.56  (× 2 — 1–2 замера)" <<<"$st" && grep -q "^build .*(нет засчитанных)" <<<"$st" && grep -q "^ДОЛГИЕ" <<<"$st"')"
ok "тип задачи по метке" "$(yes_if '[ "$(python3 -c "import sys; sys.path.insert(0, \"$DIR\"); from heavy_slot import task_type as t; print(\" \".join(t(x) for x in [\"parity-72\", \"parity-hall-exam\", \"t73-build\", \"t69-live\", \"parity-living-demo\", \"t51-look\", \"t73-hall-snap2\"]))")" = "parity exam build live parity look hall-snap" ]')"

st=$("$S" --status)
ok "после всех: очередь свободна, ожидающих нет" "$(yes_if 'grep -q "^СВОБОДНО" <<<"$st" && grep -q "^ЖДУТ: 0" <<<"$st"')"

if [ "$fails" = 0 ]; then echo "heavy-slot selftest: OK"; exit 0; fi
echo "heavy-slot selftest: $fails FAIL"; exit 1

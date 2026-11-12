#!/usr/bin/env bash
# Самопроверка `tools/ops/tour-reissue.sh` (T-20261112-92) во временной папке: заглушки вместо reissue.py, имени витрины, тревоги;
# сеть, ключи и туры не нужны. Код 0 — все случаи прошли.
#   bash tools/ops/tour-reissue-selftest.sh
set -uo pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
. "$HERE/remlab-tmp.sh"
T=$(mktemp -d "$REMLAB_TMP/tour-reissue-st.XXXX")
trap 'rm -rf "$T"' EXIT
fail=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fail=1; }
H=0123456789abcdef0123456789abcdef

# заглушка reissue.py: строки отчёта — из $STUB_ROWS (json), новая сборка тура — по образцу demo; пауза — $STUB_SLEEP
cat > "$T/reissue-stub.py" <<'PY'
import json, os, sys, time
a = sys.argv[1:]
out = a[a.index('--out') + 1]
assert '--cards' in a and a[a.index('--cards') + 1] == 'batch', a
time.sleep(float(os.environ.get('STUB_SLEEP') or 0))
rows = json.loads(os.environ['STUB_ROWS'])
hold = a[a.index('--hold') + 1] if '--hold' in a else ''
held = {x.strip() for x in open(hold).read().splitlines()} - {''} if hold and os.path.exists(hold) else set()
rows = [dict(id=r['id'], status='skipped', why='hold') if r['id'] in held else r for r in rows]   # как reissue.py --hold
demo = json.load(open(os.environ['STUB_DEMO']))
for r in rows:
    if r['status'] in ('published', 'built'):
        os.makedirs(os.path.join(out, r['id']), exist_ok=True)
        b = dict(demo, trial={'panels': [{'rooms': [1], 'openings': [{'kind': 'door'}]}]}, **r.get('patch', {}))
        json.dump(b, open(os.path.join(out, r['id'], 'bundle-new.json'), 'w'))
json.dump(rows, open(os.path.join(out, 'report.json'), 'w'))
print('stub', ' '.join(a))
sys.exit(1 if any(r['status'] in ('refused', 'failed') for r in rows) else 0)
PY
printf '#!/bin/sh\necho "$STUB_HASH"\n' > "$T/hash-stub.sh"
printf '#!/bin/sh\nprintf "%%s\\n" "$1" >> "%s/alerts.txt"\n' "$T" > "$T/alert-stub.sh"
# STUB_ORPHAN=1 — сборщик оставляет живого потомка (как зависший браузер): он не должен держать замок прохода
printf '#!/bin/sh\n[ -n "$STUB_ORPHAN" ] && (sleep 6 >/dev/null 2>&1 &)\nexec python3 "%s/reissue-stub.py" "$@"\n' "$T" > "$T/reissue-stub.sh"
chmod +x "$T"/*.sh
mkdir -p "$T/demo"
printf '{"build": "abc.r1", "rules": {"sofa_tv_cm": 200, "slot_band_cm": {"x": 1}}, "feeds": {"диван": [1, 2]}}\n' > "$T/demo/demo-data.json"

run() {   # run <случай> [env…] — свежая папка журналов на случай
  local c=$1; shift
  [ -n "${KEEP_LOGS:-}" ] || rm -rf "$T/logs" "$T/alerts.txt"
  env TOUR_REISSUE_CMD="$T/reissue-stub.sh" TOUR_REISSUE_HASH_CMD="$T/hash-stub.sh" TOUR_REISSUE_ALERT="$T/alert-stub.sh" \
    TOUR_REISSUE_ENV="$T/none.env" TOUR_REISSUE_LOGS="$T/logs" TOUR_REISSUE_LOCK="$T/lock" TOUR_REISSUE_NO_SLOT=1 \
    TOUR_REISSUE_DEMO_URL="$T/demo/" TOUR_REISSUE_PY=python3 TOUR_REISSUE_TMP="$T/tmp" TOUR_REISSUE_HOLD="$T/hold.txt" STUB_DEMO="$T/demo/demo-data.json" \
    STUB_HASH=$H "$@" bash "$HERE/tour-reissue.sh" ${BG_ARG:-} --why "проба $c" > "$T/out-$c.txt" 2>&1
  echo $? > "$T/rc-$c.txt"
}
has() { grep -qF -- "$2" "$T/out-$1.txt"; }

# 1. обычный проход: 2 перевыпущены на витрине /demo, 1 без изменений, 1 занят агентом — тревоги нет, код 0
R1='[{"id":"a1","status":"published","release":"'$H'","repeated":false},
     {"id":"a2","status":"published","release":"'$H'","repeated":true,"unchanged":true},
     {"id":"a3","status":"published","release":"'$H'","repeated":true},
     {"id":"a4","status":"skipped","why":"busy"}]'
run ok STUB_ROWS="$R1"
[ "$(cat "$T/rc-ok.txt")" = 0 ] && ok "чистый проход — код 0" || bad "чистый проход — код $(cat "$T/rc-ok.txt")"
has ok 'tour_reissue: туров 4 · перевыпущено 2 (из них «только страница» 1) · без изменений 1 · пропущено 1 (busy 1) · отказ 0' \
  && ok "итог со счётчиками" || bad "итог со счётчиками: $(grep tour_reissue: "$T/out-ok.txt")"
grep -qP '^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\tok\ttour_reissue: туров 4 .*\t\t.*-auto$' "$T/logs/reissue.log" \
  && ok "журнал проходов: время, ok, итог, папка (для ночной сводки)" || bad "журнал проходов: $(cat "$T/logs/reissue.log")"
has ok 'на витрине /demo 2 из 2 опубликованных' || has ok 'на витрине /demo 3 из 3 опубликованных' && ok "страница сверена" || bad "страница не сверена"
has ok 'данные a1: сверено' && ok "данные сверены" || bad "данные: $(grep 'данные' "$T/out-ok.txt")"
[ ! -e "$T/alerts.txt" ] && ok "без тревоги" || bad "лишняя тревога"
grep -q 'повод: проба ok' "$T/logs/reissue.log" && ok "строка в reissue.log" || bad "нет строки в reissue.log"
! grep -q '^WARN:' "$T/out-ok.txt" && ok "WARN нет" || bad "лишний WARN: $(grep '^WARN:' "$T/out-ok.txt")"

# 2. отказ сборщика и тур на чужой витрине — WARN с id, тревога днём, код 1
R2='[{"id":"b1","status":"published","release":"ffff0000ffff0000ffff0000ffff0000"},
     {"id":"b2","status":"refused","why":"no_source","detail":"x"}]'
run bad STUB_ROWS="$R2"
[ "$(cat "$T/rc-bad.txt")" = 1 ] && ok "отказ — код 1" || bad "отказ — код $(cat "$T/rc-bad.txt")"
has bad 'WARN:tour_reissue: тур b2 — отказ сборщика no_source' && ok "отказ не молча" || bad "отказ молча"
has bad 'WARN:tour_reissue: тур b1 на витрине ffff0000ffff' && ok "чужая витрина поймана" || bad "чужая витрина не поймана"
grep -q 'Замечаний 2' "$T/alerts.txt" 2>/dev/null && ok "днём — тревога" || bad "днём тревоги нет"

# 3. ночью — без тревоги, важной строкой сводки
run night STUB_ROWS="$R2" TOUR_REISSUE_NIGHT=1
grep -qP '\twarn\ttour_reissue: туров 2 .*\tзамечаний 2, первое — тур b2 — отказ сборщика no_source' "$T/logs/reissue.log" \
  && ok "ночью — замечания в журнал проходов (сводка следующей ночи)" || bad "ночью: $(cat "$T/logs/reissue.log")"
[ ! -e "$T/alerts.txt" ] && ok "ночью тревоги нет" || bad "ночью ушла тревога"

# 4. данные тура собраны другими правилами — расхождение
R4='[{"id":"c1","status":"published","release":"'$H'","patch":{"build":"def.r2","rules":{"sofa_tv_cm":180,"slot_band_cm":{"y":2}}}}]'
run drift STUB_ROWS="$R4"
has drift 'правила сборщика r2 ≠ /demo r1' && ok "метка правил сверена" || bad "метка правил: $(grep c1 "$T/out-drift.txt")"
has drift 'правила страницы отличаются: sofa_tv_cm' && ok "правила страницы сверены (полосы квартиры — нет)" \
  || bad "правила страницы: $(grep c1 "$T/out-drift.txt")"

# 5. выкладка во время прохода: второй запуск не идёт параллельно, после первого — ровно один повторный проход
rm -rf "$T/logs"; mkdir -p "$T/logs"
env TOUR_REISSUE_CMD="$T/reissue-stub.sh" TOUR_REISSUE_HASH_CMD="$T/hash-stub.sh" TOUR_REISSUE_ALERT="$T/alert-stub.sh" \
  TOUR_REISSUE_ENV="$T/none.env" TOUR_REISSUE_LOGS="$T/logs" TOUR_REISSUE_LOCK="$T/lock" TOUR_REISSUE_NO_SLOT=1 \
  TOUR_REISSUE_DEMO_URL="$T/demo/" TOUR_REISSUE_PY=python3 TOUR_REISSUE_TMP="$T/tmp" TOUR_REISSUE_HOLD="$T/hold.txt" STUB_DEMO="$T/demo/demo-data.json" \
  STUB_HASH=$H STUB_ROWS="$R1" STUB_SLEEP=2 bash "$HERE/tour-reissue.sh" --why first > "$T/out-first.txt" 2>&1 &
pid=$!
for _ in $(seq 1 50); do [ -n "$(ls "$T/logs/reissue" 2>/dev/null)" ] && break; sleep 0.1; done
KEEP_LOGS=1 run second STUB_ROWS="$R1"
KEEP_LOGS=1 run third STUB_ROWS="$R1"
wait "$pid"
has second 'проход уже идёт' && has third 'проход уже идёт' && ok "второй и третий — не параллельно" || bad "запустились параллельно"
n=$(ls "$T/logs/reissue" | grep -c auto)
[ "$n" = 2 ] && ok "три выкладки подряд — два прохода" || bad "проходов $n (ждали 2)"

# 6. сборщик оставил живого потомка — замок им не держится: следующий проход идёт сразу, а не «уже идёт»
run orphan STUB_ROWS="$R1" STUB_ORPHAN=1
KEEP_LOGS=1 run after STUB_ROWS="$R1"
! has after 'проход уже идёт' && [ "$(ls "$T/logs/reissue" | grep -c auto)" = 2 ] \
  && ok "зависший потомок не держит замок" || bad "потомок держит замок: $(cat "$T/out-after.txt")"

# 7. --bg (как ночь и хук выкладки): сразу «запущен», проход идёт сам и пишет журнал
t0=$(date +%s)
BG_ARG=--bg run bg STUB_ROWS="$R1" TOUR_REISSUE_NO_SYSTEMD=1 STUB_SLEEP=1
has bg 'проход запущен в фоне без systemd' && [ $(( $(date +%s) - t0 )) -lt 2 ] && ok "--bg не ждёт прохода" \
  || bad "--bg: $(cat "$T/out-bg.txt")"
for _ in $(seq 1 100); do grep -q 'повод: проба bg' "$T/logs/reissue.log" 2>/dev/null && break; sleep 0.1; done
grep -q 'повод: проба bg' "$T/logs/reissue.log" 2>/dev/null && ok "фоновый проход дошёл до журнала" || bad "фоновый проход не записал итог"

# 8. «держать» (T-92/5): id в файле — тур пропущен строкой hold и WARN с id; остальные идут
printf 'a3\n' > "$T/hold.txt"
run hold1 STUB_ROWS="$R1"
has hold1 'пропущено 2 (busy 1, hold 1)' && has hold1 'WARN:tour_reissue: держим 1 тур(ов) по списку «держать» — не перевыпущены: a3' \
  && has hold1 'перевыпущено 1' && ok "держать по id — тур пропущен, WARN с id" || bad "держать по id: $(grep -E 'tour_reissue|WARN' "$T/out-hold1.txt")"
# 9. «*» — прохода нет вовсе (сборщик не зван), строка warn «на паузе» в журнал; днём тревога, ночью нет
printf '# починка спален, T-96\n*\n' > "$T/hold.txt"
run holdall STUB_ROWS="$R1"
! has holdall 'stub ' && ! ls "$T"/logs/reissue/*/pass.log >/dev/null 2>&1 && ok "«*» — сборщик не зван" || bad "«*»: сборщик зван"
grep -qP '\twarn\ttour_reissue: на паузе .*\tзамечаний 1, первое — перевыпуск туров на паузе' "$T/logs/reissue.log" \
  && ok "«*» — строка «на паузе» в журнал проходов" || bad "«*» журнал: $(cat "$T/logs/reissue.log")"
grep -q 'на паузе' "$T/alerts.txt" 2>/dev/null && ok "«*» днём — тревога" || bad "«*» днём тревоги нет"
run holdnight STUB_ROWS="$R1" TOUR_REISSUE_NIGHT=1
[ ! -e "$T/alerts.txt" ] && grep -q 'на паузе' "$T/logs/reissue.log" && ok "«*» ночью — без тревоги, в сводку" || bad "«*» ночью"
rm -f "$T/hold.txt"

[ "$fail" = 0 ] && echo "tour-reissue selftest: все случаи прошли" || echo "tour-reissue selftest: ЕСТЬ ПРОВАЛЫ"
exit "$fail"

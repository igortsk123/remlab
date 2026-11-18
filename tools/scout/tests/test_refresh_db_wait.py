#!/usr/bin/env python3
"""Ожидание базы перед шагом дневной сборки (T-20261112-56/5, план stock-check-fix-01, вариант D).

После обвала postgres (нехватка памяти контейнера) база поднимается несколько секунд, а `price_truth` стартовал сразу за
`stock_check` и падал строкой «FATAL: the database system is not yet accepting connections». Теперь `STEP_DB_WAIT=<с> step …`
перед командой шага ждёт `select 1`. Проверяем настоящие `db_wait()` и `step()` из `refresh_daily.sh` на заглушке `db_ping`
(без docker и без базы), как в кроне (env без LANG):
  - без STEP_DB_WAIT проба базы не вызывается вовсе, прежнее поведение шага;
  - база отвечает сразу — шаг идёт, WARN нет;
  - база поднимается через несколько проб — шаг идёт, в статусе warn со строкой WARN:db_wait;
  - не дождались за срок — шаг НЕ запускается, в выводе понятная причина (не FATAL), rc=75, итог FAIL, строка STEPTIME;
  - переменная не «прилипает» к следующему шагу; ожидание стоит у price_truth и pool_photos и не стоит у stock_check;
  - `bash -n refresh_daily.sh`.
    python3 tools/scout/tests/test_refresh_db_wait.py
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
SRC = os.path.join(SCOUT, 'refresh_daily.sh')
sys.path.insert(0, SCOUT)
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_refresh_db_wait')   # временное теста — на диске, не в /tmp

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if not cond and extra else ''))
    fails += 0 if cond else 1


# db_ping — заглушка: считает вызовы в файле $TD/pings; отвечает, когда номер вызова > $UP_AFTER (999 — никогда)
SH = r'''set -u
LOG="$TD/log"; STEP_TMP="$TD/step"; REMLAB_TMP="$TD"
remlab_tmp_free() { echo 1; }
declare -A RES; declare -A WARNS; declare -A WARNN
eval "$(sed -n '/^db_ping() {/p; /^db_wait() {/,/^}/p; /^step() {/,/^}/p' "$SRC")"
db_ping() { local n; n=$(( $(cat "$TD/pings" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$TD/pings"; [ "$n" -gt "${UP_AFTER:-0}" ]; }
export DB_WAIT_POLL=1
pings() { cat "$TD/pings" 2>/dev/null || echo 0; }
case "$MODE" in
  nowait)   step s_plain bash -c 'echo ran > "$TD/ran1"; echo "FATAL"'; echo "pings=$(pings)" ;;
  ready)    STEP_DB_WAIT=5 step s_ready bash -c 'echo ran > "$TD/ran2"; echo привет'; echo "rc=$? pings=$(pings)" ;;
  late)     STEP_DB_WAIT=6 step s_late bash -c 'echo ran > "$TD/ran3"; echo привет'; echo "rc=$? pings=$(pings)" ;;
  never)    STEP_DB_WAIT=3 step s_never bash -c 'echo ran > "$TD/ran4"'; echo "rc=$? pings=$(pings)" ;;
  noleak)   STEP_DB_WAIT=3 step s_a true; step s_b true; echo "pings=$(pings)" ;;
esac
echo "RES=${RES[s_plain]:-}${RES[s_ready]:-}${RES[s_late]:-}${RES[s_never]:-}"
echo "WARN=${WARNS[s_late]:-}"
'''


def run(mode, up_after=0):
    with tempfile.TemporaryDirectory(prefix='dbwait-') as td:
        sh = os.path.join(td, 'run.sh')
        open(sh, 'w', encoding='utf-8').write(SH)
        env = {'HOME': td, 'PATH': '/usr/bin:/bin', 'SHELL': '/bin/bash', 'TD': td, 'SRC': SRC, 'MODE': mode, 'UP_AFTER': str(up_after)}
        p = subprocess.run(['bash', sh], env=env, capture_output=True, text=True, timeout=60)
        log = open(os.path.join(td, 'log'), encoding='utf-8').read() if os.path.exists(os.path.join(td, 'log')) else ''
        ran = {n: os.path.exists(os.path.join(td, n)) for n in ('ran1', 'ran2', 'ran3', 'ran4')}
        return p, log, ran


def main() -> int:
    r = subprocess.run(['bash', '-n', SRC], capture_output=True, text=True)
    check('bash -n refresh_daily.sh', r.returncode == 0, r.stderr[-300:])

    p, log, ran = run('nowait', up_after=999)
    check('без STEP_DB_WAIT: проба базы не вызывается, шаг идёт как прежде (вывод в журнале)',
          p.returncode == 0 and 'pings=0' in p.stdout and ran['ran1'] and 'RES=ok' in p.stdout and 'FATAL' in log, p.stdout + p.stderr)

    p, log, ran = run('ready', up_after=0)
    check('база отвечает сразу: шаг идёт, ровно одна проба, итог ok, без WARN',
          'rc=0 pings=1' in p.stdout and ran['ran2'] and 'RES=ok' in p.stdout and 'WARN:db_wait' not in log, p.stdout + log)

    p, log, ran = run('late', up_after=3)          # пробы 1–3 — «не принимает», четвёртая отвечает
    check('база поднялась через несколько проб: шаг идёт, 4 пробы, итог warn',
          'rc=0 pings=4' in p.stdout and ran['ran3'] and 'RES=warn' in p.stdout, p.stdout + log)
    check('WARN:db_wait в статусе и в журнале, вывод шага сохранён',
          'WARN:db_wait: база не отвечала' in log and 'перед шагом s_late' in log and 'привет' in log and 'db_wait' in p.stdout, p.stdout + log)

    p, log, ran = run('never', up_after=999)
    check('не дождались: шаг НЕ запущен, rc=75, итог FAIL',
          'rc=75' in p.stdout and not ran['ran4'] and 'RES=FAIL' in p.stdout, p.stdout + p.stderr)
    check('причина понятная и без FATAL: «не приняла запрос за 3 с … шаг не запускался»',
          'база remlab-devdb не приняла запрос за 3 с' in log and 'шаг не запускался' in log and 'FATAL' not in log
          and 's_never FAIL (rc=75)' in log, log)
    check('строка STEPTIME у несостоявшегося шага: rc=75 res=FAIL', 'STEPTIME name=s_never ' in log and 'rc=75 res=FAIL' in log, log)

    p, log, ran = run('noleak', up_after=0)
    check('STEP_DB_WAIT не прилипает к следующему шагу (пробы только у первого)', 'pings=1' in p.stdout, p.stdout + p.stderr)

    src = open(SRC, encoding='utf-8').read().splitlines()
    wait_on = {ln.split(' step ', 1)[1].split()[0] for ln in src if ln.startswith('STEP_DB_WAIT=') and ' step ' in ln}
    check('ожидание стоит у price_truth и pool_photos (шаги сразу за stock_check)', wait_on == {'price_truth', 'pool_photos'}, str(wait_on))
    check('у stock_check ожидания нет (он сам пишет в базу и сам её убивал)',
          any(ln.startswith('step stock_check ') for ln in src))
    print('итого:', 'OK' if not fails else f'FAIL {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

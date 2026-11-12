"""Время шагов дневной сборки и метка «спрос мешей готов» (T-20261112-56, план refresh-split-01).
- настоящий step() из refresh_daily.sh на заглушках, как в кроне (env без LANG, C-локаль): после вывода шага — строка STEPTIME
  с началом, концом, секундами, кодом, итогом и процессором детей; код возврата step() прежний (цепочки `&&`), WARN/FAIL прежние;
- mesh_demand_ready(): одна строка «дата время шаг=итог…», запись через .tmp; пустой DEMAND_READY в ночи — метка не пишется;
- refresh_step_times.py разбирает этот же журнал: минуты, процессор, утро/вечер;
- `bash -n refresh_daily.sh`.
Ничего настоящего не запускает: шаги — true/false/sleep/счётный цикл.
    ~/venvs/scout/bin/python tools/scout/tests/test_refresh_steptime.py"""
import os
import subprocess
import sys
import time
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_refresh_steptime')  # временное теста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
import tempfile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.join(HERE, '..')
SRC = os.path.join(SCOUT, 'refresh_daily.sh')
sys.path.insert(0, SCOUT)
import refresh_step_times as RST  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if not cond and extra else ''))
    fails += 0 if cond else 1


SH = r'''set -u
LOG="$TD/log"; STEP_TMP="$TD/step"; REMLAB_TMP="$TD"; DEMAND_READY="$TD/sc/mesh-demand-ready"
remlab_tmp_free() { echo 1; }
declare -A RES; declare -A WARNS; declare -A WARNN
eval "$(sed -n '/^step() {/,/^}/p; /^mesh_demand_ready() {/,/^}/p' "$SRC")"
echo "=== 2026-11-12 10:40:01 старт ===" >> "$LOG"
step s_ok true; echo "rc s_ok=$?"
step s_warn bash -c 'echo "WARN:k: предупреждение"'; echo "rc s_warn=$?"
step s_fail bash -c 'echo упал; exit 3'; echo "rc s_fail=$?"
step s_sleep sleep 1.2; echo "rc s_sleep=$?"
step s_cpu bash -c 'i=0; while [ $i -lt 400000 ]; do i=$((i+1)); done'
step s_ok true && step s_chain true; echo "chain=$?"
step s_fail2 false && step s_never true; echo "chain2=$?"
mesh_demand_ready s_ok s_fail s_absent
echo "=== 2026-11-12 10:41:01 готово (фиды ok=1) ===" >> "$LOG"
'''


def main() -> int:
    r = subprocess.run(['bash', '-n', SRC], capture_output=True, text=True)
    check('bash -n refresh_daily.sh', r.returncode == 0, r.stderr[-300:])
    with tempfile.TemporaryDirectory(prefix='steptime-') as td:
        sh = os.path.join(td, 'run.sh')
        open(sh, 'w', encoding='utf-8').write(SH)
        env = {'HOME': td, 'PATH': '/usr/bin:/bin', 'SHELL': '/bin/bash', 'TD': td, 'SRC': SRC}   # как крон: без LANG
        t0 = time.time()
        p = subprocess.run(['bash', sh], env=env, capture_output=True, text=True, timeout=120)
        check('заглушки отработали без ошибок bash', p.returncode == 0 and not p.stderr.strip(), p.stderr[-400:])
        out = p.stdout
        check('step() возвращает код команды', 'rc s_ok=0' in out and 'rc s_warn=0' in out and 'rc s_fail=3' in out)
        check('цепочки && как прежде', 'chain=0' in out and 'chain2=1' in out)
        log = open(os.path.join(td, 'log'), encoding='utf-8').read()
        lines = log.splitlines()
        st = [RST.parse_line(x) for x in lines if x.startswith('STEPTIME ')]
        names = [s['name'] for s in st if s]
        check('строка на каждый шаг, по порядку, s_never не шёл',
              names == ['s_ok', 's_warn', 's_fail', 's_sleep', 's_cpu', 's_ok', 's_chain', 's_fail2'], str(names))
        by = {s['name']: s for s in st if s}
        check('итог и код в строке', by['s_warn']['res'] == 'warn' and by['s_fail']['res'] == 'FAIL' and by['s_fail']['rc'] == 3
              and by['s_ok']['res'] == 'ok')
        check('вывод шага — до его строки STEPTIME', lines.index('упал') < next(i for i, x in enumerate(lines)
                                                                             if x.startswith('STEPTIME name=s_fail ')))
        check('FAIL-строка шага на месте', 's_fail FAIL (rc=3)' in log)
        check('секунды: sleep 1.2 → 1–2 с', 1 <= by['s_sleep']['sec'] <= 2, str(by['s_sleep']))
        check('процессор: счётный цикл виден, true — около нуля',
              by['s_cpu']['cpu'] is not None and by['s_cpu']['cpu'] >= 0.1 and by['s_ok']['cpu'] is not None
              and by['s_ok']['cpu'] < 0.1, f"{by['s_cpu']} / {by['s_ok']}")
        day = time.strftime('%Y-%m-%d', time.localtime(t0))
        check('начало/конец — дата сегодня и порядок', by['s_sleep']['start'].startswith(day)
              and by['s_sleep']['start'] < by['s_sleep']['end'])
        ready = open(os.path.join(td, 'sc', 'mesh-demand-ready'), encoding='utf-8').read()
        check('метка спроса: дата первой и итоги шагов', ready.startswith(day + ' ')
              and ready.rstrip('\n').endswith(' s_ok=ok s_fail=FAIL s_absent=нет'), ready)
        check('метка через .tmp — хвоста нет', not os.path.exists(os.path.join(td, 'sc', 'mesh-demand-ready.tmp')))
        rs = RST.runs(open(os.path.join(td, 'log'), encoding='utf-8'))
        t = RST.table(rs, split='s_sleep')
        check('разбор журнала: один прогон, 8 строк шагов (s_ok дважды → одна строка таблицы)',
              len(rs) == 1 and len(rs[0]['steps']) == 8 and len(t['rows']) == 7)
        check('утро/вечер считаются', t['split']['утро'][0] is not None and t['split']['вечер'][0] is not None)
        check('прогон целиком — 1 мин по меткам старт/готово', t['whole'] == [1.0])
    # ночь без метки: хвост ночи в tests_refresh_order идёт без DEMAND_READY — строка вызова обязана молчать
    src = open(SRC, encoding='utf-8').read()
    check('вызов метки — под [ -n "${DEMAND_READY:-}" ] сразу за demo_band',
          'step demo_band "$PY" demo_band.py --report\n[ -n "${DEMAND_READY:-}" ] && mesh_demand_ready ' in src)
    r = subprocess.run([sys.executable, os.path.join(SCOUT, 'refresh_step_times.py'), '--selftest'], capture_output=True, text=True)
    check('refresh_step_times --selftest', r.returncode == 0, r.stdout[-400:])
    print('итого:', 'OK' if not fails else f'FAIL {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

"""Прод-сторож каталога различает «прогон идёт» и «не состоялся» (T-20261112-56/2, план refresh-split-01).
- `refresh_daily.sh:status_running` публикует `overall: running` с сегодняшней датой, локальный refresh-status.json не трогает;
- `infra/server/scripts/catalog-watchdog.sh` на заглушке (CW_DIR/CW_STATUS/CW_POLL/CW_MAX_SEC, CW_DRY — без logger):
  нет статуса / вчерашний / FAIL — тревога как раньше; сегодняшний ok — тихо; running → ждёт: кончился ok — тихо, FAIL — тревога,
  не кончился к сроку — «идёт дольше»; DISABLED — молчит.
Ничего настоящего не запускает и в сеть не ходит (TG — только при `.env` в CW_DIR, в тесте его нет).
    ~/venvs/scout/bin/python tools/scout/tests/test_catalog_watchdog.py"""
import datetime
import json
import os
import subprocess
import sys
import threading
import time
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_catalog_watchdog')
import tempfile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '..', 'refresh_daily.sh')
WD = os.path.abspath(os.path.join(HERE, '..', '..', '..', 'infra', 'server', 'scripts', 'catalog-watchdog.sh'))
fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if not cond and extra else ''))
    fails += 0 if cond else 1


def utc(dt: datetime.datetime) -> str:
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


NOW = datetime.datetime.now(datetime.timezone.utc)
TODAY = NOW.strftime('%Y-%m-%d')
YDAY = (NOW - datetime.timedelta(days=1)).strftime('%Y-%m-%d')
DRV = r'''set -u
STATUS="$TD/refresh-status.json"; today="$TODAY"; STARTED="$STARTED"
eval "$(sed -n '/^publish_status() {/,/^}/p; /^status_running() {/,/^}/p' "$SRC")"
mkdir -p "$HOME/.cache/remlab-refresh"
status_running; echo "rc=$?"
'''


def write(path, obj):
    tmp = path + '.tmp'
    json.dump(obj, open(tmp, 'w', encoding='utf-8'))
    os.replace(tmp, path)


def watchdog(td, status_obj, later=None, after=1.5, **env):
    """Запуск сторожа; later — статус, которым «прогон» перезапишет файл через after с. → (rc, новые строки watchdog.log, сек)."""
    d = os.path.join(td, 'w')
    os.makedirs(d, exist_ok=True)
    st = os.path.join(td, 'prod-status.json')
    if os.path.exists(st):
        os.replace(st, st + '.old')
    if status_obj is not None:
        write(st, status_obj)
    log = os.path.join(d, 'watchdog.log')
    before = open(log, encoding='utf-8').read() if os.path.exists(log) else ''
    t = None
    if later is not None:
        t = threading.Timer(after, write, args=(st, later))
        t.start()
    e = {'PATH': '/usr/bin:/bin', 'HOME': td, 'CW_DIR': d, 'CW_STATUS': st, 'CW_POLL': '1', 'CW_DRY': '1'}
    e.update({k: str(v) for k, v in env.items()})
    t0 = time.time()
    p = subprocess.run(['bash', WD], env=e, capture_output=True, text=True, timeout=60)
    if t:
        t.join()
    after_txt = open(log, encoding='utf-8').read() if os.path.exists(log) else ''
    return p.returncode, after_txt[len(before):].strip(), time.time() - t0, p.stderr.strip()


def main() -> int:
    for f in (SRC, WD):
        r = subprocess.run(['bash', '-n', f], capture_output=True, text=True)
        check(f'bash -n {os.path.basename(f)}', r.returncode == 0, r.stderr[-300:])
    src = open(SRC, encoding='utf-8').read()
    check('status_running — сразу за строкой «старт» (после trap finish)',
          'старт ===" >> "$LOG"\nstatus_running >> "$LOG" 2>&1 || echo "WARN:status_running:' in src
          and src.index('trap finish EXIT') < src.index('status_running >> "$LOG"'))
    with tempfile.TemporaryDirectory(prefix='cwatch-') as td:
        # 1. refresh_daily публикует «идёт»
        prod = os.path.join(td, 'prod-status.json')
        started = utc(NOW.replace(microsecond=0))
        env = {'PATH': '/usr/bin:/bin', 'HOME': td, 'TD': td, 'SRC': SRC, 'TODAY': TODAY, 'STARTED': started,
               'STATUS_PUBLISH': prod}
        p = subprocess.run(['bash', '-c', DRV], env=env, capture_output=True, text=True, timeout=30)
        check('status_running отработал', 'rc=0' in p.stdout and not p.stderr.strip(), p.stdout + p.stderr)
        s = json.load(open(prod, encoding='utf-8')) if os.path.exists(prod) else {}
        check('на «прод» — running, сегодня, started_at, без finished_at',
              s.get('overall') == 'running' and s.get('date') == TODAY and s.get('started_at') == started
              and 'finished_at' not in s, str(s))
        check('локальный refresh-status.json не тронут', not os.path.exists(os.path.join(td, 'refresh-status.json')))
        check('хвоста .tmp на «проде» нет', not os.path.exists(prod + '.tmp'))
        # 2. сторож
        ok_today = {'date': TODAY, 'started_at': started, 'finished_at': utc(NOW), 'overall': 'ok', 'fails': []}
        fail_today = dict(ok_today, overall='FAIL', fails=['stock_check'])
        rc, msg, _, err = watchdog(td, None)
        check('нет статуса — тревога «НЕТ вовсе»', rc == 0 and 'НЕТ вовсе' in msg, msg + err)
        rc, msg, _, err = watchdog(td, dict(ok_today, date=YDAY))
        check('вчерашний статус — «НЕ СОСТОЯЛСЯ»', rc == 0 and 'НЕ СОСТОЯЛСЯ' in msg, msg + err)
        rc, msg, _, err = watchdog(td, ok_today)
        check('сегодня ok — тихо', rc == 0 and msg == '', msg + err)
        rc, msg, _, err = watchdog(td, fail_today)
        check('сегодня FAIL — «С ОШИБКАМИ: stock_check»', rc == 0 and 'С ОШИБКАМИ' in msg and 'stock_check' in msg, msg + err)
        rc, msg, sec, err = watchdog(td, s, later=ok_today)
        check('идёт → кончился ok — тихо, сторож дождался', rc == 0 and msg == '' and sec >= 1, f'{msg} {sec:.1f} {err}')
        rc, msg, sec, err = watchdog(td, s, later=fail_today)
        check('идёт → кончился FAIL — тревога «С ОШИБКАМИ»', rc == 0 and 'С ОШИБКАМИ' in msg and sec >= 1, msg + err)
        fresh = dict(s, started_at=utc(datetime.datetime.now(datetime.timezone.utc)))   # срок 3 с — от «сейчас»
        rc, msg, sec, err = watchdog(td, fresh, CW_MAX_SEC=3)
        check('идёт и не кончился к сроку — «идёт дольше … завис»', rc == 0 and 'идёт дольше' in msg and 2 <= sec < 15,
              f'{msg} {sec:.1f} {err}')
        old = dict(s, started_at=utc(NOW - datetime.timedelta(hours=11)))
        rc, msg, sec, err = watchdog(td, old)
        check('«идёт» 11 ч (срок 10 ч прошёл) — тревога сразу', rc == 0 and 'идёт дольше 10 ч' in msg and sec < 5, msg + err)
        rc, msg, _, err = watchdog(td, dict(s, date=YDAY))
        check('вчерашний «идёт» (DEV умерла вчера, сегодня не стартовала) — «НЕ СОСТОЯЛСЯ»', 'НЕ СОСТОЯЛСЯ' in msg, msg + err)
        open(os.path.join(td, 'w', 'DISABLED'), 'w').close()
        rc, msg, _, err = watchdog(td, None)
        check('DISABLED — молчит', rc == 0 and msg == '', msg + err)
    print('итого:', 'OK' if not fails else f'FAIL {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

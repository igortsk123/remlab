"""Недельная проверка расстановки `solver_full` — отдельный крон (T-20261112-56/3, план refresh-split-01, вариант А).
Настоящий `solver_weekly.sh` на заглушках (solver_check и heavy-slot подменены; `--dry` — без них вовсе), своя временная папка, живые файлы не трогает:
- замки: недельная проверка и дневная сборка (`~/.remlab-refresh.lock`), недельная и экзамен (`exam.flock`) не идут одновременно В ОБЕ СТОРОНЫ;
  занято дольше SW_LOCK_WAIT — пропуск со статусом skipped, строкой в журнал и тревогой; освободилось вовремя — ждёт и идёт;
- срок: solver под `timeout` до SW_DEADLINE/SW_MAX_SEC (не успел — FAIL «не уложился в срок», сутки не ломает); осталось меньше SW_MIN_SEC — пропуск;
- журнал: старт/готово и строка `STEPTIME name=solver_full …` того же вида, что у шагов сборки (её читает `refresh_step_times.py`);
- статус `solver-weekly-status.json` (ok/FAIL/skipped, числа «влезают N/M») и строка сводки `solver_weekly_status.py --digest`;
- заявка в heavy-slot честная (1 ядро, 2 ГБ, долгая); `CHECK_TAG=weekly` доходит до solver_check;
- статические связи: тот же файл замка у `refresh_daily.sh` и тот же `exam.flock` у `run.sh`; крон в `infra/dev/crontab`; `solver_check.py` из дневной
  сборки ушёл; скрипт слушает паузу обслуживания (`cron-pause.sh` GATED);
- `bash -n`.
    ~/venvs/scout/bin/python tools/scout/tests/test_solver_weekly.py"""
import json
import os
import re
import subprocess
import sys
import time
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
import remlab_tmp  # noqa: E402
remlab_tmp.use('test_solver_weekly')  # временное теста — на диске, не в /tmp; папка убирается при выходе
import tempfile  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SCOUT = os.path.abspath(os.path.join(HERE, '..'))
ROOT = os.path.abspath(os.path.join(SCOUT, '..', '..'))
SW = os.path.join(SCOUT, 'solver_weekly.sh')
sys.path.insert(0, SCOUT)
import refresh_step_times as RST  # noqa: E402
import solver_weekly_status as SWS  # noqa: E402

fails = 0


def check(name, cond, extra=''):
    global fails
    print(('OK   ' if cond else 'FAIL ') + name + (f' — {extra}' if not cond and extra else ''))
    fails += 0 if cond else 1


def read(p):
    try:
        return open(p, encoding='utf-8').read()
    except OSError:
        return ''


class Env:
    """Временная папка с замками, журналом, статусом и заглушками; `run()` — настоящий solver_weekly.sh."""

    def __init__(self, td):
        self.td = td
        self.log, self.status = os.path.join(td, 'sw.log'), os.path.join(td, 'status.json')
        self.rlock, self.elock = os.path.join(td, 'refresh.lock'), os.path.join(td, 'exam.flock')
        self.heavy_args = os.path.join(td, 'heavy-args')
        self.fakepy = os.path.join(td, 'fakepy.sh')
        self.fakeheavy = os.path.join(td, 'fakeheavy.sh')
        self.set_py('echo "сет 1: OK"; echo "CHECK_TAG=${CHECK_TAG:-}"; echo "Итого: 3/4 влезают; проблемных 1"; exit 0')
        open(self.fakeheavy, 'w').write('#!/bin/bash\necho "$*" > "$HEAVY_ARGS"\nwhile [ "$1" != -- ]; do shift; done; shift\nexec "$@"\n')
        os.chmod(self.fakeheavy, 0o755)
        self.env = {**os.environ, 'SW_LOG': self.log, 'SW_STATUS': self.status, 'SW_REFRESH_LOCK': self.rlock, 'SW_EXAM_LOCK': self.elock,
                    'REMLAB_MAINT_DIR': os.path.join(td, 'maint'), 'REMLAB_TMP': os.path.join(td, 'tmp'), 'ALERT_DRY': '1',
                    'SW_PY': self.fakepy, 'SW_HEAVY': self.fakeheavy, 'HEAVY_ARGS': self.heavy_args, 'SW_LOCK_WAIT': '2', 'SW_MIN_SEC': '1',
                    # срок — через 3 ч от сейчас (не зависит от часа запуска теста), потолок часа
                    'SW_DEADLINE_HHMM': time.strftime('%H:%M', time.localtime(time.time() + 3 * 3600)), 'SW_MAX_SEC': '3600'}
        self.env.pop('REFRESH_DAILY_RUN', None)

    def set_py(self, body):
        open(self.fakepy, 'w').write('#!/bin/bash\n' + body + '\n')
        os.chmod(self.fakepy, 0o755)

    def run(self, *args, **extra):
        env = {**self.env, **{k: str(v) for k, v in extra.items()}}
        return subprocess.run(['bash', SW, *args], env=env, capture_output=True, text=True, timeout=120)

    def popen(self, *args, **extra):
        env = {**self.env, **{k: str(v) for k, v in extra.items()}}
        return subprocess.Popen(['bash', SW, *args], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def st(self):
        try:
            return json.load(open(self.status, encoding='utf-8'))
        except (OSError, ValueError):
            return {}

    def reset(self):
        for p in (self.log, self.status, self.heavy_args):
            if os.path.exists(p):
                os.remove(p)


def holder(path, sec):
    """Другой процесс держит flock на файле sec секунд (как дневная сборка или экзамен); возвращает Popen после захвата."""
    p = subprocess.Popen(['flock', path, 'sleep', str(sec)])
    for _ in range(100):
        if subprocess.run(['flock', '-n', path, 'true']).returncode == 1:
            return p
        time.sleep(0.05)
    raise RuntimeError('замок не взят держателем')


def free(path):
    return subprocess.run(['flock', '-n', path, 'true']).returncode == 0


def main() -> int:
    for f in (SW, os.path.join(SCOUT, 'refresh_daily.sh'), os.path.join(ROOT, 'tools', 'ops', 'cron-pause.sh')):
        r = subprocess.run(['bash', '-n', f], capture_output=True, text=True)
        check(f'bash -n {os.path.basename(f)}', r.returncode == 0, r.stderr[-300:])
    check('solver_weekly_status.py --selftest', subprocess.run([sys.executable, os.path.join(SCOUT, 'solver_weekly_status.py'), '--selftest'],
                                                                capture_output=True).returncode == 0)
    # ---- статические связи
    rd, rs = read(os.path.join(SCOUT, 'refresh_daily.sh')), read(os.path.join(SCOUT, 'run.sh'))
    sw = read(SW)
    check('дневная сборка: solver_check.py не зовётся, solver_full не шаг', 'solver_check.py' not in re.sub(r'(?m)^\s*#.*$', '', rd)
          and not re.search(r'(?m)^\s*step solver_full\b', rd))
    check('дневная сборка: в понедельник шаг solver_weekly_last (итог в сводку)', re.search(r'(?m)^  step solver_weekly_last "\$PY" solver_weekly_status\.py --digest$', rd) is not None)
    m = re.search(r'exec 9>"\$HOME/(\.remlab-refresh\.lock)"', rd)
    check('замок один: файл дневной сборки = файл недельной проверки', m is not None and f'$HOME/{m.group(1)}' in sw)
    check('замок один: exam.flock у run.sh = у недельной проверки', 'exam.flock' in rs and '$HERE/exam.flock' in sw)
    check('слушает паузу обслуживания (GATED, maint_gate раньше замков)', 'tools/scout/solver_weekly.sh' in read(os.path.join(ROOT, 'tools/ops/cron-pause.sh'))
          and sw.index('maint_gate solver_weekly') < sw.index('exec 9>"$REFRESH_LOCK"'))
    cron = [ln for ln in read(os.path.join(ROOT, 'infra/dev/crontab')).splitlines() if not ln.lstrip().startswith('#') and 'solver_weekly.sh' in ln]
    check('infra/dev/crontab: одна строка, понедельник 05:30, ключа нет', len(cron) == 1 and cron[0].startswith('30 5 * * 1 ') and cron[0].endswith('/tools/scout/solver_weekly.sh'), cron)
    with tempfile.TemporaryDirectory(prefix='solver-weekly-') as td:
        e = Env(td)
        # ---- неизвестный ключ
        r = e.run('--bogus')
        check('неизвестный ключ — код 2, файлов не создаёт', r.returncode == 2 and not os.path.exists(e.log))
        # ---- 1. сухой прогон: замки свободны
        r = e.run('--dry')
        s, lg = e.st(), read(e.log)
        check('сухо: код 0, статус ok, dry=true, solver_check не запускался', r.returncode == 0 and s.get('state') == 'ok' and s.get('dry') is True
              and 'solver_check не запускался' in lg, (r.stdout + r.stderr)[-300:] + lg[-300:])
        check('сухо: журнал — старт, замки, STEPTIME solver_full ok, готово',
              '=== ' in lg and ' старт ===' in lg and 'замки взяты' in lg and re.search(r'^STEPTIME name=solver_full .* rc=0 res=ok cpu=', lg, re.M) is not None
              and re.search(r'^=== .* готово ===$', lg, re.M) is not None, lg[-400:])
        rs_ = [x for x in RST.runs(lg.splitlines(True)) if x['steps']]
        check('STEPTIME читает refresh_step_times.py (шаг solver_full, ок)', len(rs_) == 1 and rs_[0]['steps'][0]['name'] == 'solver_full'
              and rs_[0]['steps'][0]['res'] == 'ok' and rs_[0]['end'] is not None, rs_)
        check('сухо: heavy-slot не занимался', not os.path.exists(e.heavy_args))
        check('сухо: замки после выхода свободны', free(e.rlock) and free(e.elock))
        # ---- 2. настоящий путь на заглушках: ok, числа, заявка heavy-slot, CHECK_TAG
        e.reset()
        r = e.run()
        s, lg, ha = e.st(), read(e.log), read(e.heavy_args)
        check('ok: статус, числа «влезают 3/4, проблемных 1», dry=false', r.returncode == 0 and s.get('state') == 'ok' and (s.get('fit'), s.get('total'), s.get('bad')) == (3, 4, 1)
              and s.get('dry') is False, (r.stdout + r.stderr)[-300:] + str(s))
        check('ok: вывод solver_check — в журнале, CHECK_TAG=weekly дошёл', 'сет 1: OK' in lg and 'CHECK_TAG=weekly' in lg and 'solver_weekly: ok' in lg, lg[-300:])
        check('заявка heavy-slot честная: 1 ядро, 2 ГБ, долгая, метка solver-weekly',
              'solver-weekly' in ha and '--cores 1' in ha and '--min-gb 2' in ha and '--long' in ha and '--timeout 1800' in ha, ha)
        check('сводка: --digest показывает итог без предупреждения',
              SWS.digest(e.status)[0].startswith('DIGEST:недельная проверка расстановки') and len(SWS.digest(e.status)) == 1 and 'влезают 3/4' in SWS.digest(e.status)[0], SWS.digest(e.status))
        # ---- 3. solver упал → FAIL, тревога, код 1
        e.reset()
        e.set_py('echo "Traceback: boom"; exit 1')
        r = e.run()
        s, lg = e.st(), read(e.log)
        check('FAIL: код 1, статус FAIL, STEPTIME res=FAIL, тревога владельцу в журнале', r.returncode == 1 and s.get('state') == 'FAIL' and 'УПАЛА' in lg
              and re.search(r'^STEPTIME name=solver_full .* rc=1 res=FAIL', lg, re.M) is not None, lg[-400:])
        check('FAIL: сводка — WARN solver_weekly (не FAIL всей сборки)', SWS.digest(e.status)[0].startswith('WARN:solver_weekly:') and 'упала' in SWS.digest(e.status)[0])
        # ---- 4. нет итоговой строки при коде 0 — тоже FAIL
        e.reset()
        e.set_py('echo "сет 1: OK"; exit 0')
        r = e.run()
        check('код 0 без «Итого:» — FAIL (не молчаливый успех)', e.st().get('state') == 'FAIL' and 'Итого' in e.st().get('reason', ''), e.st())
        # ---- 5. срок: solver дольше срока → timeout, FAIL «не уложился»
        e.reset()
        e.set_py('sleep 30; echo "Итого: 1/1 влезают; проблемных 0"')
        t0 = time.time()
        r = e.run(SW_MAX_SEC=4, SW_MIN_SEC=1)
        s = e.st()
        check('срок: solver убит по сроку (за ~4 с, не 30), FAIL «не уложился в срок»', time.time() - t0 < 20 and s.get('state') == 'FAIL' and s.get('rc') == 124
              and 'не уложился в срок' in s.get('reason', ''), (time.time() - t0, s))
        # ---- 6. срок: осталось мало → пропуск
        e.reset()
        r = e.run(SW_MAX_SEC=5, SW_MIN_SEC=600)
        s = e.st()
        check('осталось меньше SW_MIN_SEC — пропуск (skipped), solver не запускался', r.returncode == 0 and s.get('state') == 'skipped' and 'до срока' in s.get('reason', '')
              and 'сет 1: OK' not in read(e.log), s)
        # ---- 7. heavy-slot не дал очередь → пропуск
        e.reset()
        e.set_py('echo "heavy-slot: solver-weekly не дождался очереди/памяти (--timeout) — команда не запущена" >&2; exit 124')
        r = e.run()
        s = e.st()
        check('очередь тяжёлых не дождалась — skipped с причиной, тревога', r.returncode == 0 and s.get('state') == 'skipped' and 'очереди' in s.get('reason', '') and 'ПРОПУЩЕНА' in read(e.log), s)
        e.set_py('echo "Итого: 3/4 влезают; проблемных 1"')
        # ---- 8. замки: дневная сборка держит файл — пропуск; освободилась вовремя — ждём и идём
        e.reset()
        h = holder(e.rlock, 6)
        r = e.run('--dry', SW_LOCK_WAIT=1)
        s, lg = e.st(), read(e.log)
        check('дневная сборка держит замок дольше ожидания — skipped, «~/.remlab-refresh.lock», тревога, solver не запускался',
              r.returncode == 0 and s.get('state') == 'skipped' and 'remlab-refresh.lock' in s.get('reason', '') and 'ПРОПУЩЕНА' in lg and 'замки взяты' not in lg, s)
        check('пропуск записан STEPTIME res=skipped', re.search(r'^STEPTIME name=solver_full .* res=skipped', lg, re.M) is not None, lg[-300:])
        h.wait()
        e.reset()
        h = holder(e.rlock, 2)
        t0 = time.time()
        r = e.run('--dry', SW_LOCK_WAIT=10)
        check('дневная сборка освободила замок за 2 с — недельная подождала и прошла', e.st().get('state') == 'ok' and time.time() - t0 >= 1.5, (e.st(), time.time() - t0))
        h.wait()
        e.reset()
        h = holder(e.elock, 6)
        r = e.run('--dry', SW_LOCK_WAIT=1)
        s = e.st()
        check('экзамен держит exam.flock — skipped с причиной «exam.flock»', s.get('state') == 'skipped' and 'exam.flock' in s.get('reason', ''), s)
        check('…а замок дневной сборки при этом уже отпущен (не держим чужое)', free(e.rlock))
        h.wait()
        # ---- 9. исключение в обе стороны: пока недельная идёт, ни сборка, ни экзамен замков не берут; после — берут
        e.reset()
        p = e.popen('--dry', SW_DRY_SLEEP=4)
        for _ in range(200):
            if 'замки взяты' in read(e.log):
                break
            time.sleep(0.1)
        check('недельная держит замок сборки и exam.flock (flock -n других — отказ)', 'замки взяты' in read(e.log) and not free(e.rlock) and not free(e.elock))
        out = p.communicate(timeout=60)[0]
        check('после конца оба замка свободны, статус ok', p.returncode == 0 and free(e.rlock) and free(e.elock) and e.st().get('state') == 'ok', out[-300:])
        # ---- 10. пауза обслуживания: на паузе — выход без замков, строка в журнал и тревога
        e.reset()
        os.makedirs(e.env['REMLAB_MAINT_DIR'], exist_ok=True)
        open(os.path.join(e.env['REMLAB_MAINT_DIR'], 'maintenance.pause'), 'w').write(f'until={int(time.time()) + 600}\nreason=проверка\n')
        r = e.run('--dry')
        lg = read(e.log)
        check('на паузе обслуживания: ничего не делали, строка в журнале и тревога', r.returncode == 0 and 'solver_weekly: пауза обслуживания' in lg and 'пропущен' in lg
              and not e.st() and not os.path.exists(e.heavy_args), lg[-300:])
        os.remove(os.path.join(e.env['REMLAB_MAINT_DIR'], 'maintenance.pause'))
    print(f'test_solver_weekly: ошибок {fails}')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""Автозапуск волны мешей по разрешению владельца (план conv-11, ADR-0274).

ЗАЧЕМ. Владелец 13.10: «закинул деньги на Salad — всё сделалось само, виртуалки погасились». Баланс Salad программно
не узнать (в API нет — только попыткой старта), поэтому старт идёт только по РАЗРЕШЕНИЮ владельца с потолком
(`~/scout-scenes/wave-lease.json`: срок и сумма $), а без него сторож только наблюдает и пишет причину.

РАЗРЕШЕНИЕ: {"expires": "2026-10-31", "max_usd": 30, "min_jobs": 200}. Остаток денег переводится в число моделей по
оценке цены модели (`rules/salad-groups.json → wave.usd_per_mesh`). На старте в разрешение пишется волна с потолком
`usd_cap` и отметкой книги расходов сторожа денег `usd_mark`; сторож денег гасит пул, когда потолок выбран
(`money_guard.budget_breach`). Конвейер вышел → волна закрывается: факт денег и моделей, итог владельцу в Telegram,
потраченное копится в `spent_usd`.
Волна запускается ТЕМ ЖЕ законным путём (`mesh_wave_start.sh --launch`) с `MESH_TAKE_JOBS` = остаток (верх очереди по приоритету; `MESH_MAX_JOBS` — отдельный предохранитель снимка) и
`MESH_MIN_JOBS`. Конец очереди, нет денег, предел — гасит сам конвейер (`finale()` с проверкой `stopped`), DEV пропал —
мёртвая рука на сервере.

НЕ СТАРТУЕМ, если: нет разрешения/истекло/потолок выбран; конвейер или другой старт идёт; стоп-файлы владельца
(`mesh-group-halt.json`, `mesh-batch.PAUSE`); «нет денег» было меньше 2 ч назад; диск DEV ≥ 85 % или < 20 ГБ.
«Жду денег» — одно сообщение в сутки. Крон DEV: */15.

ПРОФИЛЬ ОЧЕРЕДИ — ИЗ РАЗРЕШЕНИЯ (владелец 21.10: «меши не на весь каталог, а сколько нужно для демо»; T-20261021-10/2).
`"profile": "demo"` в lease → старт с `MESH_QUEUE_PROFILE=demo` (`mesh_wave_start.sh` собирает снимок по
`rules/mesh-queue-demo.json`), порог — `"profile_min_jobs"` (по умолчанию 1) вместо боевого `min_jobs`. Без поля — боевая
очередь, как раньше. Раньше профиль жил только в окружении ручного запуска: крон его не знал и через ≤15 мин после
demo-волны поднимал боевую на 5578 заданий. Заданий профиля меньше порога → «нечего делать»: шаги старта не проходим,
волну не открываем, в журнал — одна строка на смену состояния.

  ~/venvs/scout/bin/python salad/wave_guard.py           # решение (+ старт, если можно)
  ~/venvs/scout/bin/python salad/wave_guard.py --dry     # только решение
  python3 salad/wave_guard.py --selftest
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SC = os.path.expanduser('~/scout-scenes')
LEASE = os.path.join(SC, 'wave-lease.json')
JOURNAL = os.path.join(SC, 'wave-guard.jsonl')
NOTE = os.path.join(SC, 'wave-guard-note.json')
NO_CREDITS = os.path.join(SC, 'mesh-no-credits.json')
LOCKS = [os.path.join(SC, '.batch_show.lock'), os.path.join(SC, '.mesh-wave-start.lock')]
STOPS = [os.path.join(SC, 'mesh-group-halt.json'), os.path.join(SC, 'mesh-batch.PAUSE')]
RULES = os.path.join(HERE, '..', 'rules', 'salad-groups.json')
PROGRESS = os.path.join(HERE, '..', 'mesh-run-progress.jsonl')   # журнал заданий конвейера (тот же, что у сторожа денег)


def held(path: str) -> bool:
    if not os.path.exists(path):
        return False
    with open(path, 'a') as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
        except OSError:
            return True


def left_usd(lease: dict) -> float:
    return float(lease.get('max_usd', 0)) - float(lease.get('spent_usd', 0))


def profile_of(lease: dict | None) -> tuple[str, int]:
    """(профиль очереди, порог заданий): с профилем — свой `profile_min_jobs` (по умолчанию 1), без — боевой `min_jobs`."""
    p = str((lease or {}).get('profile') or '')
    return (p, int((lease or {}).get('profile_min_jobs', 1))) if p else ('', int((lease or {}).get('min_jobs', 100)))


def profile_jobs(profile: str) -> int | None:
    """Сколько заданий соберёт профиль — тот же отбор, что у снимка (`mesh_priority --profile … --export`), без шагов
    старта. None — посчитать не вышло (тогда не стартуем)."""
    import tempfile  # noqa: PLC0415
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, 'q.json')
        r = subprocess.run([sys.executable, os.path.join(HERE, '..', 'mesh_priority.py'), '--profile', profile, '--export', out],
                           capture_output=True, text=True, timeout=1800)
        try:
            return len(json.load(open(out, encoding='utf-8'))) if r.returncode == 0 else None
        except (OSError, ValueError):
            return None


def decide(lease: dict | None, today: str, busy: bool, stops: list, no_credit_age_h: float | None,
           disk_pct: float, free_gb: float, usd_per_mesh: float, jobs: int | None = None) -> tuple[str, dict]:
    """→ (решение, параметры старта). Чистая функция — проверяется селфтестом. `jobs` — сколько заданий у профиля
    (считает `main` только для профиля и только когда иначе был бы старт): меньше порога → 'nothing_to_do'."""
    if busy:
        return 'busy', {}
    if stops:
        return 'stopped_by_owner', {}
    if not lease:
        return 'no_lease', {}
    if str(lease.get('expires', '')) < today:
        return 'lease_expired', {}
    left = int(left_usd(lease) / usd_per_mesh)
    profile, min_jobs = profile_of(lease)
    if left < min_jobs:
        return 'budget_spent', {}
    if no_credit_age_h is not None and no_credit_age_h < 2:
        return 'waiting_money', {}
    if disk_pct >= 85 or free_gb < 20:
        return 'disk', {}
    if profile and jobs is None:
        return 'profile_unknown', {'MESH_QUEUE_PROFILE': profile}
    if profile and jobs < min_jobs:
        return 'nothing_to_do', {'MESH_QUEUE_PROFILE': profile, 'jobs': jobs}
    return 'start', {'MESH_TAKE_JOBS': str(left), 'MESH_MIN_JOBS': str(min_jobs),
                     **({'MESH_QUEUE_PROFILE': profile} if profile else {})}


def last_verdict() -> str:
    """Решение прошлого тика (последняя строка журнала) — чтобы «нечего делать» не писать каждые 15 минут."""
    try:
        with open(JOURNAL, 'rb') as f:
            f.seek(max(0, f.seek(0, 2) - 4096))
            tail = f.read().decode('utf-8', 'replace').strip().splitlines()
        return str(json.loads(tail[-1]).get('verdict') or '') if tail else ''
    except (OSError, ValueError, IndexError):
        return ''


def wave_summary(w: dict, spent: float, meshes: int, why: str, left: float) -> str:
    per = f' (≈ ${spent / meshes:.3f} за модель)' if meshes else ''
    return (f'Меши: волна закончилась — {why}. Готово моделей {meshes}, потрачено ≈ ${spent:.2f}{per} из потолка '
            f'${float(w["usd_cap"]):.2f}. Остаток разрешения ≈ ${max(left, 0):.2f}. Машины Salad погашены.')


def close_reason(halt: dict | None, no_credits_at: float | None, started: float) -> str:
    if halt and halt.get('kind') == 'budget':
        return 'выбран потолок денег'
    if no_credits_at and no_credits_at >= started:
        return 'на Salad кончились деньги'
    if halt:
        return 'сторож денег остановил пул (' + str(halt.get('kind') or '?') + ')'
    return 'очередь кончилась или конвейер остановлен'


def meshes_since(t: float) -> int:
    n = 0
    try:
        with open(PROGRESS, encoding='utf-8') as f:
            for ln in f:
                if '"ok"' in ln:
                    try:
                        r = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    n += r.get('status') == 'ok' and r.get('at', 0) >= t
    except FileNotFoundError:
        pass
    return n


def close_wave(lease: dict, dry: bool) -> None:
    """Конвейер вышел — закрыть волну: факт денег и моделей, итог владельцу, снять запрет «потолок» (он своё
    отработал; следующую волну ограничит остаток разрешения)."""
    import money_guard as MG  # noqa: PLC0415 — книга расходов сторожа денег (один источник)
    w = lease['waves'][-1]
    spent = max(MG.paid_usd(MG.load()) - float(w.get('usd_mark', 0)), 0.0)
    halt = json.load(open(STOPS[0], encoding='utf-8')) if os.path.exists(STOPS[0]) else None
    nc = json.load(open(NO_CREDITS)).get('at') if os.path.exists(NO_CREDITS) else None
    why = close_reason(halt, nc, float(w['started']))
    meshes = meshes_since(float(w['started']))
    w.update({'closed': time.time(), 'spent_usd': round(spent, 2), 'meshes': meshes, 'why': why})
    lease['spent_usd'] = round(float(lease.get('spent_usd', 0)) + spent, 2)
    print('волна закрыта:', json.dumps(w, ensure_ascii=False), flush=True)
    if dry:
        return
    json.dump(lease, open(LEASE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if halt and halt.get('kind') == 'budget' and halt.get('source', 'lease') == 'lease':   # потолок ручной волны снимает её finale
        os.remove(STOPS[0])
    subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'), wave_summary(w, spent, meshes, why, left_usd(lease))],
                   check=False, timeout=60)


def main() -> int:
    dry = '--dry' in sys.argv
    lease = json.load(open(LEASE, encoding='utf-8')) if os.path.exists(LEASE) else None
    busy = any(held(p) for p in LOCKS)
    open_wave = bool(lease and (lease.get('waves') or [{}])[-1].get('usd_cap') is not None
                     and not lease['waves'][-1].get('closed'))
    if open_wave and not busy and time.time() - float(lease['waves'][-1]['started']) > 20 * 60:
        close_wave(lease, dry)
    rules = json.load(open(RULES, encoding='utf-8'))
    usd_per_mesh = float((rules.get('wave') or {}).get('usd_per_mesh', 0.013))
    nc_age = (time.time() - json.load(open(NO_CREDITS)).get('at', 0)) / 3600 if os.path.exists(NO_CREDITS) else None
    du = shutil.disk_usage(os.path.expanduser('~'))
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    args = (lease, today, busy or open_wave and not lease['waves'][-1].get('closed'),
            [p for p in STOPS if os.path.exists(p)], nc_age, du.used / du.total * 100, du.free / 2**30, usd_per_mesh)
    verdict, env = decide(*args)
    if verdict == 'profile_unknown':                    # профиль: задания считаем, только когда иначе был бы старт
        verdict, env = decide(*args, jobs=profile_jobs(env['MESH_QUEUE_PROFILE']))
    rec = {'at': time.time(), 'verdict': verdict, **env}
    if verdict in ('nothing_to_do', 'profile_unknown') and last_verdict() == verdict:
        return 0                                        # то же «нечего делать» — молчим: одна строка на смену состояния
    with open(JOURNAL, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f'{today} автозапуск волны: {verdict} {env}', flush=True)
    if verdict == 'waiting_money':                      # одно сообщение в сутки
        note = json.load(open(NOTE)) if os.path.exists(NOTE) else {}
        if note.get('day') != today and not dry:
            subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'),
                            'Меши: на Salad нет денег — волна ждёт пополнения (разрешение действует до '
                            + str(lease.get('expires')) + '). Пополните баланс — старт сам в течение 2 ч.'], check=False, timeout=60)
            json.dump({'day': today}, open(NOTE, 'w'))
    if verdict != 'start' or dry:
        return 0
    import money_guard as MG  # noqa: PLC0415
    cap = round(min(left_usd(lease), int(env['MESH_TAKE_JOBS']) * usd_per_mesh * 1.5), 2)   # запас на прогрев/простой
    cap = min(cap, round(left_usd(lease), 2))
    lease.setdefault('waves', []).append({'at': today, 'started': time.time(), 'max_jobs': int(env['MESH_TAKE_JOBS']),
                                          'usd_cap': cap, 'usd_mark': round(MG.paid_usd(MG.load()), 2)})
    json.dump(lease, open(LEASE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)   # ДО старта: сторож видит потолок
    # MESH_WAVE_LEASE=1: потолок этой волны — запись выше в разрешении, ручной `--rub-cap` старту не нужен (T-20261027-02)
    r = subprocess.run(['bash', os.path.join(HERE, '..', 'mesh_wave_start.sh'), '--launch'],
                       env={**os.environ, **env, 'MESH_WAVE_LEASE': '1'},
                       capture_output=True, text=True, timeout=4 * 3600)
    print(r.stdout[-1500:], r.stderr[-500:], flush=True)
    if r.returncode != 0:                               # не стартовали — волну не открываем (денег не тратили)
        lease['waves'][-1].update({'closed': time.time(), 'spent_usd': 0, 'meshes': 0, 'why': f'старт не удался rc={r.returncode}'})
        json.dump(lease, open(LEASE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    else:
        subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'),
                        f"Меши: волна запущена по вашему разрешению — до {env['MESH_TAKE_JOBS']} моделей "
                        f"(потолок ${cap:.2f}). Конец очереди, денег или потолка — машины погаснут сами, итог пришлю."],
                       check=False, timeout=60)
    return r.returncode


def _one_lock_test() -> bool:
    import tempfile  # noqa: PLC0415
    import money_guard as MG  # noqa: PLC0415
    keep = MG.STATE
    MG.STATE = os.path.join(tempfile.mkdtemp(), 'st.json')
    try:
        a = MG.single_instance()
        b = MG.single_instance()
        return a is not None and b is None
    finally:
        MG.STATE = keep


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    L = {'expires': '2026-10-31', 'max_usd': 13, 'min_jobs': 200}
    d = lambda **k: decide(**{'lease': L, 'today': '2026-10-14', 'busy': False, 'stops': [], 'no_credit_age_h': None,
                             'disk_pct': 50, 'free_gb': 100, 'usd_per_mesh': 0.013, **k})
    ok('разрешение есть, всё чисто — старт на остаток 1000 моделей', d() == ('start', {'MESH_TAKE_JOBS': '1000', 'MESH_MIN_JOBS': '200'}))
    ok('без разрешения — только наблюдаем', d(lease=None)[0] == 'no_lease')
    ok('разрешение истекло', d(today='2026-11-01')[0] == 'lease_expired')
    ok('потолок выбран', d(lease={**L, 'spent_usd': 11.7})[0] == 'budget_spent')
    ok('остаток считается от потраченного', d(lease={**L, 'spent_usd': 6.5})[1].get('MESH_TAKE_JOBS') == '500')
    ok('итог: потолок', close_reason({'kind': 'budget'}, None, 0) == 'выбран потолок денег')
    ok('итог: старое «нет денег» не путает', close_reason(None, 5.0, 10.0).startswith('очередь'))
    ok('итог: свежее «нет денег»', close_reason(None, 15.0, 10.0) == 'на Salad кончились деньги')
    import money_guard as MG  # noqa: PLC0415
    st = {'paid_node_min': {'mesh-low-4': 600}}
    usd = MG.paid_usd(st)
    W = lambda **k: {'waves': [{'usd_cap': 1.0, 'usd_mark': 0, **k}]}
    ok('сторож денег: потолок не выбран — молчит', MG.budget_breach(st, W(usd_cap=usd + 1)) == '')
    ok('сторож денег: потолок выбран — гасит', MG.budget_breach(st, W(usd_cap=usd - 0.01)).startswith('ПОТОЛОК'))
    ok('сторож денег: закрытая волна не ограничивает', MG.budget_breach(st, W(usd_cap=0, closed=1)) == '')
    ok('сторож денег: без разрешения не ограничивает', MG.budget_breach(st, None) == '')
    ok('сторож денег: одна копия (замок)', _one_lock_test())
    ok('нет денег был час назад — ждём', d(no_credit_age_h=1.0)[0] == 'waiting_money')
    ok('нет денег был 3 ч назад — пробуем снова', d(no_credit_age_h=3.0)[0] == 'start')
    ok('конвейер идёт — не мешаем', d(busy=True)[0] == 'busy')
    ok('стоп-файл владельца сильнее разрешения', d(stops=['halt'])[0] == 'stopped_by_owner')
    ok('диск DEV почти полон — не стартуем', d(disk_pct=90)[0] == 'disk')
    # ПРОФИЛЬ ОЧЕРЕДИ (T-20261021-10/2)
    D = {**L, 'profile': 'demo', 'profile_min_jobs': 1}
    ok('lease без profile — боевой: в env старта профиля нет', 'MESH_QUEUE_PROFILE' not in d()[1])
    ok('profile=demo: без счёта заданий не стартуем', d(lease=D)[0] == 'profile_unknown')
    ok('profile=demo доходит до env старта, порог — свой (1), не боевой 200',
       d(lease=D, jobs=9) == ('start', {'MESH_TAKE_JOBS': '1000', 'MESH_MIN_JOBS': '1', 'MESH_QUEUE_PROFILE': 'demo'}))
    ok('пустая demo-очередь — «нечего делать», не старт', d(lease=D, jobs=0)[0] == 'nothing_to_do')
    ok('profile_min_jobs по умолчанию 1', profile_of({'profile': 'demo', 'min_jobs': 50}) == ('demo', 1))
    ok('пустая demo-очередь: mesh_wave_start не зовётся, в журнале одна строка за два тика', _quiet_test())
    ok('ручная волна с потолком не продлевает разрешение: истёкший lease — по-прежнему lease_expired', _manual_cap_test())
    return 1 if bad else 0


def _manual_cap_test() -> bool:
    """T-20261027-02: ручной старт пишет потолок в СВОЙ файл (`wave_cap.py`), разрешение владельца не тронуто."""
    import tempfile  # noqa: PLC0415
    import wave_cap as WC  # noqa: PLC0415
    keep = WC.PATH
    tmp = tempfile.mkdtemp()
    try:
        WC.PATH = os.path.join(tmp, 'manual.json')
        lease = {'expires': '2026-10-25', 'max_usd': 37, 'min_jobs': 50}
        before = json.dumps(lease, sort_keys=True)
        WC.open_wave(174, 86.89, 1.0, 'snap.json')
        v = decide(lease, '2026-10-27', False, [], None, 50, 100, 0.013)[0]
        return v == 'lease_expired' and json.dumps(lease, sort_keys=True) == before and WC.read()['waves'][-1]['usd_cap'] > 0
    finally:
        WC.PATH = keep


def _quiet_test() -> bool:
    """main() дважды на пустой demo-очереди: ни одного вызова mesh_wave_start, ни одного счёта сверх нужного, строка
    журнала одна. Пути, замки, диск и подпроцессы подменены — ни сети, ни Salad."""
    import collections  # noqa: PLC0415
    import tempfile  # noqa: PLC0415
    g = globals()
    keep = {k: g[k] for k in ('LEASE', 'JOURNAL', 'NOTE', 'NO_CREDITS', 'LOCKS', 'STOPS', 'profile_jobs')}
    keep_run, keep_du = subprocess.run, shutil.disk_usage
    calls = []
    tmp = tempfile.mkdtemp()
    try:
        g.update(LEASE=os.path.join(tmp, 'lease.json'), JOURNAL=os.path.join(tmp, 'j.jsonl'), NOTE=os.path.join(tmp, 'n.json'),
                 NO_CREDITS=os.path.join(tmp, 'nc.json'), LOCKS=[os.path.join(tmp, 'l')], STOPS=[os.path.join(tmp, 's')],
                 profile_jobs=lambda p: calls.append(('count', p)) or 0)
        json.dump({'expires': '2999-01-01', 'max_usd': 13, 'profile': 'demo', 'waves': []}, open(LEASE, 'w'))
        subprocess.run = lambda *a, **k: calls.append(('run', a[0])) or subprocess.CompletedProcess(a[0], 0, '', '')
        shutil.disk_usage = lambda p: collections.namedtuple('du', 'total used free')(100, 10, 90 * 2**30)
        import io, contextlib  # noqa: E401,PLC0415
        with contextlib.redirect_stdout(io.StringIO()):
            main(); main()
        lines = open(JOURNAL).read().splitlines()
        return (not [c for c in calls if c[0] == 'run'] and len([c for c in calls if c[0] == 'count']) == 2
                and len(lines) == 1 and json.loads(lines[0])['verdict'] == 'nothing_to_do')
    finally:
        g.update(keep)
        subprocess.run, shutil.disk_usage = keep_run, keep_du


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())

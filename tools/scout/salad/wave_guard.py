#!/usr/bin/env python3
"""Автозапуск волны мешей по разрешению владельца (план conv-11, ADR-0274).

ЗАЧЕМ. Владелец 13.10: «закинул деньги на Salad — всё сделалось само, виртуалки погасились». Баланс Salad программно
не узнать (в API нет — только попыткой старта), поэтому старт идёт только по РАЗРЕШЕНИЮ владельца с потолком
(`~/scout-scenes/wave-lease.json`: срок и сумма $), а без него сторож только наблюдает и пишет причину.

РАЗРЕШЕНИЕ: {"expires": "2026-10-31", "max_usd": 30, "min_jobs": 200}. Потолок переводится в число моделей по оценке
цены модели (`rules/salad-groups.json → wave.usd_per_mesh`); израсходованное копится в том же файле (`used_jobs`).
Волна запускается ТЕМ ЖЕ законным путём (`mesh_wave_start.sh --launch`) с `MESH_MAX_JOBS` = остаток и
`MESH_MIN_JOBS`. Конец очереди, нет денег, предел — гасит сам конвейер (`finale()` с проверкой `stopped`), DEV пропал —
мёртвая рука на сервере.

НЕ СТАРТУЕМ, если: нет разрешения/истекло/потолок выбран; конвейер или другой старт идёт; стоп-файлы владельца
(`mesh-group-halt.json`, `mesh-batch.PAUSE`); «нет денег» было меньше 2 ч назад; диск DEV ≥ 85 % или < 20 ГБ.
«Жду денег» — одно сообщение в сутки. Крон DEV: */15.

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


def decide(lease: dict | None, today: str, busy: bool, stops: list, no_credit_age_h: float | None,
           disk_pct: float, free_gb: float, usd_per_mesh: float) -> tuple[str, dict]:
    """→ (решение, параметры старта). Чистая функция — проверяется селфтестом."""
    if busy:
        return 'busy', {}
    if stops:
        return 'stopped_by_owner', {}
    if not lease:
        return 'no_lease', {}
    if str(lease.get('expires', '')) < today:
        return 'lease_expired', {}
    budget_jobs = int(float(lease.get('max_usd', 0)) / usd_per_mesh)
    left = budget_jobs - int(lease.get('used_jobs', 0))
    min_jobs = int(lease.get('min_jobs', 100))
    if left < min_jobs:
        return 'budget_spent', {}
    if no_credit_age_h is not None and no_credit_age_h < 2:
        return 'waiting_money', {}
    if disk_pct >= 85 or free_gb < 20:
        return 'disk', {}
    return 'start', {'MESH_MAX_JOBS': str(left), 'MESH_MIN_JOBS': str(min_jobs)}


def main() -> int:
    dry = '--dry' in sys.argv
    lease = json.load(open(LEASE, encoding='utf-8')) if os.path.exists(LEASE) else None
    rules = json.load(open(RULES, encoding='utf-8'))
    usd_per_mesh = float((rules.get('wave') or {}).get('usd_per_mesh', 0.013))
    nc_age = (time.time() - json.load(open(NO_CREDITS)).get('at', 0)) / 3600 if os.path.exists(NO_CREDITS) else None
    du = shutil.disk_usage(os.path.expanduser('~'))
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    verdict, env = decide(lease, today, any(held(p) for p in LOCKS), [p for p in STOPS if os.path.exists(p)],
                          nc_age, du.used / du.total * 100, du.free / 2**30, usd_per_mesh)
    rec = {'at': time.time(), 'verdict': verdict, **env}
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
    r = subprocess.run(['bash', os.path.join(HERE, '..', 'mesh_wave_start.sh'), '--launch'], env={**os.environ, **env},
                       capture_output=True, text=True, timeout=4 * 3600)
    print(r.stdout[-1500:], r.stderr[-500:], flush=True)
    if r.returncode == 0:
        lease['used_jobs'] = int(lease.get('used_jobs', 0)) + int(env['MESH_MAX_JOBS'])   # резерв: волна не больше остатка
        lease.setdefault('waves', []).append({'at': today, 'max_jobs': int(env['MESH_MAX_JOBS'])})
        json.dump(lease, open(LEASE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'),
                        f"Меши: волна запущена по вашему разрешению — до {env['MESH_MAX_JOBS']} моделей "
                        f"(≈ ${int(env['MESH_MAX_JOBS']) * usd_per_mesh:.0f}). Конец очереди или денег — машины погаснут сами."],
                       check=False, timeout=60)
    return r.returncode


def _selftest() -> int:
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('OK   ' if cond else 'FAIL ') + name)
        bad += 0 if cond else 1

    L = {'expires': '2026-10-31', 'max_usd': 13, 'min_jobs': 200}
    d = lambda **k: decide(**{'lease': L, 'today': '2026-10-14', 'busy': False, 'stops': [], 'no_credit_age_h': None,
                             'disk_pct': 50, 'free_gb': 100, 'usd_per_mesh': 0.013, **k})
    ok('разрешение есть, всё чисто — старт на остаток 1000 моделей', d() == ('start', {'MESH_MAX_JOBS': '1000', 'MESH_MIN_JOBS': '200'}))
    ok('без разрешения — только наблюдаем', d(lease=None)[0] == 'no_lease')
    ok('разрешение истекло', d(today='2026-11-01')[0] == 'lease_expired')
    ok('потолок выбран', d(lease={**L, 'used_jobs': 900})[0] == 'budget_spent')
    ok('нет денег был час назад — ждём', d(no_credit_age_h=1.0)[0] == 'waiting_money')
    ok('нет денег был 3 ч назад — пробуем снова', d(no_credit_age_h=3.0)[0] == 'start')
    ok('конвейер идёт — не мешаем', d(busy=True)[0] == 'busy')
    ok('стоп-файл владельца сильнее разрешения', d(stops=['halt'])[0] == 'stopped_by_owner')
    ok('диск DEV почти полон — не стартуем', d(disk_pct=90)[0] == 'disk')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())

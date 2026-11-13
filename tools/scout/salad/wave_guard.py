#!/usr/bin/env python3
"""Автозапуск волны мешей по разрешению владельца (план conv-11, ADR-0274).

ЗАЧЕМ. Владелец 13.10: «закинул деньги на Salad — всё сделалось само, виртуалки погасились». Баланс Salad программно
не узнать (в API нет — только попыткой старта), поэтому старт идёт только по РАЗРЕШЕНИЮ владельца с потолком
(`~/scout-scenes/wave-lease.json`: срок и сумма $), а без него сторож только наблюдает и пишет причину.

РАЗРЕШЕНИЕ: {"expires": "2026-10-31", "max_usd": 30, "min_jobs": 200}. Остаток денег переводится в число моделей по
оценке цены модели (`rules/salad-groups.json → wave.usd_per_mesh`). На старте в разрешение пишется волна с потолком
`usd_cap` и отметкой книги расходов сторожа денег `usd_mark`; сторож денег гасит пул, когда потолок выбран
(`money_guard.budget_breach`). Конвейер вышел → волна закрывается: факт денег и моделей, итог владельцу в Telegram,
потраченное копится в `spent_usd`. Конец волны — её СОБСТВЕННЫЙ конвейер (T-20261113-55/2): отметка финала `usd_end`
(`batch_show.finale` → `mark_end`, только если группы подтверждённо погашены) или подтверждённый запуск более поздней
волны (`launched`; запись, закрытая без запуска, — не конец, T-20261113-55/3); деньги и модели — за окно её конвейера
(`money_guard.wave_end`/`wave_spent`), даже если замки уже держит другая волна. Ни того ни другого — по свободным замкам,
как раньше. Файл разрешения правят три процесса (этот крон, финал конвейера, старт) — каждый под замком `.lock` рядом
с файлом и по свежему чтению (`lease_locked`), иначе один затирал бы правку другого.
Волна запускается ТЕМ ЖЕ законным путём (`mesh_wave_start.sh --launch`) с `MESH_TAKE_JOBS` = остаток (с профилем — не больше заданий профиля, T-20261106-82/3; верх очереди по приоритету; `MESH_MAX_JOBS` — отдельный предохранитель снимка) и
`MESH_MIN_JOBS`. Конец очереди, нет денег, предел — гасит сам конвейер (`finale()` с проверкой `stopped`), DEV пропал —
мёртвая рука на сервере.

НЕ СТАРТУЕМ, если: нет разрешения/истекло/потолок выбран; конвейер или другой старт идёт; стоп-файлы владельца
(`mesh-group-halt.json`, `mesh-batch.PAUSE`); «нет денег» было меньше 2 ч назад; на диске DEV свободно < 20 ГБ (процент занятого не
смотрим — владелец 10.11, TG 710: на диске 391 ГБ 85 % — это ещё ~58 ГБ свободно); ни одну группу
из `SALAD_GROUP` нельзя поднять сейчас (запрет цены, `disabled`, окно — `salad_groups.allowed_now`; T-20261106-82/2).
«Жду денег» — одно сообщение в сутки. Крон DEV: */15.

ПРОФИЛЬ ОЧЕРЕДИ — ИЗ РАЗРЕШЕНИЯ (владелец 21.10: «меши не на весь каталог, а сколько нужно для демо»; T-20261021-10/2).
`"profile": "demo"` в lease → старт с `MESH_QUEUE_PROFILE=demo` (`mesh_wave_start.sh` собирает снимок по
`rules/mesh-queue-demo.json`), порог — `"profile_min_jobs"` (по умолчанию 1) вместо боевого `min_jobs`. Без поля — боевая
очередь, как раньше. Раньше профиль жил только в окружении ручного запуска: крон его не знал и через ≤15 мин после
demo-волны поднимал боевую на 5578 заданий. Заданий профиля меньше порога → «нечего делать»: шаги старта не проходим,
волну не открываем, в журнал — одна строка на смену состояния.

ЛЕЧЕНИЕ — ТОЛЬКО ПО СЛОВУ ВЛАДЕЛЬЦА (T-20261027-02/2): `"heal": true` в разрешении → запись волны `heal: true` и старт с
`MESH_HEAL=1` (перегон `mesh-reseed.json` в конце волны). Без поля — `MESH_HEAL=0`: список не чистится и ушёл бы целиком.

  ~/venvs/scout/bin/python salad/wave_guard.py           # решение (+ старт, если можно)
  ~/venvs/scout/bin/python salad/wave_guard.py --dry     # только решение
  python3 salad/wave_guard.py --selftest
"""
import contextlib
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


def groups_now() -> list:
    """[(группа, можно поднять сейчас)] по строке `SALAD_GROUP` из salad.env — тем же чтением, что у сторожа денег
    (`money_guard.env_groups`), и тем же правилом, что у конвейера (`salad_groups.allowed_now`: запрет цены, `disabled`, окно).
    Строки нет — пустой список (→ 'no_group'): конвейеру `mesh_wave_start.sh` поднимать было бы нечего."""
    import money_guard as MG  # noqa: PLC0415
    import salad_groups as SG  # noqa: PLC0415
    return [(g, bool(SG.allowed_now(g))) for g in (MG.env_groups() or [])]


def decide(lease: dict | None, today: str, busy: bool, stops: list, no_credit_age_h: float | None,
           disk_pct: float, free_gb: float, usd_per_mesh: float, jobs: int | None = None,
           groups: list | None = None) -> tuple[str, dict]:
    """→ (решение, параметры старта). Чистая функция — проверяется селфтестом. `jobs` — сколько заданий у профиля
    (считает `main` только для профиля и только когда иначе был бы старт): меньше порога → 'nothing_to_do'.
    `groups` — [(группа, можно ли поднять сейчас)] из `SALAD_GROUP` (None — не проверяли, как раньше): ни одной разрешённой →
    'no_group' (T-20261106-82/2: с разрешением, но без годной группы конвейер стартовал бы впустую)."""
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
    if free_gb < 20:                                    # только свободное место (TG 710); `disk_pct` в запрете не участвует
        return 'disk', {}
    if groups is not None and not any(ok for _g, ok in groups):
        return 'no_group', {'groups': ','.join(g for g, _ok in groups) or '—'}
    if profile and jobs is None:
        return 'profile_unknown', {'MESH_QUEUE_PROFILE': profile}
    if profile and jobs < min_jobs:
        return 'nothing_to_do', {'MESH_QUEUE_PROFILE': profile, 'jobs': jobs}
    # ПОТОЛОК ПО ОЧЕРЕДИ (T-20261106-82/3, ведущий): с профилем берём min(деньги, задания профиля) — иначе `MESH_TAKE_JOBS`
    # считался от денег (373 при очереди 105), и потолок волны (`take × usd_per_mesh × 1,5`) становился всем остатком разрешения
    take = min(left, jobs) if profile and jobs is not None else left
    return 'start', {'MESH_TAKE_JOBS': str(take), 'MESH_MIN_JOBS': str(min_jobs),
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


def meshes_since(t: float, until: float | None = None) -> int:
    """Готовых моделей (`ok`) в журнале заданий с `t` по `until` (None — по сейчас): окно конвейера волны."""
    n = 0
    try:
        with open(PROGRESS, encoding='utf-8') as f:
            for ln in f:
                if '"ok"' in ln:
                    try:
                        r = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    at = r.get('at', 0)
                    n += r.get('status') == 'ok' and at >= t and (until is None or at <= until)
    except FileNotFoundError:
        pass
    return n


def _save_lease(lease: dict) -> None:
    tmp = LEASE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(lease, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LEASE)


def _read_lease() -> dict | None:
    try:
        d = json.load(open(LEASE, encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


@contextlib.contextmanager
def lease_locked():
    """Замок правки файла разрешения (`wave-lease.json.lock` рядом с ним). Правят трое: этот крон (`close_wave`, запись и
    отметка старта), финал конвейера (`mark_end`). Без замка «прочитал — поправил — записал» одного затирал правку
    другого: финал писал `usd_end` в уже закрытую волну и открывал её снова, или закрытие теряло отметку финала.
    Держать коротко — только чтение-правку-запись, не подпроцессы."""
    with open(LEASE + '.lock', 'a') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lk, fcntl.LOCK_UN)


def _edit_wave(started: float, **fields) -> dict | None:
    """Под замком, по свежему чтению: поля — в запись волны с этим `started` → весь файл разрешения; не нашли — None."""
    with lease_locked():
        lease = _read_lease()
        w = next((x for x in reversed((lease or {}).get('waves') or []) if x.get('started') == started), None)
        if w is None:
            return None
        w.update(fields)
        _save_lease(lease)
        return lease


def mark_end(paid_usd: float, now: float | None = None) -> dict | None:
    """Конвейер волны автозапуска вышел и погасил группы (`batch_show.finale` при MESH_WAVE_LEASE=1, T-20261113-55/2):
    отметка книги `usd_end` и время `ended` — в открытую волну разрешения. С этой минуты конвейер волны больше не тратит
    (потолок не судится), даже если замки тут же займёт другая волна; закроет волну и подведёт итог `close_wave` на
    ближайшем тике. Открытой волны нет или отметка уже стоит — None, файл не трогаем. Под замком файла (`lease_locked`)."""
    with lease_locked():
        lease = _read_lease()
        if lease is None:
            return None
        w = (lease.get('waves') or [{}])[-1]
        if w.get('usd_cap') is None or w.get('closed') or w.get('usd_end') is not None:
            return None
        w.update({'ended': now or time.time(), 'usd_end': round(paid_usd, 4)})
        _save_lease(lease)
        return w


def other_waves() -> list:
    """Записи ручных волн (`wave_cap`, свой файл): подтверждённый запуск любой из них (`launched`) — конец расхода
    открытой волны разрешения (`money_guard.next_launch`)."""
    import wave_cap as WC  # noqa: PLC0415
    return (WC.read() or {}).get('waves') or []


def close_wave(lease: dict, dry: bool, others=()) -> None:
    """Конвейер волны вышел — закрыть волну: факт денег и моделей ЗА ОКНО ЕЁ КОНВЕЙЕРА (`money_guard.wave_spent`: до
    запуска следующей волны, а её нет — книга на момент закрытия, с хвостом гашения; чужая ручная волна в её счёт не
    идёт), итог владельцу, снять запрет «потолок» разрешения (он своё отработал; следующую волну ограничит остаток).
    Правка — под замком файла и по СВЕЖЕМУ чтению (`lease_locked`): `lease` вызывающего обновляется на месте."""
    import money_guard as MG  # noqa: PLC0415 — книга расходов сторожа денег (один источник)
    halt = json.load(open(STOPS[0], encoding='utf-8')) if os.path.exists(STOPS[0]) else None
    with lease_locked() if not dry else contextlib.nullcontext():
        fresh = None if dry else _read_lease()
        if fresh is not None:
            lease.clear()
            lease.update(fresh)
        elif not dry:
            return
        w = (lease.get('waves') or [{}])[-1]
        if w.get('usd_cap') is None or w.get('closed'):
            return                                      # закрыл кто-то раньше (другой тик) — второй итог не шлём
        spent = MG.wave_spent(MG.load(), w, others)
        until = MG.wave_end(w, others)[1]
        own = halt if halt and halt.get('source', 'lease') == 'lease' else None   # потолок ручной волны — не наш итог
        nc = json.load(open(NO_CREDITS)).get('at') if os.path.exists(NO_CREDITS) else None
        why = close_reason(own, nc if until is None or (nc or 0) <= until else None, float(w['started']))
        meshes = meshes_since(float(w['started']), until)
        w.update({'closed': time.time(), 'spent_usd': round(spent, 2), 'meshes': meshes, 'why': why})
        lease['spent_usd'] = round(float(lease.get('spent_usd', 0)) + spent, 2)
        print('волна закрыта:', json.dumps(w, ensure_ascii=False), flush=True)
        if dry:
            return
        _save_lease(lease)
    if halt and halt.get('kind') == 'budget' and halt.get('source', 'lease') == 'lease':   # потолок ручной волны снимает её finale
        os.remove(STOPS[0])
    subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'), wave_summary(w, spent, meshes, why, left_usd(lease))],
                   check=False, timeout=180)


def main() -> int:
    dry = '--dry' in sys.argv
    lease = json.load(open(LEASE, encoding='utf-8')) if os.path.exists(LEASE) else None
    busy = any(held(p) for p in LOCKS)
    open_wave = bool(lease and (lease.get('waves') or [{}])[-1].get('usd_cap') is not None
                     and not lease['waves'][-1].get('closed'))
    if open_wave:
        # ВОЛНА ЗАКРЫВАЕТСЯ ПО СВОЕМУ КОНВЕЙЕРУ, А НЕ ПО СВОБОДНЫМ ЗАМКАМ (T-20261113-55/2): замки может держать уже другая
        # волна (12.11: автоволна вышла в 22:53, ручная T-55 заняла замки в 22:54 — лиз висел открытым и копил чужой расход).
        # Конец конвейера известен — `usd_end` из его финала или подтверждённый запуск более поздней волны (`launched`) —
        # закрываем сразу; иначе прежнее правило: замки свободны и с старта прошло 20 мин (конвейер успел взять замок).
        import money_guard as MG  # noqa: PLC0415
        others = other_waves()
        ended = MG.wave_end(lease['waves'][-1], others)[0] is not None
        if ended or not busy and time.time() - float(lease['waves'][-1]['started']) > 20 * 60:
            close_wave(lease, dry, others)
    rules = json.load(open(RULES, encoding='utf-8'))
    usd_per_mesh = float((rules.get('wave') or {}).get('usd_per_mesh', 0.013))
    nc_age = (time.time() - json.load(open(NO_CREDITS)).get('at', 0)) / 3600 if os.path.exists(NO_CREDITS) else None
    du = shutil.disk_usage(os.path.expanduser('~'))
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    args = (lease, today, busy or open_wave and not lease['waves'][-1].get('closed'),
            [p for p in STOPS if os.path.exists(p)], nc_age, du.used / du.total * 100, du.free / 2**30, usd_per_mesh)
    groups = groups_now()
    verdict, env = decide(*args, groups=groups)
    if verdict == 'profile_unknown':                    # профиль: задания считаем, только когда иначе был бы старт
        verdict, env = decide(*args, jobs=profile_jobs(env['MESH_QUEUE_PROFILE']), groups=groups)
    rec = {'at': time.time(), 'verdict': verdict, **env}
    if verdict in ('nothing_to_do', 'profile_unknown', 'no_group') and last_verdict() == verdict:
        return 0                                        # то же «нечего делать» — молчим: одна строка на смену состояния
    with open(JOURNAL, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f'{today} автозапуск волны: {verdict} {env}', flush=True)
    if verdict == 'waiting_money':                      # одно сообщение в сутки
        note = json.load(open(NOTE)) if os.path.exists(NOTE) else {}
        if note.get('day') != today and not dry:
            subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'),
                            waiting_text(lease.get('expires'))], check=False, timeout=180)
            json.dump({'day': today}, open(NOTE, 'w'))
    if verdict != 'start' or dry:
        return 0
    import money_guard as MG  # noqa: PLC0415
    cap = round(min(left_usd(lease), int(env['MESH_TAKE_JOBS']) * usd_per_mesh * 1.5), 2)   # запас на прогрев/простой
    cap = min(cap, round(left_usd(lease), 2))
    heal = lease.get('heal') is True
    t_start = time.time()
    rec = {'at': today, 'started': t_start, 'max_jobs': int(env['MESH_TAKE_JOBS']),
           'usd_cap': cap, 'usd_mark': round(MG.paid_usd(MG.load()), 2), 'heal': heal}
    with lease_locked():                                # ДО старта: сторож видит потолок
        lease = _read_lease() or lease
        lease.setdefault('waves', []).append(rec)
        _save_lease(lease)
    # MESH_WAVE_LEASE=1: потолок этой волны — запись выше в разрешении, ручной `--rub-cap` старту не нужен (T-20261027-02)
    r = subprocess.run(['bash', os.path.join(HERE, '..', 'mesh_wave_start.sh'), '--launch'],
                       env={**os.environ, **env, 'MESH_WAVE_LEASE': '1', 'MESH_HEAL': '1' if heal else '0'},
                       capture_output=True, text=True, timeout=4 * 3600)
    print(r.stdout[-1500:], r.stderr[-500:], flush=True)
    if r.returncode != 0:                               # не стартовали — волну не открываем (денег не тратили)
        # без `launched`: запись, закрытая без запуска, конец чужой волны не задаёт (`money_guard.next_launch`)
        lease = _edit_wave(t_start, closed=time.time(), spent_usd=0, meshes=0,
                           why=f'старт не удался rc={r.returncode}') or lease
    else:
        # код 0 у `--launch` = `mesh_wave_start.sh` увидел процесс конвейера (pgrep): запуск подтверждён
        lease = _edit_wave(t_start, launched=time.time()) or lease
        subprocess.run(['bash', os.path.join(HERE, '..', 'alert.sh'),
                        start_text(len(lease['waves']), left_usd(lease), lease.get('expires'),
                                   int(env['MESH_TAKE_JOBS']), cap)],
                       check=False, timeout=180)
    return r.returncode


def _ddmm(expires) -> str:
    """'2026-11-14' → '14.11'; непонятное — как есть."""
    s = str(expires or '')
    return f'{s[8:10]}.{s[5:7]}' if len(s) >= 10 and s[4] == '-' and s[7] == '-' else (s or '?')


def start_text(n: int, left: float, expires, jobs: int, cap: float) -> str:
    """Сообщение о старте волны (T-20261107-26: владелец «я не давал потолок такой» — потолок волны считает автомат, не
    человек; «по вашему разрешению» убрано)."""
    return (f'Меши: волна {n} запущена в рамках общего разрешения на меши (осталось ${left:.2f} до {_ddmm(expires)}) — '
            f'до {jobs} моделей; потолок волны ${cap:.2f} посчитан автоматически (модели × цена × 1,5). '
            'Конец очереди, денег или потолка — машины погаснут сами, итог пришлю.')


def waiting_text(expires) -> str:
    return (f'Меши: на Salad нет денег — волна ждёт пополнения (общее разрешение на меши действует до {_ddmm(expires)}). '
            'Пополните баланс — старт сам в течение 2 ч.')


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
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))  # tools/scout — помощник временного
    import remlab_tmp  # временное селфтеста — на диске, не в /tmp; папка убирается при выходе (T-20261107-13)
    remlab_tmp.use('wave_guard-selftest')
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
    t = start_text(10, 0.64, '2026-11-14', 33, 0.64)
    ok('текст старта: номер волны, остаток до DD.MM, потолок — автоматически, без «вашего»',
       t.startswith('Меши: волна 10 запущена в рамках общего разрешения на меши (осталось $0.64 до 14.11) — до 33 моделей;')
       and 'потолок волны $0.64 посчитан автоматически (модели × цена × 1,5)' in t and 'ваш' not in t)
    ok('текст ожидания денег: до DD.MM, без «вашего»',
       'действует до 14.11' in waiting_text('2026-11-14') and 'ваш' not in waiting_text('2026-11-14'))
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
    ok('свободно 19 ГБ — не стартуем', d(disk_pct=95, free_gb=19)[0] == 'disk')
    ok('занято 95 %, но свободно 21 ГБ — старт (процент не запрещает, TG 710)', d(disk_pct=95, free_gb=21)[0] == 'start')
    ok('ровно 20 ГБ — старт (порог «меньше 20»)', d(disk_pct=99, free_gb=20)[0] == 'start')
    ok('нет разрешённой группы (запрет цены / disabled) — не стартуем, группы в журнал',
       d(groups=[('mesh-low-10', False), ('mesh-q-low-1', False)]) == ('no_group', {'groups': 'mesh-low-10,mesh-q-low-1'}))
    ok('SALAD_GROUP пуст — не стартуем', d(groups=[]) == ('no_group', {'groups': '—'}))
    ok('хоть одна группа разрешена — старт', d(groups=[('a', False), ('b', True)])[0] == 'start')
    ok('без проверки групп (None) — прежнее решение', d(groups=None)[0] == 'start')
    # ПРОФИЛЬ ОЧЕРЕДИ (T-20261021-10/2)
    D = {**L, 'profile': 'demo', 'profile_min_jobs': 1}
    ok('lease без profile — боевой: в env старта профиля нет', 'MESH_QUEUE_PROFILE' not in d()[1])
    ok('profile=demo: без счёта заданий не стартуем', d(lease=D)[0] == 'profile_unknown')
    ok('profile=demo доходит до env старта, порог — свой (1), не боевой 200; берём min(деньги 1000, очередь 9)',
       d(lease=D, jobs=9) == ('start', {'MESH_TAKE_JOBS': '9', 'MESH_MIN_JOBS': '1', 'MESH_QUEUE_PROFILE': 'demo'}))
    ok('profile=demo: очередь больше денег — берём по деньгам (1000 из 5000)',
       d(lease=D, jobs=5000)[1].get('MESH_TAKE_JOBS') == '1000')
    ok('пустая demo-очередь — «нечего делать», не старт', d(lease=D, jobs=0)[0] == 'nothing_to_do')
    ok('profile_min_jobs по умолчанию 1', profile_of({'profile': 'demo', 'min_jobs': 50}) == ('demo', 1))
    ok('пустая demo-очередь: mesh_wave_start не зовётся, в журнале одна строка за два тика', _quiet_test())
    ok('ручная волна с потолком не продлевает разрешение: истёкший lease — по-прежнему lease_expired', _manual_cap_test())
    ok('лечение автоволны — только по "heal": true в разрешении (MESH_HEAL 0/1, запись волны); потолок волны — по очереди профиля',
       _heal_word_test())
    ok('нет разрешённой группы: mesh_wave_start не зовётся, волна не открыта, в журнале «no_group» одной строкой за два тика',
       _no_group_test())
    for name, res in _foreign_lock_tests():
        ok(name, res)
    return 1 if bad else 0


def _foreign_lock_tests() -> list:
    """T-20261113-55/2 — случай 12.11: автоволна вышла, замки сразу заняла ручная волна T-55. → [(имя, итог)].
    Пути, замки, книга денег и подпроцессы подменены; замок держит этот же процесс (как чужой конвейер)."""
    import collections  # noqa: PLC0415
    import io, contextlib, tempfile  # noqa: E401,PLC0415
    import money_guard as MG  # noqa: PLC0415
    import wave_cap as WC  # noqa: PLC0415
    g = globals()
    keep = {k: g[k] for k in ('LEASE', 'JOURNAL', 'NOTE', 'NO_CREDITS', 'LOCKS', 'STOPS', 'PROGRESS', 'profile_jobs',
                              'groups_now')}
    keep_run, keep_du, keep_mg, keep_wc = subprocess.run, shutil.disk_usage, (MG.load, MG.paid_usd), WC.PATH
    tmp = tempfile.mkdtemp()
    out = []
    lk = None
    try:
        g.update(LEASE=os.path.join(tmp, 'lease.json'), JOURNAL=os.path.join(tmp, 'j.jsonl'), NOTE=os.path.join(tmp, 'n.json'),
                 NO_CREDITS=os.path.join(tmp, 'nc.json'), LOCKS=[os.path.join(tmp, 'l')], STOPS=[os.path.join(tmp, 's')],
                 PROGRESS=os.path.join(tmp, 'p.jsonl'), profile_jobs=lambda p: 100, groups_now=lambda: [('g', True)])
        WC.PATH = os.path.join(tmp, 'manual.json')
        book = {'usd': 13.80}
        MG.load, MG.paid_usd = (lambda: {}), (lambda st: book['usd'])
        shutil.disk_usage = lambda p: collections.namedtuple('du', 'total used free')(100, 10, 90 * 2**30)
        calls = []
        subprocess.run = lambda a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, '', '')
        lk = open(LOCKS[0], 'w')
        fcntl.flock(lk, fcntl.LOCK_EX)                     # замок держит «ручной конвейер»
        t_auto = time.time() - 3 * 3600
        t_man = time.time() - 3600
        with open(PROGRESS, 'w') as f:                     # 20 моделей автоволны, 7 — ручной
            for k in range(27):
                f.write(json.dumps({'status': 'ok', 'at': t_auto + 60 + k * 60 if k < 20 else t_man + 60 + k}) + '\n')

        def lease_with(**w) -> dict:
            d = {'expires': '2999-01-01', 'max_usd': 16.16, 'spent_usd': 13.32, 'profile': 'demo',
                 'waves': [{'started': t_auto, 'max_jobs': 21, 'usd_cap': 0.41, 'usd_mark': 13.32, **w}]}
            json.dump(d, open(LEASE, 'w'))
            return d
        # (а)+(б)+(в): ручная волна стартовала после автоволны, замки заняты ею
        lease_with()
        json.dump({'waves': [{'started': t_man, 'usd_cap': 2.7621, 'usd_mark': 13.5945, 'launched': t_man + 3}]},
                  open(WC.PATH, 'w'))
        json.dump({'kind': 'budget', 'source': 'manual'}, open(STOPS[0], 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            main()
        w = json.load(open(LEASE))['waves'][-1]
        sent = ' '.join(str(c[-1]) for c in calls)
        out.append(('замки держит чужая (ручная) волна — лиз автоволны всё равно закрыт', bool(w.get('closed'))))
        out.append(('расход лиза — до старта ручной волны ($0.27), не «всё с отметки» ($0.48); остаток разрешения верный',
                    w.get('spent_usd') == 0.27 and abs(json.load(open(LEASE))['spent_usd'] - 13.59) <= 0.01))
        out.append(('модели — только своего окна (20, не 27); потолок ручной волны — не причина закрытия лиза',
                    w.get('meshes') == 20 and w.get('why', '').startswith('очередь') and os.path.exists(STOPS[0])))
        out.append(('итог владельцу ушёл, новая волна при занятых замках не стартует',
                    'волна закончилась' in sent and not any(str(a).endswith('mesh_wave_start.sh') for c in calls for a in c)))
        # (а) по отметке финала: ручной волны нет, замки заняты (например, канарейка), конвейер волны вышел сам
        os.remove(WC.PATH)
        os.remove(STOPS[0])
        lease_with()
        book['usd'] = 13.50
        r = mark_end(MG.paid_usd({}), now=t_man)
        book['usd'] = 13.80
        again = mark_end(14.0)
        with contextlib.redirect_stdout(io.StringIO()):
            main()
        w = json.load(open(LEASE))['waves'][-1]
        out.append(('финал конвейера отмечает конец волны один раз (usd_end, ended), повтор — не трогает',
                    bool(r) and again is None and w.get('usd_end') == 13.5 and w.get('ended') == t_man))
        out.append(('по отметке финала лиз закрыт при занятых замках; деньги — книга на момент закрытия ($0.48, с хвостом '
                    'гашения: позже никто не запускался), модели — до отметки (20)',
                    bool(w.get('closed')) and w.get('spent_usd') == 0.48 and w.get('meshes') == 20))
        # контроль: конца не видно (ни отметки, ни следующей волны), замки заняты — волна ещё идёт, не закрываем
        lease_with()
        with contextlib.redirect_stdout(io.StringIO()):
            main()
        out.append(('конца не видно и замки заняты — волна открыта, как раньше',
                    not json.load(open(LEASE))['waves'][-1].get('closed')))
        # T-20261113-55/3: ручная запись после лиза, закрытая БЕЗ запуска («конвейер не поднялся») — не конец лиза
        lease_with()
        json.dump({'waves': [{'started': t_man, 'usd_cap': 2.7621, 'usd_mark': 13.5945, 'closed': t_man + 4,
                              'why': 'конвейер не поднялся'}]}, open(WC.PATH, 'w'))
        with contextlib.redirect_stdout(io.StringIO()):
            main()
        out.append(('ручная запись без запуска после лиза — лиз открыт, его потолок судится (замки заняты)',
                    not json.load(open(LEASE))['waves'][-1].get('closed')
                    and MG.breach_of({}, json.load(open(LEASE)), WC.read())[1] == 'lease'))
        # ОДНОВРЕМЕННАЯ ПРАВКА ФАЙЛА РАЗРЕШЕНИЯ: финал (`mark_end`) и крон (`close_wave`) — без потери правки
        os.remove(WC.PATH)
        lease_with()
        stale = json.load(open(LEASE))                     # крон прочитал файл ДО отметки финала
        book['usd'] = 13.50
        mark_end(13.50, now=t_man)
        book['usd'] = 13.80
        with contextlib.redirect_stdout(io.StringIO()):
            close_wave(stale, False, [])
        w = json.load(open(LEASE))['waves'][-1]
        out.append(('крон закрывает по старому чтению после отметки финала — отметка финала не потеряна',
                    bool(w.get('closed')) and w.get('usd_end') == 13.5 and stale['waves'][-1].get('usd_end') == 13.5))
        import threading  # noqa: PLC0415
        lease_with()
        res = {}
        with lease_locked():                               # крон держит файл: финал ждёт, а не пишет поверх
            th = threading.Thread(target=lambda: res.update(r=mark_end(13.6)))
            th.start()
            time.sleep(0.3)
            waited = th.is_alive() and 'usd_end' not in json.load(open(LEASE))['waves'][-1]
            d = json.load(open(LEASE))
            d['waves'][-1].update(closed=time.time(), why='закрыл крон')
            _save_lease(d)
        th.join(5)
        w = json.load(open(LEASE))['waves'][-1]
        out.append(('финал и крон одновременно: финал ждёт замок и видит закрытую волну — не открывает её снова',
                    waited and res.get('r') is None and bool(w.get('closed')) and 'usd_end' not in w))
        # старт автоволны: код 0 (конвейер поднялся) → `launched`; код 75 → закрыта без `launched`
        lk.close()
        lk = None
        for rc in (0, 75):
            json.dump({'expires': '2999-01-01', 'max_usd': 16.16, 'spent_usd': 13.32, 'profile': 'demo', 'waves': []},
                      open(LEASE, 'w'))
            subprocess.run = (lambda code: lambda a, **k: calls.append(a) or subprocess.CompletedProcess(
                a, code if str(a[-1]) == '--launch' else 0, '', ''))(rc)
            with contextlib.redirect_stdout(io.StringIO()):
                main()
            w = json.load(open(LEASE))['waves'][-1]
            out.append((f'старт автоволны с кодом {rc}: ' + ('запуск подтверждён — `launched` в записи' if rc == 0 else
                        'не поднялся — запись закрыта без `launched` (конец чужой волны не задаёт)'),
                        bool(w.get('launched')) and not w.get('closed') if rc == 0 else
                        bool(w.get('closed')) and 'launched' not in w and w.get('why') == 'старт не удался rc=75'))
    finally:
        if lk:
            lk.close()
        g.update(keep)
        subprocess.run, shutil.disk_usage = keep_run, keep_du
        MG.load, MG.paid_usd = keep_mg
        WC.PATH = keep_wc
    return out


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
    keep = {k: g[k] for k in ('LEASE', 'JOURNAL', 'NOTE', 'NO_CREDITS', 'LOCKS', 'STOPS', 'profile_jobs', 'groups_now')}
    keep_run, keep_du = subprocess.run, shutil.disk_usage
    calls = []
    tmp = tempfile.mkdtemp()
    try:
        g.update(LEASE=os.path.join(tmp, 'lease.json'), JOURNAL=os.path.join(tmp, 'j.jsonl'), NOTE=os.path.join(tmp, 'n.json'),
                 NO_CREDITS=os.path.join(tmp, 'nc.json'), LOCKS=[os.path.join(tmp, 'l')], STOPS=[os.path.join(tmp, 's')],
                 profile_jobs=lambda p: calls.append(('count', p)) or 0, groups_now=lambda: [('g', True)])
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


def _no_group_test() -> bool:
    """T-20261106-82/2: разрешение и задания есть, но ни одна группа `SALAD_GROUP` не разрешена — main() не стартует."""
    import collections  # noqa: PLC0415
    import io, contextlib, tempfile  # noqa: E401,PLC0415
    g = globals()
    keep = {k: g[k] for k in ('LEASE', 'JOURNAL', 'NOTE', 'NO_CREDITS', 'LOCKS', 'STOPS', 'profile_jobs', 'groups_now')}
    keep_run, keep_du = subprocess.run, shutil.disk_usage
    calls = []
    tmp = tempfile.mkdtemp()
    try:
        g.update(LEASE=os.path.join(tmp, 'lease.json'), JOURNAL=os.path.join(tmp, 'j.jsonl'), NOTE=os.path.join(tmp, 'n.json'),
                 NO_CREDITS=os.path.join(tmp, 'nc.json'), LOCKS=[os.path.join(tmp, 'l')], STOPS=[os.path.join(tmp, 's')],
                 profile_jobs=lambda p: 100, groups_now=lambda: [('mesh-q-low-1', False)])
        json.dump({'expires': '2999-01-01', 'max_usd': 13, 'profile': 'demo', 'waves': []}, open(LEASE, 'w'))
        subprocess.run = lambda *a, **k: calls.append(a[0]) or subprocess.CompletedProcess(a[0], 0, '', '')
        shutil.disk_usage = lambda p: collections.namedtuple('du', 'total used free')(100, 10, 90 * 2**30)
        with contextlib.redirect_stdout(io.StringIO()):
            main(); main()
        lines = open(JOURNAL).read().splitlines()
        return (not calls and json.load(open(LEASE))['waves'] == [] and len(lines) == 1
                and json.loads(lines[0]) | {'at': 0} == {'at': 0, 'verdict': 'no_group', 'groups': 'mesh-q-low-1'})
    finally:
        g.update(keep)
        subprocess.run, shutil.disk_usage = keep_run, keep_du


def _heal_word_test() -> bool:
    """T-20261027-02/2: лечение волны автозапуска — только по `"heal": true` в разрешении. Без поля старт идёт с
    MESH_HEAL=0 и записью `heal: false`, с полем — MESH_HEAL=1 и `heal: true`. Подпроцессы и книга денег подменены."""
    import collections  # noqa: PLC0415
    import io, contextlib, tempfile  # noqa: E401,PLC0415
    import money_guard as MG  # noqa: PLC0415
    g = globals()
    keep = {k: g[k] for k in ('LEASE', 'JOURNAL', 'NOTE', 'NO_CREDITS', 'LOCKS', 'STOPS', 'profile_jobs', 'groups_now')}
    keep_run, keep_du, keep_mg = subprocess.run, shutil.disk_usage, (MG.load, MG.paid_usd)
    tmp = tempfile.mkdtemp()
    got = []
    try:
        g.update(LEASE=os.path.join(tmp, 'lease.json'), JOURNAL=os.path.join(tmp, 'j.jsonl'), NOTE=os.path.join(tmp, 'n.json'),
                 NO_CREDITS=os.path.join(tmp, 'nc.json'), LOCKS=[os.path.join(tmp, 'l')], STOPS=[os.path.join(tmp, 's')],
                 profile_jobs=lambda p: 100, groups_now=lambda: [('g', True)])
        MG.load, MG.paid_usd = (lambda: {}), (lambda st: 0.0)
        shutil.disk_usage = lambda p: collections.namedtuple('du', 'total used free')(100, 10, 90 * 2**30)

        def fake_run(args, **k):
            if any(str(a).endswith('mesh_wave_start.sh') for a in args):
                got.append(k['env'].get('MESH_HEAL'))
            return subprocess.CompletedProcess(args, 0, '', '')
        subprocess.run = fake_run
        res = []
        for extra in ({}, {'heal': True}):
            json.dump({'expires': '2999-01-01', 'max_usd': 13, 'profile': 'demo', 'waves': [], **extra}, open(LEASE, 'w'))
            with contextlib.redirect_stdout(io.StringIO()):
                main()
            w = json.load(open(LEASE))['waves'][-1]
            res.append((w.get('heal'), w.get('max_jobs'), w.get('usd_cap')))
        # потолок волны — от очереди профиля (100 × 0,013 × 1,5 = $1,95), не от всего разрешения $13 (T-20261106-82/3)
        upm = float((json.load(open(RULES, encoding='utf-8')).get('wave') or {}).get('usd_per_mesh', 0.013))
        cap = round(100 * upm * 1.5, 2)
        return got == ['0', '1'] and res == [(False, 100, cap), (True, 100, cap)]
    finally:
        g.update(keep)
        subprocess.run, shutil.disk_usage = keep_run, keep_du
        MG.load, MG.paid_usd = keep_mg


if __name__ == '__main__':
    sys.exit(_selftest() if '--selftest' in sys.argv else main())

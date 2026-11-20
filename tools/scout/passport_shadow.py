#!/usr/bin/env python3
"""ТЕНЬ паспортов типов: запись вердиктов сторожей К1/К3 в `passport_shadow` и ночной проход по уже вырезанному (план mesh-type-passports-01, фаза 1).

Тень только ПИШЕТ: ничего не блокирует, `photo_assessment`, ключ, очередь и платные входы не меняются. Модуль без torch (в CI живёт без GPU-зависимостей),
в `cutout_sync.py` — тонкие крючки: `after_assessment` (в `one()` ПОСЛЕ вставки `photo_assessment`, до `return 'ok'`) и `run_backfill` (`--shadow-backfill`).

ГАРАНТИИ (проверка v3/v4, тесты (а), (д), (д2) в `tests/test_mesh_type_passports.py`):
  • сбой тени не делает задачу вырезки `fail`: всё внутри своего `try`, счётчик `shadow_fail` отдельный (в `FAIL_STREAK_MAX` не входит);
  • `SHADOW_FAIL_MAX` (20) сбоев за прогон выключают тень в `one()` до конца прогона (`WARN:passport_shadow_off`), вырезка идёт; пропущенное подберёт проход;
  • пиксельный расчёт — в дочернем процессе с таймаутом `SHADOW_GUARD_TIMEOUT_S` (30 с): зависший сторож убит, исход `guard_timeout`;
  • КАЖДЫЙ вызов БД тени — с жёстким таймаутом (`SHADOW_DB_TIMEOUT_S`, 20 с: `statement_timeout`+`lock_timeout` в сеансе и `timeout` у подпроцесса), чтение вердиктов
    гейтом — `SHADOW_OBSERVE_TIMEOUT_S` (15 с), кандидатов прохода — `SHADOW_CANDIDATES_TIMEOUT_S` (120 с); скачивание исходника в проходе — не дольше
    `SHADOW_FETCH_TIMEOUT_S` (45 с) и остатка бюджета; на ВСЮ тень в `one()` за прогон — бюджет `SHADOW_RUN_BUDGET_S` (900 с): исчерпан → тень выключена до конца прогона;
  • нет таблицы (миграция `018-passport-shadow.sql` не применена) — одна строка `WARN:passport_shadow` и пропуск, не падение;
  • `PASSPORT_SHADOW=0` — выключатель на всё (ни в `one()`, ни в проходе).

ПРОХОД `--shadow-backfill` (тёплая часть: `todo()` берёт только фото без оценки, готовые сами в тень не попадут): СОСТОЯНИЕ — в самой таблице
(`status` done|retry|quarantine, `attempts`, `last_error`, `updated`), а не в памяти прогона. Порядок: сначала фото БЕЗ строки (спальня раньше, внутри — по sha),
потом `retry` по старшему `updated`, `attempts < SHADOW_ATTEMPTS_MAX` (3) и не раньше суток после последней попытки; 3-я неудача и терминальные исходы — `quarantine`
(в выборку не возвращается, пока не сменится версия замера или не запущено `--retry-quarantine`). Закрытый список исходов (OUTCOMES): плановые missing_cache,
fetch_failed, decode_failed, sha_moved, guard_timeout, ambiguous + два технических guard_error (прочее падение сторожа) и db_error (сбой БД на строке) — оба `retry`.
Бюджет ночи `SHADOW_BACKFILL_BUDGET_S` (1800 с); `SHADOW_BACKFILL_STREAK_MAX` (15) подряд сбоев ОДНОГО кода с retry-исходом завершают проход ЭТОЙ ночи
(`WARN:passport_backfill_stop code=…`, завтра идёт снова); число строк за ночь — `SHADOW_BACKFILL_MAX` (400). Бюджет — сквозной: он же ограничивает каждый вызов БД и скачивание внутри строки.
Один проход за раз: `flock` на `SHADOW_BACKFILL_LOCK` (по умолчанию `~/.remlab-shadow-backfill.lock`), а `attempts` растёт не чаще раза в сутки САМ ПО СЕБЕ (SQL `write_fail`:
прибавка только если прошлая запись строки старше `COOLDOWN_S`) — даже без замка два одновременных прохода не посчитают одну неудачу дважды. Проход не пишет в `photo_assessment` и не трогает кэш `<sha>.png`.

  python tools/scout/passport_shadow.py --selftest
"""
import collections
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import mesh_type_passports as MTP  # noqa: E402
import cutout_guards as CG  # noqa: E402

TABLE = 'passport_shadow'
PSQL = ['docker', 'exec', '-i', 'remlab-devdb', 'psql', '-U', 'remlab', '-d', 'remlab', '-q', '-v', 'ON_ERROR_STOP=1', '-t', '-A', '-F', '\x1f']

# закрытый список исходов прохода
RETRY_CODES = ('missing_cache', 'fetch_failed', 'guard_timeout', 'guard_error', 'db_error')
TERMINAL_CODES = ('decode_failed', 'sha_moved')
OUTCOMES = RETRY_CODES + TERMINAL_CODES + ('ambiguous',)
COOLDOWN_S = 24 * 3600


def _env_f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def enabled() -> bool:
    return os.environ.get('PASSPORT_SHADOW', '1') != '0'


def guard_timeout() -> float:
    return _env_f('SHADOW_GUARD_TIMEOUT_S', 30)


def fail_max() -> int:
    return int(_env_f('SHADOW_FAIL_MAX', 20))


def attempts_max() -> int:
    return int(_env_f('SHADOW_ATTEMPTS_MAX', 3))


def db_timeout() -> float:
    return _env_f('SHADOW_DB_TIMEOUT_S', 20)


def observe_timeout() -> float:
    return _env_f('SHADOW_OBSERVE_TIMEOUT_S', 15)


def candidates_timeout() -> float:
    return _env_f('SHADOW_CANDIDATES_TIMEOUT_S', 120)


def fetch_timeout() -> float:
    return _env_f('SHADOW_FETCH_TIMEOUT_S', 45)


def run_budget() -> float:
    return _env_f('SHADOW_RUN_BUDGET_S', 900)


LOCK_WAIT_S = 5          # потолок ожидания блокировки строки/таблицы в самой БД
_DEADLINE: list = [None]   # [monotonic-срок прохода] — сквозной бюджет: ограничивает и каждый вызов БД, и скачивание


def budget_left() -> float | None:
    d = _DEADLINE[0]
    return None if d is None else d - time.monotonic()


def call_bounded(fn, timeout: float, *args):
    """Вызвать `fn(*args)` не дольше `timeout` с (поток-демон: зависший вызов не держит процесс). Таймаут → TimeoutError, исключение вызова — как есть."""
    box: dict = {}

    def run():
        try:
            box['v'] = fn(*args)
        except BaseException as e:  # noqa: BLE001 — переносим в вызвавший поток
            box['e'] = e
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f'вызов не уложился в {timeout:.0f} с')
    if 'e' in box:
        raise box['e']
    return box['v']


class TableMissing(RuntimeError):
    """Таблицы passport_shadow нет (миграция не применена)."""


def next_state(prev: tuple | None, terminal: bool, amax: int) -> tuple:
    """(status, attempts) после СБОЯ попытки. prev = (status, attempts) | None. Терминальный исход или попытка №amax → quarantine."""
    n = (prev[1] if prev else 0) + 1
    return ('quarantine' if terminal or n >= amax else 'retry'), n


# ------------------------------------------------------------------ хранилище
def _q(v) -> str:
    return 'null' if v is None else "'" + str(v).replace("'", "''") + "'"


class PgStore:
    """`passport_shadow` в remlab-devdb через psql (как остальные ночные шаги)."""

    def db(self, sql: str, timeout: float | None = None) -> list:
        """Один вызов psql с ЖЁСТКИМ потолком: `statement_timeout`/`lock_timeout` в сеансе (БД сама отменяет запрос) + `timeout` у подпроцесса (зависший docker/сокет).
        Потолок = min(запрошенный, остаток сквозного бюджета прохода); бюджет исчерпан — RuntimeError без обращения к БД."""
        t = float(db_timeout() if timeout is None else timeout)
        left = budget_left()
        if left is not None:
            if left <= 0:
                raise RuntimeError('shadow_budget: бюджет тени исчерпан')
            t = min(t, left)
        t = max(t, 1.0)
        pre = f"set statement_timeout = {int(t * 1000)}; set lock_timeout = {int(min(t, LOCK_WAIT_S) * 1000)};\n"
        try:
            r = subprocess.run(PSQL, capture_output=True, text=True, input=pre + sql, timeout=t + 5)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f'db_timeout: psql не ответил за {t + 5:.0f} с') from None
        if r.returncode != 0:
            if 'does not exist' in r.stderr and TABLE in r.stderr:
                raise TableMissing(r.stderr[:200])
            raise RuntimeError(r.stderr[:400])
        return [ln.split('\x1f') for ln in r.stdout.strip().split('\n') if ln]

    def write_done(self, sha, role, mv, digest, metrics, verdict) -> None:
        self.db(f"insert into {TABLE} (source_sha, normalized_role, measurement_version, policy_digest, metrics, shadow_verdict, status, attempts, last_error) "
                f"values ({_q(sha)}, {_q(role)}, {_q(mv)}, {_q(digest)}, {_q(json.dumps(metrics, ensure_ascii=False))}::jsonb, {_q(verdict)}, 'done', 0, null) "
                "on conflict (source_sha, normalized_role, measurement_version) do update set "
                "policy_digest = excluded.policy_digest, metrics = excluded.metrics, shadow_verdict = excluded.shadow_verdict, "
                "status = 'done', attempts = 0, last_error = null, updated = now()")

    def write_fail(self, sha, role, mv, digest, code, terminal) -> None:
        """Неудача попытки. `attempts` растёт НЕ ЧАЩЕ раза в `COOLDOWN_S`: прибавка только если прошлая запись строки старше срока — два одновременных прохода
        (или повтор в ту же ночь) посчитают ОДНУ неудачу один раз. Терминальный исход и порог попыток → quarantine."""
        amax = attempts_max()
        first = 'quarantine' if terminal or amax <= 1 else 'retry'
        inc = f"(case when {TABLE}.updated <= now() - interval '{COOLDOWN_S} seconds' then 1 else 0 end)"
        self.db(f"insert into {TABLE} (source_sha, normalized_role, measurement_version, policy_digest, status, attempts, last_error) "
                f"values ({_q(sha)}, {_q(role)}, {_q(mv)}, {_q(digest)}, '{first}', 1, {_q(code)}) "
                "on conflict (source_sha, normalized_role, measurement_version) do update set "
                f"attempts = {TABLE}.attempts + {inc}, last_error = excluded.last_error, policy_digest = excluded.policy_digest, "
                f"status = case when {'true' if terminal else 'false'} or {TABLE}.attempts + {inc} >= {amax} then 'quarantine' else 'retry' end, updated = now() "
                f"where {TABLE}.status <> 'done'")

    def states(self) -> dict:
        rows = self.db(f"select source_sha, normalized_role, measurement_version, status, attempts, "
                       f"extract(epoch from now() - updated)::bigint from {TABLE}")
        return {(r[0], r[1], r[2]): (r[3], int(r[4]), int(r[5])) for r in rows if len(r) == 6}

    def release_quarantine(self) -> int:
        rows = self.db(f"update {TABLE} set status = 'retry', attempts = 0, updated = now() - interval '2 days' where status = 'quarantine' returning 1")
        return len(rows)

    def coverage(self, candidates: list) -> list:
        """[(роль, вырезано всего (уникальных фото среди кандидатов — гостиная и комнаты), done, retry, quarantine)] — для строки охвата ночного отчёта."""
        roles = [r for r, p in MTP.load()['types'].items() if p['cutout']['guards']]
        tot = {r: len({c['sha'] for c in candidates if MTP.normalize(c['role']) == r}) for r in roles}
        out = []
        for r in roles:
            st = self.db(f"select status, count(*) from {TABLE} where normalized_role = {_q(r)} group by 1")
            d = {s[0]: int(s[1]) for s in st if len(s) == 2}
            out.append((r, tot[r], d.get('done', 0), d.get('retry', 0), d.get('quarantine', 0)))
        return out


STORE = PgStore()


# ------------------------------------------------------------------ состояние прогона (one())
class Run:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.ok = 0
        self.fail = 0
        self.skipped = 0
        self.spent = 0.0        # секунд, потраченных тенью в one() за прогон (бюджет SHADOW_RUN_BUDGET_S)
        self.off = False
        self.table_missing = False
        self.codes = collections.Counter()


RUN = Run()
GUARD_CMD = None   # подмена команды дочернего процесса (тесты)


def run_reset() -> None:
    RUN.reset()


def run_line() -> str:
    """Строка ночного отчёта по тени в `one()`."""
    return (f'тень (вырезка): записано {RUN.ok}, сбоев тени {RUN.fail}'
            + (f' {dict(RUN.codes)}' if RUN.codes else '') + (', ВЫКЛЮЧЕНА по SHADOW_FAIL_MAX' if RUN.off else '')
            + (', таблицы passport_shadow нет (миграция 018 не применена)' if RUN.table_missing else ''))


def _count_fail(code: str, what: str) -> None:
    with RUN.lock:
        RUN.fail += 1
        RUN.codes[code] += 1
        n, off_now = RUN.fail, (RUN.fail >= fail_max() and not RUN.off)
        if off_now:
            RUN.off = True
    print(f'WARN:passport_shadow {what}: {code}', flush=True)
    if off_now:
        print(f'WARN:passport_shadow_off: {n} сбоев тени за прогон — тень выключена до конца прогона, вырезка идёт; пропущенное подберёт --shadow-backfill', flush=True)


def final_verdict(role: str, passport: dict, results: dict, metrics: dict | None = None) -> str:
    """Значение `shadow_verdict` строки: `photo_fit.shadow_verdict` (размер → блокирующие метки → мягкие). Ленивый импорт: photo_fit читает асет-стратегии."""
    import photo_fit as PF
    return PF.shadow_verdict(role, metrics, passport, results)[0]


def _write_result(role: str, sha: str, g: dict, passport: dict, m: dict, am_metrics: dict | None, store) -> str:
    v, sub = CG.verdict(g['name'], m, g['thresholds'])
    m = {**m, 'guard_verdict': v}      # метка сторожа (у К3 — мягкая: pattern_free|microtexture|pattern|unmeasured; в shadow_verdict она не входит)
    if sub:
        m['subtype'] = sub
    fv = final_verdict(role, passport, {g['name']: (v, sub)}, am_metrics)
    store.write_done(sha, MTP.normalize(role), g['measurement_version'], MTP.digest_of(passport), m, fv)
    return fv


# ------------------------------------------------------------------ крючок в cutout_sync.one
def after_assessment(role, sku, sha, raw, cut_path, info, store=None) -> list | None:
    """Сторожа паспорта роли после вставки `photo_assessment`. НИКОГДА не бросает. → список вердиктов или None (тень не нужна/выключена).
    `raw` — байты исходника (К1), `cut_path` — вырезка в кэше `<sha>.png`, `info` — метрики цепочки (`photo.object_xy`)."""
    t_start = time.monotonic()
    try:
        if not enabled() or RUN.off or RUN.table_missing:
            return None
        with RUN.lock:
            over = RUN.spent >= run_budget() and not RUN.off
            if over:
                RUN.off = True
        if over:
            print(f'WARN:passport_shadow_off: бюджет тени {run_budget():.0f} с за прогон исчерпан — тень выключена до конца прогона, вырезка идёт; пропущенное подберёт --shadow-backfill', flush=True)
        if RUN.off:
            return None
        store = store or STORE
        passport = MTP.get(role)
        guards = ((passport or {}).get('cutout') or {}).get('guards') or []
        if not guards:
            return None
        out = []
        xy = ((info or {}).get('photo') or {}).get('object_xy')
        with tempfile.TemporaryDirectory(prefix='passport-shadow-') as td:
            src_path = None
            if any(g['needs_source'] for g in guards):
                src_path = os.path.join(td, 'src.bin')
                with open(src_path, 'wb') as f:
                    f.write(raw)
            for g in guards:
                if RUN.off:
                    break
                code, m = CG.run_guard_child(g, cut_path, src_path if g['needs_source'] else None, xy, guard_timeout(), cmd=GUARD_CMD)
                if code != 'ok':
                    _count_fail(code, f'{sku} {g["name"]}')
                    continue
                out.append(_write_result(role, sha, g, passport, m, info, store))
                with RUN.lock:
                    RUN.ok += 1
        return out
    except TableMissing:
        with RUN.lock:
            first = not RUN.table_missing
            RUN.table_missing = True
        if first:
            print('WARN:passport_shadow: таблицы passport_shadow нет (миграция tools/scout/018-passport-shadow.sql не применена) — тень пропущена', flush=True)
        return None
    except Exception as e:  # noqa: BLE001 — сбой тени не должен тронуть вырезку
        _count_fail('shadow_exception', f'{sku}: {type(e).__name__}: {str(e)[:100]}')
        return None
    finally:
        with RUN.lock:
            RUN.spent += time.monotonic() - t_start


# ------------------------------------------------------------------ проход по тёплой части
def plan_backfill(candidates: list, states: dict, now_cooldown: int = COOLDOWN_S, reg: dict | None = None, limit: int | None = None) -> list:
    """Чистая функция: кандидаты [{sha, role, url, room}] + состояния {(sha, роль, версия): (status, attempts, age_s)} → упорядоченный список работ.
    Порядок: без строки (спальня раньше, внутри — по sha), затем retry по старшему updated; done/quarantine и retry раньше суток или с attempts ≥ max — мимо."""
    reg = reg or MTP.load()
    amax = attempts_max()
    new, retry, seen = [], [], set()
    for c in candidates:
        t = MTP.normalize(c['role'], reg)
        p = reg['types'].get(t) if t else None
        for g in ((p or {}).get('cutout') or {}).get('guards') or ():
            key = (c['sha'], t, g['measurement_version'])
            if key in seen:
                continue
            seen.add(key)
            job = {**c, 'norm': t, 'guard': g, 'passport': p, 'key': key}
            st = states.get(key)
            if st is None:
                new.append(job)
            elif st[0] == 'retry' and st[1] < amax and st[2] >= now_cooldown:
                retry.append((st[2], job))
    new.sort(key=lambda j: (j.get('room') != 'bedroom', j['sha']))
    retry.sort(key=lambda x: -x[0])
    jobs = new + [j for _, j in retry]
    return jobs[:limit] if limit is not None else jobs


def process_one(job: dict, cache_dir: str, fetch, store, am_metrics: dict | None = None) -> tuple:
    """Одна строка прохода → (исход, вердикт|None). Исход — из закрытого списка OUTCOMES или 'ok'/вердикт-метка. Пишет ТОЛЬКО в passport_shadow."""
    sha, g, p, role = job['sha'], job['guard'], job['passport'], job['role']
    norm, mv, dg = job['norm'], g['measurement_version'], MTP.digest_of(job['passport'])
    cut_path = os.path.join(cache_dir, sha + '.png')

    def fail(code):
        try:
            store.write_fail(sha, norm, mv, dg, code, code in TERMINAL_CODES)
        except TableMissing:
            raise
        except Exception:  # noqa: BLE001 — БД не приняла и отказ: строка подождёт следующей ночи
            return 'db_error', None
        return code, None
    if not os.path.exists(cut_path):
        return fail('missing_cache')
    with tempfile.TemporaryDirectory(prefix='passport-backfill-') as td:
        src_path = None
        if g['needs_source']:
            try:
                left = budget_left()
                raw = call_bounded(fetch, fetch_timeout() if left is None else max(1.0, min(fetch_timeout(), left)), job['url'])
            except Exception:  # noqa: BLE001 — сеть, HTTP, таймаут (в т.ч. «капающий» ответ дольше потолка)
                return fail('fetch_failed')
            if hashlib.sha256(raw).hexdigest() != sha:
                return fail('sha_moved')
            src_path = os.path.join(td, 'src.bin')
            with open(src_path, 'wb') as f:
                f.write(raw)
        code, m = CG.run_guard_child(g, cut_path, src_path, None, guard_timeout(), cmd=GUARD_CMD)
        if code != 'ok':
            return fail(code)
        try:
            fv = _write_result(role, sha, g, p, m, am_metrics, store)
        except TableMissing:
            raise
        except Exception:  # noqa: BLE001
            return 'db_error', None
    return ('ambiguous' if fv == 'ambiguous' else 'ok'), fv


def lock_path() -> str:
    return os.environ.get('SHADOW_BACKFILL_LOCK') or os.path.expanduser('~/.remlab-shadow-backfill.lock')


def backfill(candidates: list, cache_dir: str, fetch, store=None, budget_s: float | None = None, streak_max: int | None = None,
             limit: int | None = None, clock=time.monotonic) -> dict:
    """Проход по уже вырезанному под ЗАМКОМ (один проход за раз) и со СКВОЗНЫМ бюджетом (он ограничивает и каждый вызов БД, и скачивание). → отчёт
    {selected, done, outcomes, retry, quarantine, seconds, stop}. Не бросает наружу (кроме отсутствия таблицы — тогда stop). Замок занят — выход без работы:
    второй проход не дублирует скачивания и расчёты (а `attempts` и без замка не удваивается — SQL `write_fail`)."""
    budget = _env_f('SHADOW_BACKFILL_BUDGET_S', 1800) if budget_s is None else budget_s
    try:
        fd = os.open(lock_path(), os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:     # нет места под замок — работать без него безопаснее, чем не работать: SQL всё равно не удвоит попытки
        print(f'WARN:passport_backfill: замок прохода не открыт ({type(e).__name__}) — идём без замка', flush=True)
        fd = None
    try:
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                print('проход тени: другой проход уже идёт — выходим без работы', flush=True)
                return {'selected': 0, 'done': 0, 'outcomes': collections.Counter(), 'retry': 0, 'quarantine': 0, 'seconds': 0.0, 'stop': 'другой проход уже идёт'}
        _DEADLINE[0] = time.monotonic() + budget
        return _backfill(candidates, cache_dir, fetch, store, budget, streak_max, limit, clock)
    finally:
        _DEADLINE[0] = None
        if fd is not None:
            os.close(fd)      # закрытие снимает flock


def _backfill(candidates: list, cache_dir: str, fetch, store, budget: float, streak_max: int | None, limit: int | None, clock) -> dict:
    store = store or STORE
    rep = {'selected': 0, 'done': 0, 'outcomes': collections.Counter(), 'retry': 0, 'quarantine': 0, 'seconds': 0.0, 'stop': None}
    t0 = clock()
    smax = int(_env_f('SHADOW_BACKFILL_STREAK_MAX', 15)) if streak_max is None else streak_max
    lim = int(_env_f('SHADOW_BACKFILL_MAX', 400)) if limit is None else limit
    if not enabled():
        rep['stop'] = 'PASSPORT_SHADOW=0'
        return rep
    try:
        jobs = plan_backfill(candidates, store.states(), limit=lim)
    except TableMissing:
        rep['stop'] = 'нет таблицы passport_shadow (миграция 018 не применена)'
        print('WARN:passport_shadow: таблицы passport_shadow нет — проход пропущен', flush=True)
        return rep
    except Exception as e:  # noqa: BLE001
        rep['stop'] = f'состояние не прочитано: {type(e).__name__}'
        print(f'WARN:passport_backfill_stop code=state {type(e).__name__}: {str(e)[:100]}', flush=True)
        return rep
    rep['selected'] = len(jobs)
    streak_code, streak = None, 0
    for job in jobs:
        if clock() - t0 >= budget:
            rep['stop'] = 'бюджет времени'
            break
        try:
            code, _v = process_one(job, cache_dir, fetch, store, job.get('metrics'))
        except TableMissing:
            rep['stop'] = 'нет таблицы passport_shadow'
            break
        except Exception as e:  # noqa: BLE001 — своя строка не должна остановить проход
            code = 'guard_error'
            print(f'WARN:passport_backfill: {type(e).__name__}: {str(e)[:100]}', flush=True)
        rep['outcomes'][code] += 1
        if code in ('ok', 'ambiguous'):
            rep['done'] += 1
            streak_code, streak = None, 0
        elif code in TERMINAL_CODES:
            rep['quarantine'] += 1
            streak_code, streak = None, 0
        else:   # retry-исход
            rep['retry'] += 1
            streak = streak + 1 if code == streak_code else 1
            streak_code = code
            if streak >= smax:
                rep['stop'] = f'{streak} подряд сбоев {code}'
                print(f'WARN:passport_backfill_stop code={code}', flush=True)
                break
    rep['seconds'] = round(clock() - t0, 1)
    return rep


def report_text(rep: dict) -> str:
    oc = ', '.join(f'{k} {v}' for k, v in sorted(rep['outcomes'].items())) or '—'
    s = (f"проход тени: выбрано {rep['selected']}, done {rep['done']}, retry {rep['retry']}, quarantine {rep['quarantine']}, "
         f"исходы [{oc}], {rep['seconds']} с" + (f", остановка: {rep['stop']}" if rep['stop'] else ''))
    if rep['selected'] and rep['quarantine'] / rep['selected'] > 0.02:
        s += ' ❗ quarantine > 2 % выбранных'
    return s


def default_candidates(assessor: str, db) -> list:
    """Кандидаты прохода из БД: гостиная (`products`) и комнаты (`photo_hash.pick_rooms`), уже оценённые текущим оценщиком, роли со сторожами паспорта."""
    import photo_hash as PH
    reg = MTP.load()
    names = {n for n, p in reg['types'].items() if p['cutout']['guards']} | {a for n, p in reg['types'].items() if p['cutout']['guards'] for a in p.get('aliases') or ()}
    lst = ','.join(_q(n) for n in sorted(names))
    out = []
    for r in db("select c.source_sha, regexp_replace(coalesce(p.cat_role, ''), '\\s+\\d+$', ''), c.image_url "
                "from product_photo_current c join products p on p.shop_mid||':'||p.external_id = c.sku "
                f"join photo_assessment a on a.source_sha = c.source_sha and a.assessor_version = {_q(assessor)} "
                f"where c.source_sha is not null and regexp_replace(coalesce(p.cat_role, ''), '\\s+\\d+$', '') in ({lst})"):
        if len(r) == 3:
            out.append({'sha': r[0], 'role': r[1], 'url': r[2], 'room': 'living'})
    picked, _ = PH.pick_rooms(PH.parse_room_rows(db(PH.rooms_rows_sql(assessor))))
    for t in picked:
        if t['sha'] and t['verdict'] and MTP.normalize(t['role']) in {MTP.normalize(n) for n in names}:
            out.append({'sha': t['sha'], 'role': t['role'], 'url': t['url'], 'room': t['room']})
    return out


def run_backfill(assessor: str, cache_dir: str, fetch, db=None) -> dict:
    """Точка входа `cutout_sync.py --shadow-backfill`: кандидаты из БД → проход → строка отчёта и охват. Не бросает.
    `db=None` — запросы кандидатов идут через `STORE.db` с жёстким потолком `SHADOW_CANDIDATES_TIMEOUT_S`."""
    try:
        cands = default_candidates(assessor, db or (lambda sql: STORE.db(sql, timeout=candidates_timeout())))
    except Exception as e:  # noqa: BLE001
        print(f'WARN:passport_backfill_stop code=candidates {type(e).__name__}: {str(e)[:100]}', flush=True)
        return {'selected': 0, 'done': 0, 'outcomes': collections.Counter(), 'retry': 0, 'quarantine': 0, 'seconds': 0, 'stop': 'кандидаты не получены'}
    rep = backfill(cands, cache_dir, fetch)
    print(report_text(rep), flush=True)
    try:
        for role, tot, done, retry, quar in STORE.coverage(cands):
            print(f'охват тени «{role}»: вырезано {tot}, в тени {done}, ждут повтора {retry}, карантин {quar}', flush=True)
    except Exception as e:  # noqa: BLE001
        print(f'охват тени не получен ({type(e).__name__})', flush=True)
    return rep


def current_policy() -> dict:
    """{(нормализованная роль, версия замера): хеш паспорта} — ТЕКУЩИЕ сторожа реестра. Строка тени годна гейту только если её ключ и хеш отсюда."""
    reg = MTP.load()
    return {(t, g['measurement_version']): MTP.digest_of(p) for t, p in reg['types'].items() for g in p['cutout']['guards']}


def observe_gate(items: dict, db=None) -> None:
    """Гейт паспорта в `observe` на платном входе: items SKU→роль. Считает «заблокировал бы» (роли без паспорта — `would_block:no_passport`; вердикт тени
    не `ok` у блокирующего сторожа — `would_block:<вердикт>`). РЕШЕНИЕ ИГНОРИРУЕТСЯ: вход, очередь, ключи заданий и экспорт не меняются ни на байт.
    Вердикты тени читаются ОДНИМ запросом с жёстким потолком `SHADOW_OBSERVE_TIMEOUT_S` (по умолчанию через `STORE.db`); нет таблицы/сбой/таймаут чтения — гейт
    идёт без вердиктов (одна WARN), роли без паспорта считаются всё равно. Строка тени учитывается ТОЛЬКО если: роль строки = нормализованная роль ЭТОГО товара,
    версия замера и `policy_digest` — текущие у паспорта (старые версии остаются в таблице намеренно, но гейту не отвечают; устаревший хеш — счётчик
    `shadow_stale_digest`, его чинит `photo_fit.shadow_reverdict`). Из нескольких годных строк берётся первая по (роль, версия) — выбор детерминирован."""
    blocked = {}
    try:
        cur = current_policy()
        keys = ', '.join(f"({_q(t)}, {_q(v)})" for t, v in sorted(cur))
        if keys:
            run = db or (lambda sql: STORE.db(sql, timeout=observe_timeout()))
            for r in run("select d.sku, s.normalized_role, s.measurement_version, s.policy_digest, s.shadow_verdict from mesh_demand d "
                         f"join {TABLE} s on s.source_sha = d.source_sha and s.status = 'done' "
                         "where d.status = 'wanted' and s.shadow_verdict is not null and s.shadow_verdict <> 'ok' "
                         f"and (s.normalized_role, s.measurement_version) in ({keys}) "
                         "order by d.sku, s.normalized_role, s.measurement_version"):
                if len(r) != 5 or r[0] in blocked or r[0] not in items:
                    continue
                sku, nrole, mv, dg, verdict = r
                if MTP.normalize(items[sku]) != nrole:
                    continue
                if (nrole, mv) not in cur:      # старая версия замера: в таблице остаётся намеренно, гейту не отвечает (SQL её тоже не вернёт — это страховка)
                    continue
                if cur[(nrole, mv)] != dg:
                    MTP.STATS['shadow_stale_digest'] += 1
                    continue
                blocked[sku] = verdict
    except Exception as e:  # noqa: BLE001
        MTP.warn_once('shadow_read', f'WARN:passport_shadow: вердикты тени не прочитаны ({type(e).__name__}) — гейт без них (observe)')
    for sku, role in items.items():
        MTP.gate(role, 'observe', blocked.get(sku))


def timed_db(sql: str) -> list:
    """Запрос через `STORE.db` с потолком `SHADOW_DB_TIMEOUT_S` — для мест вне модуля (`mesh_scheduler._stamp_digest`)."""
    return STORE.db(sql)


def _selftest() -> int:
    """Самотесты тени живут в tests/test_mesh_type_passports.py; здесь — чистые правила состояния и порядка."""
    bad = 0

    def ok(name: str, cond: bool) -> None:
        nonlocal bad
        print(('  ✓ ' if cond else '  ✗ ') + name)
        bad += 0 if cond else 1
    ok('1-я неудача retry, 3-я quarantine, терминальная сразу quarantine',
       next_state(None, False, 3) == ('retry', 1) and next_state(('retry', 2), False, 3) == ('quarantine', 3) and next_state(None, True, 3) == ('quarantine', 1))
    ok('закрытый список исходов: 8 кодов, без повторов', len(OUTCOMES) == len(set(OUTCOMES)) == 8)
    print(f'passport_shadow selftest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        raise SystemExit(_selftest())
    print(__doc__)

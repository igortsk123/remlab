#!/usr/bin/env python3
"""Миграция 018 и SQL тени на НАСТОЯЩЕМ Postgres (pakardev) — T-20261120-151/6. НИЧЕГО не сохраняет: весь сценарий — в ОДНОЙ транзакции с `rollback`.

Что проверяется: файл `018-passport-shadow.sql` применим и идемпотентен (второй прогон — без ошибок); настоящие запросы `PgStore` (`write_done`, `write_fail`,
`states`, `release_quarantine`, `observe_gate`-выборка) делают то, что обещает шапка `passport_shadow.py`: ключ (sha, роль, версия), done не затирается отказом,
`attempts` растёт, 3-я неудача и терминальный исход → quarantine, возврат карантина. Колонка `mesh_jobs.passport_digest` добавляется на ВРЕМЕННУЮ копию
таблицы (`create temp table mesh_jobs … like`) — боевая `mesh_jobs` не затрагивается даже внутри транзакции.
В CI не идёт (нужна база); запуск: `r python3 tools/scout/tests/passport_shadow_dbtest.py`."""
import os
import subprocess
import sys

SCOUT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCOUT)
import remlab_tmp  # noqa: E402
remlab_tmp.use('passport_shadow_dbtest')
import passport_shadow as PS  # noqa: E402

bad = 0


def ok(name, cond, extra=''):
    global bad
    print(('  ✓ ' if cond else '  ✗ ') + name + (f' — {extra}' if extra and not cond else ''))
    bad += 0 if cond else 1


class Recorder(PS.PgStore):
    """Настоящие методы PgStore, но `db` не выполняет, а складывает SQL (потом всё — в одну транзакцию)."""

    def __init__(self):
        self.sql = []

    def db(self, sql, timeout=None):
        self.sql.append(sql.strip().rstrip(';'))
        return []


def main():
    mig = open(os.path.join(SCOUT, '018-passport-shadow.sql'), encoding='utf-8').read()
    r = Recorder()
    A, B, C = 'a' * 64, 'b' * 64, 'c' * 64
    AGE = "update passport_shadow set updated = updated - interval '2 days' where source_sha = '%s'"       # транзакция живёт в одном now(): «прошли сутки» — сдвигом updated
    r.write_fail(A, 'подушка', 'k3.v1', 'dg', 'missing_cache', False)      # 1-я неудача → retry/1
    r.sql.append("select 'S1', status, attempts, last_error from passport_shadow where source_sha = '%s'" % A)
    r.write_fail(A, 'подушка', 'k3.v1', 'dg', 'missing_cache', False)      # тот же момент (параллельный проход / повтор в ту же ночь) → остаётся 1
    r.write_fail(A, 'подушка', 'k3.v1', 'dg', 'missing_cache', False)
    r.sql.append("select 'S1b', status, attempts from passport_shadow where source_sha = '%s'" % A)
    r.sql.append(AGE % A)
    r.write_fail(A, 'подушка', 'k3.v1', 'dg', 'missing_cache', False)      # на следующую ночь → retry/2
    r.sql.append("select 'S1c', status, attempts from passport_shadow where source_sha = '%s'" % A)
    r.sql.append(AGE % A)
    r.write_fail(A, 'подушка', 'k3.v1', 'dg', 'guard_timeout', False)      # ещё ночь → quarantine/3
    r.sql.append("select 'S2', status, attempts, last_error from passport_shadow where source_sha = '%s'" % A)
    r.write_fail(B, 'кровать', 'k1.v1', 'dg', 'decode_failed', True)       # терминальный → quarantine/1 сразу
    r.sql.append("select 'S3', status, attempts from passport_shadow where source_sha = '%s'" % B)
    r.write_done(C, 'кровать', 'k1.v1', 'dg', {'registered': True, 'comps': []}, 'ok')
    r.write_fail(C, 'кровать', 'k1.v1', 'dg', 'fetch_failed', False)       # отказ поверх done — не затирает
    r.sql.append("select 'S4', status, attempts, shadow_verdict, metrics->>'registered' from passport_shadow where source_sha = '%s'" % C)
    r.write_done(A, 'подушка', 'k3.v1', 'dg2', {'p95_total': 1.0}, 'ok')   # успешная попытка после карантина — done, ошибка и attempts сброшены
    r.sql.append("select 'S5', status, last_error is null, policy_digest, attempts from passport_shadow where source_sha = '%s'" % A)
    r.write_done(A, 'подушка', 'k3.v2', 'dg2', {'p95_total': 1.0}, 'ok')   # другая версия замера — новая строка
    r.sql.append("select 'S6', count(*) from passport_shadow where source_sha = '%s'" % A)
    r.sql.append("select 'S7', count(*) from passport_shadow where status = 'quarantine'")
    r.release_quarantine()
    r.sql.append("select 'S8', status, attempts from passport_shadow where source_sha = '%s'" % B)
    r.sql.append("select 'S9', count(*) from (select source_sha, normalized_role, measurement_version, status, attempts, extract(epoch from now() - updated)::bigint from passport_shadow) t")
    # выборка observe_gate — НАСТОЯЩИЙ SQL из кода, на временной копии mesh_demand: берёт только текущую пару (роль, версия), done, не ok; порядок детерминирован
    seen = []
    MTP = PS.MTP
    cur = PS.current_policy()
    PS.observe_gate({'T1': 'кровать', 'T2': 'подушка'}, db=lambda sql: seen.append(sql) or [])
    gate_sql = seen[0] if seen else ''
    D, E = 'd' * 64, 'e' * 64
    fixture = [
        "create temp table mesh_demand (like mesh_demand including all)",
        "insert into mesh_demand (sku, role, priority, source_sha) values ('T1', 'кровать', 1, '%s'), ('T2', 'подушка', 1, '%s')" % (D, E),
        "insert into passport_shadow (source_sha, normalized_role, measurement_version, policy_digest, shadow_verdict, status) values "
        "('%s', 'кровать', 'k1.v0', 'x', 'headboard_loss', 'done'), "          # старая версия — не отвечает
        "('%s', 'кровать', 'k1.v1', 'x', 'headboard_loss', 'done'), "          # годная пара
        "('%s', 'подушка', 'k3.v1', 'x', 'ok', 'done')" % (D, D, E),            # ok — блокирующим не является
    ]
    r.sql.extend(fixture)
    # --check миграции: точная схема. Строка берётся из самого файла 018 (то, что получит db-migrate-safe); mesh_jobs в тесте — временная копия, поэтому её схема подменяется на pg_temp
    chk = next(ln for ln in mig.splitlines() if ln.startswith('--     "(select'))[len('--     "'):-1]
    chk_t = chk.replace("table_schema='public' and table_name='mesh_jobs'", "table_schema like 'pg_temp%' and table_name='mesh_jobs'")
    blk = ["select 'C1', (%s)" % chk_t]      # блок идёт В НАЧАЛО сценария: на пустой таблице поломки схемы (set not null и др.) выполнимы
    for tag, brk in (('C2', "alter table passport_shadow alter column metrics set not null"),
                     ('C3', "alter table passport_shadow alter column attempts set default 5"),
                     ('C4', "alter table passport_shadow alter column last_error type varchar"),
                     ('C5', "drop index passport_shadow_status_idx"),
                     ('C6', "alter table passport_shadow drop constraint passport_shadow_status_check"),
                     ('C7', "alter table passport_shadow drop constraint passport_shadow_pkey, add primary key (normalized_role, source_sha, measurement_version)")):
        blk += ["savepoint sp", brk, "select '%s', (%s)" % (tag, chk_t), "rollback to savepoint sp"]
    r.sql[0:0] = blk
    r.sql.append("select 'G', d.sku, s.measurement_version from (" + gate_sql.rstrip().rstrip(';') + ") q(sku, nrole, mv, dg, verdict) join mesh_demand d on d.sku = q.sku join passport_shadow s on s.source_sha = d.source_sha and s.measurement_version = q.mv and s.normalized_role = q.nrole")
    r.sql.append("select 'GN', count(*) from (" + gate_sql.rstrip().rstrip(';') + ") q")
    script = '\n'.join([
        'begin;',
        "create temp table mesh_jobs (like mesh_jobs including all);",     # временная копия перекрывает боевую в этом сеансе
        mig,
        mig,                                                                # идемпотентность: второй прогон без ошибок
        "select 'M1', count(*) from information_schema.columns where table_name='mesh_jobs' and column_name='passport_digest' and table_schema like 'pg_temp%';",
    ] + [s + ';' for s in r.sql] + [
        "select 'M2', count(*) from pg_indexes where tablename='passport_shadow';",
        'rollback;', ''])
    p = subprocess.run(PS.PSQL, input=script, capture_output=True, text=True)
    err = p.stderr.strip()
    ok('сценарий выполнен без ошибок SQL', p.returncode == 0 and 'ERROR' not in err, err[:300])
    rows = [ln.split('\x1f') for ln in p.stdout.strip().split('\n') if ln]
    g = lambda tag: [x for x in rows if x and x[0] == tag]
    ok('миграция: колонка passport_digest добавлена (на временную копию mesh_jobs)', g('M1') == [['M1', '1']], str(g('M1')))
    ok('миграция: ключ и два индекса таблицы тени на месте (3 индекса вместе с pkey)', g('M2') == [['M2', '3']], str(g('M2')))
    ok('1-я неудача: retry, attempts 1', g('S1') == [['S1', 'retry', '1', 'missing_cache']], str(g('S1')))
    ok('две ещё записи в тот же момент (параллельный проход): attempts остаётся 1', g('S1b') == [['S1b', 'retry', '1']], str(g('S1b')))
    ok('на следующую ночь: attempts 2, всё ещё retry', g('S1c') == [['S1c', 'retry', '2']], str(g('S1c')))
    ok('3-я ночь: quarantine, attempts 3, ошибка последняя', g('S2') == [['S2', 'quarantine', '3', 'guard_timeout']], str(g('S2')))
    ok('терминальный исход: quarantine сразу', g('S3') == [['S3', 'quarantine', '1']], str(g('S3')))
    ok('отказ поверх done не затирает строку', g('S4') == [['S4', 'done', '0', 'ok', 'true']], str(g('S4')))
    ok('успех после карантина: done, ошибка сброшена, digest обновлён', g('S5') == [['S5', 'done', 't', 'dg2', '0']], str(g('S5')))
    ok('другая версия замера — отдельная строка (2 строки у sha)', g('S6') == [['S6', '2']], str(g('S6')))
    ok('до возврата в карантине одна строка (B); у A уже done', g('S7') == [['S7', '1']], str(g('S7')))
    ok('release_quarantine: B снова retry, attempts 0', g('S8') == [['S8', 'retry', '0']], str(g('S8')))
    ok('states() читается', g('S9') == [['S9', '4']], str(g('S9')))
    ok('--check миграции на правильной схеме = true', g('C1') == [['C1', 't']], str(g('C1')))
    for tag, what in (('C2', 'metrics NOT NULL'), ('C3', 'default attempts'), ('C4', 'тип last_error'), ('C5', 'нет индекса status'),
                      ('C6', 'нет ограничения status'), ('C7', 'порядок колонок PK')):
        ok(f'--check ловит поломку схемы: {what}', g(tag) == [[tag, 'f']], str(g(tag)))
    ok('выборка гейта: ровно одна строка — текущая пара (k1.v1, не ok); старая версия и ok не отвечают', g('GN') == [['GN', '1']] and g('G') == [['G', 'T1', 'k1.v1']], str(g('GN')) + str(g('G')))
    chk = subprocess.run(PS.PSQL, input="select count(*) from information_schema.tables where table_name='passport_shadow' and table_schema not like 'pg_temp%';",
                         capture_output=True, text=True)
    ok('после rollback в базе ничего не осталось (таблицы тени нет, пока миграцию не применит db-migrate-safe)',
       chk.stdout.strip() == '0', chk.stdout.strip())
    print(f'passport_shadow_dbtest: ошибок {bad}')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())

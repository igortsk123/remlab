-- КАТАЛОЖНАЯ миграция дев-БД `remlab-devdb` (применять ТОЛЬКО `tools/ops/db-migrate-safe.sh` со слова владельца, P-036; здесь — ФАЙЛ, не применялась).
-- ТЕНЬ паспортов типов (план mesh-type-passports-01 v5, фаза 1, T-20261120-151/6). Две вещи, обе только добавляют:
--  1) `passport_shadow` — вердикты сторожей К1/К3 «как бы вынес паспорт». Пишут ТОЛЬКО `passport_shadow.py` (в `cutout_sync.one` и `--shadow-backfill`)
--     и `photo_fit.shadow_reverdict`; НЕ читает никто из очереди мешей/экспорта/рендера (тень ничего не блокирует). Ключ строки — (source_sha, роль, версия замера):
--     смена версии замера (`k1.v2`) = новая строка, старые остаются. `status`: done | retry | quarantine; `attempts`/`last_error` — состояние ночного прохода
--     (закрытый список исходов в шапке `passport_shadow.py`). Строка без метрик (`metrics` null) — запись об отказе попытки.
--  2) `mesh_jobs.passport_digest` — хеш паспорта типа на момент создания задания (для наблюдения; в ключ задания НЕ входит, колонка пишется отдельным update).
-- Без таблицы/колонки код пишет одну строку `WARN:passport_shadow` и пропускает тень (тест «без таблицы»).
-- ОТКАТ (данных вне тени нет): drop table if exists passport_shadow; alter table mesh_jobs drop column if exists passport_digest;
-- ПЕРЕД применением (db-migrate-safe делает сам): pause шагов, `pg_dump` devdb, затем проверка:
--   tools/ops/db-migrate-safe.sh tools/scout/018-passport-shadow.sql --check \
--     "(select count(*) from information_schema.tables where table_name='passport_shadow')=1 and (select count(*) from information_schema.columns where table_name='mesh_jobs' and column_name='passport_digest')=1 and (select count(*) from information_schema.columns where table_name='passport_shadow')=11 and (select count(*) from information_schema.key_column_usage k join information_schema.table_constraints c on c.constraint_name=k.constraint_name and c.table_name=k.table_name where c.table_name='passport_shadow' and c.constraint_type='PRIMARY KEY')=3"
-- ЖЁСТКИЕ ПОТОЛКИ ожидания (проверка Codex T-151/6, п.6): `alter table mesh_jobs` берёт ACCESS EXCLUSIVE — без потолка случайная долгая транзакция
-- подвесила бы выкатку. Не дождались замка за 5 с → миграция откатывается целиком (db-migrate-safe: --single-transaction), безопасно повторить позже.
set lock_timeout = '5s';
set statement_timeout = '60s';
create table if not exists passport_shadow (
    source_sha          text        not null,
    normalized_role     text        not null,
    measurement_version text        not null,
    policy_digest       text        not null,
    metrics             jsonb,
    shadow_verdict      text,
    status              text        not null default 'done' check (status in ('done', 'retry', 'quarantine')),
    attempts            integer     not null default 0,
    last_error          text,
    created             timestamptz not null default now(),
    updated             timestamptz not null default now(),
    primary key (source_sha, normalized_role, measurement_version)
);
create index if not exists passport_shadow_status_idx on passport_shadow (status, updated);
create index if not exists passport_shadow_role_verdict_idx on passport_shadow (normalized_role, shadow_verdict) where status = 'done';
alter table mesh_jobs add column if not exists passport_digest text;

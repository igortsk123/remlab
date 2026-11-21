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
--     "(select string_agg(column_name||':'||data_type||':'||is_nullable||':'||coalesce(column_default,''), ',' order by column_name) from information_schema.columns where table_schema='public' and table_name='passport_shadow')='attempts:integer:NO:0,created:timestamp with time zone:NO:now(),last_error:text:YES:,measurement_version:text:NO:,metrics:jsonb:YES:,normalized_role:text:NO:,policy_digest:text:NO:,shadow_verdict:text:YES:,source_sha:text:NO:,status:text:NO:''done''::text,updated:timestamp with time zone:NO:now()' and (select string_agg(a.attname, ',' order by k.ord) from pg_index i join pg_class c on c.oid=i.indrelid join pg_namespace n on n.oid=c.relnamespace cross join lateral unnest(i.indkey) with ordinality k(attnum, ord) join pg_attribute a on a.attrelid=c.oid and a.attnum=k.attnum where n.nspname='public' and c.relname='passport_shadow' and i.indisprimary)='source_sha,normalized_role,measurement_version' and (select count(*) from pg_constraint where conrelid='public.passport_shadow'::regclass and contype='c' and pg_get_constraintdef(oid) like '%status%done%retry%quarantine%')=1 and (select count(*) from pg_indexes where schemaname='public' and tablename='passport_shadow' and indexdef like '%passport_shadow_status_idx%(status, updated)')=1 and (select count(*) from pg_indexes where schemaname='public' and tablename='passport_shadow' and indexdef like '%passport_shadow_role_verdict_idx%(normalized_role, shadow_verdict)%WHERE%status%done%')=1 and (select count(*) from information_schema.columns where table_schema='public' and table_name='mesh_jobs' and column_name='passport_digest' and data_type='text')=1"
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

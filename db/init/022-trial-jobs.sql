-- Проба для агентов UK (план agent-trial-01-upload-grey-tour, T-A; поправки Codex 09.11): загрузка плана → задание в
-- Postgres прода → воркер DEV забирает его по HTTPS (claim/heartbeat/result/fail, Bearer TRIAL_WORKER_TOKEN) → JSON
-- результата здесь же. Очередь — только Postgres: `FOR UPDATE SKIP LOCKED`, аренда (lease) + heartbeat, без LISTEN/NOTIFY.
--
-- ОГРАЖДЕНИЕ: каждый claim делает attempt+1 и выдаёт новый случайный lease_token; heartbeat/result/fail принимаются одним
-- UPDATE … WHERE status='running' AND attempt=? AND lease_token=? AND lease_until>now(). Ровно max_attempts claim-ов.
-- ПДн и сроки (ICO: storage limitation / minimisation): email и ip_hash НЕ храним (email — в T9, лимитер ведёт свои
-- счётчики); исходный файл живёт до expires_at (30 дн. после финального статуса — с 10.11, 027), результат — до result_expires_at (30 дн.),
-- потом строка — «надгробие» status='expired' без данных (страница отвечает 410). Файл — на томе, в базе только имя.
-- Файл применяется на КАЖДОМ деплое — всё идемпотентно. Откат (только руками, после pg_dump):
--   drop table if exists trial_jobs; drop table if exists trial_workers;

create table if not exists trial_jobs (
  id text primary key,                                -- публичный ключ ссылки /try/<id> (lib/token.ts:randomToken, 128 бит)
  kind text not null default 'floorplan',
  status text not null default 'queued',
  stage text not null default 'queued',
  stages jsonb not null default '[]'::jsonb,          -- [{stage, at}] — время ставит прод по heartbeat
  attempt integer not null default 0,                 -- номер поколения аренды (claim → +1)
  max_attempts integer not null default 2,
  next_run_at timestamptz not null default now(),
  lease_until timestamptz,
  lease_token text,
  worker_id text,
  heartbeat_at timestamptz,
  input_hash text,                                    -- sha256(файл + текст объявления): кэш VLM/растра на DEV
  input_path text,                                    -- ТОЛЬКО имя файла в TRIAL_DIR (<id>.<ext>); null — файл удалён
  input_mime text not null,
  input_bytes integer not null,
  input_deleted_at timestamptz,
  listing_text text,
  consent_version text,
  budget_usd numeric(8, 4) not null default 0.10,
  spent_usd numeric(8, 4) not null default 0,
  error_code text,
  error_detail text,                                  -- только для разбора; наружу не отдаётся
  result jsonb,
  result_hash text,                                   -- sha256 тела результата: повтор того же result — 200, другой — 409
  result_version integer not null default 0,          -- → ETag ответа результата
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  expires_at timestamptz,                             -- когда удалить исходный файл (ставится при финальном статусе)
  result_expires_at timestamptz,                      -- когда снять результат (→ 410)
  constraint trial_jobs_status_chk check (status in ('queued', 'running', 'done', 'failed', 'cancelled', 'expired')),
  constraint trial_jobs_stage_chk check (stage in ('queued', 'raster', 'labels', 'walls', 'repair', 'export', 'done')),
  constraint trial_jobs_listing_len check (listing_text is null or char_length(listing_text) <= 5000),
  constraint trial_jobs_detail_len check (error_detail is null or char_length(error_detail) <= 2000),
  constraint trial_jobs_input_path_chk check (input_path is null or input_path ~ '^[A-Za-z0-9_-]{22}\.(jpg|png|webp|pdf)$')
);
create index if not exists trial_jobs_queue_idx on trial_jobs (status, next_run_at);
create index if not exists trial_jobs_lease_idx on trial_jobs (lease_until) where status = 'running';
create index if not exists trial_jobs_hash_idx on trial_jobs (input_hash);
create index if not exists trial_jobs_expires_idx on trial_jobs (expires_at) where input_path is not null;
create index if not exists trial_jobs_result_expires_idx on trial_jobs (result_expires_at);
create index if not exists trial_jobs_created_idx on trial_jobs (created_at);

-- «Жив ли воркер» для честного статуса страницы: last_seen обновляется на КАЖДОМ опросе (и когда воркер сам себя
-- притормозил). Причина торможения — в журналах DEV, не здесь.
create table if not exists trial_workers (
  id text primary key,
  last_seen timestamptz not null default now(),
  version text
);

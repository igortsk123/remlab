-- Проба для агентов: «Обустроить» / «Обустроить всё» как есть (план agent-trial-08, задача Р1; T-20261109-27). Комнаты, которые ждут
-- проверки размера (`awaiting_check`), агент обставляет сам: кнопка → строка очереди `trial_rebuilds` → воркер DEV прогоняет конвейер мебели
-- по сохранённому `trial_jobs.result` → ОДНА новая версия данных страницы. Задание `trial_jobs` остаётся `done`.
--
-- Право агента — ключ правки: случайный, выдаётся один раз (ответ загрузки и ссылка агента), в базе — только sha256 (`edit_key_hash`).
-- Старые задания без ключа — только просмотр. `released_rooms` — накопленный набор комнат (id страницы), с которых агент снял проверку:
-- следующая пересборка ведёт их обычным путём, не теряя прежних.
-- ОГРАЖДЕНИЕ как у заданий (`022`): claim → attempt+1 и новый lease_token; heartbeat/publish/fail — одним UPDATE/под замком с проверкой
-- status='running' AND attempt AND lease_token AND lease_until>now(). `request_id` от клиента — повтор нажатия возвращает ту же строку.
-- Одна активная (queued|running) на задание — частичный уникальный индекс. Файл применяется на КАЖДОМ деплое — всё идемпотентно.
-- Откат (только руками, после pg_dump):
--   drop table if exists trial_rebuilds; alter table trial_jobs drop column if exists edit_key_hash, drop column if exists released_rooms;

alter table trial_jobs add column if not exists edit_key_hash text;                                -- sha256(ключ правки) hex; null — правки нет
alter table trial_jobs add column if not exists released_rooms jsonb not null default '[]'::jsonb;  -- id комнат страницы, снятых с проверки

create table if not exists trial_rebuilds (
  id text primary key,                                -- lib/token.ts:randomToken
  job_id text not null references trial_jobs (id) on delete cascade,
  request_id text not null,                           -- от клиента: повтор нажатия → та же строка, без второй работы
  rooms jsonb not null,                               -- id комнат страницы или ["*"] — «Обустроить всё»
  base_version integer not null,                      -- bundle_version, от которой нажали; устарела — не публикуем
  status text not null default 'queued',
  attempt integer not null default 0,
  max_attempts integer not null default 2,
  lease_until timestamptz,
  lease_token text,
  worker_id text,
  heartbeat_at timestamptz,
  error_code text,
  error_detail text,                                  -- только для разбора; наружу не отдаётся
  bundle_hash text,
  result_version integer,                             -- версия данных страницы, которую дала эта пересборка
  created_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  constraint trial_rebuilds_status_chk check (status in ('queued', 'running', 'done', 'failed')),
  constraint trial_rebuilds_request_len check (char_length(request_id) between 8 and 64),
  constraint trial_rebuilds_detail_len check (error_detail is null or char_length(error_detail) <= 2000),
  constraint trial_rebuilds_request_uq unique (job_id, request_id)
);
create unique index if not exists trial_rebuilds_active_uq on trial_rebuilds (job_id) where status in ('queued', 'running');
create index if not exists trial_rebuilds_queue_idx on trial_rebuilds (status, created_at);
create index if not exists trial_rebuilds_job_idx on trial_rebuilds (job_id, created_at);

-- Автофото тура после подтверждения планировки (T-20261112-115 Ф2, план tour-auto-photos-01; Codex 12.11 `_intake/codex/2026-11-12-t115-answer.md`).
-- Очередь — outbox: публикация подтверждённой пересборки (`lib/trial/repo-rebuild-worker.ts:publishRebuild`, `progress.confirm`) ТОЙ ЖЕ
-- транзакцией пишет партию «снять тур» (`trial_photo_batches`, с версией данных, которую снимать) и задачи по комнатам (`trial_photo_tasks`).
-- Сетевых вызовов в транзакции нет. Задача = комната × активный вариант × 2 ракурса = ОДИН заказ сервиса кадров.
-- Ровно один раз за деньги: UNIQUE (тур, комната, подпись варианта, подпись поз, качество) резервирует задачу ДО запуска Chromium; занятая,
-- в работе, сделанная и сорвавшаяся строка тоже держит место — повтор подтверждения без правок новых задач не даёт.
-- Деньги: `reserve_rub` (резерв правила, `tools/scout/rules/tour-auto-photos.json`) до факта, `spent_rub` — факт от исполнителя; потолки тура и
-- суток считает `lib/trial/auto-photos-queue.ts`. Отказы (потолок, нет ракурсов…) — в `refused` партии, не молча.
-- Исполнитель DEV берёт партию под аренду (`POST /api/trial/worker/photos/claim`, Bearer воркера), ведёт задачи и закрывает партию.
-- Файл применяется на КАЖДОМ деплое — всё идемпотентно. Перед применением на проде — pg_dump.
-- Откат (только руками, после pg_dump; автофото перестанут ставиться, снятые фото остаются в `trial_photos`):
--   drop table if exists trial_photo_tasks;
--   drop table if exists trial_photo_batches;

create table if not exists trial_photo_batches (
  id text primary key,                                -- lib/token.ts:randomToken
  job_id text not null references trial_jobs (id) on delete cascade,
  rebuild_id text not null,                           -- подтверждённая пересборка, чья публикация поставила партию (одна партия на неё)
  bundle_version int not null,                        -- версия данных тура, которую снимать (хранятся две — поздний исполнитель сверяет)
  status text not null default 'queued',              -- queued | leased | done | failed | empty
  attempt int not null default 0,
  max_attempts int not null default 3,
  lease_token text,
  lease_until timestamptz,
  worker_id text,
  tasks int not null default 0,                       -- поставлено задач
  reserved_rub numeric(8, 2) not null default 0,      -- резерв задач партии на постановке
  refused jsonb not null default '[]'::jsonb,         -- [{room, code}] — не поставлено и почему (счётчик отказов)
  warn text,                                          -- daily_warn — сутки перешли порог предупреждения
  note text,
  created_at timestamptz not null default now(),
  finished_at timestamptz,
  constraint trial_photo_batches_status_chk check (status in ('queued', 'leased', 'done', 'failed', 'empty')),
  constraint trial_photo_batches_refused_chk check (jsonb_typeof(refused) = 'array'),
  constraint trial_photo_batches_len check (char_length(id) <= 64 and char_length(rebuild_id) <= 64
    and (worker_id is null or char_length(worker_id) <= 80) and (note is null or char_length(note) <= 400)
    and (warn is null or char_length(warn) <= 40))
);
-- тур ещё не готов к съёмке (исполнитель: TOUR_READY, exit 3) — партия возвращается в очередь без траты попытки, не раньше `next_run_at`;
-- `releases` — сколько раз возвращена (потолок — `max_releases` правила, дальше failed/tour_not_ready)
alter table trial_photo_batches add column if not exists next_run_at timestamptz not null default now();
alter table trial_photo_batches add column if not exists releases int not null default 0;
create unique index if not exists trial_photo_batches_rebuild_uq on trial_photo_batches (rebuild_id);
create index if not exists trial_photo_batches_claim_idx on trial_photo_batches (status, created_at);
create index if not exists trial_photo_batches_job_idx on trial_photo_batches (job_id, created_at);

create table if not exists trial_photo_tasks (
  id text primary key,
  batch_id text not null references trial_photo_batches (id) on delete cascade,
  job_id text not null references trial_jobs (id) on delete cascade,
  room_id text not null,                              -- комната страницы (`apartment_rooms[].id`)
  variant_id text not null,                           -- активный вариант комнаты (`variants[].id`)
  style text not null,                                -- `style_id` варианта
  ord int not null,                                   -- порядок съёмки: гостиная, спальни по площади
  area_m2 real,
  variant_sig text not null,                          -- подпись расстановки варианта (`auto-photos-pick.ts:variantSig`)
  cams jsonb not null,                                -- позы C1/C2 из данных тура (`v.cams`)
  cams_sig text not null,                             -- та же подпись поз, что у заказа (`repo-photo.ts:camsSig`)
  quality text not null default 'realistic',
  status text not null default 'reserved',            -- reserved | shooting | ordered | done | failed | skipped
  reserve_rub numeric(8, 2) not null,
  spent_rub numeric(8, 2),                            -- факт от исполнителя; в потолке — он, пока нет — резерв
  photo_id text,                                      -- строка `trial_photos` заказа (есть — деньги ушли)
  state_id text,                                      -- номер состояния страницы при съёмке (`index.html:stateIdOf`)
  fail_code text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint trial_photo_tasks_status_chk check (status in ('reserved', 'shooting', 'ordered', 'done', 'failed', 'skipped')),
  constraint trial_photo_tasks_quality_chk check (quality in ('draft', 'realistic')),
  constraint trial_photo_tasks_cams_chk check (jsonb_typeof(cams) = 'array'),
  constraint trial_photo_tasks_money_chk check (reserve_rub >= 0 and (spent_rub is null or spent_rub >= 0)),
  constraint trial_photo_tasks_len check (char_length(room_id) between 1 and 40 and char_length(variant_id) <= 80
    and char_length(style) <= 60 and char_length(variant_sig) <= 80 and char_length(cams_sig) <= 400
    and (state_id is null or char_length(state_id) <= 64) and (fail_code is null or char_length(fail_code) <= 40))
);
-- ровно один раз за деньги: та же комната в той же расстановке с теми же позами не ставится второй раз никогда
create unique index if not exists trial_photo_tasks_once_uq on trial_photo_tasks (job_id, room_id, variant_sig, cams_sig, quality);
create index if not exists trial_photo_tasks_batch_idx on trial_photo_tasks (batch_id, ord);
create index if not exists trial_photo_tasks_day_idx on trial_photo_tasks (created_at);
create index if not exists trial_photo_tasks_photo_idx on trial_photo_tasks (photo_id);

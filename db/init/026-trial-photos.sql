-- Проба для агентов: фото нейросети из тура (план agent-trial-08 § «Правило фото»; T-20261109-34). Кнопка «Сделать реалистичнее» в
-- туре → `POST /api/trial/<id>/photo` (`lib/trial/repo-photo.ts`) → заказ в сервис кадров (`draft:8099/render`, метка расхода `trial`).
-- Каждая строка — принятый сервисом заказ (номер его задания `draft_job`): по ним считается суточный предел на задание
-- (`TRIAL_PHOTO_DAILY`, 10) — агент и покупатель вместе. Счёт и заказ — под блокировкой строки задания (`for update`).
-- Файл применяется на КАЖДОМ деплое — всё идемпотентно.
-- Откат (только руками, после pg_dump):
--   drop table if exists trial_photos;

create table if not exists trial_photos (
  id text primary key,                                -- lib/token.ts:randomToken
  job_id text not null references trial_jobs (id) on delete cascade,
  room_id text not null,                              -- комната страницы (`apartment_rooms[].id`)
  draft_job text,                                     -- номер задания сервиса кадров
  created_at timestamptz not null default now(),
  constraint trial_photos_room_len check (char_length(room_id) between 1 and 40),
  constraint trial_photos_draft_len check (draft_job is null or char_length(draft_job) <= 64)
);
create index if not exists trial_photos_job_idx on trial_photos (job_id, created_at);

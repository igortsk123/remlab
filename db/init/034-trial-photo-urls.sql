-- Фото тура хранятся у тура (T-20261112-115 Ф1, план tour-auto-photos-01): строка `trial_photos` — не только счёт заказа, но и готовое
-- фото. Заказ (`lib/trial/repo-photo.ts:askPhoto`) пишет строку `queued` с тем, что снималось: вариант и стиль, номер состояния
-- расстановки (`stateId` страницы), позы камер с углом обзора (`cams`, `cams_sig` — подпись поз для будущего «не снимать дважды»),
-- качество и кто заказал (`source`: агент по ключу ссылки, покупатель, `auto` — только Bearer воркера). Сервис кадров по готовности
-- присылает кадры (`POST /api/trial/worker/<id>/photo`, `lib/trial/repo-photo-done.ts`): файлы ложатся в папку тура
-- `<TRIAL_DIR>/<id>/photos/`, после проверки файлов строка → `done` с адресами (`shots`), сбой → `failed` с кодом. Тур отдаёт
-- только `done` (`GET /api/trial/<id>/photos`, ворота как у тура).
-- Только добавляет колонки и проверки: старые строки (до Ф1) остаются с `status` NULL — заказ был, файла у тура нет.
-- Файл применяется на КАЖДОМ деплое — всё идемпотентно. Перед применением на проде — pg_dump.
-- Откат (только руками, после pg_dump; файлы `photos/` снимет срок тура вместе с папкой задания):
--   drop index if exists trial_photos_status_idx;
--   alter table trial_photos drop constraint if exists trial_photos_status_chk, drop constraint if exists trial_photos_source_chk,
--     drop constraint if exists trial_photos_quality_chk, drop constraint if exists trial_photos_meta_len,
--     drop constraint if exists trial_photos_json_chk, drop constraint if exists trial_photos_done_chk;
--   alter table trial_photos drop column if exists status, drop column if exists source, drop column if exists state_id,
--     drop column if exists variant_id, drop column if exists style, drop column if exists quality, drop column if exists cams,
--     drop column if exists cams_sig, drop column if exists shots, drop column if exists fail_code, drop column if exists done_at;

alter table trial_photos add column if not exists status text;          -- queued | working | done | failed; NULL — строка до Ф1
alter table trial_photos alter column status set default 'queued';
alter table trial_photos add column if not exists source text;          -- auto | agent | buyer
alter table trial_photos add column if not exists state_id text;        -- номер состояния варианта (`index.html:stateIdOf`)
alter table trial_photos add column if not exists variant_id text;      -- вариант комнаты страницы (`v.id`)
alter table trial_photos add column if not exists style text;
alter table trial_photos add column if not exists quality text;
alter table trial_photos add column if not exists cams jsonb;           -- [{name, x, y, rot, fov, pose, crop?}] — позы кадров заказа
alter table trial_photos add column if not exists cams_sig text;        -- `C1:x,y,rot,fov,pose;C2:…` по имени камеры
alter table trial_photos add column if not exists shots jsonb;          -- [{camera, file, thumb}] — файлы в папке тура `photos/`
alter table trial_photos add column if not exists fail_code text;
alter table trial_photos add column if not exists done_at timestamptz;

alter table trial_photos drop constraint if exists trial_photos_status_chk;
alter table trial_photos add constraint trial_photos_status_chk
  check (status is null or status in ('queued', 'working', 'done', 'failed'));
alter table trial_photos drop constraint if exists trial_photos_source_chk;
alter table trial_photos add constraint trial_photos_source_chk check (source is null or source in ('auto', 'agent', 'buyer'));
alter table trial_photos drop constraint if exists trial_photos_quality_chk;
alter table trial_photos add constraint trial_photos_quality_chk check (quality is null or quality in ('draft', 'realistic'));
alter table trial_photos drop constraint if exists trial_photos_meta_len;
alter table trial_photos add constraint trial_photos_meta_len check (
  (state_id is null or char_length(state_id) <= 64) and (variant_id is null or char_length(variant_id) <= 80)
  and (style is null or char_length(style) <= 60) and (cams_sig is null or char_length(cams_sig) <= 400)
  and (fail_code is null or char_length(fail_code) <= 40));
alter table trial_photos drop constraint if exists trial_photos_json_chk;
alter table trial_photos add constraint trial_photos_json_chk check (
  (cams is null or jsonb_typeof(cams) = 'array') and (shots is null or jsonb_typeof(shots) = 'array'));
-- готовое — только с файлами и временем готовности
alter table trial_photos drop constraint if exists trial_photos_done_chk;
alter table trial_photos add constraint trial_photos_done_chk
  check (status is distinct from 'done' or (shots is not null and done_at is not null));

-- чтение тура (`done` по заданию) и поиск строки по номеру задания сервиса кадров
create index if not exists trial_photos_status_idx on trial_photos (job_id, status, draft_job);

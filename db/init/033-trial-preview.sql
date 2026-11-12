-- Чертёж агента рядом с нашим планом (T-20261112-52; владелец TG 855, 1000, 1002): превью загруженного плана `<id>.src.webp` на томе
-- рядом с файлом задания. Делает воркер DEV (`tools/floorplan/source_preview.py`), кладёт `POST /api/trial/worker/<id>/source`;
-- отдаётся ТОЛЬКО агенту по ключу его ссылки (`lib/trial/tour-source.ts`); уходит вместе с результатом (`lib/trial/retention.ts`).
-- Только добавляет колонку и проверку имени (как у `input_path`, 022/030). Файл применяется на КАЖДОМ деплое — идемпотентно.
-- Перед применением на проде — pg_dump. Откат (только руками, после pg_dump; файлы `*.src.webp` затем снимет уборка сирот):
--   alter table trial_jobs drop constraint if exists trial_jobs_preview_path_chk;
--   alter table trial_jobs drop column if exists preview_path;

alter table trial_jobs add column if not exists preview_path text;
alter table trial_jobs drop constraint if exists trial_jobs_preview_path_chk;
alter table trial_jobs add constraint trial_jobs_preview_path_chk
  check (preview_path is null or preview_path ~ '^[A-Za-z0-9_-]{22}\.src\.webp$');

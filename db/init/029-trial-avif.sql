-- Проба для агентов: планы AVIF (T-20261110-38; владелец 10.11, TG 893 — план с сайта «Этажи» пришёл в .avif). Имя файла задания
-- получает расширение avif (`lib/trial/storage.ts:INPUT_NAME_RE`); в PNG его переводит воркер DEV (`tools/floorplan/pipeline.py:prepare`).
-- Только расширяет проверку имени: прежние строки ей удовлетворяют. Файл применяется на КАЖДОМ деплое — идемпотентно
-- (снять и поставить ту же проверку). Перед применением — pg_dump. Откат (только руками, если avif-строк нет):
--   alter table trial_jobs drop constraint if exists trial_jobs_input_path_chk;
--   alter table trial_jobs add constraint trial_jobs_input_path_chk
--     check (input_path is null or input_path ~ '^[A-Za-z0-9_-]{22}\.(jpg|png|webp|pdf)$');

alter table trial_jobs drop constraint if exists trial_jobs_input_path_chk;
alter table trial_jobs add constraint trial_jobs_input_path_chk
  check (input_path is null or input_path ~ '^[A-Za-z0-9_-]{22}\.(jpg|png|webp|avif|pdf)$');

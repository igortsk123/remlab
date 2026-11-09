-- Проба для агентов: промежуточные версии данных страницы (план agent-trial-08, задача А; T-20261109-21). Итог пробы — та же страница,
-- что `/demo`, и у задания свой `demo-data.json`: файлы лежат на томе `/app/data/trial/<id>/bundle-<версия>.json` (неизменяемые),
-- потому что `trial_jobs.result` ограничен 2 МБ. Строка — МАНИФЕСТ: читатель видит только версию, записанную здесь одним огороженным UPDATE.
-- Имя файла — только из этого числа, путь наружу не приходит. Файл применяется на КАЖДОМ деплое — всё идемпотентно.
-- Откат (только руками, после pg_dump): alter table trial_jobs drop column bundle_version, drop column bundle_hash;

alter table trial_jobs add column if not exists bundle_version integer not null default 0;  -- 0 — ещё не опубликовано
alter table trial_jobs add column if not exists bundle_hash text;                           -- sha256 текущей версии: повтор не публикуется дважды

-- Проба для агентов: исходный план хранится столько же, сколько тур, — 30 дней после финального статуса (владелец 10.11, TG 744:
-- «в течение месяца человек может поправить план»; T-20261110-24, `lib/trial/config.ts:trialFileHours`). Новые задания получают срок
-- в `lib/trial/sql.ts:terminalSet`; здесь — уже загруженные, чей файл ещё на томе (`input_path is not null`): срок файла = сроку тура.
-- Удалённые файлы (input_path = null) не вернуть — их не трогаем.
-- Только строки старого правила (срок файла не дальше 7 дней от финала — прежний потолок `TRIAL_FILE_RETENTION_HOURS` ≤ 168) и
-- законченные до 01.12.2026: если срок файла когда-нибудь снова сделают короче, повтор файла на деплое его не продлит.
-- Файл применяется на КАЖДОМ деплое — всё идемпотентно (второй прогон ничего не находит).
-- Перед применением — pg_dump (данные). Откат (только руками): вернуть прежние сроки нельзя без копии; при нужде —
--   update trial_jobs set expires_at = finished_at + interval '24 hours' where input_path is not null and expires_at = result_expires_at;

update trial_jobs set expires_at = result_expires_at
where input_path is not null
  and finished_at is not null
  and finished_at < timestamptz '2026-12-01 00:00:00+00'
  and expires_at is not null
  and result_expires_at is not null
  and expires_at < result_expires_at
  and expires_at <= finished_at + interval '7 days';

-- «Размеры своими словами» (план agent-trial-08, Р2-текст; T-20261109-33): агент пишет размеры комнат свободным текстом — со страницы
-- ожидания (уже на v1, задание ещё идёт) или с плана тура. Это пересборка того же конвейера `trial_rebuilds` (`024`) вида `listing`:
-- воркер повторяет чтение плана с исходным листом и этим текстом (кэш VLM, 0 $), затем мебель как у «Обустроить», и публикует ОДНУ новую
-- версию данных страницы. Строка `listing` ждёт `done` задания (claim берёт только `done`), её `base_version` при claim переписывается
-- на текущую версию данных — поколение, которое сверяет публикация (штатный переход v1→v3 до `done` — не отказ).
-- `listing_text` — только для воркера: наружу (статус, журнал) не отдаётся; новый текст ЗАМЕНЯЕТ текст ждущей строки (не склеиваем);
-- по завершении пересборки и по сроку результата — null. Старый воркер (без `listing` в claim) таких строк не получает.
-- Файл применяется на КАЖДОМ деплое — всё идемпотентно.
-- Откат (только руками, после pg_dump):
--   alter table trial_rebuilds drop constraint if exists trial_rebuilds_kind_chk, drop constraint if exists trial_rebuilds_text_len,
--     drop column if exists listing_text, drop column if exists kind;

alter table trial_rebuilds add column if not exists kind text not null default 'furnish';  -- furnish — «Обустроить»; listing — текст агента
alter table trial_rebuilds add column if not exists listing_text text;                     -- текст агента (≤ 2000 знаков); null у furnish

alter table trial_rebuilds drop constraint if exists trial_rebuilds_kind_chk;
alter table trial_rebuilds add constraint trial_rebuilds_kind_chk check (kind in ('furnish', 'listing'));
alter table trial_rebuilds drop constraint if exists trial_rebuilds_text_len;
alter table trial_rebuilds add constraint trial_rebuilds_text_len check (listing_text is null or char_length(listing_text) <= 2000);

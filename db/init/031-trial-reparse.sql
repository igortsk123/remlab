-- «Перечитать планировку» (план trial-reparse-01; T-20261111-02): ОПЕРАТОР ставит пересборку готового тура вида `reparse` — воркер DEV
-- перечитывает исходный лист задания (кэш VLM, 0 $) с ИСХОДНЫМ текстом объявления (`trial_jobs.listing_text`) и поздними размерами агента,
-- подбирает мебель заново и публикует ОДНУ новую версию вместе с новым `result` — только если сторож регресса не нашёл потерь
-- (`tools/floorplan/regress.py:reparse_guard`). Ставит её ручка `POST /api/trial/worker/reparse` (ключ воркера); агент такую не ставит,
-- в суточные лимиты она не входит, наружу видна нейтрально («обновляем тур», `lib/trial/repo-public.ts`).
-- Только расширяет проверку вида: прежние строки ей удовлетворяют. Тот же набор — в `025` и `028`: файлы применяются по порядку на КАЖДОМ
-- деплое, и проверка без `reparse` там упала бы на первой же такой строке. Идемпотентно (снять и поставить ту же проверку).
-- Перед применением на проде — pg_dump. Откат (только руками, после pg_dump; если строк 'reparse' нет — иначе сперва
-- `delete from trial_rebuilds where kind = 'reparse'`):
--   alter table trial_rebuilds drop constraint if exists trial_rebuilds_kind_chk;
--   alter table trial_rebuilds add constraint trial_rebuilds_kind_chk check (kind in ('furnish', 'listing', 'edit'));
--   и вернуть тот же набор в 025/028.

alter table trial_rebuilds drop constraint if exists trial_rebuilds_kind_chk;
alter table trial_rebuilds add constraint trial_rebuilds_kind_chk check (kind in ('furnish', 'listing', 'edit', 'reparse'));

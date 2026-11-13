-- Автофото тура: повтор задачи, сорвавшейся БЕЗ траты (T-20261112-115/5, решение директора 13.11 02:5x; план tour-auto-photos-01 Ф3).
-- Раньше место в UNIQUE `trial_photo_tasks_once_uq` (тур, комната, подпись расстановки, подпись поз, качество) держала любая строка навсегда:
-- задача, закрытая без заказа (abandoned, lease_lost, tour_not_ready, отказ сервиса кадров до оплаты; `photo_id` пуст — денег нет), больше
-- никогда не ставилась, и комната тура оставалась без фото. Теперь следующая постановка (`lib/trial/auto-photos-queue.ts`) берёт ТУ ЖЕ строку
-- в новую партию (UNIQUE и запрет второго заказа за деньги не меняются), а `tries` считает попытки: не больше `max_tries` правила
-- (`tools/scout/rules/tour-auto-photos.json`), дальше — отказ `retry_cap` в партии. Сорвавшееся С тратой (`photo_id` есть) не повторяется.
-- Только добавление колонки; файл применяется на каждом деплое — идемпотентно. Перед применением на проде — pg_dump.
-- Откат (руками, после pg_dump): alter table trial_photo_tasks drop column if exists tries;

alter table trial_photo_tasks add column if not exists tries int not null default 1;

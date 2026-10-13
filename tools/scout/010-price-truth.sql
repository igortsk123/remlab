-- КАТАЛОЖНАЯ миграция дев-БД `remlab-devdb` (применяет `tools/scout/db_migrate.py`).
-- Правдивая цена (план conv-10, ADR-0260): `price_rub` — как пришло в фиде (его пишет load3), а показываем
-- `price_shown_rub` — фид или цену со страницы магазина, по правилу магазина (`rules/price-truth.json`),
-- с источником и датой. Пишет `price_truth.py`; витрина, ленты и 3D читают показываемую.
alter table products add column if not exists price_shown_rub numeric;
alter table products add column if not exists price_basis text;          -- feed | page | feed-stale
alter table products add column if not exists price_checked_at timestamptz;

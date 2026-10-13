-- КАТАЛОЖНАЯ миграция дев-БД `remlab-devdb` (применяет `tools/scout/db_migrate.py`).
-- «Фото есть» = фото реально скачалось (план conv-05, ADR-0261). Пишет ОДИН писатель — `img_alive.py
-- --sync-db` из своего кэша проверок; NULL — не проверяли (не блокирует, считается в отчёте).
alter table products add column if not exists photo_alive boolean;
alter table products add column if not exists photo_alive_at timestamptz;
create index if not exists products_photo_dead_idx on products (photo_alive) where photo_alive = false;

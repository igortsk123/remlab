-- КАТАЛОЖНАЯ миграция дев-БД `remlab-devdb` (применять ТОЛЬКО `tools/ops/db-migrate-safe.sh` со слова владельца).
-- «Фото есть» у товаров комнат (спальня, прихожая — `room_catalog`) — то же правило, что у гостиной (011-photo-alive,
-- conv-05, ADR-0261): фото реально скачалось. Пишет ОДИН писатель — `img_alive.py --rooms` (`sync_rooms_db`) из общего
-- кэша проверок; NULL — не проверяли (показываем). Читают: `room_catalog.PHOTO_OK_SQL` в `shown_where` обеих комнат,
-- ленты замен — `img_alive.dead_room_photos` (план room-conveyor-02 К1, T-20261106-84). Откат — drop column (данных нет).
--   tools/ops/db-migrate-safe.sh tools/scout/017-room-photo-alive.sql --check \
--     "(select count(*) from information_schema.columns where table_name='room_catalog' and column_name in ('photo_alive','photo_alive_at'))=2"
alter table room_catalog add column if not exists photo_alive boolean;
alter table room_catalog add column if not exists photo_alive_at timestamptz;
create index if not exists room_catalog_photo_dead_idx on room_catalog (room, photo_alive) where photo_alive = false;

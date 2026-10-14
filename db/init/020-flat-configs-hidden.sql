-- Подбор 3D (ADR-0281, verify 14.10): «убранные» предметы и номер коллекции, из которой открыт 3D, — переживают ссылку.
-- Раньше `hidden` жил только в черновике браузера (по ссылке убранный предмет возвращался), а подбор из 3D коллекции
-- по ссылке открывался исходным набором витрины.
alter table flat_configs add column if not exists hidden jsonb;
alter table flat_configs add column if not exists collection_id text;

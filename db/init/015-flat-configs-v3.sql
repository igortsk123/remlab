-- Подбор версии 3 (план b2b-06, ADR-0258): квартира — id из реестра застройщиков, исходный набор мебели
-- витрины — отдельным полем, снимок «место → модель» — чтобы после ночной пересборки витрины честно
-- сказать «набор обновился», а не подменить мебель молча. Старые записи получают пустые значения.
alter table if exists flat_configs add column if not exists base_variant text;
alter table if exists flat_configs add column if not exists base_snapshot jsonb;

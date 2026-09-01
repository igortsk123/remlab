-- ПОМЕТКА И ССЫЛКА НА МЕШ ПРЯМО В КАРТОЧКЕ ТОВАРА (решение владельца 01.09).
-- «В структуру как хранятся туда и надо пометку типа требуется меш и все туда смотрят.
--  Как меш готов — там ссылка на меш и дата его изготовления.»
--
-- Почему в products, а не только в mesh_demand: спрос (demand) — рабочая очередь, он может
-- стать not_required или пересчитаться, а карточка товара живёт всегда, и все потребители
-- (планировщик, сеты, галерея, демо) уже читают products. История ревизий и брак остаются
-- в asset_revisions — здесь только УКАЗАТЕЛЬ на текущий рабочий меш.
--
-- mesh_required заполняется из канона ролей (rules/asset-strategies.json, политика v2):
-- hunyuan3d → true; procedural_plane/cutout → false. Пишет `tools/scout/mesh_bind.py`.
-- mesh_uri/mesh_at/mesh_revision_key заполняются приёмкой, когда меш принят.

alter table products add column if not exists mesh_required boolean;
alter table products add column if not exists mesh_status text;        -- ready|generating|rejected|none
alter table products add column if not exists mesh_revision_key text;  -- ключ ревизии в asset_revisions
alter table products add column if not exists mesh_uri text;           -- стабильный путь/URL модели
alter table products add column if not exists mesh_at timestamptz;     -- дата изготовления принятой модели
alter table products add column if not exists mesh_policy_version int; -- версия канона ролей на момент пометки

create index if not exists products_mesh_required_idx on products (mesh_required)
  where mesh_required;
create index if not exists products_mesh_status_idx on products (mesh_status);

-- Ревизии: без номера перегона (seed) разные попытки схлопывались в одну строку — «жёсткая
-- ссылка» закрепляла бы случайную последнюю (дефект найден разбором Codex 01.09).
alter table asset_revisions add column if not exists source_sha text;
alter table asset_revisions add column if not exists generation_variant text;  -- seed/config
alter table asset_revisions add column if not exists asset_uri text;
alter table asset_revisions add column if not exists rejected_reason text;

-- Витрина состояния: одним запросом видно, что с мешом у каждого товара.
create or replace view product_mesh_state as
select p.shop_mid || ':' || p.external_id as sku,
       p.cat_role                          as role,
       p.in_stock,
       p.mesh_required,
       coalesce(p.mesh_status, 'none')     as mesh_status,
       p.mesh_uri,
       p.mesh_at,
       p.mesh_revision_key,
       d.priority                          as demand_priority,
       d.status                            as demand_status
  from products p
  left join mesh_demand d
         on d.sku = p.shop_mid || ':' || p.external_id;

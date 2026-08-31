-- К1 мастер-плана MASTER-catalog-ai (ADR-0068): обогащение живёт ОТДЕЛЬНО от товара.
-- Фид перезаписывает только операционные поля products (цена, наличие, ссылка); всё, что добыто
-- разбором и моделями, лежит здесь и не теряется, даже если товар пропал из фида на месяц.
-- Миграция идемпотентна: гоняется столько раз, сколько нужно (tools/scout/db_migrate.py).

create table if not exists product_enrichment (
  shop_mid            integer not null,
  external_id         text    not null,

  -- дельта: что именно изменилось с прошлого прогона
  commercial_hash     text,          -- цена + старая цена + наличие + ссылка
  text_hash           text,          -- нормализованные название + описание
  geometry_hash       text,          -- нормализованные размеры
  image_hash          text,          -- URL картинки (дёшево, но URL меняют без смены картинки)
  perceptual_hash     text,          -- отпечаток САМОЙ картинки; только триггер, не доказательство

  -- жизненный цикл: исчезнувший товар деактивируем, обогащение НЕ удаляем
  status              text    not null default 'active',
  missing_runs        integer not null default 0,
  missing_since       date,

  -- версии: смена модели или промпта не должна пересчитывать весь каталог
  enrichment_version  text,
  model_name          text,
  prompt_version      text,
  schema_version      text,
  enriched_at         timestamptz,

  -- сами признаки приедут в К2; место заводим сейчас, чтобы не мигрировать дважды
  payload             jsonb,
  quality             real,

  first_seen          date not null default current_date,
  last_seen           date,
  updated_at          timestamptz not null default now(),
  primary key (shop_mid, external_id)
);

create index if not exists idx_enrich_status  on product_enrichment (status);
create index if not exists idx_enrich_phash   on product_enrichment (perceptual_hash);
create index if not exists idx_enrich_version on product_enrichment (enrichment_version);

-- products.status — производное поле: два десятка скриптов смотрят на in_stock, и ломать их
-- ради красоты нельзя. Истина о жизненном цикле — в product_enrichment.status; здесь копия
-- для быстрых выборок и совместимости. С 31.08 (ADR-0141) `in_stock` — НЕ копия статуса фида,
-- а производное трёх источников (фид + программа магазина + карточка), см. 003-stock-truth.sql.
alter table products add column if not exists status text not null default 'active';
create index if not exists idx_products_status on products (status);

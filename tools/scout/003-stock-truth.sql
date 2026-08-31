-- Наличие товара: свидетельство о карточке отдельно от свидетельства фида (31.08.2026).
--
-- ЗАЧЕМ. `products.in_stock` означал «есть в свежем фиде и с ценой» — и никогда «продаётся».
-- Фиды Гдеслона не отдают `available` вовсе, API отдаёт `available=true` даже для карточек,
-- отвечающих 404. Проверки страниц (health/linkcheck) писали вердикт прямо в `products.in_stock`,
-- и `load3.py` стирал его на следующем прогоне: 353 ссылки с HTTP 404 числились в продаже.
--
-- УСТРОЙСТВО. Три источника правды живут раздельно и не перетирают друг друга:
--   product_enrichment.status  — фид (есть/пропал/архив), пишет load3;
--   shop_status.program_state  — партнёрская программа магазина, пишет gdeslon_api;
--   product_page_status.state  — свидетельство о карточке, пишет stock_check.
-- `products.in_stock` — ПРОИЗВОДНОЕ от всех трёх, его материализует один reconciler
-- (`stock_truth.reconcile`). Прямые записи `in_stock` из скриптов запрещены.

create table if not exists product_page_observation (
  id           bigserial primary key,
  shop_mid     int  not null,
  external_id  text not null,
  url_hash     text not null,          -- sha1 нормализованной ссылки: смена ссылки = новый факт
  url          text not null,
  http_code    int,
  final_url    text,
  verdict      text not null,          -- alive | oos | gone | unknown
  reason       text,                   -- чем решили: 'schema OutOfStock', 'http 404', 'captcha'
  probe_version int not null default 1,
  run_id       text not null,
  observed_at  timestamptz not null default now()
);
-- РАЗВЕДКА И ПОДТВЕРЖДЕНИЕ — РАЗНЫЕ ВЫБОРКИ. Проход подтверждений состоит ИЗ ОДНИХ подозреваемых,
-- поэтому 100% отрицательных в нём — норма, а не поломка магазина. Гейт обязан считать долю
-- только по разведочной части, иначе он карантинит именно те прогоны, ради которых заведён.
alter table product_page_observation add column if not exists probe_kind text not null default 'explore';
create index if not exists idx_ppo_sku  on product_page_observation (shop_mid, external_id, observed_at desc);
create index if not exists idx_ppo_run  on product_page_observation (run_id);

-- Текущий результат reducer'а. `negatives` — сколько отрицательных наблюдений подряд по ОДНОЙ
-- и той же ссылке: первое даёт `suspect` (товар не снимаем), второе применяет состояние.
create table if not exists product_page_status (
  shop_mid    int  not null,
  external_id text not null,
  state       text not null default 'unknown',  -- alive | oos | gone | unknown | suspect
  reason      text,
  url_hash    text,
  negatives   int  not null default 0,
  checked_at  timestamptz not null default now(),
  applied_at  timestamptz,
  dead_since  date,
  primary key (shop_mid, external_id)
);
create index if not exists idx_pps_state on product_page_status (state);
create index if not exists idx_pps_checked on product_page_status (checked_at);

-- Программа магазина: закрылась партнёрка — товары нельзя продать, даже если фид ещё свежий.
-- Раньше это писалось прямо в products (`gdeslon_api.retire`) и стиралось следующим load3.
create table if not exists shop_status (
  shop_mid      int primary key,
  shop          text,
  program_state text not null default 'active',   -- active | retired
  checked_at    timestamptz not null default now(),
  note          text
);

-- Честная модель наличия (план stock-and-dims-honesty, Н2) и наблюдения со страницы (Н3). Идемпотентно.
--
-- Н2. «Страница есть», «товар в наличии» и «на чём основано» — три разных факта (Codex 03.09):
--   availability_state  in_stock | out_of_stock | unknown   — что известно о наличии ТОВАРА;
--   page_state          alive | gone | unknown               — есть ли страница карточки;
--   availability_basis  page | feed | none                   — на чём держится in_stock:
--                       page — наше принятое свидетельство по текущей ссылке, feed — только фид
--                       (не проверяли / не смогли / домен выключен), none — товара нет и в фиде;
--   stock_evidence_at   время последнего РЕШАЮЩЕГО принятого наблюдения (alive/oos/gone), не попытки;
--   stock_probe_at      время последней попытки (любой исход).
-- `products.in_stock` остаётся совместимым признаком «годен к продаже через нас». Всё это — производные,
-- пишет ТОЛЬКО stock_truth.reconcile(); свежесть (stale) вычисляется из stock_evidence_at читателями.
alter table products add column if not exists availability_state text;
alter table products add column if not exists page_state text;
alter table products add column if not exists availability_basis text;
alter table products add column if not exists stock_evidence_at timestamptz;
alter table products add column if not exists stock_probe_at timestamptz;
create index if not exists products_avail_basis_idx on products (availability_basis);

-- Н3. Со страницы, раз уж пришли: цена, имя, канонический адрес — ТОЛЬКО как наблюдения (append-only),
-- в products.price_rub не идут (фид — владелец коммерческих полей, ADR-0171).
alter table product_page_observation add column if not exists price_seen numeric;
alter table product_page_observation add column if not exists name_seen text;
alter table product_page_observation add column if not exists canonical_url text;

-- Последний факт со страницы по товару — для отчёта расхождений с фидом.
create or replace view product_page_facts as
select distinct on (o.shop_mid, o.external_id)
       o.shop_mid, o.external_id, o.price_seen, o.name_seen, o.canonical_url, o.observed_at as seen_at, o.verdict
  from product_page_observation o
 where o.disposition in ('accepted', 'shadow') and (o.price_seen is not null or o.name_seen is not null)
 order by o.shop_mid, o.external_id, o.observed_at desc;

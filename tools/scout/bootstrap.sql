-- Разведочная БД каталога Гдеслона (контейнер remlab-devdb).
-- Поднять контейнер (если удалён):
-- docker run -d --name remlab-devdb -e POSTGRES_PASSWORD=dev -e POSTGRES_USER=remlab \
--   -e POSTGRES_DB=remlab -p 127.0.0.1:5433:5432 -m 512m pgvector/pgvector:pg17
create table if not exists products (
  shop_mid    integer not null,
  external_id text not null,
  primary key (shop_mid, external_id),
  shop        text not null,
  category_id integer,
  category_path text,
  name        text not null,
  brand       text,
  url         text not null,
  image_url   text,
  price_rub   integer,
  old_price_rub integer,
  charge_rub  real,
  in_stock    boolean not null default true,
  w_cm real, d_cm real, h_cm real, len_cm real, dia_cm real,
  dims_source text,
  params      jsonb
);
create index if not exists idx_products_cat on products (shop_mid, category_id);

create table if not exists scrape_queue (
 shop_mid int, external_id text, primary key(shop_mid, external_id),
 role text, direct_url text, status text default 'new', tries int default 0, note text);

-- КОЛОНКИ, КОТОРЫЕ ДОБАВЛЯЮТ СКРИПТЫ НА ХОДУ (`load3.py`, `category_map.py`), — здесь тоже (14.10, conv-06): иначе
-- схема на чистой машине не собиралась — представление ниже ссылается на `cat_role`, которого ещё нет
-- (поймано интеграционным тестом `tests/pipeline_chain_dbtest.py`). `if not exists` — повтор безопасен.
alter table products add column if not exists cat_role text;
alter table products add column if not exists image_url_hd text;
alter table products add column if not exists article text;
alter table products add column if not exists description text;
alter table products add column if not exists last_seen date;
alter table products add column if not exists direct_url text;
alter table products add column if not exists direct_url_hash text;
alter table products add column if not exists dims_evidence jsonb;
-- поля меша читает представление `catalog_ready` ниже; канон их смысла — `006-mesh-binding.sql`
alter table products add column if not exists mesh_required boolean;
alter table products add column if not exists mesh_status text;
alter table products add column if not exists mesh_uri text;
alter table products add column if not exists mesh_at timestamptz;

-- РОЛЬ ТОВАРА — ИЗ ОДНОЙ КАРТЫ (11.10.2026). Раньше здесь был второй, независимый классификатор:
-- регулярки по `category_path`. Он расходился с канонической картой категорий
-- (`category-roles.json` → `products.cat_role`, пишет load3) на 2 453 товарах. Самый заметный
-- случай: категория магазина «Тумбы под телевизор» не подходила под шаблон `тв-тумб|тумб.*тв`
-- (слова «тв» в слове «телевизор» нет) — 471 тв-тумба в каноне и НОЛЬ в подборе, из-за чего
-- тв-тумбы не попадали ни в стиль-скоринг, ни в очередь мешей, а в отчёте покрытия зияла дырка
-- во всех шести стилях. Добавить ещё одну регулярку — залечить симптом: два классификатора
-- разойдутся снова. Поэтому витрина читает готовую роль, а решение «эта ветка — такая роль»
-- принимается в одном месте: category_map.py.
-- Колонки перечислены ЯВНО, а не `p.*`: у представления список колонок фиксируется при создании,
-- и `create or replace` с `p.*` ломается, как только в products добавят поле («cannot change name
-- of view column»). Набор — ровно тот, что был у прежней витрины.
create or replace view lr_roles as
select p.shop_mid, p.external_id, p.shop, p.category_id, p.category_path, p.name, p.brand,
       p.url, p.image_url, p.price_rub, p.old_price_rub, p.charge_rub, p.in_stock,
       p.w_cm, p.d_cm, p.h_cm, p.len_cm, p.dia_cm, p.dims_source, p.params,
       p.cat_role as role
from products p where in_stock;

-- Наполнение очереди скрейпа (tvoydom, роли гостиной, неполные размеры):
-- insert into scrape_queue (shop_mid, external_id, role, direct_url)
-- select shop_mid, external_id, role,
--  replace(replace(replace(substring(url from 'goto=([^&]+)'),'%3A',':'),'%2F','/'),'%3F','?')
-- from lr_roles
-- where shop='tvoydom.ru' and role in (...) and (w_cm is null or (d_cm is null and len_cm is null and dia_cm is null) or h_cm is null)
-- on conflict do nothing;

-- ОЦЕНКИ СТИЛЯ — В БАЗЕ (11.10.2026, просьба владельца «чтоб в базе было видно, где есть меши»).
-- Раньше стили жили только в файле `style-scores.json` с ключом `mid-eid`, где все небуквенные
-- символы заменены на `_` — связать стиль с мешем одним запросом было нельзя. Теперь ключ —
-- тот же, что у товара: (shop_mid, external_id). Файл остаётся кэшем прогона.
create table if not exists product_style_scores (
  shop_mid    integer not null,
  external_id text not null,
  primary key (shop_mid, external_id),
  scores      jsonb not null,     -- {"сканди": 7.2, "лофт": 3.0, ...}
  top_style   text,               -- стиль с наибольшим баллом (для быстрых выборок)
  universal   boolean,            -- вписывается куда угодно, стиля не создаёт
  src         text,               -- llm+rules | llm+rules+clip | rules+clip
  model       text,               -- какая модель считала
  scored_at   timestamptz default now()
);

-- ОДНА КАРТИНА: товар → роль → стиль → меш. Отвечает на вопрос «что готово к генерации мешей»
-- и «где меш уже есть». Стратегия ассета (меш/плоскость/вырезка) живёт в
-- `rules/asset-strategies.json` — здесь только факт наличия меша и ссылка на него.
create or replace view catalog_ready as
select p.shop_mid, p.external_id, p.shop, p.name, p.cat_role as role,
       p.price_rub, p.in_stock, p.image_url, p.image_url_hd,
       p.w_cm, p.d_cm, p.h_cm, p.dims_source,
       (p.w_cm is not null and (p.d_cm is not null or p.dia_cm is not null)
        and p.h_cm is not null)                       as размеры_есть,
       s.scores, s.top_style, s.universal, s.model    as style_model, s.scored_at as style_at,
       p.mesh_required, p.mesh_status, p.mesh_uri, p.mesh_at,
       (p.mesh_status = 'ready' and p.mesh_uri is not null) as меш_есть,
       case
         when p.mesh_status = 'ready' and p.mesh_uri is not null then 'меш готов'
         when s.scores is null                                   then 'ждёт стиль'
         when p.image_url is null                                then 'нет фото'
         when p.cat_role is null                                 then 'нет роли'
         else 'готов к генерации меша'
       end as готовность
from products p
left join product_style_scores s using (shop_mid, external_id)
where p.in_stock;

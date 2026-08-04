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

create or replace view lr_roles as
select p.*,
 case
  when category_path ~* 'садов|уличн|дачн|туристич|детск|офисн|компьютерн|ванн|придверн|духов|кухонн(ая|ые) (мойк|плит)|гайковерт|удобрен|для стекол' then null
  when category_path ~* 'диван' then 'диван'
  when category_path ~* 'подвесн.*кресл' then null
  when category_path ~* 'кресл' then 'кресло'
  when category_path ~* 'пуф|банкетк' then 'пуф'
  when category_path ~* 'журнальн|прикроватн.*столик|столы и столики|консол' then 'столик'
  when category_path ~* 'тв-тумб|тумб.*тв' then 'тв-тумба'
  when category_path ~* 'стенк' then 'стенка'
  when category_path ~* 'стеллаж' then 'стеллаж'
  when category_path ~* 'витрин|буфет|сервант' then 'витрина'
  when category_path ~* 'комод' then 'комод'
  when category_path ~* 'полк' and category_path !~* 'полкодержат' then 'полка'
  when category_path ~* 'зеркал' then 'зеркало'
  when category_path ~* '^ковры|/ ковры|ковер ' or (category_path ~* 'ковр' and category_path !~* 'коврик|подложк') then (case when p.name ~* 'подложк|придверн' then null else 'ковёр' end)
  when category_path ~* 'торшер' then 'торшер'
  when category_path ~* 'настольн.*ламп' then 'лампа'
  when category_path ~* 'бра' then 'бра'
  when category_path ~* 'люстр|настенно-потолочн' then 'люстра'
  when category_path ~* 'камин|очаг' then 'камин'
  when category_path ~* 'кухонные столы|обеденн.*стол' then 'стол обеденный'
  when category_path ~* 'кухонные стулья|барные стулья' or (category_path ~* '^стулья' or category_path ~* '/ стулья') then 'стул'
  when category_path ~* 'шторы|тюль|карниз' then 'шторы'
  when category_path ~* 'плед|покрывал' then 'плед'
  when category_path ~* 'декоративн.*подушк' or category_path ~* '^подушки' then 'подушка'
  when category_path ~* 'ваз' then 'ваза'
  when category_path ~* 'статуэт|фигур' then 'статуэтка'
  when category_path ~* 'кашпо' then 'кашпо'
  when category_path ~* 'искусственн.*растен' then 'растение'
  when category_path ~* 'часы' then 'часы'
  when category_path ~* 'обрамлен|картин|постер|панно' then 'картина'
  when category_path ~* 'распашн.*шкаф|шкафы-купе|модульн.*шкаф|углов.*шкаф|^шкафы' then 'шкаф'
 end as role
from products p where in_stock;

-- Наполнение очереди скрейпа (tvoydom, роли гостиной, неполные размеры):
-- insert into scrape_queue (shop_mid, external_id, role, direct_url)
-- select shop_mid, external_id, role,
--  replace(replace(replace(substring(url from 'goto=([^&]+)'),'%3A',':'),'%2F','/'),'%3F','?')
-- from lr_roles
-- where shop='tvoydom.ru' and role in (...) and (w_cm is null or (d_cm is null and len_cm is null and dia_cm is null) or h_cm is null)
-- on conflict do nothing;

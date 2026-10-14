-- КАТАЛОГ КОМНАТ КРОМЕ ГОСТИНОЙ (план b2b-10 этап 2, ADR-0279). Отдельно от `products`: таблицу товаров читают
-- ночные шаги гостиной (платное обогащение, проверки страниц, очередь мешей, метрики стыков) без фильтра по роли —
-- кровати там дали бы ложные тревоги и расходы. v1 — фото-каталог спальни; перенос в products с ролями по
-- комнатам — когда спальне понадобятся меши и комплекты (проект Codex 14.10).
create table if not exists room_catalog (
  shop_mid integer not null,
  external_id text not null,
  room text not null,                -- bedroom
  role text not null,                -- кровать | тумба прикроватная | комод | шкаф | туалетный столик
  shop text, name text not null, brand text,
  url text not null,                 -- ПАРТНЁРСКАЯ ссылка из фида (комиссия, ADR-0016)
  image_url text, image_url_hd text,
  price_rub integer,                 -- нет цены = не показываем (как out_of_stock у load3.assign)
  w_cm real, d_cm real, h_cm real,
  sleep_w_cm real, sleep_l_cm real,  -- только кровать: спальное место (bed_dims.py)
  footprint_ok boolean,              -- габарит сверен со спальным местом; иначе в расстановку нельзя
  dims_note text,
  params jsonb,
  last_seen date,
  missing_runs integer not null default 0,   -- прогонов подряд без оффера в СВЕЖЕМ фиде своего магазина
  updated_at timestamptz default now(),
  primary key (shop_mid, external_id, room)
);
create index if not exists idx_room_catalog_role on room_catalog (room, role);
create table if not exists room_catalog_runs (
  run_at timestamptz default now(), room text, shop_mid integer, accepted integer, verdict text
);

-- ТКАНЬ ОБИВКИ (план onb-04 Т4, ADR-0330). Своя таблица, а не столбцы `products`/`room_catalog`: признак ещё не принят
-- (выборка 50 у ведущего), его никто не читает; ключ — откуда товар (products — диван/кресло/пуф гостиной, room_catalog —
-- кровать с мягким изголовьем спальни) + оффер. Пишет только `upholstery.py --run` при `rules/upholstery.json` enabled.
create table if not exists upholstery (
  source_table text not null,        -- products | room_catalog
  shop_mid integer not null,
  external_id text not null,
  fabric text,                       -- велюр | микровелюр | рогожка | букле | шенилл | флок | … ; null — неизвестно
  generic boolean,                   -- магазин сказал только «ткань» (тип неизвестен)
  anti_claw boolean, anti_claw_src text,     -- только по слову магазина; src: name/param | desc
  easy_clean boolean, easy_clean_src text,   -- param | name/param | desc
  evidence text,                     -- param:<ключ>=<значение> | name
  conflict text,                     -- название спорит с параметром
  rules_ver text not null,
  updated_at timestamptz default now(),
  primary key (source_table, shop_mid, external_id)
);

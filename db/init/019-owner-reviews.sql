-- Отметки владельца на проверочных страницах /test/* (ADR-0275): «подходит / не подходит» стиль, карантин моделей.
-- Одна строка — одно нажатие (история); текущее решение — последняя строка по (kind, item_key). Без ПДн.
create table if not exists owner_reviews (
  id bigserial primary key,
  kind text not null,          -- style | quarantine
  item_key text not null,      -- товар/модель и вопрос, например «112923_123|сканди»
  verdict text not null,       -- yes | no | accept | reject | cut
  comment text,
  created_at timestamptz not null default now()
);
create index if not exists owner_reviews_kind_idx on owner_reviews (kind, id);

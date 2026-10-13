-- Коллекции покупателя (план b2b-05, ADR-0264): снимок своей расстановки демо, открывается ссылкой.
-- Без ПДн; `send_id` — номер отправки менеджера (псевдоним, не человек). Срок — 365 дней, чистит
-- ежечасный сторож. Файл применяется на каждом деплое — всё идемпотентно.
create table if not exists collections (
  id text primary key,
  partner_id text not null,
  apartment_id text not null,
  base_variant text not null,
  send_id text,
  lang text not null default 'ru',
  payload jsonb not null,
  content_hash text not null,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '365 days')
);
create index if not exists collections_send_idx on collections (send_id) where send_id is not null;
create index if not exists collections_expires_idx on collections (expires_at);

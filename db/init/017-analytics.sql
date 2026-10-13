-- Отчёт застройщику (план b2b-03, ADR-0265). Файл применяется на каждом деплое — всё идемпотентно.

-- Заходы без ссылки менеджера: только агрегаты, без идентификаторов людей и адресов.
create table if not exists page_counters (
  day date not null,
  partner_id text not null,
  apartment_id text not null,
  kind text not null,
  lang text not null,
  n integer not null default 0,
  primary key (day, partner_id, apartment_id, kind, lang)
);

-- Ключи страницы отчёта застройщика: в базе только SHA-256 ключа (утечка базы не открывает отчёт).
create table if not exists partner_keys (
  key_hash text primary key,
  partner_id text not null,
  label text,
  active boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists partner_keys_partner_idx on partner_keys (partner_id);

-- Смета-лист (v0.4, ADR-0016). Для свежей БД; для существующей — tools/migrate.mjs.
create table if not exists estimates (
  id text primary key,
  session_id text not null,
  data jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists estimates_session_idx on estimates (session_id);

-- Лог кликов через /go/ — приоритет реф-регистраций.
create table if not exists link_clicks (
  id text primary key,
  estimate_id text not null,
  item_id text not null,
  domain text,
  target_url text not null,
  session_id text,
  created_at timestamptz not null default now()
);
create index if not exists link_clicks_domain_idx on link_clicks (domain);

-- Маршруты реф-программ (late-binding): домен → шаблон реф-URL. Пусто → прямая ссылка.
create table if not exists link_routes (
  domain text primary key,
  network text not null,
  url_template text not null,
  priority integer default 0,
  active boolean not null default true,
  updated_at timestamptz not null default now()
);

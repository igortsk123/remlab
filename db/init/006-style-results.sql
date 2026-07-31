-- Результат игры «узнай свой вкус» (лаборатория, план lab-hub-tabs).
-- Один стиль на анонимную сессию; повторная игра перезаписывает. Для свежей БД; существующая — tools/migrate.mjs.
create table if not exists style_results (
  session_id text primary key,
  style text not null,
  updated_at timestamptz not null default now()
);

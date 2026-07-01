-- Схема каркаса Stage 1 (для свежей БД; для существующей — tools/migrate.mjs).
create table if not exists projects (
  id text primary key,
  session_id text not null,
  data jsonb not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists projects_session_idx on projects (session_id);

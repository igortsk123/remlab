-- Трейсинг пайплайна (ADR-0013): подробный лог каждого вызова LLM.
-- Выполняется один раз при инициализации пустого volume remlab-db.
-- Для существующей БД — tools/migrate.mjs (идемпотентно).

create sequence if not exists generation_seq start 1;

create table if not exists generation_runs (
  id text primary key,
  seq integer not null unique,
  project_id text,
  session_id text,
  pipeline_id text not null,
  pipeline_version text not null,
  status text not null,            -- running | ok | error
  error text,
  total_latency_ms integer,
  total_cost_usd double precision,
  meta jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists gen_runs_seq_idx on generation_runs (seq);
create index if not exists gen_runs_project_idx on generation_runs (project_id);

create table if not exists generation_steps (
  id text primary key,
  run_id text not null,
  idx integer not null,            -- порядок внутри прогона
  step_name text not null,
  kind text not null,              -- vision | image | text
  provider text not null,
  model text not null,
  prompt_id text,
  prompt_version text,
  prompt_text text,
  params jsonb,
  input_text text,
  output_text text,
  status text not null,            -- ok | error
  error_kind text,
  error_message text,
  latency_ms integer,
  cost_usd double precision,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);
create index if not exists gen_steps_run_idx on generation_steps (run_id);

create table if not exists generation_assets (
  id text primary key,
  run_id text not null,
  step_id text,
  role text not null,              -- input | intermediate | output
  mime_type text not null,
  storage_key text not null,       -- относительный путь под TRACE_DIR
  size_bytes integer,
  created_at timestamptz not null default now()
);
create index if not exists gen_assets_run_idx on generation_assets (run_id);

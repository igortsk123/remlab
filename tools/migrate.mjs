// Идемпотентная миграция схемы (для существующей БД). Читает DATABASE_URL из окружения.
// Запуск: pnpm db:migrate  (на сервере — с DATABASE_URL из /opt/remlab/.env).

import postgres from "postgres";

const url = process.env.DATABASE_URL;
if (!url) {
  console.error("DATABASE_URL не задан");
  process.exit(1);
}

const sql = postgres(url, { max: 1 });
try {
  await sql`create extension if not exists vector`;
  await sql`
    create table if not exists projects (
      id text primary key,
      session_id text not null,
      data jsonb not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )`;
  await sql`create index if not exists projects_session_idx on projects (session_id)`;

  // Трейсинг пайплайна (ADR-0013). Sequence — источник «номера генерации».
  await sql`create sequence if not exists generation_seq start 1`;
  await sql`
    create table if not exists generation_runs (
      id text primary key,
      seq integer not null unique,
      project_id text,
      session_id text,
      pipeline_id text not null,
      pipeline_version text not null,
      status text not null,
      error text,
      total_latency_ms integer,
      total_cost_usd double precision,
      meta jsonb,
      started_at timestamptz not null default now(),
      finished_at timestamptz
    )`;
  await sql`create index if not exists gen_runs_seq_idx on generation_runs (seq)`;
  await sql`create index if not exists gen_runs_project_idx on generation_runs (project_id)`;
  await sql`
    create table if not exists generation_steps (
      id text primary key,
      run_id text not null,
      idx integer not null,
      step_name text not null,
      kind text not null,
      provider text not null,
      model text not null,
      prompt_id text,
      prompt_version text,
      prompt_text text,
      params jsonb,
      input_text text,
      output_text text,
      status text not null,
      error_kind text,
      error_message text,
      latency_ms integer,
      cost_usd double precision,
      started_at timestamptz not null default now(),
      finished_at timestamptz
    )`;
  await sql`create index if not exists gen_steps_run_idx on generation_steps (run_id)`;
  await sql`
    create table if not exists generation_assets (
      id text primary key,
      run_id text not null,
      step_id text,
      role text not null,
      mime_type text not null,
      storage_key text not null,
      size_bytes integer,
      created_at timestamptz not null default now()
    )`;
  await sql`create index if not exists gen_assets_run_idx on generation_assets (run_id)`;

  // Смета-лист (v0.4, ADR-0016).
  await sql`
    create table if not exists estimates (
      id text primary key,
      session_id text not null,
      data jsonb not null,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )`;
  await sql`create index if not exists estimates_session_idx on estimates (session_id)`;
  await sql`
    create table if not exists link_clicks (
      id text primary key,
      estimate_id text not null,
      item_id text not null,
      domain text,
      target_url text not null,
      session_id text,
      created_at timestamptz not null default now()
    )`;
  await sql`create index if not exists link_clicks_domain_idx on link_clicks (domain)`;
  await sql`
    create table if not exists link_routes (
      domain text primary key,
      network text not null,
      url_template text not null,
      priority integer default 0,
      active boolean not null default true,
      updated_at timestamptz not null default now()
    )`;

  // Результат игры «узнай свой вкус» (план lab-hub-tabs).
  await sql`
    create table if not exists style_results (
      session_id text primary key,
      style text not null,
      updated_at timestamptz not null default now()
    )`;

  // Проверка ориентации 3D-мешей человеком (ADR-0131, /lab/mesh-review).
  await sql`
    create table if not exists mesh_review_tasks (
      id serial primary key,
      task_key text not null unique,
      sku text not null,
      role text,
      contract text not null,
      payload jsonb not null,
      status text not null default 'open',
      created_at timestamptz not null default now()
    )`;
  await sql`
    create table if not exists mesh_review_decisions (
      id serial primary key,
      task_id integer not null references mesh_review_tasks(id),
      choice text not null,
      reviewer text not null default 'owner',
      idem_key text not null unique,
      created_at timestamptz not null default now()
    )`;
  await sql`create index if not exists mesh_review_tasks_status_idx on mesh_review_tasks (status)`;
  await sql`create index if not exists mesh_review_decisions_task_idx on mesh_review_decisions (task_id)`;

  // Ручная приёмка мешей владельцем (план mesh-owner-audit, /lab/mesh-audit).
  await sql`
    create table if not exists mesh_audit_items (
      id serial primary key,
      sku text not null unique,
      generation_key text not null,
      revision_key text,
      role text,
      name text,
      image_url text,
      poster_url text,
      model_path text not null,
      seed integer,
      attempt integer,
      generated_at timestamptz,
      photo_stale boolean not null default false,
      manual_attempts integer not null default 0,
      status text not null default 'open',
      rework_status text,
      rework_error text,
      redone_at timestamptz,
      seen_at timestamptz,
      created_at timestamptz not null default now(),
      updated_at timestamptz not null default now()
    )`;
  await sql`create index if not exists mesh_audit_items_status_idx on mesh_audit_items (status)`;
  await sql`
    create table if not exists mesh_audit_decisions (
      id serial primary key,
      item_id integer not null,
      sku text not null,
      generation_key text not null,
      verdict text not null,
      manual_attempt_no integer not null,
      reviewer text not null default 'owner',
      idem_key text not null unique,
      created_at timestamptz not null default now()
    )`;
  await sql`create index if not exists mesh_audit_decisions_item_idx on mesh_audit_decisions (item_id)`;
  await sql`create unique index if not exists mesh_audit_decisions_sku_attempt_uq on mesh_audit_decisions (sku, manual_attempt_no)`;
  await sql`
    create table if not exists mesh_audit_batches (
      id serial primary key,
      batch integer not null,
      token text not null unique,
      status text not null default 'requested',
      files_total integer,
      files_done integer,
      bytes_total bigint,
      error text,
      requested_at timestamptz not null default now(),
      activated_at timestamptz,
      removed_at timestamptz,
      updated_at timestamptz not null default now()
    )`;
  await sql`create index if not exists mesh_audit_batches_status_idx on mesh_audit_batches (status)`;

  console.log("migrate: ok");
} finally {
  await sql.end();
}

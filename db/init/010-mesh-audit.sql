-- Ручная приёмка мешей владельцем (план mesh-owner-audit, /lab/mesh-audit).
-- Истина по мешам — на DEV; здесь read-model «одна строка на товар = его текущий меш» (пушит DEV
-- по machine-токену), журнал решений append-only (DEV забирает курсором after_id) и партии
-- публикации моделей (владелец просит партию кнопкой, DEV льёт и отчитывается о прогрессе).
create table if not exists mesh_audit_items (
  id serial primary key,                      -- порядок карточек = порядок регистрации
  sku text not null unique,
  generation_key text not null,               -- текущее физическое поколение (CAS при клике)
  revision_key text,
  role text,
  name text,
  image_url text,                             -- фото товара (CDN магазина)
  poster_url text,                            -- рендер 320px, живёт постоянно
  model_path text not null,                   -- путь модели внутри каталога партии
  seed integer,
  attempt integer,
  generated_at timestamptz,
  photo_stale boolean not null default false,
  manual_attempts integer not null default 0, -- ручные переделки за всё время (≤2)
  status text not null default 'open',        -- open|redo_requested|redo_queued|redo_blocked|replace_needed
  rework_status text,                         -- ACK с DEV
  rework_error text,
  redone_at timestamptz,
  seen_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index if not exists mesh_audit_items_status_idx on mesh_audit_items (status);

create table if not exists mesh_audit_decisions (
  id serial primary key,
  item_id integer not null,
  sku text not null,
  generation_key text not null,
  verdict text not null,                      -- redo | replace_needed
  manual_attempt_no integer not null,         -- 1, 2 — переделки; 3 — «нужна замена»
  reviewer text not null default 'owner',
  idem_key text not null unique,
  created_at timestamptz not null default now()
);
create index if not exists mesh_audit_decisions_item_idx on mesh_audit_decisions (item_id);
create unique index if not exists mesh_audit_decisions_sku_attempt_uq on mesh_audit_decisions (sku, manual_attempt_no);

create table if not exists mesh_audit_batches (
  id serial primary key,
  batch integer not null,
  token text not null unique,
  status text not null default 'requested',   -- requested|uploading|verifying|active|retiring|removed|failed
  files_total integer,
  files_done integer,
  bytes_total bigint,
  error text,
  requested_at timestamptz not null default now(),
  activated_at timestamptz,
  removed_at timestamptz,
  updated_at timestamptz not null default now()
);
create index if not exists mesh_audit_batches_status_idx on mesh_audit_batches (status);

-- Отмена случайного клика (владелец 05.09): решение удаляется, факт отмены — append-only,
-- конвейер забирает курсором after_id и откатывает у себя.
create table if not exists mesh_audit_cancellations (
  id serial primary key,
  decision_id integer not null,
  item_id integer not null,
  sku text not null,
  generation_key text not null,
  verdict text not null,
  manual_attempt_no integer not null,
  created_at timestamptz not null default now()
);
create index if not exists mesh_audit_cancellations_item_idx on mesh_audit_cancellations (item_id);

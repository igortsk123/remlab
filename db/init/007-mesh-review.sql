-- Проверка ориентации 3D-мешей человеком (ADR-0131, план mesh-queue-orientation).
-- Задачи ставит DEV-конвейер (machine-токен), решения кликает владелец на /lab/mesh-review.
-- Решения append-only: конвейер забирает их курсором after_id и применяет у себя.
create table if not exists mesh_review_tasks (
  id serial primary key,
  task_key text not null unique,      -- revision_key ориентации: sku|glb_sha|contract
  sku text not null,
  role text,
  contract text not null,
  payload jsonb not null,             -- рендеры (data-URL), варианты кнопок, evidence
  status text not null default 'open',  -- open|decided|superseded
  created_at timestamptz not null default now()
);
create table if not exists mesh_review_decisions (
  id serial primary key,
  task_id integer not null references mesh_review_tasks(id),
  choice text not null,               -- front_0|front_90|front_180|front_270|symmetric|bad_up|bad_mesh|skip
  reviewer text not null default 'owner',
  idem_key text not null unique,      -- идемпотентность повторного клика
  created_at timestamptz not null default now()
);
create index if not exists mesh_review_tasks_status_idx on mesh_review_tasks (status);
create index if not exists mesh_review_decisions_task_idx on mesh_review_decisions (task_id);

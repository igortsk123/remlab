-- ЧЕРНОВИК (T-20261112-118, шаг 1) · НЕ ПРИМЕНЯТЬ до «ок» владельца на макет. Будущий файл: db/init/034-mesh-audit-marks.sql
-- Перед применением на проде: pg_dump (правило feedback-db-migrations-pilot). Всё только добавляется, старое не меняется.

-- Журнал нажатий «ок» / «брак» / снятие (повторное нажатие). Append-only: каждая строка навсегда, ничего не удаляется.
-- Текущая отметка карточки = последняя строка по (item_id, generation_key); новое поколение меша = карточка снова «не проверена».
create table if not exists mesh_audit_marks (
  id            bigserial primary key,
  item_id       integer     not null,
  sku           text        not null,
  generation_key text       not null,             -- какой именно меш оценён (CAS с mesh_audit_items.generation_key)
  mark          text        not null check (mark in ('ok', 'bad', 'clear')),
  reviewer      text        not null default 'owner',
  decision_id   integer,                          -- «брак» → строка mesh_audit_decisions (та же очередь переделки), если создана
  idem_key      text        not null unique,      -- повтор запроса (сеть, две вкладки) не даёт второй строки
  created_at    timestamptz not null default now()
);
create index if not exists mesh_audit_marks_item_idx on mesh_audit_marks (item_id, id);

-- Комментарий: каждая версия текста — строка (как style_note у страницы стилей). Сохраняется сам: через 1 с после ввода,
-- при уходе из поля и при закрытии вкладки (sendBeacon). Пустая строка = комментарий стёрт (тоже версия).
create table if not exists mesh_audit_notes (
  id            bigserial primary key,
  item_id       integer     not null,
  sku           text        not null,
  generation_key text       not null,
  body          text        not null check (char_length(body) <= 2000),
  reviewer      text        not null default 'owner',
  client_seq    integer     not null,             -- номер версии во вкладке: старая версия, пришедшая позже, не затирает новую
  created_at    timestamptz not null default now()
);
create index if not exists mesh_audit_notes_item_idx on mesh_audit_notes (item_id, id);

-- Быстрый показ страницы и счётчики разделов: текущее состояние прямо в read-model (пишется той же транзакцией, что и журнал).
alter table mesh_audit_items add column if not exists mark       text;          -- ok | bad | null — по ТЕКУЩЕМУ поколению
alter table mesh_audit_items add column if not exists mark_at    timestamptz;
alter table mesh_audit_items add column if not exists note       text;          -- последняя версия комментария
alter table mesh_audit_items add column if not exists section    text;          -- раздел страницы из роли (lib/mesh-audit/sections.ts)
alter table mesh_audit_items add column if not exists poster_hd_url text;       -- снимок 1024 px для увеличения
create index if not exists mesh_audit_items_section_idx on mesh_audit_items (section, id);

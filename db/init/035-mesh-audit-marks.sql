-- Страница проверки мешей /lab/mesh-check (T-20261112-118, владелец TG 1361): «ок»/«брак» и комментарий к каждой модели.
-- Каждое нажатие и каждая версия текста — строка журнала навсегда (append-only, ничего не удаляется); текущее состояние карточки —
-- колонки в mesh_audit_items (пишутся той же транзакцией, новое поколение меша их сбрасывает — `lib/mesh-audit/repo-items.ts`).
-- Только добавления: старые строки не переписываются, прежняя версия приложения новых колонок не видит и не ломается.
-- Идемпотентно (прод применяет все init-файлы на каждом деплое): if not exists + именованные ограничения внутри create table.
-- Перед первым применением на проде — pg_dump.
-- Откат (только руками, после pg_dump):
--   drop table if exists mesh_audit_marks; drop table if exists mesh_audit_notes;
--   alter table mesh_audit_items drop column if exists poster_hd_url, drop column if exists mark, drop column if exists mark_at,
--     drop column if exists mark_by, drop column if exists note, drop column if exists note_seq;

-- Журнал нажатий. Не применённое нажатие (старая вкладка видела другое состояние, модель уже заменена) тоже пишется: applied=false.
create table if not exists mesh_audit_marks (
  id             bigserial   primary key,
  item_id        integer     not null,
  sku            text        not null,
  generation_key text        not null,               -- какой именно меш оценён
  mark           text        not null,               -- ok | bad | clear (повторное нажатие снимает)
  expected       text,                               -- какую отметку видела вкладка (ok | bad | null) — защита от гонки вкладок
  applied        boolean     not null default true,
  reason         text,                               -- почему не применено / что не сделано: stale | state_conflict | queued_kept
  reviewer       text        not null,
  decision_id    integer,                            -- «брак» → строка mesh_audit_decisions (та же очередь переделки)
  cancelled_decision_id integer,                     -- снятие «брака» отменило это решение (факт — в mesh_audit_cancellations)
  idem_key       text        not null,               -- повтор запроса (сеть, двойной тап) не даёт второй строки
  created_at     timestamptz not null default now(),
  constraint mesh_audit_marks_idem_uq unique (idem_key),
  constraint mesh_audit_marks_mark_chk check (mark in ('ok', 'bad', 'clear')),
  constraint mesh_audit_marks_reviewer_len check (char_length(reviewer) between 1 and 40)
);
create index if not exists mesh_audit_marks_item_idx on mesh_audit_marks (item_id, id);

-- Журнал версий комментария. Сохраняется сам: через 1 с после ввода, при уходе из поля и при закрытии вкладки (sendBeacon).
-- op_id — один и тот же пакет из fetch, маяка и повтора даёт одну строку. client_seq — номер версии (растёт в браузере, ≥ время в мс):
-- версия меньше уже принятой журналится с applied=false и текущий текст не затирает. Пустая строка = текст стёрт (тоже версия).
create table if not exists mesh_audit_notes (
  id             bigserial   primary key,
  item_id        integer     not null,
  sku            text        not null,
  generation_key text        not null,
  body           text        not null,               -- как набрано, без обрезки пробелов
  reviewer       text        not null,
  editor_id      text        not null,               -- вкладка/устройство (uuid из браузера)
  client_seq     bigint      not null,
  applied        boolean     not null default true,
  reason         text,                               -- stale (модель уже заменена) | older (пришла позже более новой версии)
  op_id          text        not null,
  created_at     timestamptz not null default now(),
  constraint mesh_audit_notes_op_uq unique (op_id),
  constraint mesh_audit_notes_body_len check (char_length(body) <= 2000),
  constraint mesh_audit_notes_reviewer_len check (char_length(reviewer) between 1 and 40)
);
create index if not exists mesh_audit_notes_item_idx on mesh_audit_notes (item_id, id);

-- Текущее состояние по ТЕКУЩЕМУ поколению (раздел считается из role в коде — `lib/mesh-audit/sections.ts`).
alter table mesh_audit_items add column if not exists poster_hd_url text;   -- снимок 1024 px для увеличения
alter table mesh_audit_items add column if not exists mark text
  constraint mesh_audit_items_mark_chk check (mark in ('ok', 'bad'));
alter table mesh_audit_items add column if not exists mark_at timestamptz;
alter table mesh_audit_items add column if not exists mark_by text;
alter table mesh_audit_items add column if not exists note text;            -- последняя принятая версия комментария
alter table mesh_audit_items add column if not exists note_seq bigint;      -- её client_seq

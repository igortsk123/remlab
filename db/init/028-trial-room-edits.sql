-- Правка комнаты в туре пробы (план trial-room-edit-01, Е3; T-20261110-36): агент со своей ссылкой поправил название и/или габариты
-- комнаты на плане тура. Правка хранится ОТДЕЛЬНО от прочитанного плана (`trial_jobs.result` остаётся как прочитан): воркер накладывает
-- её на копию результата перед КАЖДОЙ сборкой — пересборка правки (`trial_rebuilds.kind = 'edit'`), «Обустроить» и перечитывание
-- по тексту агента (`listing` заменяет `result` — правка не теряется). Комната — по (`panel`, `src_id`) прочитанного плана; если при
-- перечитывании id сменились — по `anchor` (центр комнаты в долях охвата панели), единственное совпадение, иначе правка не ложится.
-- `w_cm`/`d_cm` — габариты (охват контура по осям листа) после правки; null — габариты как прочитаны (правили только название).
-- `built` — правка уже вошла в опубликованную версию (воркер пересобирает комнаты, у которых false).
-- Строки снимаются вместе с заданием (on delete cascade). Файл применяется на КАЖДОМ деплое — всё идемпотентно.
-- Перед применением на проде — pg_dump. Откат (только руками, после pg_dump):
--   drop table if exists trial_room_edits;
--   alter table trial_rebuilds drop constraint if exists trial_rebuilds_kind_chk;
--   alter table trial_rebuilds add constraint trial_rebuilds_kind_chk check (kind in ('furnish', 'listing'));  -- если строк 'edit' нет

create table if not exists trial_room_edits (
  job_id      text not null references trial_jobs(id) on delete cascade,
  room_key    text not null,                       -- `<panel>|<src_id>` — один ряд на комнату прочитанного плана
  panel       text not null,
  src_id      text not null,
  anchor      jsonb not null,                      -- {"x": 0..1, "y": 0..1} — центр охвата комнаты в охвате всех комнат панели
  name        text not null,
  kind        text not null,
  w_cm        integer,
  d_cm        integer,
  built       boolean not null default false,
  request_id  text not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (job_id, room_key),
  constraint trial_room_edits_kind_chk check (kind in ('living', 'bedroom', 'kitchen', 'bathroom', 'hall', 'other')),
  constraint trial_room_edits_name_len check (char_length(name) between 1 and 60),
  constraint trial_room_edits_dims check ((w_cm is null) = (d_cm is null) and (w_cm is null or (w_cm between 50 and 5000 and d_cm between 50 and 5000)))
);

-- набор видов — как в `025`/`031` (`reparse` — перечитать планировку, T-20261111-02): файлы применяются по порядку на каждом деплое
alter table trial_rebuilds drop constraint if exists trial_rebuilds_kind_chk;
alter table trial_rebuilds add constraint trial_rebuilds_kind_chk check (kind in ('furnish', 'listing', 'edit', 'reparse'));

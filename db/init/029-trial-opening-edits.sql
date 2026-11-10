-- Окна и двери агента на плане тура пробы (план trial-room-edit-01, Е4; T-20261110-39; владелец TG 871): агент со своей ссылкой щёлкает
-- по стене плана, ставит окно или дверь и растягивает до нужной ширины, двигает или снимает распознанный проём («ложная дверь»).
-- Как правки комнат (028): правка хранится ОТДЕЛЬНО от прочитанного плана (`trial_jobs.result` остаётся как прочитан); воркер
-- накладывает её на копию результата перед КАЖДОЙ сборкой, после правок комнат (`tools/floorplan/opening_edits.py`); пересборка —
-- та же `trial_rebuilds.kind = 'edit'`. Комнаты правка проёма не трогает — у неё своя таблица и свой шаг.
-- Ряд — один проём панели: `op_key` = `<panel>|s<номер>` — распознанный (номер в `result` и центр как прочитан `src_c`: по нему проём
-- находится, если перечитывание плана сменило номера), `<panel>|u<токен>` — добавленный агентом. `removed` — проём снят (у добавленного —
-- просто не ставится). `c` — центр на стене, `width_cm` — ширина, см листа как прочитано (исходные стены, `trial_room.openings_of`).
-- `built` — правка уже вошла в опубликованную версию (воркер пересобирает комнаты, чьих стен коснулись правки с false).
-- Строки снимаются вместе с заданием (on delete cascade). Файл применяется на КАЖДОМ деплое — всё идемпотентно.
-- Перед применением на проде — pg_dump. Откат (только руками, после pg_dump): drop table if exists trial_opening_edits;

create table if not exists trial_opening_edits (
  job_id      text not null references trial_jobs(id) on delete cascade,
  op_key      text not null,                       -- `<panel>|s<номер>` или `<panel>|u<токен>`
  panel       text not null,
  src_idx     integer,                             -- номер распознанного проёма в `result` (null — добавленный)
  src_c       jsonb,                               -- [x, y] — центр распознанного как прочитан (null — добавленный)
  kind        text not null,
  c           jsonb not null,                      -- [x, y], см листа
  width_cm    integer not null,
  removed     boolean not null default false,
  built       boolean not null default false,
  request_id  text not null,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (job_id, op_key),
  constraint trial_opening_edits_kind_chk check (kind in ('door', 'window')),
  constraint trial_opening_edits_width check (width_cm between 30 and 600),
  constraint trial_opening_edits_src check ((src_idx is null) = (src_c is null))
);

create index if not exists trial_opening_edits_request on trial_opening_edits (job_id, request_id);

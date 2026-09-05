-- КАТАЛОЖНАЯ миграция дев-БД (номер 008: 007 уже занят photo-origin) `remlab-devdb` (применяет `tools/scout/db_migrate.py`).
-- План mesh-owner-audit (05.09): ручная приёмка мешей владельцем.
--
-- ЗАЧЕМ ОТДЕЛЬНАЯ ТАБЛИЦА ПОКОЛЕНИЙ. `asset_revisions` — логическая ревизия «товар × фото ×
-- версия конвейера» (`sku|sha16|v1`), и её ключ читают точным равенством (`mesh_scheduler`) и
-- префиксом (`mesh_ready`, `enforce_ready_invariant`) — менять его нельзя. Но один и тот же
-- товар с тем же фото генерируется несколько раз (seed 0, 1, 2…), и все попытки писались в ОДНУ
-- строку: отказ владельца адресовать было нечему, а «текущим» становился тот файл, который реестр
-- прочитал последним по алфавиту (разбор Codex 05.09). Здесь каждая физическая модель — своя
-- строка, а ревизия и карточка товара хранят ЯВНЫЙ указатель на текущее поколение.
create table if not exists mesh_generations (
  generation_key    text primary key,          -- sku|sha16|pipeline|seed|glb8
  sku               text not null,
  source_sha        text not null,             -- input_hash из манифеста (16 знаков)
  pipeline_version  text not null,             -- версия конвейера scout (как в revision_key)
  seed              int  not null,
  glb_sha           text not null,             -- sha256(model.glb)[:16] — как в asset_revisions
  job_id            text not null,             -- каталог поколения на DEV
  path              text not null,             -- абсолютный путь к каталогу поколения
  glb_bytes         bigint,                    -- размер и mtime model.glb: хеш пересчитывается
  glb_mtime         double precision,          -- только когда они изменились (11 ГБ за прогон иначе)
  generated_at      timestamptz not null,      -- mtime model.glb; по нему выбирается «текущее»
  machine_verdict   text,                      -- verdict.json.status приёмки (generated|flat_shape|…)
  owner_verdict     text,                      -- null | redo | replace_needed — ТОЛЬКО человек
  owner_decision_id int,                       -- id решения на проде (идемпотентность применения)
  owner_verdict_at  timestamptz,
  created           timestamptz default now(),
  updated           timestamptz default now()
);
create index if not exists mesh_generations_sku_idx on mesh_generations (sku, generated_at desc);
create index if not exists mesh_generations_owner_idx on mesh_generations (owner_verdict)
  where owner_verdict is not null;

-- Явный указатель «какое поколение сейчас представляет ревизию / стоит в карточке товара».
-- Без него нельзя атомарно доказать, какой именно файл отвергнут (CAS при отказе владельца).
alter table asset_revisions add column if not exists current_generation_key text;
alter table products        add column if not exists mesh_generation_key text;

-- Инбокс переделок по решению владельца. Живая очередь (`mesh-queue-*.json`) НЕ редактируется:
-- регламент `rules/mesh-priority.json` §identity запрещает позиционный курсор по перестроенной
-- очереди. Запрос попадает в снимок при его сборке (`mesh_priority.py --build-queue`) и получает
-- `queued` только после атомарной записи файла; до этого он честно «requested».
create table if not exists mesh_rework_requests (
  id                       serial primary key,
  prod_decision_id         int  not null unique,   -- решение на проде: одно применение
  sku                      text not null,
  source_sha               text,
  pipeline_version         text not null default 'v1',
  rejected_generation_key  text not null,
  manual_attempt_no        int  not null,          -- 1 | 2 — ручной счёт владельца (авто не считается)
  next_seed                int,                    -- резервирует allocator при сборке снимка
  status                   text not null default 'requested',
                           -- requested | queued | running | done | blocked | cancelled
  queue_build_id           text,                   -- имя снимка, в который попало задание
  error                    text,
  created                  timestamptz default now(),
  updated                  timestamptz default now(),
  unique (sku, manual_attempt_no)
);
create index if not exists mesh_rework_requests_status_idx on mesh_rework_requests (status);

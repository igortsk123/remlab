-- ПРИВЯЗКА ТОВАР → МЕШ (room-pipeline-01 В-1а, T-20261105-45; разбор Codex _intake/codex/room-bind-2026-11-05-answer.md;
-- владелец 05.11 TG 126: «можешь править базу»). Вывод из фактов БД и диска, не первичные данные: пишет ТОЛЬКО
-- `room_bindings.py --build` одной транзакцией (полная замена: delete всё + insert снимка snapshot_id), рядом тот же снимок
-- файлом ~/scout-scenes/catalog-assets/v1/bindings-<snapshot_id>.json (откат и разбор). Читает catalog_items(with_assets=True).
-- Ключ — товар (shop_mid, external_id) БЕЗ комнаты и роли: товар в двух комнатах — одна привязка. Внешних ключей нет
-- (у room_catalog в ключе комната; товар room_catalog может отсутствовать в products). Ассет — полный sha256 model.glb.
create table if not exists offer_asset_binding (
  shop_mid integer not null,
  external_id text not null,
  status text not null check (status in ('ready', 'blocked')),
  asset_id text,                      -- sha256:<64> файла model.glb; null — файла/ревизии текущего фото нет
  mesh_id text,                       -- mid_eid товара-владельца меша (у варианта — представителя); ключ mesh-index прода
  local_path text,                    -- путь к model.glb на DEV (папка поколения); для локального 3D
  generation_key text,                -- mesh_generations.generation_key (текущая попытка ревизии, не свежая по mtime)
  revision_key text,                  -- asset_revisions.revision_key
  source_sha text,                    -- хеш фото генерации (16, как в ключе ревизии)
  representative_mid integer,         -- вариант семьи: представитель по products.mesh_family_rep
  representative_eid text,
  via_family boolean not null default false,
  family_id text,                     -- mesh-family:v1:<sha16 mesh_family>
  reasons jsonb not null default '[]',   -- почему не ready; пусто у ready
  warnings jsonb not null default '[]',
  solver boolean not null,            -- габарит каталога есть (+ footprint_ok у room_catalog)
  local_3d boolean not null,          -- файл цел, sha совпал, брака нет, ориентация решена для этого sha, паспорт сошёлся
  appearance boolean not null,        -- свой меш или вариант того же цвета
  published_3d boolean not null,      -- на проде нужный файл (индекс + размер); только чтение, публикация — В-1б
  passport jsonb,                     -- {status, catalog_dims, hash, asset_dims_cm, role}
  orientation jsonb,                  -- {revision_key, status, source, contract, resolution_sha, yaw_deg, quat_wxyz}
  photo jsonb,                        -- {basis hash|url, current_sha}
  seen_in jsonb not null default '[]',   -- [[комната, роль, origin], …] — справка, не ключ
  policy_version text not null,       -- rules/catalog-bindings.json
  snapshot_id text not null,          -- content_sha снимка (64); файл bindings-<первые 16>.json
  built_at timestamptz not null,
  primary key (shop_mid, external_id)
);
create index if not exists offer_asset_binding_status on offer_asset_binding (status);
comment on table offer_asset_binding is 'Привязка товар→меш (T-20261105-45). Пишет только room_bindings.py --build (полная замена в транзакции); снимок-файл ~/scout-scenes/catalog-assets/v1/bindings-<sha16>.json';

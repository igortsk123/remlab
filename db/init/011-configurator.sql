-- Сохранённые подборы 3D-конфигуратора квартиры (план apartment-3d-configurator, ADR-0210).
--
-- Пишет: POST /api/flat/config (кнопка «сохранить подбор» у покупателя).
-- Читает: GET /api/flat/config/<id> — открыть ссылку, и менеджер продаж/CRM.
--
-- ПОЧЕМУ ТАК (разбор Codex 28.09):
--  * `id` — случайный публичный токен, по нему нельзя перебрать чужие подборы;
--  * контакт покупателя хранится ОТДЕЛЬНЫМ полем и НИКОГДА не отдаётся публичным GET;
--  * `quote` — снимок цены на момент сохранения: каталог меняется, а обещанная цена нет;
--  * `*_revision` — чтобы через месяц понять, из какой версии каталога собран подбор.
-- Файл применяется на КАЖДОМ деплое, поэтому всё идемпотентно.

create table if not exists flat_configs (
  id text primary key,
  apartment_id text not null,
  developer_id text not null,
  schema_version integer not null default 1,
  apartment_revision text,
  catalogue_revision text,
  selections jsonb not null,
  quote jsonb not null,
  contact jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists flat_configs_created_idx on flat_configs (created_at desc);
create index if not exists flat_configs_developer_idx on flat_configs (developer_id, created_at desc);

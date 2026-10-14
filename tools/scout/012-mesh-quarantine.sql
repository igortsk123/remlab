-- Карантин моделей по осям (план conv-04, ADR-0276; дев-база каталога). Модель, у которой ширина или глубина
-- расходится с паспортом товара больше порога (rules/mesh-quarantine.json), выводится из готовых: статус ревизии
-- `quarantine`, прежний статус хранится здесь — решение владельца возвращает его или отправляет в брак.
create table if not exists mesh_quarantine (
  sku text not null,
  glb_sha text not null,          -- 16 знаков, как в asset_revisions
  prev_status text not null,
  axis text, dev numeric, dw numeric, dd numeric,
  threshold numeric not null,
  created timestamptz not null default now(),
  decision text,                  -- accept | reject | cut (кнопки на /test/mesh-quarantine/)
  comment text,
  decided_at timestamptz,
  primary key (sku, glb_sha)
);

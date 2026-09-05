-- КАТАЛОЖНАЯ миграция дев-БД `remlab-devdb` (применяет `tools/scout/db_migrate.py`).
-- Семейства моделей (владелец 05.09): один меш на модель, цвета/ткани — варианты одной формы.
-- `mesh_family` — ключ семейства (`tools/scout/mesh_family.py`), `mesh_family_rep` — sku
-- представителя, чей меш считается мешом семейства. У представителя rep = свой sku.
-- Варианты в очередь не встают; готовность и ссылка на меш у них — от представителя.
alter table products add column if not exists mesh_family text;
alter table products add column if not exists mesh_family_rep text;
create index if not exists products_mesh_family_idx on products (mesh_family) where mesh_family is not null;
create index if not exists products_mesh_family_rep_idx on products (mesh_family_rep) where mesh_family_rep is not null;

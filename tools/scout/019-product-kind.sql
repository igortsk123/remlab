-- КАТАЛОЖНАЯ миграция дев-БД `remlab-devdb` (применяет `tools/ops/db-migrate-safe.sh` / `tools/scout/db_migrate.py`; T-20261124-08/2).
-- «Что за товар» отдельно от «какая у мебели роль»: комплектующие (штанги, ролики, рамки…) не мебель, но данные нужны будущей смете.
-- Писатель один — `tools/scout/component_guard.py` (правило Г, rules/component-guard.json). Все колонки NULL у обычных товаров;
-- до первого прогона правила данные не меняются.
--   product_kind — NULL (обычный) | 'component' (комплектующее: cat_role = NULL, строка грузится, в архив не уходит);
--   kind_reason  — почему снято (карантин без размеров + предок/слова), строкой;
--   role_before  — роль, снятая при переходе в component, для возврата.
-- Откат: alter table products drop column if exists product_kind, drop column if exists kind_reason, drop column if exists role_before;
--        (перед откатом вернуть роли: update products set cat_role = role_before where product_kind = 'component';)
alter table products add column if not exists product_kind text;
alter table products add column if not exists kind_reason text;
alter table products add column if not exists role_before text;
create index if not exists products_kind_idx on products (product_kind) where product_kind is not null;

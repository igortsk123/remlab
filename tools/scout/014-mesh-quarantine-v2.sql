-- Карантин v2 (14.10, разметка владельца + разбор Codex): причины — независимые признаки, версия замера.
alter table mesh_quarantine add column if not exists reasons text;        -- mask,slab,proportion через запятую
alter table mesh_quarantine add column if not exists metric_version integer not null default 1;
alter table mesh_quarantine add column if not exists slab text;           -- component | merged
alter table mesh_quarantine add column if not exists mask text;           -- причина плохой вырезки из manifest

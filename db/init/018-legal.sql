-- Согласия и сроки хранения (план b2b-04, ADR-0268). Файл применяется на каждом деплое — всё идемпотентно.

-- На какой версии текста политики человек дал согласие (lib/legal/policy.ts:POLICY_VERSION).
alter table leads add column if not exists consent_version text;
alter table share_requests add column if not exists consent_version text;

-- Журнал удаления по срокам: что, сколько и по какому сроку удалено (проверка «данные не живут дольше»).
create table if not exists retention_runs (
  id bigserial primary key,
  kind text not null,          -- traces | leads | flat_contacts
  days integer,                -- срок; null — срок не задан владельцем, ничего не удалялось
  deleted integer not null default 0,
  ran_at timestamptz not null default now()
);
create index if not exists retention_runs_ran_idx on retention_runs (ran_at desc);

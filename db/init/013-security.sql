-- Безопасность перед показом застройщику (план b2b-01-security-hardening, ADR-0248).
-- Файл применяется на КАЖДОМ деплое — всё идемпотентно.

-- Счётчики частоты: фиксированное окно на ключ («parse-link:ip:1.2.3.4», «paid:gen:day»).
-- Пишет `lib/ratelimit.ts` одним upsert-ом; старые окна чистит он же, изредка.
create table if not exists rate_limits (
  key text not null,
  window_start timestamptz not null,
  count integer not null default 0,
  primary key (key, window_start)
);
create index if not exists rate_limits_window_idx on rate_limits (window_start);

-- Заявки «отправить подборку себе» с демо. Раньше контакт лежал JSON-файлом в папке, которую
-- раздавал Caddy с листингом (инцидент 13.10) — теперь только здесь. Контакт — ПДн: хранится
-- до `expires_at` и удаляется приложением; наружу не отдаётся ни одним публичным маршрутом.
create table if not exists share_requests (
  id text primary key,
  share_id text not null,
  share_url text not null,
  channel text not null,
  contact text not null,
  shot_count integer not null default 0,
  ip text,
  status text not null default 'pending',
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '90 days')
);
create index if not exists share_requests_created_idx on share_requests (created_at desc);
create index if not exists share_requests_expires_idx on share_requests (expires_at);

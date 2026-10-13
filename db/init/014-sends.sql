-- Персональная ссылка от менеджера и сигналы ему (план b2b-02, ADR-0257).
-- Данных ПОКУПАТЕЛЯ здесь нет: менеджер пишет боту «Вася, кв 215», мы храним только id его
-- сообщения (чтобы сигналы приходили ответом на него), но не текст. Файл применяется на каждом
-- деплое — всё идемпотентно.

-- Менеджеры застройщика (сотрудники; их контакты показываются покупателю на странице).
create table if not exists managers (
  id text primary key,
  partner_id text not null,
  display_name text not null,
  public_phone text,             -- рабочий телефон для покупателей
  public_telegram text,          -- username без @
  public_whatsapp text,          -- номер для wa.me, только цифры
  connect_phone text,            -- номер, по которому менеджер привязывает Telegram (может отличаться)
  tg_user_id bigint,
  tg_chat_id bigint,
  page_key text not null unique, -- секрет страницы менеджера (128 бит), живёт в #фрагменте адреса
  active boolean not null default true,
  created_at timestamptz not null default now()
);
create index if not exists managers_partner_idx on managers (partner_id);

-- Отправка ссылки: одна запись = одна ссылка одному покупателю.
create table if not exists sends (
  id text primary key,           -- публичный токен 128 бит (base64url, 22 символа)
  partner_id text not null,
  apartment_id text not null,
  manager_id text not null,
  lang text not null default 'ru',
  market text not null default 'ru',
  status text not null default 'sent',
  created_via text not null,     -- bot | page | crm
  origin_chat_id bigint,         -- чат и сообщение менеджера «Вася, кв 215» — сигналы идут ответом на него
  origin_message_id bigint,
  revoked boolean not null default false,
  opened_at timestamptz,
  open_signal_at timestamptz,    -- когда последний раз сигналили «открыл»
  summary_due_at timestamptz,    -- когда отправить сводку выбора (антишум)
  status_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists sends_manager_idx on sends (manager_id, created_at desc);
create index if not exists sends_partner_idx on sends (partner_id, created_at desc);
create index if not exists sends_summary_due_idx on sends (summary_due_at) where summary_due_at is not null;

-- События по отправке: действия покупателя и смены статуса (кто/с какого/на какой).
create table if not exists send_events (
  id bigserial primary key,
  send_id text not null,
  kind text not null,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists send_events_send_idx on send_events (send_id, created_at);

-- Очередь сигналов менеджеру: доставка с повторами, ничего не теряется при недоступном Telegram.
create table if not exists signal_outbox (
  id bigserial primary key,
  send_id text not null,
  manager_id text not null,
  kind text not null,
  text text not null,
  status text not null default 'pending',   -- pending | sent | failed | no_channel
  attempts integer not null default 0,
  next_at timestamptz not null default now(),
  last_error text,
  sent_at timestamptz,
  created_at timestamptz not null default now()
);
create index if not exists signal_outbox_due_idx on signal_outbox (status, next_at);

-- Входящие обновления Telegram уже обработаны: Telegram повторяет вебхук при сбое.
create table if not exists tg_updates (
  update_id bigint primary key,
  created_at timestamptz not null default now()
);

-- Лиды «найти дешевле» (К6). email — ПДн: собирать только по согласию; юр. часть — TODO (CLAUDE.md).
CREATE TABLE IF NOT EXISTS leads (
  id text PRIMARY KEY,
  email text,
  channel text NOT NULL,
  url text,
  city text,
  kind text,
  session_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS leads_session_idx ON leads (session_id);
-- Город лида (раунд 2): добавляем идемпотентно для уже существующих БД.
ALTER TABLE leads ADD COLUMN IF NOT EXISTS city text;

-- П7 лид-канал: человекочитаемый номер заявки, регион по IP, привязка чата мессенджера, статус.
CREATE SEQUENCE IF NOT EXISTS leads_no_seq;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS lead_no integer;
ALTER TABLE leads ALTER COLUMN lead_no SET DEFAULT nextval('leads_no_seq');
ALTER TABLE leads ADD COLUMN IF NOT EXISTS ip_region text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS messenger_chat_id text;
ALTER TABLE leads ADD COLUMN IF NOT EXISTS status text;

-- Сообщения по заявке: маппинг «сообщение в служебном TG-боте ↔ заявка» для ответов реплаем.
CREATE TABLE IF NOT EXISTS lead_messages (
  id text PRIMARY KEY,
  lead_id text NOT NULL,
  direction text NOT NULL, -- in (от клиента) | out (ответ владельца)
  text text NOT NULL,
  admin_tg_message_id bigint, -- id карточки/пересылки в СЛУЖЕБНОМ боте (по нему ищем заявку у reply)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS lead_messages_lead_idx ON lead_messages (lead_id);
CREATE INDEX IF NOT EXISTS lead_messages_admin_msg_idx ON lead_messages (admin_tg_message_id);

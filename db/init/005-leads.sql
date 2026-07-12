-- Лиды «найти дешевле» (К6). email — ПДн: собирать только по согласию; юр. часть — TODO (CLAUDE.md).
CREATE TABLE IF NOT EXISTS leads (
  id text PRIMARY KEY,
  email text,
  channel text NOT NULL,
  url text,
  kind text,
  session_id text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS leads_session_idx ON leads (session_id);

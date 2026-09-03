-- Честность наличия (план stock-and-dims-honesty, Н1, 03.09.2026). Идемпотентно.
--
-- 1) Наблюдение получает СТРУКТУРУ вместо свободного текста reason:
--    disposition   — судьба наблюдения: accepted | quarantined | anchor | shadow.
--                    Только accepted участвуют в свёртке и в исторической норме гейта
--                    (раньше карантинный ложный 404 «всплывал» в следующем прогоне через 90-дневную историю);
--    response_kind — http | transport_error | redirect;
--    failure_kind  — почему НЕ смогли проверить: timeout|dns|tls|rate_limit|server_error|challenge|
--                    no_signal|redirected|http_error (404 — не сбой, а свидетельство);
--    evidence_kind — чем доказан вердикт: schema | inline_stock | http_gone | none.
alter table product_page_observation add column if not exists disposition   text not null default 'accepted';
alter table product_page_observation add column if not exists response_kind text;
alter table product_page_observation add column if not exists failure_kind  text;
alter table product_page_observation add column if not exists evidence_kind text;
create index if not exists idx_ppo_disp on product_page_observation (disposition);
-- бэкфилл evidence_kind по прежним текстовым причинам (одноразово, только где пусто)
update product_page_observation set evidence_kind = case
    when verdict in ('gone') and coalesce(reason,'') like 'http 4%' then 'http_gone'
    when verdict in ('alive','oos') and coalesce(reason,'') like 'schema%' then 'schema'
    else 'none' end
 where evidence_kind is null;
update product_page_observation set failure_kind = case
    when verdict <> 'unknown' then null
    when coalesce(reason,'') like 'антибот%' then 'challenge'
    when coalesce(reason,'') like 'http 4%' or coalesce(reason,'') like 'http 5%' then 'http_error'
    when coalesce(reason,'') like 'не проверилось: URLError: <urlopen error timed out%' then 'timeout'
    when coalesce(reason,'') like 'не проверилось:%' then 'transport'
    when coalesce(reason,'') like 'редирект%' then 'redirected'
    when coalesce(reason,'') like '200 без%' then 'no_signal'
    else null end
 where failure_kind is null and verdict = 'unknown';

-- 2) Ссылка карточки: негатив действует только по ТЕКУЩЕЙ ссылке. `page_alive.url_key()` — Python,
--    поэтому хеш текущей `direct_url` материализует load3 в products.direct_url_hash, а формула
--    наличия сверяет его с `product_page_status.url_hash` (раньше починенная ссылка оставалась «снятой»
--    до следующей проверки).
alter table products add column if not exists direct_url_hash text;

-- 3) Здоровье домена (антибот, блокировка, «сайт лежит») — свойство хоста и версии пробника, а не
--    партнёрской программы, поэтому НЕ в shop_status.
create table if not exists probe_domain_status (
  host          text primary key,
  probe_version int  not null default 1,
  policy        text not null default 'auto',     -- auto | disabled (владелец/антибот подтверждён)
  state         text not null default 'open',     -- open | blocked
  blocked_until timestamptz,
  reason        text,
  checked_at    timestamptz not null default now(),
  last_probe_at timestamptz                       -- последняя недельная проба выключенного домена
);
-- mdm-complect: Яндекс SmartCaptcha (307 → ?_ycch), единственный подтверждённый антибот (03.09)
insert into probe_domain_status (host, policy, state, reason)
values ('mdm-complect.ru', 'disabled', 'blocked', 'Яндекс SmartCaptcha, антибот подтверждён 03.09')
on conflict (host) do nothing;

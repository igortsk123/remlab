#!/usr/bin/env bash
# Завести (или обновить) менеджера застройщика и получить ссылку на его страницу (план b2b-02).
# На сервере:  /opt/remlab/scripts/manager-add.sh --partner demo --name "Анна" --phone "+7 913 000-00-00" \
#                [--telegram anna_sales] [--whatsapp "+7 913 …"] [--connect-phone "+7 913 …"] [--id demo-anna] [--rotate-key]
# Значения уходят в psql переменными (:'x') — кавычки в имени SQL не ломают.
# Номер для подключения к боту нормализуется так же, как `modules/sends/phone.ts`.
set -euo pipefail
declare -A A=([rotate-key]=0)
while [ $# -gt 0 ]; do
  case "$1" in --rotate-key) A[rotate-key]=1; shift;; --*) A[${1#--}]="${2:-}"; shift 2;; *) echo "лишний аргумент $1"; exit 1;; esac
done
[ -n "${A[partner]:-}" ] && [ -n "${A[name]:-}" ] || { echo "нужны --partner и --name"; exit 1; }
norm() {
  local d; d=$(printf '%s' "$1" | tr -cd '0-9')
  if [ ${#d} -eq 11 ] && [ "${d:0:1}" = 8 ]; then d="7${d:1}"
  elif [ ${#d} -eq 10 ] && [ "${d:0:1}" = 9 ]; then d="7$d"
  elif [ ${#d} -eq 11 ] && [ "${d:0:2}" = 07 ]; then d="44${d:1}"; fi
  if [ ${#d} -ge 11 ] && [ ${#d} -le 15 ]; then printf '%s' "$d"; fi
}
ID=${A[id]:-${A[partner]}-$(openssl rand -hex 4)}
KEY=$(openssl rand -base64 16 | tr '+/' '-_' | tr -d '=\n')
CONNECT=$(norm "${A[connect-phone]:-${A[phone]:-}}")
WA=$(norm "${A[whatsapp]:-}")
TG=${A[telegram]:-}; TG=${TG#@}
docker exec -i remlab-db psql -U remlab -d remlab -qtA -v ON_ERROR_STOP=1 \
  -v id="$ID" -v partner="${A[partner]}" -v name="${A[name]}" -v phone="${A[phone]:-}" -v tg="$TG" \
  -v wa="$WA" -v connect="$CONNECT" -v key="$KEY" -v rotate="${A[rotate-key]}" <<'SQL'
insert into managers (id, partner_id, display_name, public_phone, public_telegram, public_whatsapp, connect_phone, page_key)
values (:'id', :'partner', :'name', nullif(:'phone', ''), nullif(:'tg', ''), nullif(:'wa', ''), nullif(:'connect', ''), :'key')
on conflict (id) do update set display_name = excluded.display_name, public_phone = excluded.public_phone,
  public_telegram = excluded.public_telegram, public_whatsapp = excluded.public_whatsapp, connect_phone = excluded.connect_phone,
  page_key = case when :'rotate' = '1' then excluded.page_key else managers.page_key end
returning 'менеджер ' || id || ': страница https://remont-lab.online/manager#' || page_key;
SQL
[ -n "$CONNECT" ] && echo "подключение к боту по номеру $CONNECT" || echo "номер для бота не задан — бот этого менеджера не узнает"

#!/usr/bin/env bash
# Выдать застройщику ссылку на отчёт по ссылкам покупателям (план b2b-03, ADR-0265).
# На сервере:  /opt/remlab/scripts/partner-key-add.sh --partner demo [--label "Отдел продаж"]
#              /opt/remlab/scripts/partner-key-add.sh --partner demo --revoke-all   # отозвать все ссылки застройщика
# В базе хранится только SHA-256 ключа: сам ключ печатается один раз — потерян, значит выдать новый.
set -euo pipefail
PARTNER=""; LABEL=""; REVOKE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --partner) PARTNER="${2:-}"; shift 2;;
    --label) LABEL="${2:-}"; shift 2;;
    --revoke-all) REVOKE=1; shift;;
    *) echo "лишний аргумент $1"; exit 1;;
  esac
done
[ -n "$PARTNER" ] || { echo "нужен --partner"; exit 1; }
if [ "$REVOKE" = 1 ]; then
  docker exec -i remlab-db psql -U remlab -d remlab -qtA -v ON_ERROR_STOP=1 -v partner="$PARTNER" <<'SQL'
update partner_keys set active = false where partner_id = :'partner' and active returning 'отозвана ссылка ' || coalesce(label, '');
SQL
  exit 0
fi
KEY=$(openssl rand -base64 16 | tr '+/' '-_' | tr -d '=\n')
HASH=$(printf '%s' "$KEY" | sha256sum | cut -d' ' -f1)
docker exec -i remlab-db psql -U remlab -d remlab -qtA -v ON_ERROR_STOP=1 -v h="$HASH" -v partner="$PARTNER" -v label="$LABEL" <<'SQL' >/dev/null
insert into partner_keys (key_hash, partner_id, label) values (:'h', :'partner', nullif(:'label', ''));
SQL
echo "отчёт застройщика $PARTNER: https://remont-lab.online/partner/report#$KEY"

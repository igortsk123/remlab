#!/usr/bin/env bash
# Проверки DEV для дайджеста (план b2b-09, ADR-0266): шаг `dev_checks` в tools/scout/refresh_daily.sh.
# Печатает `WARN:<код>: текст` — дайджест покажет. Ничего не чистит: что можно чистить — в
# .memory_bank/domain/deployment-details.md § «DEV: диск».
set -uo pipefail
LIMIT=${DEV_DISK_WARN:-85}
use=$(df --output=pcent / | tail -1 | tr -dc '0-9')
echo "диск DEV: ${use}% (порог ${LIMIT}%)"
[ "${use:-0}" -ge "$LIMIT" ] && echo "WARN:dev_disk: диск DEV занят на ${use}% — ночной прогон и волна мешей встанут на 100% (что чистить — deployment-details § DEV: диск)"
B=$HOME/remlab-backups
last=$(grep ' ok ' "$B/pull.log" 2>/dev/null | tail -1 | cut -d' ' -f1)
if [ -z "$last" ]; then
  echo "WARN:backup_offsite: копии прод-базы на DEV нет (tools/ops/backup-pull.sh)"
else
  age_h=$(( ( $(date +%s) - $(date -d "$last" +%s) ) / 3600 ))
  echo "копия прод-базы на DEV: $age_h ч назад"
  [ "$age_h" -le 48 ] || echo "WARN:backup_offsite: последняя копия прод-базы на DEV — $age_h ч назад"
fi
drill=$(tail -1 "$B/drill.log" 2>/dev/null)
case "$drill" in *" ok "*) echo "репетиция восстановления: ${drill%% *}";; *) echo "WARN:restore_drill: последняя репетиция восстановления не прошла или не было (${drill:0:120})";; esac
# каналы LLM (13.10: все три оказались без денег, заметили случайно): крошечный запрос, ответ «нет денег» → WARN
ENVS="$(dirname "$0")/../scout/.env"
if [ -f "$ENVS" ]; then
  # shellcheck disable=SC1090
  set -a; . "$ENVS"; set +a
  probe() {  # $1 имя, $2 url, $3 ключ, $4 модель
    [ -n "$3" ] || return 0
    c=$(curl -s -o /tmp/llm-probe.$$ -w '%{http_code}' --max-time 30 "$2" -H "Authorization: Bearer $3" \
        -H 'content-type: application/json' -d "{\"model\":\"$4\",\"messages\":[{\"role\":\"user\",\"content\":\"1\"}],\"max_completion_tokens\":16}")
    if [ "$c" = 402 ] || grep -q 'insufficient_quota\|credit_balance' /tmp/llm-probe.$$ 2>/dev/null; then
      echo "WARN:llm_no_credits: $1 — нет денег (HTTP $c): оценка стиля и обогащение стоят"
    else echo "канал LLM $1: HTTP $c"; fi
    rm -f /tmp/llm-probe.$$
  }
  probe "шлюз Vercel" https://ai-gateway.vercel.sh/v1/chat/completions "${VERCEL_AI_GATEWAY_KEY:-}" openai/gpt-6-luna
  probe "OpenAI" https://api.openai.com/v1/chat/completions "${OPENAI_API_KEY:-}" gpt-6-luna
fi
exit 0

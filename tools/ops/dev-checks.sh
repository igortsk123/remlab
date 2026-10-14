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
# DEV-РЕНДЕР ДЕМО (план demo-03, 14.10): 13.10 его убил earlyoom, и прод сутки молча рисовал запасным путём с
# упрощёнными мешами — дайджест не сказал ни слова. Теперь: жив ли он сам, виден ли проду через туннель, сколько
# раз за сутки поднимался заново (крон раз в 10 минут, dev_render_backend.sh) и сколько кадров прод снял без него.
if curl -s -m 5 http://127.0.0.1:8600/health | grep -q '"ok": true'; then echo "DEV-рендер: жив"
else echo "WARN:dev_render_down: DEV-рендер (порт 8600) не отвечает — кадры демо снимаются запасным путём (tools/scout/dev_render_backend.sh)"; fi
tun=$(ssh -o BatchMode=yes -o ConnectTimeout=8 root@89.167.127.0 'curl -s -m 5 http://172.18.0.1:8601/health; echo; docker logs --since 24h remlab-draft 2>&1 | grep -c "DEV-бэкенд молчит"' 2>/dev/null)
case "$tun" in *'"ok": true'*) echo "туннель прод→DEV-рендер: жив";; *) echo "WARN:dev_render_tunnel: прод не видит DEV-рендер через туннель — кадры демо идут запасным путём";; esac
fb=$(printf '%s\n' "$tun" | tail -1 | tr -dc '0-9')
[ "${fb:-0}" -gt 0 ] && echo "WARN:dev_render_fallback: за сутки прод $fb раз рисовал кадр запасным путём (DEV молчал)"
since=$(date -d '24 hours ago' '+%F %T')
rs=$(awk -v s="$since" '/сервис запущен/ && ($1" "$2)>=s' "$HOME/scout-scenes/dev-render.log" 2>/dev/null | wc -l)
[ "${rs:-0}" -gt 0 ] && echo "WARN:dev_render_restart: DEV-рендер поднимался заново $rs раз за сутки (падал — см. ~/scout-scenes/dev-render.log, earlyoom)"
# карта сценариев демо ↔ живые проверки (demo-03 п.3): строка карты без проверки — жёлтый
. "$(dirname "$0")/node-env.sh" 2>/dev/null; node "$(dirname "$0")/demo-map-check.mjs" 2>&1 | tail -2
exit 0

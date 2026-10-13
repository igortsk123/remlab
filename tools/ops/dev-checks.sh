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
exit 0

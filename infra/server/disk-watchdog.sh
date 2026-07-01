#!/usr/bin/env bash
# remlab disk watchdog — алерт в syslog + файл при заполнении корня.
set -euo pipefail
THRESH=${1:-80}
use=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if [ "${use:-0}" -ge "$THRESH" ]; then
  msg="DISK WARNING: root ${use}% >= ${THRESH}% on $(hostname)"
  logger -t remlab-watchdog "$msg"
  mkdir -p /opt/remlab/backups
  echo "$(date '+%F %T') $msg" >> /opt/remlab/backups/watchdog.log
fi

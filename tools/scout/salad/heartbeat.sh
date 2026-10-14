#!/usr/bin/env bash
# Признак жизни конвейера мешей для мёртвой руки на сервере (план conv-11, ADR-0274). Крон DEV раз в 3 минуты:
# пока `batch_show` держит свой замок, ставим отметку на сервере. Нет конвейера — отметки нет, и если группы Salad
# при этом крутятся дольше 30 минут, сервер их гасит (`infra/server/salad-deadman.py`).
LOCK="$HOME/scout-scenes/.batch_show.lock"
[ -e "$LOCK" ] || exit 0
flock -n "$LOCK" true 2>/dev/null && exit 0          # замок свободен — конвейер не идёт
ssh -o ConnectTimeout=15 -o BatchMode=yes -p 22222 root@89.167.127.0 \
  'mkdir -p /opt/remlab/mesh && touch /opt/remlab/mesh/heartbeat' >/dev/null 2>&1 || true

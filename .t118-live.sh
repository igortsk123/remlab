#!/usr/bin/env bash
# T-118: dev-сервер своей копии на временной БД t118-pg → снимки страницы /lab/mesh-check → остановить свой dev-сервер.
# Запуск (под heavy-slot): bash .t118-live.sh <папка снимков>
set -u
OUT="$1"
mkdir -p "$OUT"
cd /home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112
export DATABASE_URL=postgres://remlab:t118@127.0.0.1:55618/remlab
export MESH_REVIEW_SECRET=t118-local-secret
export NEXT_TELEMETRY_DISABLED=1
PORT=8818
node_modules/.bin/next dev -p "$PORT" > "$OUT/dev.log" 2>&1 &
DEV=$!
for _ in $(seq 1 120); do
  curl -s -o /dev/null "http://127.0.0.1:$PORT/lab/mesh-check" && break
  sleep 2
done
echo "dev pid $DEV готов"
node .t118-page-shots.mjs "http://127.0.0.1:$PORT" "$OUT" "$MESH_REVIEW_SECRET" 2>&1 | tee "$OUT/shots.log"
RC=${PIPESTATUS[0]}
kill "$DEV" 2>/dev/null
wait "$DEV" 2>/dev/null
echo "shots rc=$RC"

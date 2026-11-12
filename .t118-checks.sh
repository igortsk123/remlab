#!/usr/bin/env bash
# T-118: свои тесты (vitest), те же — на временной БД t118-pg, eslint изменённых TS. Запуск (под heavy-slot): bash .t118-checks.sh
set -u
cd /home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112
T="tests/unit/mesh-check-marks.test.ts tests/unit/mesh-check-note-saver.test.ts tests/unit/mesh-check-routes.test.ts tests/unit/mesh-check-db.test.ts tests/unit/mesh-audit.test.ts"
echo "== vitest (без БД)"
node_modules/.bin/vitest run $T 2>&1 | grep -vE "^\s*$" | tail -25
echo "== vitest (БД t118-pg)"
MESH_CHECK_PG_URL=postgres://remlab:t118@127.0.0.1:55618/remlab node_modules/.bin/vitest run tests/unit/mesh-check-db.test.ts 2>&1 | grep -vE "^\s*$" | tail -25
echo "== vitest related"
node_modules/.bin/vitest related lib/mesh-audit/rules.ts lib/mesh-audit/repo-items.ts lib/mesh-audit/repo-decisions.ts --run 2>&1 | grep -E "Test Files|Tests |FAIL" | tail -10
echo "== eslint"
node_modules/.bin/eslint app/lab/mesh-check app/api/lab/mesh-audit components/lab/MeshCheck*.tsx components/lab/useMeshPress.ts lib/mesh-audit tests/unit/mesh-check-*.ts db/schema.ts 2>&1 | tail -30
echo "eslint rc=${PIPESTATUS[0]}"

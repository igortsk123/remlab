#!/bin/bash
# ТЕСТОВЫЙ конвейер сетов (владелец 2026-08-07): референсная десятка за минуты — пересборка →
# судья → перегон размещаемости → страница с публикацией. Боевой полный прогон это НЕ заменяет.
#   bash test_pipeline.sh            # десятка по умолчанию (testmode.REFERENCE_TEN)
#   SETS_ONLY="1,5,9" bash test_pipeline.sh
set -u
cd "$(dirname "$0")"
export SCOUT_TEST=1
PY="$HOME/venvs/scout/bin/python"
cp sets3.json "sets3.json.pre-test.$(date +%H%M)"
$PY compose2.py --style --bands all 2>&1 | tail -3
$PY judge.py --v3 2>&1 | tail -2
$PY sets_incremental.py --index 2>&1 | tail -1
CHECK_TAG=test CHECK_REPORT=solver-check-test.json $PY solver_check.py 2>&1 | tail -5
$PY layout10_page.py --publish 2>&1 | tail -2

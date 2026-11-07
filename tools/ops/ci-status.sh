#!/usr/bin/env bash
# Состояние «CI gate» на main по публичному API GitHub (T-20261107-41): «зелёный / красный: шаг X, коммит Y».
#   bash tools/ops/ci-status.sh            код 0 — зелёный, 1 — красный, 2 — API не ответил
#   bash tools/ops/ci-status.sh --digest   строка DIGEST (+ WARN:ci_status при красном) для ночной сводки, код 0
# Логика и проверки — tools/ops/ci_status.py (--selftest).
exec python3 "$(dirname "$0")/ci_status.py" "$@"

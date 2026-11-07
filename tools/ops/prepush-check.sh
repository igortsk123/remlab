#!/usr/bin/env bash
# Перед пушем — быстрые самопроверки CI, которые касаются изменённых файлов (T-20261107-41); карта «путь → команда» — из ci.yml.
#   bash tools/ops/prepush-check.sh [--files a b] [--dry] [--budget 120]
# Как git pre-push хук: читает stdin протокола (local_ref local_sha remote_ref remote_sha). Код 1 — проверка упала, пуш стоп.
# python — venv scout (там pyyaml), иначе python3. Логика и проверки — tools/ops/prepush_check.py (--selftest).
PY="$HOME/venvs/scout/bin/python"
[ -x "$PY" ] || PY=python3
# ссылкой из .git/hooks/pre-push: свой путь — по ссылке; проверяется копия, ИЗ КОТОРОЙ пуш (корень git текущей папки)
exec "$PY" "$(dirname "$(readlink -f "$0")")/prepush_check.py" "$@"

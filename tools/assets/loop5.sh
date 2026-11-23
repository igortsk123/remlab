#!/usr/bin/env bash
# Круг «на 5» (T-20261123-29/1): tools/assets/loop5.sh --code-ref <SHA> --from 06|07|08 [--dry] [--skus a,b] — см. loop5.py (описание, правила — tools/scout/rules/loop5.json).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${LOOP5_PYTHON:-$HOME/venvs/scout/bin/python}"
exec "$PY" -I "$HERE/loop5.py" "$@"

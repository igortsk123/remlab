#!/usr/bin/env bash
# Ф3 (план cwd-free-tooling): ЕДИНАЯ ТОЧКА ВХОДА конвейера расстановки.
# Сама встаёт в свою папку — любой вызов из ЛЮБОЙ директории корректен.
# Причина: 13.08 четыре раза команды падали/врали из-за «не той папки»
# (включая тихий показ вчерашнего отчёта как нового).
#
#   tools/scout/run.sh exam            # экзамен 252 сцены (6 воркеров)
#   tools/scout/run.sh sets            # пересборка сетов (compose2 --style --bands all)
#   tools/scout/run.sh gallery         # пересборка галереи планов
#   tools/scout/run.sh scene <id>      # разбор сцены (напр. set7-bay)
#   tools/scout/run.sh audit           # аудит правил (RULE-NO-PROOF)
#   tools/scout/run.sh guards          # сторожа целостности (pytest)
set -euo pipefail
cd "$(dirname "$0")"
PY="$HOME/venvs/scout/bin/python"

case "${1:-}" in
  exam)
    rm -f acceptance-report-zoned.jsonl
    exec env ACC_WORKERS=6 "$PY" acceptance_run.py zoned ;;
  sets)
    exec "$PY" compose2.py --style --bands all ;;
  gallery)
    exec "$PY" acceptance_gallery.py ;;
  scene)
    shift; exec "$PY" scene.py "$@" ;;
  audit)
    exec "$PY" rules_audit.py ;;
  guards)
    cd ../.. && exec "$PY" -m pytest services/planner-solver/tests/test_template_integrity.py -q ;;
  *)
    grep '^#   tools' "$0" | sed 's/^#  //'; exit 1 ;;
esac

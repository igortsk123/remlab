#!/usr/bin/env bash
# Ф3 (план cwd-free-tooling): ЕДИНАЯ ТОЧКА ВХОДА конвейера расстановки.
# Сама встаёт в свою папку — любой вызов из ЛЮБОЙ директории корректен.
# Причина: 13.08 четыре раза команды падали/врали из-за «не той папки»
# (включая тихий показ вчерашнего отчёта как нового).
#
#   tools/scout/run.sh exam            # полный экзамен 272 сцены (10 воркеров) — гейт/ночью
#   tools/scout/run.sh smoke           # быстрый смоук ~40 сцен (обратная связь, не гейт)
#   tools/scout/run.sh perf            # 3 самые тяжёлые сцены — замер времени
#   tools/scout/run.sh scenes a,b,c    # точечный реплей сцен
#   tools/scout/run.sh render          # перерисовать PNG из артефактов без пересчёта
#   tools/scout/run.sh sets            # пересборка сетов (compose2 --style --bands all)
#   tools/scout/run.sh gallery         # пересборка галереи планов
#   tools/scout/run.sh scene <id>      # разбор сцены (напр. set7-bay)
#   tools/scout/run.sh audit           # аудит правил (RULE-NO-PROOF)
#   tools/scout/run.sh guards          # сторожа целостности (pytest)
set -euo pipefail
cd "$(dirname "$0")"
HERE="$(pwd)"
PY="$HOME/venvs/scout/bin/python"

case "${1:-}" in
  exam)
    rm -f acceptance-report-zoned.jsonl
    # ЗАМОК (17.08): пока идёт экзамен, конвейер (refresh_daily/enrich_wait) НЕ трогает sets3.json —
    # утренний heal переписал банки под бегущими воркерами (pod-комплекты 72→17), экзамен стал смешанным.
    # flock: второй экзамен/сборка не стартуют параллельно; exam.lock — сигнал для cron
    exec 9>"$HERE/exam.flock"; flock -n 9 || { echo "экзамен уже идёт (exam.flock)"; exit 3; }
    touch "$HERE/exam.lock"; trap 'rm -f "$HERE/exam.lock"' EXIT
    set +e; env ACC_WORKERS="${ACC_WORKERS:-10}" "$PY" acceptance_run.py zoned; rc=$?; rm -f "$HERE/exam.lock"; exit $rc ;;
  smoke)
    # БЫСТРЫЙ СМОУК (~40 сцен, ≈5 мин): обратная связь по правке, НЕ гейт (полный — exam/ночью)
    exec 9>"$HERE/exam.flock"; flock -n 9 || { echo "экзамен уже идёт (exam.flock)"; exit 3; }
    "$PY" smoke_manifest.py >/dev/null
    rm -f acceptance-report-zoned-smoke.jsonl
    touch "$HERE/exam.lock"; trap 'rm -f "$HERE/exam.lock"' EXIT
    set +e; env ACC_WORKERS="${ACC_WORKERS:-10}" ACC_MANIFEST="$HERE/smoke-manifest.json" ACC_REPORT_SUFFIX=-smoke "$PY" acceptance_run.py zoned; rc=$?; rm -f "$HERE/exam.lock"; exit $rc ;;
  perf)
    # PERF-СМОУК: 3 самые тяжёлые сцены — замер времени (не для гейта/галереи)
    rm -f acceptance-report-zoned-perf.jsonl
    exec env ACC_WORKERS=3 ACC_MANIFEST="$HERE/perf-manifest.json" ACC_REPORT_SUFFIX=-perf "$PY" acceptance_run.py zoned ;;
  scenes)
    # точечный реплей: run.sh scenes set16-base,set28-base
    rm -f acceptance-report-zoned-scenes.jsonl
    exec env ACC_WORKERS="${ACC_WORKERS:-6}" ACC_SCENES="$2" ACC_REPORT_SUFFIX=-scenes "$PY" acceptance_run.py zoned ;;
  render)
    # RENDER-ONLY: перерисовать PNG всех артефактов из JSON без пересчёта (подписи/подача)
    exec "$PY" render_plan.py --all -j "${ACC_WORKERS:-6}" ;;
  sets)
    if [ -f "$HERE/exam.lock" ]; then echo "exam.lock: идёт экзамен — сборка сетов отложена (не параллелить)"; exit 3; fi
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

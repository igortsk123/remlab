#!/usr/bin/env bash
# НОЧНОЙ ПОЛНЫЙ ЭКЗАМЕН (ускорение 17.08, Codex п.1): 272 сцены → галерея → публикация на /test/.
# Днём — смоук/точечные сцены; полный — здесь (и вручную перед коммитом). Не стартует, если идёт
# экзамен (flock внутри run.sh exam) или openai/cron сборка (exam.lock).
set -uo pipefail
cd "$(dirname "$0")"
LOG=nightly.log
# пауза обслуживания (onb-12, `tools/ops/cron-pause.sh`): на паузе — строка в лог и выход
. ../ops/maintenance.sh
maint_gate nightly_exam "$LOG"
# ВРЕМЕННОЕ ВСЕГО ЭКЗАМЕНА — НА ДИСК (T-20261107-13): как в refresh_daily, TMPDIR → REMLAB_TMP до первого шага, чтобы python
# (tempfile), node и Chromium экзамена не писали в /tmp (tmpfs с квотой, EDQUOT при пиках у соседей)
. ../ops/remlab-tmp.sh
export TMPDIR="$REMLAB_TMP"
echo "=== $(date '+%F %T') ночной экзамен старт ===" >> "$LOG"
./run.sh exam >> "$LOG" 2>&1; rc=$?
echo "экзамен rc=$rc" >> "$LOG"
if [ $rc -eq 0 ]; then
  ./run.sh gallery >> "$LOG" 2>&1
  # АРХИВ ГАЛЕРЕИ — В REMLAB_TMP НА ДИСКЕ, НЕ В /tmp (T-20261107-02/2): /tmp DEV — tmpfs с квотой; scp не прошёл — архив 24 МБ
  # оставался в /tmp навсегда (rm стоял в конце цепочки &&). Теперь свой архив убирает trap при любом исходе.
  # GAL_RTMP — /tmp СЕРВЕРА, куда scp кладёт архив и где он распаковывается (не DEV). REMLAB_TMP задан в начале скрипта.
  GAL_RTMP=${GAL_RTMP:-/tmp}
  if GAL_TGZ=$(mktemp -p "$REMLAB_TMP" acc-gallery-nightly.XXXXXX); then trap 'rm -f "$GAL_TGZ"' EXIT
  else GAL_TGZ=; echo "галерея не опубликована: нет места под архив в $REMLAB_TMP" >> "$LOG"; fi
  ( [ -n "${GAL_TGZ:-}" ] && cd ~/scout-scenes && tar czf "$GAL_TGZ" acc-gallery && \
    scp -q -P 22222 "$GAL_TGZ" "root@89.167.127.0:$GAL_RTMP/acc-gallery-nightly.tgz" && \
    ssh -p 22222 root@89.167.127.0 "cd '$GAL_RTMP' && rm -rf acc-gallery && tar xzf acc-gallery-nightly.tgz && rm -rf /opt/remlab/test/acceptance-plans.prev && mv /opt/remlab/test/acceptance-plans /opt/remlab/test/acceptance-plans.prev && mv acc-gallery /opt/remlab/test/acceptance-plans && rm acc-gallery-nightly.tgz" && \
    echo "галерея опубликована" ) >> "$LOG" 2>&1
  ~/venvs/scout/bin/python - >> "$LOG" 2>&1 <<'PY'
import json
rep=[json.loads(l) for l in open('acceptance-report-zoned.jsonl') if l.strip()]
to=[r['scene'] for r in rep if 'TIMEOUT' in str(r['fails'])]
print(f"итог: ok {sum(r['ok'] for r in rep)}/{len(rep)}, TIMEOUT {len(to)} {to[:6]}")
dem=[r for r in rep if str(r['scene']).endswith('-demo')]
print(f"демо-гостиная (сцены витрины): ok {sum(r['ok'] for r in dem)}/{len(dem)}" + ''.join(f"; {r['scene']}: {str(r['fails'])[:80]}" for r in dem if not r['ok']))
PY
fi
echo "=== $(date '+%F %T') ночной экзамен готово ===" >> "$LOG"

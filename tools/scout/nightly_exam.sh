#!/usr/bin/env bash
# НОЧНОЙ ПОЛНЫЙ ЭКЗАМЕН (ускорение 17.08, Codex п.1): 272 сцены → галерея → публикация на /test/.
# Днём — смоук/точечные сцены; полный — здесь (и вручную перед коммитом). Не стартует, если идёт
# экзамен (flock внутри run.sh exam) или openai/cron сборка (exam.lock).
set -uo pipefail
cd "$(dirname "$0")"
LOG=nightly.log
echo "=== $(date '+%F %T') ночной экзамен старт ===" >> "$LOG"
./run.sh exam >> "$LOG" 2>&1; rc=$?
echo "экзамен rc=$rc" >> "$LOG"
if [ $rc -eq 0 ]; then
  ./run.sh gallery >> "$LOG" 2>&1
  ( cd ~/scout-scenes && tar czf /tmp/acc-gallery-nightly.tgz acc-gallery && \
    scp -q -P 22222 /tmp/acc-gallery-nightly.tgz root@89.167.127.0:/tmp/ && \
    ssh -p 22222 root@89.167.127.0 'cd /tmp && rm -rf acc-gallery && tar xzf acc-gallery-nightly.tgz && rm -rf /opt/remlab/test/acceptance-plans.prev && mv /opt/remlab/test/acceptance-plans /opt/remlab/test/acceptance-plans.prev && mv acc-gallery /opt/remlab/test/acceptance-plans && rm acc-gallery-nightly.tgz' && \
    rm -f /tmp/acc-gallery-nightly.tgz && echo "галерея опубликована" ) >> "$LOG" 2>&1
  ~/venvs/scout/bin/python - >> "$LOG" 2>&1 <<'PY'
import json
rep=[json.loads(l) for l in open('acceptance-report-zoned.jsonl') if l.strip()]
to=[r['scene'] for r in rep if 'TIMEOUT' in str(r['fails'])]
print(f"итог: ok {sum(r['ok'] for r in rep)}/{len(rep)}, TIMEOUT {len(to)} {to[:6]}")
PY
fi
echo "=== $(date '+%F %T') ночной экзамен готово ===" >> "$LOG"

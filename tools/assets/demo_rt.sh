#!/usr/bin/env bash
# ЛЁГКИЕ КОПИИ МОДЕЛЕЙ ДЕМО — ВОРОТА ПУБЛИКАЦИИ (план demo-01 п.5, шаг `demo_rt` ночного прогона между сборкой витрины
# и публикацией). Модели вариантов, декора и первых 6 кандидатов каждой ленты: собрать недостающие и устаревшие
# (отпечаток = исходник + рецепт), выложить на /rt/, проверить. У модели варианта нет свежей копии → код 1 и WARN:
# публикация демо в эту ночь не идёт (живая сцена тянула бы исходник 4–10 МБ вместо копии 0,2–0,4 МБ).
# Таблица копий ночной сборки — вне репо (`~/scout-scenes/flat3d-rt/runtime-meshes.json`): ночь не правит git.
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
PY=${PY:-$HOME/venvs/scout/bin/python}
DATA=${DEMO_DATA:-$HOME/scout-scenes/flat215-demo/demo-data.json}
M=${RT_MANIFEST:-$HOME/scout-scenes/flat3d-rt/runtime-meshes.json}
[ -f "$M" ] || cp data/flat3d/runtime-meshes.json "$M"
"$PY" tools/assets/runtime_mesh.py --ids-from-demo "$DATA" --manifest "$M" --size 1024 2>&1 | tail -2
"$PY" tools/assets/runtime_mesh.py --ids-from-demo "$DATA" --manifest "$M" --size 512 --suffix=-lite 2>&1 | tail -2
bad=0
if ! RT_MANIFEST="$M" bash tools/assets/publish_rt.sh > /tmp/demo_rt_pub.$$ 2>&1; then
  tail -3 /tmp/demo_rt_pub.$$; bad=1; echo "выкладка копий на /rt/ не прошла"
else tail -2 /tmp/demo_rt_pub.$$; fi
rm -f /tmp/demo_rt_pub.$$
# копии моделей вариантов — НА ПРОДЕ, обе (verify 14.10: локальная проверка не видела сбой выкладки)
miss=$("$PY" - "$DATA" <<'PYEOF'
import json, sys, urllib.request
sys.path.insert(0, "tools/assets")
from runtime_mesh import demo_ids
var, _ = demo_ids(sys.argv[1], 6)
bad = []
for m in var:
    for suf in ("", "-lite"):
        try:
            req = urllib.request.Request(f"https://remont-lab.online/rt/{m}{suf}.glb", method="HEAD")
            urllib.request.urlopen(req, timeout=20)
        except Exception:  # noqa: BLE001
            bad.append(m + suf)
print(len(bad), " ".join(bad[:5]))
PYEOF
)
echo "копии моделей вариантов на проде: не хватает ${miss:-?}"
case "$miss" in 0*) ;; *) bad=1;; esac
"$PY" tools/assets/runtime_mesh.py --ids-from-demo "$DATA" --manifest "$M" --size 1024 --check || bad=1
"$PY" tools/assets/runtime_mesh.py --ids-from-demo "$DATA" --manifest "$M" --size 512 --suffix=-lite --check || bad=1
if [ "$bad" = 1 ]; then
  echo "WARN:demo_rt_missing: у моделей вариантов демо нет свежих лёгких копий — демо этой ночью не публикуется (вчерашнее остаётся)"
  exit 1
fi

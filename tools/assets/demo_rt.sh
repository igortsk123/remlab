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
OUT=${RT_OUT:-$HOME/scout-scenes/flat3d-rt}
# ВСЕ КОМНАТЫ ВИТРИНЫ (T-20261106-77): модели вариантов каждой комнаты из DEMO_DATA и кандидаты лент по типу комнаты
# (`rules/demo-swap.json:rt_feed_top`). Сборка рядом (/test/<папка>): DEMO_DATA, RT_MANIFEST — копия таблицы, RT_ADD_ONLY=1;
# таблица копий ложится рядом с её demo-data.json (RT_TABLE_OUT), витрина /demo не трогается.
export RT_TABLE_OUT=${RT_TABLE_OUT:-$(dirname "$DATA")/rt-meshes.json}
[ -f "$M" ] || cp data/flat3d/runtime-meshes.json "$M"
"$PY" tools/assets/runtime_mesh.py --ids-from-demo "$DATA" --manifest "$M" --out "$OUT" --size 1024 2>&1 | tail -2
"$PY" tools/assets/runtime_mesh.py --ids-from-demo "$DATA" --manifest "$M" --out "$OUT" --size 512 --suffix=-lite 2>&1 | tail -2
bad=0
# вывод выкладки — в REMLAB_TMP на диске, не в /tmp (T-20261107-02: ночью 07.11 запись сюда упала на квоте tmpfs — EDQUOT,
# и демо не опубликовалось); свой файл убираем при любом выходе
. tools/ops/remlab-tmp.sh
PUB_LOG=$(mktemp -p "$REMLAB_TMP" demo_rt_pub.XXXXXX) || { echo "WARN:demo_rt_missing: нет места под временный файл в $REMLAB_TMP"; exit 1; }
trap 'rm -f "$PUB_LOG"' EXIT
if ! RT_MANIFEST="$M" bash tools/assets/publish_rt.sh "$OUT" > "$PUB_LOG" 2>&1; then
  tail -3 "$PUB_LOG"; bad=1; echo "выкладка копий на /rt/ не прошла"
else tail -2 "$PUB_LOG"; fi
# копии моделей вариантов — НА ПРОДЕ, обе (verify 14.10: локальная проверка не видела сбой выкладки)
miss=$("$PY" - "$DATA" <<'PYEOF'
import json, sys, urllib.request
sys.path.insert(0, "tools/assets")
from runtime_mesh import demo_ids
var, _ = demo_ids(sys.argv[1])
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
"$PY" tools/assets/runtime_mesh.py --ids-from-demo "$DATA" --manifest "$M" --out "$OUT" --size 1024 --check || bad=1
"$PY" tools/assets/runtime_mesh.py --ids-from-demo "$DATA" --manifest "$M" --out "$OUT" --size 512 --suffix=-lite --check || bad=1
if [ "$bad" = 1 ]; then
  echo "WARN:demo_rt_missing: у моделей вариантов демо нет свежих лёгких копий — демо этой ночью не публикуется (вчерашнее остаётся)"
  exit 1
fi

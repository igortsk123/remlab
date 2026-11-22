#!/usr/bin/env bash
# T-20261118-52/5, T-20261119-03/2: ОТКАТ перекраски ОДНОЙ модели. Сухо по умолчанию (`--dry-run` — то же): только проверки и печать шагов, `--apply` — выполнить.
#   recolor_rollback.sh <sku> [--apply|--dry-run]        sku вида mid:eid
#   ORIG=<файл>  — откуда брать оригинал (по умолчанию <поколение>/model.orig.glb)
#   WORK=<папка> — куда писать список для GALLERY_ONLY (по умолчанию ~/remlab-logs/recolor-window)
#   MANIFEST=<копия runtime-meshes.json> — если лёгкие копии пересобирать в чужой манифест (живой не трогать)
#   ROLLBACK_SKIP_PROD=1 — не ходить на прод за sha (тест)
# Ничего не удаляет: перекрашенный файл остаётся рядом как model.recolor.glb, старые строки БД остаются.
# Шаги пишут в DEV-базу (реестр, привязка) и на прод (одна папка модели) — те же, что при записи (`recolor_window.py`).
# Не запускать при волне/шагах цепочки: отказ (код 4) — mesh_wave_start, batch_show, ingest_registry, orient_worker, room_bindings, gallery_build, mesh_publish,
# runtime_mesh, refresh_daily, publish_demo. После отката лёгкие копии (1024 и -lite) пересобираются, если они уже были.
set -euo pipefail
SKU="${1:?sku}"; APPLY=0
for a in "${@:2}"; do [ "$a" = "--apply" ] && APPLY=1; done
SID="${SKU//:/_}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCOUT="$(cd "$HERE/.." && pwd)"; REPO="$(cd "$SCOUT/../.." && pwd)"
PY="${PY:-$HOME/venvs/scout/bin/python}"
WORK="${WORK:-$HOME/remlab-logs/recolor-window}"
V2="$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2/$SID"
GAL="$HOME/scout-scenes/mesh-pilot-gallery/$SID"
RT="$HOME/scout-scenes/flat3d-rt"
HOST=root@89.167.127.0; PROD=/opt/remlab/test/mesh-pilot10
say() { echo "[откат $SKU] $*"; }
run() { if [ "$APPLY" = 1 ]; then say "ВЫПОЛНЯЮ: $*"; eval "$*"; else say "(сухо) $*"; fi; }

# 1. поколение: где лежит оригинал
GEN=""
for d in "$V2"/*/; do
  [ -d "$d" ] || continue
  d="${d%/}"
  if [ -f "$d/model.orig.glb" ] || { [ -n "${ORIG:-}" ] && [ -f "$d/model.glb" ]; }; then GEN="$d"; fi
done
[ -n "$GEN" ] || { say "нет model.orig.glb ни в одном поколении $V2 — откатывать нечего"; exit 3; }
ORIGF="${ORIG:-$GEN/model.orig.glb}"
[ -f "$ORIGF" ] || { say "нет файла оригинала $ORIGF"; exit 3; }
say "поколение: $GEN"
say "оригинал: $ORIGF  sha=$(sha256sum "$ORIGF" | cut -c1-16)"
say "сейчас в v2:   sha=$(sha256sum "$GEN/model.glb" | cut -c1-16)"
[ -f "$GAL/model.glb" ] && say "в галерее:     sha=$(sha256sum "$GAL/model.glb" | cut -c1-16)"
if [ "${ROLLBACK_SKIP_PROD:-0}" != 1 ]; then
  say "на проде:      sha=$( (ssh -p 22222 -o BatchMode=yes -o ConnectTimeout=20 $HOST "sha256sum $PROD/$SID/model.glb" || echo "недоступен") | cut -c1-16)"
fi

# 2. не пересекаться с цепочкой мешей
BUSY="$(ps -eo pid,etime,args | grep -E 'mesh_wave_start|batch_show|gallery_build|mesh_publish|runtime_mesh|ingest_registry|orient_worker|room_bindings|refresh_daily|publish_demo' | grep -v grep | grep -v recolor_rollback || true)"
if [ -n "$BUSY" ]; then say "ЗАНЯТО, идут шаги цепочки:"; echo "$BUSY" | cut -c1-160; [ "$APPLY" = 1 ] && exit 4; fi

# 3. шаги (порядок тот же, что при записи)
run "cp -a '$GEN/model.glb' '$GEN/model.recolor.glb.new' && mv -n '$GEN/model.recolor.glb.new' '$GEN/model.recolor.glb'"
run "cp -a '$ORIGF' '$GEN/model.glb.tmp' && mv -f '$GEN/model.glb.tmp' '$GEN/model.glb'"
run "$PY $SCOUT/salad/ingest_registry.py"
run "$PY $SCOUT/room_bindings.py --build"
run "mkdir -p '$WORK' && printf '%s\n' '$SKU' > '$WORK/only-$SID.txt' && cd '$SCOUT' && GALLERY_ONLY='$WORK/only-$SID.txt' GALLERY_SRC='$HOME/scout-scenes/meshes-hunyuan/meshes/hunyuan21/v2' $PY salad/gallery_build.py"
run "rsync -a -c --info=stats1 -e 'ssh -p 22222 -o BatchMode=yes' '$GAL/' $HOST:$PROD/$SID/"
MAN=""; [ -n "${MANIFEST:-}" ] && MAN="--manifest '$MANIFEST'"
if [ "$APPLY" != 1 ] || [ -f "$RT/$SID.glb" ]; then run "cd '$REPO' && $PY tools/assets/runtime_mesh.py --id $SID --force $MAN"; fi
if [ "$APPLY" != 1 ] || [ -f "$RT/$SID-lite.glb" ]; then run "cd '$REPO' && $PY tools/assets/runtime_mesh.py --id $SID --force --size 512 --suffix=-lite $MAN"; fi
say "готово. Проверка: sha в v2, галерее и на проде должны совпасть с оригиналом (см. строки выше); лёгкие копии пересобраны, если были."

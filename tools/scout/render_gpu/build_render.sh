#!/usr/bin/env bash
# Сборка образа рендера Blender (T-20261117-22) с ГЕЙТОМ ПО СЖАТОМУ РАЗМЕРУ — как `salad/build.sh` меш-образа, но без весов нейросетей.
#   build_render.sh bench   # образ замера: Blender + код + две сцены /demo (по умолчанию)
#   build_render.sh agent   # образ машины под контроллером (T-24/1): код + агент готовности
#   build_render.sh worker  # БОЕВАЯ машина (T-24/2): агент готовности + воркер заданий
#   build_render.sh code    # боевой образ: Blender + код, без сцен (сцену воркер берёт по манифесту)
# Контекст сборки собирается в ~/remlab-logs/t22-1117/ctx (вне репо): Blender-архив (тот же 5.3.0, что на DEV), код, сцены lv-set10/lv-bed1.
# Лимит Salad — 35 ГБ сжатого; наш порог для рендера — 3 ГБ (если больше, что-то лишнее попало в образ). Секретов в контексте нет.
set -euo pipefail
TARGET="${1:-bench}"
BASE="${RENDER_BASE:-base}"            # thin — тонкий образ (T-24/3): тег получает суффикс -thin
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CYC="$HERE/../cycles_probe"
L="$HOME/remlab-logs/t63-1117"
CTX="$HOME/remlab-logs/t22-1117/ctx"
REPO="${RENDER_IMAGE_REPO:-ghcr.io/igortsk123/render-blender}"
LIMIT_GB=3
TGZ="$HOME/opt/dl/blender-5.3.0.tar.xz"

mkdir -p "$CTX/scenes/public"
cp -f "$HERE/Dockerfile.render" "$HERE/ready_probe.py" "$HERE/bench.py" "$HERE/machine_agent.py" "$HERE/render_worker.py" "$HERE/jobs_proto.py" "$CYC/render_cycles.py" "$CTX/"
cp -f "$HERE/../../../data/flat3d/wall-art.json" "$CTX/wall-art.json"
[ -f "$CTX/blender-5.3.0.tar.xz" ] || cp "$TGZ" "$CTX/blender-5.3.0.tar.xz"
SHA="$(sha256sum "$CTX/blender-5.3.0.tar.xz" | cut -d' ' -f1)"

if [ "$TARGET" = "bench" ]; then
  for pair in "living:lv-set10" "bedroom:lv-bed1"; do
    n="${pair%%:*}"; s="${pair##*:}"
    mkdir -p "$CTX/scenes/$n"
    rsync -a --delete "$L/export2/$s/" "$CTX/scenes/$n/export/"
    rsync -a --delete "$L/demo_dump/$s/" "$CTX/scenes/$n/dump/"
  done
  # карты стен и пола и вид из окна — ровно то, что называет scene-export.json (проверено перечнем путей)
  for f in $(python3 - "$L/demo_dump/lv-set10/scene-export.json" "$L/demo_dump/lv-bed1/scene-export.json" <<'EOF'
import re, sys
out = set()
for p in sys.argv[1:]:
    out |= set(re.findall(r'"(/[^"]+\.(?:webp|png|jpg))"', open(p, encoding='utf-8').read()))
print(' '.join(sorted(x.lstrip('/') for x in out)))
EOF
  ); do
    mkdir -p "$CTX/scenes/public/$(dirname "$f")"
    cp -f "$HERE/../../../public/$f" "$CTX/scenes/public/$f"
  done
else
  rm -rf "$CTX/scenes"; mkdir -p "$CTX/scenes"      # цель code сцен не копирует
fi

TAG="$REPO:cycles-5.3.0-$TARGET"; [ "$BASE" = "thin" ] && TAG="$TAG-thin"
TAG="$TAG${RENDER_TAG_SUFFIX:-}"      # суффикс тега (T-24/5: -fmt2) — новый образ не перекрывает тег прежнего, которого держит работающая группа
echo "== сборка $TAG (Blender sha256 ${SHA:0:12}…)"
docker build -f "$CTX/Dockerfile.render" --target "$TARGET" --build-arg "BLENDER_SHA256=$SHA" --build-arg "BASE=$BASE" -t "$TAG" "$CTX"
echo "== локальный размер: $(docker image inspect "$TAG" --format '{{.Size}}' | python3 -c 'import sys;print(round(int(sys.stdin.read())/2**30,2))') ГБ (распакованный)"
echo "== публикация $TAG (вход в ghcr уже сделан на DEV для мешей)"
docker push "$TAG" | tail -3
# buildx кладёт рядом с образом аттестацию, и верхний digest — это список манифестов (слоёв в нём нет: `docker manifest inspect` дал бы 0 ГБ).
# Закрепляем и считаем по манифесту linux/amd64 — одиночному образу.
INDEX=$(docker inspect --format '{{index .RepoDigests 0}}' "$TAG")
AMD=$(docker buildx imagetools inspect --raw "$INDEX" | python3 -c 'import json,sys; m=json.load(sys.stdin); print(next(x["digest"] for x in m["manifests"] if x.get("platform",{}).get("architecture")=="amd64" and x["platform"].get("os")=="linux"))')
DIGEST="${INDEX%@*}@$AMD"
COMPRESSED=$(docker buildx imagetools inspect --raw "$DIGEST" | python3 -c 'import json,sys; m=json.load(sys.stdin); print(sum(l["size"] for l in m["layers"]))')
echo "== сжатый размер в реестре: $(python3 -c "print(round($COMPRESSED/2**30,2))") ГБ; digest (amd64): $DIGEST"
echo "$DIGEST" > "$HOME/remlab-logs/t22-1117/image-$TARGET.digest"
python3 -c "import sys; sys.exit(1 if $COMPRESSED/2**30 > $LIMIT_GB else 0)" || { echo "!! образ больше ${LIMIT_GB} ГБ — искать лишнее"; exit 1; }
echo "== ок"

#!/usr/bin/env bash
# Сборка образа с ГЕЙТОМ ПО РАЗМЕРУ.
#
# Salad не скачает образ больше 35 ГБ в сжатом виде. Локальный `docker images` показывает
# распакованный размер и расходится со сжатым в разы — поэтому проверяем именно то, что
# увидит платформа: сумму сжатых слоёв в реестре через `docker manifest inspect`.
# Порог 28 ГБ — с запасом: если упрёмся, веса переезжают в R2 отдельным бандлом.
#
#   ./build.sh cu124   # 3090 (Ampere) и 4090 (Ada) — связка, проверенная апстримом
#   ./build.sh cu128   # 5090 (Blackwell) — отдельный образ, на 4090 не запустится
set -euo pipefail
cd "$(dirname "$0")"

VARIANT="${1:-cu124}"
REPO="${MESH_IMAGE_REPO:-ghcr.io/igortsk123/mesh-hunyuan}"
HY_COMMIT="${HY_COMMIT:-main}"
LIMIT_GB=28

# cu124 — комбинация, проверенная апстримом (их docker/Dockerfile). Покрывает 3090 (8.6)
# и 4090 (8.9) одним образом. cu128 нужен только Blackwell, апстримом НЕ проверен.
case "$VARIANT" in
  cu124) CUDA_TAG=12.4.1; TORCH_INDEX=cu124; TORCH_ARCH="8.6;8.9"
         TORCH_SPEC="torch==2.5.1 torchvision==0.20.1" ;;
  cu128) CUDA_TAG=12.8.1; TORCH_INDEX=cu128; TORCH_ARCH="12.0"
         TORCH_SPEC="torch torchvision" ;;
  *) echo "неизвестный вариант: $VARIANT (cu124|cu128)"; exit 1 ;;
esac

TAG="$REPO:$VARIANT"
echo "== сборка $TAG (CUDA $CUDA_TAG, arch $TORCH_ARCH, torch: $TORCH_SPEC, Hunyuan @ $HY_COMMIT)"
docker build \
  --build-arg "CUDA_TAG=$CUDA_TAG" \
  --build-arg "TORCH_INDEX=$TORCH_INDEX" \
  --build-arg "TORCH_ARCH=$TORCH_ARCH" \
  --build-arg "TORCH_SPEC=$TORCH_SPEC" \
  --build-arg "HY_COMMIT=$HY_COMMIT" \
  --build-arg "BAKE_WEIGHTS=${BAKE_WEIGHTS:-1}" \
  -t "$TAG" .

# GHCR — реестр владельца, вход тем же токеном, что и gh CLI (write:packages).
# Образ приватный: Salad получает отдельный read-токен в настройках container group.
echo "== публикация в $REPO (гейт размера считается по реестру, до запуска на Salad)"
docker login ghcr.io -u igortsk123 -p "$(gh auth token)" >/dev/null 2>&1 || \
  echo "!! вход в ghcr не удался — проверь право write:packages у токена gh"
docker push "$TAG"

COMPRESSED=$(docker manifest inspect "$TAG" \
  | python3 -c 'import json,sys; m=json.load(sys.stdin); print(sum(l["size"] for l in m.get("layers",[])))')
GB=$(python3 -c "print(f'{$COMPRESSED/2**30:.1f}')")
echo "== сжатый размер в реестре: ${GB} ГБ (лимит Salad 35, наш порог ${LIMIT_GB})"

if python3 -c "import sys; sys.exit(0 if $COMPRESSED/2**30 > $LIMIT_GB else 1)"; then
  echo "!! ОБРАЗ СЛИШКОМ БОЛЬШОЙ. Варианты: вынести веса в R2 бандлом и докачивать при"
  echo "!! старте (замерив, тарифицируется ли докачка), либо урезать базовый образ до runtime."
  exit 1
fi
echo "== ок: $TAG готов к развёртыванию на Salad"

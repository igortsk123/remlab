#!/usr/bin/env bash
# Сборка образа с ГЕЙТОМ ПО РАЗМЕРУ.
#
# Salad не скачает образ больше 35 ГБ в сжатом виде. Локальный `docker images` показывает
# распакованный размер и расходится со сжатым в разы — поэтому проверяем именно то, что
# увидит платформа: сумму сжатых слоёв в реестре через `docker manifest inspect`.
# Порог 28 ГБ — с запасом: если упрёмся, веса переезжают в R2 отдельным бандлом.
#
#   ./build.sh cu121   # 4090 (Ada)
#   ./build.sh cu128   # 5090 (Blackwell) — отдельный образ, на 4090 не запустится
set -euo pipefail
cd "$(dirname "$0")"

VARIANT="${1:-cu121}"
REPO="${MESH_IMAGE_REPO:-remlab/mesh-hunyuan}"
HY_COMMIT="${HY_COMMIT:-main}"
LIMIT_GB=28

case "$VARIANT" in
  cu121) CUDA_TAG=12.1.1; TORCH_INDEX=cu121; TORCH_ARCH=8.9 ;;
  cu128) CUDA_TAG=12.8.1; TORCH_INDEX=cu128; TORCH_ARCH=12.0 ;;
  *) echo "неизвестный вариант: $VARIANT (cu121|cu128)"; exit 1 ;;
esac

TAG="$REPO:$VARIANT"
echo "== сборка $TAG (CUDA $CUDA_TAG, arch $TORCH_ARCH, Hunyuan @ $HY_COMMIT)"
docker build \
  --build-arg "CUDA_TAG=$CUDA_TAG" \
  --build-arg "TORCH_INDEX=$TORCH_INDEX" \
  --build-arg "TORCH_ARCH=$TORCH_ARCH" \
  --build-arg "HY_COMMIT=$HY_COMMIT" \
  -t "$TAG" .

echo "== публикация (гейт размера считается по реестру, до запуска на Salad)"
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

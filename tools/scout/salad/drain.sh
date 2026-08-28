#!/usr/bin/env bash
# Откачка принятых мешей с exit-fi на дев-машину и освобождение места.
#
# exit-fi работает ТРАНЗИТОМ: у него 23 ГБ свободных и рядом боевая VPN-нода, копить у него
# нельзя. Приёмник отдаёт 507, когда каталог перерос лимит, — тогда ноды получают честный
# отказ, задание возвращается в очередь, а мы запускаем это.
#
# Забираем ТОЛЬКО завершённые комплекты (те, где есть complete.json) — иначе утащим
# полуфабрикат, который сейчас догружается.
#
#   ./drain.sh            # забрать и удалить с сервера
#   ./drain.sh --keep     # забрать, на сервере оставить (для проверки)
set -euo pipefail

SRV="${MESH_SRV:-root@89.167.127.0}"
PORT="${MESH_SSH_PORT:-22222}"
REMOTE="${MESH_ROOT:-/opt/remlab/meshes}"
LOCAL="${MESH_LOCAL:-$HOME/scout-scenes/meshes-hunyuan}"
KEEP="${1:-}"

mkdir -p "$LOCAL"
echo "== ищу завершённые комплекты на $SRV:$REMOTE"
mapfile -t DIRS < <(ssh -p "$PORT" "$SRV" \
  "find '$REMOTE' -name complete.json -printf '%h\n' 2>/dev/null | sed 's|^$REMOTE/||'")

if [ ${#DIRS[@]} -eq 0 ]; then
  echo "нечего забирать"; exit 0
fi
echo "== комплектов: ${#DIRS[@]}"

for d in "${DIRS[@]}"; do
  mkdir -p "$LOCAL/$d"
  rsync -a -e "ssh -p $PORT" "$SRV:$REMOTE/$d/" "$LOCAL/$d/"
  # Проверяем, что маркер доехал, и только потом разрешаем удаление на сервере
  if [ ! -f "$LOCAL/$d/complete.json" ]; then
    echo "!! $d: маркер не доехал, на сервере НЕ трогаю"; continue
  fi
  if [ "$KEEP" != "--keep" ]; then
    ssh -p "$PORT" "$SRV" "rm -rf '$REMOTE/$d'"
  fi
done

echo "== локально: $(find "$LOCAL" -name complete.json | wc -l) комплектов, $(du -sh "$LOCAL" | cut -f1)"
ssh -p "$PORT" "$SRV" "du -sh '$REMOTE' 2>/dev/null; df -h / | tail -1"

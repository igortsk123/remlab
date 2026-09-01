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

# ОДИН DRAIN НА МАШИНУ. Теперь он ходит фоном (параллельно генерации), а звать его могут
# и конвейер, и волна лечения, и соседняя сессия. Два разом подрались бы за общий каталог
# сборки и за удаление на сервере.
exec 9>"$LOCAL/.drain.lock"
if ! flock -n 9; then
  echo "== drain уже идёт (другой процесс держит замок) — выхожу"; exit 0
fi

echo "== ищу завершённые комплекты на $SRV:$REMOTE"
mapfile -t DIRS < <(ssh -p "$PORT" "$SRV" \
  "find '$REMOTE' -name complete.json -printf '%h\n' 2>/dev/null | sed 's|^$REMOTE/||'")

if [ ${#DIRS[@]} -eq 0 ]; then
  echo "нечего забирать"; exit 0
fi
echo "== комплектов: ${#DIRS[@]}"

STAGE_ROOT="$LOCAL/.staging"
NEW=0; SKIP=0
for d in "${DIRS[@]}"; do
  # УЖЕ ЗАБРАННОЕ НЕ ТЯНЕМ ПОВТОРНО. С `--keep` каталоги остаются на сервере, и прежняя
  # версия каждую пачку заново rsync'ила ВСЕ комплекты (390 отдельных ssh-сессий при 477
  # уже лежащих локально) — работа росла с числом сделанных мешей и съедала оплаченное
  # время нод. Комплект целен по определению: `complete.json` пишется последним.
  if [ -f "$LOCAL/$d/complete.json" ]; then
    SKIP=$((SKIP + 1))
    if [ "$KEEP" != "--keep" ]; then ssh -p "$PORT" "$SRV" "rm -rf '$REMOTE/$d'"; fi
    continue
  fi
  # АТОМАРНАЯ ПУБЛИКАЦИЯ. rsync писал прямо в конечный каталог, а файлы приезжают по
  # алфавиту: `complete.json`/`manifest.json` РАНЬШЕ `model.glb`. Постобработка, идущая
  # теперь параллельно, увидела бы комплект без модели. Собираем в стороне и переносим
  # каталог одним rename.
  STAGE="$STAGE_ROOT/$d"
  rm -rf "$STAGE"; mkdir -p "$STAGE"
  rsync -a -e "ssh -p $PORT" "$SRV:$REMOTE/$d/" "$STAGE/"
  if [ ! -f "$STAGE/complete.json" ]; then
    echo "!! $d: маркер не доехал, на сервере НЕ трогаю"; rm -rf "$STAGE"; continue
  fi
  mkdir -p "$(dirname "$LOCAL/$d")"
  rm -rf "$LOCAL/$d"
  mv "$STAGE" "$LOCAL/$d"
  NEW=$((NEW + 1))
  if [ "$KEEP" != "--keep" ]; then
    ssh -p "$PORT" "$SRV" "rm -rf '$REMOTE/$d'"
  fi
done
rm -rf "$STAGE_ROOT"

echo "== забрано новых: $NEW, уже было: $SKIP"
echo "== локально: $(find "$LOCAL" -name complete.json -not -path "$STAGE_ROOT/*" | wc -l) комплектов, $(du -sh "$LOCAL" | cut -f1)"
ssh -p "$PORT" "$SRV" "du -sh '$REMOTE' 2>/dev/null; df -h / | tail -1"

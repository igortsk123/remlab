#!/usr/bin/env bash
# Приоритетная волна опыта с экспозицией (владелец 01.09: «отправляй в приоритет эти модели»).
#
# Порядок важен. Основной прогон нельзя рвать посреди пачки — ноды Salad тарифицируются, а
# оборванные задания вернутся дырками. Поэтому: ставим штатную паузу, ДОЖИДАЕМСЯ выхода
# конвейера (он сам гасит группу), поднимаем группу заново и гоним ТОЛЬКО наши задания.
# После волны стаскиваем результат и пересобираем страницу сравнения.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY=/home/pakar/venvs/scout/bin/python
PAUSE="$HOME/scout-scenes/mesh-batch.PAUSE"
MARKS=/home/pakar/igor/remlab/.memory_bank/_intake/owner-marks-mesh-color-0109.txt

echo "[$(date +%H:%M)] ставлю паузу основному конвейеру"
touch "$PAUSE"

# Ждём КОНКРЕТНЫЙ pid, а не по маске: `pgrep -f` ловит и обёртки харнесса с тем же текстом
# в командной строке, и тогда ожидание не кончится никогда (урок про pkill -f).
BPID="${1:-}"
if [ -n "$BPID" ]; then
  while kill -0 "$BPID" 2>/dev/null; do sleep 30; done
fi
echo "[$(date +%H:%M)] основной конвейер вышел"

echo "[$(date +%H:%M)] поднимаю группу"
$PY - <<'P'
import sys; sys.path.insert(0, '/home/pakar/igor/remlab/tools/scout/salad')
import ssh_run; ssh_run.ensure_group_started()
P

for f in mesh-exposure-jobs.json mesh-redo-jobs.json; do
  n=$($PY -c "import json;print(len(json.load(open('$HERE/../$f'))))" 2>/dev/null || echo 0)
  [ "$n" = "0" ] && { echo "[$(date +%H:%M)] $f пуст — пропускаю"; continue; }
  echo "[$(date +%H:%M)] волна $f: $n заданий"
  for try in 1 2 3 4 5 6 7 8; do
    $PY "$HERE/ssh_run.py" --jobs-file "$HERE/../$f" --keep-alive && break
    code=$?
    [ "$code" = "75" ] || break        # 75 = нет ёмкости: ждём и пробуем снова
    echo "[$(date +%H:%M)] нет прогретых нод — жду 3 мин (попытка $try)"
    sleep 180
  done
done

echo "[$(date +%H:%M)] стаскиваю результат"
bash "$HERE/drain.sh" --keep
$PY "$HERE/ingest_registry.py"

echo "[$(date +%H:%M)] гашу группу (деньги)"
$PY - <<'P'
import sys; sys.path.insert(0, '/home/pakar/igor/remlab/tools/scout/salad')
import ssh_run; ssh_run.stop_group()
P

echo "[$(date +%H:%M)] пересобираю страницу сравнения"
$PY "$HERE/color_test_page.py" "$MARKS"
rsync -a -e "ssh -p 22222 -o BatchMode=yes" "$HOME/scout-scenes/mesh-color/" \
      root@89.167.127.0:/opt/remlab/test/mesh-color/
echo "[$(date +%H:%M)] ГОТОВО — /test/mesh-color/"

#!/usr/bin/env bash
# Приоритетная волна опыта с экспозицией (владелец 01.09: «отправляй в приоритет эти модели»).
# Версия 2: с добором пропавших заданий. Отдельный файл, а не правка первого — правка скрипта,
# который в этот момент исполняется, сдвигает смещения, и bash дочитывает мусор.
#
# Порядок важен. Основной прогон нельзя рвать посреди пачки — ноды Salad тарифицируются, а
# оборванные задания вернутся дырками. Поэтому: штатная пауза, ждём выхода конвейера (он сам
# гасит группу), поднимаем группу заново и гоним ТОЛЬКО наши задания.
#
# ДОБОР ПРОПАВШИХ. В нынешнем ssh_run отказ `input_failed` считается ответом генератора:
# задание закрывается молча и в очередь перегона не попадает. Сегодня так съела 35 заданий
# нода 35b10e39 — у неё нет сети наружу, она не может скачать фото (предупредила соседняя
# сессия, чинит это отдельным планом). Поэтому после каждого прохода стаскиваем результат и
# сверяем ДЕРЕВО: чего нет — гоним ещё раз, до трёх проходов.
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

run_wave() {                       # $1 — файл заданий (абсолютный путь)
  jf="$1"
  for pass in 1 2 3; do
    n=$($PY -c "import json;print(len(json.load(open('$jf'))))" 2>/dev/null || echo 0)
    if [ "$n" = "0" ]; then echo "[$(date +%H:%M)] $(basename "$jf"): заданий нет"; return; fi
    echo "[$(date +%H:%M)] $(basename "$jf"), проход $pass: $n заданий"
    for try in 1 2 3 4 5 6 7 8; do
      if $PY "$HERE/ssh_run.wave.py" --jobs-file "$jf" --keep-alive; then break; fi
      if [ "$?" != "75" ]; then break; fi     # 75 = нет ёмкости: ждём и повторяем
      echo "[$(date +%H:%M)] нет прогретых нод — жду 3 мин (попытка $try)"
      sleep 180
    done
    bash "$HERE/drain.sh" --keep
    $PY "$HERE/wave_missing.py" "$jf" "$jf.missing" || return
    left=$($PY -c "import json;print(len(json.load(open('$jf.missing'))))" 2>/dev/null || echo 0)
    if [ "$left" = "0" ]; then echo "[$(date +%H:%M)] $(basename "$jf"): доехали все"; return; fi
    jf="$jf.missing"
  done
  echo "[$(date +%H:%M)] остались недоехавшие — см. $jf"
}

run_wave "$HERE/../mesh-exposure-jobs.json"
run_wave "$HERE/../mesh-redo-jobs.json"

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

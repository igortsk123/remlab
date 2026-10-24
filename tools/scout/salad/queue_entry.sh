#!/bin/bash
# ЗАПУСК КОНТЕЙНЕРА ГРУППЫ С ОЧЕРЕДЬЮ SALAD (план mesh-18, T-20261024-03): воркер генерации + воркер очереди Salad.
#
# ЗАЧЕМ. Через SSH-шлюз Salad до части машин задание не доходит (проба 24.10: вход рвёт соединение до приветствия SSH при
# живом контейнере). Очередь Salad возит задание изнутри машины: её воркер берёт задание и шлёт его на наш /generate.
# Образ не пересобираем: `command` группы заменяет CMD образа (`Dockerfile`: python -u /app/worker.py) этим скриптом.
#
# ПОРЯДОК. Скачать закреплённую версию воркера очереди и сверить SHA-256 (не совпало — выход до запуска чего-либо) →
# поднять генерацию → ждать её /ready (200 только после прогрева, `worker.py` ready) → поднять воркер очереди. Задания
# не берутся, пока модель не прогрета. Упал любой из двух — гасим второй и выходим: Salad перезапустит контейнер целиком
# (полуживой контейнер, где генерация умерла, а очередь берёт задания, хуже перезапуска).
#
# Текст скрипта уходит в `command` группы как `bash -c '<текст>'` (`queue_setup.py`): строки-комментарии и пустые строки
# при этом вырезаются (лимит Salad — 1000 знаков на элемент `command`). Переменные QW_* и APP — только для локальной
# проверки (`tests_queue.py`); на машине Salad их нет, действуют значения по умолчанию.
set -u
QV=${QW_VERSION:-v0.7.0}
QS=${QW_SHA256:-074a329cf6462e77fc7b72100f59d8a690831456d9420186a834a8f30634c9e4}
QU=${QW_URL:-https://github.com/SaladTechnologies/salad-cloud-job-queue-worker/releases/download/$QV/salad-http-job-queue-worker_x86_64.tar.gz}
D=${QW_DIR:-/opt/qw}
RU=${READY_URL:-http://127.0.0.1:8000/ready}
mkdir -p "$D" && cd "$D" || exit 10
for i in 1 2 3; do wget -q -O q.tgz "$QU" && break; sleep 10; done
echo "$QS  q.tgz" | sha256sum -c --status - || { echo "qw: sha256 не совпал"; exit 12; }
tar xzf q.tgz salad-http-job-queue-worker || exit 13
W=; Q=
trap 'kill $W $Q 2>/dev/null; exit 143' TERM INT
${APP:-python -u /app/worker.py} & W=$!
until python -c "import urllib.request as u;u.urlopen('$RU',timeout=5)" 2>/dev/null; do
kill -0 $W 2>/dev/null || { echo "qw: генерация умерла"; wait $W; exit 14; }
sleep 10; done
echo "qw: готово, очередь $QV"
./salad-http-job-queue-worker & Q=$!
wait -n
c=$?
echo "qw: выход $c, гашу второй"
kill $W $Q 2>/dev/null
exit $c

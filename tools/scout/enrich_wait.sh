#!/bin/bash
# Ждём пакеты обогащения и забираем результат в БД. Критерий успеха — ФАКТ, а не статус
# провайдера: `enrich.py --fetch` архивирует enrich-batch-id.txt только когда ВСЕ части
# completed И записаны в базу (счётчики потерь печатает fetch). Раньше «готово» считался любой
# нетерминальный статус — так 2 000 оплаченных строк не доехали до БД (урок 190, ADR-0073).
# Терминальный сбой (failed/expired/cancelled) — алерт и выход с ошибкой, файл остаётся человеку.
#   bash enrich_wait.sh          # опрос раз в 5 минут, до 24 часов (дальше пакет истекает сам)
set -u
cd "$(dirname "$0")"
PY="$HOME/venvs/scout/bin/python"
[ -s enrich-batch-id.txt ] || { echo "активного пакета нет — ждать нечего"; exit 0; }
for i in $(seq 1 288); do
  out=$($PY enrich.py --fetch 2>&1)
  echo "[$(date +%H:%M)] $out"
  if [ ! -s enrich-batch-id.txt ]; then
    echo "все части забраны и записаны в БД"
    $PY enrich.py --stats
    if grep -q "АЛЯРМ" <<<"$out"; then
      bash alert.sh "remlab: обогащение забрано, но потери >10% — см. refresh.log"
    fi
    # хвост цепочки на СВЕЖИХ данных: индекс кандидатов и комплекты (иначе новинки без индекса)
    $PY candidates.py --build && $PY sets_incremental.py --index
    # А7: судья-сэмпл свежих обогащений (сильная модель), дрифт к бейзлайну, копилка для голдена
    $PY enrich_judge.py || bash alert.sh "remlab: enrich_judge упал — см. refresh.log"
    exit 0
  fi
  if grep -qE 'статус (failed|expired|cancelled)' <<<"$out"; then
    echo "ТЕРМИНАЛЬНЫЙ сбой пакета — нужен человек, id остаются в enrich-batch-id.txt"
    bash alert.sh "remlab: batch failed/expired — обогащение НЕ забрано, гейт отправки закрыт"
    exit 1
  fi
  sleep 300
done
echo "истекли сутки ожидания — проверь пакеты вручную"
bash alert.sh "remlab: сутки ожидания batch истекли — проверь enrich-batch-id.txt"
exit 1

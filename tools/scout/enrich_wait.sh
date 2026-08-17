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
# Гейт старше 26 ч = пакет истёк или застрял (окно Batch API — 24 ч): алерт и ВЫХОД с
# ошибкой — опрашивать труп бессмысленно, id остаются человеку (T0, урок 203; verify-фикс:
# план требует FAIL, а не только алерт)
if [ -n "$(find enrich-batch-id.txt -mmin +1560 2>/dev/null)" ]; then
  bash alert.sh "remlab: enrich-batch-id.txt старше 26 ч — гейт заклинен, нужен человек"
  exit 1
fi
CRASHES=0
for i in $(seq 1 288); do
  out=$($PY enrich.py --fetch 2>&1)
  echo "[$(date +%H:%M)] $out"
  # Забор падает исключением (404/сеть/бag) — три подряд = алерт и выход, не молчать сутки
  if grep -q 'Traceback' <<<"$out"; then
    CRASHES=$((CRASHES+1))
    if [ "$CRASHES" -ge 3 ]; then
      bash alert.sh "remlab: enrich --fetch падает исключением 3 раза подряд — см. refresh.log"
      exit 1
    fi
    sleep 300; continue
  fi
  CRASHES=0
  # Терминальность по результату (урок 203): completed с 0 готовых — сбой, не «ждём дальше»
  if grep -q 'СБОЙ-РЕЗУЛЬТАТА' <<<"$out"; then
    echo "пакет completed, но результата нет (0 готовых) — нужен человек, id остаются"
    bash alert.sh "remlab: batch completed с 0 готовых (биллинг?) — обогащение НЕ забрано, гейт закрыт"
    exit 1
  fi
  if [ ! -s enrich-batch-id.txt ]; then
    echo "все части забраны и записаны в БД"
    $PY enrich.py --stats
    if grep -q "АЛЯРМ" <<<"$out"; then
      bash alert.sh "remlab: обогащение забрано, но потери >10% — см. refresh.log"
    fi
    # хвост цепочки на СВЕЖИХ данных: индекс кандидатов и комплекты (иначе новинки без индекса)
    $PY capabilities.py --build --export; $PY candidates.py --build && $PY sets_incremental.py --index   # Q6a: caps после забора обогащения
    # А7: судья-сэмпл свежих обогащений (сильная модель), дрифт к бейзлайну, копилка для голдена
    # 17.08: дрифт-судья (terra, 30 карточек) — раз в неделю (понедельник), не ежедневно; рубильник openai.off
    if [ -f openai.off ]; then echo "openai.off: enrich_judge (платный) пропущен" >> refresh.log; elif [ "$(date +%u)" = "1" ]; then $PY enrich_judge.py || bash alert.sh "remlab: enrich_judge упал — см. refresh.log"; else echo "enrich_judge: не понедельник — пропуск (еженедельный режим 17.08)" >> refresh.log; fi
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

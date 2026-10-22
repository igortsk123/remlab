Вердикт: план пока рано показывать владельцу. Центральный путь — не «пересборка», а массовый ремонт старого банка; утверждение про отсутствие реф-ссылки неверно; экзамен на копии сейчас фактически читает живой банк.

1. Как собирать банк

- Настоящий сборщик `sets3` — `compose2.py --style --bands all`: стилевой режим задаёт `sets3.json`, полный набор бэндов включается через `--bands all` (`tools/scout/compose2.py:24-29`, `tools/scout/compose2.py:533-537`, `tools/scout/compose2.py:1276-1289`).
- Рекомендация: добавить ему безопасный `SETS_OUTPUT=sets3.next.json`, собрать с нуля, а `enforce_contracts` запускать сначала как валидатор. Если свежая сборка требует сотен исправлений — расходятся сборщик и контракт, это надо чинить, а не маскировать ремонтом.
- `enforce_contracts` заменяет каждый слот отдельно по размеру и пропорциям (`tools/scout/sets_incremental.py:895-909`). Он не пересобирает капсулу, цвет/материалы, CLIP-связность и глобальное разнообразие, которые учитывает `compose2` (`tools/scout/compose2.py:65-84`, `tools/scout/compose2.py:477-524`).
- Потеряются/протухнут `alternates`: полный сборщик формирует их заново (`tools/scout/compose2.py:734`), ремонт обходит только `items` (`tools/scout/sets_incremental.py:878-930`).
- Бюджет: ремонт держит замену лишь в ±30% цены старого товара (`tools/scout/sets_incremental.py:371-401`) и пересчитывает сумму (`tools/scout/sets_incremental.py:943-951`), но не возвращает сет в ценовую полосу тира. Полный сборщик применяет тир по каждой роли, хотя общего жёсткого бюджета сета тоже нет (`tools/scout/compose2.py:315-319`, `tools/scout/compose2.py:404`).
- Минус полной сборки: дельта будет шире 192 слотов и потребует полноценного визуального одобрения. Зато пары и pod-комплекты создаются атомарно (`tools/scout/compose2.py:1154-1163`, `tools/scout/compose2.py:1212-1221`).
- В самом `compose2` ещё есть fail-open при сбое фото/mesh-предиката (`tools/scout/compose2.py:365-387`), тогда как contracts fail-closed. Это отдельный обязательный гейт паритета.

2. Товар divan.ru без фида

- Фраза плана «без фида нет реф-ссылки» неверна (`.memory_bank/plans/conv-13-bank-rebuild-live.md:26-28`). Исчезновение оффера переводит статус в `missing/archived`, но не очищает прежний `products.url` (`tools/scout/load3.py:527-541`).
- `catalog_media` по-прежнему отдаёт сохранённый `products.url` как партнёрский, одновременно помечая товар `gone` (`tools/scout/catalog_media.py:84-100`).
- `/go/` здесь не участвует: он обслуживает сметы и при отсутствии маршрута делает fallback на прямую ссылку (`lib/estimate/links.ts:17-24`). Статические банки/демо используют партнёрский URL напрямую (`.memory_bank/decisions/adr-0101-0150.md:1290-1294`, `:1314-1315`).
- Комиссия тоже не обязательно исчезла: API обновляет `charge_rub` по офферам последних 14 дней (`tools/scout/catalog_api_sync.py:199-206`). Но код не доказывает, что старая ссылка после выпадения из фида продолжит атрибутироваться.
- Итог: совет «не брать» правильный, но по другой причине. Формула наличия требует `feed_active`, даже при живой странице (`tools/scout/stock_truth.py:193-218`); сборщик берёт только `p.in_stock` (`tools/scout/compose2.py:238-244`), демо удаляет `gone` (`tools/scout/flat215_demo.py:410-430`).

3. Предохранитель и побочные записи

- При полном `compose2` отключать 25% вообще не нужно.
- Если оставлять миграционный вариант: `enforce_contracts(bank_path, allow_mass_copy, journal=False)`, причём `allow_mass_copy` разрешён только после проверки `realpath(bank_path) != realpath(SETS)`. Не менять `MAX_SETS_SHARE` и не вводить общий env-флаг: опечатка пути тогда опасна.
- Побочные эффекты `apply`:

  - `.bak-contracts` и запись банка (`tools/scout/sets_incremental.py:965-970`);
  - DDL/INSERT в `set_changes` (`tools/scout/heal_policy.py:103-118`);
  - сетевые проверки и запись общего `img-alive.json` через `alive_now` (`tools/scout/img_alive.py:123-140`).

- `catalog_media` имеет только внутрипроцессный кэш и читает БД (`tools/scout/catalog_media.py:49-70`); `sync_bank` автоматически не вызывается.
- `sets2.json` теперь не переписывается: вместо импорта исполняемого `compose2` используется `slot_rules` (`tools/scout/sets_incremental.py:201-203`).
- Ещё дыра: `sync_pairs` внутри contracts не попадает в журнал, а чисто парные изменения не запишутся, если `fixed == dropped == 0` (`tools/scout/sets_incremental.py:935-953`). На него нельзя полагаться как на самостоятельный шаг копии.

4. Экзамен и демо

- Для прямого `solver_run.py` `SETS_SNAPSHOT` достаточно (`tools/scout/solver_run.py:13-15`).
- Для `acceptance_run.py` — нет: он безусловно копирует живой `sets3.json` и перезаписывает переданный env (`tools/scout/acceptance_run.py:48-56`).
- Нужны также разные `ACC_REPORT_SUFFIX`: иначе старые строки JSONL считаются уже готовыми результатами (`tools/scout/acceptance_run.py:123-134`). Общий `scene-durations.json` тоже переписывается даже при suffix (`tools/scout/acceptance_run.py:159-170`).
- Planner-тесты `SETS_SNAPSHOT` не поддерживают и читают `sets3.json` напрямую, например `services/planner-solver/tests/test_bank_coverage.py:19-53`.
- У демо уже есть отдельный output через `FLAT215_DEMO_OUT` (`tools/scout/flat215_demo.py:21-22`), но входной банк захардкожен (`tools/scout/flat215_demo.py:879-886`). Дополнительно он пишет общий `demo-sets.json`, удаляет и пересчитывает общие layout-файлы (`tools/scout/flat215_demo.py:465`, `tools/scout/flat215_demo.py:803-810`).
- Без `--publish` сам скрипт прод не трогает (`tools/scout/flat215_demo.py:1475-1480`), но ночной cron публикует отдельно (`tools/scout/refresh_daily.sh:414-418`). Для ссылки владельцу нужна изолированная публикация в `/test/bank-next-<hash>/`; «не публиковать» и «дать ссылку /test/» сейчас противоречат друг другу.

5. Что добавить в план

- Порядок: безопасный output `compose2` → полный rebuild → синхронизация affiliate/media на копии → contracts dry-run → пары dry-run → инварианты банка → A/B экзамен → изолированное демо → владелец → атомарная подмена → ночной контроль.
- Требовать 126 сетов, неизменную карту `(band, style, tier, set_id)`, 0 `gone`, 0 pair mismatch, 0 нарушений contracts, живые affiliate URL, валидные alternates.
- Ограничить `coverage_gap`: нынешнее «0 или любой остаток объяснён» позволяет принять банк без ключевых ролей (`.memory_bank/plans/conv-13-bank-rebuild-live.md:48`). Для дивана, столика, media-bearer и обязательной пары допустим только ноль.
- Демо не доказывает полноту банка: перед показом оно само дозаполняет копию (`tools/scout/flat215_demo.py:473-478`, `:883-886`). Нужен отдельный отчёт «что демо замаскировало».
- В коде шесть стилей, не пять (`tools/scout/flat215_demo.py:50-65`); критерий плана на пять стилей ошибочен (`.memory_bank/plans/conv-13-bank-rebuild-live.md:34`).
- После подмены ожидаемый contracts-результат — `0 замен`, а не просто «≤25%» (`.memory_bank/plans/conv-13-bank-rebuild-live.md:36-37`). Любая массовая ночная дельта означает, что кандидат приняли грязным.

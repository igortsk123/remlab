## Вывод

Вердикт: **условный no-go** на merge+SQL в текущем виде. Основная идея правильная, но перед применением нужны три небольшие доработки:

1. расширить правило на аксессуары/табуреты и корректно разобрать `Модуль … дивана`;
2. запретить удержание и promote кандидата, если роль слота несовместима с актуальным `cat_role`;
3. обновлять `mesh_demand.role` при re-upsert.

После этого порядок «код → shadow → безопасная SQL-миграция» верный.

## 1. Правило ролей

Правило удачно расположено: после категориальной классификации, но до разбора размеров; снятие роли не архивирует товар, потому что `accepted` вычислен раньше: [load3.py:236](/home/pakar/igor/remlab/.claude/worktrees/roles-53/tools/scout/load3.py:236), [load3.py:245](/home/pakar/igor/remlab/.claude/worktrees/roles-53/tools/scout/load3.py:245), [load3.py:255](/home/pakar/igor/remlab/.claude/worktrees/roles-53/tools/scout/load3.py:255).

Но оно пока не вполне «общее»:

| Название | Сейчас | Оценка |
|---|---:|---|
| `Диван-кровать` | диван | правильно |
| `Пуф-трансформер в кровать` | пуф | разумно, но функционально неоднозначно |
| `Кресло-мешок` | исходная роль | правильно только если исходная роль уже `кресло` |
| `Диван с оттоманкой` | диван | правильно |
| `Оттоманка …` | пуф | возможный false positive: бывает крупной секцией/кушеткой |
| `Банкетка-диван` | пуф | формально по первому типу, но составное название неоднозначно |
| `Модуль угловой дивана …` | диван | ошибка: слово `дивана` полностью отключает правило модуля |
| `Секция угловая дивана …` | диван | пропуск: `секция` не распознаётся |
| `Топпер для дивана` | диван | ошибка |
| `Табурет Glasar` | диван/кресло | ошибка |

Причина — `_SEAT_HEAD` объединяет диван и кресло и при срабатывании сохраняет исходную роль; модуль рассматривается только при полном отсутствии любого слова `диван/кресло`: [category_map.py:314](/home/pakar/igor/remlab/.claude/worktrees/roles-53/tools/scout/category_map.py:314), [category_map.py:330](/home/pakar/igor/remlab/.claude/worktrees/roles-53/tools/scout/category_map.py:330), [category_map.py:336](/home/pakar/igor/remlab/.claude/worktrees/roles-53/tools/scout/category_map.py:336). Тест даже закрепляет `Кресло с пуфом` при исходной роли `диван` как `диван`: [category_map.py:501](/home/pakar/igor/remlab/.claude/worktrees/roles-53/tools/scout/category_map.py:501).

Рекомендую оставить один ordered type-rule, но различать результаты:

- диван/софа/тахта/кушетка → `диван`;
- кресло → `кресло`;
- пуф/банкетка/самостоятельная оттоманка → `пуф`;
- табурет → `стул`;
- кровать, топпер/наматрасник/чехол, отдельный модуль/секция → без роли;
- `Модуль … дивана` трактовать как секцию, когда модуль/секция — главный тип, а `дивана` является принадлежностью.

`Модуль дивана` сейчас правильно оставлять **без scene-role**. Новой роли не следует добавлять, пока нет конструктора совместимых модулей, слота и правил сборки. Если товар нужно сохранить для будущего, лучше отдельный `product_type=sofa_module`, а не `cat_role`.

## 2. Live bank и демо

Текущее состояние безопаснее, чем выглядит:

- `write_enabled=false`, поэтому `bank_refresh` живой банк сейчас не пишет: [bank-candidate.json:26](/home/pakar/igor/remlab/tools/scout/rules/bank-candidate.json:26).
- При этом запускается старый `sets_heal --apply`: [refresh_daily.sh:330](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:330), [refresh_daily.sh:343](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:343).
- Heal считает `cat_role is null` выбытием и пытается заменить позицию, иначе снимает её: [sets_incremental.py:582](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:582).

По проверенному `shadow.json` в живом `sets3.json` затронуты только два товара, и оба уже находятся в слотах `пуф`. Roleless модулей/кроватей в live bank нет. Поэтому именно эта миграция текущие live-сеты не опустошит.

Однако найден риск кандидата: текущий `sets3.next.json` содержит четыре позиции `Босс пуф` в слотах `кресло/кресло 2` и один такой запасной. Они могут пережить SQL:

- `catalog_media` вообще не читает `cat_role`: [catalog_media.py:53](/home/pakar/igor/remlab/tools/scout/catalog_media.py:53);
- удержание проверяет доступность и slot contract, но не актуальную каталожную роль: [compose2.py:557](/home/pakar/igor/remlab/tools/scout/compose2.py:557);
- `bank_invariants` также не проверяет соответствие slot↔`cat_role`: [bank_invariants.py:99](/home/pakar/igor/remlab/tools/scout/bank_invariants.py:99);
- поэтому `bank_promote.strict` их не заблокирует: [bank_promote.py:121](/home/pakar/igor/remlab/tools/scout/bank_promote.py:121).

Нужен единый `slot_catalog_compatible()` для keep, invariants и promote. Нумерованные слоты сравнивать по base-role; исключение — планировочная `банкетка`, которая намеренно может происходить из `пуф/диван`.

`115/126` — реальная, воспроизводимая разница **свежей полной пересборки**: контрольный повтор дал `0/126`. Но это не означает одномоментный churn live bank:

- nightly `bank_prepare` удерживает прошлый кандидат: [compose2.py:545](/home/pakar/igor/remlab/tools/scout/compose2.py:545);
- при включении писателя promote ограничен `floor(25% × 126)=31` ячейкой и пропускает только ready+strict+exam+demo: [bank_promote.py:236](/home/pakar/igor/remlab/tools/scout/bank_promote.py:236);
- сейчас писатель вообще выключен.

`demo_band` и `flat215_demo` работают по живому банку после возможной записи: [refresh_daily.sh:420](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:420), [refresh_daily.sh:426](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:426). Кандидат сам по себе демо не меняет. У выбранного демо обязательно наличие слота `диван`, hidden-сеты исключаются: [flat215_demo.py:69](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:69).

## 3. `mesh_queue.role`

Добавить в upsert `role=excluded.role` в целом безопасно и правильно: сейчас обновляются priority/media/status, но не role: [mesh_queue.py:388](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:388).

Почему безопасно:

- role не входит в ключи `mesh_jobs`/`asset_revisions`;
- дневной бюджет глобальный, не по ролям: [mesh_scheduler.py:35](/home/pakar/igor/remlab/tools/scout/mesh_scheduler.py:35), [mesh_scheduler.py:113](/home/pakar/igor/remlab/tools/scout/mesh_scheduler.py:113);
- диван, кресло, пуф и стул используют одну mesh-стратегию;
- актуальная role уже передаётся в экспорт задания и влияет на role-specific preprocessing/orientation: [mesh_queue.py:423](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:423).

Оговорки:

- `mesh_demand.role == cat_role` не является абсолютным инвариантом: спрос от опубликованного слота намеренно использует роль слота, включая planning aliases;
- для товара без роли нельзя писать `NULL` — колонка `NOT NULL`; он должен выпасть из `want` и перейти в `not_required`;
- уже submitted payload не изменится, готовый меш не должен перегенерироваться;
- существующее orientation-решение при `диван→пуф` автоматически не сбрасывается. Это обычно безвредно, но стоит отдельно посчитать такие принятые ревизии.

## 4. Топперы и табуреты

Да:

- топпер/наматрасник/чехол дивана → без роли;
- обычный табурет → `стул` в текущей модели, потому что compose и столовая используют только роль `стул`.

Барные, офисные и чрезмерно высокие варианты уже должен отсечь общий фильтр: [unfit.py:11](/home/pakar/igor/remlab/tools/scout/unfit.py:11), [unfit.py:26](/home/pakar/igor/remlab/tools/scout/unfit.py:26). Отдельную роль `табурет` имеет смысл вводить только вместе со слотом и правилами композиции.

## 5. `sql_scan`

Alias-баг подтверждён: регулярное выражение принимает только `UPDATE <table> SET`, поэтому `UPDATE products p SET` не находится: [db-migrate-safe.sh:29](/home/pakar/igor/remlab/tools/ops/db-migrate-safe.sh:29).

Но уточнение: для файла только с таким UPDATE результатом будет **полный дамп**, потому что «таблиц не нашли» переводит режим в full: [db-migrate-safe.sh:73](/home/pakar/igor/remlab/tools/ops/db-migrate-safe.sh:73), [db-migrate-safe.sh:101](/home/pakar/igor/remlab/tools/ops/db-migrate-safe.sh:101). Schema-only возможен в смешанном SQL, если сканер увидел лишь создаваемые новые таблицы.

Минимальная правка:

- разрешить после имени таблицы необязательное `[AS] alias`;
- в `awk` для UPDATE брать токен после `UPDATE [ONLY]`, а не `$NF`;
- добавить selftests для `products set`, `products p set`, `products AS p set`, `ONLY public.products p set`.

Сгенерированный коммитом SQL уже намеренно использует alias-free форму: [seat_role_shadow.py:129](/home/pakar/igor/remlab/.claude/worktrees/roles-53/tools/scout/seat_role_shadow.py:129).

## Рекомендованный порядок

1. Доработать lexical rule и тесты для перечисленных edge cases.
2. Добавить slot↔catalog-role gate в keep/invariants/promote; пересобрать или инвалидировать текущие плохие ячейки кандидата.
3. Добавить `role=excluded.role` в mesh upsert.
4. Исправить и протестировать `sql_scan`.
5. Merge кода.
6. Повторный shadow по актуальной БД и проверка live/candidate banks.
7. Alias-free SQL через `db-migrate-safe.sh`, с ожидаемыми flow-counts и post-check.
8. Оставить `write_enabled=false` минимум на одну контрольную ночь; включать писатель только после чистого кандидата.

Неопределённость: прямой повтор DB-запросов из reviewer sandbox был заблокирован доступом к Docker socket; числа 330/4639 подтверждены по сохранённому `shadow.json`, а логика, банки и generated artifacts проверены непосредственно.
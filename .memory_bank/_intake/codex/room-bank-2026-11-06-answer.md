## Вывод

План пока не готов к реализации. Направление верное — единый механизм с параметром комнаты лучше отдельной копии, — но в черновике отсутствуют несколько блокирующих контрактов:

- стабильная идентичность ячейки спальни и начальная загрузка первого живого банка;
- источник готовности ассетов для `room_catalog`;
- доказательство, что меш уже доступен витрине;
- сквозной `run_id`, не позволяющий продвинуть вчерашний кандидат после сегодняшнего сбоя;
- кандидат-специфичные exam/demo-проверки спальни;
- атомарность кандидата и ненулевой код при нарушениях;
- жёсткая развязка флагов записи гостиной и спальни.

До этого `write_enabled` спальни включать нельзя. `write_enabled` гостиной сейчас действительно `false` и должен остаться таким минимум контрольную ночь после фактического вливания T‑53: [`bank-candidate.json:26`](/home/pakar/igor/remlab/tools/scout/rules/bank-candidate.json:26).

## 1. Проверка утверждений плана

| Утверждение | Вердикт | Доказательство |
|---|---|---|
| `write_enabled` общий | Верно, и риск шире, чем сказано | Все четыре `bank_*` читают один `rules/bank-candidate.json`: [`bank_prepare.py:36`](/home/pakar/igor/remlab/tools/scout/bank_prepare.py:36), [`bank_promote.py:60`](/home/pakar/igor/remlab/tools/scout/bank_promote.py:60), [`bank_pending.py:48`](/home/pakar/igor/remlab/tools/scout/bank_pending.py:48), [`bank_refresh.py:52`](/home/pakar/igor/remlab/tools/scout/bank_refresh.py:52). Ночь вычисляет единственный `BANK_WRITE`, которым одновременно включает `bank_refresh` гостиной и выключает прежних писателей гостиной: [`refresh_daily.sh:325`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:325), [`refresh_daily.sh:343`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:343), [`refresh_daily.sh:422`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:422). |
| Пути поколений зашиты под гостиную | Верно | Живой файл — `sets3.json`, manifest общий, поколения — общий каталог: [`bank_refresh.py:55`](/home/pakar/igor/remlab/tools/scout/bank_refresh.py:55). Имя снимка буквально `sets3-…`: [`bank_refresh.py:117`](/home/pakar/igor/remlab/tools/scout/bank_refresh.py:117). У promote и pending также общие файлы `sets3.next.json`, `bank-promote.json`, `bank-pending.json`: [`bank_promote.py:61`](/home/pakar/igor/remlab/tools/scout/bank_promote.py:61), [`bank_pending.py:48`](/home/pakar/igor/remlab/tools/scout/bank_pending.py:48). |
| `check_bank` всегда возвращает 0 | Формулировка неверна | Сама функция реально собирает нарушения, включая HARD солвера: [`compose_bedroom.py:594`](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:594), [`compose_bedroom.py:626`](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:626). Но обычный `main` печатает нарушения и безусловно возвращает 0: [`compose_bedroom.py:688`](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:688). Только отдельный `--check` возвращает 1: [`compose_bedroom.py:797`](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:797). Корректно: «нарушения не влияют на код возврата обычной сборки». |
| Запись спальни неатомарна | Верно | Банк и отчёт пишутся прямо в целевой файл через `open(..., 'w')`: [`compose_bedroom.py:677`](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:677), [`compose_bedroom.py:686`](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:686). Проверка идёт уже после перезаписи. |
| `--nightly` только для включённых комнат; включённых нет | Верно, но источник флага не тот, что у витрины | Композитор фильтрует по `flat215-bedrooms.json`: [`compose_bedroom.py:663`](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:663). Все варианты геометрии сейчас `enabled:false`, например [`flat215-bedrooms.json:9`](/home/pakar/igor/remlab/tools/scout/flat215-bedrooms.json:9), [`flat215-bedrooms.json:42`](/home/pakar/igor/remlab/tools/scout/flat215-bedrooms.json:42). Это не флаг публикации из партнёрского реестра. |
| Комната включается в `data/partners/demo.json` | Механизм верен, ссылка плана вводит в заблуждение | `room_flags` принимает только настоящее `enabled is True`: [`flat215_demo.py:523`](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:523). Но у спальни в текущем реестре поля `enabled` вообще нет: [`demo.json:64`](/home/pakar/igor/remlab/data/partners/demo.json:64). Поэтому сейчас она выключена по умолчанию. |
| Демо читает живой банк, иначе `.next` | Неполно | Явный `BEDROOM_SETS` имеет приоритет. Публикуемая папка всегда использует живой путь, даже если файла нет; `.next` берёт только сборка рядом: [`flat215_demo.py:1130`](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1130). Кандидат на прод молча не попадает — это правильно. |
| Живого банка спальни нет, сборщик отказывается его писать | Верно | `room_bank_output` запрещает и `sets-bedroom.json`, и `sets3.json`: [`bank_paths.py:93`](/home/pakar/igor/remlab/tools/scout/bank_paths.py:93). На проверенном HEAD отсутствуют и `sets-bedroom.json`, и `sets-bedroom.next.json`. |

Отдельно: `slot_catalog_compatible` в текущем `main` отсутствует. Условие плана «если к тому времени влит» недостаточно — T‑53 должен стать обязательным prerequisite.

## 2. Обобщение или отдельная обёртка

Я выбрал бы общий движок `bank_*` с `--room`, где значение по умолчанию — `living`, но не в виде россыпи `if room == bedroom`. Нужны:

- `RoomBankSpec`: пути live/candidate/report/pending/work/generations, правила, ключ ячейки;
- адаптер composer из `room_profile.COMPOSERS`;
- адаптер каталога и готовности ассета;
- адаптер strict/exam/demo;
- общий транзакционный writer/rollback.

Старые команды без `--room` должны попадать в неизменённый living-adapter. Совместимая тонкая CLI-обёртка поверх общего ядра полезна; тонкая обёртка вокруг нынешнего living-кода — нет.

Причина: нынешние модули не являются просто «гостиной с другими путями»:

- `set_identity` жёстко считает ячейкой `(band, style, tier)`: [`set_identity.py:31`](/home/pakar/igor/remlab/tools/scout/set_identity.py:31). Для спальни нужен как минимум `(room_id, purpose, band, style, tier)`.
- Более того, `set_id` спальни сейчас зависит от SKU: [`compose_bedroom.py:134`](/home/pakar/igor/remlab/tools/scout/compose_bedroom.py:134). При любой замене это другой set, а не новое поколение прежней ячейки.
- Promote гостиной содержит специфические правила столовой, связок гостиной, `acceptance-scenes.json` и `flat215_demo.choose_banks`: [`bank_promote.py:107`](/home/pakar/igor/remlab/tools/scout/bank_promote.py:107), [`bank_promote.py:368`](/home/pakar/igor/remlab/tools/scout/bank_promote.py:368), [`bank_promote.py:413`](/home/pakar/igor/remlab/tools/scout/bank_promote.py:413).
- Pending гостиной читает готовность из `products`: [`bank_ready.py:151`](/home/pakar/igor/remlab/tools/scout/bank_ready.py:151). Мебель спальни во многом живёт в `room_catalog`, для неё канон — `offer_asset_binding`: [`room_bindings.py:16`](/home/pakar/igor/remlab/tools/scout/room_bindings.py:16).

Альтернативы:

- Полная копия `bedroom_bank_*`: быстро сначала, но два writer/rollback-протокола неизбежно разойдутся.
- Обёртка, выставляющая `BANK_CANDIDATE`, `BANK_GENERATIONS` и вызывающая нынешние файлы: мало кода, но небезопасна из-за неверной идентичности, living-specific strict и неверного источника готовности.
- Общие ядра плюс адаптеры комнат: больший первоначальный объём, зато один протокол записи, отката, manifest и crash-recovery. Это мой выбор.

Это не маленькая правка путей: ориентировочно средний рефакторинг нескольких модулей и существенный набор тестов.

## 3. Сторожа спальни

Обязательный набор перед продвижением:

1. Идентичность и полнота.

   - Уникальный полный ключ ячейки.
   - Стабильный `set_id`, не зависящий от состава.
   - Точная ожидаемая матрица активных ячеек из `composer.rules`; текущие правила дают 60 непустых ячеек спальни.
   - Запрет пропавших, лишних и дублирующихся ячеек.

2. Аттестация профиля и сборщика.

   В candidate/manifest нужны `room_type`, `profile_id`, `profile_version`, `content_sha`, `composer.plugin` и digest правил. Сейчас профиль действительно задаёт composer спальни: [`bedroom.json:11`](/home/pakar/igor/remlab/tools/scout/rules/profiles/bedroom.json:11), но банк это происхождение не фиксирует.

3. Strict по текущему каталогу.

   - товар существует и доступен;
   - URL и фото текущие;
   - слот совместим с текущей ролью каталога;
   - размеры проходят полосу слота;
   - обязательное ядро, количество тумб, alternates;
   - сумма и ценовой порядок тиров;
   - разнообразие между стилями;
   - `planner.validate`: HARD = 0.

   Текущий `check_bank` покрывает часть размеров, ядра, alternates, геометрию и разнообразие, но не перепроверяет текущую роль товара в каталоге.

4. Готовность витрины по стратегии профиля.

   - Для `mesh` — binding `ready`, правильная ревизия/ориентация/appearance и `published_3d`.
   - Для `flat`/`cutout` — их собственные требования, без ложного требования меша.
   - Для `room_catalog` использовать `offer_asset_binding`; `products.mesh_status` недостаточен.

   Канон уже различает `local_3d`, `appearance` и `published_3d`: [`room_bindings.py:16`](/home/pakar/igor/remlab/tools/scout/room_bindings.py:16), а адаптер отдаёт эти capabilities: [`catalog_items.py:305`](/home/pakar/igor/remlab/tools/scout/catalog_items.py:305).

5. Candidate-specific exam.

   Нынешний `bedroom_exam.py` проверяет статические kits и не принимает банк-кандидат: [`bedroom_exam.py:35`](/home/pakar/igor/remlab/tools/scout/bedroom_exam.py:35), [`bedroom_exam.py:48`](/home/pakar/igor/remlab/tools/scout/bedroom_exam.py:48). Он полезен как регрессия солвера, но не доказывает пригодность заменяемой ячейки. Нужен прогон фактических items/layout каждой продвигаемой ячейки и сравнение old/hybrid.

6. Bedroom demo old против hybrid.

   Аналог living `replaced=0, dropped=0` здесь неприменим: bedroom-варианты не используют тот же журнал дозаполнения. Нужно проверять:

   - выбранный `(room_id, style)` не исчез;
   - не появилось нового `incomplete`;
   - ядро кровать + тумба присутствует;
   - нет `dims_unknown` у размещаемого;
   - каждый mesh-required объект ссылается на реально опубликованный `mesh_id`;
   - нет новых HARD после one-layout.

7. Доля замен.

   Не более 25% существующих ячеек за одну запись, целыми ячейками. Группировка tier/diversity должна учитывать `room_id` и `purpose`, иначе спальни и назначения будут ошибочно сравниваться друг с другом.

## 4. Порядок ночи

Блок спальни должен стоять после полного блока гостиной, включая возможный `bank_refresh`, но до общей сборки и публикации демо.

Рекомендуемая последовательность:

```text
общие каталожные шаги
→ living: prepare → pending → promote → [refresh]
→ room_catalog спальни
→ room_bindings
→ bedroom: prepare
→ публикация мешей кандидата комнаты --rooms-only
→ room_bindings повторно, чтобы подтвердить published_3d
→ pending → promote(strict → exam → demo)
→ [bedroom refresh → post-write verify]
→ обычные demo_band / mesh_publish гостиной
→ flat215_demo → demo_rt → publish
```

`room_catalog` сейчас запускается только непосредственно перед демо, уже после living bank-цепочки: [`refresh_daily.sh:426`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:426), [`refresh_daily.sh:435`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:435). Для свежего кандидата спальни это слишком поздно.

Комнатный mesh publisher уже умеет брать явно `.next` и работать отдельно от гостиной: [`room_publish.py:16`](/home/pakar/igor/remlab/tools/scout/room_publish.py:16), [`mesh_publish.py:28`](/home/pakar/igor/remlab/tools/scout/mesh_publish.py:28).

Каждый этап спальни должен быть связан явным `&&`/run-id, а не просто последовательностью `step`. Сейчас `step` возвращает ошибку, но shell продолжает: [`refresh_daily.sh:47`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:47). Поэтому существующая цепочка может после упавшего prepare вызвать promote: [`refresh_daily.sh:411`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:411), [`refresh_daily.sh:419`](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:419).

Это реальная дыра и в гостиной: `bank_promote` не требует отчёта сегодняшнего prepare, а читает существующие candidate/pending: [`bank_promote.py:479`](/home/pakar/igor/remlab/tools/scout/bank_promote.py:479). Свежий manifest после суда вчерашнего кандидата затем удовлетворит проверку возраста writer. Нужен единый `run_id`, проходящий prepare → pending → promote → refresh, и writer обязан проверить его.

Если спальня откатилась:

- откат завершён и SHA восстановленного live подтверждён — продолжать публикацию из восстановленного банка;
- сбой произошёл до изменения live — продолжать из прежнего банка;
- состояние live неопределённо или откат не подтвердился — публикацию сегодняшнего demo пропустить, оставив вчерашнее;
- если спальня ещё выключена в реестре, её bank-сбой не должен блокировать публикацию гостиной.

Текущий `publish_demo.sh` не имеет отката: он делает `rsync --delete` прямо в live-каталог, затем лишь проверяет HTTP: [`publish_demo.sh:23`](/home/pakar/igor/remlab/tools/scout/publish_demo.sh:23). Поэтому T‑59 — prerequisite перед включением спальни на главной, а не необязательный follow-up.

## 5. Главные упущения и риски

Критические:

- Первый живой банк неоткуда продвигать. `bank_promote` и writer требуют существующий live: [`bank_promote.py:492`](/home/pakar/igor/remlab/tools/scout/bank_promote.py:492), [`bank_refresh.py:184`](/home/pakar/igor/remlab/tools/scout/bank_refresh.py:184). Нужен отдельный bootstrap-протокол: полностью проверенный candidate, ручное разрешение, generation-0 и явная семантика rollback.
- Текущая identity спальни несовместима с механизмом гостиной.
- `check_bank` не блокирует запись кандидата.
- Флаг сборки банка смешан с флагом показа. Банк должен обновляться по своим `prepare/promote/write_enabled`, независимо от `rooms[].enabled`.
- T‑53 ещё не в `main`; нельзя оставлять его условным.
- Нет run-id/chain attestation.
- Нет crash-recovery между записью live и записью journal. Сейчас snapshot создаётся, затем live заменяется, затем пишется journal: [`bank_refresh.py:233`](/home/pakar/igor/remlab/tools/scout/bank_refresh.py:233), [`bank_refresh.py:244`](/home/pakar/igor/remlab/tools/scout/bank_refresh.py:244). Падение процесса в этом окне оставит изменённый банк без зарегистрированного поколения.
- Прихожая не имеет demo-пути — это уже зафиксировано в parity-конфигурации: [`parity-living.json:12`](/home/pakar/igor/remlab/tools/scout/rules/parity-living.json:12). Для неё нужен другой showability-гейт, а не фиктивный bedroom demo.

## Обязательные тесты

Минимальный набор перед shadow-ночами:

- golden-тест: все `bank_*` без `--room` дают те же файлы, JSON, пути и решения для living;
- truth table флагов: living/bedroom `write_enabled` во всех четырёх комбинациях;
- включение bedroom writer не меняет `BANK_WRITE`, не отключает legacy writers гостиной и не вызывает living `bank_refresh`;
- атомарность candidate/report с fault injection до и во время rename;
- обычный `compose_bedroom` возвращает ненулевой код при HARD;
- identity спальни: reorder, duplicate, missing, extra, изменение SKU при стабильном set_id;
- bootstrap и повторный bootstrap;
- strict на ушедший товар, stale URL/фото, неправильную catalog-role, размер, qty, HARD, отсутствующий binding, неопубликованный меш;
- профиль/composer SHA mismatch;
- cap 25%, включая границу и целостность ячейки;
- stale candidate/state/manifest и несовпадающий `run_id`;
- writer: manifest/live/hybrid/candidate hashes, чужая комната в manifest, изменение непродвинутой ячейки;
- crash после snapshot, после rename live, до journal; автоматическое восстановление;
- rollback byte-for-byte, hold только своей комнаты;
- dry-demo old/hybrid с потерей варианта, отсутствующим core, mesh и размерами;
- nightly failure injection на каждом шаге: living завершается, спальня остаётся LKG, demo публикуется из LKG;
- [`tests_refresh_order.py`](/home/pakar/igor/remlab/tools/scout/tests_refresh_order.py:88) расширить независимым room-блоком;
- parity living = 0 и parity bedroom по `catalog, bank, exam, demo, cams`: соответствующие шаги уже описаны в [`parity-living.json:7`](/home/pakar/igor/remlab/tools/scout/rules/parity-living.json:7).

## Рекомендация

Переписать план до выдачи:

1. Сначала контракт `RoomBankSpec`, стабильная identity и bootstrap.
2. Затем общий transaction writer/rollback с recovery.
3. Потом source-specific readiness и bedroom strict/exam/demo.
4. После этого nightly-блок с независимыми флагами.
5. Две shadow-ночи спальни с rehearsal записи в копию и отката по SHA.
6. Одна контрольная ночь гостиной после T‑53 при `living.write_enabled=false`.
7. По отдельному разрешению включить только `bedroom.write_enabled`.
8. Показ спальни в реестре — отдельное решение после T‑59 и визуальной приёмки.

## Неопределённости

- T‑53, возможно, существует в другой ветке, но в проверенном `main` функции `slot_catalog_compatible` нет.
- Живые данные БД, внешние parity-эталоны и ночные артефакты не прогонялись; ревью выполнено по текущему коду.
- Нужно решение владельца, считать ли все 60 активных bedroom-ячеек обязательной матрицей либо разрешать sparse candidate. Для механизма «как у гостиной» рекомендую полную матрицу.
- Для прихожей требуется отдельно определить пользовательский preview/demo-гейт.

Файлы не изменялись.
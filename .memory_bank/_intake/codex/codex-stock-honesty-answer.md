## Вывод

План в текущем виде начинать целиком нельзя. Направление верное, но есть пять блокеров:

1. Н0 вводит новые отрицательные сигналы раньше, чем закрыты дефекты применения и карантина.
2. Отброшенные гейтом наблюдения позднее могут снова попасть в `fold()`.
3. Н2 смешивает «страница существует», «товар в наличии» и «проверка свежая».
4. Р1 не закрывает уже работающий некалиброванный вывод размеров из меша в демо и сохранение старых осей в сетах.
5. Н3 превращает цену страницы в новую коммерческую истину без доказательства, что извлечена цена именно выбранного SKU.

Правильный порядок: сначала безопасность применения Н1, затем Н0 в тени, потом модель честного наличия Н2. Размеры — отдельной атомарной миграцией банка. Цена страницы пока только наблюдение.

## 1. Н0: регулярка и `overallStock`

- **Блокер. Нельзя активировать новый отрицательный парсер до Н1.** Сейчас одного `oos/gone` достаточно для снятия: `CONFIRM_NEEDED=1`, а `apply_run()` сразу вызывает `reconcile()`. Ошибка на доле большого магазина немедленно попадёт в сеты. [stock_truth.py:30](/home/pakar/igor/remlab/tools/scout/stock_truth.py:30), [stock_check.py:483](/home/pakar/igor/remlab/tools/scout/stock_check.py:483)

- **Блокер. Выборка 30 и критерий «совпало ≥95%» непригодны для защиты от массового ложного снятия.** Один ложный отрицательный из 30 всё ещё даст 96,7%, но в масштабе 11 тысяч товаров это сотни снятий. До включения нужно:
  
  - не менее 300 заведомо живых карточек с нулём ложных `oos/gone` — это лишь ограничивает ошибку примерно 1% сверху при 95% доверии;
  - все доступные известные `oos/gone`, желательно ≥30 каждого класса;
  - полный shadow-прогон магазина без записи `in_stock`;
  - ручная проверка всех новых отрицательных сигналов, а не случайных 30 страниц.

  Это прямо следует из уже пережитого дефекта текстового маркера. [anti-patterns.md:593](/home/pakar/igor/remlab/.memory_bank/anti-patterns.md:593), [stock-and-dims-honesty.md:80](/home/pakar/igor/remlab/.memory_bank/plans/stock-and-dims-honesty.md:80)

- **Важно. `overallStock` — не «второй голос».** Это тот же HTTP-ответ, та же карточка и, возможно, общий остаток модели/сети магазинов. Его надо объединять со schema-сигналом внутри одного вызова `classify()`, а в `fold()` передавать один вердикт. Безопасная логика:
  
  - любой корректно привязанный положительный сигнал побеждает;
  - отрицательный — только если нет положительного;
  - конфликт schema и inline JSON → `unknown`, а не голосование два против одного.

  Текущая защита «положительный среди смешанных offers побеждает» обоснованна и не должна исчезнуть. [page_alive.py:119](/home/pakar/igor/remlab/tools/scout/page_alive.py:119)

- **Важно. Простого расширения `_SCHEMA_RE` недостаточно.** Текущий шаблон требует `itemprop` раньше `content` и ищет availability по всему HTML, включая варианты и аксессуары. `href=` надо разбирать независимо от порядка атрибутов; JSON-LD — ограничивать объектом `Product` текущей карточки. Иначе snake_case будет исправлен, но привязка сигнала к SKU останется слабой. [page_alive.py:65](/home/pakar/igor/remlab/tools/scout/page_alive.py:65)

- **Блокер. «Ранний обрыв на отрицательном признаке» надо удалить из плана.** Это уже отменено ADR‑0148: отрицательная разметка аксессуара может идти раньше положительной разметки товара. Читать можно прекращать только по положительному сигналу либо после полностью разобранного объектно-привязанного JSON. [stock_check.py:127](/home/pakar/igor/remlab/tools/scout/stock_check.py:127), [decisions.md:3022](/home/pakar/igor/remlab/.memory_bank/decisions.md:3022)

- **Важно. Новый классификатор требует `PROBE_VERSION=2`.** И история, и гейт должны учитывать только ту же версию контракта. Сейчас версия равна 1, а исторический запрос не фильтрует её. [page_alive.py:50](/home/pakar/igor/remlab/tools/scout/page_alive.py:50), [stock_check.py:348](/home/pakar/igor/remlab/tools/scout/stock_check.py:348)

- **Важно. WAF-маркеры без ограничения длины тоже могут ложно сработать.** Убрать зависимость от общей длины разумно, но требовать структурный признак challenge в первых чанках/URL и проверить на живых страницах. Сейчас HTTP-ошибка читает только один чанк. [page_alive.py:76](/home/pakar/igor/remlab/tools/scout/page_alive.py:76), [stock_check.py:139](/home/pakar/igor/remlab/tools/scout/stock_check.py:139)

## 2. Н1: состояния, гейты и доменный автомат

- **Блокер. Карантин сейчас не окончателен.** Наблюдения сохраняются до гейта; текущий карантин исключает SKU только из `touched`, но следующий успешный прогон снова читает всю 90-дневную историю — без признака, что старое наблюдение было отвергнуто. Поэтому карантинный ложный 404 способен «всплыть» позднее. [stock_check.py:333](/home/pakar/igor/remlab/tools/scout/stock_check.py:333), [stock_check.py:374](/home/pakar/igor/remlab/tools/scout/stock_check.py:374), [stock_check.py:379](/home/pakar/igor/remlab/tools/scout/stock_check.py:379)

  Нужен `observation_disposition=accepted|quarantined|anchor` либо таблица результата `(run_id, shop/domain, admitted)`. `fold()` и историческая норма читают только `accepted`.

- **Блокер. Старый негатив продолжает действовать после смены URL.** `url_key()` обещает обнуление свидетельства, но `TRUTH_SQL` применяет `product_page_status.state`, не сверяя его `url_hash` с текущей `direct_url`. До новой проверки исправленная карточка может оставаться снятой. [page_alive.py:93](/home/pakar/igor/remlab/tools/scout/page_alive.py:93), [stock_truth.py:160](/home/pakar/igor/remlab/tools/scout/stock_truth.py:160)

  Нужен материализованный `probe_url_hash` текущей карточки или явная инвалидация `product_page_status` при изменении ссылки.

- **Важно. `failure_kind` в плане слишком плоский.** `404/410` — не транспортная ошибка, а свидетельство `page_gone`; `429`, `5xx`, timeout, DNS, TLS, challenge и redirect — разные причины невозможности проверки. Лучше хранить отдельно:
  
  - `response_kind`: `http|transport_error|redirect`;
  - `failure_kind`: `timeout|dns|tls|rate_limit|server_error|challenge|no_signal`;
  - `evidence_kind`: `schema|inline_stock|http_gone|none`.

  В `fold()` идут только вердикты; `failure_kind` нужен доменному автомату и confidence. Сейчас всё схлопывается в свободный `reason`. [page_alive.py:135](/home/pakar/igor/remlab/tools/scout/page_alive.py:135)

- **Важно. Доменное здоровье не стоит помещать в `shop_status`.** Таблица уже отвечает за состояние партнёрской программы и ключуется `shop_mid`; блокировка является свойством hostname/маршрута и версии пробника. Нужна отдельная маленькая таблица `probe_domain_status(host, probe_version, state, blocked_until, reason, checked_at)`. [003-stock-truth.sql:53](/home/pakar/igor/remlab/tools/scout/003-stock-truth.sql:53)

- **Важно. Якорь «главная + одна старая живая карточка» недостаточен.** Главная может работать при заблокированном product route, а одна карточка могла действительно исчезнуть. Минимум: главная и 2–3 недавно положительных карточки; замораживать домен по кворуму. Якорные запросы нельзя записывать как фиктивные `unknown` каждому SKU — это исказит `checked_at` и покрытие. Текущий breaker существует только в памяти одного обхода. [stock_check.py:273](/home/pakar/igor/remlab/tools/scout/stock_check.py:273)

- **Важно. `blocked >50% за 7 дней` слишком медленно и двусмысленно.** Для известного антибота `mdm` честнее сразу задать `probe_policy=disabled` и не тратить запросы. Динамический breaker должен срабатывать по нескольким проваленным доменным канарейкам/прогонам, затем работать half-open. `no_signal` нельзя считать блокировкой. [stock_check.py:312](/home/pakar/igor/remlab/tools/scout/stock_check.py:312)

- **Важно. Формула гейта должна считать решающие ответы, но иметь отдельный blast cap.** После удаления `unknown` из знаменателя случай `2 gone + 998 blocked` превращается в 100% отрицательных при выборке меньше 30 — а текущий гейт малую выборку вообще пропускает. [stock_truth.py:138](/home/pakar/igor/remlab/tools/scout/stock_truth.py:138)

  Нужны одновременно `attempted`, `decisive`, `negative`, исправный доменный якорь и абсолютный предел применяемых негативов для малой выборки. История — только `explore + accepted + current probe_version`.

- **Важно. `suspect` не переназначать.** Его лучше удалить из stock-домена; ожидание перепроверки уже выражено `dead_since` и очередью свежеснятых. Новая семантика под старым именем сломает отчёты, которые всё ещё трактуют его как «ждёт второй голос». [stock_check.py:200](/home/pakar/igor/remlab/tools/scout/stock_check.py:200), [health.py:70](/home/pakar/igor/remlab/tools/scout/health.py:70), [sync_metrics.py:69](/home/pakar/igor/remlab/tools/scout/sync_metrics.py:69)

- **Важно. `gzip` требует явной распаковки и лимита уже распакованных байтов.** `urllib` не даёт безопасного автоматического контракта здесь. Нужны `Content-Encoding`, streaming decompressor и защита от чрезмерно большого распакованного тела. [stock_check.py:110](/home/pakar/igor/remlab/tools/scout/stock_check.py:110)

- **Мелочь. Документация устарела:** она всё ещё утверждает, что снятие требует двух голосов, хотя код и ADR требуют один. [page_alive.py:12](/home/pakar/igor/remlab/tools/scout/page_alive.py:12), [stock_truth.py:12](/home/pakar/igor/remlab/tools/scout/stock_truth.py:12), [health.py:11](/home/pakar/igor/remlab/tools/scout/health.py:11)

## 3. Н2: `stock_confidence`

- **Блокер. Трёх значений недостаточно.** `gone` подтверждает отсутствие страницы, а не отсутствие товара на складе. План приравнивает `alive/oos/gone` к `verified`, что прямо противоречит правилу владельца «404 не равно нет в наличии». Текущий классификатор правильно различает `oos` и `gone`, но булевый `in_stock` снова их схлопывает. [page_alive.py:8](/home/pakar/igor/remlab/tools/scout/page_alive.py:8), [stock_truth.py:160](/home/pakar/igor/remlab/tools/scout/stock_truth.py:160)

  Минимальный честный контракт:

  - `availability_state`: `in_stock|out_of_stock|unknown`;
  - `page_state`: `alive|gone|unknown`;
  - `availability_basis`: `page|feed|none`;
  - `evidence_at` и отдельно `last_probe_at`.

  `products.in_stock` можно сохранить как совместимый признак «товар сейчас пригоден для продажи через нас», но UI не должен называть `page_gone` отсутствием на складе.

- **Блокер. Нельзя считать confidence только из свернутого `product_page_status.state`.** Последний `unknown` пропускается в `fold()`, поэтому старый `alive` остаётся состоянием, но `checked_at` обновляется временем последнего неудачного запроса. Такой товар ошибочно станет `verified` «сегодня». [stock_truth.py:111](/home/pakar/igor/remlab/tools/scout/stock_truth.py:111), [stock_check.py:394](/home/pakar/igor/remlab/tools/scout/stock_check.py:394)

- **Важно. Нужен явный `stale`.** Через три месяца без успешной проверки товар не может называться `verified`, даже если поле заполнено. Либо четвёртое значение confidence, либо вычисляемая свежесть из `evidence_at`. Истечение freshness не обязано автоматически менять `in_stock`: это отдельное продуктовое решение, затрагивающее ADR‑0147. [stock_check.py:87](/home/pakar/igor/remlab/tools/scout/stock_check.py:87), [decisions.md:2972](/home/pakar/igor/remlab/.memory_bank/decisions.md:2972)

- **Важно. `reconcile()` обновляет только строки, где изменился `in_stock`.** Если просто добавить присваивание confidence, большинство прежних строк не обновится. Условие `WHERE` и `audit()` должны проверять все производные поля. [stock_truth.py:173](/home/pakar/igor/remlab/tools/scout/stock_truth.py:173), [stock_truth.py:196](/home/pakar/igor/remlab/tools/scout/stock_truth.py:196)

- **Важно. `catalog_media.state` оставить как routing-совместимость, confidence передавать отдельными полями.** Сейчас `drop_unavailable()` зависит только от `state == gone`; менять его смысл нельзя. [catalog_media.py:70](/home/pakar/igor/remlab/tools/scout/catalog_media.py:70), [flat215_demo.py:313](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:313)

- **Важно. Схема должна накатываться обычной DB-миграцией.** Сейчас `003-stock-truth.sql` выполняется только при запуске `stock_check`; новый потребитель может стартовать раньше и упасть на отсутствующих колонках. [stock_check.py:477](/home/pakar/igor/remlab/tools/scout/stock_check.py:477)

## 4. Н3: цена и имя со страницы

- **Блокер. Использовать `page_price` в сетах и сметах сейчас нельзя.** Фид является владельцем коммерческих полей по ADR‑0171; `compose2` и `catalog_media` читают `price_rub`. Цена из страницы может быть старой, клубной, ценой другого варианта либо cross-sell offer. [decisions.md:3688](/home/pakar/igor/remlab/.memory_bank/decisions.md:3688), [compose2.py:236](/home/pakar/igor/remlab/tools/scout/compose2.py:236), [catalog_media.py:53](/home/pakar/igor/remlab/tools/scout/catalog_media.py:53)

  Первая версия: хранить `price_seen`, currency, тип цены и идентичность извлечённого Product только в append-only наблюдении. Сделать latest-view для аудита, но не менять коммерческий resolver.

- **Важно. `name_seen` и `canonical_url` — свидетельства идентичности, не замены полей товара.** Canonical может вести на серию, а `<title>` содержать маркетинговый текст. Их полезно использовать в канарейке и отчёте несоответствий.

- **Важно. «Тот же чанк» не гарантирован.** Сейчас чтение прекращается на раннем положительном availability; цена или canonical могут находиться ниже. Критерий «цена записана у 90%» либо заставит снова скачивать 4 МБ, либо стимулирует брать первую чужую цену. [stock_check.py:119](/home/pakar/igor/remlab/tools/scout/stock_check.py:119)

- **Мелочь. WARN должен быть один агрегированный на магазин, детали — в JSON.** `refresh_daily` считает все маркеры, но в статус и Telegram кладёт только первый. [refresh_daily.sh:38](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:38)

## 5. Р1: убрать выдуманные размеры

- **Блокер. План пропустил действующий некалиброванный вывод размеров в `flat215_demo`.** `_dim_from_mesh()` выводит любую недостающую ось, а затем `_dims_of()` использует меш до завершения исследования Р2. Это надо выключить до успешной калибровки. [flat215_demo.py:211](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:211), [flat215_demo.py:267](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:267)

- **Блокер. Демо затем снова берет размер из старой раскладки.** То есть даже после удаления mesh-инференса чужая глубина вернётся через `v.get('d')`. Для SKU с неизвестной осью должен быть контрактный отказ/пропуск, а не fallback. [flat215_demo.py:276](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:276)

- **Блокер. `catalog_media.sync_bank()` не очищает неизвестную сегодня ось.** Если каталог знает ширину и высоту, но не глубину, старая глубина остаётся в `sets3.json`; `_dims_unknown` ставится только когда неизвестно вообще всё. Это ровно путь утечки постороннего размера. [catalog_media.py:133](/home/pakar/igor/remlab/tools/scout/catalog_media.py:133)

- **Блокер. Контракт лечения требует лишь один любой габарит, а не footprint.** Более того, исключения при чтении каталога fail-open. Нужно требовать `(w && d) || dia` для напольного слота из актуального каталога, а не из карточки сета. [sets_incremental.py:206](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:206)

- **Важно. В composer остаются ещё два источника выдумки:** глубина дивана 100 и площадь 0,16 м² для торшера/кашпо/камина. [compose2.py:296](/home/pakar/igor/remlab/tools/scout/compose2.py:296), [compose2.py:374](/home/pakar/igor/remlab/tools/scout/compose2.py:374)

- **Важно. В `solver_run` лучше поставить один входной assert, а не удалять fallback по одному.** Сейчас типовые размеры пронизывают основной диван, копии, угловой диван и медиа-фолбэк. Список ролей можно оставить для порядка размещения, но отделить его от размеров. [solver_run.py:35](/home/pakar/igor/remlab/tools/scout/solver_run.py:35), [solver_run.py:56](/home/pakar/igor/remlab/tools/scout/solver_run.py:56), [solver_run.py:82](/home/pakar/igor/remlab/tools/scout/solver_run.py:82), [solver_run.py:600](/home/pakar/igor/remlab/tools/scout/solver_run.py:600)

- **Важно. `scene_build` выдумывает также высоту товара, декора и светильников.** Надо разделить:
  
  - реальный SKU — все нужные потребителю оси доказаны;
  - синтетический объект сцены вроде телевизора — допустима явно паспортная геометрия с `source=derived_rule`.

  Критерий «ни одного hardcoded размера» в плане слишком широк: он запретит и честные синтетические элементы. [scene_build.py:41](/home/pakar/igor/remlab/tools/scout/scene_build.py:41), [scene_build.py:130](/home/pakar/igor/remlab/tools/scout/scene_build.py:130), [scene_build.py:153](/home/pakar/igor/remlab/tools/scout/scene_build.py:153)

- **Важно. Равенство `d=w` по роли тоже является предположением.** Ваза, кашпо и основание торшера не обязаны быть круглыми/квадратными. Допустимо только `dia → w=d=dia` или явный shape-паспорт. [flat215_demo.py:142](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:142), [flat215_demo.py:262](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:262)

- **Важно. В плане неверны число сетов и команда миграции.** Сейчас `sets3.json` содержит 126 сетов, из них 77 диванов без глубины, не 77 из 116. `--refresh` меняет лишь товар на заметно лучший по стилю и максимум два на сет — контрактные дефекты он не лечит. [sets3.json:1](/home/pakar/igor/remlab/tools/scout/sets3.json:1), [sets_incremental.py:376](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:376)

  `--enforce-contracts` ближе по смыслу, но штатный предохранитель остановит изменение более 25% сетов. Значит нужна явная миграция: новый банк рядом → экзамен → сравнение покрытия → атомарная публикация. [sets_incremental.py:727](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:727), [sets_incremental.py:839](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:839)

## 6. Р2: калибровка глубины из меша

Перед v2 для Риббл и Ольен обязательно проверить:

- **Блокер. Точную ревизию и статус.** Сейчас `mesh_dims` допускает не только `accepted`, но и `generated`. Для каталожного размера этого недостаточно. [mesh_dims.py:54](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:54)

- **Блокер. Провенанс опорных осей.** Любые ненулевые `w/h` проходят в калибровку; код не проверяет, что они измерены из параметров/manual/scrape, а не разрешены слабым `prior/plaus`. Иначе mesh-инференс масштабируется другим инференсом. [mesh_dims.py:64](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:64), [dim_resolver.py:231](/home/pakar/igor/remlab/tools/scout/dim_resolver.py:231)

- **Важно. Для каждого выброса:** SKU/вариант фото, исходные params, сложенный или разложенный размер, диван-кровать/модульность, текущий `source_sha`, матрица `R`, raw extents до/после ориентации, крупнейшая компонента против общего bbox, наличие плиты/мусора.

- **Важно. Проверить обмен X/Z из-за неверного поворота на 90°.** Ошибка 186 вместо 108 похожа не только на плохой mesh-depth, но и на выбранную широкую ось.

- **Важно. `s_w/s_h` — только sanity-check, не доказательство.** Обе оси могут быть согласованно неверны. Текущий допуск 25% слишком широк для обещания ±10%. [mesh_dims.py:127](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:127)

- **Важно. Калибровка и приёмка должны быть на разных SKU.** Текущие 38 используются одновременно для построения формулы и вердикта. При таком n доверительный интервал доли около 80% слишком широк. Нужен frozen held-out, лучше ≥100 на включаемую страту, либо Wilson lower bound. [mesh_dims.py:137](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:137)

- **Важно. Ошибки должны быть асимметричны.** Недооценка глубины опаснее переоценки: она создаёт физические пересечения. Код считает `max_under`, но не включает его в verdict. [mesh_dims.py:152](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:152)

- **Важно. Провенанс должен включать** `calibration_version`, страту, источник каждой опорной оси, конфигурацию товара, `source_sha`, текущие revision/orientation hashes и confidence. При смене меша или ориентации прежнее значение обязано стать stale; `load3` сейчас сохраняет любую прежнюю `mesh_ratio`-глубину без такой проверки. [mesh_dims.py:199](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:199), [load3.py:455](/home/pakar/igor/remlab/tools/scout/load3.py:455)

## 7. Порядок и Verification

Правильный порядок пакетов:

1. Миграция observation/domain/disposition + current URL hash.
2. Починка гейта, канареек, blocked-domain и истории.
3. Н0 parser v2 только в shadow.
4. Gold/shadow-замер; затем отдельное решение о включении негативов.
5. Н2: честная модель state/basis/freshness и только потом UI.
6. Н4: перестать собирать API `available`.
7. Н3: page attributes только как наблюдения.
8. Р1 под feature flag, staged rebuild всех сетов, полный экзамен.
9. Р2 только исследование; запись после независимого held-out-гейта.

Оценка плана занижена: Н0+Н1 — скорее 2–3 дня, Р1 с безопасной пересборкой и экзаменом — ещё 2–3 дня. Н3 как сбор наблюдений укладывается в 0,5 дня; как новая ценовая истина — отдельный проект.

### Критически недостающие проверки

- Карантинное наблюдение никогда не применяется будущим `fold()`.
- Смена URL немедленно лишает старый негатив силы.
- История другой `probe_version` не участвует.
- Mixed positive/negative, snake_case, `href` в обоих порядках атрибутов.
- `overallStock=0` при положительном schema → не `oos`.
- WAF-404 больше 65 КБ, gzip, timeout, 429, 5xx, redirect.
- Провал якоря не обновляет SKU `checked_at`.
- Ни в одном напольном слоте банка нет неизвестного footprint.
- Старые оси удаляются из `sets3.json`, а solver/scene/export падают до генерации результата.
- Полный solver exam и сравнение покрытия стилей до атомарной замены банка.

## Изменить в плане до начала кода

1. Поставить Н1 перед включением Н0.
2. Добавить `accepted/quarantined` для наблюдений и фильтрацию истории по версии.
3. Инвалидировать page-status при смене `direct_url`.
4. Удалить ранний обрыв на отрицательном сигнале.
5. Заменить «30, ≥95%» на ≥300 живых без ложных снятий + отдельную отрицательную выборку и shadow.
6. Развести `availability_state`, `page_state`, basis и freshness.
7. Оставить page-price только наблюдением; не использовать в сетах/сметах.
8. Закрыть `_dim_from_mesh`, layout fallback, `SQUARE_ROLES` и частичный merge банка.
9. Ввести один общий `footprint_known()` для первичной сборки, лечения и экспорта.
10. Заменить `--refresh` на staged rebuild и сделать mesh-калибровку held-out и по стратам.

## Можно начинать как есть

- Сбор диагностических `price_seen/name_seen/canonical_url` без влияния на products и цены.
- Удаление чтения/записи `api_offers.available` с пометкой исторической колонки deprecated.
- Исследование двух худших mesh-выбросов без записи в каталог.
- Добавление структурного `failure_kind`, если сразу разделить транспорт, evidence и итоговый verdict.
- Расширение selftest fixtures для snake_case и `href`; включать новые негативы пока нельзя.
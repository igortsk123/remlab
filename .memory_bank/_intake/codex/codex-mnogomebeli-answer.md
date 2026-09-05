Вывод: обрезку Mnogomebeli надо отменить. Но план смешивает две разные ссылки: адрес карточки для проверки и партнёрскую ссылку для пользователя. Если просто оставить `direct_url` во всех местах, наличие починится, а монетизация может остаться сломанной.

1. Полная ссылка `/!вариант/`

Хранить её можно: `!` допустим в path по RFC 3986; `%21` — эквивалентное кодирование. Причины технически обрезать путь нет. [RFC 3986 §2.2](https://www.rfc-editor.org/rfc/rfc3986#section-2.2)

Но `erid` — маркировка рекламы, не доказательство партнёрской атрибуции. GdeSlon пишет, что продажи связываются через `click_id`, создаваемый при переходе по партнёрской ссылке; официальный инструмент именно превращает прямой URL в партнёрский deeplink. [GdeSlon: партнёрские ссылки](https://gdeslon.ru/faq/60/), [GdeSlon: click_id](https://gdeslon.ru/faq/114/)

Поэтому нужен контракт:

- `affiliate_url` — исходный `xf.gdeslon.ru/...goto=...`, показываем пользователю;
- `merchant_url` — декодированная полная карточка `/!вариант/`, проверяем наличие и парсим;
- `erid` остаётся в affiliate URL; для health-запроса он необязателен.

Это дополнительно подтверждается названием API-поля `destination-url-do-not-send-traffic` в [catalog_api_sync.py:92](/home/pakar/igor/remlab/tools/scout/catalog_api_sync.py:92): такой URL нельзя автоматически считать пользовательским.

До выпуска проверьте один реальный переход через исходный GdeSlon URL с `subID`: конечная карточка, появление клика в отчёте и сохранение атрибуции. Прямая карточка лишь с `erid` этого не доказывает.

2. Первый проход

`GATE_SHARE_FIRST_RUN=0.60` недостаточен. Ошибка преобразования, затрагивающая 37% ссылок, спокойно пройдёт гейт. Два одинаковых 404 через 15 минут подтверждают стабильность ответа, но не корректность нового URL.

Рекомендую:

1. 200 карточек, стратифицированно по категориям, `--dry-run`.
2. Два прохода.
3. Вручную проверить минимум 20 случайных 404 и 20 положительных: `goto` действительно указывает на этот вариант, название/цвет совпадают.
4. Затем обход всех 1092 и обычное применение.

Порог 60% оставить аварийным предохранителем, но не считать migration-гейтом. Текущая логика находится в [stock_truth.py:35](/home/pakar/igor/remlab/tools/scout/stock_truth.py:35).

Ещё одна архитектурная дыра: формула наличия доверяет `product_page_status.state`, не проверяя, что его `url_hash` совпадает с текущей ссылкой: [stock_truth.py:153](/home/pakar/igor/remlab/tools/scout/stock_truth.py:153). Поэтому обещание «смена URL обнуляет негатив» исполняется только после нового наблюдения. При массовом backfill нужно явно инвалидировать старые статусы с несовпавшим hash либо учитывать соответствие в `reconcile()`.

3. Потребители и кэши

Обязательно проверить:

- Запись при каждом фиде: [load3.py:110](/home/pakar/igor/remlab/tools/scout/load3.py:110), [load3.py:122](/home/pakar/igor/remlab/tools/scout/load3.py:122), [load3.py:178](/home/pakar/igor/remlab/tools/scout/load3.py:178). Ручной backfill без правки `reflink` на следующий день перезапишется.
- Проверка наличия: [stock_check.py:123](/home/pakar/igor/remlab/tools/scout/stock_check.py:123).
- Повторное преобразование: [catalog_media.py:53](/home/pakar/igor/remlab/tools/scout/catalog_media.py:53), [catalog_media.py:77](/home/pakar/igor/remlab/tools/scout/catalog_media.py:77).
- Сборка и индексы: [compose2.py:236](/home/pakar/igor/remlab/tools/scout/compose2.py:236), [candidates.py:60](/home/pakar/igor/remlab/tools/scout/candidates.py:60), [set_optimize.py:40](/home/pakar/igor/remlab/tools/scout/set_optimize.py:40), [sync_metrics.py:33](/home/pakar/igor/remlab/tools/scout/sync_metrics.py:33).
- Пилот мешей: [mesh_pilot.py:96](/home/pakar/igor/remlab/tools/scout/mesh_pilot.py:96).
- `sets*.json`, candidates-index и `demo-data.json` содержат копии URL — их надо пересобрать.
- Демо действительно не проверяет наличие: оно переносит URL прямо из сетов в [_sku](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:70) и товарные ленты [flat215_demo.py:151](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:151).

PostgreSQL `text` длину не ограничивает. Но аудитные `url/final_url` режутся до 900 символов в [stock_check.py:254](/home/pakar/igor/remlab/tools/scout/stock_check.py:254).

Добавьте тест эквивалентности `!` и `%21` в `url_key`: сейчас path не декодируется, поэтому формы могут получить разные hash.

4. Двойной `direct()`

Убрать. Нормализация должна выполняться один раз на ingestion.

В `catalog_media` следует брать:

- готовый `affiliate_url` для сета/клика;
- `merchant_url` вообще не отдавать как пользовательскую ссылку;
- fallback `direct(raw_url)` разрешать только при `merchant_url IS NULL`, а не повторно применять к готовому значению.

Текущий draft `reflink.direct()` также слишком широко ищет `goto=(.+)$`: он не проверяет хост GdeSlon и захватывает все последующие параметры. Лучше разбирать affiliate URL через `urlsplit/parse_qsl`, извлекать ровно `goto`, а не регулярным выражением.

5. Что проверить по остальным магазинам

Сделать автоматическую матрицу на каждый shop:

`affiliate URL → redirect target → merchant_url → final_url → Product identity`

Гейты:

- target ведёт на SKU, а не категорию/серию;
- финальный host ожидаемый;
- slug/canonical/Product name или SKU соответствует товару;
- пользовательская ссылка остаётся партнёрской;
- health проверяет именно merchant URL.

Отдельный дефект: `schema_state()` ищет availability по всему HTML и считает любой `InStock` сильнее всех отрицательных: [page_alive.py:98](/home/pakar/igor/remlab/tools/scout/page_alive.py:98). `fetch()` ещё и прекращает чтение при первом таком сигнале: [stock_check.py:81](/home/pakar/igor/remlab/tools/scout/stock_check.py:81). На странице с родственными товарами или несколькими вариантами это может признать живым не тот SKU. Для Mnogomebeli:

- 404/410 можно уверенно считать `gone`;
- `alive/oos` применять только из JSON-LD блока целевого `Product`, сопоставленного с canonical URL/SKU/вариантом;
- до такого сопоставления 200 со schema лучше считать `unknown`.

Итого: снять обрезку — правильно; массово применять после canary; разделить merchant и affiliate URL; убрать повторную нормализацию; усилить target-specific разбор schema. Без разделения ссылок план чинит наличие ценой вероятной потери партнёрской атрибуции.
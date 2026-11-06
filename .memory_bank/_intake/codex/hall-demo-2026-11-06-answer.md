Вердикт: направление правильное, но план в текущем виде — **no-go для этапа Ж**. Он способен довести прихожую до `/test/`, но не до главной: живой банк прихожей исключён из scope, тогда как публикуемая сборка не должна читать `.next`; `RoomBankSpec` сейчас допускает только living/bedroom (`room_bank_spec.py:174-185`). Это прямое противоречие `hall-demo-01.md:60,63,91`.

### 1. Порядок и пробелы

А → Б → В слишком рано обобщает «списки комнат». Наличие профиля не означает готовность этапа: среди профилей есть legacy living и процедурная kitchen (`room_profile.py:38-43`). Автоматически перечислять `room_profile.types()` (`room_profile.py:55-56`) опасно: кухня попадёт в каталог/mesh-demand, хотя её модель принципиально другая.

Нужен явный реестр capability/plugin: `catalog_loader`, `demo_builder`, `mesh_demand`, `bank`, а не «все JSON-профили». Пути геометрии, расписание и enablement нельзя класть в RoomProfile — схема прямо запрещает расписание и пути квартиры (`room-profile.schema.json:5`).

Главные пропуски:

- Вход должен быть данными `RoomInstance/opening`, например `is_entrance`, а не эвристикой «первая южная дверь» (`hall_checks.py:47-51`) и не hardcode `kind === hall ? south` (`viewer.ts:344-350`). Факт владельца следует внести во все варианты; `entrance-east` лучше удалить из рабочих вариантов, не просто подписать.
- `room_geo()` теряет `contour` (`demo_bedroom.py:73-81`), поэтому Г-образная прихожая станет прямоугольной.
- `build_variant()` теряет `elev` (`demo_bedroom.py:331-339`): зеркало, которое солвер поднимает (`hall.py:65-72`), окажется на полу.
- Этап Ж требует bootstrap `sets-hall.json` либо должен честно завершаться `/test/`. Родительский план уже требует room-specific bank chain (`room-bank-01.md:68-74`).
- Бюджет не общий фактически: `room_mesh_demand` режет каждый запуск по своему `500` (`room_mesh_demand.py:45-48,161-164`). Нужен один ledger/остаток для bedroom+hall.
- Нельзя обещать «~10 мешей» до расчёта по фактическим пяти наборам. Все роли, кроме зеркала, по канону требуют mesh (`asset-strategies.json:10-19`).

Рекомендуемый порядок: baseline+T-70 → generic core и parity bedroom → hall adapter `/test/` → зеркало end-to-end → спрос по фактическим вариантам и общий бюджет → меши → камеры/UI → live-bank bootstrap → две shadow-ночи → enable.

### 2. `demo_room.py`

Это правильный ход только как **strangler**: общий чистый engine + bedroom/hall adapters; living остаётся legacy. Не следует превращать RoomProfile в язык алгоритмов или сразу переводить living.

«Побайтно прежняя спальня» обязательна, но baseline надо снять после вливания T-70, без исключения «кроме известных отличий». Нужны два golden: выход чистого builder и полный `demo-data.json` при выключенных/включённых спальнях.

Скрытые bedroom-допущения:

- Константы геометрии, ядра, solver/place/list roles, purpose/tier/bands (`demo_bedroom.py:23-41`).
- `room_type='bedroom'`, прямой импорт solver и bedroom-validate (`:84-97,165-176`).
- Две спальни выбираются по префиксу ID, не по `apt.rooms[].kind` (`flat215_demo.py:1235`).
- Стили прихожей не берутся из профиля, а наследуются от вариантов living (`:1246`).
- Ядро — `кровать AND тумба`; прихожей нужно `ANY storage`, которое уже формализовано (`hall-composition.json:14-32`).
- Нумерованные парные тумбы и одна SKU на обе позиции (`demo_bedroom.py:228-230,314-315`).
- One-layout валидируется только bedroom-правилами (`:179-214`).
- Gate перебирает только `SOLVER_ROLES`, а mesh-free задан только ковром (`:225-264`). Для зеркала решение должно идти от `asset_strategy`, не от списка.
- Лента требует mesh для любого товара (`:376-387`), поэтому procedural mirror не попадёт в замены.
- `feeds` и `slot_band_cm` глобальны по роли; UI читает `D.feeds[role]` (`index.html:5295-5310`). При одинаковых ролях комнаты будут смешиваться — нужно namespace `(room_type, role)`.
- Остался отдельный bedroom-каталог/UI с текстом «3D позже» (`index.html:7331-7362`); его надо удалить либо обобщить.
- `cache_images` отдельно знает только `bedroom_catalog` (`flat215_demo.py:1703-1711,1788-1792`).

### 3. Nightly и living

`hall_catalog` после `room_catalog` непосредственно перед demo (`refresh_daily.sh:445-446`) появляется слишком поздно: photo/cutout уже прошёл на `:301-307`, bindings/room-bank chain для hall вообще отсутствуют. Отдельный `step` не блокирует следующую команду: при сбое каталога demo всё равно соберётся на старых данных.

Обязательны per-room freshness/run-id, сохранение последнего годного банка и запрет публикации hall при неопределённом состоянии. При этом сбой hall не должен блокировать living.

Риск living максимален от unconditional загрузки новых каталогов/полей и изменения порядка JSON. Проверять надо не только solver, но demo-data, index/bundle, feeds, cached-image manifest и nightly trace. Родитель требует parity после каждого этапа (`room-pipeline-01.md:107-111`).

### 4. Обязательные тесты

- А: все варианты hall имеют явный южный entrance; перестановка openings не меняет вход; east rejected.
- Б: capability matrix; living/kitchen не запускают hall/bedroom adapters; неизвестный тип падает.
- В: byte-golden bedroom engine и full build; обе спальни, purposes/tiers, пары тумб, alternates, feed namespace; hall fixture — пять стилей, ANY-storage, `elev`, contour, HARD=0.
- Г: сервер и браузер рисуют вертикальное зеркало с правильными wall/rot/elev; оно не clay, не mesh-job, не препятствие; occlusion/screenshot 375×667 и 1440. Нужен также `lib/configurator/fromDemo.ts`: сейчас procedural реализован только для ковра (`fromDemo.ts:332-375`).
- Д: спрос только для товаров выбранных вариантов; procedural исключён; blocked/ready/T-70 modes; общий бюджет ≤500 и probe-first.
- Е: две камеры каждого hall-варианта, покрытие ключевых ролей, разные стороны, узкий коридор, оба viewport.
- Ж: failure injection каждого nightly-шага, stale run-id, rollback, две shadow-ночи; living byte parity; main не включается без live hall bank и опубликованных ассетов.

### 5. Что изменить

Разделить план на `/test/ hall` и `main enable`; включить live-bank bootstrap в обязательные prerequisites. Заменить «списки из профилей» на capability registry. Сделать entrance частью геометрии экземпляра. Обобщить feeds/catalog/UI по комнате. Расширить scope зеркала на `fromDemo → build-scene → viewer` и server renderer. Только после этого подключать nightly и тратить mesh-бюджет.
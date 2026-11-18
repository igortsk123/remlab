## Вывод

Текущий ключ нельзя считать ни точным, ни полностью безопасным:

- он массово инвалидирует все комнаты из-за глобальных `rules stamp` и `env_sha`;
- при этом способен не измениться при реальном изменении картинки.

Причина — `scene_hash` описывает смесь состояния комнаты, происхождения сборки и глобальных файлов, но не полный набор фактических входов рендера.

Правильная модель:

```text
publish stamp ≠ scene digest ≠ frame key

publish stamp — происхождение/совместимость публикации
scene digest  — материализованная сцена конкретной комнаты + фактически выбранные ассеты
frame key     — scene digest + программа рендера + эффективный preset
```

Рекомендую двухступенчатый content-addressed pipeline: сначала разрешить сцену и все её ассеты, получить манифест конкретной комнаты, затем считать ключ кадра из этого манифеста. Для 16 опубликованных вариантов манифесты и ключи должны строиться до активации публикации.

Ниже путь `render_snapshot.py` фактически находится в `tools/scout/`, а `demo_scene_dump.mjs` — в `tools/scout/cycles_probe/`, не в каталогах из вопроса.

## Что сломано сейчас

`room_of()` возвращает всю геометрию комнаты, но в `brief` попадают только `w,d`; следом полный `snap['room']` передаётся экспортёрам. Поэтому хеш и фактический вход расходятся: [render_snapshot.py:138](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:138), [render_snapshot.py:302](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:302), [render_exec.py:944](/home/pakar/igor/remlab/tools/scout/render_exec.py:944).

Вне прямого хеша остаются как минимум:

- `height_cm`;
- `openings`, `openings_ir`;
- `finish`;
- `fixtures_ir`;
- `radiators`;
- `window_view`.

Все эти поля материализуются сборщиком комнаты: [flat215_demo.py:2212](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:2212), [flat215_demo.py:2662](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:2662). JS затем явно читает выбранную полную комнату: [demo_scene_dump.mjs:133](/home/pakar/igor/remlab/tools/scout/cycles_probe/demo_scene_dump.mjs:133), [demo_scene_dump.mjs:151](/home/pakar/igor/remlab/tools/scout/cycles_probe/demo_scene_dump.mjs:151).

Глобальная `build`-часть не закрывает эту дыру. `_rules_of_build()` оставляет только хеш `DEMO_INPUTS`; изменение карточки квартиры, отделки или другого входа вне rules может не изменить его вообще: [render_snapshot.py:161](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:161), [build_stamp.py:36](/home/pakar/igor/remlab/tools/scout/build_stamp.py:36).

Одновременно screen-only правила вроде `demo-photo-pick`, `demo-swap`, `quiz`, тарифов и цен входят в общий stamp и сбрасывают все комнаты. Текущий self-test прямо закрепляет поведение «смена rules → новый хеш» и «любой env-файл → новый хеш»: [render_snapshot.py:423](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:423), [render_snapshot.py:442](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:442).

`env_sha()` хеширует целиком четыре дерева, включая все растения, материалы и виды, поэтому изменение одного неиспользуемого файла касается 16/16 комнат: [scene_inputs.py:130](/home/pakar/igor/remlab/tools/scout/scene_inputs.py:130), [scene_inputs.py:142](/home/pakar/igor/remlab/tools/scout/scene_inputs.py:142).

Есть и stale-риски:

- для декора `_sku_inputs(..., mesh=False)` не включает GLB, хотя декор может быть мешем: [render_snapshot.py:308](/home/pakar/igor/remlab/tools/scout/render_snapshot.py:308);
- отсутствующий файл даёт пустой хеш или «последний известный», но дампер может получить другие байты по сети;
- дампер читает живой `/demo/rt-meshes.json` и имеет сетевой fallback: [demo_scene_dump.mjs:145](/home/pakar/igor/remlab/tools/scout/cycles_probe/demo_scene_dump.mjs:145), [demo_scene_dump.mjs:54](/home/pakar/igor/remlab/tools/scout/cycles_probe/demo_scene_dump.mjs:54);
- итоговый `render_version()` хеширует лишь несколько верхнеуровневых файлов, не полный транзитивный Python/TS-код и не все встроенные `data/flat3d/*.json`: [render_exec.py:132](/home/pakar/igor/remlab/tools/scout/render_exec.py:132);
- более широкий `_code_sha()` используется только для кэша подготовленной сцены, но не для уже готовых кадров: [render_exec.py:777](/home/pakar/igor/remlab/tools/scout/render_exec.py:777), [render_exec.py:792](/home/pakar/igor/remlab/tools/scout/render_exec.py:792);
- готовый кадр принимается только по наличию `meta.json` и двух JPEG, без повторной проверки входного манифеста: [render_jobs.py:167](/home/pakar/igor/remlab/tools/scout/render_jobs.py:167).

## Конкретный дизайн ключа

Ввести `RenderInputV2`, единственный render-only DTO, который потребляют и Python-export, и JS-dump. Не передавать им произвольный кусок `demo-data.json`.

Канонический манифест:

```json
{
  "schema": "room-frame/v2",
  "scene": {
    "room": {
      "w": 439,
      "d": 325,
      "height_cm": 270,
      "openings": [],
      "openings_ir": [],
      "finish": {},
      "fixtures_ir": {},
      "radiators": [],
      "window_view": "yard"
    },
    "style": "scandi",
    "items": [],
    "decor": [],
    "cameras": []
  },
  "assets": [],
  "renderer": {},
  "preset": {}
}
```

### `scene`

Включать только визуально значимые, уже материализованные данные:

- полную render-проекцию комнаты;
- предметы с устойчивым `slot_id`, ролью, позицией, размерами, `corner`, `section`, стратегией и визуальными параметрами;
- отфильтрованный реально рисуемый декор с `place`, `look`, стратегией;
- C1/C2 целиком: `x,y,rot,fov,pose,pshift`;
- стиль, поскольку он влияет на акцентную стену и растения.

Не включать:

- `build`, git SHA, publish ID;
- `source=demo|trial`, если пиксели одинаковы;
- цену, URL магазина, тексты, quiz, swap UI, photo pick;
- идентификатор варианта, если он не участвует в визуальном выборе.

Массивы нельзя без доказательства сортировать. Сейчас `brief.items` сортируется, а renderer получает исходный порядок; для повторяющихся ролей порядок может влиять на slot ID. Сортировать допустимо только после присвоения устойчивых визуальных `slot_id`.

### `assets`

После разрешения сцены — отсортированный список фактически использованных файлов:

```json
[
  {
    "kind": "mesh",
    "logical": "slot:диван",
    "sha256": "<полный sha256>"
  },
  {
    "kind": "plant",
    "logical": "plant:decor:ваза",
    "id": "branches",
    "sha256": "<sha256 glb>"
  },
  {
    "kind": "material-map",
    "logical": "room:wall:normal",
    "sha256": "<sha256 webp>"
  }
]
```

Нужны хеши:

- GLB каждого предмета и мешевого декора;
- фото-текстур ковров, картин и текстиля;
- конкретных material records и только реально выбранных карт;
- выбранного растения и его GLB;
- конкретного `window_view`;
- общего `outside.webp`/HDRI, если он реально используется;
- прочих внешних файлов, которые попали в подготовленный пакет.

Хеш должен относиться к тем же байтам, которые затем рендерятся. Нельзя сначала хешировать файл по пути, а потом снова открыть его: это TOCTOU. Байты следует положить в CAS по SHA-256 и рендерить из CAS.

Особенно важно материализовать выбор растения. Сейчас выбор зависит от всего массива подходящих растений через `hash(seed) % fits.length`: [plants.ts:128](/home/pakar/igor/remlab/lib/viewer3d/kits/plants.ts:128). Поэтому простое «хешируем только выбранный GLB» небезопасно, если выбор каждый раз пересчитывается: добавление кандидата может сменить выбранное растение. В `RenderInputV2` должен уже лежать итоговый `plant_id`; после этого хешируются только его record и GLB.

### `renderer`

Включить:

- digest детерминированного JS bundle сцены;
- digest транзитивного Python-exporter bundle;
- digest `render_cycles.py` и его runtime-зависимостей;
- точный Blender/Cycles build или immutable worker image digest;
- OCIO-конфигурацию;
- версии контрактов `RenderInput`, `scene-export`, подготовленного пакета.

Каталоги растений и материалов не должны быть зашиты внутрь глобального code bundle: иначе изменение одного record снова инвалидирует все комнаты. Это данные, разрешаемые в `assets`.

Локальный fallback и GPU не должны писать под один ключ, если у них разные Blender/OCIO/program digest. Сейчас fallback сообщает версии primary executor: [render_exec.py:1764](/home/pakar/igor/remlab/tools/scout/render_exec.py:1764).

### `preset`

Хешировать эффективный, уже нормализованный preset:

- samples, resolution/pct;
- все flags, реально меняющие изображение;
- JPEG quality/формат;
- параметры света, камеры, denoise, color transform;
- production mode дампа, если его эквивалентность не доказана.

Итог:

```text
scene_digest =
  SHA256("room-scene/v2\0" + canonical_json(scene + assets))

renderer_digest =
  SHA256(canonical_json(renderer))

preset_digest =
  SHA256(canonical_json(effective_preset))

frame_key =
  SHA256("room-frame/v2\0" +
         scene_digest + "\0" +
         renderer_digest + "\0" +
         preset_digest)
```

Я бы сохранял полный 64-символьный SHA-256. Текущие 32 hex дают достаточные 128 бит, но полный digest проще аудировать.

`render_exec.cache_key()` можно оставить как низкоуровневую функцию, но передавать ему `scene_digest`, а не нынешний `scene_hash`: [render_exec.py:192](/home/pakar/igor/remlab/tools/scout/render_exec.py:192).

## Как не пропустить вход картинки

Одной ручной проекции полей недостаточно. Нужны три уровня защиты.

1. Герметичный renderer.

- Запретить сеть при подготовке опубликованных кадров.
- Любой отсутствующий asset — ошибка сборки, не `sha=""` и не remote fallback.
- Runtime mesh table должен быть зафиксирован в публикации или полностью устранён из визуального пути.

2. Манифест фактических чтений.

- Локальный HTTP-сервер дампера уже видит все URL; расширить существующий `DUMP_URLS` до `{logical URL, path, sha256}`.
- Для Node/Python фиксировать открытия файлов audit hook/системной трассировкой.
- Разделять program reads, asset reads и временные outputs.
- Любое чтение вне declared manifest — красный тест.

3. Финальная сверка подготовленного пакета.

После `export_scene.py` и `demo_scene_dump.mjs` вычислять digest всех файлов, реально переданных Blender: `scene.json`, NPZ, текстуры, `scene-export.json`, `demo_nodes.glb`, камеры. Сохранить его в `meta.json`. Это ловит ошибку даже в resolver-манифесте.

`build_inputs.py` для этого недостаточен: он проверяет ссылки только на rules-файлы сборщика и не описывает runtime I/O рендера: [build_inputs.py:128](/home/pakar/igor/remlab/tools/ops/build_inputs.py:128). `conveyor_check` лишь вызывает этот guard: [conveyor_check.py:312](/home/pakar/igor/remlab/tools/ops/conveyor_check.py:312). Нужен отдельный `render_inputs` guard, подключённый к conveyor.

Обязательная mutation-матрица для 16 комнат:

- изменение каждого поля `RenderInputV2` меняет ровно затронутые ключи;
- изменение каждого referenced asset меняет только его потребителей;
- изменение неиспользуемого plant/material/mesh не меняет ни одного ключа;
- изменения quiz, tariffs, photo-pick, swap UI не меняют ключи;
- renderer/preset меняет все ключи — это корректно;
- изменение общего `outside.webp` меняет все комнаты, которые реально его используют;
- observed-read manifest полностью покрыт key manifest.

## Publish stamp отдельно

`data['build'] = build_stamp.stamp()` полезен для provenance и проверки «публикуется сборка по тем правилам»: [flat215_demo.py:2861](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:2861), [publish_demo.sh:227](/home/pakar/igor/remlab/tools/scout/publish_demo.sh:227). Его нужно сохранить, но полностью убрать из frame key.

Публикация должна содержать таблицу:

```text
variant/state → scene_digest → frame_key C1/C2
```

Screen-only publish переиспользует все старые frame keys. Изменение одной комнаты создаёт новый ключ только для неё.

Поскольку неверный старый кадр хуже отсутствующего, активацию picture-changing публикации следует делать атомарно только после наличия всех требуемых v2-кадров. При изменении одного растения ждать придётся только комнаты, где выбран именно этот asset. UI-only публикация сможет выходить сразу.

## Миграция

Старые cache entries нельзя автоматически объявить v2-валидными: в `meta.json` нет полного входного манифеста, поэтому доказать их соответствие невозможно.

Безопасный порядок:

1. Ввести отдельный namespace `room-frame/v2`.
2. Построить v2-манифесты всех 16 вариантов.
3. Предварительно заполнить только отсутствующие v2 keys.
4. Проверить coverage 16/16 и соответствие `meta.input_manifest_sha`.
5. Атомарно переключить публикацию/API на v2.
6. Старый cache оставить read-only для старых URL до GC, но не использовать как fallback для v2.

Hardlink старого JPEG под новый ключ допустим только после повторной верификации или побайтового сравнения с новым рендером; экономии рендера это практически не даёт.

## Альтернативы

Минимальный вариант — убрать `_rules_of_build`, положить весь `room` в `brief`, заменить `env_sha` на несколько адресных хешей и расширить `render_version`. Он быстро уберёт основную 16/16-инвалидизацию, но останется хрупкой ручной allowlist-схемой и не даст гарантии против новых чтений.

Хеш готового подготовленного пакета — самый сильный вариант, но ключ становится известен только после подготовки сцены. Для 16 опубликованных вариантов это приемлемо: подготовка делается до publish, а таблица variant→key публикуется вместе с данными. Для пользовательской перестановки подготовка выполняется при первом запросе и кэшируется.

Оставить глобальную инвалидизацию безопаснее минимальной allowlist, но она не решает окно без кадров и всё равно не устраняет уже найденные stale-дыры.

Stale-while-revalidate с показом старого кадра я не рекомендую: это прямо против заданного приоритета корректности.

## Основные риски и неопределённости

- «Меняется точно тогда, когда меняются пиксели» математически недостижимо без самого рендера. Практическая гарантия — ключ меняется при изменении любого фактического входа pipeline. Изменение program artifact считается изменением по условию задачи, даже если это безвредный рефакторинг.
- Динамические выборы растений, акцента и материалов нужно материализовать до хеша; иначе зависимостью остаётся весь каталог кандидатов.
- Следует решить, является ли C1+C2 одной cache entry. Сейчас изменение одной камеры пересчитывает пару. Более точная схема — общий `scene_digest` и отдельный `frame_key` на каждую камеру.
- QA-правила меняют допустимость, но не пиксели. Их лучше хранить отдельным `validation_digest` и перевалидировать cached frames, не добавляя в picture key.
- Неясно, должен ли живой `rt-meshes.json` влиять на изображение или только на метаданные/QA. До доказательства его надо либо фиксировать по содержимому, либо убрать из production frame path.

Что изменило бы мою рекомендацию: доказательство герметичным I/O-тестом, что нынешний `brief` уже покрывает все прочитанные визуальные данные; наличие полного старого input manifest в cache; либо измерение, что подготовка сцены до определения ключа неприемлема и publish не может хранить variant→key. Тогда я выбрал бы publish-time Merkle manifest без финального package digest. Сейчас наиболее безопасен комбинированный вариант: адресный manifest до подготовки плюс проверочный digest фактического пакета после неё.

Файлы не изменялись.
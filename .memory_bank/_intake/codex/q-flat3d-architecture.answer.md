## Вывод

План в текущем объёме — не MVP на одну ночь, а минимум три независимых проекта: новый конфигуратор, runtime-конвейер ассетов и продуктовая модель апгрейдов застройщика. Если начать A–G одновременно, к утру будет инфраструктура без убедительного пользовательского сценария.

Главный блокер даже не Three.js: данных полной квартиры нет. У квартиры №215 геометрия есть только у гостиной; остальные семь помещений — `stub` в [flat215.json](/home/pakar/igor/remlab/tools/scout/flat215.json:40). Общий контур относится к другой квартире №180 в [flat215.json](/home/pakar/igor/remlab/tools/scout/flat215.json:75). Поэтому обещание «ходить по своей квартире комната за комнатой» сейчас технически ложное.

Первым выкинуть: E целиком, кухни/санузлы из D, полную квартиру, CRM/contact и массовую KTX2-конверсию. Делать одну гостиную как вертикальный срез.

---

## 1. Где MVP провалится

### Блокер: отсутствует пространственный канон квартиры

Предложение `Apartment.rooms` как прямоугольники в глобальных координатах опирается на несуществующие данные. Более того, само ядро уже допускает Г/П-контуры через `Room.contour` в [models.py](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:48). Возврат к прямоугольникам — архитектурная регрессия.

Для целой квартиры нужны:

- контуры помещений;
- их трансформы в системе квартиры;
- общие сегменты стен;
- связи дверей между помещениями;
- высоты потолков, пилоны, шахты;
- постоянные `roomId/wallSegmentId`.

Без экспликации/BIM от застройщика это будет реконструкция по картинке, не «своя квартира».

### Блокер: нынешний 3D уже геометрически расходится с каноном

Планировщик хранит центр footprint в [models.py](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:104), а браузер прибавляет половину ширины и глубины в [index.html](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3133). Это надо исправить и закрыть unit-тестом до любой новой сцены. Иначе новый `ResolvedScene` лишь узаконит неправильную матрицу.

### Блокер: G небезопасен и невоспроизводим

`contact jsonb` плюс публичный `GET /api/flat/config/[id]` без описанной авторизации создаёт утечку PII. Также `{slotId: optionId}` недостаточно, чтобы через месяц воспроизвести цену после смены каталога.

Минимум нужен:

- случайный внутренний UUID;
- отдельный публичный share-token без контакта;
- `developer_id` с проверкой tenant;
- `schema_version`, `apartment_revision`, `catalog_revision`;
- снимок quote-lines, валюты, VAT и времени расчёта;
- consent, retention/delete policy;
- `updated_at`, идемпотентный save;
- Zod-лимиты на размер JSON.

Контакт лучше пока оставить существующему lead-flow, а конфигурацию хранить отдельно.

---

## 2. Модель данных

Связка Slot→Option одновременно переусложнена для текущего MVP и недостаточна для Sims:

- один slot не представляет четыре одинаковых стула;
- замена kitchen package может создавать несколько шкафов, технику и материалы;
- поверхность требует площади/раскладки, а не товарного slot;
- свободно поставленная мебель вообще не имеет заранее существующего slot;
- `priceGbpDelta` не выражает количество, площадь, погонные метры, VAT и пакетные скидки;
- универсальные `requires/excludes` быстро превращаются в самодельный constraint engine.

Лучше разделить два разных понятия:

```ts
type Configuration = {
  schemaVersion: number;
  apartmentRevision: string;
  catalogRevision: string;

  choices: Record<ChoicePointId, OptionId>; // пол, пакет кухни, плитка

  placements: Array<{
    instanceId: string;
    productId: string;
    roomId: string;
    xCm: number;
    yCm: number;
    elevationCm: number;
    rotationDeg: number;
    anchorId?: string;
    locked: boolean;
  }>;
};
```

Сейчас `placements` заполняются существующей расстановкой и не редактируются. В следующей фазе Sims они становятся редактируемыми без миграции формата.

`Slot` оставить только для фиксированных точек выбора:

- `surface` — пол/стена/фартук;
- `fixture` — сантехника, техника;
- `anchor` — место встроенного модуля.

Обычная мебель должна быть entity/placement, не slot.

`resolveConfiguration()` должен выдавать:

- стабильные instance IDs;
- мировые трансформы;
- surface assignments;
- asset IDs и LOD;
- visibility/room membership;
- quote lines;
- warnings и provenance.

Не хранить в нём Three.js-классы.

---

## 3. Runtime-ассеты

### Что неверно

Цель «каждый GLB ≤500 КБ» произвольна и для узнаваемой мягкой мебели, вероятно, разрушительна. Нужен бюджет сцены и визуальные гейты, а не один предел на файл.

40k треугольников × 15 объектов — около 600k треугольников: это не главный враг. Главный враг — две текстуры 2048². После декодирования это примерно 32 МБ на товар без mipmaps; 15 товаров способны занять сотни мегабайт GPU-памяти.

Приоритет оптимизации:

1. immutable URL и кэш;
2. albedo 1024 desktop / 512 mobile;
3. MR 256–512 либо роль-зависимые scalar roughness/metalness для Lite;
4. KTX2 для GPU-памяти;
5. LOD геометрии;
6. только затем агрессивный decimate.

Репозиторий уже имеет упрощатель с сохранением UV и защитой открытых границ в [mesh_render.py](/home/pakar/igor/remlab/tools/scout/mesh_render.py:45). Игнорировать накопленные там ловушки и писать новый decimator с нуля опасно.

### Source GLB как есть

Подходит только для первого desktop-спайка на 3–5 предметах. Для телефона — нет.

В конфиге Caddy уже глобально включены `zstd gzip` в [Caddyfile](/home/pakar/igor/remlab/caddy/Caddyfile:8), поэтому утверждение «без gzip» неверно на уровне репо; надо проверить фактический `Content-Encoding`. Но JPEG/PNG внутри GLB всё равно почти не сожмутся повторно, а GPU-память gzip вообще не уменьшает.

### Meshopt + KTX2

Правильное направление, но не собственная GLB-хирургия на Python. Наличие декодеров в `node_modules` не даёт энкодера. Для KTX2 нужен внешний KTX encoder; glTF-Transform сам вызывает KTX tooling. Лучше закрепить версию glTF-Transform/KTX в контейнере и сделать воспроизводимый job. Официальный pipeline поддерживает Meshopt, resize и KTX2/WebP, но KTX2 требует отдельного encoding toolchain ([glTF-Transform CLI](https://github.com/donmccurdy/glTF-Transform/blob/main/packages/cli/src/cli.ts)).

Для первого спайка:

- 10 репрезентативных моделей;
- WebP/JPEG resize + Meshopt;
- KTX2 — отдельный A/B после установки encoder;
- source GLB никогда не перезаписывать;
- runtime manifest: source SHA, pipeline version, LOD, byte size, triangles, texture dimensions;
- гейт по силуэту и нескольким фиксированным рендерам.

`GLTFLoader` требует явно зарегистрировать и KTX2 loader, и Meshopt decoder; сами файлы в `node_modules` автоматически не подключаются ([Three.js GLTFLoader](https://threejs.org/docs/pages/GLTFLoader.html)).

### Instanced-прокси

Хороши для `3D Lite`, но не как основной desktop-режим: пользователь должен узнавать реальный товар. На мобильном допустима лестница:

- видимые крупные товары — LOD1;
- дальние — proxy;
- не вошедшие в бюджет — box/billboard;
- Photo остаётся default.

---

## 4. Kit-of-parts

«Байты ~0» — неверно. Параметрические корпуса действительно дёшевы, но убедительная кухня требует фасадов, ручек, цоколя, столешницы, мойки, крана и узнаваемых лицевых панелей техники. Санузел из BoxGeometry будет выглядеть как технический прототип и способен убить продажную демонстрацию.

Лучше гибрид:

- параметрическая раскладка шкафов и плитки;
- 10–20 переиспользуемых GLB-модулей;
- `InstancedMesh` для повторяющихся фасадов/ручек;
- реальные low-poly GLB для духовки, мойки, крана, ванны, WC;
- фиксированные наборы застройщика, а не универсальный конструктор кухни.

Дешёвое усиление вида:

- скруглённые фаски;
- корректный физический масштаб текстур;
- небольшой environment map/PMREM;
- ACES tone mapping;
- один curated материал на тип поверхности;
- реальные зазоры и цоколи.

Hemisphere + directional без environment lighting сделают PBR плоским. При этом E следует выкинуть: normal/roughness/AO, выведенные из яркости фотографии, повторно запекут свет и тени. Для MVP взять небольшой вручную проверенный набор PBR-материалов. AO должен происходить из геометрии, а не из albedo.

---

## 5. Как не рассинхронизировать Photo / 3D / Top-down

Одна модель данных не гарантирует совпадение: сервер и браузер всё равно применяют разные реализации трансформа, камеры и ассета.

Нужны четыре уровня проверки.

1. **Contract test**

   Один JSON `ResolvedScene` проходит Zod в TS и Pydantic/JSON Schema в Python.

2. **Transform conformance**

   Для канонического куба сравнить восемь мировых вершин после:

   - canonical yaw;
   - anisotropic scale;
   - placement rotation;
   - elevation;
   - translation.

   TS должен совпадать с `scene_mesh.world_vertices()` в [scene_mesh.py](/home/pakar/igor/remlab/tools/scout/scene_mesh.py:61) с допуском, например, `1e-4 м`.

3. **Projection conformance**

   Проецировать bbox каждого предмета одной и той же камерой и сравнивать экранные прямоугольники/маски. Это устойчивее pixel screenshot на разных GPU.

4. **Snapshot adapters**

   Для одного fixture проверять:

   - top-down polygon;
   - список Three entities и матрицы;
   - точный payload `/api/render`;
   - quote lines и общий `configurationHash`.

Особенно важно: photo-adapter должен получать уже разрешённый `ResolvedScene`, а не повторно выполнять `requires/excludes`.

Ассеты source/runtime должны иметь общий `assetId`, одинаковые orientation/extents version. Иначе геометрия совпадёт по JSON, но не по факту.

---

## 6. Что нарушает «без большого rewrite»

Фактически rewrite создают:

- перенос статического `/demo` в новый Next UI;
- новый каталог опций;
- новый runtime asset pipeline;
- параметрические кухни/санузлы;
- material-authoring CLI;
- CRM persistence;
- новый full-apartment формат.

Существующее демо не является частью Next: оно копируется как статический HTML и обслуживается отдельно. Новый Next viewer рядом с ним означает второй frontend, а не небольшое расширение.

### Реалистичная замена на одну ночь

1. Только существующая гостиная №215.
2. Исправить центр координат.
3. Вынести чистую TS-функцию `placementToMatrix()`.
4. Desktop: существующие 3D-меши, максимум 5–8, immutable-кэш.
5. Mobile: Photo default; Lite = low-poly/proxy без кухни и санузла.
6. Три выбора: вариант мебели, пол, цвет стен.
7. Один `ResolvedScene` → Three / SVG / существующий `/api/render`.
8. Сохранение пока без `contact`: versioned configuration JSON или минимальная DB-запись.
9. Photo pipeline не трогать.

Это даёт доказательство ценности. После него отдельно решать runtime pipeline и получать геометрию квартиры от застройщика.

---

## 7. Three.js + Next.js: конкретные грабли

### `next/dynamic`

`ssr:false` работает только внутри Client Component. Нужен маленький `'use client'` wrapper; попытка поставить его прямо в Server Component завершится ошибкой. Это прямо оговорено в [Next.js lazy loading guide](https://nextjs.org/docs/app/guides/lazy-loading).

### Две версии Three

Статическое демо тащит локальную Three r160 через import map в [index.html](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3079), а Next-проект содержит `three 0.186.1` в [package.json](/home/pakar/igor/remlab/package.json:36). Нельзя смешивать loader/controls одной версии с core другой. Новый viewer должен использовать только npm-версию и соответствующие addons.

### Strict Mode

`reactStrictMode: true` уже включён в [next.config.mjs](/home/pakar/igor/remlab/next.config.mjs:4). В development Effect выполняется повторно — это штатное средство поиска отсутствующего cleanup ([React StrictMode](https://react.dev/reference/react/StrictMode)).

Effect обязан:

- быть идемпотентным;
- иметь generation token/disposed flag;
- игнорировать завершившиеся после cleanup GLTF loads;
- не создавать второй canvas;
- не оставлять `ResizeObserver`, listeners и RAF.

### Dispose

Текущий код вызывает лишь `renderer.dispose()` в [index.html](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3091). Этого недостаточно.

Нужно:

- `renderer.setAnimationLoop(null)`;
- `controls.dispose()`;
- пройти сцену и dispose geometry;
- dispose всех material и texture maps;
- dispose render targets/KTX2 loader;
- закрывать `ImageBitmap`, если используются;
- снять observers/listeners;
- при окончательном уничтожении — освободить context.

Three.js не освобождает geometry/material/texture автоматически при удалении объекта ([официальное руководство](https://threejs.org/manual/pages/how-to-dispose-of-objects.html)).

### CSS `zoom`

Глобальный `body { zoom: ... }` находится в [globals.css](/home/pakar/igor/remlab/app/globals.css:15). Для конфигуратора его надо отключить на уровне route:

```css
html[data-canvas-route] body { zoom: 1; }
```

И считать pointer NDC только через фактический rect canvas:

```ts
const r = canvas.getBoundingClientRect();
x = ((clientX - r.left) / r.width) * 2 - 1;
y = -((clientY - r.top) / r.height) * 2 + 1;
```

Размер renderer обновлять через `ResizeObserver`, не только `window.resize`.

### Асинхронная загрузка

GLTF может доехать после смены комнаты или unmount. Нужен request generation ID; иначе старая модель попадёт в новую сцену. Для настоящего abort лучше `fetch(..., {signal}) → arrayBuffer → parseAsync()`, а не необрываемый `loader.load()`.

### Переключение Photo/3D

На desktop выгоднее ставить animation loop на паузу и скрывать canvas, а не каждый раз уничтожать сцену и повторно скачивать текстуры. На mobile, наоборот, при уходе в Photo следует освобождать 3D-память.

### Bundle и decoder paths

- Three должен быть только в динамическом client chunk.
- KTX2 transcoder надо явно публиковать и задавать `setTranscoderPath()`.
- `detectSupport(renderer)` вызывается после создания renderer.
- Meshopt decoder явно передаётся loader.
- Нужен fallback при WebGL context lost/unsupported → Photo.
- Прогресс должен учитывать байты, а не только число моделей.

---

## Приоритет решения

**Сейчас:** одна комната, правильные матрицы, единый resolver, исправленный lifecycle Three, 5–8 ассетов, Photo fallback.

**Следом:** измеренный runtime-pipeline на 10 моделях; не массовая конверсия 590 файлов.

**После получения данных застройщика:** Apartment shell, room navigation, реальные upgrade packages.

**Последним:** авторинг материалов, кухни/санузлы, свободное перемещение и CRM-интеграция.

Мой вывод изменился бы, если уже существует скрытая точная модель квартиры №215 с глобальными координатами помещений и спецификация реальных UK upgrade packages. Без этих двух источников план строит красивый движок вокруг вымышленных данных.
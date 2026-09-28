# Критика архитектуры: 3D-конфигуратор квартиры поверх photo-first конвейера

Роль: независимый рецензент. Нужна жёсткая критика, а не одобрение. Отвечай по-русски, тезисно,
с указанием конкретных рисков и альтернатив. Если считаешь решение ошибочным — скажи прямо и
предложи замену с обоснованием.

## Задача владельца (ТЗ, кратко)
Покупатель квартиры в новостройке UK до сдачи дома ходит по своей квартире в 3D, комната за
комнатой меняет мебель и реальные апгрейды застройщика (полы, кухня + встроенная техника,
санузел/плитка), видит сумму и сохраняет конфигурацию для менеджера продаж/CRM.
Сейчас в проекте есть только photo-first: сцена собирается сверху (top-down), расставляются меши,
серверный z-buffer рендер даёт кадр за 5–7 с, потом GPT «улучшает». Этот конвейер сохраняем.
Desktop по умолчанию 3D (+переключение Photo/Top-down), mobile по умолчанию Photo + облегчённый
«3D Lite». Требование: НЕ делать большой rewrite; архитектуру заложить так, чтобы следующим шагом
можно было прийти к Sims-подобному редактору (добавление/удаление/перемещение мебели в зонах).

## Факты аудита нашего кода (проверены)
1. Канон координат (`services/planner-solver/planner/models.py:1-8`): сантиметры, x вправо,
   y вглубь, **x/y = ЦЕНТР footprint**, rot по часовой, 0 → +y. В 3D-блоке демо
   (`tools/scout/flat215-demo/index.html:3133`) x/y трактуются как угол — баг, сдвиг +w/2,+d/2.
2. Верная трансформация меша (`index.html:3154-3165`, совпадает с сервером
   `tools/scout/scene_mesh.py:61-83`): yaw из orient.json на объекте → неравномерный scale по трём
   осям на обёртке (Group) → rot расстановки → посадка по Box3 (центр XZ, min.y на пол).
3. Меши: `/test/mesh-pilot10/<msid>/model.glb`, 590 шт. на проде. Медиана 3.9 МБ, 40 000 треуг.,
   ДВЕ текстуры 2048² (baseColor JPEG + metallicRoughness PNG) лежат base64 ВНУТРИ JSON-чанка,
   `extensionsUsed: []` (никакого Draco/Meshopt/KTX2), нормалей нет, индексы uint32.
   MR-карты = 41 % веса галереи. Caddy отдаёт `/test/*` с `no-store` и без gzip.
4. Photo-конвейер: `POST /api/render {room, items[], cams[], style, quality}` →
   синхронно `{shots:[...]}` либо `{job}` + опрос `GET /api/job?id=` раз в 3 с. Питон-сервис вне
   compose (`tools/scout/draft_service.py`), задания в памяти процесса.
5. Next.js 15 App Router, TS strict + noUncheckedIndexedAccess, React 19, Tailwind v4,
   Zod v4 контракты, Drizzle только schema+query, миграции — raw SQL `db/init/NNN-*.sql`
   (применяются на каждом деплое, обязана быть идемпотентность), Vitest (только `tests/unit/*.test.ts`,
   чистые модули) + Playwright (`pnpm start`, селекторы по роли и русскому тексту).
   `next/dynamic` в проекте не использовался ни разу. На body висит CSS `zoom` — ломает арифметику
   clientX→canvas. В dev `reactStrictMode` монтирует useEffect дважды.
6. На машине НЕТ ни gltfpack, ни gltf-transform, ни toktx, ни basisu. Есть node 22, pnpm, сеть до
   npm, и python-venv с trimesh/pygltflib/PIL/numpy/cv2. В node_modules/three/examples/jsm уже лежат
   KTX2Loader, meshopt_decoder, meshopt_simplifier, basis transcoder.
7. Диск прода 38 ГБ (занято /test = 4.6 ГБ), диск DEV — 25 ГБ свободно.

## Предлагаемая архитектура (критикуй по пунктам)
A. **Стек.** Three.js оставляем. Vite НЕ вводим (в проекте одна сборка Next.js standalone + CI);
   react-three-fiber не берём (хотим императивный тестируемый слой, общий для режимов);
   Babylon.js не берём. Viewer подключаем через `next/dynamic({ssr:false})`.
B. **Единая модель.** `Apartment` (rooms как прямоугольники в общих координатах квартиры, см;
   openings: door/window по стенам) → `Slot`-ы (surface | builtin | furniture) → `Catalogue`
   опций (id, category, roomKinds, tier base/standard/premium, package, priceGbp-дельта,
   developerId, asset: mesh|material|kit, requires/excludes) → `Configuration` = только
   {slotId: optionId}. Чистая функция `resolveConfiguration()` даёт `ResolvedScene`, из которой
   три адаптера: 3D-сцена, top-down SVG, запрос в существующий /api/render.
C. **Ассеты в три класса:** source GLB (тяжёлый конвейер мешей) ≠ runtime GLB (Meshopt + KTX2,
   цель ≤ 500 КБ, отдаём с НОВОГО immutable-маршрута `/rt/*`, т.к. `/test/*` = no-store) ≠
   фото-ассет (серверный рендер). Конвейер: скачиваем source → decimate + meshopt + текстуры
   1024/512 → манифест с весами.
D. **Встроенное — параметрический kit-of-parts в TypeScript** (кухня: база/верх/столешница/
   фартук/техника; санузел: ванна/унитаз/раковина/плитка; кровать, шкаф): мешей на это нет,
   варианты = материалы + уровень техники, байты ~0, переключение мгновенное, и это же будущая
   основа Sims-редактора.
E. **Материалы из фото:** фото образца → perspective correction (4 точки) → cleanup →
   tileable (offset+mirror blend) → colour normalization → normal/roughness/AO из яркости →
   KTX2/WebP + preview + material.json с физическим размером (см на тайл). MVP semi-manual CLI;
   где фото нет — процедурная генерация тем же CLI.
F. **Свет.** MVP без лайтмапов: hemisphere + один directional, контактные тени спрайтом; на
   mobile тени и постобработка выключены, pixelRatio ≤ 1.5, первая комната грузится сразу,
   остальные лениво по близости.
G. **Сохранение.** `db/init/011-configurator.sql`: таблица конфигураций (id text, apartment_id,
   developer_id, selections jsonb, contact jsonb, created_at timestamptz) + API
   `POST /api/flat/config` (сохранить) и `GET /api/flat/config/[id]`.

## Вопросы, на которые нужен ответ
1. Где в этой схеме главный риск провала MVP за одну ночь работы? Что выкинуть первым?
2. Модель данных: не переусложнена ли связка Slot↔Option↔Category? Где она сломается при переходе
   к Sims-редактору (свободное размещение) и что заложить сейчас, чтобы не переделывать?
3. Runtime-ассеты: наш путь (decimate+meshopt+KTX2 своим конвейером на python/node) против
   альтернатив (отдавать source GLB как есть с gzip и кэшем; или instanced-прокси). Что дешевле
   и надёжнее при 40k треуг./3.9 МБ на модель и 5–15 моделях в кадре на телефоне?
4. Параметрические kit-of-parts против покупки/генерации мешей кухни и сантехники: не даст ли это
   «картонный» вид, который убьёт демо для застройщика? Чем усилить дёшево?
5. Три режима из одной модели: где типичные места рассинхрона (фото vs 3D) и как их поймать
   тестом, а не глазами?
6. Что в нашем плане нарушает «не делать большой rewrite» и «не превращать photo-конвейер в
   realtime engine»?
7. Конкретные грабли Three.js + Next.js 15 (strict mode double mount, dispose, CSS zoom на body,
   SSR, bundle) — что нас укусит и как правильно.

Отвечай по существу, максимум конкретики. Если есть предложение лучше — сформулируй его как
замену с оценкой цены и риска.

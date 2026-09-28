---
workstream: 3d-configurator
slug: apartment-3d-configurator
title: Интерактивный 3D-конфигуратор квартиры (Three.js) поверх photo-first конвейера
status: in_progress
created: 2026-09-28
updated: 2026-09-28
completed:
plan_kind: sub
parent_plan: MASTER-cost-first
---

## Цель
Подпроект: покупатель новостройки ходит по квартире в 3D, комната за комнатой меняет мебель и
реальные апгрейды застройщика (полы, кухня + встроенная техника, санузел), видит сумму и
сохраняет конфигурацию для менеджера продаж. Photo-конвейер не переделываем — он остаётся
третьим режимом показа.

## Источник задачи
ТЗ владельца 28.09 (ночной автономный прогон): «3D-конфигуратор квартиры поверх текущего
photo-first pipeline… сначала audit, затем architecture + data model + asset pipeline + MVP scope,
только потом vertical slice; большой rewrite не делать». Проверять будет на
https://remont-lab.online/demo/ — вход в 3D должен быть оттуда.

## Аудит (сделан 28.09; подробности — `core/apartment-configurator.md`)
1. **Сцена сейчас** — не хранится: страница `/demo/` качает `demo-data.json` (сборка
   `tools/scout/flat215_demo.py`), расстановку клонирует в глобальный `items` и никуда не
   сохраняет (F5 = откат). Персист — только `#v=<vid>` и камеры в localStorage.
2. **Конвенции координат — канон** (`services/planner-solver/planner/models.py:1-8`): сантиметры,
   `x` вправо, `y` вглубь, **`x/y` = ЦЕНТР footprint**, `rot` по часовой, `0 → +y`.
   В 3D-блоке демо (`flat215-demo/index.html:3133`) `x/y` трактуются как угол — **баг**, сдвиг
   на `+w/2,+d/2`; не копировать.
3. **Трансформация меша** (`index.html:3154-3165`) — выстрадана и верна: yaw из `orient.json` на
   объекте → неравномерный scale по трём осям на обёртке → `rot` расстановки → посадка по `Box3`.
   Совпадает с сервером (`tools/scout/scene_mesh.py:61-83`). Переносим дословно.
4. **Меши** — `/test/mesh-pilot10/<msid>/model.glb` + `mesh-index.json` (590 на проде) +
   `orient.json` (196). Ключ модели — `msid` (представитель семейства, ADR-0196), не артикул.
   Вес: медиана 3.9 МБ, 40 000 тр., текстуры 2048² base64 **внутри JSON-чанка**, сжатия нет
   (`extensionsUsed: []`), MR-карты PNG = 41 % веса. `/test/*` отдаётся `no-store` и без gzip.
5. **Photo-конвейер** — `POST /api/render` (`tools/scout/draft_service.py`): `{room, items[],
   cams[], style, quality}` → синхронно кадр или `{job}` + опрос `GET /api/job?id=` раз в 3 с.
   Не трогаем: конфигуратор просто говорит на этом контракте.
6. **Переиспользуем:** конвенции координат, трансформацию меша, `msid||sid`, меши прода, контракт
   `/api/render`. **Не переносим:** 20+ глобальных `let`, `draw()`-god-function, ручную SVG-графику
   мебели, мёртвый `applyKit()`, советчик за `HINTS_ON=false`.

## Решения (→ ADR)
- **ADR-0209 Стек рантайма 3D:** Three.js остаётся; **Vite НЕ вводим** — сборка Next.js 15 одна на
  проект (`output: standalone`, докер, CI); r3f не берём (сцена нужна императивным тестируемым
  слоем). WebGL2 — дефолт three. Babylon.js — нет.
- **ADR-0210 Единая модель:** apartment → rooms → surfaces/slots → configurable items; каталог
  опций отдельно; `Configuration` = только выбор (slotId → optionId). Три режима (3D, top-down,
  photo) — адаптеры над одним `resolveConfiguration()`.
- **ADR-0211 Два класса ассетов:** source GLB (тяжёлый, конвейер мешей) ≠ runtime GLB
  (Meshopt + KTX2/уменьшенные текстуры, цель ≤ 500 КБ) ≠ фото-ассет (серверный рендер).
  Runtime-ассеты отдаются с НОВОГО immutable-маршрута `/rt/*` (по образцу `/test/mesh-audit/*`),
  потому что `/test/*` = `no-store`.
- **ADR-0212 Встроенное — параметрический kit-of-parts в TS** (кухня, техника, санузел, кровать,
  шкаф): мешей на это нет и не будет скоро, а варианты = материалы/уровень техники. Байты ~0,
  переключение мгновенное, тот же код позже даёт Sims-редактор.
- **ADR-0213 Материалы из фото:** pipeline фото → перспектива → cleanup → tileable → цвет →
  normal/roughness/AO → runtime-текстуры + preview + `material.json` с физическим размером
  плитки. MVP — semi-manual CLI; где фото нет, тот же CLI генерирует процедурный образец.

## Скоуп — что входит (MVP)
- Одна демо-квартира UK new-build: hall, living, kitchen, bathroom, bedroom.
- Режимы 3D / Photo / Top-down; desktop → 3D, mobile → Photo + «3D Lite».
- Прогулка: desktop WASD + мышь, mobile tap/point-and-go.
- Комната → категория → вариант, только релевантные категории, мгновенная замена.
- Base + 3 варианта: flooring, kitchen (Base/Practical/Comfort/Premium) + встроенная техника,
  bathroom tiles/finishes; мебель — несколько вариантов на слот из реальных мешей.
- Сумма апгрейдов (£), сохранение конфигурации (БД) и ссылка для менеджера.
- Photo-режим: запрос в существующий конвейер по гостиной.
- Asset pipeline: runtime-GLB (Meshopt/KTX2) + материалы из фото; манифест с весами.

## Скоуп — что НЕ входит
- Sims-редактор (свободное размещение, добавление/удаление, физика), большой каталог.
- Переделка photo-конвейера в реалтайм; лайтмап-бейкинг; мультиэтажность; VR.
- Wardrobes/lighting/home office (заложено в модель, но не наполняем).

## Файлы к изменению
- [ ] `contracts/apartment.ts`, `contracts/configurator.ts` — Zod-модель и каталог
- [ ] `lib/configurator/{rules,resolve,pricing,storage,client,types}.ts` — чистое ядро
- [ ] `lib/viewer3d/*` — рантайм Three.js (renderer, assets, rooms, kits, controls, quality)
- [ ] `components/configurator/*` — React-обёртка, панели, top-down, photo
- [ ] `app/flat/page.tsx`, `app/api/flat/**` — страница и API
- [ ] `db/schema.ts`, `db/init/011-configurator.sql`, `.github/workflows/ci.yml` — сохранение
- [ ] `data/flat3d/*` — квартира, каталог, материалы
- [ ] `tools/assets/*` — конвейер runtime-ассетов и материалов из фото
- [ ] `tests/unit/configurator-*.test.ts`, `e2e/flat3d.spec.ts`
- [ ] прод: Caddy-маршрут `/rt/*`, кнопка входа на `/demo/`

## Задачи
- [x] Аудит (сцена, top-down, меши, photo-конвейер, конвенции Next.js)
- [ ] Контракты + чистое ядро + тесты
- [ ] Данные демо-квартиры и каталога (Base + 3)
- [ ] Runtime-ассеты: конвейер + первая партия + публикация на `/rt/`
- [ ] Материалы: CLI + первый набор (полы/плитка/столешницы/ковёр)
- [ ] Three.js viewer + режимы + управление (desktop/mobile)
- [ ] UI room-by-room + цена + сохранение
- [ ] Photo-режим через существующий `/api/render`
- [ ] Тесты, линт, сборка, e2e; verify-субагент
- [ ] Деплой (push → CI), кнопка на `/demo/`, прод-проверка
- [ ] `/memory-check`, ADR, `core/apartment-configurator.md`

## Критерии приёмки
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` зелёные
- [ ] e2e: страница открывается, сцена рисует кадр, смена варианта меняет сцену
- [ ] На проде: страница 200, кнопка на `/demo/`, GLB отдаются с immutable-кэшем
- [ ] Mobile Lite: первая комната грузится ≤ ~2 МБ, остальные — лениво
- [ ] Не задеты файлы чужих фич (photo-конвейер, приёмка мешей, смета)

## Definition of Done — память (без этого `completed` запрещён)
- [ ] `core/apartment-configurator.md` заведён и виден в decision tree INDEX
- [ ] ADR-0209…0213 — тексты в `decisions/adr-0201-0250.md` + строки в индекс
- [ ] `project-state.md` — снимок обновлён
- [ ] «Уроки» заполнены; `/memory-check` чисто

## Лог выполнения
- 2026-09-28 — аудит тремя субагентами, план создан, стек проверен (Vite отклонён)

## Completion summary
[заполняется при переводе в completed]

### Уроки (ОБЯЗАТЕЛЬНО)
[заполняется]

## Follow-up work
- [ ] Sims-редактор: добавление/удаление/перемещение в допустимых зонах
- [ ] Лайтмапы вместо динамического света; wardrobes/lighting/home office
- [ ] Загрузка каталога конкретного застройщика (developer-specific)

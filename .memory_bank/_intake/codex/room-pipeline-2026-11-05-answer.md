## 1. Вывод

Лучший путь — сейчас сохранить `room_catalog` изолированным, но изолировать от него и `products` все следующие стадии через единый типизированный адаптер каталога.

Не следует:

- немедленно переносить новые комнаты в `products`;
- добавлять `--room` и условные ветки в каждый существующий скрипт;
- превращать `compose2.py` или living solver в универсальный монолит;
- требовать, чтобы кухня обязательно проходила через фото → cutout → mesh: процедурный kit является допустимым asset provider.

Целевая модель:

```text
источники → CatalogItem
RoomProfile + фактический RoomInstance → RoomDemand
CatalogItem + RoomDemand → кандидаты/ассеты/комплекты
solver plugin → layout
camera profile → views
provider-specific scene assembly → render
```

Living room первое время должен оставаться полностью на legacy-path. Новый generic path работает для остальных комнат и в shadow-режиме воспроизводит living. Переключать living можно только после доказанного паритета.

Долгосрочно нужна не миграция «в `products`», а нормализация:

```text
catalog_offer                 — физическое предложение один раз
offer_room_role               — много комнат/ролей для одного offer
offer_dimensions/style/assets — общие факты и ассеты
```

`products` и `room_catalog` затем могут стать compatibility views.

---

## 2. Доказательства в коде

### Каталог и стили

- ADR-0330 правильно вводит защитный периметр, но это переходное решение: [adr-0301-0350.md:415](/home/pakar/igor/remlab/.memory_bank/decisions/adr-0301-0350.md:415).
- Более ранний ADR прямо планировал перенос после появления mesh и комплектов спальни — этот момент уже наступил, но перенос именно в старую таблицу не решает многоролевую модель: [adr-0251-0300.md:555](/home/pakar/igor/remlab/.memory_bank/decisions/adr-0251-0300.md:555).
- В `products` первичный ключ физического предложения не содержит комнаты, а роль фактически одиночная. В `room_catalog` комната входит в PK: [013-room-catalog.sql:5](/home/pakar/igor/remlab/tools/scout/013-room-catalog.sql:5). Простое объединение схем даст либо дубликаты ассетов, либо невозможность назначить одному предмету несколько ролей.
- `room_catalog.py` пока является bedroom-loader, а не generic catalog: фиксированы `ROOM`, набор ролей и bedroom rules: [room_catalog.py:32](/home/pakar/igor/remlab/tools/scout/room_catalog.py:32).
- `style_score.py` знает только `living` и специальный bedroom-source, а bedroom SQL фиксирует четыре роли: [style_score.py:29](/home/pakar/igor/remlab/tools/scout/style_score.py:29), [style_score.py:52](/home/pakar/igor/remlab/tools/scout/style_score.py:52).
- `styles.json` содержит living-ориентированные веса ролей: [styles.json:3](/home/pakar/igor/remlab/tools/scout/styles.json:3). Стили могут быть глобальными, но веса по ролям должны принадлежать профилю комнаты.

### Какие стадии действительно living-specific

| Стадия | Что обнаружено | Минимальное изменение |
|---|---|---|
| Photo/cutout | `cutout_sync.todo()` и `photo_hash` выбирают только `products`: [cutout_sync.py:221](/home/pakar/igor/remlab/tools/scout/cutout_sync.py:221), [photo_hash.py:73](/home/pakar/igor/remlab/tools/scout/photo_hash.py:73) | Подменить только выбор target items на адаптер. Маскирование и оценку фото оставить общими |
| Dimensions | `drawing_dims.eligible()` — sofa и фиксированные магазины: [drawing_dims.py:294](/home/pakar/igor/remlab/tools/scout/drawing_dims.py:294) | Оставить как provider `sofa_drawing`; добавить цепочку providers и policy из профиля |
| Composition | `compose2.py` фиксирует living roles, размерные bands, sofa/TV/dining/rug и `sets3.json`: [compose2.py:24](/home/pakar/igor/remlab/tools/scout/compose2.py:24), [compose2.py:243](/home/pakar/igor/remlab/tools/scout/compose2.py:243) | Не параметризовать сейчас. Зарегистрировать как `living_legacy` composer; новые composers должны иметь общий интерфейс |
| Judge | Визуальная оценка в основном общая, но inputs, роли и alternative lookup living-specific: [judge.py:14](/home/pakar/igor/remlab/tools/scout/judge.py:14), [judge.py:49](/home/pakar/igor/remlab/tools/scout/judge.py:49) | Параметризовать input/output, role contract и поиск альтернатив |
| Mesh demand | `mesh_queue.py` и `mesh_priority.py` строят спрос из living banks и `products`: [mesh_priority.py:60](/home/pakar/igor/remlab/tools/scout/mesh_priority.py:60) | Общий Salad worker оставить; заменить расчёт demand/rank на профильный |
| Mesh binding | `room_mesh_jobs.py` генерирует jobs, но `mesh_bind`, `mesh_family`, `mesh_ready` обновляют/читают `products`: [room_mesh_jobs.py:2](/home/pakar/igor/remlab/tools/scout/room_mesh_jobs.py:2), [mesh_bind.py:167](/home/pakar/igor/remlab/tools/scout/mesh_bind.py:167) | Критический разрыв: binding/readiness должны адресовать canonical offer, иначе room meshes остаются «сиротами» |
| Solver | `solver_run.py` глубоко living-specific. Отдельный bedroom solver — правильная форма плагина | Общий façade/registry, но отдельные алгоритмы по типу комнаты |
| Validation | Любая неизвестная комната, включая kitchen/hall, сейчас фактически попадает в living validator: [validate.py:2006](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:2006). `RoomType` не содержит hall: [models.py:17](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:17) | Registry dispatch и fail-closed для неизвестного типа — обязательный ранний фикс |
| Demo | `roomOf` и геометрия комнат уже достаточно общие: [index.html:1273](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1273). Но начальный layout предполагает living: [flat215_demo.py:404](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:404) | Сохранить room-aware shell, вынести получение layout/variant в providers |
| Cameras | Группировка по комнатам общая, но веса, высоты и ключевые роли — sofa/table/TV: [index.html:1760](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1760), [index.html:1802](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1802) | Геометрический scorer оставить, semantics views/focus roles получать из профиля |
| Scene assembly | `fromDemo.ts` уже принимает room identity и несколько помещений: [fromDemo.ts:121](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:121) | Добавить asset-provider dispatch; не переписывать мост |
| Kitchen | Это отдельный процедурный provider: [kitchen.ts](/home/pakar/igor/remlab/lib/viewer3d/kits/kitchen.ts) | Дать ему тот же variant/swap/render contract, не заставлять становиться catalog mesh |
| Night orchestration | `refresh_daily.sh` запускает living pipeline; `room_catalog` появляется почти перед demo: [refresh_daily.sh:435](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:435) | Legacy order оставить; для новых комнат ввести отдельный profile DAG |

Особо важный факт: число `30` в [demo_swap_pool.py](/home/pakar/igor/remlab/tools/scout/demo_swap_pool.py) относится к наполнению swap-пула, а не является универсальной нормой mesh generation. Квота должна считаться по `style × slot/role × size bucket`, плюс общий бюджет.

---

## 3. Основные риски

1. **Две таблицы навсегда.** Появятся две истины о наличии, размерах, стиле, фото и mesh readiness.

2. **Миграция в `products` сейчас.** Старые запросы почти нигде не фильтруют room type. Новые товары начнут влиять на living queues, метрики, enrichment и стоимость Salad.

3. **Одна роль на продукт.** Один и тот же стол, кресло или шкаф может использоваться в нескольких комнатах и ролях. Поле `products.cat_role` это не выражает.

4. **Generic JSON как новый язык программирования.** Если записать в профиль всю геометрию и алгоритмы, получится плохо тестируемый DSL. Профиль должен выбирать алгоритм и передавать данные, но solver остаётся кодовым плагином.

5. **Fail-open dispatch.** Текущее падение kitchen/hall в living validation способно выдавать формально успешные, но бессмысленные layouts.

6. **Статические slot sizes.** Они недостаточны для следующего шага с реальным контуром комнаты. Окончательный допустимый envelope должен вычисляться из конкретного `RoomInstance`.

7. **Сгенерированные, но недоступные meshes.** Сейчас room job может завершиться, однако binding/readiness не увидит результат.

8. **Ложная универсальность кухни.** Функциональный паритет нужен по стилю, swap, views и rerender, но не по внутреннему способу производства ассета.

9. **Тихая несовместимость банков.** Любое изменение профиля должно менять `profile_version`; старый bank нельзя автоматически считать совместимым.

---

## 4. Альтернативы

- **Изоляция + адаптер сейчас, нормализация позже — рекомендую.** Минимальный риск для live living, но требует временно поддерживать два источника.

- **Сразу нормализовать весь каталог.** Лучшее конечное состояние, но слишком большой blast radius на фоне четырёх незавершённых веток. Имеет смысл после shadow parity.

- **Оставить отдельные pipeline на каждую комнату.** Самое безопасное на ближайшие дни, но быстро создаст четыре версии cutout, mesh queue, camera logic и nightly orchestration.

- **Добавить `--room` во все существующие скрипты.** Выглядит просто, но превратит `compose2.py`, shell orchestration и solver в сеть условных веток. Это наиболее вероятный источник регрессий.

- **Сразу строить event-driven orchestration/service.** Пока избыточно. Детерминированный DAG с версионированными артефактами достаточен.

---

## 5. Рекомендация

### Контракты

Нужны четыре явных типа:

1. `CatalogItem`: canonical offer ID, origin, roles, dimensions с provenance, photo revision, style vector, asset strategy и readiness.

2. `RoomProfile`: правила типа комнаты.

3. `RoomInstance`: реальный контур, openings, utility points, purpose и версия профиля.

4. `RoomDemand`: вычисленные для конкретной комнаты zones и slot instances с допустимыми envelopes.

`items(room_type)` должен быть одним repository API поверх canonical DB view, а не договорённостью, которую каждый скрипт реализует сам.

### Содержимое RoomProfile

Профиль должен быть schema-versioned и содержать:

- `profile_id`, версию, допустимые purposes;
- роли, aliases, cardinality, required/optional, alternatives и dependencies;
- обязательные размерные оси и допустимые providers/inference policy;
- slot archetypes: идеал или формула, size buckets, default tolerance `−20…+10%`, hard limits;
- zones, anchors и отношения между зонами;
- ссылки на нормы из единого registry, severity и applicability;
- `solver_plugin` и constraint plugins;
- camera views: zone, label, focus/must/optional roles, минимальное покрытие и связь пары;
- глобальные style IDs и профильные веса ролей/материалов;
- asset strategy: `catalog_mesh`, `flat/decor`, `procedural_kit`;
- mesh coverage target по `style × slot-role × size bucket`, budget и dedup rules;
- publication/quality gates.

Флаги партнёров, filesystem paths, `.next`, расписание и включение конкретной квартиры в профиль помещать не надо.

### Кто читает профиль

- style — веса ролей и style dimensions;
- dimensions — provider policy и обязательные оси;
- selection/composer — required/optional, slots, tolerances и alternatives;
- mesh demand — coverage targets и asset strategy;
- judge — ожидаемый состав, style и views;
- solver façade — plugin, zones и norm references;
- camera engine — view/focus contract;
- demo/configurator — только готовые variants и provider-specific assets;
- orchestrator — список stage capabilities, но не бизнес-нормы.

### Защита living

- Не направлять live living через адаптер на первом этапе.
- Зафиксировать golden DB snapshot, legacy commands, environment, seed и время.
- Сравнивать adapter rows через `EXCEPT ALL`, сохраняя порядок.
- Проверять точные hashes для style inputs, cutout todo, mesh demand, `sets3`, judge inputs, layout/camera JSON и demo data.
- Не добавлять новые поля в legacy artifacts при выключенном флаге.
- GPU render проверять по scene/camera hash и perceptual snapshot: побайтовое равенство изображения между GPU/драйверами нереалистично.
- Новые комнаты публиковать только в `.next`; promotion атомарный, rollback — возврат предыдущего manifest.
- Обязательные негативные тесты: kitchen/hall не могут вызвать living validator; неизвестная комната завершается ошибкой.
- Переключение living — только после минимум двух чистых nightly runs и отдельного canary.

### Подготовка к распознаванию плана

Сейчас достаточно определить входной контракт `ApartmentPlan → RoomInstance[]`. Будущий CV/OCR модуль должен выдавать именно его, включая confidence и provenance измерений. Он не должен писать напрямую в solver/demo.

Так prebuilt mesh library естественно индексируется по:

```text
style × role/slot × size_bucket × asset_provider
```

а конкретная квартира создаёт `RoomDemand` и берёт готовое, запуская генерацию только для дефицита.

### Порядок работ с текущими worktrees

Текущие четыре вертикальные ветки не надо посреди работы заставлять рефакторить общий pipeline.

| Исполнитель | Сейчас владеет | Запретить в этой волне |
|---|---|---|
| onb-06 | bedroom composer/set/layout bank и его тесты | `compose2.py`, `style_score.py`, nightly shell |
| onb-07 | единственный writer `flat215_demo.py` и `index.html` | бизнес-правила bedroom внутри demo |
| onb-09 | kitchen solver/kit/checks в отдельных файлах | общий demo, общий dispatch, `models.py` |
| onb-13 | hallway rules/loader/solver в отдельных файлах | общий demo, `room_catalog.py`, `models.py` |

После завершения:

1. Merge bedroom set/layout contract.
2. Merge isolated kitchen и hallway modules.
3. Один интегратор единолично меняет `RoomType`/solver registry/validation dispatch.
4. Merge bedroom demo последним из этой волны.
5. Затем параллельно запустить 3–4 независимые задачи:

   - новый profile schema/loader/linter и fixtures;
   - canonical catalog view/adapter и living shadow equality test;
   - living parity harness и golden manifests;
   - read-only asset coverage audit, включая orphan room meshes.

6. Только после этих результатов параметризовать style/cutout/dimensions.
7. Затем generic mesh demand/binding.
8. После этого — composer/judge interface и camera profile.
9. `refresh_daily.sh`, общие bank paths и publication должен менять один ops-интегратор последним.

На текущей волне я бы вообще не трогал `compose2.py`, `mesh_queue.py` и live living orchestration.

---

## 6. Неопределённости

- Анализ был статическим; тесты не запускались, чтобы не создавать кэши или иные файлы.
- Код в активных внешних worktrees может уже отличаться от видимого состояния.
- Нет production snapshot БД и текущих manifests, поэтому реальное число пересекающихся SKU и возможность точного byte parity не подтверждены.
- Неясно, означает ли «~30 per style» 30 готовых замен суммарно или 30 для каждой значимой slot category.
- Для кухни ещё предстоит определить, является ли swap заменой отдельных модулей, фасада/палитры или всего kitchen run.

---

## 7. Что изменило бы моё мнение

Я поддержал бы немедленную миграцию, если будет показано, что:

- новая схема имеет отдельную many-to-many таблицу room roles, а не одно поле в `products`;
- все существующие readers инвентаризированы и защищены фильтрами;
- living golden run даёт нулевой diff;
- есть атомарный rollback и dual-write reconciliation.

Постоянные отдельные каталоги были бы оправданы, если доказано, что товары комнат никогда не пересекаются и у них действительно разные жизненные циклы.

Отказ от `RoomDemand` в пользу только статических профилей был бы разумен лишь если реальные планы всегда приводятся к небольшому набору стандартных прямоугольных шаблонов. Для заявленного следующего шага это маловероятно.

Файлы не изменялись.
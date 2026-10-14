---
tier: 2
topic: codex-floor-options
scope: Критика Codex плана demo-06 (пол от застройщика) до показа владельцу, 14.10
updated: 2026-10-14
source: external:codex
---

Вердикт: план владельцу пока не показывать. Идея здравая, но план смешивает две разные демо-квартиры, две ценовые модели и не описывает сквозное состояние.

### 1. «Что есть»: поправки

- `living-floor` действительно имеет 5 вариантов, но относится к UK-квартире `demo-uk-1` ([apartment.json:267](/home/pakar/igor/remlab/data/flat3d/apartment.json:267), [demo-uk.json:33](/home/pakar/igor/remlab/data/partners/demo-uk.json:33)). Российская `flat215` имеет только `demoData`, не `flat3d` ([demo.json:37](/home/pakar/igor/remlab/data/partners/demo.json:37)).
- Поэтому перенос из окна в «уже существующий living-floor» неверен: `/flat?demo=` строит отдельную одно-комнатную квартиру с мебельными слотами, без поверхностей ([fromDemo.ts:97](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:97), [fromDemo.ts:124](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:124)).
- У существующих полов цены не пустые: `0/1150/1450/2600`, а фото-вариант тоже `0` ([catalogue-base.json:301](/home/pakar/igor/remlab/data/flat3d/catalogue-base.json:301), [catalogue-base.json:320](/home/pakar/igor/remlab/data/flat3d/catalogue-base.json:320), [catalogue-base.json:1400](/home/pakar/igor/remlab/data/flat3d/catalogue-base.json:1400)). Это фиксированные числа, не `perM2`.
- Материалы и генераторы уже есть: планки, ёлочка, плитка ([material_pipeline.py:402](/home/pakar/igor/remlab/tools/assets/material_pipeline.py:402)); baseColor — 1024, остальные карты — 512, а не «1024 ×4» ([material_pipeline.py:32](/home/pakar/igor/remlab/tools/assets/material_pipeline.py:32), [material_pipeline.py:365](/home/pakar/igor/remlab/tools/assets/material_pipeline.py:365)).
- KTX2 фактически не реализован: он лишь обещан в комментарии ([material_pipeline.py:18](/home/pakar/igor/remlab/tools/assets/material_pipeline.py:18)); материалы грузятся обычным `TextureLoader` ([materials.ts:58](/home/pakar/igor/remlab/lib/viewer3d/materials.ts:58)). Имеющийся KTX2Loader обслуживает GLB ([meshes.ts:83](/home/pakar/igor/remlab/lib/viewer3d/meshes.ts:83)).
- Кухня — не полноценная механика выбора: отдельный жёстко заданный `kind==='kitchen'`, состояние только в `localStorage`; сцену, сумму, историю и коллекцию она не меняет ([index.html:3945](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3945), [index.html:3952](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3952)).
- В numpy пол действительно один семантический квад ([scene.py:469](/home/pakar/igor/remlab/services/planner-solver/planner/scene.py:469)), затем красится одним `_CLAY.floor` ([scene.py:570](/home/pakar/igor/remlab/services/planner-solver/planner/scene.py:570)).
- `light oak floor` сейчас лишь подсказка стиля «сканди», не выбранный пол; основной промпт разрешает модели самой выбрать материал пола ([draft_render.py:1658](/home/pakar/igor/remlab/tools/scout/draft_render.py:1658), [draft_render.py:2052](/home/pakar/igor/remlab/tools/scout/draft_render.py:2052)).

### 2. Общий контракт кухни/пола/плитки

Предложенная форма сломается напрямую: сейчас `kind` — `kitchen|bathroom|flooring`, `roomKind` не допускает `all`, а pricing использует `type: included|surcharge|on_request|from_configurator` ([partner.ts:49](/home/pakar/igor/remlab/contracts/partner.ts:49), [partner.ts:73](/home/pakar/igor/remlab/contracts/partner.ts:73)).

`materialId` нельзя требовать у всех: кухня ссылается на kit через `configuratorOptionId`; материал — только surface-ассет ([partner.ts:57](/home/pakar/igor/remlab/contracts/partner.ts:57), [configurator.ts:96](/home/pakar/igor/remlab/contracts/configurator.ts:96)).

Нужна одна авторская схема:

- `kind: kitchen|flooring|bathroom_tile`;
- `asset: {type:"configuratorOption", optionId} | {type:"material", materialId}`;
- `pricing: included | fixed(amount) | per_m2(rate,billableAreaM2) | on_request`;
- `settlement: allowance | property_price | developer_surcharge`;
- явные `roomIds/slotIds`, без расплывчатого `all`.

`billableAreaM2` обязан приходить от застройщика: витрина имеет комнату 439×325, UK living — 880×280, поэтому пример `+21 600 ₽` ни из одной автоматически не следует ([fromDemo.ts:97](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:97), [apartment.json:151](/home/pakar/igor/remlab/data/flat3d/apartment.json:151)).

Миграция — одним коммитом: новый контракт + оба partner JSON + адаптер в runtime `Option`; старую kitchen-схему сразу удалить. `ApartmentCard` можно сохранить совместимым, тогда текущий UI не упадёт. `from_configurator` через глобальный UK-каталог нельзя применять к RU-полу: сейчас именно так делает registry ([registry.ts:63](/home/pakar/igor/remlab/lib/partners/registry.ts:63)).

### 3. Доплата и ADR-0254

Отдельная строка не обязательно противоречит ADR, но план ложно называет это решением владельца. ADR запрещает несколько лимитов сертификата и требует один расчёт «выбрано/лимит/доплата» ([adr-0251-0300.md:108](/home/pakar/igor/remlab/.memory_bank/decisions/adr-0251-0300.md:108)); он не определяет, входит ли пол в сертификат.

По умолчанию:

- RF: пол — `developer_surcharge`, вне мебельного сертификата, пока конкретный застройщик письменно не включил его; книга называет сертификат на мебель/встраиваемое ([product-book.md:57](/home/pakar/igor/remlab/.memory_bank/guides/product-book.md:57)).
- UK: пол — `property_price`, часть персонализации/оценки недвижимости, не furniture allowance ([product-book.md:65](/home/pakar/igor/remlab/.memory_bank/guides/product-book.md:65)).

Текущий `/flat` применяет сертификат ко всем `scene.totals.upgrades` ([FlatConfigurator.tsx:289](/home/pakar/igor/remlab/components/flat3d/FlatConfigurator.tsx:289)). Нужны раздельные итоги `allowanceEligible` и `property/developerSurcharge`, включая серверный Quote; иначе пол фактически попадёт в лимит.

### 4. Смена материала ≤0,5 с

`tiled()` клонирует материал и каждую карту, задаёт repeat по `room/tileCm`; загрузка асинхронная и кэшируется по URL ([materials.ts:155](/home/pakar/igor/remlab/lib/viewer3d/materials.ts:155)). Сейчас API смены пола отсутствует: `update()` вызывает `setApartment()+syncObjects()`, но не `buildShell()`, поэтому новый surface сам не появится ([demo-scene.ts:127](/home/pakar/igor/remlab/lib/viewer3d/demo-scene.ts:127), [viewer.ts:272](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:272)).

Для гарантии 0,5 с нужны предзагрузка всех пяти albedo и отдельный `setSurfaceMaterial`; desktop — догрузка дополнительных карт до открытия picker, mobile — только albedo. Текущие пять комплектов весят лишь ≈268 КБ по сети, но декодируются примерно в 35 MiB GPU. KTX2 для этого демо лишний; сначала cold-cache тест. Критерий уточнить: «клик → первый кадр с окончательной текстурой», а не просто смена `material`.

### 5. Numpy-кадр

Не надо вести пол через треугольный `mesh_render`: его Python-цикл дорог именно по граням ([mesh_render.py:200](/home/pakar/igor/remlab/tools/scout/mesh_render.py:200)). Лучший путь — векторизованно семплировать только baseColor 256/512 по мировым X/Z пикселей маски `SEMANTIC.floor`; normal/roughness/AO кадру GPT не нужны.

Средний цвет оставить fallback. Геометрический генератор сотен досок не нужен; процедурный рисунок допустим лишь как пиксельная формула. Добавить floor id в cache key — сейчас ключ знает только комнату, мебель и камеры ([draft_render.py:2384](/home/pakar/igor/remlab/tools/scout/draft_render.py:2384)). Гейт: два ракурса p95 ≤7 с; ADR зафиксировал рабочий цикл 4,8 с ([adr-0151-0200.md:875](/home/pakar/igor/remlab/.memory_bank/decisions/adr-0151-0200.md:875)).

### 6. Перенос состояния

`Configuration` хранит не `slots`, а `selections: slotId→optionId` — этого достаточно после появления стабильного `living-floor` ([configurator.ts:158](/home/pakar/igor/remlab/contracts/configurator.ts:158)). Но коллекция v1 хранит только мебель/decor/cams ([collection.ts:36](/home/pakar/igor/remlab/contracts/collection.ts:36)), а `resolveCollectionFlat()` снова собирает furniture-only вариант ([source.ts:63](/home/pakar/igor/remlab/lib/configurator/source.ts:63)).

Нужны Collection v2 `developerOptions`, upgrader v1→v2, маппинг group→slot и путь для несохранённого `/flat?demo=`. Floor также должен войти в history, render payload и новый `stateId s2`; текущий hash считает только комнату, мебель и декор, а regex принимает лишь `s1` ([index.html:3365](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3365), [collection.ts:32](/home/pakar/igor/remlab/contracts/collection.ts:32)).

### 7. Пять главных рисков и решение

1. Подмена RU-витрины UK-квартирой из-за ошибочного предположения о `living-floor`.
2. Два источника цены/ассета и неверный `perM2` без утверждённой оплачиваемой площади.
3. Пол ошибочно попадёт в сертификат из-за единого `totals.upgrades`.
4. Выбор потеряется в history/collection/link/cache/server frame.
5. Supplier-фото без прав: у текущего фото `licence` пуст ([materials.json:201](/home/pakar/igor/remlab/data/flat3d/materials.json:201)); либо только procedural, либо лицензия — обязательный гейт.

Ещё добавить в план: `floor_pick` в обоих enum событий и отчёте ([analytics.ts:8](/home/pakar/igor/remlab/contracts/analytics.ts:8), [send.ts:11](/home/pakar/igor/remlab/contracts/send.ts:11)); EN-приёмку; холодный mobile; отдельный `kitchen-floor` не менять ([apartment.json:592](/home/pakar/igor/remlab/data/flat3d/apartment.json:592)).

Итог: делать, но иначе — сначала единый доменный контракт + settlement + состояние Collection v2, затем live/`/flat`, после этого дешёвый baseColor в numpy. KTX2 и новые пять текстур избыточны до визуального аудита уже существующих материалов.
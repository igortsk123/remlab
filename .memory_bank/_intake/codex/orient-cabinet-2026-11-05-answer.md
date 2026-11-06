## Вывод

Направление плана правильное: `cabinet_front` не должен менять yaw внутри рендера. Но в текущем виде план к выкладке не готов.

Главная проблема шире двух алгоритмов: сейчас существуют как минимум четыре независимых источника итогового yaw:

1. `orientation_state`;
2. опубликованный `orient.json`, включая отдельные решения `/test/orient-review/`;
3. `topview.json`, который фактически служит источником для `orient.json`;
4. `data/flat3d/front-overrides.json` и геометрический фолбэк `tools/flat3d/mesh_front.py`.

Критический дефект: `topview_render` принимает yaw из `orientation_state` независимо от статуса, а затем `batch_show` публикует весь `topview.json` как `orient.json`. Поэтому `vlm_pending` и `review_pending` уже сейчас могут стать боевым yaw. Простого переноса `cabinet_front` в `orient_worker` недостаточно.

Моя рекомендация:

- немедленно перестать считать `cabinet_front` финальным судьёй;
- сделать его консервативным свидетелем/вето;
- публиковать `orient.json` отдельным экспортёром только из `auto_resolved|human_resolved` для точного GLB;
- мигрировать ручные решения из `orient_review` и `front-overrides` в `orientation_state`;
- не использовать `topview.json` как реестр ориентации.

## 1. Карта решений и потребителей

### `orientation_state`

Схема допускает `pending`, `vlm_pending`, `review_pending`, `auto_resolved`, `human_resolved`: [mesh_queue.py:102](/home/pakar/igor/remlab/tools/scout/mesh_queue.py:102).

Писатели:

- Основной каскад пишет `status` и `resolution`: [orient_worker.py:379](/home/pakar/igor/remlab/tools/scout/orient_worker.py:379), [orient_worker.py:393](/home/pakar/igor/remlab/tools/scout/orient_worker.py:393).
- Человек через основной mesh-review меняет матрицу, `legacy_front_yaw` и статус на `human_resolved`: [mesh_review_sync.py:145](/home/pakar/igor/remlab/tools/scout/mesh_review_sync.py:145), [mesh_review_sync.py:151](/home/pakar/igor/remlab/tools/scout/mesh_review_sync.py:151), [mesh_review_sync.py:172](/home/pakar/igor/remlab/tools/scout/mesh_review_sync.py:172).
- Старый отдельный калибратор `orient_run.py` пишет другой контракт `…|v1`, используя `mesh_orient.calibrate`: [orient_run.py:28](/home/pakar/igor/remlab/tools/scout/salad/orient_run.py:28), [orient_run.py:37](/home/pakar/igor/remlab/tools/scout/salad/orient_run.py:37), [orient_run.py:43](/home/pakar/igor/remlab/tools/scout/salad/orient_run.py:43). Активных вызовов этого скрипта в репозитории не найдено.

Потребители yaw:

- `topview_render` читает `status`, `source`, `legacy_front_yaw`, но не фильтрует статус: [topview_render.py:33](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:33), [topview_render.py:42](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:42), [topview_render.py:49](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:49). Любая найденная запись становится `dec`, затем yaw применяется: [topview_render.py:355](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:355), [topview_render.py:372](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:372).
- `room_bindings` читает точный `legacy_front_yaw` и SHA: [room_bindings.py:643](/home/pakar/igor/remlab/tools/scout/room_bindings.py:643), [room_bindings.py:650](/home/pakar/igor/remlab/tools/scout/room_bindings.py:650). Здесь статусный gate правильный: разрешены только `auto_resolved|human_resolved`: [room_bindings.py:173](/home/pakar/igor/remlab/tools/scout/room_bindings.py:173), [catalog-bindings.json:20](/home/pakar/igor/remlab/tools/scout/rules/catalog-bindings.json:20). Затем yaw отдаётся клиенту через `mesh_for`: [room_bindings.py:514](/home/pakar/igor/remlab/tools/scout/room_bindings.py:514), [room_bindings.py:536](/home/pakar/igor/remlab/tools/scout/room_bindings.py:536).
- Старый `/test/orient-review/` сравнивает `legacy_front_yaw` базы с продом: [orient_review.py:38](/home/pakar/igor/remlab/tools/scout/orient_review.py:38), [orient_review.py:92](/home/pakar/igor/remlab/tools/scout/orient_review.py:92).
- `mesh_dims` применяет полную `R`, а не `legacy_front_yaw`, и допускает только решённые статусы: [mesh_dims.py:54](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:54), [mesh_dims.py:60](/home/pakar/igor/remlab/tools/scout/mesh_dims.py:60).
- `mesh_ready` и `mesh_family` читают только статус, SHA и `unusable`, чтобы решить готовность меша: [mesh_ready.py:47](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:47), [mesh_ready.py:64](/home/pakar/igor/remlab/tools/scout/mesh_ready.py:64), [mesh_family.py:227](/home/pakar/igor/remlab/tools/scout/mesh_family.py:227).
- `gallery_binding_shadow` читает только статус: [gallery_binding_shadow.py:150](/home/pakar/igor/remlab/tools/scout/gallery_binding_shadow.py:150).

### `topview.json`

Писатель — `topview_render`: [topview_render.py:443](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:443), [topview_render.py:467](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:467).

Читатели:

- `topview_page.py` читает `png`, `yaw`, `orient` для тестовой страницы и бейджа: [topview_page.py:23](/home/pakar/igor/remlab/tools/scout/salad/topview_page.py:23), [topview_page.py:37](/home/pakar/igor/remlab/tools/scout/salad/topview_page.py:37).
- `flat215_demo._mesh_extents` читает yaw: [flat215_demo.py:315](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:315), [flat215_demo.py:335](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:335). Но это сейчас мёртвый исследовательский путь: `_dim_from_mesh` нигде не вызывается, а рабочая `_dims_of` явно запрещает достройку размеров из меша: [flat215_demo.py:350](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:350), [flat215_demo.py:381](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:381). Следовательно, утверждение плана, что текущий спор расходится через габариты демо, устарело.
- Самый важный потребитель — не демо напрямую, а публикация всего файла как `orient.json`: [batch_show.py:650](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:650), [batch_show.py:656](/home/pakar/igor/remlab/tools/scout/salad/batch_show.py:656). `publish_merge` ничего не знает о статусах и просто делает `merged.update(local)`: [publish_merge.py:54](/home/pakar/igor/remlab/tools/scout/salad/publish_merge.py:54), [publish_merge.py:61](/home/pakar/igor/remlab/tools/scout/salad/publish_merge.py:61).

Это и есть основной канал утечки нерешённого yaw в прод.

### `orient.json`

Писатели:

- `batch_show` публикует в него `topview.json`.
- `/test/orient-review/ --pull` пишет человеческое решение только в продовый `orient.json`, не в `orientation_state`: [orient_review.py:249](/home/pakar/igor/remlab/tools/scout/orient_review.py:249), [orient_review.py:259](/home/pakar/igor/remlab/tools/scout/orient_review.py:259), [orient_review.py:268](/home/pakar/igor/remlab/tools/scout/orient_review.py:268).
- `orient_review --sync` также публикует отдельную проекцию: [orient_review.py:115](/home/pakar/igor/remlab/tools/scout/orient_review.py:115), [orient_review.py:123](/home/pakar/igor/remlab/tools/scout/orient_review.py:123).

Потребители:

- `flat215_demo.annotate_yaw` читает продовый файл и кладёт yaw в `demo-data.json`: [flat215_demo.py:1697](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1697), [flat215_demo.py:1704](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1704), [flat215_demo.py:1721](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1721).
- HTML демо переносит `p.yaw` при замене товара: [index.html:5407](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5407), [index.html:5411](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5411).
- `/flat` получает этот yaw из `demo-data.json`: [fromDemo.ts:301](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:301), [fromDemo.ts:384](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:384), [fromDemo.ts:452](/home/pakar/igor/remlab/lib/configurator/fromDemo.ts:452).
- Three.js применяет `rotation.y = -yaw`: [meshes.ts:146](/home/pakar/igor/remlab/lib/viewer3d/meshes.ts:146), [meshes.ts:149](/home/pakar/igor/remlab/lib/viewer3d/meshes.ts:149).
- Серверный 3D-рендер читает `orient.json`: [draft_render.py:2369](/home/pakar/igor/remlab/tools/scout/draft_render.py:2369), [draft_render.py:2377](/home/pakar/igor/remlab/tools/scout/draft_render.py:2377). Он применяет yaw только по строковому поиску источника: [draft_render.py:3247](/home/pakar/igor/remlab/tools/scout/draft_render.py:3247), [draft_render.py:3252](/home/pakar/igor/remlab/tools/scout/draft_render.py:3252). Будущий `review_pending:cabinet_conflict` содержит `cabinet_` и ошибочно будет считаться уверенным.
- `build-catalogue.mjs` строит статический каталог `/flat`: [build-catalogue.mjs:109](/home/pakar/igor/remlab/tools/flat3d/build-catalogue.mjs:109), [build-catalogue.mjs:137](/home/pakar/igor/remlab/tools/flat3d/build-catalogue.mjs:137).
- `tools/flat3d/mesh_front.py` сначала читает `orient.json`, а при отсутствии решает yaw заново по геометрии: [mesh_front.py:80](/home/pakar/igor/remlab/tools/flat3d/mesh_front.py:80), [mesh_front.py:103](/home/pakar/igor/remlab/tools/flat3d/mesh_front.py:103), [mesh_front.py:120](/home/pakar/igor/remlab/tools/flat3d/mesh_front.py:120).
- `pipeline_map` считает только покрытие: [pipeline_map.py:148](/home/pakar/igor/remlab/tools/scout/pipeline_map.py:148).

### Другие судьи

- Активный второй судья: `front_by_depth`, перебивающий каскад: [topview_render.py:400](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:400), [topview_render.py:410](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:410).
- Ручной override сильнее `orient.json`: [front-overrides.json:2](/home/pakar/igor/remlab/data/flat3d/front-overrides.json:2), [build-catalogue.mjs:119](/home/pakar/igor/remlab/tools/flat3d/build-catalogue.mjs:119), [flat215_demo.py:1708](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1708).
- Геометрический судья `/flat`: [mesh_front.py:60](/home/pakar/igor/remlab/tools/flat3d/mesh_front.py:60), [mesh_front.py:126](/home/pakar/igor/remlab/tools/flat3d/mesh_front.py:126). В текущем `furniture.json` действительно есть записи `frontSource: geometry`, то есть это не только мёртвый код.
- `mesh_orient.calibrate` — старый независимый решатель: [mesh_orient.py:127](/home/pakar/igor/remlab/tools/scout/mesh_orient.py:127), [mesh_orient.py:185](/home/pakar/igor/remlab/tools/scout/mesh_orient.py:185). Активной автоматизации не найдено.
- `mesh_front.infer_seat_front` — не второй глобальный судья, а штатное evidence сидячих внутри каскада: [mesh_front.py:45](/home/pakar/igor/remlab/tools/scout/mesh_front.py:45).
- `scene_mesh.py` yaw не решает — только применяет переданный аргумент: [scene_mesh.py:80](/home/pakar/igor/remlab/tools/scout/scene_mesh.py:80).
- `gallery_build.py` yaw не читает; он, наоборот, удаляет случайный `orient.json` из каталога: [gallery_build.py:35](/home/pakar/igor/remlab/tools/scout/salad/gallery_build.py:35).

## 2. Роль `cabinet_front`

Схема «согласен → auto, спор → review» разумна как конечная цель, но с оговорками.

Я бы сделал так:

- Для нормального orienter:
  - `cabinet` согласен и имеет доказанную точность → второй свидетель, можно `auto_resolved`;
  - спорит → `review_pending`;
  - unsure → VLM, затем текущая логика.
- Для `up_rejected` нельзя писать `orienter+cabinet_agree`: orienter уже отвергнут. Здесь свидетели — `generator_front_prior` и `cabinet`/VLM.
- До калибровки новой метрики `cabinet` лучше использовать только как veto: конфликт отправляет в review, согласие само по себе не повышает статус.
- `cabinet_squarish` и неразличимые модели должны воздерживаться, а не получать yaw по tie-break.

Варианты:

- Убрать override сейчас — самый безопасный короткий шаг. На предъявленной выборке это исправляет 9 и не ухудшает 3 неразличимых. Риск: среди остальных 14 конфликтов каскад может быть неправ.
- Оставить только как фолбэк при отсутствии решения каскада — хуже. Отсутствие решения обычно означает недостаток уверенности; слабый алгоритм получит максимальную власть именно на сложных случаях.
- Оставить текущий override — неприемлемо: он уже доказанно выбирает заднюю стенку.
- Свидетель/вето — лучший баланс, если публикация строго фильтрует статусы.

Отдельно нужно нормализовать роли. `topview_render` превращает `тумба прикроватная` в `тумба` через `split()[0]`: [topview_render.py:381](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:381). В каскаде роль остаётся `тумба прикроватная`, а `CABINET_ROLES` содержит лишь `тумба`: [cabinet_front.py:26](/home/pakar/igor/remlab/tools/scout/salad/cabinet_front.py:26). Расширять на шкафы/стеллажи без отдельной валидации не следует.

## 3. `flip_prob`

`flip_prob` — softmax-вероятность самой вероятной из 24 кубических перестановок после orienter: [orient_infer.py:90](/home/pakar/igor/remlab/tools/scout/orient_infer.py:90), [orient_infer.py:93](/home/pakar/igor/remlab/tools/scout/orient_infer.py:93), [orient_infer.py:114](/home/pakar/igor/remlab/tools/scout/orient_infer.py:114).

Это не вероятность «перед выбран правильно» и не VLM-confidence. Это уверенность flipper во всей дискретной ориентации, включая up.

Находка верна именно для `up_rejected`: исходные `R` и quaternion заменяются на `RAW_UPRIGHT_R`, но условие продолжает проверять старый `inf['flip_prob']`: [orient_worker.py:207](/home/pakar/igor/remlab/tools/scout/orient_worker.py:207), [orient_worker.py:215](/home/pakar/igor/remlab/tools/scout/orient_worker.py:215), [orient_worker.py:237](/home/pakar/igor/remlab/tools/scout/orient_worker.py:237). Вердикт отвергнутого flipper больше не относится к применённой гипотезе.

Безопасная правка:

- сохранить явный `up_rejected`;
- для обычной ветки оставить нынешний порог до отдельной калибровки;
- для `up_rejected` не учитывать `flip_prob`, но авторазрешать только при наличии второго валидированного основания: известный generator-front prior плюс уверенный VLM/cabinet;
- источник называть `generator_prior+vlm_agree`, а не `orienter+vlm_agree`;
- если provenance генератора неизвестен — `review_pending`, потому что это иначе VLM-only, что противоречит контракту строки 8: [orient_worker.py:4](/home/pakar/igor/remlab/tools/scout/orient_worker.py:4).

Глобально удалять `flip_prob >= 0.5` я бы не стал.

## 4. Метрика глубины

Отступ 8–10% вероятно поможет против рамки задней стенки: нынешняя эрозия всего 4 px на карте 300 px, то есть около 1,3%: [cabinet_front.py:223](/home/pakar/igor/remlab/tools/scout/salad/cabinet_front.py:223), [cabinet_front.py:227](/home/pakar/igor/remlab/tools/scout/salad/cabinet_front.py:227). Она практически не отсекает рамку.

Но одной этой правки мало:

- В docstring заявлено `small_relief − 2×deep_holes`: [cabinet_front.py:208](/home/pakar/igor/remlab/tools/scout/salad/cabinet_front.py:208).
- Реальный код считает `small + deep`: [cabinet_front.py:236](/home/pakar/igor/remlab/tools/scout/salad/cabinet_front.py:236), [cabinet_front.py:242](/home/pakar/igor/remlab/tools/scout/salad/cabinet_front.py:242). Большой провал задней панели тем самым становится положительным фасадным признаком.

Лучший признак:

- отбрасывать край по distance transform относительно размера bbox, а не фиксированными пикселями;
- отделять мелкие выступающие компоненты — ручки;
- искать повторяющиеся горизонтальные/вертикальные швы — ящики и дверцы;
- ниши учитывать как центральные области, но не как один большой прямоугольный утопленный задник;
- большой сплошной плоский центр с одной периферической рамкой считать признаком зада;
- оценивать знак и распределение рельефа после вычитания низкочастотной плоскости, а не только долю абсолютных градиентов.

«Асимметрия толщины» сама по себе ненадёжна: Hunyuan может выдумать толщину и паразитную геометрию. Ручки, повторные швы и число/площадь плоских сегментов сильнее.

Порог надо подбирать с обязательной зоной abstain. Проверки 12 моделей недостаточно: нужны все 14 конфликтов плюс случайная выборка из 93 согласий, иначе можно улучшить конфликтный лист и испортить silent-majority.

## 5. Выкатка и откат

Рекомендуемый порядок:

1. Снять согласованный baseline:
   - `orientation_state`;
   - продовый `orient.json`;
   - `topview.json` и PNG;
   - `front-overrides.json`;
   - `demo-data.json`;
   - `data/flat3d/furniture.json`;
   - точные GLB SHA для каждого mesh id.

2. Остановить публикацию `topview.json → orient.json`.

3. Запустить shadow нового каскада без записи в существующие строки. Нужен явный policy/version: текущий worker не пересчитывает уже существующий revision key: [orient_worker.py:308](/home/pakar/igor/remlab/tools/scout/orient_worker.py:308), [orient_worker.py:317](/home/pakar/igor/remlab/tools/scout/orient_worker.py:317).

4. Проверить глазами:
   - 12 известных;
   - все 14 конфликтов;
   - случайную выборку согласий;
   - модели с `up_rejected`;
   - прикроватные тумбы, шкафы и стеллажи отдельно.

5. Мигрировать человеческие решения из двух внешних каналов в `orientation_state`:
   - `/test/orient-review/`;
   - `front-overrides.json`.

6. Построить отдельный `orient.json`-export:
   - только `auto_resolved|human_resolved`;
   - exact GLB SHA;
   - yaw, status, source, resolution SHA;
   - нерешённые записи не экспортировать.

7. Затем пересобрать:
   - `room_bindings`;
   - галерею/`mesh-index`;
   - `orient.json`;
   - topview;
   - `demo-data.json`;
   - статический `furniture.json`;
   - runtime-копии GLB;
   - серверные 3D-кадры.

Текущий nightly-порядок этого не гарантирует: демо собирается на строке 436, а `orient_worker` запускается только на 505: [refresh_daily.sh:427](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:427), [refresh_daily.sh:436](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:436), [refresh_daily.sh:505](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:505).

### Кэш

`orient_sig` содержит GLB key и md5 resolution: [topview_render.py:76](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:76). Этого недостаточно при изменении политики рендера. Если просто удалить override, существующая запись с тем же `orient_sig` будет взята из кэша до вызова новой логики: [topview_render.py:359](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:359), [topview_render.py:365](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:365).

Нужно включить в signature:

- версию политики yaw;
- статус;
- resolution SHA;
- версию рендера;
- точный GLB SHA.

И убрать legacy-исключение, считающее старый `cabinet_*` автоматически валидным: [topview_render.py:362](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:362).

`demo-data.json` в браузере запрашивается с `Date.now()`: [index.html:1162](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1162). GLB имеет `?v=sha`: [mesh-url.ts:26](/home/pakar/igor/remlab/lib/configurator/mesh-url.ts:26). Клиентская подпись объекта включает yaw: [viewer.ts:1790](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:1790). Это хорошо.

Но `draft_render` кэширует всю карту ориентации в глобальной `_S3_ORIENT` без TTL: [draft_render.py:2372](/home/pakar/igor/remlab/tools/scout/draft_render.py:2372). После выкладки нужен рестарт/инвалидация долгоживущих процессов и прогрев 3D-сцен.

### Откат

Копии одного `topview.json` недостаточно. Откатывать надо согласованный release:

- строки `orientation_state`;
- `orient.json`;
- `topview.json` и соответствующие PNG;
- `demo-data.json`;
- `furniture.json`;
- room bindings;
- ручные overrides, пока они существуют.

`publish_merge` не умеет удалять ошибочно добавленные ключи, поэтому откат через очередной merge неполон. Нужна атомарная замена реестра из snapshot либо release-пойнтер.

## 6. Что в плане упущено или неверно

1. Неверно определён рабочий путь `flat215_demo.py:335`: это не активный источник габаритов; реальный ущерб идёт через публикацию `topview.json` как `orient.json`.

2. Нет статусного gate в `topview_render`. Это blocker: pending/review yaw публикуется.

3. Не учтён отдельный человеческий источник `/test/orient-review/`, который пишет прод, но не базу.

4. Не учтён `front-overrides.json`, явно стоящий поверх канонического решения.

5. Не учтён геометрический решатель `tools/flat3d/mesh_front.py`.

6. Фолбэк `yaw_for` нельзя оставить «как сейчас». Он читает старую запись `…|v1`, но ищет поле `resolution.yaw`: [topview_render.py:81](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:81), [topview_render.py:90](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:90). Старый `mesh_orient` пишет `front_yaw`, а не `yaw`: [mesh_orient.py:185](/home/pakar/igor/remlab/tools/scout/mesh_orient.py:185). На этом формате фолбэк фактически возвращает 0.

7. Не решена идентичность физического файла. `topview_render` выбирает первый SKU в лексикографическом обходе: [topview_render.py:324](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:324), [topview_render.py:333](/home/pakar/igor/remlab/tools/scout/salad/topview_render.py:333). Галерея выбирает поколение отдельно, по mtime или binding: [gallery_build.py:47](/home/pakar/igor/remlab/tools/scout/salad/gallery_build.py:47). Затем `orient.json` теряет SHA и индексируется только `mesh_id`. Поэтому `GALLERY_FROM_BINDING` нельзя откладывать в follow-up, если заявлена гарантия «один yaw у каждого меша».

8. Откат одного JSON не покрывает БД, демо, статический каталог и накопительный merge.

9. `refresh_daily.sh` и `index.html` ошибочно вынесены за scope: первый определяет неправильный порядок сборки, второй является фактическим потребителем yaw через `demo-data.json`.

10. Тесты должны дополнительно проверять:
   - pending/review никогда не экспортируются;
   - `cabinet_conflict` не считается `sure` строковым поиском;
   - изменение renderer-policy инвалидирует topview cache;
   - отзыв решения удаляет/заменяет запись в `orient.json`;
   - галерея, orientation и binding ссылаются на один SHA;
   - ручное решение проходит только через БД;
   - `up_rejected` не зависит от старого `flip_prob`.

## Итоговая рекомендация

Сохранить идею плана, но изменить архитектурную формулировку:

> `orientation_state` — единственный авторитет. `cabinet_front`, orienter, VLM и seat detector только формируют evidence. Человек финализирует ту же запись. `orient.json` — ревизионно-точная read-only проекция только решённых статусов. `topview.json` — манифест рендера, никогда не источник ориентации.

Для ближайшей безопасной выкладки я бы сначала отключил override `front_by_depth`, закрыл публикацию pending/review и проверил 14 конфликтов. Улучшение самой depth-метрики — второй этап, а не условие прекращения уже известной ошибочной перебивки.

Неопределённости: факты 12/107/14 приняты из постановки и независимо по рабочим листам не перепроверялись; статический аудит не доказывает, какие ручные flat3d-скрипты сейчас запускаются вне репозитория. Однако наличие `frontSource: geometry` в собранном `furniture.json` подтверждает, что дополнительный геометрический контур применялся.
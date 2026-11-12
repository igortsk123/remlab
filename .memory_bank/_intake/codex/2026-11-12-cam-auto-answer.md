---
tier: 3
topic: codex-answer
scope: cam-auto
updated: 2026-11-12
source: external:codex-exec-ephemeral-2026-11-12
---
# Ответ Codex: автовыбор ракурсов (T-20261112-76/1)

> Сверено работником по коду: demo-scene.ts:434 pose(), index.html:4280 (неизвестный тип → гостиная), draft_trial.py:43 (≥2 вида), index.html:4074 (зазор 20 см) — подтверждены. tools/ops/tour-reissue.sh есть только в worktree auto-reissue-1112 (T-92, не влит).

Итог: направление верное, но текущая модель `intent` слишком бедна для заявленной таблицы, а «один ракурс» затрагивает не только подбор камер, но и весь серверный контракт генерации. Я бы принял идею с четырьмя поправками:

- детская — профиль `bedroom:child:*`, не новый `kind`;
- неизвестная комната — `other`, никогда не fallback на гостиную;
- `need` заменить на явные группы целей для каждого вида;
- ручную камеру хранить отдельным override-слоем, сохраняя `v.cams` как автоэталон.

### 1. Цели ракурсов

Общие нормы: честно передавать размер и планировку, снимать примерно с уровня груди, показывать связь помещений, избегать крупного предмета перед объективом. Вход/угол — хорошая точка съёмки, но дверь не обязана быть главным объектом кадра. Окно лучше сбоку либо с контролируемой экспозицией, а не как выбитое белое пятно. Это совпадает с рекомендациями [Zillow](https://www.zillow.com/learn/real-estate-photography-tips/), [Adobe](https://www.adobe.com/au/creativecloud/photography/discover/real-estate-photography.html) и [realtor.com](https://www.realtor.com/marketing/wp-content/uploads/2024/08/realtor.com_How-to-improve-your-photography-skills-for-real-estate-listing-photos.pdf).

Моя корректировка таблицы:

- Гостиная:
  - C1 от входа/ближайшего честного угла, диван целиком и связь с ТВ-зоной;
  - C2 с противоположной стороны, обеденная зона либо окно и связь с входом.
  - Не требовать одновременно диван и всю ТВ-стену, если из-за этого получается чрезмерно широкий объектив.

- Спальня:
  - C1 от двери по диагонали: кровать, изголовье и хотя бы одна тумба;
  - C2 с дальней стороны: шкаф/комод и связь с входом; кровать остаётся узнаваемой.
  - «От окна» не должно означать камеру вплотную к подоконнику.

- Кухня:
  - C1 от входа или диагонального угла, чтобы показать протяжённость рабочего фронта, столешницу и остров/второе плечо;
  - C2 от противоположного торца: столовая группа и связь кухни с соседней зоной;
  - если стола нет — второе плечо, остров или холодильник/колонны, а не случайный угол.
  - Прямой плоский вид на одну стену обычно слабее диагонального двухстенного вида.

- Детская:
  - C1 — кровать как признак спальной функции;
  - C2 — стол у окна плюс хранение/игровая зона;
  - кровать и стол в одном кадре — преимущество, но не жёсткое требование для маленькой комнаты.

- Прихожая:
  - пара «от входа вдоль оси / с другого конца обратно» правильна. Для коридоров Matterport также рекомендует эквивалентные точки на обоих концах [Matterport](https://matterport.com/en-gb/blog/wow-factor-our-conversation-photographer-daniel-milstein-why-3d-photography-works).

- Санузел:
  - базовый кадр из проёма/дальнего доступного угла: раковина плюс ванна/душ; унитаз не должен доминировать;
  - C2 только если он показывает отдельную полезную зону, а не ту же сцену с поворотом на месте.
  - Один кадр на санузел — нормальная практика: примерный shot list realtor.com даёт один кадр на ванную, 1–2 на спальню и 2–4 на кухню. Для тесных помещений Zillow советует угол или дверной проём [Zillow 3D Home](https://www.zillow.com/3d-home/guide/).

Важно: нынешний `window` фактически не требует окна в кадре. Он только выбирает значение `kind`; для любого не-`dining` C2 проверяется `S.need`, обычно главное изделие: [index.html:4960](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4960), [index.html:4900](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4900).

### 2. Где хранить intent и риски `camPairV2`

Оставить декларативную таблицу рядом с CAMFIT — правильно: этот блок уже исполняется и страницей, и `demo-cams.mjs`: [demo-cams.mjs:19](/home/pakar/igor/remlab/tools/flat3d/demo-cams.mjs:19). Но я бы переименовал её в `CAM_PROFILES` и разделил:

```text
profile selector: kind + purpose
profile data: roles, view goals, crop, clearance, count policy
pair engine: camPairFor(profile, room, variants, openings, previous)
```

Ключи: `living`, `bedroom`, `bedroom:child`, `kitchen`, `hall`, `bathroom`, `other`.

Сейчас детская — вариант спальни с `purpose`, а не `kind`: [trial_bedroom.py:1081](/home/pakar/igor/remlab/tools/scout/trial_bedroom.py:1081). Поэтому сигнатуре `camPairFor(kind, room, items, openings)` не хватает `purpose` или готового `profileKey`.

Не оставлять нынешний fallback неизвестного типа на гостиную: [index.html:4280](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4280). Для `other` нужен нейтральный профиль без дивана и ТВ.

Простого `intent.need` недостаточно:

- сейчас список означает «покажи хотя бы один предмет из списка»: [index.html:4892](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4892), [index.html:4900](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4900);
- поэтому им нельзя выразить «кровать + стол», «диван + ТВ» или «раковина + ванна».

Нужны группы наподобие:

```js
views: [
  {must:[{roles:['кровать'], min:1},
         {roles:['тумба прикроватная'], min:1, optional:true}]},
  {must:[{roles:['стол детский','стол рабочий'], min:1},
         {roles:['шкаф','стеллаж','комод'], min:1, optional:true}]}
]
```

Риски лестницы:

- уровень 9 разрешает C2 на любом полу, поэтому алгоритм всегда пытается выдумать пару: [index.html:4791](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4791);
- `pairFar` — штраф в ключе, не жёсткое условие: [index.html:5026](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5026);
- физический зазор до мебели сейчас всего 20 см: [index.html:4074](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4074);
- `ready:false` у кухни и прихожей нигде не проверяется; это фактически комментарий, а не feature flag: [index.html:4247](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4247).

Для прихожей 1,2×3 м нельзя применять общий порог короткой стороны: две точки вдоль оси полезны. Нужен отдельный corridor-профиль с ослабленной боковой близостью — такая логика уже есть через `near:0.6`: [index.html:4276](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4276).

### 3. Когда оставлять один ракурс

Не принимать решение только по площади. Санузел 1,5×1,7 м и прихожая 1,2×3 м показывают, почему это ошибочно.

Рекомендованный порядок:

1. Предварительный сигнал для bathroom/other: площадь `<3,2 м²` или короткая сторона `<1,60 м`.
2. Реальное решение — по геометрии кандидатов.
3. C2 существует, только если:
   - вокруг точки есть свободная площадка хотя бы `60×60 см`;
   - точка вне полотна/траектории двери;
   - расстояние C1–C2 не меньше `max(100 см, 0,40 диагонали комнаты)`;
   - C2 добавляет новую обязательную зону либо хотя бы 15–20% нового покрытия;
   - это не просто поворот менее чем на 45–60° из почти той же точки.
4. Для bathroom площадью `<3,2 м²` по умолчанию один кадр; второй разрешается только при прохождении всех условий.
5. Для hall пороги площади и короткой стороны не применять; проверять длину оси и разнесённость точек.

То есть `area/shortSide` — быстрый prior, но окончательное правило — `meaningfulSecondCandidate`.

### 4. Ручной ракурс

Отдельный слой лучше. Не заменять им `v.cams`.

Минимальный контракт:

```js
v.cams                 // автоматическая пара, как сейчас
v.cams_ver             // версия автоалгоритма
cameraOverrides[state] // C1/C2 с source:'user'
effectiveCams()        // override поверх auto
```

`state` — `roomStateKey`, поскольку он уже различает комнату, вариант и геометрию: [index.html:3144](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3144).

При первом нажатии:

- взять `LIVE.scene.pose()`; движок уже экспортирует `viewPose()`: [demo-scene.ts:434](/home/pakar/igor/remlab/lib/viewer3d/demo-scene.ts:434);
- преобразовать `rot = (540 - yaw) % 360`;
- записать C1 и перейти в UX «Ракурс 2/2»;
- после подтверждения C2 запустить существующий `vwRealistic`.

Для точного текущего взгляда недостаточно `x/y/rot`: `viewPose()` возвращает ещё `pitch`: [viewer.ts:900](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:900). Сейчас `PhotoPose` не содержит пользовательский pitch, а `capturePhoto` строит фиксированный `photoRay`: [viewer.ts:122](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:122), [viewer.ts:1827](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:1827). Нужно добавить `pitch` в:

- `PhotoPose`, `photoRay/capturePhoto`;
- `camPoseOf`;
- `payload().cams`;
- `draft_render.cams_from_request`;
- `shotCamOk`.

Иначе «запомнили текущий взгляд» будет неверно при наклоне вверх/вниз.

Совместимость:

- `vwPreKey` уже строится из эффективных поз, поэтому после добавления `pitch` к `camPoseOf` кэш будет корректно инвалидироваться: [index.html:11099](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:11099).
- `shotCamOk` сейчас сравнивает только x/y/rot/fov/pose — добавить pitch с допуском около 0,5°: [index.html:5336](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5336).
- подписи сделать динамическими: «Ваш ракурс / Второй ракурс», а не статические `CAM_VIEW_NAMES`: [index.html:10940](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:10940).
- для ручной камеры заново считать `crop` и `pshift`; иначе мобильное превью возьмёт старое окно или fallback: [index.html:9796](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:9796).

Один кадр требует отдельной серверной ветки. Сейчас:

- тур принимает только ≥2 browser views: [draft_trial.py:43](/home/pakar/igor/remlab/tools/scout/draft_trial.py:43);
- `build_from_views` прямо требует оба вида: [improve_mode.py:616](/home/pakar/igor/remlab/tools/scout/improve_mode.py:616);
- промпт многократно зафиксирован на «TWO views».

Не дублировать C1 как C2. Ввести `view_count:1`, однокадровый лист и однокадровый промпт.

### 5. Подтверждение и версии

Backend-шага отдельно не нужно: `EditRebuild` публикует только итог, а итоговая сборка идёт с камерами: [conveyor.py:294](/home/pakar/igor/remlab/tools/floorplan/conveyor.py:294), [conveyor.py:304](/home/pakar/igor/remlab/tools/floorplan/conveyor.py:304). Но нужен клиентский шаг применения результата:

- дождаться новой bundle version;
- сбросить manual override для подтверждённых комнат либо привязать его к старому `stateId`;
- показать авто-пару новой версии.

Иначе локальный `CAMS_VER` не спасает: его ключ содержит версию правила и id варианта, но не bundle version: [index.html:5392](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5392).

`cams_ver` нужен, лучше назвать `cams_rule_ver`, чтобы не путать с локальным `CAMS_VER`. При отсутствии/несовпадении страница должна пересчитать авто-пару, но не удалять ручной override без явного события подтверждения/«Вернуть авто».

Старые живые туры перевыпустить стоит. В текущем дереве команда — не `tools/ops/tour-reissue.sh`, а `tools/floorplan/reissue.py`: [reissue.py:11](/home/pakar/igor/remlab/tools/floorplan/reissue.py:11). Перевыпуск уже вызывает текущий `add_cams`: [trial_reissue.py:201](/home/pakar/igor/remlab/tools/scout/trial_reissue.py:201).

После перевыпуска нужен аудит фото: изменившиеся точки перестанут проходить `shotCamOk`. Карточки/обложки и важные опубликованные фото придётся доснять; платные фото я бы не регенерировал массово без списка реально изменившихся камер.

### 6. Что ещё упущено

- Обложка: пользовательский C1 не должен автоматически становиться poster. Выбирать обложку по `camPosterBad` либо отдельной кнопкой «Сделать обложкой»: [index.html:5086](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:5086), [index.html:6676](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:6676).
- `cams_own`: «Вернуть авто» должен возвращать авто-пару именно текущего стиля, а не shared-пару комнаты: [demo-cams.mjs:73](/home/pakar/igor/remlab/tools/flat3d/demo-cams.mjs:73).
- Пустые комнаты: текущий сервер вообще требует непустые `room` и `items`, поэтому санузел/кухня тура без мебели фото не получит: [draft_service.py:593](/home/pakar/igor/remlab/tools/scout/draft_service.py:593).
- Туры пока обставляют только living/bedroom: [trial_bundle.py:64](/home/pakar/igor/remlab/tools/scout/trial_bundle.py:64). Intent для кухни/санузла сам по себе не создаст им варианты и фотосцену.
- Серверный fallback `draft_render.demo_cams` остаётся отдельным старым алгоритмом: [draft_render.py:674](/home/pakar/igor/remlab/tools/scout/draft_render.py:674). Для требования «одна функция везде» его надо либо заменить вызовом канонического CAMFIT, либо оставить только аварийным и явно маркировать.
- Нужны эталонные проверки минимум на: санузел 150×170, коридор 120×300, галерейную кухню 180×360, детскую со столом у окна, комнату с двумя дверями и комнату без распознанного типа.

Главный архитектурный вывод: расширять декларативные профили рядом с `CAM_ZONES` правильно, но публичной единицей должна стать не «обязательно пара», а результат `{cams:[1..2], ruleVer, profile, diagnostics}`. Тогда один и тот же контракт честно обслужит авто, ручной UX, старые туры и маленькие помещения.
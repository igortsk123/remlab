Короткий вывод: пункты 1, 3 и 4 — реальные дефекты геометрии/поиска. Пункт 2 смешивает разные каноны. Пункт 5 геометрически корректен только для свободностоящей корпусной группы, но не для «встройки». Пункт 6 — дефект эталонной сцены, плюс рядом обнаружен недодержанный контракт прохода.

### 1. `seating.L_left / L_right`

Вердикт: дефект. Арифметика верна. Для текущей галереи `S=220`, `T=110` зазор равен уже 75 см. Глубина и длина второго дивана из формулы сокращаются, поэтому обязательный loveseat проблему не решает.

Код проверяет расстояние только до первого дивана: `_by_base()` сохраняет первый экземпляр, после чего `check_distances()` обращается к одному `by["диван"]` — [validate.py:304](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:304), [validate.py:357](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:357). Позиции создаются именно так, как описано, — [template.py:355](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:355), [template.py:462](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:462), [template.py:608](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:608).

Практика: 16–18″, то есть примерно 40–46 см, относится к столу относительно всей окружающей мягкой посадки, а не только главного дивана. Стол должен быть доступен с каждого места. [Homes & Gardens](https://www.homesandgardens.com/interior-design/the-library-how-to-design-the-perfect-living-room-layout)

Минимальная правка:

- Для L-формы канонически сдвигать стол к внутреннему углу до `target=COFFEE_GAP=42.5`:

  `base_gap = sofa.w/2 + L_GAP − table_long/2`  
  `shift = side × max(0, base_gap − target)`

  Для текущей карточки это ±32.5 см.

- В `check_distances()` проверять стол относительно всех диванов того же seating-блока: preferred 36–46, hard 32–50.
- `TABLE_OFF_AXIS` сделать shape-aware: для настоящей L-композиции допустима ось внутренней полости, если стол в preferred-вилке обоих диванов. Иначе правильный сдвиг будет ошибочно получать `COFFEE_TABLE_OFF_CENTER` — сейчас soft начинается после 22 см [validate.py:793](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:793).
- Если SKU после сдвига не помещается — отклонять L-схему либо брать круглый/квадратный/nesting-стол, но не менять размеры SKU.

Сторож: зеркальная параметризация `L_left/right` для нескольких размеров дивана/стола; у обоих диванов gap ∈ `[32,50]`, целевой — 42.5.

### 2. `quiet.fireplace_flank`

Здесь владелец прав в классификации, но два столика сами по себе не «ошибка практики». Это допустимый обслуженный вариант, однако не определяющий канон.

Три композиции относятся к разным схемам:

- `quiet.fireplace_flank`: ровно два кресла + камин.
- `reading.fireplace_anchor`: одно кресло + камин, поверхность/свет опциональны.
- `reading.corner_vignette`: кресло + поверхность + свет без камина.

Пара кресел по сторонам камина — самостоятельный распространённый приём; два приставных столика не являются обязательной частью определения. [Architectural Digest](https://www.architecturaldigest.com/video/watch/space-savers-3-interior-designers-transform-the-same-cozy-living-room)

Сейчас состав меняется скрыто от инвентаря: ≥2 поверхностей автоматически превращают базовый канон в вариант с двумя столами — [template.py:2801](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2801), [template.py:2820](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2820). При этом паспорт глобально объявляет поверхность `required_any`, а fireplace-ветка и валидатор её не требуют — [templates.json:438](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:438), [validate.py:1488](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:1488).

Минимальная правка:

- Карточку и базовый `fireplace_flank` собирать без поверхностей.
- Не делать один стул допустимым внутри `quiet`: создать отдельный `reading.fireplace_anchor`.
- Перенести `required_any=surface` внутрь паспорта `quiet_chat`; у `fireplace_flank` обязательный якорь — камин.
- Если два внешних столика действительно нужны продукту, оформить отдельной схемой `fireplace_flank_served`, а не включать по факту наличия SKU.
- `SERVICE_SURFACE` либо оставить как честный soft для минимального fireplace-канона, либо сделать документированное исключение только для `fireplace_flank`. Глобально правило ослаблять нельзя.

### 3. `reading.corner_vignette`

Арифметика верна. Для `180×92`, повёрнутого на 45°:

`extent_x = extent_y = (180 + 92) / (2√2) = 96.2 см`.

Это координаты центра для касания стен. При отступе 14 см нужны `x=y=110.2`, тогда как код даёт 81.4. Фактическое проникновение в стены — около 14.8 см.

Причина: `_corner_candidates()` смешивает радиус до угла `hypot(w,d)/2` с проекцией по осям, а потом повторно умножает его на `sin/cos` — [template.py:2471](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2471).

Правильная общая формула:

```text
ex = |cos θ|·w/2 + |sin θ|·d/2
ey = |sin θ|·w/2 + |cos θ|·d/2
center_x = wall_x ± (ex + margin)
center_y = wall_y ± (ey + margin)
```

Практика подтверждает состав «кресло + столик + лампа» в неиспользуемом углу, но не даёт универсального нормативного отступа 14 см. Это продуктовый operational margin, который следует хранить в JSON как hypothesis. [Homes & Gardens](https://www.homesandgardens.com/interior-design/chair-table-lamp-layout-hack)

Минимальная правка: заменить расчёт в `_corner_candidates()` на `ex/ey`. Важно: нынешний `canon_gallery.corner_scene()` уже считает bbox иначе и тем самым маскирует дефект production-плейсера — [canon_gallery.py:163](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:163). Галерея и solver должны вызывать общий helper.

Краевой случай: если рассчитывать envelope всего блока, ближайшим к стенам может оказаться торшер или столик, а кресло будет выдвинуто. Если владелец требует именно кресло глубоко в углу, нужен дополнительный anchor-контракт кресла и зеркальные варианты компаньонов.

### 4. `reading.bay_anchor`

С диагнозом согласен, но переиспользовать `place_bay_armchair()` буквально нельзя: его координаты рассчитаны по одному креслу, не по полному блоку.

Сейчас:

- `place_reading()` добавляет только центроид эркера — [template.py:2083](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2083).
- `place_bay_armchair()` генерирует 25/50/75% и прижимает спинку к наружной кромке — [template.py:2188](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2188).
- `build_reading(allow_solo=True)` маркирует singleton исключительно как `window_anchor` — [template.py:2016](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2016).
- Паспорт утверждает, что singleton в эркере допустим, но exemption есть только для окна — [templates.json:512](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:512), [templates.json:526](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:526).

Практика допускает как одиночное кресло, так и пару кресел в крупном эркере. [Homes & Gardens](https://www.homesandgardens.com/ideas/reading-nook-ideas)

Минимальная правка:

- Выделить общий `_bay_candidates(room, block)` с позициями 50/25/75%.
- Прижимать к наружной границе спинку кресла-якоря; весь блок обязан быть внутри комнаты, но торшер/столик могут находиться у устья эркера, а не на 75% внутри ниши.
- Добавить `build_reading(anchor_variant='bay_anchor', allow_solo=True)` и exemption `bay_anchor: min_composition`.
- `place_bay_armchair()` сделать алиасом общего пути.
- Галерею тоже вести через этот helper: нынешний отдельный `bay_scene()` снова может показывать то, чего solver получить не умеет — [canon_gallery.py:187](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:187).

Для непрямоугольного эркера bbox недостаточен: затем понадобится реальная наружная грань полигона и inward normal.

### 5. `media.media_installation`

Текущая геометрия математически корректна для свободностоящих корпусов у одной стены:

- внутренние edge-gap действительно одинаковы по 40 см независимо от ширины компаньонов;
- формула `−(bearer.d−c.d)/2` точно совмещает задние плоскости — [template.py:2308](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2308).

Но это не канон «встроенной инсталляции». Настоящая встроенная мебель проектируется как единая заказная система вокруг ТВ; у неё непрерывный модульный ряд или заданные изготовителем швы и общая фасадная плоскость. [Homes & Gardens](https://www.homesandgardens.com/interior-design/living-rooms/built-in-cabinet-ideas-for-family-rooms)

Проблемы паспорта:

- 40 см не подтверждены источником: `_proof` просто переносит число из несвязанной схемы `TV+камин` — [templates.json:226](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:226).
- При одном компаньоне композиция заведомо не симметрична.
- При двух разных по ширине/высоте корпусах равные зазоры не создают общей симметрии.

Минимальная правка зависит от смысла:

- Если это реальные отдельные SKU: переименовать в `freestanding_media_storage`, оставить back-alignment и одинаковые edge-gap; 40 см пометить hypothesis, не нормой.
- Если нужна настоящая `installation`: `gap=0` в 2D или модульный шов производителя, одинаковая серия/глубина, фасадная плоскость; до появления collection/carcass-данных схема должна быть sleeping.
- Слово «симметрия» использовать только для пары одинаковых или геометрически совместимых компаньонов. Один/разные — отдельный asymmetric/balanced-вариант.

То есть менять 40 на другое произвольное число сейчас неправильно: сначала надо развести два разных канона.

### 6. `storage.console_behind_sofa`

Частично подтверждаю. Ковёр не является абсолютным hard-требованием для любого одиночного дивана, но для эталона плавающей seating-группы он нужен: он делает остров визуально намеренным и связывает диван со столиком. Практика рекомендует хотя бы передние ножки посадки на ковре. [Pottery Barn](https://www.potterybarn.com/pages/rug-guide/living-room/)

Это дефект мини-сцены, не `place_console_behind_sofa()`. Более того, сцена вручную создаёт диван и столик вместо production seating-блока — [canon_gallery.py:453](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:453).

Минимальная правка:

- Собрать свидетеля через `build_block('sofa_solo', диван+столик+ковёр)`, затем вызвать production console placer.
- Для дивана 220 см взять ковёр порядка 250–270 см вдоль дивана — действующая проектная вилка `sofa +30…50`. Передние ножки — на ковре.
- Ковёр не должен заходить под консоль: `комод` прямо запрещён на seating-rug — [template.py:1084](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1084). Ковёр располагается со стороны фронта дивана; консоль — за спинкой.
- Сначала устранить внутренний дрейф правил: builder использует tuck 15 см, `occupancy.json` говорит 25 см, invariant проверяет лишь 2% площади — [template.py:387](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:387), [occupancy.json:573](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:573), [invariants.py:67](/home/pakar/igor/remlab/services/planner-solver/planner/invariants.py:67).

Сама консоль вплотную к спинке плавающего дивана правильна: это признанный sofa-table приём, не обязательно настенная консоль. Настенный вариант — отдельный `wall_console`. [Homes & Gardens](https://www.homesandgardens.com/interior-design/styling-the-back-of-the-sofa)

Дополнительный дефект: `route_after_console_required=true`, но production фактически гарантирует лишь общий проход 46 см. В галерее после консоли остаётся около 100.5 см — хорошо; в бою при остатке 91 см и консоли глубиной 40 останется только около 49 см. Нужно принимать консоль лишь при:

`остаток за диваном ≥ gap_sofa_console + console_depth + route_min(91)`.

### Приоритет исправлений

1. Общие `_corner_candidates` и `_bay_candidates`, используемые и solver, и галереей — сейчас галерея маскирует production-дефекты.
2. L-table: зазор до каждого дивана + shape-aware axis.
3. Развести `fireplace_flank` / `fireplace_anchor` и убрать скрытое добавление двух столиков.
4. Добавить ковёр через настоящий seating-блок и закрыть route-контракт консоли.
5. Переименовать текущую media installation; настоящую встройку не имитировать без данных.

Общий гейт галереи стоит усилить: не только «нет hard», но и «нет неожиданных soft»; разрешённые soft должны иметь явный allowlist в паспорте. Иначе эталон продолжит показывать композиции, которые сам движок считает неканоничными.
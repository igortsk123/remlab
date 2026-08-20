## Вывод

- `tandem_r/l` — не признанный самостоятельный канон с таким названием. Это законная **асимметричная пара кресел на одном фланге**, но только ситуационный fallback. Сейчас паспорт переоценивает её: форма должна проигрывать обычной паре по сторонам и допускаться по сертификату недостижимости.
- `square` — нормальная трёхсторонняя разговорная композиция: два дивана образуют Г, пара кресел закрывает третью сторону, четвёртая остаётся входом. Но текущая реализация односторонняя и неполная.
- Таблица якорей требует ещё двух типов: `free_region` и `zone_boundary`. Кроме того, формы seating нельзя привязать к одному якорю: один и тот же блок сейчас пробуется у стены, у окна и в центре.

## 1. `seating.tandem_r/l`

### Что реально строит код

Название `tandem` вводит в заблуждение. Кресла не сидят «одно за другим» по направлению взгляда:

- у них одинаковый `x`;
- оба повернуты одинаково на 90°/270°;
- по `y` они разнесены на сумму половин **ширины** кресел + 12 см.

То есть функционально это два кресла **плечом к плечу на одном боку композиции**, хотя на чертеже они выглядят вертикальным столбиком: [template.py:775](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:775).

### Норма или костыль

Базовая практика — диван с парой кресел напротив него либо зеркально по сторонам. Ballard называет «sofa + two chairs opposite» наиболее универсальной схемой; при дверях пару предлагают разворачивать так, чтобы сохранить пересечение комнаты. [Ballard Designs](https://www.ballarddesigns.com/howtodecorate/2017/04/15-best-living-room-layout-tips/). AD и H&G отдельно подчёркивают целостность и визуальный баланс парных кресел. [Architectural Digest](https://www.architecturaldigest.com/story/living-room-furniture-layout-maximizes-small-space), [Homes & Gardens](https://www.homesandgardens.com/interior-design/living-room-layout-hacks).

Пара на одном фланге встречается в практике, особенно при дверях, маршруте или асимметричной архитектуре. Но это не общая «норма узкой комнаты» и не известный тип `tandem`. Правильный статус:

> Поддержанный практикой асимметричный L-layout, но продуктовый fallback, а не первичный канон.

Частота 23 справа против 5 слева ничего не доказывает: `tandem_r` стоит раньше `tandem_l` в каскаде [zones.json:145](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:145), а `place_template` перебирает формы последовательно: [template.py:1663](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1663). Это может быть алгоритмический right-first bias.

### Условия законности

1. Обычная `pair_sides`, `u`, `facing` или медиапригодная форма должна быть сертифицирована как недостижимая, а не просто не попасть в бюджет. Такая политика уже записана для one-sided fallback: [zones.json:1208](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1208).

2. Нужны два одинаковых кресла либо доказанная matched pair. Это особенно важно здесь:

   - асимметрия уже заложена самой постановкой;
   - `ax` считается по глубине `arm1` и применяется к обоим креслам, поэтому разные глубины дают разные фактические зазоры.

3. Оба кресла должны независимо:

   - смотреть в общий центр;
   - достигать столика;
   - входить в компактную группу;
   - иметь доступ, не перекрытый соседним креслом.

4. Пустой бок обязан выполнять функцию — маршрут либо открытый вход в группу. Для secondary-маршрута использовать действующие 76 см, для primary — 91 см: [occupancy.json:345](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:345). Публичные рекомендации также дают около 36″/91 см для основного прохода и требуют планировать движение до мебели. [Homes & Gardens](https://www.homesandgardens.com/interior-design/the-library-how-to-design-the-perfect-living-room-layout).

5. Не нужен фиксированный порог ширины комнаты. Проверять надо полезную поперечную ширину на выбранной оси:

   ```text
   pair_sides требует примерно:
   sofa.w + 2×FLANK_GAP + arm1.d + arm2.d

   side_pair требует примерно:
   sofa.w + FLANK_GAP + max(arm1.d, arm2.d)
   ```

   Плюс реальные краевые клиренсы. Большая комната с дверью или пилоном тоже может иметь узкую полезную полосу.

6. Поворот строго 90° допустим для разговорной группы: кресла смотрят поперёк на центр. Но это не лучший медиаканон. Если media-сценарий требует кресло к ТВ, хотя бы одно кресло должно выполнить действующий конус ≤45°; иначе форма должна иметь `intent=conversation_fallback`, а не наследовать `media_primary`. Дизайнерские источники рекомендуют слегка разворачивать кресла, когда это улучшает общение и проход, но универсального обязательного угла 20–45° нет. [Homes & Gardens](https://www.homesandgardens.com/ideas/living-room-seating-ideas).

### Готовые формулировки

Для обоих зеркал одинаковый текст, меняется сторона.

`when`:

> `sofa_2armchairs`; два кресла образуют одинаковую либо явно согласованную пару; предпочтительные двухсторонние формы (`pair_sides/u/facing/media_bridge`) full-chain недостижимы из-за полезной поперечной ширины, проёма или маршрута; пара на одном фланге hard-valid, а противоположный фланг сохраняет требуемый маршрут 76/91 см. В media-primary хотя бы одно кресло выполняет угол к носителю ≤45°.

`why`:

> Ситуационная асимметричная L-композиция: два парных кресла стоят плечом к плечу на одном боку зоны и освобождают второй бок для входа/маршрута. Практика подтверждает парные кресла как единый элемент и допускает их перенос/разворот ради дверей и движения, но базовыми остаются пара напротив дивана или зеркальные фланги. Поэтому это fallback только после сертификата недостижимости предпочтительных форм, а не общий канон узкой комнаты. Provenance: Ballard Designs sofa+2 chairs/doorway layout; AD/H&G paired chairs; числовые маршруты — `occupancy.json`.

Я бы сохранил ID ради совместимости, но задал обоим:

```text
form=side_pair
mirror=right | left
```

В перспективе лучше одна схема `side_pair` с двумя зеркальными кандидатами, сравниваемыми полным ключом.

## 2. `seating.square`

### Вердикт

Основной паттерн каноничен. Дизайнер прямо рекомендует композицию «два дивана по двум сторонам, два кресла на третьей, открытая сторона — маршрут». [Homes & Gardens](https://www.homesandgardens.com/celebrity-style/martha-stewart-christian-wide-swivel-armchair). Это трёхсторонняя U/open-square conversation group, а не геометрический трюк.

В коде:

- главный и второй диваны образуют Г;
- пара кресел стоит на противоположной боковой стороне центрального столика;
- кресла опять же стоят плечом к плечу, а не перекрывают друг друга: [template.py:625](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:625).

Форма полезна не просто «в тесной комнате», а когда ограничена **глубина**, но есть поперечная ширина. Она переносит кресла с дальней стороны главного дивана на бок, то есть экономит глубину ценой ширины.

### Дефекты текущей реализации

- `square` всегда ставит второй диван слева, кресла справа: для него нет зеркала. Поворот блока не заменяет отражение.
- Центр `x` обоих кресел рассчитывается по глубине `arm1`; для разных кресел геометрия несимметрична.
- Паспорт говорит лишь «два дивана», хотя фактически форма требует ещё два кресла.
- В family policy `square` уже правильно классифицирован как one-sided fallback, а не предпочтительный `two_sofa`: [zones.json:1154](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1154).

Минимально нужны два зеркальных кандидата одной формы и matched-pair contract для кресел.

### Готовые формулировки

`when`:

> Группы `sofa_loveseat_2armchairs` или `two_sofas_2armchairs`: два дивана образуют Г, два одинаковых/согласованных кресла помещаются парой на третьей стороне центрального столика; вариант с креслами напротив главного дивана недостижим по глубине, но поперечная сторона hard-valid; четвёртая сторона остаётся открытой для маршрута и входа в группу. Допускается только после сертификата недостижимости предпочтительных two-sofa/U форм.

`why`:

> Каноническая трёхсторонняя разговорная группа: два дивана занимают соседние стороны, парные кресла балансируют второй диван на третьей, центральный столик связывает все места, четвёртая сторона остаётся открытой для доступа. Такая форма экономит глубину, но требует большей поперечной ширины; поэтому это ситуационный depth-constrained fallback, а не форма для любых двух диванов. Provenance: Homes & Gardens — два дивана по двум сторонам и пара кресел на третьей; AD/H&G — paired chairs и общий центральный якорь.

Рекомендуемое `form`:

```text
form=three_sided_pair
mirror=left_sofa | right_sofa
```

## 3. Якоря и формы: главная ошибка таблицы

Ваша классификация смешивает **форму блока** и **место его постановки**.

Например, `default`, `u` или `tandem` не имеют единственного `wall_segment`: тот же блок последовательно получает кандидаты:

- у стены;
- спинкой к окну;
- в середине комнаты;
- относительно медиа-вилки.

Это видно непосредственно в `place_template`: [template.py:1669](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1669).

Более того, `Candidate.topology` уже существует, но после ранжирования не сохраняется в выбранной гипотезе: [template.py:1295](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1295). Именно topology, а не ID формы, должен стать фактическим anchor в артефакте.

Ещё одна проблема: `seating.default` не является одной формой:

- `sofa_2armchairs.default` — кресла по разным сторонам;
- `sofa_loveseat.default` — два дивана Г-стыком;
- `sofa_armchair.default` — одно фланговое кресло;
- `sofa_solo.default` — один диван.

Значит, разрешённый ID канона должен быть как минимум:

```text
seating.{group_id}.{variant}.{anchor_topology}
```

### Исправленная карта

| Схемы | Корректный anchor | Исправление |
|---|---|---|
| `default/bulky/facing/bridge/tandem/u/square/pouf_table` | `inherited/runtime`; композиционно `object(primary_sofa)` | Это формы, не ситуации. Разрешённый anchor берётся из фактического candidate topology: wall/window/free-region. |
| `gap_compact` | наследуется | Это параметр формы — другой зазор столика, не якорь. |
| `floating_pair` | `object(media_bearer)` с relation `opposite_at_viewing_distance` | `room_center` описывает положение, но не причину: диван вычисляется относительно носителя/ТВ-вилки. |
| `window_back` | `window` | Верно. |
| `media_centered` | `wall_segment` + relation `aligned_to object(primary_sofa)` | Просто `wall_segment` теряет главное содержание «по оси дивана». |
| `media_mirror` | `wall_segment` | Верно; `mirror` — form, не новый anchor. |
| `media_at_jamb` | `wall_segment` + qualifier `adjacent_to_opening/jamb` | Лучше добавить anchor `opening`; generic `object` для двери не использовать. |
| `media_between_windows` | `wall_segment` + qualifier `between_windows` | Верно только с qualifier. |
| `media_installation/storage_combo/builtin` | `wall_segment` | Верно. |
| `media_corner` | `corner` | Верно. |
| `fireplace_side_by_side` | `wall_segment` | Верно: камин здесь обязательный член атомарного блока, а не уже поставленный якорь. |
| `tv_over_fireplace` | `object(fireplace)` | Верно. |
| `fireplace.storage_flanks/plant_flanks` | `object(fireplace)` | Не `wall_segment`: корпуса и растения определены относительно очага. Весь блок затем ставится у стены. |
| `fireplace.solo`, `fireplace_solo.solo` | `wall_segment` | Верно для одиночного очага; одновременно это дублирующиеся канонические идентичности, лучше один сделать alias. |
| `quiet_chat` | `wall_segment \| free_region`; composition anchor=`object(surface)` | Код якорит блок на столике и пробует стены плюс середину: [template.py:3123](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:3123). |
| `quiet.fireplace_flank` | `object(fireplace)` | Верно. |
| Все четыре `reading.*` | window / bay / corner / object(fireplace) | Ваши значения верны. |
| `dining_island`, `dining_round_compact` | `free_region` | Не обязательно геометрический центр комнаты. Нужен новый тип `free_region`; `room_center` был бы ложным обещанием центровки. |
| `dining_against_wall`, `dining_edge_nook` | `wall_segment` | Верно. |
| `dining_foldable` | пока неоднозначно | Freestanding extendable → `free_region`; откидной/пристенный → `wall_segment`. Сначала разделить семантики. |
| `storage_perimeter` | `wall_segment` | Верно. |
| `storage_shallow` | `wall_segment` + relation `behind object(sofa)` | Корпус остаётся пристенным; диван задаёт остаточную полосу, но не является непосредственной опорой. |
| `storage_zone_divider` | `zone_boundary` | Не `room_center`: делитель должен совпадать с границей living/dining или иной пары зон. Нужен новый тип. |
| `corner_tower` | `corner` | Верно, с secondary relation к одной из стен угла. |
| `decor.corner_plant`, `decor.bay_plant` | corner / bay | Верно. |
| `window_seat.bench_under_window`, `bay_bench` | window / bay | Верно. |

### Какие типы добавить

Минимально расширить реестр:

```text
window | bay | corner | wall_segment | free_region |
zone_boundary | object
```

`room_center` оставить только для схем, действительно требующих центрирования, а не как синоним «не у стены».

Для двери можно не добавлять отдельный тип, если разрешены qualifiers:

```text
anchor=wall_segment
qualifier=adjacent_to_opening
```

### Ещё одна паспортная дыра

Runtime shapes содержат `L_right`, `media_parallel`, `media_half`, `media_bridge`, но среди seating-схем `templates.json` их нет. Сравнение видно между [zones.json:145](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:145) и [templates.json:79](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:79). До CI-гейта ADR-0112 их нужно либо завести как формы, либо явно объявить aliases; иначе «все 45 схем имеют anchor/form» всё равно не покроет реально исполняемую библиотеку.
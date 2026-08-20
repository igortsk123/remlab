## Вывод

Библиотека покрывает основные типы гостиной, но сейчас её нельзя считать ни полной, ни строго канонической. Главная проблема — не число схем, а ложная единица учёта:

- `seating.default` скрывает несколько принципиально разных композиций;
- зеркала и алиасы считаются отдельными канонами;
- некоторые реальные production-схемы вообще отсутствуют в паспорте;
- паспорт часто не позволяет однозначно восстановить, какой именно канон выбрал солвер.

По рабочему дереву в `templates.json` уже **53 схемы**, включая `square_r`, а не 52. При этом галерея дважды создаёт `seating.default` и добавляет непаспортный `storage.console_behind_sofa`. Поэтому «52 карточки и полное покрытие» пока не является доказанным инвариантом.

Мой главный совет: сначала исправить идентичность канона на уровне `(function, group_id, anchor, form, mirror)`, трассировку и CI; лишь затем добавлять новые формы. Иначе библиотека будет расти количественно, но аудит останется недостоверным.

Критерий:

> Канон — воспроизводимая композиция с ясной функцией, ситуационным якорем, минимальным составом и инвариантами. Геометрический fallback тоже допустим, но только как явно названный situational fallback с сертификатом недостижимости предпочтительного канона.

---

## Что обнаружено в инфраструктуре

1. Тест покрытия проверяет лишь наличие `shape` среди паспортов seating. Один общий `default` формально покрывает `sofa_armchair`, `sofa_facing_sofa`, `sofa_lamp`, `armchair_pair` и другие разные композиции: [test_passport_situational.py](/home/pakar/igor/remlab/services/planner-solver/tests/test_passport_situational.py:45).

2. Галерея создаёт `seating.default` для разных групп с одинаковым ID и именем файла; одна карточка может затереть другую: [canon_gallery.py](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:343).

3. `sofa_facing_sofa` существует как группа, но не как самостоятельный канон: [zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:106). Семантика спрятана внутри ветвей `build_block`: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:551).

4. `storage.console_behind_sofa` реализован, валидируется и рисуется, но отсутствует в паспорте: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2040), [validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:1659), [canon_gallery.py](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:484).

5. `media_storage_combo` и `media_installation` используют одну композицию; галерея прямо трактует первую как вторую: [canon_gallery.py](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:581).

6. `media_wall` реально возвращается для роли `стенка`, но у зоны ноль схем: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2703).

7. `place_reading` имеет непаспортный wall-fallback: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2251).

8. `dining_edge_nook` в паспорте всё ещё описан как unwired, хотя placer уже его вызывает: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1870).

9. Почти нигде нет структурированного `provenance`; `why` с названием журнала не заменяет источник, дату, статус и проверяемое утверждение. CI проверяет `anchor/form/when/why/status`, но не проверяет scheme-level composition/provenance.

10. Перед применением приоров надо синхронизировать данные: текущий [practice_priors.json](/home/pakar/igor/remlab/tools/scout/rules/practice_priors.json:1) содержит старые частоты — например окно `empty=19`, `bench=17`, `sofa=16`, `plant=7`, тогда как в вопросе уже `bench=19`, `plant=17`, `empty=17`, `sofa=9`. Идентификаторы исходов местами также не совпадают с классификатором [opportunities.py](/home/pakar/igor/remlab/services/planner-solver/planner/opportunities.py:42).

---

## Аудит существующих схем

Обозначения: **К** — полноценный канон; **С** — честный ситуационный fallback; **П** — параметрический профиль, а не отдельная композиция; **Д** — дубль/алиас; **H** — гипотеза, требующая подтверждения.

Для всех строк по умолчанию не хватает структурированного provenance и явного scheme-level `required/optional roles`.

### Seating

| Схема | Вердикт | Что исправить |
|---|---|---|
| `default` | Не канон, общий технический ID | Расщепить минимум на `armchair_pair.vis_a_vis`, `sofa_armchair.single_flank`, `sofa_2armchairs.pair_sides`, `sofa_facing_sofa.vis_a_vis`, `sofa_lamp`, `sofa_solo`, `sofa_pouf`. |
| `bulky` | С/П | Переименовать в `deep_armchairs_opposite`; только для конкретных групп и глубоких кресел, после недостижимости обычных флангов. |
| `facing` | К | `armchair_pair_opposite_sofa`; ограничить применимость группой и ролями. Нынешнее `when` упоминает лишний `диван 2`. |
| `bridge` | С/H | `armchair_pair_angled_inward`; явно указать, что это не media-вариант и что предпочтительные формы недостижимы. |
| `tandem_r`, `tandem_l` | С | Один канон `side_pair`, `mirror=±1`; обязательны одинаковая пара и сертификат недостижимости двухсторонней формы. Не считать два зеркала двумя канонами. |
| `u` | К | Реальная U-композиция; вместо общего `area>25` нужны допустимые группы, минимальная свободная оболочка и центральная поверхность. |
| `square`, `square_r` | К/С | Один `three_sided_conversation`, зеркала — варианты. Для тесной двухдиванной сцены это fallback с сертификатом, а не универсальная форма. |
| `pouf_table` | К | Min: seating + сертифицированный пуф/оттоманка, пригодная как поверхность. Порог пригодности поверхности пока H. |
| `floating_pair` | К, неверное имя | Переименовать в `floating_sofa_opposite_media`: это отношение дивана к media bearer, а не «пара». Anchor `object:media_bearer` верен. |
| `gap_compact` | П | Оставить как geometry profile совместимых композиций, не учитывать отдельным практическим каноном. |
| `window_back` | К/С | Валидная ситуация; нужны радиатор, штора, открывание окна, высота спинки и Q8. Не делать предпочтительным только из-за наличия окна. |
| `media_parallel` | К/H | `single_armchair_parallel_to_sofa`; anchor лучше `object:media_bearer`. Для названия «к экрану» ограничить угол 30°, а 30–45° передавать `media_half`. |
| `media_half` | К | Оставить; anchor `object:media_bearer`, явный диапазон угла и `facing_target`. |
| `media_bridge` | К/H | Парная диагональная форма к экрану; min — два кресла одного визуального семейства. |
| `L_left`, `L_right` | К | Один `two_sofa_l_joint` с зеркалом. Anchor — основной диван/центр группы, а не безликий `runtime`. |

Два дивана визави, диван с двумя креслами и U-композиции — стандартные практические семейства, а диагональ кресел применяется для обхода входов и маршрутов. Это подтверждают [Ballard Designs](https://www.ballarddesigns.com/howtodecorate/2017/04/15-best-living-room-layout-tips/) и [Homes & Gardens](https://www.homesandgardens.com/ideas/living-room-furniture-ideas). Но конкретно «два кресла столбиком с одного бока» — не самостоятельная общеупотребительная норма; это допустимый асимметричный fallback.

### Media

| Схема | Вердикт | Что исправить |
|---|---|---|
| `media_centered` | К | Базовая схема; дополнить отношением к оси главного дивана и допустимыми компаньонами. |
| `media_mirror` | Д | Это зеркальная сторона акцента у `media_centered`, не отдельный канон. |
| `media_at_jamb` | С | Anchor `opening` верен; только если чистая стена недоступна и сохранены дверь/маршрут. |
| `media_corner` | С | Честный fallback; предпочтительная прямая стена должна быть сертифицированно недоступна. |
| `media_between_windows` | К/С | Anchor — `wall_segment:between_windows`; экран полностью на глухом простенке, учесть блики и шторы. |
| `media_storage_combo`, `media_installation` | Д | Объединить в `freestanding_media_storage_run`; room mode и число компаньонов — варианты одной формы. Зазор 40 см оставить H. |
| `fireplace_side_by_side` | К | Min: TV bearer + fireplace на одной стене; оба должны читаться с главной посадки, баланс не обязательно означает равную ширину. |
| `tv_over_fireplace` | Sleeping правильно | Нужны вертикальная геометрия, модель жара, инструкция конкретного камина и ТВ. |
| `media_builtin` | Sleeping правильно | Нужны совместимые модули/коллекция, крепёж, высоты и глубины. |
| фактический `media_wall` | К, паспорт отсутствует | Лучше не заводить вторую зону: добавить `media.wall_unit_centered`, carrier=`стенка`, `counts_as_storage=true`. |

Практика допускает встроенный ТВ, скрытый ТВ и вторичный/off-axis экран, поэтому центрирование — не абсолютная догма, а часть конкретного канона. См. [Homes & Gardens о ТВ как менее доминирующем фокусе](https://www.homesandgardens.com/interior-design/living-rooms/layout-tricks-that-make-a-tv-less-dominant).

### Fireplace, dining, storage

| Схема | Вердикт | Что исправить |
|---|---|---|
| `fireplace.storage_flanks` | К | Min: камин + согласованная пара хранения; симметрия относительно камина. |
| `fireplace.plant_flanks` | H | Возможная декоративная форма, но не требовать два растения автоматически; допустима асимметрия при балансе. |
| `fireplace.solo` | К | Оставить единственным solo-каноном. |
| `fireplace_solo.solo` | Д | Удалить из канонической библиотеки; runtime alias при необходимости сохранить вне галереи. |
| `dining_island` | К | Верно: свободный регион, стол и доступные места вокруг. |
| `dining_against_wall` | К/С | Компактная схема: недоступная сторона без стульев, остальные места и pullout валидны. |
| `dining_round_compact` | К | Не только fallback: круглый стол — самостоятельная форма для компактной циркуляции. |
| `dining_foldable` | Sleeping, anchor неверен | Разделить: extendable freestanding → `free_region`; wall drop-leaf → `wall_segment`. Нужны open/closed dims. |
| `dining_edge_nook` | К | Статус исправить на production-wired. Явно хранить bench seats, chair sides, доступ и конкретную форму 4/5/6 мест. |
| `storage_perimeter` | К | Лучше `wall_storage_run`; min — один или несколько storage-модулей у стены. |
| `storage_shallow` | К/С | Явно разделить wall-shallow и отношение к плавающему дивану. |
| `storage_zone_divider` | Sleeping правильно | Нужны finished back, устойчивость/крепёж, высота и запрет опрокидывания. |
| `storage.corner_tower` | К/С | Ситуационный канон; нужен пригодный угловой сегмент и крепление высокой мебели. |
| фактический `console_behind_sofa` | К, паспорт отсутствует | Добавить: anchor=`object:sofa`, form=`back_console_centered`, min — floating sofa + shallow console; маршрут за консолью ≥91 см либо консоль у стены. |

Открытые стеллажи как делители и консоли за диваном — признанные приёмы зонирования: [Homes & Gardens — room dividers](https://www.homesandgardens.com/interior-design/living-rooms/living-room-divider-ideas), [зонирование мебелью](https://www.homesandgardens.com/interior-design/how-can-i-divide-a-room-with-furniture).

### Quiet, reading, decor, window seat

| Схема | Вердикт | Что исправить |
|---|---|---|
| `quiet_chat` | К, имя можно улучшить | `paired_conversation`; min — два кресла + общая доступная поверхность. Anchor фактически `free_region/wall`, внутренний object-anchor — поверхность. |
| `quiet.fireplace_flank` | К | Min — камин + два кресла; поверхности optional. Одиночное кресло — другой канон. |
| `reading.window_anchor` | К | Min chair; для функции reading желательно `task light OR sufficient daylight`, поверхность optional. Зеркальные углы — варианты, не каноны. |
| `reading.bay_anchor` | К | То же; объединить с устаревшим `bay_armchair` runtime-alias. |
| `reading.corner_vignette` | К | Min должен быть chair + task light + reachable side table; иначе это просто одиночное кресло. |
| `reading.fireplace_anchor` | Погранично | Кресло+камин без света/поверхности — `fireside_seat`, не доказанная reading-zone. Либо переименовать/перенести в quiet, либо требовать лампу. |
| скрытый `reading.wall` fallback | Непаспортная схема | Добавить `reading.wall_vignette` с полноценным составом или удалить fallback. |
| `decor.corner_plant` | К | Anchor/form верны; min — одно крупное напольное растение/кашпо. |
| `decor.bay_plant` | К | Верно, если не блокируются окно, радиатор, штора и доступ. |
| `bench_under_window` | К | Различать freestanding bench и built-in seat; fail-closed над неизвестным радиатором. |
| `bay_bench` | К/H | Прямая товарная скамья — реализуема; встроенная скамья по форме эркера требует custom geometry и не должна обещаться текущим SKU. |

Практика подтверждает кресло у окна/камина с лампой и приставным столом, пары кресел в эркере и отдельные оконные скамьи: [Architectural Digest — reading nook](https://www.architecturaldigest.com/story/jenny-slate-reading-nook), [Livingetc — reading corners](https://www.livingetc.com/ideas/reading-corner-ideas), [Architectural Digest — window seats](https://www.architecturaldigest.com/gallery/window-seat-ideas).

---

## Дыры из вопроса: мой вердикт

1. **`light` без схем — не дыра канонов.** Торшер в 55% проектов остаётся компаньоном reading/seating/quiet, а не самостоятельной пространственной зоной. `light` лучше оформить как cross-cutting contract: есть ли task/ambient light там, где он нужен. Одиночный торшер ради процента создавать не следует. В практике свет маркирует микрозону рядом с функцией: [Homes & Gardens](https://www.homesandgardens.com/interior-design/how-to-micro-zone-your-home).

2. **`sofa_facing_sofa` — настоящая критическая дыра паспорта.** Код и товары есть, новый placer не нужен.

3. **`media_wall` — дыра трассировки, но не повод сохранять отдельную зону.** Лучше subtype media.

4. **Бар-тележка — реальный, но низкоприоритетный канон**, только при сценарии drinks/entertaining. Частота 7% не делает её обязательной: [Architectural Digest](https://www.architecturaldigest.com/story/bar-cart-ideas), [мини-бар рядом с диваном](https://www.architecturaldigest.com/story/mini-bar-ideas-for-your-home).

5. **Стол/бюро у окна — реальная функция, но не dining fallback.** Нужны `work_need`, роли `desk/work_chair`, место ног, питание и модель бликов. Источник подтверждает размещение рабочего стола у окна, но не наши размеры: [Homes & Gardens](https://www.homesandgardens.com/interior-design/how-to-make-use-of-the-space-in-front-of-a-window).

6. **Растение у окна — настоящая и дешёвая дыра.** Можно реализовать существующим decor placer и ролью `кашпо`, если модель растения входит в визуальный объект.

7. **`entry_zone` — пока opportunity, не функция.** Не создавать схемы ради полноты матрицы. Реальные формы — console/bench/runner — появятся при наличии роли и сценария входа.

8. **Пара кресел у окна/в эркере — настоящая дыра.** Но частота 28% объединяет одиночное кресло и пару: нельзя присваивать все 28% паре.

---

## Ранжированный список добавлений

| Приоритет | Новый/явный канон | Min-состав и условия | Сейчас? |
|---|---|---|---|
| P0 | `seating.sofa_facing_sofa.vis_a_vis` | 2 дивана + центральный столик; обе посадки смотрят в центр | Да, код и каталог есть |
| P0 | `storage.console_behind_sofa` | floating sofa + shallow console; Q8/маршрут | Да, уже работает |
| P0 | `media.wall_unit_centered` | стенка-носитель; связь с осью дивана; storage credit | Да |
| P1 | `reading.window_pair` | 2 одинаковых/согласованных кресла + общая поверхность, окно, свободный доступ | Да при наличии пары; потребуется отдельная гипотеза распределения |
| P1 | `reading.bay_pair` | то же, но обе позиции внутри эркера | Да для достаточно широкого bay |
| P1 | `decor.window_plant` | растение/кашпо у окна, не блокирует створку, радиатор и шторы | Да |
| P1 | `reading.wall_vignette` | кресло + task light + приставной стол | Да; либо убрать текущий скрытый fallback |
| P2 | `dining.window_table` | dining need + стол около окна, но не перекрывает радиатор/створку | Геометрически да; сначала shadow |
| P2 | `seating.open_center` | посадка + ковёр + доступные боковые поверхности, намеренно без coffee table | Да, но нужен явный сценарий/причина, иначе это деградация |
| P2 | `seating.nesting_tables` | сертифицированный комплект либо согласованная группа малых столов | Нет: нужен capability/комплектность |
| P2 | `work.window_desk` | desk + work chair + task light; питание, блики, место ног | Нет: новые роли и scenario need |
| P3 | `storage.window_low_console` | низкий корпус ниже подоконника, без радиатора | Нужны caps высоты/глубины и radiator policy |
| P3 | `serving.bar_cart` | тележка у dining/seating, только drinks/entertaining need | Нужна роль и каталог |
| P3 | `entry.console/bench/runner` | явный входной opportunity и соответствующий инвентарь | Пока не нужно |

Свободный центр и nesting tables — реальные практические решения, но не должны включаться ради статистической квоты. Источник подчёркивает и необходимость negative space, и применение малых/nesting tables: [Homes & Gardens — perfect living-room layout](https://www.homesandgardens.com/interior-design/the-library-how-to-design-the-perfect-living-room-layout).

---

## Приоритет известных дефектов

1. **P0: resolved canon ID и честный coverage gate.**  
   Проверять `(group_id, shape)`, уникальность ID/файла, соответствие emitted `tpl_variant` паспорту. Без этого остальные метрики ненадёжны.

2. **P1: tandem certificate и right-first bias.**  
   Одна зеркальная семья; обе стороны детерминированно пробуются; tandem допускается только после недостижимости pair-sides/U/media-bridge. Текущие 23 против 5 очень похожи на порядок каскада, а не на свойство комнат.

3. **P1: семантическая граница `media_parallel`.**  
   Общий hard-конус 45° можно сохранить как предел валидности, но scheme `parallel` ограничить до 30°. Интервал 30–45° должен называться `media_half`. Иначе артефакт сообщает более сильную семантику, чем гарантирует геометрия.

4. **P2: зеркала окна ±30° и сторона лампы.**  
   Пробовать обе ориентации. При неизвестной ведущей руке не фиксировать сторону торшера как норму; выбирать по бликам, теням, доступу и коллизиям.

5. **P2: `square_r`.**  
   Само зеркало уже добавлено; теперь важнее объединить обе стороны под одним form и проверить reflection-invariance.

6. **P3: `dining_foldable`.**  
   Оставить sleeping, пока не разделены extendable и drop-leaf и нет open/closed dimensions. `anchor=unresolved` для паспорта недопустим.

---

## Что объединить, переименовать или убрать

Объединить:

- `tandem_r/l` → `side_pair`, mirror;
- `L_left/right` → `two_sofa_l_joint`, mirror;
- `square/square_r` → `three_sided_conversation`, mirror;
- `media_storage_combo/install­ation` → `freestanding_media_storage_run`;
- `media_mirror` → вариант `media_centered`;
- `fireplace.solo` и `fireplace_solo.solo` → одна схема;
- `bay_armchair` → окончательно в `reading.bay_anchor`;
- `media_wall` → subtype внутри media.

Переименовать:

- `floating_pair` → `floating_sofa_opposite_media`;
- `facing` → `armchair_pair_opposite_sofa`;
- `bulky` → `deep_armchairs_opposite`;
- `quiet_chat` → `paired_conversation`.

Перевести в fallback/shadow до сертификата:

- `tandem`;
- `bulky`;
- `bridge`, если нет подтверждённого target/facing-контракта;
- `media_corner` и `media_at_jamb`.

Оставить sleeping:

- `tv_over_fireplace`;
- `media_builtin`;
- `dining_foldable`;
- `storage_zone_divider`.

Не создавать:

- отдельный канон одиночного торшера;
- каноны entry только ради заполнения матрицы;
- custom built-in bay seat из обычной прямой товарной банкетки.

---

## Минимальные машинные гейты

1. Каждая placement-группа в артефакте имеет уникальный `resolved_canon_id`; для active placement нет `unknown/default` без `group_id`.

2. Coverage проверяет не множество `shape`, а все допустимые `(zone, group_id, shape)`.

3. У карточек уникальны ID и пути; лишняя карточка без паспорта и паспорт без карточки запрещены.

4. Каждый active scheme содержит:

   - `function`, `anchor`, `form`;
   - `required_roles`, `optional_roles`;
   - `when`, `invariants`;
   - структурированный `provenance[]` и `status`;
   - допустимые soft-нарушения.

5. Для зеркальных форм: отражённая сцена должна давать отражённый эквивалент, а не систематически правый вариант.

6. После добавления канона: прежние floor-гейты, `TIMEOUT=0`, p95 и слепые пары. Частоты практики остаются shadow-диагностикой, не квотой.

Главный риск — начать добавлять формы до этой нормализации: beam станет дороже, карточек станет больше, но нельзя будет доказать, что солвер действительно использует показанный владельцу канон.
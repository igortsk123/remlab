Итог: базовый репертуар у нас уже широкий, но покрытие переоценено. Главные реальные дыры — медиапригодная богатая посадка, несколько полноценных зон в large, nook/round dining, консоль/делитель и честная геометрия специальных SKU. Статусы ниже — на сегодня: подготовленный Q3-патч ещё не считается реализованным.

Практика — это репертуар, не набор обязательных правил. Внешняя база: типы sectional L/U/chaise и консоль за ним — [Room & Board](https://www.roomandboard.com/ideas-advice/design-your-space/living/sectional-ideas); классические парные диваны, sofa+2 chairs, chaise-разделитель — [Houzz](https://www.houzz.com/magazine/lay-out-your-living-room-floor-plan-ideas-for-rooms-small-to-large-stsetivw-vs~11333443); несколько групп в большой комнате — [Homes & Gardens](https://www.homesandgardens.com/interior-design/the-library-how-to-design-the-perfect-living-room-layout) и [Architectural Digest](https://www.architecturaldigest.com/story/how-to-arrange-furniture-in-open-space). Для dining/nook — [IKEA](https://www.ikea.com/sg/en/rooms/dining/3-tips-for-buying-a-dining-table-pubdd7aaa20/) и [Houzz](https://www.houzz.com/magazine/no-room-for-a-dining-area-install-a-banquette-stsetivw-vs~72943424); для делителей — [Wallpaper](https://www.wallpaper.com/design-interiors/furniture/colin-king-audo-crescent-bookcase-design); для TV/fireplace — [Houzz](https://www.houzz.com/magazine/7-ways-to-rock-a-tv-and-fireplace-combo-stsetivw-vs~5176882).

Локальная база сравнения: [seating_groups](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:8), [паспорта зон](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:57), [build_block/place_*](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:518), [выгрузка каталога](/home/pakar/igor/remlab/.memory_bank/_intake/catalog-extract-nook.txt:1).

## 1. Независимая матрица

### Посадка / отдых

| Вариант в практике | Типовой состав | У нас сегодня | Что нужно / товары |
|---|---|---|---|
| Диван соло | диван, столик, ковёр, свет | Есть: `sofa_solo`, `sofa_lamp` | Товары есть |
| Диван + одно кресло | диван, кресло, столик, ковёр | Частично: `sofa_armchair`; кресло пока не media-aware | Q3 `media_parallel/media_half`; товары есть |
| Угловой + кресло | L-sectional, кресло, столик | Есть состав, частична функция: `sectional_armchair` | Q3 media-поворот |
| Диван + пара кресел по бокам / открытая U | диван, два кресла, столик, ковёр | Частично: `default/u`, но текущие повороты не решают цель №3 | Q3 `media_bridge/pair_sides`; товары есть |
| Диван ↔ два кресла | кресла напротив дивана | Есть `facing/bulky`, но это conversation-first, не TV-primary | Оставить отдельным intent |
| Два дивана визави | два дивана, столик, ковёр | Есть `sofa_facing_sofa`, намеренно без ТВ | Не менять семантику |
| Два дивана буквой L | основной диван + второй диван/loveseat | Геометрически есть под именем `sofa_loveseat` | Нужен честный subtype: сейчас «диван 2» не гарантирует loveseat |
| Два дивана + два кресла | квадрат/U вокруг столика | Частично: два group-id используют одну L-геометрию; `square` складывает кресла с одной стороны | Q3 отдельные `two_sofa_media` и `pair_sides` |
| Sectional + два кресла | L-sectional, парные кресла напротив/по сторонам | Нет | Создать в Q3; товары есть |
| Диван + пуф/крупная оттоманка | пуф как footrest или стол | Есть `sofa_pouf`, `pouf_table` | Проверять реальную функцию пуфа |
| Пара кресел / тихий pod | два кресла, малый стол, иногда ковёр | Есть `armchair_pair`, `quiet`, но quiet только face-to-face | Расширить в Q5 |
| Четыре кресла вокруг стола/оттоманки | conversation/game pod | Нет | Низкий приоритет Q5; кресла есть, отдельного game-table контракта нет |
| Несколько самостоятельных групп | main TV group + quiet/fireplace/read pod | Частично: только узкий `quiet` | Главная дыра Q5 |
| Chaise/daybed как лёгкий разделитель | кушетка/шезлонг, столик, свет | Нет capability и шаблона | 152 кушетки, 42 размерных кандидата; Q6a, затем отдельный пакет |
| U/curved sectional одним SKU | модульный U/криволинейный диван | Нет: модель умеет только прямой/L-полигон | В категориях есть 62 П‑образных и 308 модульных, но нужна новая геометрия; высокая сложность |

### Медиа-зона

| Вариант | Состав | У нас | Решение |
|---|---|---|---|
| Базовая TV-консоль | ТВ + низкая тумба, иногда кашпо | Есть `media_centered/mirror` | Довести axis/scale по Q2/Q4 |
| Полноценная стенка с нишей | TV wall unit | Есть `media_wall` | Товаров 479 |
| ТВ + парные шкафы/стеллажи | центральный носитель + 2 фланга | Частично `media_installation`, только large | Исправить паспорт small/large; гейт масштаба |
| Мягко сбалансированная стена | слева закрытое хранение, справа открытое/декор | Нет отдельной композиции | Создать `media_installation_balanced` в Q6 |
| Асимметричная TV-стена | ТВ со смещением + весомый фланг | Частично: отдельный storage не образует атома | Вариант того же Q6-шаблона |
| TV-консоль + настенные полки | тумба, навесные полки | Только тумба; 201 полка не планируется в 2D floor layer | Скорее host/render layer, не новый floor-template |
| ТВ + камин рядом | side-by-side на одной стене | Код есть `media_fireplace`, паспорта нет | Добавить паспорт и reachability-гейт |
| ТВ над камином | вертикальная композиция | Нет | Не включать без типа камина, тепловых отступов и высоты ТВ: производители требуют сверяться с конкретными manual/specs ([Heatilator](https://www.heatilator.com/shopping-tools/articles/can-i-mount-a-tv-over-my-fireplace)) |
| Угол / косяк / между окнами | fallback для сложной архитектуры | Есть | Оставить fallback |
| Скрытый TV / TV в шкафу | двери, подъёмник, art-TV | Нет состояния товара | Вне v7 |

### Обеденная зона

| Вариант | Состав | У нас | Решение / товары |
|---|---|---|---|
| Свободный остров | стол, стулья вокруг | Есть | База |
| Компактный круг/овал | круглый стол, 2–4 стула | Спящий паспорт; квадратный bbox | Q6d; 7 подтверждённых круглых ≤110 см |
| Голый стол одной стороной к стене | стол, стулья только с доступных сторон | Частично `edge` | Добавить `wall_contact_sides`, доступность стульев и сертификат island-infeasible |
| Прямая банкетка/nook | банкетка у стены, стол, стулья со свободных сторон | Нет | Q6b/c; есть 17 банкеток, 42 кушетки-кандидата и 3 скамьи |
| L-банкетка в углу | угловая банкетка, pedestal table, стулья | Нет | Явных товаров/capability нет; после straight nook, не сейчас |
| Складной/drop-leaf | стол с двумя геометрическими состояниями | Спит | Есть 8 компактных кандидатов, но нет доказанных состояний; не активировать |
| Стол за диваном | обычный island/edge в регионе за floating sofa | Частично достижим | Это топология кандидата, не новый предметный шаблон |
| Café table на двоих | малый стол + 2 стула | Покрывается каскадом dining на 2 места | Отдельный шаблон не нужен |

Минимум 80 см от стола до препятствия даёт IKEA; при проходящем за сидящим трафике NKBA рекомендует больше — 91/112 см в зависимости от сценария ([NKBA](https://media.nkba.org/uploads/2022/05/Kitchen-Planning-Guidelines.pdf)). Поэтому edge допустим, но не как автоматический эквивалент острова.

### Хранение / делители / остаток

| Вариант | У нас | Решение / товары |
|---|---|---|
| Пристенный стеллаж/комод/витрина | Есть `storage_perimeter/shallow` | Товаров много |
| Второй ряд хранения на другой стене | Частично есть | Паспортный `max_zones_per_room` код не читает |
| Низкая консоль за floating sofa | Нет | Q6e; 572 размерных кандидата глубиной 25–45 см требуют capability-фильтра |
| Низкий открытый стеллаж-делитель | Спящий `storage_zone_divider` | Q6a capability `open_back/finished_back`, затем Q6e/Q6f |
| Высокий открытый делитель | Нет активной реализации | Только с доказанным сохранением света/маршрута; generic «стеллаж» недостаточен |
| Библиотечная/built-in стена | Только обычный ряд или media wall | Архитектурное встроенное изделие — вне товарного шаблона |
| Экран/ширма/двусторонний камин | Нет подходящего товара/геометрии | Вне v7 |

### Тихая / чтение / эркер

| Вариант | У нас | Решение |
|---|---|---|
| Кресло + торшер + приставной | Есть `reading` | База |
| Кресло + оттоманка + свет | Частично: код не собирает все аксессуары одновременно | Исправить вариант, если нужен по Q5 |
| Пара кресел + малый стол | Есть только face-to-face `quiet` | Q5: добавить angled/side-by-side по фактическому фокусу |
| Малый диван/кушетка как quiet pod | Нет | Q6a capability; полезно для длинных rooms |
| Одиночное кресло в эркере | Есть `bay_armchair` | База |
| Настоящее window seat/скамья в эркере | Нет | `bay_armchair` этим не является; нужен bench capability и новый шаблон |
| Game/card pod на 2–4 места | Нет | Низкий приоритет; не переименовывать обеденный стол |

Типовой reading nook действительно строится из кресла, света, столика/оттоманки; bay window seat — отдельный тип, а не синоним кресла в эркере ([Homes & Gardens: reading](https://www.homesandgardens.com/celebrity-style/reese-witherspoon-reading-nook), [bay window seat](https://www.homesandgardens.com/interior-design/living-rooms/small-living-room-layout-ideas)).

### Камин

| Вариант | У нас | Решение |
|---|---|---|
| Камин соло | Есть `fireplace_solo` | Оставить |
| Камин + парные стеллажи/растения | Есть `build_fireplace` | Добавить явные схемы в паспорт |
| Камин + два кресла под углом | Есть через `кресло 3/4` | Формализовать intent и конкуренцию с quiet |
| Главная посадка ориентирована на камин | Частично: камин ищется в поле зрения готовой посадки | Нужна явная fireplace-primary гипотеза только для `media_need=off/preferred` |
| ТВ и камин side-by-side | Есть кодом | Добавить паспорт |
| ТВ и камин на соседних стенах + swivel chairs | Нет явного семейства; swivel capability отсутствует | Отложить до данных |
| Угловой камин | Кандидаты есть | Оставить fallback |
| ТВ над камином | Нет | Не создавать сейчас |
| Двусторонний камин-разделитель | Не моделируется | Архитектурный scope, не мебельный шаблон |

## 2. Расхождения с таблицей первичного агента

Таблица полезна по направлению, но в пяти местах слишком оптимистична:

- `media_bridge` и прочие Q3-формы помечены почти как «есть» ([строка 13](/home/pakar/igor/remlab/.memory_bank/_intake/zones-practice-vs-ours-agent.md:13)). Сегодня их нет; текущий `bridge` разворачивает кресла 135°/225° и не выполняет цель №3.
- `media_fireplace` объединяет side-by-side и TV-above-fireplace ([строка 32](/home/pakar/igor/remlab/.memory_bank/_intake/zones-practice-vs-ours-agent.md:32)). Реализован только side-by-side.
- `bay_armchair` назван window seat ([строка 22](/home/pakar/igor/remlab/.memory_bank/_intake/zones-practice-vs-ours-agent.md:22)). Это кресло в нише; встроенная скамья отсутствует.
- `media_installation` не гарантирует «одинаковое симметричное хранение»: код может поставить один фланг либо два разных предмета.
- `fireplace_flank in bridge` ([строка 19](/home/pakar/igor/remlab/.memory_bank/_intake/zones-practice-vs-ours-agent.md:19)) в коде отсутствует: `bridge` — форма основной посадки, а каминные кресла строит отдельно `build_fireplace`.
- `sofa_loveseat` — пока только имя ступени: «диван 2» не имеет подтверждённой семантики loveseat.
- «Стол за спинкой» не обязательно требует нового build-template: нужен явный topology/candidate для существующего dining-блока.

Упущены:

- sectional + два кресла;
- реальный U-sectional как SKU;
- четыре кресла/game pod;
- различие single bay chair и built-in window bench;
- отдельный раздел quiet/reading;
- fireplace-primary и TV/fireplace на разных фокусах;
- hidden TV как существующий в практике, но сознательно откладываемый вариант;
- отсутствие capability для swivel/open-back/finished-back/stateful furniture.

Лишнее для текущей цели:

- числа «18–22 ft → две зоны», «>22 ft → три» и «50″ между зонами» нельзя переносить в rules как общепринятые пороги: найденные сильные источники подтверждают принцип нескольких зон, но не универсальные границы;
- bar/work zone — расширение продуктового scope;
- «два ковра», парные лампы и парные side tables не должны становиться отдельными атомарными шаблонами;
- conversation circle и L-банкетка полезны в каталоге практик, но не должны задерживать v7.

## 3. Что создавать по приоритету

| Приоритет | Пакет | Шаблон/изменение | Польза | Сложность | Цели |
|---|---|---|---|---|---|
| P0 | Q3 | `media_parallel`, `media_half`, `media_bridge` с проверкой к фактическому ТВ | Очень высокая | Низкая–средняя | 2, 3, 8, 13 |
| P0 | Q3 | `sectional_2armchairs_media`, `pair_sides`, отдельный `two_sofa_media`; убрать подмену богатых схем one-side square | Очень высокая | Средняя | 3, 6, 7, 14 |
| P0 | Q5 | Семейство `simple_main + quiet_pair/read/fireplace pod`, с собственной beam-квотой | Очень высокая | Средняя | 6, 8, 9, 14 |
| P0 | Q6b/c | Прямой `edge_nook` | Очень высокая | Средняя | 5, 9, 12, 13 |
| P0 | Q6d | `round_compact` с круговой геометрией | Высокая | Средняя | 5, 9, 12 |
| P0 | Q6e | `console_behind_sofa` | Высокая | Средняя | 4, 6, 9, 14 |
| P1 | Q6a+e | `media_installation_balanced/asymmetric` | Высокая | Средняя | 2, 4, 9 |
| P1 | Q6a+f | `storage_divider_low/open` с доказанной capability | Средняя–высокая | Высокая | 6, 9, 14 |
| P2 | после core | `bay_window_bench` / chaise quiet pod | Средняя | Высокая | 6, 9 |
| P2 | отдельный geometry-пакет | U/curved sectional SKU | Высокая для large, узкое покрытие | Очень высокая | 6, 7, 14 |

Минимальные гейты:

- Q3: для каждого богатого семейства — `declared → block_generated → full_chain_valid → compared`; tandem/one-side допустим только с сертификатом недостижимости `pair_sides/U/two_sofa_media`.
- Q5: при 40+ м² и подходящем банке существует hard-valid `main+pod` либо терминальная причина; проверяется не только выбранный план, но и достижимость.
- Q6: nook никогда не заменяет валидный island; round считается окружностью; console ставится только за floating sofa при сохранённом проходе; divider — только SKU с подтверждённой двусторонностью.

То есть текущий [MASTER-zones-v7](/home/pakar/igor/remlab/.memory_bank/plans/MASTER-zones-v7.md:114) менять радикально не надо. Я бы добавил в Q3 `sectional_2armchairs/two_sofa_media`, в Q5 — варианты второго pod, в Q6 — balanced media wall и capability делителя. Остальной дизайнерский репертуар оставить в backlog, чтобы не размыть основную цель владельца.
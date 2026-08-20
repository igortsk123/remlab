## Вывод

Направление владельца верное: качество расстановки действительно определяется не абстрактной связкой предметов, а связкой **функция × архитектурный/предметный якорь × форма композиции**.

Но предложенную архитектуру нельзя вводить буквально:

- Не нужен второй параллельный объект `Situation`: его роль уже почти выполняет `opportunity`. Нужен типизированный экземпляр возможности с устойчивым ID.
- Нельзя делать полный декартов `function × anchor`: большинство клеток бессмысленны. Нужен реестр только заявленных применимых сочетаний.
- Текущий `practice_prior_key` нельзя включать: сумма рангов — это скрытая аддитивная система весов.
- Сертификат должен быть единым журналом результата, но не новым монолитным оркестратором поиска.
- Все семь sleeping-схем одновременно «разбудить» честно нельзя. Три доступны геометрически, четыре требуют новых товарных или инженерных данных.

## A. Критика архитектуры

### Что принять

1. Канон должен иметь разрешённое представление:

   `function=reading → anchor=window → form=single_armchair_angled`.

2. В артефакте нужны:

   - `opportunity_id`;
   - `scheme_id`;
   - `anchor_type` и `anchor_ref`;
   - `form`;
   - применённые qualifiers;
   - кандидаты и причины отказа;
   - выбранный исход;
   - версия правил и приора.

3. Каноническая галерея должна строиться из тех же resolver/placer/validator, что production. Нынешний gate проверяет лишь наличие карточки у активной схемы и пропускает sleeping-схемы; семантику якоря он не проверяет: [canon_gallery.py:635](/home/pakar/igor/remlab/tools/scout/canon_gallery.py:635).

### Что изменить

Список «ситуаций» сейчас смешивает разные уровни:

| Уровень | Примеры |
|---|---|
| Архитектурный якорь | окно, эркер, угол, участок стены, центр комнаты |
| Предметный якорь | камин, диван, носитель ТВ |
| Отношение | между окнами, за диваном |
| Ограничение | радиатор под окном, стена с дверью |
| Форма постановки | floating, wall-backed, diagonal |

Поэтому правильная модель:

```text
Opportunity
  id
  anchor_type: window | bay | corner | wall_segment | room_center | object
  anchor_ref
  qualifiers: radiator_overlap, between_openings, door_adjacent...
  applicable_functions
  candidates
  outcome
```

`behind_sofa` — не равноправный тип комнаты, а предметно-зависимая возможность, возникающая после размещения дивана. Аналогично `fireplace_anchor`.

Функцию не стоит дублировать в каждой схеме: она уже задана родительской зоной `reading`, `storage`, `media`. В исходном JSON достаточно обязательных `anchor` и `form`, а полный тройной паспорт можно выдавать в разрешённом экспорте.

### Матрица покрытия

Полный декартов гейт не нужен: он заставит документировать бессмысленные `dining×fireplace`, `media×free_corner` и создаст сотни фиктивных клеток.

CI должен проверять:

1. Каждая схема имеет допустимые `anchor`, `form`, состав, статус и provenance.
2. Каждая объявленная применимой клетка имеет `implemented` либо `sleeping` с конкретным blocker.
3. У активной схемы есть resolver, синтетическая сцена, карточка галереи и validator contract.
4. Необъявленные сочетания считаются `not_applicable`, без ручного перечисления всего декартова произведения.

Сейчас тест требует фактически только префикс `implemented|sleeping`: [test_passport_parity.py:20](/home/pakar/igor/remlab/services/planner-solver/tests/test_passport_parity.py:20).

### Детерминизм и сертификат

Сейчас ID окна зависит от порядка входного массива — `window:{wall}:{i}`: [opportunities.py:151](/home/pakar/igor/remlab/services/planner-solver/planner/opportunities.py:151). Нужно либо upstream-ID проёма, либо ID из канонически отсортированной геометрической сигнатуры `(wall, offset, width, sill)`.

Попытки сейчас адресуются только по `kind`, поэтому два окна или несколько углов невозможно объяснить независимо: [opportunities.py:125](/home/pakar/igor/remlab/services/planner-solver/planner/opportunities.py:125).

Сертификат должен проецировать фактический search trace:

```text
applicable → inventory_eligible → block_feasible
→ full_chain_attempted → full_valid → selected
```

Он не должен повторно запускать solver. Полные цепочки остаются под существующим beam-cap; возможности сначала проходят дешёвый фильтр применимости и локальной геометрии.

## B. Как связывать приоры с ключом

Текущий вариант production включать нельзя.

`practice_prior_key()` суммирует ordinal-ранги разных возможностей: [opportunities.py:208](/home/pakar/igor/remlab/services/planner-solver/planner/opportunities.py:208). Это скрытая взвешенная сумма с весом 1: плохой исход у окна может компенсироваться углом, а комната с четырьмя углами получает другой масштаб цели.

Кроме того, `prior_would_choose` сортирует кандидатов только по приору, не сохраняя равенство верхних ярусов: [zones.py:2002](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:2002). Поэтому нынешний shadow не моделирует безопасное будущее включение.

Правильный вариант:

1. Выделить именованный prefix ключа до конца `zone_quality`.
2. Приор применять локально, только если:

   - prefix полностью равен;
   - required-зоны и вместимость равны;
   - планы различаются исходом одной и той же возможности;
   - оба исхода full-valid и достижимы.

3. Затем сравнивать `prior_rank`.
4. После него — нынешняя эстетическая часть и стабильный технический tie-break.

Не суммировать ранги окон и углов. Если планы меняют сразу несколько возможностей, на первом этапе приор не должен выбирать победителя. Позже возможен лексикографический вектор по стабильному порядку возможностей, но этот порядок сам станет новой продуктовой политикой.

Важно: фраза «порядок ключа не меняется» неточна. Вставка приора перед aesthetics меняет выбор. Верхние контракты остаются неизменными, но изменение ключа должно быть отдельным ADR.

Частоты также нельзя трактовать как целевые распределения. Ранг 28/19/17 означает лишь порядок распространённости. Детерминированный one-best solver будет выбирать первый исход во всех равных случаях, а не воспроизводить доли 28/19/17.

### Протокол слепой проверки

- Заморозить код, банки, правила и набор кандидатов.
- Показывать только пары, где верхний prefix одинаков, а приор меняет исход.
- Одинаковый рендер, скрытые A/B, случайная сторона.
- Стратификация: окно/угол/центр; small/large; эркер/радиатор; все прежние замечания владельца плюс holdout реальных комнат.
- 10–15% пар повторить с переставленными сторонами.
- Ответ: A / B / равно / оба неприемлемы + причина.
- Заранее определить гейт, например ≥60% побед приор-версии среди нетайных пар, без роста «оба неприемлемы», при сохранении экзаменационных floors и p95.

Это проверит предпочтение владельца, но не докажет универсальную статистическую норму.

## C. Нужна ли отдельная сущность `Situation`

Нужен отдельный **runtime-экземпляр**, но не новая параллельная иерархия.

Рекомендую:

- `RoomMap` — архитектурные факты;
- `Opportunity` — типизированный экземпляр ситуации;
- `templates.json` — схема с `anchor` и `form`;
- search trace — какие схемы попробованы;
- certificate — сериализованное объяснение результата.

Текущий `RoomMap` хранит стены, маршруты, эркеры и колонны, но не универсальные якоря: [room_map.py:52](/home/pakar/igor/remlab/services/planner-solver/planner/room_map.py:52). Расширять его всеми предметно-зависимыми ситуациями нельзя: `behind_sofa` ещё не существует до постановки дивана.

Пороговые `WINDOW_ZONE_DEPTH_CM`, `CORNER_BOX_CM`, `CENTER_REACH_CM` сейчас зашиты в код без provenance: [opportunities.py:23](/home/pakar/igor/remlab/services/planner-solver/planner/opportunities.py:23). Их нужно перенести в rules JSON независимо от рефакторинга.

Ещё один симптом дрейфа: исход `window_seat_bench` до сих пор привязан к `edge_nook`, хотя зона `window_seat` уже существует: [practice_priors.json:21](/home/pakar/igor/remlab/tools/scout/rules/practice_priors.json:21). Исход следует определять по фактическому `tpl_id/anchor`, не по первой встретившейся роли в полосе.

## D. Как закрепить направление в памяти

Не переписывать ADR-0110 задним числом. Создать ADR-0112:

**«Situational canon: function × opportunity-anchor × form; приоры только локально и в тени»**.

В ADR зафиксировать:

- онтологические уровни;
- `Opportunity` как единственный экземпляр ситуации;
- отсутствие полного декартова покрытия;
- локальный prior tie-break вместо суммы;
- rollout `schema → correct shadow → blind pairs → production`;
- отвергнутые варианты: глобальная сумма рангов, вероятностный выбор, роли-в-полосе, новый полный solver на сертификат.

Далее:

- `source-of-truth.md` — одна жёсткая норма про ситуационный паспорт и запрет глобальной суммы приоров;
- `core/layout.md` — поток `room_map → opportunity → applicable schemes → search trace → certificate`;
- `project-state.md` — что уже реально внедрено, что пока shadow;
- `anti-patterns.md` — сумма ordinal-рангов, частота как квота, полный Cartesian matrix, нестабильные IDs, повторный solve ради сертификата;
- `MASTER-zones-v7.md` — отдельный Q12 с пакетами и гейтами;
- `INDEX.md` — ссылки на ADR и новый пакет.

## E. Семь sleeping-схем

| Схема | Можно сейчас честно? | Нормы и необходимые данные | Рекомендация |
|---|---|---|---|
| `media.tv_over_fireplace` | **Нет, не в общем случае** | Samsung указывает риск превышения 40 °C и слишком высокой линии взгляда; производители каминов задают разные зазоры по конкретной модели и heat-management kit. Например, Heat & Glo допускает 12″ только для определённых систем, а не как общую норму. [Samsung](https://www.samsung.com/au/support/tv-audio-video/things-to-consider-before-mounting-the-tv-on-a-wall/), [Heat & Glo](https://www.heatnglo.com/ideas/tv-or-fireplace-both-please) | Последней. Нужны тип/модель камина, верх топки, mantel и его вылет, thermal profile/допустимый TV clearance, размер экрана, центр и наклон ТВ. Без этого только `sleeping`; возможен узкий allowlist сертифицированных комбинаций. |
| `media.media_builtin` | **Нет как комбинация произвольных SKU** | Встройка вокруг ТВ — устойчивая практика, но числовой универсальной нормы нет; важны система и совместимость модулей. [AD](https://www.architecturaldigest.com/story/living-room-furniture-layout-maximizes-small-space), [Homes & Gardens](https://www.homesandgardens.com/interior-design/tv-stand-ideas) | Нужны `system_id/collection_id`, совместимые модули, отделка, цоколь, глубины, фасадная плоскость, правила стыковки и кабелей. Текущая `media_installation` честно остаётся отдельными корпусами: [templates.json:230](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:230). Custom millwork лучше экспортировать как downstream design intent, а не притворяться SKU-комплектом. |
| `dining.dining_foldable` | **Не production; сбор данных можно начать сейчас** | Утверждение «в каталоге нет» уже устарело: локальная выгрузка содержит несколько «Стол раскладной»: [catalog-extract-nook.txt:63](/home/pakar/igor/remlab/.memory_bank/_intake/catalog-extract-nook.txt:63). Но название не доказывает пригодность сложенного состояния. Производители публикуют min/max размеры и число мест, например [IKEA VIHALS](https://www.ikea.com/us/en/p/vihals-extendable-table-white-90569097/). | Разделить `extendable dining` и настоящий fold-down/console. Нужны `closed_w/d`, `open_w/d`, места в каждом состоянии, рабочее состояние, envelope раскладывания. Solver не должен менять SKU: выбранное состояние — явная feed-backed конфигурация в артефакте. |
| `storage.storage_zone_divider` | **Нет через текущий role allowlist** | Открытая полка как делитель действительно сохраняет свет и sightlines. [Homes & Gardens](https://www.homesandgardens.com/interior-design/how-can-i-divide-a-room-with-furniture). Но высокую мебель требуется закреплять; это отдельный safety-контракт. [CPSC](https://www.cpsc.gov/Safety-Education/Safety-Education-Centers/AnchorItgov). Даже KALLAX одновременно рекламируется как divider и снабжается инструкцией крепления: [IKEA guide](https://www.ikea.com/us/en/files/pdf/3b/6c/3b6c9616/kallax_jan_2022_np.pdf). | Не переносить всю роль `стеллаж` в `room_divider_capable_active`: [occupancy.json:937](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:937). Нужны SKU-capabilities: finished back, manufacturer-approved freestanding/divider use, open fraction, anchoring mode, устойчивость. Якорь — граница двух реально существующих зон, не «периметр не сработал». |
| `storage.corner_tower` | **Геометрию — да; все высокие SKU — нет** | Угловое вертикальное хранение — практика, но универсального отступа нет; безопасность высокой мебели требует anchoring. [Homes & Gardens](https://www.homesandgardens.com/solved/things-organized-people-have-in-their-living-rooms), [CPSC](https://www.cpsc.gov/Safety-Education/Safety-Education-Centers/AnchorItgov) | Добавить в `place_storage` wall-candidates, примыкающие к углу, а не диагональный `_corner_candidates`: паспорт требует корпус вдоль одной стены. Проверять фасадный доступ, дверь/окно/маршрут и выдавать `installation_requirement=wall_anchor` для высокой мебели. |
| `window_seat.bench_under_window` | **Только в узком fail-closed варианте** | Window seat подтверждён практикой; высота обычно близка обычному стулу. [Livingetc](https://www.livingetc.com/ideas/window-seat-ideas), [AD](https://www.architecturaldigest.com/gallery/window-seat-ideas). Accessible-bench 43–48.5 см высотой и 51–61 см глубиной — полезный эргономический ориентир, но не универсальная жилая норма. [U.S. Access Board](https://www.access-board.gov/ada/ada-ibc-comparison/chapter-9/). Радиатор нельзя закрывать произвольной лавкой; рекомендации обычно требуют 15–30 см и зависят от прибора. [BestHeating](https://www.bestheating.com/info/faqs/can-you-put-furniture-in-front-of-a-radiator/) | Сейчас активировать лишь при отсутствии радиатора и доказанном `window_seat_capable`. Нужны отдельно seat height/depth и overall height. Текущий `wall_seat_capable d≤45` создан для банкетки столовой и не должен автоматически означать полноценный lounge-window-seat: [capabilities.json:34](/home/pakar/igor/remlab/tools/scout/rules/capabilities.json:34). |
| `window_seat.bay_bench` | **Частично** | Эркер — канонический якорь window seat. [AD](https://www.architecturaldigest.com/gallery/window-seat-ideas). Но прямая товарная скамья внутри эркера и заказная встроенная скамья по его контуру — разные продукты. | Сейчас можно реализовать только `freestanding_straight_bench_in_bay`: полностью внутри bay, лицом в комнату, без радиатора. Настоящий fitted bay bench оставить sleeping до контурной геометрии изделия/custom-millwork режима и данных окна. |

`Radiator` сейчас не содержит высоту или тип, только стену, ширину и глубину: [models.py:41](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:41). `Opening` не описывает тип и траекторию открывания оконной створки. Поэтому исключение «можно над батареей» невозможно сертифицировать честно.

## Рекомендуемый порядок работ

1. **Q12-0 — ADR и термины.** Зафиксировать ontology и границы сущностей.
2. **Q12-1 — типизированный Opportunity.** Стабильные ID, qualifiers, пороги в rules JSON, классификация по `tpl_id/anchor`.
3. **Q12-2 — исправить shadow-приор.** Локальный counterfactual только при равном верхнем prefix; удалить сумму рангов и ложный `prior_would_choose`.
4. **Q12-3 — гейты библиотеки.** Схема → resolver → synthetic scene → validator → canon card → certificate.
5. **Q12-4 — малорисковые схемы:** ограниченный `corner_tower`, `bench_under_window` без радиатора, прямая скамья в эркере.
6. **Q12-5 — данные каталога:** состояния столов; per-SKU divider capability.
7. **Q12-6 — системы:** media built-in только после compatibility graph.
8. **Q12-7 — вертикальная инженерия:** TV over fireplace последним и только по сертифицированным профилям.

Гейты: идентичный результат при перестановке openings/банка; ни одного prior-flip при различном верхнем prefix; сертификат точно ссылается на выбранную схему и якорь; TIMEOUT 0, прежние floors, p95 не выше согласованного лимита; новые opportunities не добавляют повторных full-chain прогонов.

## Главные неопределённости

- Неизвестны выборка, география и условные разрезы процентов владельца — это честно записано в [practice_priors.json:4](/home/pakar/igor/remlab/tools/scout/rules/practice_priors.json:4).
- Не определено, что продукт считает «встройкой»: покупной модульный комплект или заказную столярку.
- Нет данных о створках окон, типах радиаторов и тепловых профилях каминов.
- Не решено, является ли wall anchoring частью гарантии layout-солвера или обязательной пометкой монтажнику.

Вывод изменили бы: надёжные условные данные практики, стабильные upstream-ID архитектурных элементов, manufacturer compatibility для модулей, явные состояния столов и вертикально-тепловая модель камина. До этого приоры должны оставаться shadow, а инженерно недоказанные схемы — sleeping.
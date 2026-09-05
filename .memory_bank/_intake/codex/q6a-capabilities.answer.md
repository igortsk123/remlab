Вердикт: направление правильное — отдельная capability-проекция без изменения `cat_role`. До реализации я бы поправил четыре вещи: tri-state вместо булевых догадок, разделение seat/overall dimensions, отделение capability от slot-envelope и корректную дельту после асинхронного enrich.

1. Пороги и эвристики

- Не смешивать `seat_depth_cm` с `products.d_cm`, а `seat_length_cm` — с `w_cm`. Хранить отдельно `overall_*` и `seat_*`. Общие размеры годятся для footprint, но не доказывают эргономику сиденья.

- `seat_height_cm` — только точный параметр. Категориальное `specific.seat_height=средняя` хранить как `seat_height_class`, не переводить в сантиметры. Общую `h` можно использовать лишь для явно backless-предмета: тогда `h≈seat_height`, с `confidence=medium`.

- Для dining: preferred `43–48`, hard `42–49` см. Текущий внутренний ориентир уже 43–48 ([occupancy.json:740](/home/pakar/igor/remlab/services/planner-solver/rules/occupancy.json:740)); официальный ориентир доступной скамьи — 43–48,5 см. [U.S. Access Board](https://www.access-board.gov/ada/ada-ibc-comparison/chapter-9/)

- Кушетка без спинки не становится столовой автоматически. Она может быть `wall_seat_capable`; для dining — только `candidate`, если известны точные seat height/depth и схема гарантирует стену как опору. Стандарт допускает скамью с собственной спинкой либо закреплённую у стены, но это не доказательство пригодности любой кушетки. [U.S. Access Board](https://www.access-board.gov/ada/ada-ibc-comparison/chapter-9/)

- `nominal_seats=floor(L/55)` допустим как soft-оценка. Для hard-сертификата использовать `guaranteed_seats=floor(L/60)`: текущий dining-контракт требует 61 см кромки на человека ([templates.json:281](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:281)); IKEA также рекомендует около 60 см и вертикальный зазор сиденье→стол 28–32 см. [IKEA dining guide](https://www.ikea.com/sg/en/rooms/dining/dining-room-guide-pub21ad8080/)

- У `wall_seat_capable` убрать верхний предел `w≤144`: это envelope конкретного нука, не capability товара. Capability: подтверждённый subtype/category + `overall_d≤62`, `usable_seat_length≥100`; допустимую длину решает Q6b по стене и столу.

- Для консоли аналогично: `d≤40` — capability; `w 90–160` и `h≤85` — преждевременный slot-envelope. Высота и ширина должны проверяться относительно конкретного дивана: существующий контракт уже задаёт `h≤back+5`, `w≥⅔ sofa` ([zones.json:772](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:772)). Общий prefilter можно оставить `h≤90`, согласовав с валидатором ([validate.py:496](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:496)).

- `foldable_dining` пока назвать `foldable_dining_candidate` или `extension_mechanism_present`. Regex не доказывает closed/open geometry; sleeping соответствует мастер-плану ([MASTER-zones-v7.md:145](/home/pakar/igor/remlab/.memory_bank/plans/MASTER-zones-v7.md:145)).

2. Evidence

Строки недостаточно. Нужна структура, но float-confidence без калибровки тоже не нужен:

```json
{
  "value": 45,
  "state": "known",
  "source": "params",
  "path": "params.Посадочное место: Высота посадочного места",
  "raw": "45см",
  "confidence": "high",
  "rule_id": "seat-height-param-v1"
}
```

Состояния: `known | inferred | unknown | conflict`; confidence: `high | medium | low`. Для производного capability хранить `depends_on` и reason codes. `false` означает доказанное несоответствие; отсутствие параметра — `unknown`, не `false`.

Особенно важно: нынешний `specific.back` не имеет явного варианта «нет», только виды спинки/`не_видно`; поэтому он доказывает наличие, но не отсутствие. Enrich и сам предупреждает, что модельная самооценка уверенности ненадёжна ([enrich.py:12](/home/pakar/igor/remlab/tools/scout/enrich.py:12)).

3. Хранение и дельта

Отдельная таблица правильнее колонки в `product_enrichment`: enrichment хранит модельный ответ и его версии ([001-enrichment.sql:22](/home/pakar/igor/remlab/tools/scout/001-enrichment.sql:22)), capabilities — детерминированную проекцию params+dims+enrichment+rules.

К предложенной схеме добавить:

- `schema_version`, `rules_hash`, `input_hash`;
- `computed_at` менять только при изменившемся результате;
- PK `(shop_mid,external_id)`, текущий snapshot; историю правил даёт git, а использованные caps снапшотятся в сет;
- expression/partial indexes на востребованные capabilities.

Критический нюанс refresh: одного запуска «после enrich» нет — batch асинхронный ([refresh_daily.sh:85](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:85)). Нужны два пересчёта:

1. после `load3`, используя только актуальное enrichment;
2. в `enrich_wait.sh` после fetch, перед candidates ([enrich_wait.sh:39](/home/pakar/igor/remlab/tools/scout/enrich_wait.sh:39)).

Не читать старый payload, если `enrichment_version IS NULL`: `load3` при изменении смысла сохраняет payload, но сбрасывает версию ([load3.py:234](/home/pakar/igor/remlab/tools/scout/load3.py:234)).

4. Контракт для Q6b/Q6e

В `sets3` нельзя класть голый алиас SKU. Сохранять:

- `source_role`, `planning_role`, `caps_used`, `cap_rules_version`;
- `usable_seat_length`, `guaranteed_seats`;
- `requires_wall_back_support`;
- `front_access_kind`: `drawers|hinged|open|none|unknown`;
- `mounting_mode`: `freestanding|wall_hung|unknown`;
- `placement_modes`: `wall_console`, `behind_sofa`.

Это нужно сейчас: solver `Item` пока знает только роль и габариты ([models.py:81](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:81)), а seating/clearance-классы захардкожены по роли ([zones.py:281](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:281), [clearances.py:59](/home/pakar/igor/remlab/services/planner-solver/planner/clearances.py:59)). Иначе Q6b снова потребует менять модель данных.

Для Q6e разделить `shallow_storage_capable` и `behind_sofa_console_capable`: подвесная тумба или корпус с неизвестной задней отделкой может быть wall-console, но не автоматически консолью за диваном. Сервисный envelope уже различается: комод 76 см, тумба 45, открытый стеллаж 30 ([clearances.py:66](/home/pakar/igor/remlab/services/planner-solver/planner/clearances.py:66)).

5. Fail-closed и тесты

Capability нельзя выводить из одних размеров:

- пуф: нужен subtype/category/name «банкетка», иначе это может быть пуф-стол, мешок или хранение;
- диван: точная категория/подтип «кушетка», а не просто маленький диван;
- отсутствующие params → `unknown`; dims дают только `fits_wall_envelope=true`, не функциональную пригодность.

Счётчики ≥10/≥100 хороши как acceptance-smoke, но не как единственный тест. Добавить fixed fixtures с контрпримерами, проверку `true ⇒ достаточное evidence`, stale-enrichment test, повторный прогон `input_hash` без изменений и отчёт unknown-rate по каждому магазину. Дневные количества лучше мониторить как baseline/drop-alert; реальное уменьшение фида не должно превращать корректный код в unit-test failure.
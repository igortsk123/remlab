## 1. Вывод

Лучший вариант — не чистый **(a)** и не буквальный **(b)**, а **(b) с транзакционным адаптером**, то есть strangler-подход:

- `rules/room-templates/living.json` становится источником истины о **полной композиции**: обязательных независимых и зависимых слотах, вариантах и целых уровнях деградации.
- Существующий living-room solver пока остаётся исполнителем проверенной геометрии.
- Между ними появляется типизированный адаптер: он переводит `geometry_ref` из нового паспорта в конкретные вызовы старых seating/media/dining/storage/floating-алгоритмов.
- После размещения основных предметов, но до финальной валидации и расчёта цены, выполняется детерминированное размещение зависимых слотов.
- Результат принимается только атомарно: либо размещены все входящие в выбранную композицию товары, либо отклоняется вся композиция.

Буквальный тонкий `living.json`, просто ссылающийся на `templates.json`, сейчас не заработает: `room-composition/1` не умеет исполнять такие ссылки, а схемы старого паспорта не являются стабильным API «scheme id → одна функция».

Полностью переписывать living room на новый механизм сейчас опасно: старый solver содержит значительно больше поведения, чем видно из JSON, и обслуживает одновременно `/demo` и `/try/<id>`.

Ключевой инвариант нового контракта:

```text
catalog/priced slot instance IDs
    ==
successfully resolved 3D placement slot instance IDs
```

Исключение допустимо только для явно объявленных непродаваемых виртуальных объектов, например виртуального экрана TV. Состояния `unplaced`, `list_only`, «товар в цене, но скрыт viewer’ом» в успешной композиции быть не должно.

---

## 2. Доказательства в коде

### `room-composition/1` пока не является общим исполняемым форматом

Набор известных `kind` жёстко ориентирован на bedroom и не содержит carrier/dependent-модели: [room_templates.py](/home/pakar/igor/remlab/services/planner-solver/planner/room_templates.py:30).

Проверка схемы валидирует известные kinds и `rule_ref`, но не проверяет:

- циклы зависимостей;
- существование и исполнимость legacy scheme refs;
- неизвестные поля;
- атомарную полноту композиции.

См. [room_templates.py](/home/pakar/igor/remlab/services/planner-solver/planner/room_templates.py:52).

`template_for()` просто выбирает первый паспорт по `purpose` и priority; оно не перебирает C1/C2/C3 по геометрической применимости: [room_templates.py](/home/pakar/igor/remlab/services/planner-solver/planner/room_templates.py:127).

Кроме того, `Room.purpose` сейчас содержит bedroom-семантику, а не living-room scenarios: [models.py](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:80). Поэтому поля наподобие `purpose: ["living", "media"]` нельзя бездумно копировать из раннего дизайн-документа.

Bedroom engine всё ещё содержит геометрию групп в Python и использует новый паспорт главным образом как селектор состава: [bedroom.py](/home/pakar/igor/remlab/services/planner-solver/planner/bedroom.py:627). Его fallback допускает исключение optional groups/roles, что уже не соответствует последнему правилу владельца.

### Старый living solver нельзя заменить одним JSON без существенной потери поведения

Старый паспорт содержит seating/media/floating, виртуальный экран, ковровые правила и другие ограничения: [templates.json](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:1).

Но фактическое поведение распределено по коду. Например:

- сборка блока из реальных размеров SKU: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:582);
- последовательное размещение зон: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:930);
- отбрасывание отдельных optional zones quality gate’ом: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1055);
- превращение оставшихся ролей в `skipped_optional`: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1238);
- дополнительные частичные fallback’и beam search: [beam.py](/home/pakar/igor/remlab/services/planner-solver/planner/beam.py:200).

`Layout.ok` не считает `skipped_optional` ошибкой: [models.py](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:178). Это фундаментально отличается от нового требования, а не просто является пробелом в паспорте.

Living room до сих пор зарегистрирован отдельно от room solver plugins: [room_registry.py](/home/pakar/igor/remlab/services/planner-solver/planner/room_registry.py:43).

### Подбор каталога сейчас происходит не «в слот»

Composer сначала выбирает фактически один товар на роль, после чего solver размещает уже выбранный набор. Фильтр размеров применяется только к ролям с описанным slot rule: [slot_rules.py](/home/pakar/igor/remlab/tools/scout/slot_rules.py:69).

Следовательно, одного `living.json` недостаточно. Для правила «лучший подходящий SKU в тот же слот» исполнитель должен получать пул кандидатов на слот либо orchestration должен перебирать кандидатов транзакционно.

### Нынешний export прямо создаёт запрещённые состояния

Soft roles объявлены как товары «без места в 3D»: [asset_strategy.py](/home/pakar/igor/remlab/tools/scout/salad/asset_strategy.py:56).

В live builder soft roles и вазы экспортируются отдельными путями: [flat215_demo.py](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1720). Люстра не входит в `DECOR_ROLES`: [flat215_demo.py](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:373).

В configurator tabletop-item при отсутствии подходящей опоры остаётся в составе с `unplaced=true`: [resolve.ts](/home/pakar/igor/remlab/lib/configurator/resolve.ts:296). Viewer затем просто не создаёт для него объект сцены: [build-scene.ts](/home/pakar/igor/remlab/lib/viewer3d/build-scene.ts:115).

Wall art имеет тот же контракт: отсутствие стены оставляет товар в цене, но без размещения: [wall-art.ts](/home/pakar/igor/remlab/lib/configurator/wall-art.ts:1). Кроме того, пара картин может независимо деградировать до одной: [wall-art.ts](/home/pakar/igor/remlab/lib/configurator/wall-art.ts:74). По новой политике «две картины» и «одна картина» должны быть разными полными композициями либо результатом заранее определённого count rule, а не локальным fallback’ом.

Live gate проверяет главным образом core roles, а не равенство invoice и 3D placements: [flat215_demo.py](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:1743).

---

## 3. Предлагаемый carrier/dependent-контракт

Нужен единый набор геометрических anchor kinds, не привязанный к комнатам:

- `item_surface`: сиденье дивана, поверхность кровати, столешница, тумба;
- `item_edge`: спинка, подлокотник, край кровати;
- `wall_above`: стена над диваном, кроватью, комодом;
- `ceiling_over`: потолок над зоной или её центром;
- `opening`: окно или дверной проём;
- `free_floor_region`: свободная область пола, при необходимости с qualifier `corner`.

Последний — формально не dependent от товара. Напольное кашпо занимает пол и должно участвовать в основном поиске коллизий, а не добавляться после solver’а.

Концептуально слот должен выглядеть примерно так:

```json
{
  "id": "seating.sofa.pillows",
  "role": "pillow",
  "carrier": {
    "slot_ref": "seating.sofa",
    "anchor": {
      "kind": "item_surface",
      "surface": "seat"
    }
  },
  "cardinality": {
    "kind": "by_carrier_width",
    "rule_ref": "distances_cm.dependents.sofa_pillow_count"
  },
  "fit": {
    "kind": "surface_fit",
    "rule_ref": "distances_cm.dependents.soft_item_fit"
  },
  "placement": {
    "rule_ref": "distances_cm.dependents.pillows_balanced"
  },
  "symmetry": "balanced",
  "on_failure": "reject_composition"
}
```

Это пока проект нового контракта, а не JSON, который примет текущий `check()`.

Для каждого dependent slot нужны:

- стабильный `id` и `role`;
- `carrier.slot_ref` либо ссылка на архитектурную/зональную опору;
- anchor kind и, для товара, имя поверхности;
- cardinality: fixed или по размеру фактического carrier;
- номинальный size envelope через `rule_ref`;
- правило фактической совместимости с поверхностью;
- ориентация, зеркальность, симметрия;
- вертикальное размещение и clearance через `rule_ref`;
- условия применимости, например «если в комнате есть окно»;
- единственная production-политика ошибки: `reject_composition`.

У SKU/3D asset при этом должны появиться реальные capabilities/support surfaces:

```text
seat polygon + height
top polygon + height
bed/top surface
back/arm edges
wall mounting plane
handedness / mirrorability
```

Их место — в данных товара/asset capabilities, а не в room template.

### Замена carrier

При замене дивана, кровати или комода необходимо:

1. Проверить новый SKU против независимого slot envelope `−20…+10 %`.
2. Взять реальные support surfaces нового asset.
3. Пересчитать count и локальные координаты dependents.
4. Заново выбрать совместимые SKU dependents.
5. Проверить их взаимные коллизии и вместимость поверхности.
6. Атомарно принять всю замену или отклонить её.

Нынешнее поведение configurator, где меняются размеры модели при сохранении центра и rotation, недостаточно: [resolve.ts](/home/pakar/igor/remlab/lib/configurator/resolve.ts:281).

### Если подходящего малого товара нет

Порядок должен быть таким:

1. Следующий SKU того же dependent slot.
2. Следующий основной carrier SKU, если его размер влияет на совместимость.
3. Следующая целая композиция, явно описанная паспортом.
4. Честный `CATALOG_NO_SIZE_MATCH`/`NO_COMPLETE_COMPOSITION`.

Нельзя удалять только вазу, подушку или картину из уже выбранной композиции.

Архитектурное условие не является деградацией: если окна нет, curtain slot не активируется; если окно есть и slot входит в композицию, отсутствие подходящих штор отклоняет её целиком.

---

## 4. Где выполнять размещение

Зависимые слоты следует размещать в **детерминированном post-step внутри solver transaction**:

```text
выбор полной композиции
→ основные напольные предметы
→ реальные carriers и виртуальные obstacles
→ dependents
→ общая 2D/3D валидация
→ цена и export
```

Не в export: там слишком поздно выбирать другой SKU, carrier или композицию. Именно export-подход создал нынешний `unplaced`.

Не все dependents надо помещать в beam search: подушки, ваза, лампа, картины и люстра обычно не меняют размещение крупной мебели. Это излишне увеличит пространство поиска.

Исключения:

- напольное кашпо;
- крупный торшер;
- предметы, реально занимающие проход или площадь пола.

Они должны быть обычными основными слотами либо участвовать в solver feasibility.

Виртуальный TV screen следует сделать полноценным непродаваемым placement/obstacle, привязанным к media carrier. Иначе wall solver не видит занятую экраном область.

---

## 5. Высоты и настенные объекты

Режим крепления является свойством SKU/слота, но нормативные высоты и clearance должны находиться в `occupancy.json` и ссылаться через `rule_ref`.

При текущем ограничении checker’а это должны быть новые ключи внутри:

```text
distances_cm.mounting.wall_art.*
distances_cm.mounting.wall_shelf.*
distances_cm.mounting.wall_planter.*
distances_cm.mounting.tv_screen.*
distances_cm.mounting.chandelier.*
distances_cm.mounting.radiator_clearance.*
```

Сейчас часть высот лежит в `heights_cm`, а отдельные art numbers продублированы в [wall-art.json](/home/pakar/igor/remlab/data/flat3d/wall-art.json:1). Это надо консолидировать либо сознательно изменить правило schema checker’а; при данных ограничениях предпочтительнее первое.

Настенная валидация должна работать не только с плоским интервалом стены, а с вертикальной occupancy:

```text
wall segment + horizontal interval + z interval + depth
```

В неё должны попадать:

- окна и curtain envelope;
- двери и swing;
- радиаторы и тепловой clearance;
- высокий корпус;
- виртуальный TV screen;
- уже занятые wall slots.

Текущий wall-art resolver проверяет окно, дверь и часть мебели, но не имеет полноценной информации о радиаторах и виртуальном экране: [wall-art.ts](/home/pakar/igor/remlab/lib/configurator/wall-art.ts:41).

Настенный planter не должен fallback’иться на пол. Напольный и настенный варианты — разные placement modes и разные slots.

---

## 6. Альтернативы и риски

| Вариант | Оценка |
|---|---|
| Полная миграция living в новый solver сейчас | Чистая конечная архитектура, но максимальный риск потерять скрытое поведение seating/media/rug/floating/quality gate и сломать live |
| Тонкий `living.json` без адаптера | Неисполняемая декларация: нынешний loader не вызывает старые schemes и не обеспечивает атомарность |
| Новый паспорт + legacy geometry adapter | Рекомендуется: новый контракт состава при сохранении проверенной геометрии |
| Добавить carriers прямо в `templates.json` | Быстрее как эксперимент, но закрепляет второй несовместимый формат и не масштабируется на bedroom и другие комнаты |
| Размещать dependents в export | Неприемлемо: нельзя выполнить атомарный fallback, подбор SKU и полную валидацию |
| Включить все dependents в beam | Дорого и в основном не нужно; оправдано только для предметов, занимающих пол |

Основные edge cases:

- зеркальный угловой диван, fixed handedness;
- изменение числа подушек на границе ширины и соответствующее изменение количества в цене;
- лампа и ваза конкурируют за одну поверхность;
- carrier формально подходит по bbox, но asset не имеет нужной support surface;
- диван не стоит у стены, поэтому `wall_above` неприменим;
- окно перекрывает стену над диваном;
- радиатор под окном конфликтует со шторами;
- низкий потолок и допустимый свес люстры;
- замена carrier в клиенте после первоначального расчёта;
- отсутствие 3D asset у подходящего каталожного товара;
- повтор одного SKU с quantity > 1 и стабильные instance IDs;
- циклические ссылки dependents;
- «две картины → одна» как скрытая локальная деградация;
- mandatory decor из нового требования противоречит старым LR levels, где ваза или растение могут отсутствовать.

---

## 7. Безопасный поэтапный ввод

### Этап 0 — минимальный и безопасный первый шаг

Без изменения live-поведения:

1. Расширить schema/checker для dependency graph, executor refs, неизвестных полей, циклов и атомарных composition levels.
2. Создать `room-templates/living.json` с LR-C1/C2/C3/M1/O1/O2/L1/L2/X1 как shadow-паспортом.
3. Добавить типизированный registry `geometry_ref → legacy executor`; не ссылаться на произвольные Python symbols или описательные `status` из JSON.
4. Добавить linter/compiler, проверяющий, что каждый полный уровень разрешается в конкретный набор слотов.
5. Ничего не подключать к default `/demo` и `/try`.

Это самый маленький шаг, который создаёт проверяемый контракт и не затрагивает production geometry.

### Этап 1 — общий placement IR

Расширить `Placement` данными:

- `slot_instance_id`;
- `parent_slot_instance_id`;
- anchor/surface;
- local transform;
- elevation/mount plane;
- priced/virtual marker.

Реализовать generic dependent resolver и тестировать его отдельно от live builder.

### Этап 2 — наблюдение за текущим production

Добавить report-only аудит:

```text
selected/priced IDs − rendered placement IDs
```

Пока не делать его hard gate: нынешние pillow/plaid/curtain/chandelier потоки гарантированно дадут нарушения.

### Этап 3 — shadow living engine

Новый living adapter запускается на тех же входах, но не публикует результат:

- старый solver остаётся authoritative;
- новый пишет отдельный отчёт и scene artifact;
- сравниваются крупная геометрия, выбранные слоты, hard violations и completeness.

Для этого уже подходят отдельный `FLAT215_DEMO_OUT` и независимые trial directories. Нельзя переключать main copy: cron пересобирает опубликованный `/demo`.

### Этап 4 — acceptance gates

Перед canary:

- все 6 стилей `/demo`;
- репрезентативный замороженный набор `/try/<id>`;
- все approved масштабы LR-C1…X1;
- ноль hard violations;
- ноль priced-without-placement;
- точное равенство invoice slots и rendered placements;
- тесты min/max размеров carrier;
- mirror/handedness;
- отсутствие wall/support metadata;
- приемлемое время решения.

### Этап 5 — living-only canary

Переключать только через явный engine mode:

```text
legacy | shadow | composition
```

С сохранением мгновенного rollback. Старый `templates.json` не менять до завершения canary.

После стабилизации удалить отдельные `soft/list_only/decor` export-пути и сделать export простым потребителем единого placement IR.

### Этап 6 — bedroom и остальные комнаты

Для bedroom достаточно того же набора generic kinds:

- pillow/throw → `item_surface` кровати;
- lamp → `item_surface` nightstand;
- picture → `wall_above` bed/headboard.

Комнатно-специфичными должны быть composition passports, rule refs и geometry executors, но не carrier kinds.

---

## Неопределённости

- В репозитории нет однозначного исполняемого соответствия LR-C1…X1 старым solver calls. [living_schemes.py](/home/pakar/igor/remlab/tools/scout/living_schemes.py:1) — drawing script, а не production geometry API.
- Неизвестно покрытие каталога и asset metadata для обязательных подушек, пледов, штор и люстр. Архитектура может быть готова раньше контента.
- Нужно уточнить price/quantity semantics для вычисляемого числа подушек.
- Не определено, может ли пользовательская замена carrier атомарно перевести комнату на другой complete level.
- Ранние дизайн-документы содержат raw numbers и kinds, которые текущий checker не принимает; переносить их дословно нельзя.
- Полный pytest-запуск в этой сессии был невозможен из-за read-only среды без writable temp directory. Статическая загрузка bedroom passport проходит, living passport сейчас отсутствует.

## Что изменило бы вывод

Вывод в пользу адаптера стоило бы пересмотреть, если:

- обнаружится уже существующий стабильный API, где каждый старый scheme id однозначно исполним и возвращает атомарную композицию;
- parity покажет, что адаптация старого solver сложнее полной реализации утверждённых LR-схем;
- утверждённая геометрия LR-C1…X1 намеренно существенно отличается от production solver;
- владелец отменит требование об атомарной полноте и снова разрешит priced-but-unplaced;
- каталог практически не содержит обязательных dependent assets — тогда первым product blocker будет наполнение каталога и 3D metadata, хотя рекомендуемый архитектурный контракт останется тем же.
Вердикт: концепция правильная, но до реализации я бы исправил четыре контракта: не использовать зазор 10–15 см, требовать именно `dining_seat_capable`, явно моделировать выдвигание стульев и совместимость опоры стола. Иначе геометрически валидный nook может оказаться физически неудобным.

### а. Размеры и нормы

- `bench_table_gap_cm` лучше заменить на знаковый `table_edge_to_bench_front_cm`. Для банкетки нормальна кромка стола вровень с передней гранью сиденья или небольшой нахлёст, а не щель 10–15 см. Shelby Williams рекомендует нахлёст не более 3″ ≈ 7,6 см и центральную/консольную опору стола. Для текущей 2D-модели безопасный Q6b-прокси: `0…3 см`, пока вертикальный нахлёст не моделируется. [Shelby Williams — Booth & Banquette Tables](https://www.shelbywilliams.com/files/docs/sw-badtablesinfo.pdf)
- Использовать уже существующие `dining_chair_pullout=[55,71]`: 55 см hard, 71 см preferred. Не вводить дублирующие 60–75 см. Но нужен отдельный полигон **за стулом**: нынешний clearance направлен не гарантированно туда, куда стул выдвигается ([clearances.py](/home/pakar/igor/remlab/services/planner-solver/planner/clearances.py:76)).
- На одного сидящего сохранять минимум 60–61 см длины кромки. Это совпадает и с проектным `edge_per_diner_cm=61`, и с рекомендацией IKEA 60 см. [IKEA — место за обеденным столом](https://www.ikea.com/ch/en/customer-service/knowledge/articles/3gbc7ffd-5023-4c02-bfeb-50d51e204d4g.html)
- Вертикальная совместимость: ориентир 28–32 см между сиденьем и нижней кромкой стола. Но у нас известна высота столешницы, а не царги/нижней кромки, поэтому пока это диагностика/preference, не hard. [IKEA](https://www.ikea.com/ch/en/customer-service/knowledge/articles/3gbc7ffd-5023-4c02-bfeb-50d51e204d4g.html)
- Нужен `nook_table_compatible`: центральная колонна либо достаточно утопленные ножки. Четыре наружные ножки могут сделать корректную 2D-схему непригодной. Это подтверждают и [Room & Board](https://www.roomandboard.com/design/inspiration/dining-kitchen/dining-and-kitchen-table-finder), и Shelby.
- Проход к торцу банкетки: 60 см допустим как внутренний проектный минимум `secondary passage`, но не надо называть его accessibility-нормой. Требования доступности предусматривают отдельное свободное место у торца, существенно больше локальной полосы 60 см. [U.S. Access Board, §903](https://www.access-board.gov/ada/ada-ibc-comparison/chapter-9/)

### б. Стена, окно и L-форма

Q6b правильно ограничить **одной прямой стеной**. L-образный nook — отдельный атомарный шаблон: два сегмента стены, угловой стык, другая посадочная ёмкость и эвакуация. Его не следует скрывать как вариант `edge_nook`.

Окно пока исключить: `allow_window_back=false`. Нынешний `wall_candidates` воспринимает оконную стену как обычный контур ([candidates.py](/home/pakar/igor/remlab/services/planner-solver/planner/candidates.py:117)). Подоконник, радиатор, шторы и высоту спинки лучше честно добавить в Q8. Банкетка с `requires_wall_back_support` не может опираться на проём.

### в. Посадочные места

Считать:

```text
total_seats = caps.guaranteed_seats + фактически поставленные стулья
```

Для `edge_nook` минимум именно **4 места**:

- `guaranteed_seats >= 2`, то есть полезная длина банкетки не менее 120–122 см;
- не менее двух стульев со свободной стороны;
- все предметы проходят hard целиком, иначе шаблона нет.

Важно требовать `dining_seat_capable=true`, а не только `wall_seat_capable`: кушетка допустимой глубины ещё не обязательно имеет подходящую для еды высоту. Этот контракт уже выводится в [capabilities.py](/home/pakar/igor/remlab/services/planner-solver/planner/capabilities.py:151).

Варианты с торцевыми стульями лучше сделать отдельными атомарными формами `edge_nook_4/5/6`, а не молча добавлять или отбрасывать предметы внутри одного блока.

### г. Диагностика

В `_dining` достаточно хранить:

```json
{
  "scheme": "edge_nook",
  "zone_instance_id": "...",
  "state": "full_valid|inventory_gap|template_infeasible|access_blocked|full_chain_invalid",
  "capacity": {"bench": 2, "chairs": 2, "total": 4},
  "wall": {"segment_id": "...", "window_back": false},
  "geometry": {
    "edge_offset_cm": 0,
    "open_end": "left",
    "end_access_cm": 63,
    "chair_pullout_min_cm": 55,
    "table_base_kind": "pedestal"
  },
  "reject_codes": []
}
```

Стабильные причины: `no_bench`, `bench_not_dining_capable`, `bench_capacity_lt2`, `no_table`, `table_base_unknown/incompatible`, `chairs_lt2`, `no_wall_segment`, `window_wall_disallowed`, `wall_support_missing`, `table_bench_mismatch`, `chair_pullout_blocked`, `end_access_blocked`, `door_swing_blocked`, `route_blocked`.

### д. Конфликты валидатора

Сейчас нет hard-правила «стул с каждой стороны» или общего запрета стола у стены: `check_chairs_at_table` проверяет только близость стула к столу ([validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:708)). Поэтому широких исключений делать не нужно.

Нужны точечные изменения:

- включить банкетку в функциональную группу dining для nook;
- добавить `check_edge_nook_contract`: опора на стену, ёмкость, два стула, доступный торец, pullout, основание стола;
- проверять door swing и route против operational/pullout-полигонов, не только footprint;
- не разрешать 2D-пересечение `table × bench`, пока нет данных о столешнице/царге; использовать прокси `0…3 см`;
- оставить один логический `tpl_id="dining"` с `tpl_variant="edge_nook"`, чтобы не возникла вторая столовая;
- в Q6b держать паспорт `implemented_library/unwired`; подключать эксклюзивно в Q6c. Nook-комплект не должен сначала пробоваться обычным `dining_island`.

И ещё адаптерный якорь: у `Item` сейчас нет типизированных caps, а `RAW_BANK` не пропустит новую напольную роль без регистрации ([solver_run.py](/home/pakar/igor/remlab/tools/scout/solver_run.py:40)). Перед placer нужны `банкетка` в floor-role map и перенос provenance/caps в модель без повторного вычисления мест из ширины.
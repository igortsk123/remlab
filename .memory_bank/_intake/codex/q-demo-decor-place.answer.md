Вывод: вазу правильно материализовать на сервере, но не как скрытый побочный эффект. Каноническим должен быть отдельный surface-placement: декор связан с конкретной опорой, заблокирован для редактирования, а координаты выводятся из текущей позы опоры. Делать его обычным `items[]` или хранить только `{role, sku}` — обе крайности ломкие.

Критичные дефекты текущего решения:

1. «Не влезло — поставить стопкой» недопустимо. Сейчас все предметы получают одинаковые `x,y`, если суммарная ширина больше столешницы: [draft_render.py:392](/home/pakar/igor/remlab/tools/scout/draft_render.py:392). Это даст взаимопроникновение и окклюзию. Нужно пробовать следующую опору, затем возвращать `unplaced`; проверять и ширину, и глубину с отступом.

2. Высота опоры всё ещё выдумывается как 45 см: [draft_render.py:380](/home/pakar/igor/remlab/tools/scout/draft_render.py:380). Это нарушает Р1. Высота поверхности должна быть `support.elev_cm + support.item.h_cm`; опора без `h_cm` непригодна.

3. В режиме улучшения поставленная ваза станет clay-заглушкой. Обычный draft добавляет `sid` декора в карту мешей: [draft_render.py:3024](/home/pakar/igor/remlab/tools/scout/draft_render.py:3024), а `improve_mode` строит её только из `items`: [improve_mode.py:277](/home/pakar/igor/remlab/tools/scout/improve_mode.py:277). При этом поставленная ваза уже исключается из третьего листа: [improve_mode.py:323](/home/pakar/igor/remlab/tools/scout/improve_mode.py:323). Нужно добавить декор и в `sid_by_role`, и в identity-лист как уже размещённый товар.

4. Замена декора не инвалидирует старый кадр: `revision()` учитывает только `items`: [index.html:1838](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1838). В ревизию должны входить SKU декора, опора и версия правила его размещения.

5. Индекс замены нестабилен: `decorList()` фильтрует массив, затем UI пишет по этому индексу в исходный `v.decor`: [index.html:1398](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1398), [index.html:2868](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2868). При невалидной записи перед вазой заменится другой элемент. Нужен исходный индекс или стабильный `decor_id`.

6. Сумма пока считается несогласованно. Итог списка включает декор, но `priceCard()` получает сумму без него: [index.html:1474](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1474). `variantPrice()` в основной ветке возвращается до добавления декора: [index.html:913](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:913). `variantCount()` также его не считает: [index.html:903](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:903).

7. В модалке кадра декор виден в списке, но кнопки замены у него не будет: она создаётся только при совпадении с `items`: [index.html:2359](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2359).

### 1. Где считать постановку

Лучший минимальный контракт:

```json
{
  "id": "decor-1",
  "role": "ваза",
  "sku": {},
  "placement": {
    "kind": "surface",
    "support_id": "столик",
    "u": 0,
    "v": 0,
    "locked": true
  }
}
```

- Сборка демо выбирает и сохраняет опору, но не абсолютные координаты.
- Сервер выводит `x/y/elev` из актуальной позы опоры.
- Браузер тем же отношением рисует метку на плане.
- При движении столика ваза автоматически следует за ним.

В обычные `items[]` декор класть нельзя: у `Placement` нет `fixed`/`placement_kind`: [models.py:104](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:104), а обработчик плана считает перетаскиваемыми все элементы `items`: [index.html:2640](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2640).

### 2. Ваза без высоты

Сейчас — не ставить и не предлагать как замену. Более того, для демо лучше заменить её при сборке на вазу с полными `w/d/h`, чем молча включать в стоимость товар, которого нет в кадре.

`demo_swap_pool` уже требует все три размера: [demo_swap_pool.py:57](/home/pakar/igor/remlab/tools/scout/demo_swap_pool.py:57), но лента, собранная из сетов, проверяет только `w/d`: [flat215_demo.py:459](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:459), а `tryOn()` также требует только их: [index.html:2862](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2862). Это надо выровнять.

`_dim_from_mesh` в прод пока не использовать. Позже допустима отдельная калиброванная проекция с provenance вроде `mesh_estimate:<generation_key>` и confidence, но не скрытая подстановка в рендере.

### 3. Коллизии и занятость

`_push_from_supports` декор непосредственно не сдвинет: он работает только со стульями, креслами и табуретами: [draft_render.py:2741](/home/pakar/igor/remlab/tools/scout/draft_render.py:2741), [draft_render.py:2784](/home/pakar/igor/remlab/tools/scout/draft_render.py:2784).

Но утверждение «`elev_cm > 1` исключает предмет из занятости пола» неверно в общем случае:

- это исключает его только из препятствий камеры: [scene.py:120](/home/pakar/igor/remlab/services/planner-solver/planner/scene.py:120);
- `floor_used_pct()` считает все `Placement`: [geometry.py:341](/home/pakar/igor/remlab/services/planner-solver/planner/geometry.py:341);
- `free_space()` тоже вычитает их footprint: [geometry.py:326](/home/pakar/igor/remlab/services/planner-solver/planner/geometry.py:326);
- проверка коллизий полностью двумерная и проигнорирует высоту: [validate.py:88](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:88).

Поэтому surface-декор следует материализовать после солверной валидации только для рендера либо добавить явную семантику `placement_kind=surface`. `elev_cm` недостаточно: он одинаково описывает вазу, телевизор и люстру.

### 4. Выбор опоры

Выбор человеком в первой версии не нужен. Достаточна детерминированная политика:

1. Совместимый журнальный столик.
2. Совместимый обеденный стол.
3. Иначе `unplaced`.

ТВ-тумба и комод сейчас добавлены сверх буквального решения владельца: [draft_render.py:326](/home/pakar/igor/remlab/tools/scout/draft_render.py:326). Их лучше не включать без отдельного согласования.

«Совместимый» означает: известны `w/d/h` опоры, весь декор помещается внутри обеих осей с отступом, без наложений. Если первая опора мала — пробовать вторую, но никогда не складывать предметы друг в друга.

Отдельно: не переносите всю роль `кашпо` в настольный декор. В действующем каноне это напольная роль: [zones.json:789](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:789), [template.py:3749](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:3749). Для настольных кашпо нужен отдельный subtype/capability, а не порог `ширина ≤60`.

Приоритет внедрения: сначала контракт surface-placement и строгие габариты; затем синхронизация draft/improve; затем revision, сумма и обе точки замены; после этого — несколько предметов и дополнительные типы декора.
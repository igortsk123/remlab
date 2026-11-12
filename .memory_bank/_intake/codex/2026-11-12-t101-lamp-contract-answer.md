## Вердикт

Ваш вывод в основном правильный: нужен общий IR «зависимый декор паспорта», но не общий алгоритм размещения. Люстра остаётся фиксированной, лампа — привязанной к носителю.

1. Не проводить лампу путём вазы. `DECOR_SUPPORTS` сознательно ограничен столиками и столами (`lib/viewer3d/scene-extras.ts:180`), тогда как паспорт явно задаёт комод, поверхность и fit (`services/planner-solver/rules/room-templates/living.json:381`). Добавление комода в `DECOR_SUPPORTS` подменит паспорт эвристикой.

2. Лучше вынести из `chandelier.py` общий `dependent_decor.py`, оставив отдельные политики товара: люстре нужен особый `hang` по мешу (`lib/configurator/fromDemo.ts:529`), обычной лампе — каталожные Ш×Г×В, как прочему декору (`lib/configurator/fromDemo.ts:516`).

3. Общий контракт должен переносить не только абсолютное место:

```text
strategy: carrier_surface
place: {x,y,bottom_cm,slot_instance_id,parent_slot_instance_id,
        anchor:{kind:item_surface,surface:top},
        local:{dx,dy,rot}, carrier:{role:комод,ordinal:0}, fit:{...}}
```

`parent_slot_instance_id`, `anchor` и `local` уже являются штатным IR решателя (`services/planner-solver/planner/models.py:188`); выбрасывать их и потом восстанавливать связь по одной роли хуже.

## Поведение сцены

Выбирать пересчёт от текущего комода. ✥ должен трансформировать `local.dx/dy` поворотом носителя; «Заменить» — заново проверить fit и взять новый верх. Нет/не влезает — `unplaced`, но слот и цена остаются: цена начисляется до размещения (`lib/configurator/resolve.ts:168`), а `unplaced` лишь исключается из рисунка (`lib/viewer3d/build-scene.ts:130`).

Абсолютные `x/y/bottom_cm` нужны как исходный снимок и диагностика, не как постоянная истина. Для люстры они остаются истиной (`lib/configurator/fromDemo.ts:536`).

Не включать `carrier_surface` в пакет ваз. Сейчас любой новый strategy попадёт в общий фильтр (`lib/configurator/fromDemo.ts:464`, `tools/scout/draft_render.py:478`, `tools/scout/flat215-demo/index.html:5624`) и крупная лампа действительно может снять все вазы правилом «всё или ничего». Нужны две независимые группы: свободный tabletop и carrier-bound.

Для плана лучше экспортировать из `demo-scene.ts` расчёт места, как уже сделано для картин (`tools/scout/flat215-demo/index.html:5620`), а не писать четвёртую копию. Python-порт закрепить golden-паритетом (`tools/assets/scene_extras_golden.py:96`).

## Риски

- Подвесной комод: сейчас клиент поднимает его после `placeTabletop` (`lib/viewer3d/build-scene.ts:251`), поэтому лампу надо рассчитывать с `hungLiftCm` раньше либо внутри carrier-layout. Сервер тоже должен использовать уже поднятый `Placement`, а не сырой `payload.items` (`tools/scout/draft_render.py:403`, `tools/scout/draft_render.py:470`).
- Замена на меньший комод требует повторного `surface_fit`; одного сохранённого смещения недостаточно. Норма существенно строже вазовой: отступ 8 см и площадь ≤20% (`services/planner-solver/rules/occupancy.json:542`).
- Лампа без модели: искать годную лампу того же стиля, как люстра ищет кандидатов (`tools/scout/chandelier.py:111`). Если кандидата нет — не допускать «цена без 3D»: громко снять лампу/вариант, не делать `list_only`.
- `stableSlotIds` устойчив только по роли и номеру (`lib/configurator/fromDemo.ts:84`); связь с носителем должна быть явной, не по позиции массива.
- Цена: лампа должна жить только в `decor`, не одновременно в `items`; страница уже складывает обе коллекции (`tools/scout/flat215-demo/index.html:5723`).
- Тур: товар лампы следует сохранить ещё в `trial_demo` вместе с выбранным `set_id`, а не заново читать изменившийся банк в `trial_bundle`; сейчас передаётся лишь список ролей (`tools/scout/trial_demo.py:253`), затем `decor` обнуляется (`tools/scout/trial_bundle.py:1148`).
- Для товара в `variants[].decor[].sku` придётся расширить whitelist: сейчас `GOODS_AT` разрешает товарные поля только в `items` и feeds (`tools/scout/trial_bundle.py:245`).

## Минимальные тесты

1. Python: место лампы равно результату `dependents.resolve`, включая parent/local/fit; основа уже есть в `services/planner-solver/tests/test_dependents.py:130`.
2. Один и тот же набор даёт канонически одинаковую строку lamp decor в /demo и туре.
3. TS: исходное место, ✥/поворот комода, замена высоты, маленький комод и удалённый комод → `unplaced`, цена сохранена.
4. Подвесной комод: верх и лампа подняты одинаково в TS и серверном кадре.
5. Лампа не участвует в batch ваз; её отказ не снимает вазу.
6. `priced_vs_3d`, public-whitelist и «ровно один ценовой слот»; отдельно регрессия спальни `list_only` (`tools/scout/demo_bedroom.py:48`).
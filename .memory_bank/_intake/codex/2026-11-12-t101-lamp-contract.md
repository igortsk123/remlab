Ты — независимый советник по коду репозитория remlab (только чтение). Отвечай по-русски, кратко (≤ 60 строк), со ссылками `файл:строка`.

## Задача T-20261112-101
Настольная лампа на комоде в гостиной должна появиться в 3D, в списке и в цене — и на /demo, и в турах пробы (одним правилом).
Сейчас её нет нигде:
- /demo гостиная: цикл декора `tools/scout/flat215_demo.py` (~1769) берёт только `DECOR_ROLES` и мягкое — «лампа» выпадает молча
  (в банке `tools/scout/sets3.json` лампа в 122 из 126 наборов, лампа+комод — в 85; годная модель у 15 из 17 разных ламп).
- Туры: `tools/scout/trial_bundle.py:1148` — `'decor': []` всегда.
- Решатель (T-98, `services/planner-solver/rules/zones.json light_carriers.requires_decor`) уже считает комод светом только при лампе.
- Спальни (лампы на прикроватных, `demo_bedroom.py:LIST_ROLES`, list_only) — НЕ трогаем.

## Что уже есть
1) Паспорт гостиной `services/planner-solver/rules/room-templates/living.json` → `groups.light.variants.dresser_lamp`: зависимое место
   `light.lamp` на `item_surface top` носителя `light.dresser`, fit `surface_fit` (`distances_cm.dependents.surface_decor`).
   Решатель зависимых мест — `services/planner-solver/planner/dependents.py:resolve`.
2) Люстра T-66 (`tools/scout/chandelier.py`, `flat215_demo.py:chandelier_decor`): место считает тот же `dependents.resolve`, в данные
   варианта идёт строка декора `{role, strategy:'ceiling_over', place:{x,y,bottom_cm,slot_instance_id}, sku}`; мост в сцену
   `lib/configurator/fromDemo.ts` (~290 `isCeilingDecor`, ~530 слот `ceilingOver`, место фиксированное, сцена не пересчитывает).
3) Ваза: строка декора без места; мост делает слот `tabletop:true`, место пересчитывает сцена при каждом расчёте
   `lib/configurator/resolve.ts:placeTabletop` → `lib/viewer3d/scene-extras.ts:decorLayout` (опоры только `DECOR_SUPPORTS` = столик,
   стол обеденный) — ваза идёт за опорой, если покупатель двигает (✥) или меняет столик. То же правило — кадр сервера
   `tools/scout/draft_render.py:decor_layout` и метка на плане `tools/scout/flat215-demo/index.html:decorSupport`.

## Мой вывод (проверь и оспорь)
Директор хочет: контракт decor+place для лампы ОБЩИЙ с люстрой, не второй путь. Мой вариант:
- Python: обобщить `chandelier.py` в «зависимый декор паспорта» (роль → место паспорта): люстра `ceiling.chandelier`, лампа
  `light.lamp`; лампе — `strategy:'carrier_top'`, `place:{x,y,bottom_cm,slot_instance_id, carrier_slot_instance_id}`.
  Носители — переходник роль варианта → место паспорта (как `_SEATING` в chandelier.py; комод → `light.dresser`).
- Мост/сцена: лампа — НЕ фиксированное место, как у люстры, а «стоит на носителе»: место из данных — исходное, но сцена держит
  смещение относительно текущего комода (передвинули/заменили комод — лампа следует; комода нет — `unplaced`, остаётся в цене).
  Т.е. расширить `placeTabletop`: слот с `carrierRole`/смещением вместо поиска опоры по DECOR_SUPPORTS.
- Кадр сервера `draft_render.decor_layout` и `index.html` — по тем же данным.
- Тур: `trial_bundle` строит ту же строку (нейтральное имя, цена по goods), место — тем же Python.

## Вопросы
1. Это правильно «один путь», или лампу честнее провести путём вазы (опора по роли в `DECOR_SUPPORTS`/правило в данных) без `place`
   из паспорта? Что меньше расходится между /demo, туром, кадром сервера и меткой на плане?
2. Фиксированное место (как люстра) vs пересчёт от носителя (как ваза) — что выбрать для лампы, учитывая ✥ и «Заменить» комода?
3. Риски: «всё или ничего» в `decorLayout` (лампа на столике сняла бы вазы?), подвесной комод (`scene-extras.ts:hungLiftCm`),
   модель лампы без модели, высота по мешу vs каталогу, `stableSlotIds`, двойной учёт в цене.
4. Минимальный набор тестов.

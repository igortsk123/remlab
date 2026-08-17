Вывод: делать только атомарный `quiet_pod = кресло 3 + кресло 4 + столик 2`. Камин — альтернативная раскладка этого комплекта, не замена отсутствующей поверхности.

1. Источник поверхности

Брать из `cat['столик']`, но выбирать отдельным слотом `quiet_surface` и сохранять как роль `столик 2`. Категории «журнальный/столик» уже сводятся в `столик` ([category_map.py:58](/home/pakar/igor/remlab/tools/scout/category_map.py:58)); отдельной каталожной роли `приставной` нет ([compose2.py:229](/home/pakar/igor/remlab/tools/scout/compose2.py:229)).

Не использовать нынешний A2 напрямую: он фильтрует лишь top‑3 от подбора главного столика ([compose2.py:692](/home/pakar/igor/remlab/tools/scout/compose2.py:692)), тогда как главный слот требует ширину 120–135 см ([zones.json:696](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:696)). Малые модели отсеиваются раньше постфильтра.

Рекомендуемые ворота:

- круглый: `35 ≤ dia ≤ 70`; прямоугольный: обе стороны `≤70`, не только `w≤70`;
- предпочтительно `h=40–65`;
- цена строго в `tier_band('столик', tier)`, без безлимитного `soft=True`;
- отличать от главного столика по `(mid,eid)`, не по `mid`: `mid` — магазин, а не модель ([compose2.py:294](/home/pakar/igor/remlab/tools/scout/compose2.py:294), [compose2.py:1098](/home/pakar/igor/remlab/tools/scout/compose2.py:1098)).

Запас достаточен: в индексе 10.08 после ручного исключения Nonton — 94 малых оффера/71 дедуп-модель, 81 оффер при `h=40–65`; по пересекающимся тирам 21/59/39. Но всего два магазина, поэтому это достаточная ёмкость, не высокая отказоустойчивость. Методика индекса — [candidates.py:51](/home/pakar/igor/remlab/tools/scout/candidates.py:51).

2. Пара без поверхности

Не создавать. Если поверхность не найдена или комплект не проходит cap — не добавлять все три роли. `build_quiet` уже честно возвращает `None` без поверхности ([template.py:2564](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2564)); контракт также требует `required_any` ([templates.json:382](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:382)).

Даже наличие камина не оправдывает неполную пару: композитор не знает, окажется ли камин угловым/геометрически достижимым. Для будущей 3D/LLM-визуализации структурный pod значительно масштабируемее мёртвых SKU и лишних ветвей поиска. Пониженный fill честнее; fill здесь заявлен диагностикой, не причиной добора ([zones.json:664](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:664)).

3. Компактность кресел

Да, нужна, но двухступенчато:

- preferred: `w≤90, d≤95`;
- hard: примерно `w≤100, d≤105`, плюс запрет recliner/кресло-кровать и тяжёлого подтипа.

Строгое `90×95` оставляет 93 оффера/45 дедуп-моделей, но все у одного магазина Divan.ru и с дырами в premium loft/neoclassic. Поэтому жёсткий `90×95` снизит достижимость.

Критически: вызывать `pick2(..., qty=2)` — квота кресла относится ко всей паре. Сейчас стоит `qty=1` ([compose2.py:1111](/home/pakar/igor/remlab/tools/scout/compose2.py:1111)), поэтому подбор предпочитает кресла с удвоенным футпринтом. Существующий envelope контролирует только ширину, глубины в нём нет ([zones.json:689](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:689)).

4. Что изменить вокруг compose2

- Создавать `pod_key`, общий `pair_key` кресел и `surface_key`; альтернативы и heal хранить целыми pod-комплектами. Сейчас heal заменяет роли независимо и может разрушить exact-SKU пару ([sets_incremental.py:237](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:237)).

- Резервировать футпринт pod после появления ядра `столик+ковёр`, до низкоприоритетного `_ENRICH`; ядро не вытеснять ([compose2.py:964](/home/pakar/igor/remlab/tools/scout/compose2.py:964)). По текущим 36 сетам только 30 проходят верхний cap после добавления пары и условных 0,36 м² поверхности; остальные шесть должны убрать enrichment-extra либо отказаться от pod.

- Исправить скрытую стоимость: `total/fill` вычисляются до P4/Q5 ([compose2.py:1072](/home/pakar/igor/remlab/tools/scout/compose2.py:1072)). Хранить отдельно `primary_total/fill` и `pod_delta_price/pod_floor_fp`; сейчас пара добавляет ещё 69–96 тыс. ₽ плюс столик, но в итоговой цене этого нет.

- Добавить `столик 2` в claimable-роли quiet ([templates.json:593](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:593)) и в `compact_media_plus_quiet.requires_roles`: сейчас reserved-ветка требует только кресла 3/4 ([zones.json:1155](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1155)).

- Сделать `кресло 2` P4 и `quiet_pod` явными альтернативными ветками. Солвер уже запрещает quiet при богатой primary ([template.py:2605](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2605)), но текущий приоритет ставит `pair_sides` раньше quiet ([zones.json:1202](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1202)). Для цели `quiet≥50` нужна квота/ротация выбора quiet, иначе одна лишь доступность 72 комплектов результата не даст.

Итого: поверхность — обязательная часть пакета; торшер не заменяет её. Цель сборщика — покрыть пакетом почти все 72 eligible-сета, чтобы после геометрических отказов получить ≥50 реальных quiet-планов.
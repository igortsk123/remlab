Вопрос НОРМЫ (нужны источники). Две наши схемы посадки не имеют обоснования в паспорте — только id.
Владелец спросил про первую напрямую: «в каких случаях такая композиция используется обычно?»

1) `seating.tandem_r` / `tandem_l` — ДВА КРЕСЛА СТОЛБИКОМ С ОДНОГО БОКА дивана (одно за другим
   вдоль его торца, оба развёрнуты к центру зоны на 90° к оси дивана), второй бок пуст.
   Реализация: `services/planner-solver/planner/template.py` (ветка `variant in ('tandem_r','tandem_l')`).
   Комментарий в коде: «узкая комната: фланги с двух сторон не влезают по ширине». В паспорте
   `rules/templates.json → zones.seating.schemes` у обеих схем НЕТ ни when, ни why.
   Частота в наших планах: tandem_r 23 из 272 (8%), tandem_l 5 (2%).

   Вопрос: это признанный приём практики или наш геометрический костыль? При каких условиях
   он законен (ширина комнаты, маршрут вдоль второго бока, одинаковые ли кресла, углы разворота)?
   Что говорят источники про «два кресла подряд с одной стороны» против «по одному с каждой»?
   Если приём законен — сформулируй `when` и `why` с провенансом; если нет — предложи, чем
   ограничить (например, только при ширине комнаты ниже порога и только для пары одного SKU).

2) `seating.square` — при двух диванах Г-стыком кресла ставятся СТОЛБИКОМ СБОКУ СТОЛИКА
   (в коде — «фолбэк для тесных канонических комнат»). В паспорте есть `when`, нет `why`.
   Тот же вопрос: норма или костыль, и как это правильно описать.

3) Заодно проверь мои формулировки якоря и формы, которые я собираюсь проставить ВСЕМ 45 схемам
   (ADR-0112 требует `anchor` и `form` в паспорте). Типы якоря: window | bay | corner |
   wall_segment | room_center | object. Скажи, где я ошибаюсь:
   - формы посадки (default/bulky/facing/bridge/tandem_r/tandem_l/u/square/pouf_table/gap_compact)
     → anchor=wall_segment; floating_pair → room_center; window_back → window;
   - media_centered/media_mirror/media_at_jamb/media_between_windows/media_installation/
     media_storage_combo/media_builtin → wall_segment; media_corner → corner;
     fireplace_side_by_side → wall_segment; tv_over_fireplace → object(камин);
   - fireplace.* → wall_segment; quiet.quiet_chat → wall_segment; quiet.fireplace_flank → object(камин);
   - reading.window_anchor → window; bay_anchor → bay; corner_vignette → corner;
     fireplace_anchor → object(камин);
   - dining_island/dining_round_compact → room_center; dining_against_wall/dining_edge_nook/
     dining_foldable → wall_segment;
   - storage_perimeter → wall_segment; storage_shallow → object(диван); corner_tower → corner;
     storage_zone_divider → room_center;
   - decor.corner_plant → corner; bay_plant → bay; window_seat.* → window/bay соответственно.

Файлы не изменяй. Верни: вывод по каждому пункту; источники со ссылками; готовые формулировки
`when`/`why` для схем без обоснования; исправления моей таблицы якорей/форм.

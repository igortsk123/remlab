Вывод: это продуктовая доктрина, не общая норма. Если владелец говорит «не должен», её можно сделать H1, но только для самостоятельного комода, а не для любого предмета с базовой ролью `комод`.

1. «За видимостью»

Честнее всего — основной конус взгляда:

- вершина: `seat_axis_origin(главный диван)`;
- ось: фактический `facing_vector(divan.rot)`, не направление на ТВ;
- полуугол: ±60° до границы комнаты;
- нарушение: в конусе более 5% футпринта комода.

Полуплоскость `forward <= 0` слишком строга: она запрещает законные боковые стены впереди плеча. Узкий коридор диван→ТВ, наоборот, слишком слаб. Назвать правило лучше `primary_sofa_view_cone`, а не буквальной «видимостью»: ±60° — продуктовый порог, не физиологическая норма.

Внешние источники подтверждают пользу закрытого хранения и снижение визуального шума, но не запрет положения перед диваном. [Homes & Gardens](https://www.homesandgardens.com/interior-design/living-rooms/why-were-stressed-by-the-visual-clutter-of-open-storage).

2. Severity

H1 — да, раз формулировка владельца абсолютная. Но:

- фильтр кандидатов должен сработать до `_best_block`;
- если легального положения нет, комод остаётся unused;
- причина: `outside_primary_view_infeasible`;
- видимый комод как автоматическая деградация запрещён.

Хранение сейчас optional, поэтому сцена не должна падать целиком. HARD без кандидатного фильтра действительно создаст кандидатов-зомби и может ухудшить поиск.

3. Конфликты

- `media_installation`: узкое исключение для `tpl_id=media AND tpl_variant=installation`. Это не случайный комод, а член атомарной фокус-стены. Желательно всё же ранжировать компаньонов `витрина/стеллаж` раньше комода.
- `console_behind_sofa`: проходит геометрически без исключения. Причём обычные комоды уже исключены из этого канона — нужен `sofa_console_capable` ([template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2092)).
- Буфет столовой: исключение пока не давать. В текущем коде такой схемы вообще нет: dining не включает комод, а `STORAGE_ROLES` даже не содержит `комод 2` ([template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1950)). Будущий буфет должен получить отдельные `dining_sideboard_capable`, `tpl_id=dining`; по умолчанию он также вне конуса.
- Малые комнаты: `unused`, не видимый fallback. Q6-capability означает возможность использования, а не обязанность поставить товар.

4. Реализация

- `zones.json`: `half_angle_deg=60`, `max_footprint_overlap_pct=5`, применимость и исключения, provenance `owner_product_doctrine`, дата 21.08.
- Общий helper `primary_sofa_view_cone`; существующий `view_metrics.view_cone()` не подходит — он требует ТВ и направлен на носитель ([view_metrics.py](/home/pakar/igor/remlab/services/planner-solver/planner/view_metrics.py:103)).
- `place_storage`: фильтровать полный трансформированный блок, а не только центр якорного предмета.
- `validate`: финальный `DRESSER_IN_SOFA_VIEW`, H1, с узким media-exemption.
- Диагностика: overlap%, стена, `tpl_id/variant`, exemption/reject reason.

Гейты: ноль standalone-комодов с overlap >5%; media-компаньоны только с явным exemption; прежние media/dining floors и TIMEOUT; отдельно показать владельцу, сколько комодов стало unused.
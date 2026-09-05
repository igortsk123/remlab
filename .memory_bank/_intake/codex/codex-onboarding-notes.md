## A. Продукт и ограничения

1. remlab — B2C-сервис «Смета-first»: расчёт ремонта → реферальная смета; визуализация и мебель — последующий слой М5 ([CLAUDE.md](/home/pakar/igor/remlab/CLAUDE.md:3)).
2. Stage 1 уже в проде, но ядро сметы М1–М3 ещё не построено; текущий осознанный фокус владельца — расстановка мебели ([project-state.md](/home/pakar/igor/remlab/.memory_bank/project-state.md:21)).
3. Владелец не программирует: результат должен быть проверяем тестами, артефактами, причинами отказа и слепой оценкой.
4. Для реализованного поведения истина — текущий код; для продукта — ADR-0016 и MASTER-cost-first; для живого состояния — прод ([source-of-truth.md](/home/pakar/igor/remlab/.memory_bank/source-of-truth.md:20)).
5. Layout-ядро — детерминированный Python/Shapely rule engine без ML-координат ([layout.md](/home/pakar/igor/remlab/.memory_bank/core/layout.md:14)).
6. Боевой режим — только атомарные зонные шаблоны с паспортами и машинными инвариантами.
7. Composer подбирает реальные SKU; solver не имеет права менять их габариты ([project-state.md](/home/pakar/igor/remlab/.memory_bank/project-state.md:26)).
8. Новые числовые пороги живут в rules JSON с единицами, семантикой, статусом и provenance; новые приоритеты — отдельные лексикографические поля, не правки `weights.json`.
9. Экзамен: 272 фиксированные сцены; floors базы №1–252 — dining ≥220, media 252; отдельный канон — 269 OK + 3 сертифицированных `MEDIA_MISSING` ([MASTER-zones-v7.md](/home/pakar/igor/remlab/.memory_bank/plans/MASTER-zones-v7.md:49)).
10. Durable-память проекта существует только в `.memory_bank/` ([CLAUDE.md](/home/pakar/igor/remlab/CLAUDE.md:30)).

## B. Архитектура solver сегодня

```text
каталог → compose2 → sets3/raw bank
→ solver_run: bank→Item adapter
→ seating ladder + beam гипотез
→ атомарная seating-зона
→ цепочка media/dining/secondary/storage/decor
→ hard validate + quality gates + plan_key
→ JSON/PNG, _beam/_view/_input_bank/_bank_unused
→ acceptance report/gallery/blind pairs
```

- `compose2.py` собирает товарный банк по каталожным ролям, стилю, бюджету и slot-envelope; размерный допуск −20/+10 применяется только здесь.
- `solver_run.py` адаптирует банк в точные `Item`; текущий Q1 уже передаёт явные `диван 2`, `кресло 3/4` и пишет начальные `_input_bank/_bank_unused` ([solver_run.py](/home/pakar/igor/remlab/tools/scout/solver_run.py:61)).
- `solve_zoned_beam()` сохраняет старый greedy как гипотезу №0, перебирает ограниченное число ступеней и топологически разных seating-блоков, затем достраивает каждый до готового плана ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1372)).
- `_solve_zoned_core()` фиксирует атомарную посадку и выполняет цепочку зон в порядке из `zone_priority`; preferred/optional-зона принимается или откатывается целиком через `quality.not_worse` ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:792), [zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:951)).
- `validate()` проверяет физику и hard-контракты; `MEDIA_MISSING` намеренно добавляется только к готовому плану, а не к промежуточным блокам ([validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:1403)).
- Текущий `plan_key`: hard → missing required → covered preferred → номинальный `seat_rank` → axis class → нижние лексикографические уровни ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1332)). Его замена — Q4, ещё не production.

Пять главных инвариантов:

1. Шаблон атомарен: нельзя удалить/повернуть один его предмет после построения.
2. Размеры и идентичность SKU сохраняются от банка до экспорта; phantom dimensions — провал.
3. Hard-физика и обязательные зоны всегда старше любого качества или эстетики.
4. Приоритеты сравниваются лексикографически; существующие веса допустимы лишь внутри нижних soft-ярусов.
5. Детерминизм обязателен, а regression floors после честно принятой базы могут двигаться только вверх.

## C. Известные слабости и MASTER-zones-v7

Текущее состояние: Q0 завершён отдельным коммитом; Q1 находится в рабочем дереве и в экзамене; Q2–Q7 ещё не активированы.

| Пакет | Закрываемая слабость |
|---|---|
| Q0 | Добавляет диагностические `_view`-метрики, соответствующие глазу владельца: маршрут у ТВ, угол/дальность кресел, dining-cone, фронтальные компаньоны, фактическая посадка. Выбор плана не меняет ([view_metrics.py](/home/pakar/igor/remlab/services/planner-solver/planner/view_metrics.py:172)). |
| Q1 | Закрывает потерю `диван 2`, alt-`кресло 2`, `кресло 3/4` между composer и solver; вводит secondary scope и объяснимость судьбы каждого SKU ([MASTER-zones-v7.md](/home/pakar/igor/remlab/.memory_bank/plans/MASTER-zones-v7.md:67)). |
| Q2 | Переносит отсутствующие perceptual-контракты в `view_contracts` с provenance; owner-derived dining/frontal пороги остаются shadow. Также ограничивает исключение `TALL_ON_TV_WALL` только атомарной инсталляцией. |
| Q3 | Добавляет media-aware формы кресел. Сейчас основные формы ориентируют их поперёк или к дивану, а не к ТВ. Сертификат должен различать реальную недостижимость и search gap. |
| Q4 | Заменяет не совпадающий с владельцем `plan_key`: убирает номинальный `seat_rank`, поднимает маршрут, media-seat, dining-cone, corner и фронтальную композицию; добавляет фактическую посадку и забытый `storage`. |
| Q5 | Исправляет пустые большие комнаты: кресла с 25 м², пара одной модели/коллекции, второй seating pod и формальная причина его отсутствия в 40+ м². |
| Q6a–e | Закрывает catalog/runtime gap: capabilities без смены `cat_role`, атомарный edge nook, round compact, alternative bundles и low-storage/console. Это отдельная каталожная волна и отдельный blind-релиз. |
| Q7 | Защищает от переобучения на первых десяти парах: 80 новых сравнений + 12 скрытых повторов, партиями по 20; frozen thresholds, Wilson lower bound >0.5 и repeatability ≥10/12 ([MASTER-zones-v7.md](/home/pakar/igor/remlab/.memory_bank/plans/MASTER-zones-v7.md:142)). |

Главный вывод blind round 1: beam как механизм поиска не является корневой проблемой; текущая функция выбора плохо моделирует взгляд владельца. Владелец ставит выше чистый входной маршрут, медиапригодные кресла, отделённую столовую, наполненную ТВ-стену, угловой Г-диван в малой комнате и достаточную посадку в большой ([blind-round1-owner.md](/home/pakar/igor/remlab/.memory_bank/_intake/owner/blind-round1-owner.md:7)).

## D. Что отслеживать дальше

- Q1 пока не полностью соответствует собственному контракту: текущий черновик индексирует в основном по имени роли, не формирует полноценные `instance_id/base_role/bank_role/usage_scope`, а `passed_not_placed` ещё не разбит на семь требуемых терминальных причин. Экзамен может подтвердить отсутствие регрессии, но не полноту identity-модели.
- В рабочем дереве есть незакоммиченный тест с ожиданиями Q2/Q3, однако `view_contracts`, `media_parallel/media_bridge` и сертификат ещё отсутствуют. Не считать тест-файл реализованной функцией.
- Прочитанный live-report сейчас содержит 272 записи: 270 OK + 2 `MEDIA_MISSING`, тогда как каноническая база говорит 269+3. После экзамена нужно установить, является ли это валидным улучшением; если да — поднять floor и обновить ADR/память, не оставлять две конкурирующие базы.
- Q3 обязан предшествовать Q4: иначе новый ключ станет штрафовать кресла за контракт, для которого генератор ещё не умеет создавать достижимые варианты.
- Сертификаты должны учитывать поисковый бюджет. Особенно опасен `large_xl` с одной ступенью и двумя блоками: «не найдено» ещё не доказывает геометрическую невозможность.
- В коде остаётся сбрасываемое module-state (`MEDIA_NEED`, media mode, waiver). Нужно продолжать проверять повтор одного solve в одном процессе, а не только межпроцессный acceptance.
- Q6 нельзя сводить к размерной переклассификации: `cat_role` сохраняется, SKU не может одновременно стать диваном и банкеткой, nook — только цельный bundle, после добавления альтернатив пересчитываются все агрегаты.
- До Q7 новый `plan_key` должен оставаться shadow. Первые десять пар — discovery/smoke, не доказательство качества.

## E. Как брифовать меня в следующих сессиях

Достаточно прислать:

- текущий Q-пакет, статус `shadow/default` и commit/hash;
- какие файлы и контракты изменились;
- новый ADR или решение владельца;
- результаты экзамена: 272/272, base dining/media, список hard/MM, p95 и hash повтора;
- для спорной сцены: scene ID, обе картинки/координаты и поля `_beam`, `_view`, `_bank_unused`, `_dining`, `_axis_contract`;
- точный вопрос: дизайн, root cause, каталог, интерпретация blind или решение о rollout.

Файлы не изменял.
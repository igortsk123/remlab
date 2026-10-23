1. Корень подтверждается, но он составной.

- В текущем manifest нет ни одной `ready`: 118 `wait`, 8 `blocked`. Promote сначала требует тот же `candidate_hash` и `status=ready`; экзамен/демо ещё вообще не запускались ([bank_promote.py:248](/home/pakar/igor/remlab/tools/scout/bank_promote.py:248)).
- Pending считается внутри `bank_prepare` ([bank_prepare.py:150](/home/pakar/igor/remlab/tools/scout/bank_prepare.py:150)), а `mesh_bind_early` идёт позже ([refresh_daily.sh:434](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:434)). Поэтому свежая привязка меша невидима promote этой ночи.
- Следующей ночью новый hash сбрасывает `since/missing` ([bank_pending.py:115](/home/pakar/igor/remlab/tools/scout/bank_pending.py:115)); hash меняется даже от цены, URL, габаритов и capsule ([bank_pending.py:78](/home/pakar/igor/remlab/tools/scout/bank_pending.py:78)).
- Строгий promote отдельно блокирует только 8 ячеек без `столик` ([bank_invariants.py:43](/home/pakar/igor/remlab/tools/scout/bank_invariants.py:43)); он не объясняет остальные 118.
- Фактическая запись банка сейчас всё равно выключена: `write_enabled=false` ([bank-candidate.json:26](/home/pakar/igor/remlab/tools/scout/rules/bank-candidate.json:26)).

Итого: главный корень — `pending до bind` + churn кандидата; не «слишком строгий promote».

2. Порядок устройства: сначала исправить порядок ночи, затем **(в) → (а) → (б)**.

- **(в) Детерминизм** — обязательная диагностика. Гипотеза именно про `PYTHONHASHSEED` по коду пока не доказана: каталог имеет `ORDER BY` ([compose2.py:247](/home/pakar/igor/remlab/tools/scout/compose2.py:247)), но финальная ничья сортируется лишь по score/price, без SKU ([compose2.py:532](/home/pakar/igor/remlab/tools/scout/compose2.py:532)). Добавить полный ключ `(−score, price, mid, eid)` и заморозить thumbnail/embedding-входы.
- **(а) Kept** — механизм сходимости. Хранить целиком выбранную ячейку и пересобирать только invalid. В `compose2` уже есть почти нужный шаблон частичной сборки, но `_PREV` берётся из живого банка; нужен предыдущий кандидат ([compose2.py:549](/home/pakar/igor/remlab/tools/scout/compose2.py:549), [compose2.py:613](/home/pakar/igor/remlab/tools/scout/compose2.py:613)).
- **(б) Бонус готовому мешу** — только последний tie-break внутри небольшого окна качества, не основной скор. Иначе законсервируете посредственный ассортимент с мешами.

TTL: не автоматическое удаление, а право на переоценку. Начально: `wait_asset` — review через 21 ночь (сейчас 137 уникальных семейств ≈14 партий по 10); `wait_catalog` — 2–3 ночи без активного обогащения; готовой валидной ячейке TTL не нужен. Плановый refresh — раз в 30 дней и только при существенном улучшении.

3. Граница удержания:

- Сразу пересобрать: товар `gone`, hard policy/reject/failed-terminal, нарушен контракт роли, запрещён представитель семейства.
- Удерживать: новый URL/цена/фото того же SKU; пересчитать media/readiness, но не менять выбор. Смена фото может потребовать новый меш, а не новый товар.
- `wait_catalog`: короткая отсрочка, затем rebuild, иначе ячейка может зависнуть навсегда ([bank_ready.py:85](/home/pakar/igor/remlab/tools/scout/bank_ready.py:85), [bank_ready.py:104](/home/pakar/igor/remlab/tools/scout/bank_ready.py:104)).
- Исчезновение из стилевой ленты — не причина само по себе; пересобирать только при hard style/function incompatibility, желательно после двух последовательных ночей.
- Цена вышла из сегмента: hysteresis, например 10–15% и две ночи; немедленно — если нарушился порядок тиров.
- Новый лучший товар: не трогать ожидающую меш ячейку. На refresh менять при `Δscore ≥ max(1.0, 2× p95 шума повторного прогона)` и без увеличения mesh-долга.

Нужны два hash: `selection_hash` по ролям/SKU/qty для удержания и нынешний полный `candidate_hash` для проверки публикуемой версии.

4. Рекомендуемый порядок ночи:

`catalog/enrich/decisions → mesh_family_early → blacklist refresh → bank_prepare без pending → mesh_bind_early → bank_pending --update → bank_promote`.

Чёрный список следует строить из текущих решений и семейств до compose, а не только из вчерашнего pending: сейчас `_blocked()` читает сохранённое состояние ([compose_gates.py:24](/home/pakar/igor/remlab/tools/scout/compose_gates.py:24)).

Семейный дефект подтверждается: решение наследуется через `sku или rep` ([bank_ready.py:93](/home/pakar/igor/remlab/tools/scout/bank_ready.py:93)), а compose проверяет точный SKU ([compose_gates.py:42](/home/pakar/igor/remlab/tools/scout/compose_gates.py:42)). Blacklist должен быть keyed по `mesh_family_rep` либо развёрнут на всех сестёр.

5. Метрики — три уровня:

- Результат: `ready_after_bind`, `promoted`, `published` ячеек за ночь.
- Опережающий прогресс: уникальные `mesh_family_rep`, а не позиции: `missing`, `queued/running`, `completed`; доля `missing` с активным заказом.
- Защита от churn: `% ячеек с тем же selection_hash`, `% сохранённых role→SKU`, число заказанных мешей, брошенных до promote.

Главный критерий сходимости: у валидной kept-когорты `missing reps` не растёт, `ready` монотонно растёт, abandoned mesh близок к нулю. Capsule считать отдельно от товарной стабильности.

Что проверить тестом:

- Один snapshot + frozen caches, `PYTHONHASHSEED=1/2/3`: 126/126 одинаковых selection hashes и байтовый diff.
- Две ночи: `wait_asset → bind → pending → ready → promote` в ту же ночь.
- Цена/URL/capsule меняются, SKU прежние: selection и `since` ожидания не сбрасываются.
- `reject(rep)` исключает все сестринские SKU; снятие решения возвращает всё семейство.
- Kept удерживает небольшого challenger, но немедленно заменяется при gone/policy; `wait_catalog` истекает по grace.

Три профильных selftest (`bank_ready`, `bank_pending`, `bank_promote`) сейчас проходят. Тест порядка ночи в этой read-only среде не запустился из-за отсутствия writable temp-каталога.
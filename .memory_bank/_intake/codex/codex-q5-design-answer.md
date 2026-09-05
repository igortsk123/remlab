Рекомендация: с 25 м² давать солверу согласованную пару кресел как возможность; с 40 м² гарантировать ей один слот поиска второй зоны. Ранжировать не число кресел, а число кресел с валидным intent в связном шаблоне.

1. Композитор

- Порог — `25 м²` из `zones.json`, не `room_mode`: композитор не знает геометрию конкретной вариации комнаты. Отдельно оставить `40 м²` как порог обязательного сертификата второго pod.
- `кресло 3/4` вынести из `_ENRICH`: сейчас добор зависит от достижения fill 30% и выбирает два SKU независимо ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:954)). Создавать пару как `reserved/secondary_quiet` после основного состава.
- На первом этапе — два экземпляра одного точного SKU: одинаковые `(shop_mid, external_id)`. `mid` — это `shop_mid`, не модель ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:236)).
- «Одна коллекция» допустима только по явному `params["Коллекция/серия"|"Коллекция"|"Серия"|"Модель"]` плюс одинаковый магазин/бренд. Сейчас эти поля запрос не загружает; `model_key(name)` — эвристика, не доказательство. Хранить `pair_key` и `pair_provenance=exact_sku|explicit_collection`.
- `кресло 2` оставить, но исправить: это второй экземпляр основного кресла, а не случайный альтернативный SKU. Сейчас фильтр `mid != ...` фактически предпочитает другой магазин ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:1097)). После клонирования 26 gaps должны исчезнуть при наличии базового кресла.

2. Второй pod и бюджет

Нужна резервная квота внутри существующего cap, не сверх него:

- `large, cap=4`: `pair_sides → compact+quiet(reserved) → u_cluster → two_sofa`.
- `large_xl, cap=3`: `pair_sides → compact+quiet(reserved) → two_sofa`.
- Первая волна — максимум один полный прогон на семейство. Если пары 3/4 нет, reserved-слот освобождается.
- В `compact_media_plus_quiet` добавить `requires_roles=["кресло 3","кресло 4"]` и проверку `pair_key`: текущее `inventory_complete` проверяет только primary-группу ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1622)).

Итог писать в `composition_certificate.second_pod`:

- `full_valid` — кандидат с `+qz` существует, независимо от того, выбран ли он;
- `inventory_gap` — нет согласованной пары;
- `quality_rejected` — `place_quiet` дал блок, но его отверг `_not_worse`;
- `template_infeasible` — объявленное пространство кандидатов исчерпано без hard-valid блока;
- `search_budget_exhausted` — валидные для перебора гипотезы остались, но cap закончился.

Второй прогон не нужен: в текущей полной цепочке `place_quiet` уже вызывается ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:897)). Достаточно сохранить её `generated/gate_rejected/placed` в `lay.meta`, затем агрегировать в сертификат.

3. `seating_deficit` без самоцели

Банк — только доказательство inventory, не достижимости. После уже выполненного beam:

```text
armchairs_reachable =
    max(valid_connected_armchairs(candidate))
    по всем full-valid кандидатам
```

Правильная активация:

```text
deficit = need - realized, только если armchairs_reachable >= need;
иначе deficit = 0
```

Не нынешнее `min(need, reachable)`: при достижимом только одном кресле оно ошибочно создаст частичный долг ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1488)).

`valid_connected_armchairs` считать только для кресел:

- входящих в атомарный `tpl_id=seating|quiet`;
- имеющих объявленный shape/zone intent;
- прошедших его контракт: media — фактический угол, conversation/quiet — целостность группы; tandem дополнительно требует сертификат fallback.

Экспортировать по каждому креслу: `{role, zone, group, shape, intent, valid, evidence}`. И `seating_deficit`, и нижний tie-breaker `-armchairs` должны использовать это число, а не сырой счётчик из [view_metrics.py](/home/pakar/igor/remlab/services/planner-solver/planner/view_metrics.py:153). Тогда два случайных кресла не получают преимущества. Более богатый вариант с худшим префиксом всё равно не победит — это уже гарантирует лексикографический порядок.

Минимальные правки:

- `rules/zones.json`: числовые пороги 25/40, `requires_roles`, reserved-family slot, intent по shape.
- `compose2.py`: атомарное создание пар 2 и 3/4, `pair_key/provenance`.
- `zones.py`: reserved scheduler, quiet-диагноз, `second_pod`, candidate-derived reachability, формула deficit.
- `view_metrics.py`: `valid_connected_armchairs` и `seat_intents`.
- Геометрию `template.py/place_quiet` менять не требуется.

Машинные гейты:

- 0 несовпадающих `pair_key`; при базовом кресле — 0 P4 inventory gaps.
- Для каждой сцены 40+ ровно `full_valid` либо одна из четырёх терминальных причин; `attempted ≤ 4/3`.
- `v2_would_choose` не оставляет одно кресло при равном предыдущем префиксе и кандидате с ≥2 intent-valid креслами.
- Экзамен: `TIMEOUT=0`, p95 ≤1.5× Q4, `269 ok + 3 MEDIA_MISSING`, media 252, dining ≥220; без регрессии quiet/two-sofa/u-cluster относительно Q4.
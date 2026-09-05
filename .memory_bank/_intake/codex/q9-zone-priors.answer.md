Главный вывод: частоты нельзя превращать в случайный выбор или напрямую заставлять экзамен повторять 28/19/17%. Это безусловные наблюдаемые доли, смешивающие предпочтения, площадь, наличие товара и сценарий. Их безопасное применение — **локальный ordinal prior между равноценными и достижимыми исходами**, сначала в shadow.

### а. Порядок поиска и место в ключе

Предварительный дизайн в целом верный, но есть две поправки.

1. Нельзя просто пробовать семьи по частоте при ограниченном beam: ранняя семья съест бюджет, а редкая не будет исследована. Правильно:

- определить opportunity: `window`, `seating_center`, `free_corner`, `primary_wall`;
- дать по одной полной попытке каждому достижимому семейству;
- `free_intentional` тоже считать кандидатом;
- частотой упорядочивать только оставшиеся попытки после семейной квоты;
- писать `eligible → attempted → full_valid → selected/not_attempted_budget`.

2. Не применять prior одновременно как сильный порядок поиска и как полноценный ярус — это двойной учёт. В production лучше семейная квота + локальный tie-break; порядок нужен лишь для переполнения бюджета.

Если всё же вводить общий `practice_prior_key`, его точное место — **после `zone_quality`, перед `aesthetics`**, то есть концептуально:

```python
(...existing_prefix,
 circulation, functional, zone_quality,
 practice_prior_key,
 aesthetics)
```

Сейчас обе функции просто добавляют `lk[1:]` ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1419)). Нельзя ставить prior выше circulation, TV-связей, coverage, `seat_rank`, view-contracts или template degradation: популярность не оправдывает функционально худший план.

Первый гейт: prior может изменить победителя, только если весь ключ до него совпадает.

Важно: предложенный порядок окна расходится с цифрами. Частоты дают:

```text
кресло 28 → свободно 19 → window seat 17 → диван 16
```

Если владелец хочет `window seat` выше `free`, это отдельный продуктовый приоритет, а не вывод из частот.

### «Намеренно пусто»

Да, нужен явный исход, но не фиктивная зона и не пустой шаблон:

```json
{
  "opportunity_id": "window:east:0",
  "applicable": true,
  "selected_outcome": "free_intentional",
  "alternatives": {
    "armchair": "full_valid",
    "window_seat": "inventory_gap",
    "sofa": "full_valid"
  },
  "selected_by": "practice_prior_tiebreak"
}
```

Различать:

- `free_intentional` — пустой вариант сравнивался и выиграл;
- `inventory_gap`;
- `template_infeasible`;
- `quality_rejected`;
- `search_budget_exhausted`;
- `not_applicable`.

Пустота не должна считаться покрытой preferred/required-зоной.

Для центра есть принципиальный конфликт: сейчас столик — клей практически всех primary seating-групп, а схемы без столика сознательно удалены после замечаний владельца ([templates.json](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:82), [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1555)). Поэтому `center=free 8%` нельзя внедрить одним prior: это новая атомарная схема и отдельное ADR, потенциально противоречащее прежнему решению «куда делся столик?». `nesting 10%` также сначала требует товаров и шаблона.

### б. Честное измерение

272 сцены оставить только регрессионным корпусом. Не пытаться приблизить их распределение к процентам: синтетика почти везде содержит ТВ, однотипное восточное окно и часто радиатор.

Для каждого opportunity считать воронку:

```text
architecturally_applicable
→ inventory_eligible
→ block_generated
→ full_chain_valid
→ compared
→ selected
```

Основные метрики:

- доли исходов среди всех applicable и отдельно среди full-valid;
- `winner_flips` относительно baseline;
- `prior_decision_count` — сколько планов изменилось именно на prior-ярусе;
- доля `free_intentional`, отдельно от невозможности;
- `not_attempted_budget` по семействам;
- окно: кресло/window-seat/диван/free и распределение back-gap;
- центр и угол — те же outcome-классы;
- старый ключ победителя против нового до prior-яруса.

Защита от переобучения:

- заморозить priors до прогона;
- не менять проценты по результатам экзамена;
- слепо оценивать только изменившиеся пары, стратифицированные по opportunity и площади;
- отдельно накапливать реальные комнаты — именно они позднее смогут проверить внешнее распределение.

### в. Площадь и тип комнаты

Условные частоты нужны, но выдумывать коэффициенты нельзя. Пока использовать площадь только через существующие:

- hard feasibility;
- `room_mode`;
- floor cap и проходы;
- наличие подходящего блока;
- scenario needs.

Так маленькая комната естественно чаще выберет `free`, потому что кресельный/window-seat блок не пройдёт, а не потому что мы придумали множитель для 15 м².

В данные стоит записать:

```json
{
  "denominator": "all_projects",
  "conditional_breakdown": "unknown",
  "sample_size": "unknown",
  "status": "shadow_hypothesis"
}
```

Если владелец отдельно постановит «в small свободное окно предпочтительнее кресла», это допустимо, но с provenance `owner_product_rule`, а не как статистический вывод.

Я бы хранил это как `practice_priors` в `zones.json` либо в отдельном зарегистрированном `practice_priors.json`; новый файл обязательно подключить к `rules_audit.py`. У каждого числа нужны источник самого процента, размер/метод корпуса, дата и география. BHG/H&G подтверждают качественные принципы, но не являются provenance для конкретных 28% или 19%.

### г. Главная стена

При `media_need=required` распределение `TV 35 / fireplace 27 / art…` **не участвует в выборе наличия ТВ**. Кардинальность требует один носитель, и это выше любого prior ([zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1025)).

Кроме того, категории не вполне взаимоисключающие:

- TV + камин уже может быть одной композицией через `place_media_fireplace`;
- стенка одновременно media и storage;
- ТВ может быть интегрирован в библиотеку;
- искусство может быть companion, а не primary focus.

Поэтому текущие проценты пригодны только как `dominant_focus` и лишь когда сценарий допускает выбор:

- `media_need=off`;
- `media_need=preferred`;
- будущий вход `primary_focus=auto|tv|fireplace|art|library|window`.

Для default TV-room нужны другие условные priors: `media_only`, `media+fireplace`, `media+storage`, `media+art`. Исходную таблицу к ним механически переводить нельзя.

### д. Основные риски и гейты

- Детерминизм: никаких `random`; сортировка по `prior_rank`, затем стабильному `outcome_id` и геометрическому ключу.
- Beam-бюджет: минимум одна попытка на достижимое семейство, иначе частота становится скрытым запретом.
- Opportunity определяется до optional-заполнения; план не должен «уничтожить угол», чтобы избежать штрафа.
- Не переупорядочивать глобальный `zone_priority`: частота предметов в углу не означает, что decor должен стать важнее dining или storage.
- `free_intentional` не закрывает required/preferred coverage.
- Никакой потери media/dining ради prior.

Машинный гейт:

```text
для каждого prior-caused flip:
old_key_prefix_through_zone_quality == new_key_prefix_through_zone_quality
```

Плюс прежние 269+3, media/dining floors, TIMEOUT 0 и сертификат `not_attempted_budget`. В production prior включать только после слепых пар; до этого — `practice_prior_key_shadow` в артефакте.
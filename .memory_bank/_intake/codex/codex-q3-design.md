Подготовка Q3 правильная: формы в конце сохраняют greedy, а media-квота гарантирует достижимость. Но «сверх квоты» должно относиться только к пулу блоков, не к числу дорогих полных прогонов.

### 1. Как считать бюджет

Да: семейство считается `contributing` только когда получен полный кандидат:

- `outs[0].placements` есть;
- `hard_count == 0`;
- все required-зоны сохранены;
- при `media=required` фактически стоит `тв-тумба|стенка`;
- заявленный контракт семьи реализован: нужные роли не потеряны, media-кресло действительно ≤45°, для pod реально есть `+qz`.

Но нужны два независимых счётчика:

- `attempted_full_chains` — жёсткий детерминированный лимит;
- `contributing_families` — успешно полученные семейства.

Иначе цикл «до двух успешных» на сложной сцене станет безграничным.

Стартовый бюджет без увеличения нынешнего worst case:

| Режим | Полных попыток сверх greedy | На одну семью |
|---|---:|---:|
| `large` | максимум 4 | одна лучшая позиция |
| `large_xl` | максимум 3 | одна лучшая позиция |

Для XL порядок:

1. non-one-sided rich primary;
2. compact primary с обязательным quiet pod;
3. резерв: следующая rich-семья, если квота не закрылась; иначе media-installation.

Сейчас XL способен сделать до трёх дорогих попыток: два блока плюс `/inst` первого ([zones.py:1472](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1472)). Значит, предлагаемый потолок не расширяет максимальную работу. Важная правка: `_contrib += 1` перенести с факта `variants` ([zones.py:1463](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1463)) на факт принятого полного кандидата.

### 2. Где должна жить семейная квота

Только в `solve_zoned_beam`.

- `pick_ladder` отвечает за доступные атомарные составы и площадь — не менять.
- `place_template` отвечает за геометрию одной `(group_id, shape)`. Добавить максимум `shape_filter`/`top_per_shape=1`.
- Beam-драйвер планирует семейства, расходует full-chain budget и строит сертификат.

Детерминированная классификация из `zones.json`:

| Семья | `(group_id, shape)` |
|---|---|
| `pair_sides` | `sofa_2armchairs × {default, media_bridge}` |
| `u_cluster` | `{sofa_2armchairs, sofa_4armchairs} × u` |
| `two_sofa` | `{sofa_loveseat, sofa_loveseat_2armchairs, two_sofas_2armchairs} × non-square` |
| `compact_media_plus_quiet` | `{sofa_armchair, sectional_armchair, sofa_pouf, sofa_lamp, sofa_solo} × *`, плюс обязательный реализованный `quiet` |
| `one_sided_fallback` | `sofa_2armchairs × tandem_l/r`; двухдиванные группы × `square` |

`media_parallel/media_half` относятся к compact media-primary; `media_bridge` — к `pair_sides`.

Сертификат в `_beam.composition_certificate`:

```json
{
  "families": {
    "pair_sides": {
      "inventory_complete": true,
      "block_generated": 1,
      "full_attempted": 1,
      "full_valid": 0,
      "reject_codes": ["..."]
    }
  },
  "one_sided": {
    "allowed": false,
    "reason": "preferred_family_unattempted"
  },
  "budget": {
    "cap": 3,
    "attempted": 3,
    "exhausted": true
  }
}
```

`tandem/square-one-side` разрешать только если у всех применимых предпочтительных семейств:

- либо `inventory_complete=false`;
- либо `block_generated=0`;
- либо `full_attempted=1 && full_valid=0`.

`budget_exhausted` — не доказательство недостижимости. В этом случае писать `SEARCH_GAP_COMPOSITION`; one-sided нельзя объявлять сертифицированным. Сертификат означает «недостижимо в объявленном полном поиске», не математическую невозможность.

### 3. `sofa_4armchairs`

Выбираю **(б): production-семантика — кресла 3/4 остаются второй quiet-зоной**.

Это даёт больше осмысленного богатства: две компактные функциональные зоны вместо одной перегруженной группы. Возврат 3/4 в общие counts снова превратит число предметов в самоцель и рискует повторить план №174.

При этом `sofa_4armchairs/u` можно оставить как shadow-контрфактуал `large_main_u4`:

- вызывается beam-драйвером явно;
- generic counts не меняются;
- разрешён только для пары одной модели/коллекции;
- сравнивается с `compact+quiet`;
- до слепой проверки production не влияет.

### Минимальные правки

- `rules/zones.json`
  - `beam.composition_families`;
  - `max_full_attempts: large=4, large_xl=3`;
  - порядок семейных квот;
  - политика `one_sided_fallback`;
  - `sofa_4armchairs.status=shadow_alternative`;
  - provenance для каждого правила.

- `template.py::place_template`
  - `shape_filter`;
  - не более одной позиции на запрошенную форму;
  - media-вариант можно вернуть сверх локального `enumerate_k`, но beam решает, запускать ли его полной цепочкой.

- `zones.py::solve_zoned_beam`
  - отдельные attempt/contribution counters;
  - data-driven family scheduler;
  - проверка полного кандидата;
  - `require_quiet` для compact+pod;
  - composition certificate и `SEARCH_GAP_COMPOSITION`.

### Машинные гейты

1. Каждая паспортная `(group, shape)` классифицирована ровно в одно семейство; hash классификации детерминирован.

2. Кандидат с block-valid, но hard-invalid полной цепочкой не закрывает семейную квоту.

3. `large_xl`: не более трёх дополнительных full-chain вызовов; `large`: не более четырёх; p95 ≤1.5× Q1.

4. Wide fixture: при достижимом `pair_sides/U` one-sided выбрать нельзя. Narrow fixture: tandem разрешён только с заполненным сертификатом отказов.

5. Fixture с `кресло 3/4`: generic ladder counts неизменны; quiet-пара одной модели достижима; `large_main_u4` появляется только в shadow.

6. На 272 сценах: прежние floors не снижаются, новых timeout нет, повторный hash совпадает. Q3 в production пока не включать: сначала доказать пул/сертификаты, выбор передать Q4/Q5.
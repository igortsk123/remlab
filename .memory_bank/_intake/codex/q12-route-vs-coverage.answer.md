## Вывод

Правильное решение — вариант **(4): отдельный ярус качества фактического маршрута + финальный floor**, а не простое повышение нынешнего `_main_path_violations`.

Рекомендованный порядок:

```text
hard
→ missing_required
→ main_route_tier
→ covered_preferred
→ seat_rank / capacity
→ axis
→ остальные ярусы
```

Где:

- tier 0: маршрут ≥75 см;
- tier 1: 70–74 см — допустимый, но сертифицированный soft-fallback;
- tier 2: <70 см — финально недопустим.

Для `set5-trapezoid` должен победить компактный кандидат, если его реальный `_route_cm` ≥70. Предпочтительно требовать ≥75, поскольку именно 75 записан как quality gate.

### Важная поправка к диагнозу

В приведённых ключах `-3` и `-2` — **не `-covered_preferred`**, а следующий ярус `-seat_rank`:

```python
(hard, missing_req, -covered_pref, -seat_rank, axis_cls, main_path, ...)
```

У обоих кандидатов `covered_preferred == 0`; это видно и по одинаковым тегам `+tv+st+dc`. Победитель выиграл из-за номинального ранга ступени, а не дополнительной зоны: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1455), [артефакт set5-trapezoid](/home/pakar/igor/remlab/tools/scout/v3set5-layout-acc-zoned-set5-trapezoid.json).

---

## A. Оценка вариантов

| Вариант | Вердикт | Риск |
|---|---|---|
| 1. Поднять текущий `_main_path_violations` | Направление верное, метрика неверная | Высокий: статический контрфактуал по сохранённым beam-кандидатам меняет **25/272** планов; 6 теряют preferred-зону, 16 — seat rank, 5 ухудшают axis |
| 2. Сделать `<70` hard | Верно только как финальный full-plan floor | Низкий по текущему корпусу: выбранный план `<70` ровно один. Высокий, если сделать hard внутри общего `validate()` |
| 3. Признать 60 см нормой трапеции | Неверно | Ломает regression floor, quality gate и предметную семантику главного маршрута |
| 4. Новый route tier + финальный сертификат | Рекомендую | Меняет максимум одну текущую выбранную сцену, если использовать именно `_route_cm`, а не `MAIN_PATH_TIGHT` |

Почему нельзя просто поднять `_main_path_violations`:

- `check_passages()` вызывает `passage_min_cm(kind)`;
- практически все вызовы `validate()` не передают `passage="main"`;
- значит используется default `secondary`, то есть **60 см**, а не 75 или 91: [validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:240), [clearances.py](/home/pakar/igor/remlab/services/planner-solver/planner/clearances.py:102);
- кроме того, эта проверка измеряет достижимость конкретных `MAIN_PATH_ROLES`, тогда как сторож использует другую метрику — `quality.route_width_cm()`: [quality.py](/home/pakar/igor/remlab/services/planner-solver/planner/quality.py:54).

Поэтому `MAIN_PATH_TIGHT=1` и `_route_cm=60` коррелируют в этой сцене, но это не один контракт.

Есть и причина, почему текущий quality gate не спас сцену: `failed_axes()` запрещает новой optional-зоне ухудшить маршрут ниже `min(before, 75)`. Если основная посадка уже оставила 60 см, последующий декор, сохранивший те же 60, формально ничего не ухудшил. Гейт зон — не финальный acceptance gate: [quality.py](/home/pakar/igor/remlab/services/planner-solver/planner/quality.py:204).

---

## Конкретная правка

В данных — один авторитетный блок, например:

```json
"main_route": {
  "target_cm": 91,
  "quality_min_cm": 75,
  "acceptance_floor_cm": 70,
  "secondary_fallback_cm": 60
}
```

С provenance отдельно для каждого смысла:

- 91 — рекомендуемый главный маршрут;
- 75 — продуктовый quality threshold, примерно нижняя граница 30″;
- 70 — regression floor проекта, а не внешняя дизайнерская норма;
- 60 — вторичный проход, не главный.

В `zones.py`:

```python
def main_route_tier(room, lay):
    w = cached_route_width_cm(room, lay.placements)
    if w >= 75:
        return 0
    if w >= 70:
        return 1
    return 2
```

Порядок production-v1:

```python
(hard, missing_req, main_route_tier,
 -covered_pref, -seat_rank, axis_cls,
 _main_path_violations, template_degradation, orphan, ...)
```

Для `plan_key_capacity` сначала остаётся `primary_sofa_missing`, поскольку это LEVEL A:

```python
(hard, missing_req, primary_sofa_missing,
 main_route_tier, -covered_pref, -capacity, ...)
```

В `plan_key_v2` маршрут нужно поставить после `hard/missing_required/unplaced_required`, но до visual/enrichment/preferred-ярусов. Иначе один и тот же проектный инвариант будет иметь разный приоритет в v1/v2.

`_main_path_violations` можно сохранить ниже как отдельную диагностику доступности предметов, но больше не называть её реализацией порога 75 см.

---

## B. Если ни одна гипотеза не даёт 70 см

Не релаксировать молча и не возвращать `ok=true`.

Правильный terminal outcome:

```text
CIRCULATION_MISSING
```

с best-effort планом для диагностики и сертификатом:

```json
{
  "required_floor_cm": 70,
  "quality_target_cm": 75,
  "best_achievable_cm": 60,
  "full_candidates_attempted": 4,
  "search_exhaustive": true,
  "reason": "geometry_infeasible"
}
```

Если бюджет beam не позволил доказать недостижимость:

```json
"reason": "search_budget_exhausted",
"search_exhaustive": false
```

Это не `MEDIA_MISSING`: причина другая. Но семантика результата та же — план можно показать как диагностический fallback, нельзя объявлять успешно принятым.

Автоматический tight-mode допустим только как явный сценарий пользователя. Для accessibility-сценария, напротив, floor должен быть не 70, а около 91 см.

Важно: финальный hard не следует добавлять прямо в общий `check_passages()`. Он вызывается и на промежуточных блоках во время поиска; это может преждевременно убить композицию, которая после полного размещения получила бы иной связный маршрут. Делать проверку нужно на полностью собранном кандидате — подобно финальному media-контракту в [solve_zoned](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:199).

---

## C. Нормы практики

Для обычной гостиной нет универсального закона, требующего ровно 75 или 70 см между переставляемой мебелью. Есть три разных уровня:

- Дизайнерская практика: для **главного маршрута** рекомендуется около 36″, то есть 91 см; между предметами — 18–24″, то есть 46–61 см. Это прямо поддерживает разделение ваших классов `main=91` и `secondary=46–60`: [Homes & Gardens](https://www.homesandgardens.com/interior-design/the-library-how-to-design-the-perfect-living-room-layout).

- Строительный ориентир: IRC требует для стационарного жилого коридора минимум 36″/914 мм. Это полезный benchmark, но не прямая юридическая норма для прохода между диваном и мебелью внутри комнаты: [ICC, IRC R311.6](https://codes.iccsafe.org/content/IRC2021P1/chapter-3-building-planning).

- Доступная среда: непрерывный accessible route — 36″/915 мм; локальное сужение до 32″/815 мм допускается лишь на коротком участке. Это применимо только при соответствующем accessibility brief: [U.S. Access Board, §403.5.1](https://www.access-board.gov/ada/chapter/ch04/).

Следовательно:

- 91 см — хорошо обоснованная цель;
- 75 см — разумный продуктовый минимум для обычного тесного интерьера, но не универсальная «норма закона»;
- 70 см — только аварийный regression floor;
- 60 см — нормальный вторичный зазор между мебелью, но слишком мало для заявленного главного пути от двери.

Трапециевидный контур сам по себе не делает 60 см канонически допустимыми, особенно когда уже найден более свободный hard-valid вариант.

---

## D. Детерминизм и производительность

Детерминизм не пострадает:

- `route_width_cm()` — чистая детерминированная функция;
- пороги дискретны;
- после route tier остаётся прежний полный ключ для разрешения ничьих.

Чтобы не увеличить время:

- вычислять `_route_cm` один раз на **полный** beam-кандидат;
- сохранить его в candidate trace/meta;
- повторно использовать в ключе, сертификате и экспорте;
- не вызывать морфологическую эрозию на каждом промежуточном placement.

Новых full-chain попыток правка не создаёт. Поэтому TIMEOUT и p95 должны практически не измениться; возможна лишь небольшая стоимость нескольких Shapely-buffer на готовый кандидат.

---

## Что проверить после правки

1. `set5-trapezoid`:

   - выбранный `_route_cm ≥75`;
   - если лучший достижимый только 70–74 — soft `MAIN_ROUTE_BELOW_QUALITY`, но не `<70`;
   - в trace видно старого и нового кандидата с их фактическими `route_cm`.

2. Синтетические сторожа:

   - `60 см + более богатая ступень` проигрывает `≥75 см + менее богатая`;
   - два кандидата `≥75` сравниваются точно прежним ключом;
   - если максимум 60 — `ok=false`, `CIRCULATION_MISSING`, сертификат;
   - 70–74 допустимы только как tier-1 fallback.

3. Полный экзамен:

   - 272/272 без нового terminal failure;
   - dining не ниже 238;
   - media не ниже 269;
   - TIMEOUT 0;
   - p95 не хуже прежнего более чем на шум.

4. Число изменившихся выбранных планов. При точном `_route_cm`-ярусе ожидается **не более одной текущей сцены**, потому что остальные 271 уже имеют маршрут ≥75. Если меняется больше — значит ключ использует не ту метрику или вычисление кандидата расходится с экспортным `_route_cm`.

Итого: **не делать нынешний `MAIN_PATH_TIGHT` hard и не поднимать его вслепую. Ввести отдельный route-tier по той же функции, которой пользуется сторож, поставить его выше preferred/seat richness и добавить финальный floor `<70`.**
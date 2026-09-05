Вывод: A нужен — это реальный wiring-дефект. Но helper не должен быть простым `joint first → return`: совместный камин опционален и не вправе ухудшать обязательные медиа/столовую.

По `media_between_windows`: поправку принимаю — геометрически достижимо. Однако оно получается через общие `wall_candidates` + свободный простенок + ось дивана, а не отдельный tagged-кандидат канона. Это стоит различать в диагностике.

### A. `_media_min`

Согласен с заменой четырёх ранних вызовов: сейчас носитель действительно потребляется на [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:665) до совместной цепочки [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:919).

Но нужны три условия:

- `_media_min(..., top=1, relaxed=False)` должен повторять интерфейс `place_media`. Иначе `_media_lookahead()` передаст `top=K`, получит `TypeError` и тихо отключит защиту столовой: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:450).
- Joint-кандидат принимается только если держит тот же `media_comfort` и dining-lookahead; иначе fallback на обычный `place_media`. Ещё лучше — вернуть оба как кандидаты полного плана, но это дороже.
- Оба зеркала `side_by_side` сейчас first-valid, а не сравнены: [template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2738). После A этот bias станет массовым — надо сравнить оба хотя бы по axis/route/lexo.

Отдельная дыра: `tv_over_fireplace` пока не является полноценным результатом `_media_min`. Код лишь помечает камин и не создаёт носитель/экран: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1113), тогда как `plan_key` считает media только по `тв-тумба|стенка`: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1542). До явного виртуального `screen` либо признака `media_function=true` эту ступень нельзя считать выполненным media-контрактом.

### B. Какой угол считать каноном

Не 60° и не 37,5°. Текущий авторитетный контракт:

- главный диван: ±35°;
- прочая посадка: ±45°;
- каминная secondary-зона: отдельный конус ±75° от кресла.

Это прямо записано в [zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:435) и так же читается валидатором: [validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:1374). `75°/2` здесь неверно: код трактует `cone_deg=75` уже как допустимое отклонение, а не полную ширину сектора.

`fireplace_view_max_deg=60` — устаревший второй источник: [templates.json](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:1280). Его следует убрать/депрекейтить и читать `primary_sector_deg` по фактическому типу посадки.

Причём синхронизировать надо и дистанцию: генератор сейчас фильтрует только `≥90`, а hard-контракт главной посадки требует 200–450 см. Правильнее общий helper:

```text
fireplace_primary_contract(seat):
  sofa  → angle ≤35°, edge distance 200–450
  chair → angle ≤45°, edge distance 200–450
```

Точные 35/45 — продуктовая operational hypothesis, не строительная норма; публичная практика требует комфортной видимости без поворота корпуса, но универсального градусного стандарта нет. Ослаблять hard до 60° без слепых пар не рекомендую.

### Судьба `+tvfp`

Сейчас не убирать и не передвигать. Оставить первым в поздней цепочке как idempotent fallback для путей, где ранний helper не запускался. После полного перевода всех входов:

- ранний `_media_min` и поздний `+tvfp` должны вызывать один общий helper;
- поздний вызов делает мгновенный no-op, если одного из предметов уже нет;
- в тег писать конкретную форму: `+tvfp:side`, `+tvfp:adjacent`, `+tvof`.

Гейты: совместная схема действительно выбирается хотя бы в синтетических сценах каждого типа; dining/media floors не падают; оба зеркала достигаются; `candidate_generated>0, hard_valid=0` из-за рассинхрона углов становится нулём.
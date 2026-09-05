Вердикт: нужен отдельный лексикографический признак деградации шаблона; optional-зоны считать нельзя; beam должен сохранять допуски, но только как явно более слабый fallback.

1. Центрирование и ключ

Сейчас `table_centering` уже существует, но находится в `zone_quality`, поэтому закономерно проигрывает `circulation` ([score.py](/home/pakar/igor/remlab/services/planner-solver/planner/score.py:138), [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1365)). Перенос внутри обычных lexo-термов проблему не решит.

Добавить в v1 и v2 отдельный `template_degradation_key`, но не простой счётчик:

```text
(max_degradation_level, degradation_count)
```

Порядок:

```text
... axis_class,
main_path_contract_violation,
template_degradation,
circulation residual, functional, zone_quality, aesthetics
```

`main_path_contract_violation` нужен потому, что `MAIN_PATH_TIGHT` сейчас soft ([validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:269)): иначе канон может победить вариант, реально сохраняющий проход 90 см.

Классы:

- `0` — канон: столик центрирован, номинальный зазор.
- `1` — допустимый fallback: неноминальный комфортный зазор.
- `2` — осевой сдвиг столика или крайний зазор 32/48.
- Поворот ковра не считать деградацией, если он обеспечивает правило «длинной стороной вдоль дивана».

Вставка — после `_axis_class()` и до `lk[1:]` в [plan_key](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1388) и [plan_key_v2](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1422).

Заодно переименовать `axis_shifted` в `table_axis_shifted`: фактически сдвигается только столик, не ось посадки.

2. Optional-зоны

Не добавлять `-optional_zone_count`. Это прямо противоречит статусам `decor/light/seating_extra=optional`: отсутствие не штрафуется, negative space легален ([zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1010), ADR-0091).

Декор не должен побеждать пустое место просто количеством. Если чтение/quiet требуется для конкретной площади или сценария, повышать именно эту зону до `preferred` с достижимостью — не считать все optional одинаково. Для set16 отдельный бонус `+dc` не нужен: проблему исправляет каноничность столика.

3. Перечисление вариантов

Только `tries[0]` оставлять нельзя: сдвиг или иной зазор может быть нужен не для валидности блока, а чтобы затем собрались медиа/столовая.

Правильная схема:

- Сначала перечислять канонические варианты всех форм и топологий.
- Затем резервировать максимум один деградированный вариант на ступень/форму.
- Деградация может выиграть, если улучшает верхний дискретный ярус — required/preferred-зону, media axis, main-path contract — либо канонической полной цепочки нет.
- В сертификате: `canonical_full_valid`, `degradation_codes`, `fallback_reason`.

Сейчас есть реальное противоречие: паспорт разрешает `axis_shifted`, когда центральных позиций нет ([templates.json](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:144)), а `enumerate_k` продолжает каскад и выдаёт сдвиг наряду с уже найденным каноном ([template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1602)). Комментарий «сдвиг означает centered hard-invalid» верен только для greedy, но не для enumeration ([template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1664)). Также сейчас не маркируются альтернативные gaps и поворот ковра ([template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1520)); media-квота повторяет тот же каскад ([template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1684)).

Минимальные гейты:

- set16-base: поперечное смещение столика от центра дивана ≤2 см.
- Если канон и fallback имеют одинаковый ключ до `main_path_contract`, всегда выбран канон.
- Каждый выбранный fallback имеет сертификат причины.
- Полный экзамен: текущие планки не снижаются, `TIMEOUT=0`; отдельно diff всех сцен, где изменился выбранный вариант.
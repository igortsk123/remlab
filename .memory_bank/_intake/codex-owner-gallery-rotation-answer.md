Вердикт: `rot` надо поднять до жёсткого контракта позы. `set91-base` — семантически неполный pod; `set92-base` вообще не quiet-pod, а основная conversation-группа с ошибочной подписью. Поперечный фланг допустим для разговора, но не должен считаться `media_primary`.

### 1. Контракт ориентации для 3D/LLM

Для каждого направленного предмета экспортировать:

```json
"orientation": {
  "yaw_deg": 270,
  "front_vector_world": {"x": -1, "z": 0},
  "intent": "media_primary",
  "facing_target": {
    "type": "item",
    "role": "тв-тумба",
    "point_cm": {"x": 210, "z": 30},
    "distance_cm": 238,
    "bearing_deg": 241,
    "angular_error_deg": 29
  },
  "relation": "angled_toward",
  "validated": true
}
```

Контракт схемы:

- 2D `(x,y)` солвера → 3D `(X,Z)`, вертикаль `Y`.
- `yaw=0` — фронт модели вдоль `+Z`; положительный угол по часовой сверху.
- Локальный фронт каждого 3D-ассета обязан быть `+Z`. Иначе нужен SKU-level `asset_front_axis`.
- `rot/yaw` — источник истины; `facing_target` — проверяемое объяснение, не команда LLM самостоятельно довернуть предмет.
- Не делать глобальный snap к 90°: `media_half/media_bridge` законно используют 45°. Разрешённая сетка должна задаваться вариантом шаблона.
- Для буквального «лицом к» я бы взял ошибку `≤15°`; `15–45°` — «под углом/вполоборота»; выше — не считать целью. Иначе set26-base с 29° и после исправления останется подписан «к ТВ».

В `plan-NNN.json` добавить поля непосредственно каждому placement: `zone_instance_id`, `template_id/version`, `variant`, `orientation`. Сейчас placement и `_zones` приходится сопоставлять вручную ([export_plans_ai.py](/home/pakar/igor/remlab/tools/scout/export_plans_ai.py:158)). В MD выводить стрелку `→`, intent, цель и фактическую ошибку.

Да, нужен обязательный тест:

```text
pose_hash(role, item_id, x, y, rot)
validated == artifact == plan-NNN
```

Именно сравнение `rot`, а не повторная проверка коллизий: для симметричного прямоугольника `0°` и `180°` имеют одинаковый footprint, но противоположный фронт. Не приводить `rot` через `int()`; экспортировать нормализованный float. Текущая математическая семантика фронта уже едина в [geometry.py](/home/pakar/igor/remlab/services/planner-solver/planner/geometry.py:22).

### 2. Осмысленный второй pod

`set91-base` по новому контракту должен быть отвергнут: нынешний `build_quiet` разрешает два кресла без поверхности ([template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:2535)), а паспорт требует только кресла ([templates.json](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:371)). Практический reading/quiet nook обычно включает свет и небольшую поверхность; пара кресел также нуждается в общем композиционном центре. [Architectural Digest](https://www.architecturaldigest.com/gallery/reading-nook-ideas) рекомендует для reading nook лампу и маленький приставной стол.

Минимально:

- `quiet_chat`: `кресло 3 + кресло 4 + (приставной|малый столик)` обязательно; кресла повернуты на 30–45° к общему центру, а не строго «интервью» 0/180.
- `fireplace_flank`: два кресла по сторонам камина; оба в паспортной вилке расстояния и с ошибкой к камину `≤45°`. Только тогда `facing_target=fireplace`. Парные кресла вокруг камина — нормальная практика, но композиция должна быть пространственно связана с фокусом. [Homes & Gardens](https://www.homesandgardens.com/interior-design/living-rooms/how-to-arrange-furniture-around-a-fireplace)
- Порядок `place_quiet`: достижимый `fireplace_flank` → quiet у окна → quiet в свободном углу.
- Не ставить pod, если нет поверхности/валидного камина, атомарный envelope с доступом не помещается, уже есть богатая primary-группа (`≥2` кресла либо два дивана), уже существует reading/bay pod или не проходит `not_worse`. Fill% здесь только диагностика.

`set92-base` этим не исправляется: кресла 1/2 принадлежат `sofa_2armchairs`. Их intent — `conversation_center`, а камин за 5 м не должен появляться как target.

Также нужен отдельный `check_quiet_contract`: сейчас secondary-кресла полностью пропускаются валидатором ([validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:874)). Проверять состав, поверхность, развороты и выбранный focal target. В текущем Q5 нельзя трактовать любой `missing_zone` как `quality_rejected`: без quiet-диагноза это может быть `template_infeasible`.

### 3. Поперечный фланг

В общей практике боковое кресло допустимо, если оно действительно наклонено к ТВ и не требует неудобного поворота головы; рядом обычно предусматривают доступную поверхность. [Wayfair](https://www.wayfair.com/sca/ideas-and-advice/rooms/how-to-arrange-living-room-furniture-around-a-tv-T24004)

Но контракт владельца строже:

- `media_parallel` — первый вариант;
- `media_half` — второй, если он уменьшает фактическую ошибку до `≤45°`;
- обычный `rot 90/270` — только `conversation`, не `media_primary`.

Не делать `media_half` безусловным default: диагональный footprint сильнее конфликтует со столиком, ковром и зоной доступа. Выбирать между `parallel/half` по готовой hard-valid геометрии и фактическому углу к ТВ; поворот должен участвовать в `_best_block`, а не добавляться после размещения.

Гейты:

- 100% directional placements проходят pose-hash round trip.
- Любой `facing_target` пересчитывается из координат с теми же distance/error.
- 0 quiet-pod без поверхности или валидного камина.
- `fireplace` никогда не заявляется вне его distance/angle contract.
- Каждый `media_primary` кандидат имеет кресло `≤45°`; default-фланг его не сертифицирует.
- Fixtures: set26-base/set30-base/set31-bay/set91-base/set92-base плюс прежние экзаменные floors и `TIMEOUT=0`.
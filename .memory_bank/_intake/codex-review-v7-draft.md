Вердикт: [MASTER-zones-v7.md](/home/pakar/igor/remlab/.memory_bank/plans/MASTER-zones-v7.md) по направлению верен, но как deploy-plan пока неприемлем. Главные блокеры: Q2/Q3 перепутаны местами, Q0 смешивает разные семантики нумерованных ролей, blind-гейт урезан до статистически бесполезных 15 пар, Q5 объединяет четыре независимых риска, а regression gates используют устаревший знаменатель.

## Критические замечания

### 1. Q3 должен предшествовать включению нового `plan_key`

При нынешних формах кресло иногда случайно оказывается ≤45° к ТВ, но гарантированно медиапригодной формы нет. Если Q2 включить первым:

- планы с креслами и углом >45° получат нарушение;
- планы без кресел, скорее всего, получат `not_applicable=0`;
- поскольку медиаконтракт стоит выше `seating_deficit` и фактической посадки, beam начнёт предпочитать armchair-less ступени.

То есть штраф не обязательно будет одинаковым для всех — наиболее опасный вариант именно систематическое выталкивание кресел.

Решение должно быть двойным:

1. Сначала добавить `media_parallel`/`media_bridge`, intent и гарантированную квоту этих форм в пуле гипотез.
2. Даже после этого применять tier только по сертификату достижимости:

```text
reachable_media_seat_ok =
  существует hard-valid media_primary-гипотеза
  с креслом основной группы и фактическим angle_to_actual_tv <= 45°
```

Если сертификат ложен, tier нейтрален для всех кандидатов, а артефакт получает `SEARCH_GAP_MEDIA_SEAT`; отсутствие кресла регулируется поздним `seating_deficit`, а не считается выполненным медиаконтрактом. `quiet`, `conversation` и `fireplace` от него освобождаются.

Важно: `0°/45°/315°` в локальном `build_block` ещё не гарантируют ≤45° к фактически поставленному ТВ, особенно при offset/corner media. Проверять надо законченный seating+media план, не локальную ротацию.

### 2. Blind-гейт искажен

Предыдущая рекомендация была 80 новых пар + 12 скрытых повторов, минимум 60. Draft сократил это до 15 и перенёс правило `8/15` с изолированного свойства на весь раунд.

Правильный протокол:

- исходные 10 пар — только discovery/smoke: воспроизвести метрики и ожидаемое ранжирование, но не калибровать по ним;
- 80 новых пар на ранее не использованных сценах;
- внутри них по 15 one-property сравнений для пяти поднимаемых контрактов: маршрут, media-seat, dining-cone, corner, frontal composition;
- оставшиеся 5 — целостные сложные планы;
- 12 скрытых повторов с инверсией A/B;
- пороги и порядок ключа замораживаются до начала;
- минимум по классам: 20 сцен `<20 м²`, 20 `20–29.9`, 20 `≥30`, из них ≥10 `40+`; ≥20 elongated, ≥20 сложных контуров, ≥20 сцен с 2+ проёмами;
- отдельно покрыть 0/1/2/4 кресла, прямой/Г-диван, банки с/без media-installation.

Фальсификация каждого tier: если нарушающий вариант выбран в ≥8 из его 15 изолированных сравнений — tier не включать. Если решающих ответов меньше 10, результат считается неопределённым, а не пройденным.

Общий deploy-гейт: на решающих новых парах нижняя граница 95% Wilson CI для доли побед нового выбора должна быть >0.5; повторяемость — не менее 10/12. Иначе остаётся shadow.

### 3. Q0 «передать все роли» небезопасен

Сейчас адаптер разрушительно сворачивает `... 2` через `replace(' 2','')`, затем восстанавливает `qty` и отдельно `диван 2` ([solver_run.py](/home/pakar/igor/remlab/tools/scout/solver_run.py:31)). Простая отмена whitelist затронет сразу несколько разных моделей:

- `кресло 2` может быть вторым экземпляром `qty=2` или независимым alt-SKU — это коллизия имён;
- `диван 2` бывает членом двухдиванного шаблона и запасным прямым диваном вместо углового;
- `кресло 3/4` одновременно доступны `sofa_4armchairs`, `quiet`, reading и fireplace;
- появление 3/4 в `items` меняет `counts`, верх лестницы и делает доступной `sofa_4armchairs`, хотя composer мог предназначать их второй зоне;
- `стеллаж 2` поддержан не везде, `комод 2` заявлен в паспорте, но отсутствует в `STORAGE_ROLES`;
- phantom-dimensions привязан к имени роли. При превращении запасного `диван 2` в роль `диван` он может сравниваться с габаритами главного дивана;
- увеличение `items` переключает двухпроходную ветку, расширяет beam и особенно опасно при `large_xl=1×2`, где одна гипотеза уже занимает 5–7 минут.

Минимальный безопасный первый проход:

- сохранить raw bank без нормализации;
- развести `sku_id/instance_id`, `base_role`, `bank_role` и `usage_scope`;
- `qty`-копии создавать только при отсутствии явной роли с тем же именем;
- существующую семантику `диван 2` пока не расширять;
- независимое `кресло 2` допускать только как `main_group` и без конфликта с `qty`;
- `кресло 3/4` сначала активировать только как `secondary_quiet`, исключив из main-ladder counts;
- `стеллаж 2`/`комод 2` оставить shadow до отдельного storage-пакета.

`_bank_unused` требует более полной таксономии:

```text
adapter_excluded
not_claimed_by_enabled_template
template_infeasible
quality_rejected
feasible_not_selected
reserved_alternative
placed
```

Текущие четыре причины не позволяют отличить «hard-valid, но проиграл ключ» от «вообще не генерировался».

### 4. Q5 надо разделить

Реалистичная последовательность:

1. Capability/data model.
2. Синтетически тестируемый `build/place_edge_nook`.
3. End-to-end `alternative_bundles` для nook.
4. `round_compact` с круговым footprint.
5. `wall_run_low_storage`.
6. `behind_sofa_low_storage` после data-audit и моделирования открывания ящиков.

`dining_foldable` остаётся sleeping до `closed_w/d`, `open_w/d`, `usable_seats_closed`, `closed_state_is_dining`.

Первый видимый выигрыш вообще — существующий second seating pod после безопасной передачи `кресло 3/4`. Первый видимый каталожный выигрыш — end-to-end `edge_nook`; один data-layer или builder владельцу ничего не покажет. Console следует делать последней: полезный пул пока не доказан.

### 5. Что draft потерял или исказил

- Корпус уже содержит 272 сцены, не 252. Мой read-only подсчёт текущих отчётов: 269 valid + 3 certified `MEDIA_MISSING`, media 269, dining в текущих артефактах 235. Поэтому `media 252` и `dining ≥220` либо устарели, либо понижают текущие планки — это запрещено.
- `frontal_composition_class` имеет неверную/неопределённую полярность: в ключе «меньше лучше», поэтому raw-класс `0/1/2` наградит пустую стену. Нужен `frontal_composition_deficit`.
- `armchair_tv_dist_ratio_max = 1.0 + 30 см` размерностно неверен. Должно быть `d_chair_tv <= d_sofa_tv + 30 cm`, отдельно — попадание в screen-based viewing range.
- В верхушке ключа потерян `unplaced_required_items`. Текущий `plan_key` выбрасывает `lk[0]`, где учитывался unplaced.
- `realized_seats` и `has_footrest` не определены данными. Наличие роли `пуф` не доказывает footrest: он может быть столиком, flex-seat или storage.
- Ranking не создаёт кандидатов. Frontal installation, альтернативный dining и новые формы должны сначала гарантированно попасть в пул.
- Локальный `_zones` агрегирует по `tpl_id`, а не по уникальному instance. Этим нельзя надёжно измерить две зоны и атомарность каждой из них.
- Прежний blind-протокол — стратификация, скрытые повторы, Wilson CI и запрет перенастройки — почти полностью выпал.
- Из каталожного аудита потерян clearance открывания ящиков за диваном.
- Указание `weights.json` среди предполагаемых файлов опасно: новые приоритеты обязаны быть отдельными лексикографическими полями, не весами.

## Исправленный порядок и машинные критерии

Для каждого selection-changing пакета действует общий гейт: один frozen manifest из 272 scene IDs + hash банка/правил/flags; ни одна принятая regression-планка не снижается; новые пороги только в JSON с provenance; 0 phantom dimensions; атомарный состав по точному multiset каждого zone instance; канонический hash одинаков в повторных запусках и при другом порядке сцен; новых timeout нет, p95 ≤1.5× baseline.

1. **Q0 — baseline, диагностика, metric contract.**

   Зависимостей нет. Выбор плана должен быть бит-в-бит прежним; blind-сигнатуры воспроизводятся с заданным допуском; метрики покрыты fixtures для rectangle/L/trapezoid, нескольких дверей и стенки как носителя.

2. **Q1 — identity-aware adapter в shadow.**

   Зависит от Q0. Каждый входной SKU имеет ровно один terminal disposition; явный `кресло 2` не перетирается `qty`-копией; SKU ID и размеры проходят до `Item`; при flags off output hash равен Q0. Первая активация ограничена scope, описанным выше.

3. **Q2 — правила и provenance.**

   Зависит от Q0. `rules_audit == 0`; каждое число имеет `value/unit/semantics/provenance/status`; нет новых threshold literals в Python; новые поля не добавлены в weighted score. `TALL_ON_TV_WALL` освобождает только компаньона того же атомарного `media_installation`, а не любой высокий предмет на стене.

4. **Q3 — media-aware shapes + reachability certificates.**

   Зависит от Q1+Q2. Для каждого `media_primary` fixture с достижимой геометрией в пуле есть hard-valid кандидат ≤45° к фактическому ТВ; pair05/09 — только smoke. Старые conversation/quiet формы остаются достижимыми. `large_xl` имеет quota хотя бы на одну media-aware форму, а не только первые две позиции default.

5. **Q4 — новый `plan_key`, сначала shadow.**

   Зависит от Q3. Ключ должен начинаться так:

   ```text
   hard_count,
   missing_required_zones,
   unplaced_required_items,
   entry_sightline_violation,
   media_seat_violation_if_reachable,
   dining_view_cone_violation,
   small_room_corner_violation,
   missing_reachable_valid_preferred,
   frontal_composition_deficit,
   seating_deficit,
   -realized_armchairs,
   -realized_valid_flex_seats,
   -has_actual_footrest,
   axis_class, circulation, functional, zone_quality, aesthetics
   ```

   Unit-тесты доказывают доминирование каждого tier над всеми нижними. Первые 10 пар проходят smoke, но production promotion запрещён до Q7.

6. **Q5 — area seating и second pod.**

   Зависит от Q1+Q4. Пара 3/4 — одна модель либо подтверждённая коллекция; случайная пара запрещена. В сцене не допускается один armchair, если существует кандидат с ≥2 креслами и тем же или лучшим префиксом ключа до `seating_deficit`. Для 40+ — hard-valid second-zone candidate либо машиночитаемая причина `inventory_gap/template_infeasible/quality_rejected/search_budget_exhausted`.

7. **Q6a — capability model.**

   Все 152 кушетки сохраняют `catalog_role`; capability не удаляет остальные 110; `seat_height` не выводится из общей `h`; evidence хранится по каждому capability; исключённые категории проверяются по source/category ID.

8. **Q6b — `edge_nook` builder.**

   Зависит от Q6a. Точный атом: банкетка + стол + ≥2 стула или ничего; уникальный zone instance; спинка к стене; стулья только со свободных сторон; door swing, pullout и route проходят hard.

9. **Q6c — nook bundles и production cascade.**

   Зависит от Q6b. После добавления bundle заново считаются total/style/diversity/identity/envelope; максимум один dining/residual bundle. На frozen eligible-cohort доля naked edge строго снижается; ни один hard-valid island не заменяется nook.

10. **Q6d — round compact.**

    Зависит от Q6a. Круг моделируется окружностью с реальным диаметром, не квадратным bbox; SKU-габарит не меняется; старые island floors не падают.

11. **Q6e — low storage/console capability.**

    Зависит от Q6a. Новой глобальной роли `консоль` нет; `d<=40`, относительная высота и ширина читаются из JSON; для комода проверяется service envelope ящиков; wall-run выпускается раньше behind-sofa.

12. **Q7 — blind validation и rollout.**

    Зависит от всех активируемых пакетов. Протокол 80+12, per-tier falsification, Wilson CI, frozen labels/thresholds. Только после него shadow можно сделать default.

## Топ-5 рисков

1. **Priority inversion и вытеснение кресел.**  
   Митигация: Q3 до Q4, двухфазный candidate-pool, certificate-gated tier.

2. **Коллизия роли и экземпляра.**  
   Митигация: `instance_id/base_role/usage_scope`, запрет silent overwrite, phantom check по SKU ID.

3. **Переобучение на 10 сценах.**  
   Митигация: discovery-only smoke, 80 unseen +12 repeats, изолированные контрфактуалы и предрегистрация.

4. **Search explosion и недетерминизм.**  
   Митигация: topology quotas, отдельные бюджеты intent-классов, fresh/same-process hash-тесты, no-new-timeout gate.

5. **Ложные catalog capabilities и неатомарные bundles.**  
   Митигация: evidence per attribute, role conservation, exact zone-instance multiset, model-family counts вместо числа цветовых offers.

## Что действительно спросить у владельца перед деплоем

1. Готов ли он оценить 80 новых пар +12 скрытых повторов без промежуточного раскрытия результатов и перенастройки правил?
2. Включать ли owner-derived `dining 45°/10%` и нормы ТВ-стены `1/2 companions` сразу, либо держать их shadow до прохождения соответствующих 15 контрфактуалов? Рекомендую shadow.
3. Допустимы ли три честных `MEDIA_MISSING` как пользовательский отказ «решение не найдено», или deploy блокируется до 272/272 с носителем?
4. Выпускать ли core-ranking/second-pod отдельно от каталожной волны, или ждать end-to-end `edge_nook`? Технически безопаснее и быстрее — два релиза.

Файлы не изменялись.

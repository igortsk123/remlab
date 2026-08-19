## Вывод

Направление верное, но я бы не заменял `seat_rank` простым числом всех кресел/диванов. Его надо разложить:

- `seat_rank` оставить только для порядка поиска лестницы;
- финальный план сравнивать по реально реализованной вместимости;
- LEVEL A защитить отдельным условным ярусом дивана;
- обязательно добавить beam-гипотезу переноса кресла — одного изменения ключа недостаточно.

### а. Фактическая вместимость

Минимально безопасная метрика:

```text
capacity =
  canonical_seats(selected_primary_group)
  + valid seats outside primary seating
```

То есть:

- `sofa_armchair`: паспортные 4 места;
- `sofa_lamp + window_anchor`: 3 + 1 = те же 4;
- quiet-пара добавляет 2;
- flex-seat/footrest остаются отдельными нижними компонентами.

Это надёжнее попытки сейчас вычислять места дивана по SKU: у `Item` нет подтверждённой вместимости диванов, а `zones.json` уже содержит паспортные `seats`: [zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:54). Позже можно перейти на `caps.guaranteed_seats`, но не выводить места из ширины новым незафиксированным порогом.

«Валидное внешнее место» считать только если:

- весь план hard-valid;
- кресло принадлежит разрешённой атомарной зоне: `quiet`, `reading`, `bay_armchair`;
- контракт экземпляра зоны выполнен;
- для `reading/window_anchor` фактически подтверждены привязка к окну и допустимая ориентация;
- для обычного reading есть компаньон;
- случайное кресло только с непустым `tpl_id` не засчитывается.

Нынешний `valid_connected_armchairs` пока слишком либерален: любое кресло с любым `tpl_id` считается валидным: [view_metrics.py](/home/pakar/igor/remlab/services/planner-solver/planner/view_metrics.py:172). Перед использованием в production-ключе нужна явная whitelist и variant-specific проверка.

Одиночное кресло `window_anchor` считать полноценным местом правильно: его композиционный якорь — окно, и исключение уже зафиксировано паспортом: [templates.json](/home/pakar/igor/remlab/services/planner-solver/rules/templates.json:468).

### б. Место яруса

Для минимальной смены политики:

```text
hard
→ missing_required
→ primary_sofa_missing_if_reachable
→ -covered_pref
→ -realized_regular_capacity
→ -valid_flex
→ -footrest
→ axis_class
→ main_path
→ template_degradation
→ orphan_back_gap
→ circulation / functional / zone_quality / aesthetics
```

То есть вместимость занимает нынешнее место `-seat_rank`: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1488). `covered_pref` сохраняется выше — оконное кресло не должно вытеснять достижимую dining-зону.

Порядок `axis/degradation/orphan` пока не менять: иначе Q10 одновременно перепишет ещё три ранее согласованные политики. Q9-prior позже остаётся ниже functional/zone-quality, поэтому не сможет предпочесть кресло у окна ценой плохой функции.

Отдельный сторож: если перенос единственного кресла уничтожает достижимый контракт «кресло смотрит ТВ», планы функционально неравны. Такое перемещение либо отклонять `not_worse`-гейтом по seat intents, либо оставлять проигрывать нижнему functional tier.

### в. LEVEL A

Саму лестницу это не ломает: LEVEL A уже защищён в генерации и dining-sacrifice независимо от ключа: [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:620), [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:256).

Но для beam нужен отдельный бинарный контракт:

```text
primary_sofa_missing =
  sofa_in_bank && sofa_candidate_reachable && sofa_not_in_plan
```

Он должен стоять выше `covered_pref`. Если ни одна диванная ступень hard-valid, бездиванный fallback остаётся разрешён. То есть «диван обязателен, когда достижим», а не безусловно.

### г. Честный замер

Сначала сделать отдельный shadow-ключ `v1_capacity`, меняющий только `seat_rank`. Не смешивать его с большим v2.

Целевая когорта:

- окно есть;
- старый план забрал ровно одно кресло в primary;
- существует full-valid `sofa-only + window_anchor`;
- диван, media, dining и фактическая вместимость не хуже;
- media-seat intent не ухудшен.

Ожидаемые изменения — только внутри этой когорты. Не надо ждать изменения всех 113 сцен. И замечание: по абсолютным цифрам геометрический отказ всё ещё больше — 149 против 113; распределение является главным **устранимым архитектурным** блокером, но не единственным.

В сертификат:

```text
window_transfer:
  applicable
  lower_step
  capacity_old/new
  primary_sofa_preserved
  media_intent_old/new
  full_valid
  selected
  reject_reason
```

Гейты:

- LEVEL A: 100%;
- dining ≥238, media 269, TIMEOUT 0;
- capacity выбранного плана не ниже старой;
- ноль prior/capacity-flip с потерей required/preferred;
- p95 ≤1.2×;
- слепые пары по всем выбранным переносам либо выборка 20.

### д. Нужна ли явная beam-гипотеза

Да. Это не альтернатива изменению ключа — нужны оба изменения:

- без гипотезы движок часто вообще не построит `sofa_lamp/sofa_solo + window_anchor`;
- с гипотезой, но старым `seat_rank`, она гарантированно проиграет.

Добавить условное семейство `window_armchair_transfer`:

- только если окно есть;
- primary забрал единственное кресло;
- вторичного кресла нет;
- одна каноническая нижняя диванная ступень;
- одна лучшая оконная позиция;
- один полный прогон внутри существующего cap, не сверх него.

Перед дорогим прогоном сделать дешёвый precheck блока и оконного footprint. Так попытка затронет только часть 113 сцен и почти не повлияет на p95.

Итого: **разложить `seat_rank`, добавить conditional sofa guard и одну reserved transfer-гипотезу**. Это исправляет системную ошибку «место считается богатством только внутри главной группы», не превращая кресло у окна в обязательную мебель ради процента.
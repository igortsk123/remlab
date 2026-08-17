Вывод: Q5 по поиску прошёл, production-выбор менять до Q7 не надо. Но каталог Q5 пока нельзя считать принятым из-за Nonton, а сертификаты `pod_not_placed` требуют уточнения.

### 1. Честный гейт Q5

Считать по сертификатам:

- для 40+ м²: `second_pod.full_valid` либо точная терминальная причина;
- `two_sofa.full_valid` — отдельный гейт достижимости семейства;
- `QUIET_POD_* = 0`, голых pod = 0;
- текущие планки, `TIMEOUT=0`.

Выбранные `quiet=4` не должны быть гейтом до Q7: v1 намеренно предпочитает rich primary, а сертификат доказывает альтернативу. Владельцу сочетание «диван + 2 кресла + столовая + медиа + ещё quiet-pod» без отдельной функции, скорее всего, не понравится — он уже сказал про №181: «что это и зачем такое, если уже есть зона отдыха одна».

Практика допускает несколько зон не из-за одной площади, а при разных функциях — чтение, камин, разговор, игры — и сохранённом потоке. Дизайнеры одновременно требуют достаточного negative space и проходов; площадь сама по себе не оправдывает дополнительную мебель. [Homes & Gardens: purposeful zones and circulation](https://www.homesandgardens.com/interior-design/the-library-how-to-design-the-perfect-living-room-layout), [House Beautiful: multiple seating zones depend on purpose and flow](https://www.housebeautiful.com/design-inspiration/a71887984/living-room-layout-seating-zones/).

Поэтому:

- `primary_rich` не делать просто зависимым от площади;
- позже разрешить исключение только для отдельного архитектурного назначения: достижимый камин/эркер/окно + отдельный регион + проход;
- v2 включать только по результату Q7, не автоматически.

Ещё замечание: v2 всё ещё имеет `-_valid_arm` отдельным ярусом в [zones.py:1502](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1502), поэтому после категориального равенства он снова предпочитает кресла второму дивану. Именно это, вероятно, даёт 68 переключений на compact+quiet. Перед Q7 этот ярус надо убрать либо заменить эквивалентной вместимостью программы.

Из 10 `pod_not_placed`:

- 8: оба варианта `no_valid_position`;
- 2: `quiet_diag.placed=quiet_chat`, но `+qz` отсутствует — почти наверняка placer сработал, затем pod отверг `not_worse`.

Эти две сцены должны стать `quality_rejected`; сейчас [zones.py:960](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:960) не записывает отказ quality-gate в `QUIET_DIAG`. После этого сертификат будет честным.

### 2. Two-sofa: корень не преимущественно в размерах

Разбор 32 сцен с `block_generated=0`:

- **22/32**: главный диван угловой; ветка немедленно возвращает `None` по `sofa.corner` в [template.py:598](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:598). Три reject-кода — не три независимых провала, а один общий неподдерживаемый subtype.
- 5 сцен имели hard-valid блок в общей лестнице, но семейство не получило разрешённый вариант: часть — только `square`, исключённый политикой [zones.json:1146](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1146), часть — без media-min.
- Остаток — реальные позиционные отказы, включая большие диваны.

`d=None` не проходит в solver как `None`: адаптер подставляет 95 см в [solver_run.py:82](/home/pakar/igor/remlab/tools/scout/solver_run.py:82). Это риск достоверности каталога, но не непосредственная ошибка вычисления. Клоны кресел также не главный корень: `sofa_loveseat` без кресел проваливается вместе с двумя кресельными группами.

Минимально:

1. В сертификате различать `unsupported_subtype:corner_main`, `shape_policy_excluded`, `no_media_min`, `hard_geometry`.
2. Добавить зеркальные `L-left/L-right`: `_add_L` сейчас всегда ставит второй диван слева ([template.py:450](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:450)); это реальная дыра поиска.
3. Не уменьшать `L_GAP=20` и не ослаблять hard.
4. `sectional+straight_sofa` — отдельный будущий шаблон, а не снятие corner-guard.
5. Пробросить `fits/validated/top_reject` из `_best_block` в family certificate.

Интерпретация ZDBG:

- `fits=0, top_hard=None` → конверт/кандидаты;
- `top_hard=WINDOW_BLOCKED/COLLISION/...` → реальная hard-геометрия;
- `NO_CENTERED_BEARER/NO_ROOM_FOR_BEARER` → конфликт с media-min;
- ранний `None` без `block[...]` → build guard/subtype.

Планку 37 нельзя переносить на новые sets3 и нельзя молча снизить до 30. Оставить ≥37 на замороженной старой когорте; для новых сетов вести долю `full_valid / eligible`, исключив неподдерживаемый corner-subtype, пока не появится его шаблон.

### 3. Nonton — обязательный hard-фильтр

Да: не «предпочесть живой фид», а **запретить broken/stale для нового pod**.

Сейчас баг явный:

- Nonton имеет `state=broken`, но `mids=[]`, а `116933` лежит в `mids_quarantine_pending` ([feed-freshness.json:22](/home/pakar/igor/remlab/tools/scout/feed-freshness.json:22)).
- `compose2` исключает только `rec.mids`, поэтому 116933 остаётся в пуле ([compose2.py:245](/home/pakar/igor/remlab/tools/scout/compose2.py:245)).

Минимальный фикс: для `state in {broken, stale}` объединять `mids + mids_quarantine_pending`; хотя бы для `pod_kit` — fail-closed. Если свежего компактного комплекта нет, результат должен быть `inventory_gap`, а не stale-SKU.

После исключения 116933 sets3/pod-комплекты нужно пересобрать и повторить каталоговый гейт. Нынешние 72/72 доказывают геометрию pod, но не товарную доступность.
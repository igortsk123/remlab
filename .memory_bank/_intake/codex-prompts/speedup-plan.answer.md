Вывод: пункты 1–4 правильные. `large_xl cap 3→2` для боевого режима не делать; 10 воркеров сначала подтвердить замером. Главные быстрые выигрыши — render-only, корректный кэш, планирование тяжёлых сцен и устранение повторных полных цепочек.

### А. Риски smoke и кэша

Smoke — только обратная связь, не гейт закрытия пакета: он пропустит редкую комбинацию геометрии, банка и шаблона, а также конкурентные TIMEOUT.

Ключ solver-кэша считать по содержимому:

```text
scene JSON
+ точный банк этого set
+ planner/**/*.py
+ rules/**/*.json
+ solve-часть адаптера
+ engine/search profile и все LAYOUT_*
+ версии Python/Shapely/Pydantic
+ schema_version
```

Не использовать git commit или mtime: дерево бывает dirty. Пока брать полный хеш `planner/` и `rules/`, а не граф зависимостей — динамические импорты и глобальные режимы делают граф ненадёжным. Изменение общего правила честно инвалидирует все сцены; изменение одного банка — только сцены его set.

Текущий `_set_hash` покрывает лишь `items` ([solver_run.py](/home/pakar/igor/remlab/tools/scout/solver_run.py:969)). Resume сейчас доверяет одному `scene id` ([acceptance_run.py](/home/pakar/igor/remlab/tools/scout/acceptance_run.py:94)) — прямой запуск после изменения может подхватить устаревшее. Нужен `solve_key` в каждой строке.

Дополнительно:

- Не кэшировать TIMEOUT/crash; сертифицированный `MEDIA_MISSING` можно.
- Первое включение: cold/warm прогоны должны дать byte-equivalent смысловые артефакты; затем 5% cache-hit сцен перепроверять.
- Экзамену лучше читать снимок `sets3.json`, а не живой файл. `exam.lock` — хорошая первая защита ([run.sh](/home/pakar/igor/remlab/tools/scout/run.sh:19)), но snapshot/`flock` защищает и от SIGKILL/ручного запуска.
- Solver- и render-кэш разделить: сейчас JSON пишется и сразу начинается PNG-код ([solver_run.py](/home/pakar/igor/remlab/tools/scout/solver_run.py:1040)).

Для `compose2`: существующие `SETS_ONLY` и обратный индекс уже дают основу ([compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:533), [sets_incremental.py](/home/pakar/igor/remlab/tools/scout/sets_incremental.py:30)). Но изменение общей логики композиции, правил или появление новых лучших товаров требует полного пересчёта: из-за глобального разнообразия затронуты могут быть не только сеты, где товар уже стоял.

### Б. Smoke около 40 сцен

Не полный `band×shape`, а детерминированный pairwise-набор:

- 18 сцен: покрытие `room_mode × contour × openings`; каждый класс минимум дважды. Контуры: base, long, bay, pylons, trapezoid/L; проёмы: обычные, 2 doors, balcony, multiwindow.
- 10 сцен: семантические ветки — corner sofa, pair_sides, U, two_sofa, compact+quiet, media installation, fireplace, dining island, dining edge, window waiver.
- Все 3 сертифицированных `MEDIA_MISSING`.
- Около 9 сцен владельца: все открытые замечания плюс по одному минимальному репро на каждый уже закрытый класс бага, а не бесконечный список дублей.

Три самых тяжёлых XL вынести в отдельный `perf-smoke`: включение 7–9-минутной сцены несовместимо с обещанием smoke ≈5 минут.

### В. `large_xl cap`

Не снижать боевой cap. Сейчас XL-порядок: `pair_sides → compact+quiet → two_sofa`, а cap=3 ровно покрывает эти три семейства ([zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1208), [zones.json](/home/pakar/igor/remlab/services/planner-solver/rules/zones.json:1230)). При cap=2 `two_sofa` систематически не дойдёт до полного прогона; сертификат станет `search_budget_exhausted`, а достижимость будет занижена.

Допустим отдельный `search_profile=fast`, но его результаты нельзя использовать для галереи, полов, сертификатов и сравнения качества. Лучше сократить число сцен, а не глубину поиска одной сцены.

### Г. Что профилировать первым

Сначала добавить `_perf`: время и число вызовов по `family/place_template/full_chain/media/dining/validate`, плюс `duration_s` в acceptance-report.

Приоритеты:

1. `_best_block`: до 24 полных `validate`, затем до 24 проб носителя на каждую позицию ([template.py](/home/pakar/igor/remlab/services/planner-solver/planner/template.py:1264)). Это вероятный главный множитель.

2. Повторные полные цепочки: greedy считается отдельно, затем семейства снова вызывают `solve_zoned` ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1576), [zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:1705)). Сначала измерить дубли по ключу блока, затем мемоизировать точные гипотезы.

3. Media lookahead повторно строит top-3 media и пробует dining ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:427)). Возвращать top-K из первого вызова и переиспользовать.

4. `validate()` всегда выполняет весь набор проверок ([validate.py](/home/pakar/igor/remlab/services/planner-solver/planner/validate.py:1506)). После профиля — отдельный быстрый hard-only путь для поиска с обязательным тестом эквивалентности полному валидатору.

5. Кэшировать на сцену `usable_polygon`, статические блокеры и подготовленные геометрии; сейчас `usable_polygon` пересобирается многократно ([zones.py](/home/pakar/igor/remlab/services/planner-solver/planner/zones.py:67)).

Ещё бесплатный выигрыш: писать длительности и запускать исторически тяжёлые сцены первыми, ограничивая одновременно XL до 2–3, а свободные воркеры заполнять малыми. Сравнить 6/8/10 воркеров по общей длительности, p95 сцены и peak RSS; 10 не гарантированно быстрее из-за CPU/cache contention.

### Д. Порядок внедрения

1. Телеметрия времени, snapshot банка, надёжный lock.
2. Вынести render-only.
3. Зафиксировать smoke-manifest и отдельный perf-smoke.
4. Content-addressed solver/render cache с cold/warm-аудитом.
5. Инкрементальный compose с dry-run: «какие сеты и почему»; общий код/правила → `ALL`.
6. По профилю: дедуп full-chain → переиспользование media top-K → room geometry cache → hard-only validate.
7. После этого подобрать число воркеров. Боевой `large_xl cap=3` оставить.
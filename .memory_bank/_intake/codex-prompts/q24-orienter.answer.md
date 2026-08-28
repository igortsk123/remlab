## Вывод

Схема практична как исследовательский challenger и источник полного `up/front/side`, но не как готовая замена текущему `mesh_front`. Для нашей системы правильный порядок такой:

1. raw GLB и геометрический gate;
2. `3d-orienter` предлагает полный `raw_to_canonical`;
3. для сидячих ролей `mesh_front` остаётся авторитетом по переду после выравнивания `up`;
4. при конфликте — abstain/человек, не автоматический VLM;
5. GLB не меняется, рядом хранится версионированный quaternion/matrix.

На DEV-VM спайк 40 мешей возможен, но время нельзя честно назвать до прогона первых пяти: upstream не публикует CPU-бенчмарк. Массовые 30k на этой VM нерациональны — после проверки контура вычисление следует переносить на Salad.

## 1. Что реально представляет собой `3d-orienter`

Репозиторий настоящий: это официальный код работы ICML 2025. Есть quotient-orienter, flipper, pretrained checkpoints, нормализатор, генератор txt-индекса и `two_stage_inference_script.py`. Upstream ожидает нормализованные OBJ и сохраняет ориентированные OBJ. [Официальный репозиторий](https://github.com/cscarv/3d-orienter), [статья ICML/PMLR](https://proceedings.mlr.press/v267/scarvelis25a.html).

Но внешний совет переоценивает готовность:

- README не обещает CPU inference и не даёт CPU/GPU latency.
- Не документирован production API вида `rotation + confidence + APS`; штатный интерфейс — «входные OBJ → выходные ориентированные OBJ». Извлечение матрицы, вероятностей и candidate set потребует обёртки/правки исследовательского кода.
- APS присутствует в benchmark-скрипте, но это ещё не означает, что штатный inference его возвращает.
- Модель обучена на ShapeNet. Сами авторы прямо называют надёжную полную ориентацию произвольных форм открытой задачей; Hunyuan/Trellis-меши с артефактами — отдельный domain shift.
- Лицензия кода — GPL-3.0. Коммерческое внутреннее применение возможно, но распространение модифицированного контейнера/сервиса требует лицензионной проверки. Условия именно checkpoint-файлов отдельно не разъяснены.
- Репозиторий небольшой: 10 коммитов, без релизов; это research artifact, не поддерживаемый сервис.

DEV-VM: 6 физических/12 логических ядер i5-13400F, 9.8 GiB RAM, swap уже используется, Torch CPU-only; Poetry не установлен. Ставить зависимости в `~/venvs/scout` нельзя — только отдельный venv или контейнер с зафиксированными commit/checkpoint hash.

Оценку 40 моделей предлагаю сделать условной:

- если после прогрева `p95 ≤60 с/меш` — около 40 минут последовательно;
- при `p95 ≤120 с` — около 80 минут;
- если `p95 >120 с`, RSS >7 GiB либо растёт swap — CPU-спайк остановить и тот же контейнер перенести на Salad.

Для 30k даже 60 с/меш означают 500 часов последовательного CPU. DEV-VM годится для отладки и ежедневных единичных дельт, не для массового прогона.

## 2. Нужен ли DINOv2/CLIP

Не первым этапом.

`DINO/CLIP(render, photo)` отвечает на вопрос «какой рендер похож на фотографию», но не «где у предмета семантический перед». Каталожное фото может быть снято сзади или в три четверти. Более того, текстура Hunyuan могла быть получена из того же фото — свидетельство будет коррелированным.

Это не дубликат `mesh_front`, но и не полноценный независимый судья:

- `mesh_front` ищет сиденье и спинку в геометрии;
- image matching восстанавливает направление каталожной камеры;
- orienter использует статистический канон ShapeNet.

Для первого спайка достаточно уже существующего дешёвого слоя: четыре, лучше восемь, рендеров + silhouette IoU + spatial color grid в [mesh_orient.py](/home/pakar/igor/remlab/tools/scout/mesh_orient.py:118). Если он не различает размеченные виды, в репозитории уже есть оба CPU-challenger: DINOv2 в [sku_bench.py](/home/pakar/igor/remlab/tools/scout/sku_bench.py:109) и CLIP/FastEmbed в [compose2.py](/home/pakar/igor/remlab/tools/scout/compose2.py:205).

Рекомендация по авторитету:

- стул/кресло/диван: `up` от orienter, `front` от `mesh_front`;
- кровать/шкаф: orienter как primary только после локального gold-set;
- DINO/CLIP: evidence/shadow;
- Qwen/VLM: только предложение человеку. Автоматический `+180°` не разрешать — ваш собственный тест уже показал систематическую ошибку на стуле.

## 3. Стыковка с текущим кодом

Здесь обнаружено расхождение документации с реальностью.

В плане написано, что геометрия сиденья уже стала авторитетом [viz-mesh-orientation.md](/home/pakar/igor/remlab/.memory_bank/plans/viz-mesh-orientation.md:136), но `infer_seat_front()` нигде не вызывается вне собственного CLI. `mesh_orient.calibrate()` продолжает работать только через фото, силуэт и цвет. Это надо закрыть до добавления нового orienter.

Дополнительно:

- [mesh_front.py](/home/pakar/igor/remlab/tools/scout/mesh_front.py:45) предполагает, что `Y` уже является верхом, и проверяет лишь четыре горизонтальные оси. Поэтому сначала нужен `up` от orienter, затем seat-front.
- `банкетка` безусловно объявлена симметричной [mesh_front.py](/home/pakar/igor/remlab/tools/scout/mesh_front.py:25). Это неверно для банкетки со спинкой: симметрию надо выводить из capability/subtype, а не только роли.
- `facing_target` уже правильно существует на уровне плана: [models.py](/home/pakar/igor/remlab/services/planner-solver/planner/models.py:126), [export_plans_ai.py](/home/pakar/igor/remlab/tools/scout/export_plans_ai.py:191). Он задаёт, куда предмет должен смотреть. Asset orientation лишь превращает локальный перед меша в этот плановый `rot`.
- [scene_mesh.py](/home/pakar/igor/remlab/tools/scout/scene_mesh.py:60) применяет `ry(-front_yaw)`. При этом комментарий на строке 10 всё ещё пишет противоположный знак — опасная ловушка для миграции.
- Манифест [mesh_gate.py](/home/pakar/igor/remlab/tools/scout/mesh_gate.py:50) хеширует лишь `front_yaw`, но не версию `mesh_front`, checkpoint orienter и полный transform.

`canonicalRotation` не должен быть тремя Euler-углами. Нужен однозначный контракт:

```json
{
  "orientation_version": 2,
  "raw_glb_sha": "...",
  "raw_to_canonical_quaternion_xyzw": [0, 0, 0, 1],
  "canonical_axes": {"front": "+Z", "up": "+Y"},
  "status": "confident|ambiguous|symmetric|review",
  "equivalent_rotations": [],
  "source": "3d-orienter+mesh_front",
  "source_versions": {
    "orienter_commit": "...",
    "checkpoint_sha": "...",
    "mesh_front_version": 2
  },
  "evidence": {}
}
```

Направление преобразования надо назвать именно `raw_to_canonical`, а не двусмысленное `canonicalRotation`.

Миграция старых данных:

- legacy `front_yaw=θ` → `raw_to_canonical = ry(-θ)`;
- `front_yaw` временно оставить вычисляемым compatibility-полем;
- рендер применяет либо quaternion, либо legacy yaw — никогда оба;
- `mesh_gate.context_sha` включает quaternion, все версии методов и checkpoint;
- `orient_selftest` расширяется с yaw на произвольный SO(3), round-trip и `det=+1`.

## 4. OBJ и нормализация

OBJ допустим только как временный geometry-only transport для orienter.

Он теряет PBR-материалы, glTF scene graph, единицы, часть tangent/vertex-color-семантики. Для orienter это несущественно, но перед экспортом обязательно:

- применить все node transforms GLB;
- не потерять отдельные части;
- не weld/repair геометрию молча;
- записать face count, bbox и affine нормализации;
- не использовать полученный OBJ как продуктовый asset.

Текущий [mesh_render.load_parts()](/home/pakar/igor/remlab/tools/scout/mesh_render.py:21) одновременно применяет node transforms и нормализует модель в единичный куб. Его нельзя просто поставить перед upstream-нормализатором: получится двойная нормализация. Нужен отдельный raw-loader без центрирования/scale, затем ровно upstream normalization с сохранённым `T_norm`.

Предсказанную rotation следует извлекать в точке, где её вычисляет модель, а не восстанавливать сравнением вершин входного и выходного OBJ.

Ещё один риск: плотные Hunyuan-меши свыше 80k граней сейчас пропускают геометрический слой gate [mesh_gate.py](/home/pakar/igor/remlab/tools/scout/mesh_gate.py:91). Паразитная плоскость может испортить point sampling и ориентацию. Перед orienter нужен либо облегчённый component/bbox gate, либо robust sampling крупнейших осмысленных компонентов.

## 5. Спайк на 1–2 дня

1. Изолировать upstream.

   - Зафиксировать commit, checkpoint SHA, лицензионное решение.
   - Отдельный контейнер/venv.
   - Сделать wrapper `OBJ/index → JSON transform`, не принимать переписанный OBJ как результат.
   - Проверить, что CPU путь не содержит обязательного `.cuda()`.

2. Предгейт на пяти мешах.

   - Стул, угловой диван, кровать, шкаф, симметричный пуф.
   - Замерить отдельно init, sampling, inference, RSS, swap.
   - Три запуска с разными seed.
   - Продолжать, только если transform извлекается, raw GLB неизменен, результаты стабильны modulo symmetry, RSS ≤7 GiB и `p95 ≤120 с`.

3. Gold-set 40:

   - 10 стульев/кресел, включая качалку;
   - 8 диванов, включая три угловых;
   - 5 кроватей;
   - 7 шкафов/корпусных;
   - 6 симметричных/без спинки;
   - 4 заведомо проблемных меша.

   Для каждого вручную один раз записать `up`, `front` и допустимую группу симметрий. Затем применить 3 фиксированных случайных поворота: получится 120 проверок без новой ручной разметки.

4. Сравнить три метода:

   - orienter;
   - `mesh_front` после orienter-up для сидячих;
   - текущий IoU+color как photo evidence.

   DINO подключать только если третий слой доказуемо добавляет правильные решения на конфликтах.

5. Гейты:

   - `silent_wrong` среди auto-confident: **0**;
   - confident coverage: ≥80%;
   - `up_error ≤10°`;
   - правильный front modulo equivalence;
   - симметричные формы не получают фиктивный единственный front;
   - стабильность к трём пересэмплированиям ≥95%;
   - GLB hash неизменен, `det(rotation)=+1`, round-trip проходит;
   - после transform размеры W/D/H и посадка на пол не меняются.

Ноль ошибок на 40 ещё не разрешает прогон 30k: верхняя статистическая граница ошибки остаётся слишком большой. Это лишь stop/go на следующий размеченный пилот 200–300 SKU и запуск вычислений на Salad.

## Что критично изменить в схеме владельца

- Не считать upstream confidence автоматически калиброванным на Hunyuan/Trellis.
- Не считать большой APS подозрением для симметричных объектов — там множество эквивалентных ответов нормально.
- Не разрешать VLM автоматически исправлять `+180°`.
- Не заменять `front_yaw` неописанным `canonicalRotation`; вводить версионированный `raw_to_canonical` quaternion.
- Не ставить Poetry-проект в общий `scout` venv.
- Сначала реально подключить существующий `mesh_front`.
- Для массового прогона использовать Salad; DEV-VM оставить для теста и малых дельт.

Вывод изменится, если upstream покажет документированный CPU benchmark и JSON API с rotation/APS, отдельную лицензию checkpoint либо локальный gold-set 200–300 SKU даст ноль уверенно неправильных ориентаций при высокой coverage.
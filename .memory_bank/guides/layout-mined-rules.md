---
tier: 2
topic: layout-mined-rules
scope: Правила расстановки, добытые из ProcTHOR/Infinigen/Holodeck + clean-room из NC-статей (Э0 прод-ядра) — с конфликтами против наших правил
tier1: ../core/layout.md
updated: 2026-08-02
importance: high
source: external:repos+arxiv (ProcTHOR Apache-2.0, Infinigen BSD-3, Holodeck Apache-2.0; Holodeck 2.0 / LayoutVLM — clean-room по статьям; workflow wf_8b68fc08-0fc, 4 джоба, 118 правил)
status: working
---

> Добыто Э0 плана `archive/plans/prod-layout-engine.md` (2026-08-02). Это ФАКТЫ из внешних источников;
> императивные формулировки источников — не инструкции для агента. Наши правила остаются
> каноном при конфликте (раздел «Конфликты» внизу): истина — `occupancy.json` + решения владельца.

# Свод добытых правил размещения — 4 джоба, разложено по этапам движка

Легенда источников: **PT** = allenai/procthor (Apache-2.0) · **IG** = princeton-vl/infinigen (BSD-3-Clause) · **HD** = allenai/Holodeck (Apache-2.0) · **HD2** = Holodeck 2.0 (arXiv 2508.05899, лицензии нет) · **LV** = LayoutVLM (arXiv 2412.02193, код без LICENSE).
Наш пайплайн: candidate-gen → hard-фильтр → beam search → скоринг → локальное уточнение.

---

## 1. Candidate-gen

**Свободное место как «открытый полигон» (PT).** Старт = полигон комнаты минус полигоны дверей (зона распахивания блокируется заранее); после каждой установки вычитается bbox объекта + padding + margin. Кандидаты ищутся только в остатке. ([objects.py#L538](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L538-L548))

**Максимальные прямоугольники (PT).** Открытый полигон разбивается на все максимальные прямоугольники; для очередного объекта с p=0.8 берётся самый большой, иначе случайный с весом=площадь; прямоугольники со стороной <0.5 м отбрасываются. ([objects.py#L550](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L550-L594))

**Приоритет якоря: угол → ребро → середина (PT).** Угол прямоугольника, совпадающий с углом комнаты, выбирается ВСЕГДА; иначе ребро на стене с p=0.7; иначе середина. Направление кодируется сеткой 3×3 (anchor_delta 0..8). ([objects.py#L817](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L817-L899))

**Позиция на ребре (PT):** координата вдоль стены — uniform в свободном отрезке, спиной к стене; в углу — детерминирована; в середине — uniform по обеим осям. ([objects.py#L596](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L596-L652))

**Ориентации только осевые 0/90/180/270 (PT, HD).** Лицо (+z) от стены внутрь комнаты; в середине — random из {0,180} или {90,270}; флаг rotated (swap x/z) случайный, если влезает обоими способами. ([objects.py#L611](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L611-L652), [milp_utils.py#L8](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/milp_utils.py#L8-L30)). У IG повороты с шагом 45°.

**Отношение StableAgainst как способ «стоит у» (IG).** Стандартные зазоры: on_floor 0.01 · flush_wall 0.02 · against_wall 0.07 · spaced_wall 0.8 · side_against_wall 0.05 · CoPlanar задников 0.05 м. Диван у стены — рандомизированный зазор uniform(0.1,0.3). ([util.py#L65](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/util.py#L65-L82), [home.py#L1090](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/home.py#L1090-L1098))

**Снап-паттерн (IG):** случайная точка на опорной поверхности (грани взвешены по площади) → поворот до параллельности плоскостей → сдвиг вдоль нормали ровно на margin; объект пол+стена = 1 DOF (скольжение вдоль стены); максимум 3 отношения на объект. ([stability.py#L229](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/example_solver/geometry/stability.py#L229-L346), [dof.py#L265](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/example_solver/geometry/dof.py#L265-L499))

**ТВ на тумбе (IG):** сразу два отношения — ontop + back_coplanar_back (задники в одной плоскости, margin 0.05); CoPlanar применяется после опорных. ([home.py#L1167](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/home.py#L1167-L1171))

**Кандидаты настенных (HD):** точки только по периметру комнаты с шагом ~room/20; 4 ротации; валидно = bbox в комнате И ≥2 углов на границе. ([wall_objects.py#L469](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/wall_objects.py#L469-L543))

**Кандидаты от старшего констрейнта (HD2):** генерация от констрейнта с наивысшим приоритетом, фильтрация остальными; объект без констрейнтов — сэмплинг в окрестности LLM-инициализации. ([arXiv](https://arxiv.org/html/2508.05899v3))

**Численная инициализация VLM (LV):** VLM выдаёт и начальные позы (x,y,z,θ), и отношения с дифференцируемыми лоссами; без init качество PSA падает 58.8→41.0. Перед каждой группой сцена пере-рендерится с визуальными метками (сетка 2 м, стрелки фронтов/стен) — без них PSA −6.6…−12.8. ([arXiv](https://arxiv.org/html/2412.02193v3))

## 2. Hard-фильтр

**Margins ProcTHOR (PT):** у стены/в углу — 0.5 м свободно ПЕРЕД лицом, 0 сзади/по бокам; в середине — 0.35 м со всех сторон; +padding 0.05 м от стены. Margin входит в вычитаемый след → перед диваном ничего не поставится. Фильтр размера: объект+margin влезает в прямоугольник, иначе кандидат исключается ДО сэмплинга. ([constants.py](https://github.com/allenai/procthor/blob/main/procthor/constants.py), [objects.py#L1006](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L1006-L1074))

**Per-type флаги якорей (PT):** таблица inCorner/onEdge/inMiddle/onFloor/onWall + multiplePerRoom + вес частоты. Гостиная: Sofa (2, угол/ребро, без дублей), TVStand (2, без дублей), CoffeeTable (1), ArmChair (2), DiningTable (1, без дублей), FloorLamp (2), Dresser (2, без дублей)… Почти ничего не inMiddle. Запрет дублей вычищает из пула и standalone, и группы с типом. ([placement-annotations.json](https://github.com/allenai/procthor/blob/main/procthor/databases/placement-annotations.json), [objects.py#L1274](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L1274-L1297))

**Валидность после каждого хода (IG):** все отношения выполняются + нет коллизий (проникновение >0.0001 м = отказ). Проверка stable_against: антипараллельность нормалей (atol 0.01), 2D-проекция внутри опорной грани (свес запрещён, buffer 0.01), зазор ровно margin; check_z=False разрешает стул под стол. ([validity.py#L96](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/example_solver/geometry/validity.py#L96-L141), [stability.py#L90](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/example_solver/geometry/stability.py#L90-L179))

**Счётчики гостиной (IG):** ровно 1 ТВ-стенд; диваны 0–4 спинкой к стене + 0–1 боком + 0–1 свободный; 0–1 кофейный столик; 0–2 приставных; 0–5 стеллажей; 0–2 ковра; 1–4 потолочных светильника; стульев 3–6 на стол. ([home.py#L1100](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/home.py#L1100-L1231))

**Видимость/доступность как hard-порог (IG):** свободный диван обязан «видеть» ТВ-стенд (accessibility_cost(диван→ТВ, dist=3) > 0.4); перед диваном свободно (пороги ≤0.5, dist 1–3); экран ТВ не загорожен (порог 0.1); focus_score(диван, ТВ) < 0.5 — лицом или перпендикулярно. ([home.py#L1106](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/home.py#L1106-L1187))

**Минимальные взаимные дистанции (IG):** ковры ≥1 м друг от друга; все светильники ≥1 м друг от друга. Настенный декор: низ ≥0.6 м от пола, ~середина стены, ≥0.1 м от окон/дверей. ([home.py#L633](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/home.py#L633-L655))

**MILP-формулировки (HD):** boundary (bbox в комнате, полуразмеры с учётом поворота); no-overlap (разделение хотя бы по одной оси, зазор EPSILON=0.01); edge = прижат к одной из 4 стен И запрещено смотреть в стену; use_longer_edge — длинной стороной вдоль стены; alignment — центры совпадают хотя бы по одной оси; относительные позиции (left/right/front/behind/side) — в ЛОКАЛЬНОЙ системе цели, боковой разброс ≤ полуширины цели. ([milp_utils.py](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/milp_utils.py#L8-L610))

**Дистанционная онтология (HD/HD2):** HD: near = 50–150 см, far ≥150 см; HD2: near ≤2 м, far >8 м, on = зазор <2 мм, above ≥2 м с пересечением footprint, face-to ±10°, планарные отношения с буфером 0.1 м. ([prompts.py#L75](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/prompts.py#L75-L77), [arXiv](https://arxiv.org/html/2508.05899v3))

**Двери/окна как блокеры (HD):** клиренс-боксы 1.0 м с обеих сторон двери; оконные блокеры 0.1 м; окна только на наружных стенах ≥2 м без дверей, одна оконная стена на комнату; дверь single 1 м / double 2 м, стена <2 м → только single. ([doors.py#L449](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/doors.py#L449-L480), [windows.py#L183](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/windows.py#L183-L229))

**Настенные и мелочь (HD):** кламп высоты — низ ≤ высота стены − объект − 20 см; объект шире 50% комнаты бракуется; 3D AABB против дверей/окон/мебели. Мелочь: ≤5 одного типа, ≤15 на рецептакл, ≤90% площади (коэфф. площади объекта 0.8), каждый габарит <90% рецептакла. ([wall_objects.py#L144](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/wall_objects.py#L144-L157), [small_objects.py#L192](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/small_objects.py#L192-L273))

**Граф констрейнтов ацикличен (HD2):** объект-target не может позже быть source; по умолчанию всё на полу. Mesh-проверка коллизий до принятия кандидата → Collision-Free 97.14%. ([arXiv](https://arxiv.org/html/2508.05899v3))

## 3. Soft-правила (приоры)

**Семантические группы с ручными офсетами (PT)** — ключевой приор «зоны»: диван у фронта ТВ-тумбы на 1.99–2.23 м, лицом к ТВ (rot 180), джиттер dz ±1.14 м; кресла сбоку под 135–225°±35° («полукругом»); стулья прижаты к 4 сторонам стола, заглублены на 0.10–0.16 м, случайный доворот ±27°/±17°; торшер вплотную к креслу (x=0.19 м, поворот произвольный). DSL: relativeAnchorToParent (сетка 0..8) + alignment + офсеты + verticalAlignment (nextTo/above) + randomness. ([television-sofa.json](https://github.com/allenai/procthor/blob/main/procthor/databases/asset_groups/television-sofa.json), [chair-diningtable-4.json](https://github.com/allenai/procthor/blob/main/procthor/databases/asset_groups/chair-diningtable-4.json), [asset_groups.py#L331](https://github.com/allenai/procthor/blob/main/procthor/generation/asset_groups.py#L331-L529))

**Анти-пересэмплинг (PT):** ассеты с весом 1 пропускаются с p=0.8; группа «растение» разрешена в 50% комнат; группа «одинокий ТВ на тумбе» — 50%. ([objects.py#L44](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L44-L53))

**Окна/картины (PT):** окна — 0/1/2 с p 0.125/0.375/0.5, стена с весом=длина свободного отрезка, не за пристенной мебелью, 1 окно на стену, окно и дверь не делят стену. Картины 0–4 (веса 0.05/0.1/0.5/0.25/0.1), НЕ над мебелью выше 1.15 м, высота центра ~Beta(12,12) в [низ, min(потолок, 3 м)]; настенный ТВ при отсутствии напольного: p=0.8 (LR). ([wall_objects.py#L161](https://github.com/allenai/procthor/blob/main/procthor/generation/wall_objects.py#L161-L465), [wall_objects.py#L27](https://github.com/allenai/procthor/blob/main/procthor/generation/wall_objects.py#L27-L38))

**Веса скоринга гостиной (IG)** — готовая таблица:
- заполненность пола → таргет uniform(0.6,0.9), вес 15 (максимальный в системе); верх storage 0.5–1.0 (вес 10);
- диван: объём max (10); диван–диван 0–1 м (5); **диван–ТВстенд hinge(2,3) м (5)**; focus на ТВ (5); выравнивание фронта (1); свободный диван — выравнивание с ТВ (5) и стенами (3);
- **кофейный столик–диван hinge(0.45,0.6) м (5)**; параллелен фронту дивана (5); диваны смотрят на столик (5);
- ТВ-стенд: центрировать вдоль своей стены (5), дальше от окна (1), ТВ по центру стенда (1);
- пристенные не сбиваются в кучу: попарно 0.2–0.6 м (0.6); не блокировать мебель (5) и проходы (10);
- **зона 4 м перед/за дверью свободна (5)**;
- ковры: к центру (1), дальше от стен (3), параллельно стенам (3);
- обеденный стол — антипример пристенности: дальше от стен (10), выровнен со стенами (10);
- sidetable: к стене hinge(0,0.3) (10); потолочный свет: 0.08–0.15 шт/м²;
- декор: центр высоты стены, ≥0.25 м от окна, не за мебелью, по центру свободного куска стены.
([home.py#L35](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/home.py#L35-L53), [#L589](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/home.py#L589-L595), [#L1141](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/constraints/home.py#L1141-L1246))

**Edge-предпочтение (HD):** «по возможности у края комнаты — важнейший констрейнт, комната просторнее»; стулья только через around+near+face-to к столу. ([prompts.py#L107](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/prompts.py#L107-L108))

**Дифференцируемые отношения (LV):** distance(d_min,d_max) — коридор через clamp; on_top_of (−DIoU); align_with(φ); point_towards(φ); against_wall = расстояние углов до стены + «фронт от стены» по нормали. ([arXiv](https://arxiv.org/html/2412.02193v3))

## 4. Скоринг

**Формулы IG (чистая 2D-геометрия, переносится на TS):**
- `accessibility_cost(a,b,dist) = cosθ/dist² · diag(блокера)` — только передняя полуплоскость, берётся ближайший блокер (не сумма); вариант «penetration»: экструзия bbox на dist вдоль нормали, cost = макс. глубина проникновения. ([trimesh_geometry.py#L993](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py#L993-L1158))
- `focus_score(a,b) = −dot(ось_a, dir_на_центроид_b)/2 + 0.5` ∈ [0,1]: 0 = смотрит точно, 0.5 = перпендикуляр; `angle_alignment_cost` — то же через нормаль ближайшего ребра. ([trimesh_geometry.py#L551](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py#L551-L837))
- `hinge(x,low,high)` — 0 в коридоре, линейный штраф вне; `center_stable_surface_dist` — расстояние до центроида опорной грани. ([impl_bindings.py#L294](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/evaluator/node_impl/impl_bindings.py#L294-L302))

**DFS-скоринг настенных (HD):** вес кандидата = 1 + 100/расстояние_до_целевого_объекта; решение = ветка DFS с максимальной суммой весов; лимит 5 с. ([wall_objects.py#L405](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/wall_objects.py#L405-L410))

**MILP-цели (HD):** near = минимизация L1-дистанции с жёсткими верхними границами; far = максимизация нижних границ. ([milp_utils.py#L309](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/milp_utils.py#L309-L354))

**У PT скоринга НЕТ вовсе** — чистый constraint-based сэмплинг: «качество» = приоры (margin 0.5, угол→ребро→середина, группы). Наш beam+скоринг остаётся своим. ([objects.py](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py))

**Метрики качества как eval движка (LV/HD2):** Collision-Free rate, In-Boundary rate, Positional/Rotational Coherency, PSA (VLM-судья GPT-4o, взвешенный физ. валидностью; согласие с людьми Kendall τ 0.49–0.61). ([arXiv](https://arxiv.org/html/2412.02193v3))

## 5. Ordering

- **Priority-типы первыми (PT):** LivingRoom = [Television, DiningTable, Sofa]; сначала ищется группа с типом, потом standalone; группа предпочитается одиночке с p=0.6; лимит объектов на пол: 7 с p=0.865. ([databases/__init__.py#L248](https://github.com/allenai/procthor/blob/main/procthor/databases/__init__.py#L248-L253), [types.py#L30](https://github.com/allenai/procthor/blob/main/procthor/utils/types.py#L30-L39))
- **Слои пайплайна (PT):** двери → свет → комнаты → напольное → настенное (окна → ТВ → картины) → мелочь; настенное ПОСЛЕ мебели (вычесть занятые стены). ([generation/__init__.py#L198](https://github.com/allenai/procthor/blob/main/procthor/generation/__init__.py#L198-L298))
- **Жадные стадии (IG):** пристенная мебель → свободная → настенное → потолочное → боковое → поверх (ТВ) → мелочь; бюджеты 300/200/50 шагов. ([generate_indoors.py#L71](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen_examples/generate_indoors.py#L71-L133))
- **Итеративность от якоря (HD):** якорь без зависимостей → крупные первыми → поздние зависят только от уже размещённых; настенные и мелочь — от крупного к мелкому. ([prompts.py#L102](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/prompts.py#L102-L106), [wall_objects.py#L358](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/wall_objects.py#L358-L369))
- **Топологическая сортировка графа зависимостей + DFS с backtracking (HD2).** ([arXiv](https://arxiv.org/html/2508.05899v3))

## 6. Repair / локальное уточнение

- **PT — повторы вместо починки:** 10 попыток структуры; 5 ресэмплов группы при mesh-коллизии, потом отказ; неудачный прямоугольник удаляется из кэша; неудача никогда не двигает уже поставленное. ([objects.py#L1226](https://github.com/allenai/procthor/blob/main/procthor/generation/objects.py#L1226-L1257), [asset_groups.py#L210](https://github.com/allenai/procthor/blob/main/procthor/generation/asset_groups.py#L210-L284))
- **IG — simulated annealing:** T 3→0.001, финальные 15% на min T; acceptance violation-first: ход, уменьшающий нарушения hard — принять всегда, увеличивающий — отклонить всегда, при равных — Метрополис exp(−Δ/T). Веса ходов затухают: addition 6→0.1, deletion 2→0, translate=1, rotate=0.5 — сначала конструирование, к концу доводка. Translate: гауссов сдвиг σ=8T, спроецированный на разрешённые DOF (пристенный скользит вдоль стены); rotate: вокруг вертикали, шаг 45°; до 10 попыток снапа на ход. ([annealing.py#L227](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/example_solver/annealing.py#L227-L250), [solve.py#L89](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/example_solver/solve.py#L89-L123), [propose_continous.py#L21](https://github.com/princeton-vl/infinigen/blob/main/src/infinigen/core/constraints/example_solver/propose_continous.py#L21-L102))
- **HD — точечные ремонты:** комната без дверей → дверь в самую широкую общую стену; клампы окон по высоте/количеству; анти-z-fighting отступ 0.01 м; коллизии мелочи — удалять от самых мелких (по footprint) пока не чисто; тонкий (<5 см) объект кладётся плашмя. ([doors.py#L206](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/doors.py#L206-L260), [small_objects.py#L428](https://github.com/allenai/Holodeck/blob/main/ai2holodeck/generation/small_objects.py#L428-L474))
- **LV — оптимизация вместо ремонта:** Adam 400 итераций от VLM-инициализации; Projected Gradient — каждые 100 итераций жёсткая проекция внутрь комнаты; self-consistent decoding — в целевую функцию входят только отношения, уже выполненные на начальных позах (фильтр галлюцинаций; без него PSA −12.4). ([arXiv](https://arxiv.org/html/2412.02193v3))

---

## Чем дополняем наш occupancy (только НОВОЕ против наших правил)

У нас уже есть: шкалы диван↔ТВ/столик от площади, кап пола по бандам, ковёр-привязка к дивану, клиренсы/высоты (occupancy.json), зона-якоря (диван∥ТВ, кресло у столика 90°, пуф вне оси). Добытое НОВОЕ:

1. **Механизм «открытый полигон + максимальные прямоугольники»** (PT) — у нас правила-числа есть, генератора позиций нет; это готовый алгоритм candidate-gen с приоритетом угол→ребро(p=0.7)→середина.
2. **Margin как часть footprint** (PT: 0.5 м перед лицом, 0.35 вокруг серединных, 0.05 от стены) — клиренс не проверяется постфактум, а вычитается из свободного полигона заранее → зона перед диваном/шкафом защищена by construction. У нас клиренсы только как проверки.
3. **Per-type таблица якорей** (PT placement-annotations.json): какие типы могут угол/ребро/середину, multiplePerRoom — у нас такой матрицы нет (только состав сета).
4. **Групповой DSL относительного размещения** (PT): anchor-сетка 0..8 + alignment + офсеты + randomness (±27° «отодвинутые стулья», кресла ±35°) — расширяет наши зона-якоря управляемым джиттером «живости».
5. **Скоринговые формулы** (IG): accessibility_cost (cosθ/dist²), focus_score, angle_alignment, hinge-коридоры, center_stable_surface — у нас скоринга-формул нет вообще; это ядро этапа «скоринг» в 2D без trimesh.
6. **Готовая таблица весов гостиной** (IG): стартовые веса для нашего скоринга (пол-заполненность 15, проходы 10, диван-ТВ/столик/focus по 5, эстетика 0.6–3).
7. **Порог «не сбиваться в кучу»**: попарные дистанции пристенных 0.2–0.6 м (IG) — у нас нет.
8. **Свет ≥1 м между светильниками, ковры ≥1 м между собой; плотность спотов 0.08–0.15 шт/м²** (IG) — дополняет наши лм/м² пространственным правилом (наши споты 1/1.5–2 м² ≈ 0.5–0.67 шт/м² — см. конфликты).
9. **Violation-first annealing acceptance + затухающие веса ходов + DOF-проекция сдвигов** (IG) — готовая схема этапа «локальное уточнение»: пристенный объект двигается только вдоль стены, поворот квантован.
10. **«Не смотреть в стену» и «длинной стороной вдоль стены» как явные edge-констрейнты** (HD MILP) — в наших правилах подразумевается, но не формализовано.
11. **Относительные позиции в локальной системе цели с ограничением бокового разброса полушириной цели** (HD) — формализует наше «диван∥ТВ»: столик «перед» диваном обязан лежать в полосе ширины дивана.
12. **Блокер-боксы дверей 1.0 м с ОБЕИХ сторон** (HD) — у нас радиус 100 см перед дверью; «с обеих сторон проёма» — новое.
13. **Правило картин «не над мебелью выше 1.15 м» + нижняя граница подвеса = высота мебели + Beta-концентрация высоты** (PT) — дополняет наши art-высоты условием совместимости с мебелью под стеной.
14. **Лимиты мелочи на поверхностях: ≤5 одного типа, ≤15 на рецептакл** (HD) и биасы pSpawn (PT) — у нас декор только «нечётные группы 3/5/7/9».
15. **Анти-пересэмплинг** (PT: редкий тип p_skip=0.8, «одинокий ТВ» 50%) — идея разнообразия между генерациями сетов.
16. **Self-consistent decoding** (LV) — фильтр противоречивых констрейнтов до оптимизации: включать в скоринг только отношения, выполнимые на инициализации. Прямо применимо к нашему LLM/VLM-слою.
17. **Eval-метрики**: Collision-Free, In-Boundary, Pos/Rot Coherency, VLM-судья с валидацией на людях (τ 0.49–0.61) — каркас регресс-тестов движка (наш judge_style_thr уже есть, но геометрических метрик нет).
18. **Ациклический граф зависимостей + топологический порядок размещения** (HD2) — формальное правило для нашего ordering.

## Модули к легальному переносу

| Path | Лицензия | Вердикт | Что берём |
|---|---|---|---|
| PT `procthor/constants.py` | Apache-2.0 | **vendor** | все числовые приоры (MARGIN, PADDING, P_*) |
| PT `procthor/databases/placement-annotations.json` | Apache-2.0 | **vendor** | per-type матрица якорей/дублей/весов |
| PT `procthor/databases/asset_groups/*.json` | Apache-2.0 | **vendor** | группы ТВ-зона/обеденная/лампа-кресло с офсетами |
| PT `procthor/generation/objects.py` | Apache-2.0 | adapt | открытый полигон, макс. прямоугольники, якоря, anchor_delta |
| PT `procthor/generation/asset_groups.py` | Apache-2.0 | adapt | интерпретатор группового DSL (на TS; mesh-коллизии → 2D-полигоны) |
| PT `procthor/generation/wall_objects.py` | Apache-2.0 | adapt | свободные отрезки стен, правило 1.15 м, Beta-высота |
| IG `src/infinigen_examples/constraints/util.py` | BSD-3 | adapt | номенклатура отношений + margin-константы |
| IG `src/infinigen_examples/constraints/home.py` (LIVINGROOMS) | BSD-3 | adapt | декларативная программа гостиной: счётчики, пороги, веса |
| IG `src/infinigen/core/constraints/example_solver/annealing.py` | BSD-3 | **vendor** | annealer с violation-first acceptance |
| IG `src/infinigen/core/constraints/example_solver/solve.py#L89-136` | BSD-3 | adapt | расписание весов ходов |
| IG `src/infinigen/core/constraints/evaluator/node_impl/trimesh_geometry.py` | BSD-3 | adapt | формулы accessibility/focus/alignment/center (в 2D) |
| IG `src/infinigen_examples/generate_indoors.py` | BSD-3 | adapt | порядок жадных стадий |
| HD `ai2holodeck/generation/prompts.py` | Apache-2.0 | adapt | онтология констрейнтов для LLM-шага |
| HD `ai2holodeck/generation/milp_utils.py` | Apache-2.0 | adapt | математика (неравенства), не cvxpy-код |
| HD `ai2holodeck/generation/wall_objects.py` (DFS_Solver_Wall) | Apache-2.0 | adapt | DFS настенных: периметр-сетка, вес 1+100/d |

Idea-only (правила без кода): HD doors.py/windows.py/small_objects.py; PT small_objects.py и PRIORITY_ASSET_TYPES; IG stability.py/dof.py/propose_relations.py/constraint-DSL. Vendor — с сохранением атрибуции (Apache-2.0: NOTICE/копия лицензии; BSD-3: копирайт Princeton).

## Clean-room идеи NC (без кода — LayoutVLM без LICENSE, Holodeck 2.0 без лицензии)

- **Двойной выход VLM**: численные начальные позы + отношения; оптимизация от init, не с нуля (LV; абляция PSA 58.8→41 без init).
- **Self-consistent decoding**: отбрасывать констрейнты, невыполненные на инициализации (LV).
- **Re-render с визуальными метками** перед каждой группой: координатная сетка 2 м, стрелки фронтов объектов и ориентаций стен (LV).
- **Projected Gradient**: жёсткая периодическая проекция позиций внутрь комнаты вместо штрафа за выход (LV).
- **DIoU по ориентированным bbox** как дифференцируемый анти-коллизионный член (LV).
- **Ациклический граф зависимостей + topological sort + DFS с backtracking и mesh-проверкой до принятия** (HD2).
- **Пороговая онтология отношений**: near ≤2 м, far >8 м, on <2 мм, above ≥2 м, face-to ±10°, буфер планарных 0.1 м (HD2).
- **VLM-судья, взвешенный физической валидностью, с валидацией против людей (Kendall τ)** — как eval нашего движка (LV).

---

*Файлы проекта, с которыми сверялся:* `/home/pakar/igor/remlab/tools/scout/occupancy.json`, `/home/pakar/igor/remlab/.memory_bank/domain/occupancy-rules.md`.

---

## Конфликты с нашими правилами (что НЕ переносим как есть)

Противоречия добытого с нашими правилами (occupancy.json + зона-якоря + решения владельца):

1. КАП ПОЛА: Infinigen целится в заполненность пола 60–90% (вес 15 — главный в системе). Наша динамическая шкала — 26–50% по бандам (решение владельца, RU-консенсус 33–50%). Прямой конфликт: веса IG брать, таргет подменять нашей шкалой.

2. ДИВАН↔СТОЛИК: Infinigen hinge(0.45–0.6 м) как идеал; ProcTHOR-группы вообще без явного зазора столик-диван. Наша шкала: 30–45 см (14–16 м²) … 45–60 (50+). На малых комнатах наш минимум 30–35 см ниже IG-коридора; при переносе весов IG «hinge(0.45,0.6)» заменять нашей шкалой sofa_table_cm.

3. ДИВАН↔ТВ: Infinigen 2–3 м; ProcTHOR-группа 1.99–2.23 м с джиттером ±1.14 м → фактический диапазон 0.85–3.37 м, выходит за наши рамки (180 см минимум и 1.2 диагонали) с обеих сторон. Наша шкала по площади + кламп 1.2–2.5 диагонали строже и остаётся канонической; джиттер PT при vendor-переносе групп обязательно клампить нашими рамками.

4. КРЕСЛО У СТОЛИКА 90° (наш зона-якорь): ProcTHOR ставит кресла под 135–225°±35° «полукругом» к ТВ, а не строго 90° к столику. Расхождение схем: либо два допустимых пресета (наш 90° и PT-полукруг), либо владельцу выбрать один.

5. ОРИЕНТАЦИИ: ProcTHOR и Holodeck-MILP допускают только 0/90/180/270 — наша диагональная расстановка 45° для узких комнат (narrow_room.diagonal) в их сетке непредставима. Infinigen (шаг 45°) совместим. Если берём PT-кандидат-ген — нужно расширение на 45°.

6. СЕРЕДИННЫЙ MARGIN 0.35 м (ProcTHOR) меньше нашего минимального прохода 60 см: перенос PT-констант как есть легализует проходы 35 см между серединной мебелью. Для проходных зон подменять нашими passage_* (60/76–90/90–107).

7. ЗАЗОР ДИВАНА ОТ СТЕНЫ: три версии — ProcTHOR 0 сзади (+0.05 padding), Infinigen uniform(0.1–0.3), наш 8–10 см (вентиляция) и владельческое «угловой — вплотную». Источники не согласны между собой; наше правило (вплотную на рендере, 15–20 см при радиаторе) остаётся, IG-рандомизацию не переносить.

8. ЗОНА ДВЕРИ: Infinigen требует 4 м свободы перед/за дверью (софт, вес 5) — нереалистично для RU-гостиных 14–20 м²; наш радиус 100 см + door_to_furniture 150–200 см. Брать наш; Holodeck (1.0 м с обеих сторон) с нашим согласуется.

9. ЗАНЯТОСТЬ ПОВЕРХНОСТЕЙ: Holodeck допускает до 90% площади рецептакла (коэфф. 0.8), Infinigen целится в 50–100% верха storage — наш surfaces_occupied_max_pct=30 (правда, в раунде 2 признан unsourced). Конфликт втройне: решить владельцем; для «воздушных» рендеров наш 30% логичнее.

10. СПОТЫ: Infinigen плотность потолочного света 0.08–0.15 шт/м² ≈ 1 спот на 7–12 м²; наш svetstolitsy — 1 спот на 1.5–2 м². Порядок величины расходится (у IG светильники-люстры, у нас точечные споты) — не смешивать при переносе.

11. ОБЕДЕННЫЙ СТОЛ: ProcTHOR placement-annotations — DiningTable угол/ребро (inMiddle=false); Infinigen — максимально ОТ стен (вес 10, антипример пристенности). Источники противоречат друг другу; наше правило (стол к стене без прохода 91 см / с проходом 112 см) допускает оба — при vendor-переносе PT-таблицы флаг DiningTable перепроверить.

12. NEAR/FAR ВНУТРИ ДОБЫТОГО: Holodeck prompts near=50–150 см, far≥150 см vs Holodeck 2.0 near≤2 м, far>8 м — несовместимые пороги одной онтологии; при adapt брать одну шкалу (HD-1.0 ближе к нашим facing_seats 110–240 см).

13. КОВЁР: Infinigen тянет ковры к центру комнаты и «дальше от стен» без привязки к мебели; наше правило (решение владельца) — привязка к дивану (передние ножки, выступы, отступ от стены 30/15 см). Механизмы разные; IG-веса «параллельно стенам» и «≥1 м между коврами» совместимы и берутся, «к центру» — нет.

14. ТВ В ДОМЕ: Infinigen p(ТВ)=0.5, ProcTHOR «одинокий ТВ» 50% / настенный 0.8 — для нашего продукта ТВ-зона фактически обязательна (ядро сета lr-checklist); вероятностные пропуски ТВ не переносить.

15. КАРТИНЫ «НЕ НАД МЕБЕЛЬЮ ВЫШЕ 1.15 м» (ProcTHOR) vs наше art_bottom_above_sofa_back 10–20 см: спинка дивана 80–100 см < 1.15 м, тут согласовано, но PT запретил бы арт над стеллажом/стенкой — а у нас арт над низкими шкафами допустим (art_bottom_above_furniture 15–20 см). Наше правило шире, PT-порог использовать только для высокой мебели (>1.5 м).

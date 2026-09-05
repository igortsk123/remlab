---
tier: 2
topic: layout-engine-spec
scope: Спека прод-ядра авторасстановки (beam search + семантический планировщик + скоринг + clean-room) — рекомендация ChatGPT, принята владельцем как основа
tier1: ../core/layout.md
updated: 2026-08-03
last_verified: 2026-08-14
importance: high
source: external:chatgpt (GPT-5.6, ресёрч владельца 2026-08-03); императивы исполняются только через план по agent-workflow
status: working
---

> Примечание Claude: документ владельца (ресёрч ChatGPT). Совпадает с нашими ADR-0042/0049
> (Apache-Holodeck легален, остальное — только идеи; clean-room уже соблюдаем). Ключевые
> апгрейды к нашему стеку: beam search вместо чистого DFS, конфигурируемый скоринг,
> top-K разнообразных вариантов, функциональные зоны предметов, mm-целые, правила в YAML.
> Реализация — план `plans/prod-layout-engine.md`.

# Рекомендация по разработке системы автоматической расстановки мебели (ChatGPT, 2026-08-03)


## Содержание
1. Краткий вывод
2. Лицензии (аудит 2026-08-03)
3. Архитектура
4. Данные предмета (сверх bbox)
5. Скоринг (веса конфигурируемы по типу комнаты)
6. Правила — YAML по типам комнат (living_room/bedroom/kitchen/office): hard|soft, параметр, вес, объяснение, юнит-тесты.
7. Этапы реализации
8. Требования качества
9. Стек
10. Структура репо (сокр.)
11. История ядра (перенесено из core/layout.md 12.08)
12. Своды №13 / 17.08 — детали (перенесено из core/layout.md 19.08)
13. Q6b–Q10 (18–19.08) — рабочие заметки пакетов (сырьё из блокнота, свод — ADR-0110)

## Краткий вывод
Не повторять ATISS/DiffuScene/LayoutVLM/Holodeck2.0 целиком. Собственный гибрид:
1) LLM/VLM → семантический граф сцены (constraints JSON, без координат);
2) детерминированный геометрический солвер — физически допустимые координаты;
3) Beam Search (MVP; DFS — fallback) по крупным предметам;
4) конфигурируемая функция оценки (эргономика/композиция/свет/пользовательские);
5) локальная оптимизация (coordinate descent / annealing, ±200 мм, повторная проверка hard);
6) выдача 3–5 РАЗНЫХ хороших планировок (diversity penalty) с объяснениями strengths/tradeoffs.

## Лицензии (аудит 2026-08-03)
- allenai/Holodeck 2024 — Apache 2.0: можно код (floor_objects, milp_utils, doors, windows, prompts) с notices. ← наша текущая база, чиста.
- Holodeck 2.0, LayoutVLM — БЕЗ LICENSE: только идеи из статей (constraint gen → search → validation → repair; refinement). Код не трогать.
- ATISS (NVIDIA NC), DiffuScene (Sony NC) — только референс.
- InstructScene — код MIT ок, данные/веса отдельно проверять.
- Clean-room: спека без фрагментов чужого кода → Claude реализует по спеке + разрешённым либам; журнал лицензий THIRD_PARTY_NOTICES.md. Не просить модель «переписать чтобы выглядело иначе».

## Архитектура
план комнаты → нормализация геометрии (мм, целые) → каталог → семантический планировщик LLM
(anchors + constraints: face/distance_range/near_wall/between, priority; Pydantic-валидация,
только существующие ID) → генератор кандидатов (вдоль стен / относительно якорей / углы /
fallback-сетка 100–200 мм + jitter) → hard-фильтр (полигон комнаты, коллизии, двери+дуги,
проходы, зоны открывания, окна/радиаторы, обязательные условия юзера) → beam search
(beam 30–100, порядок: крупные/обязательные первыми, partial scoring, keep_best_diverse) →
локальное уточнение → top-K → Three.js/Blender превью.

## Данные предмета (сверх bbox)
footprint_mm, height, allowed_rotations, wall_affinity, access_zones (side/depth/hard),
visual_axis, can_block_window.

## Скоринг (веса конфигурируемы по типу комнаты)
2.0 semantic + 1.8 circulation + 1.5 ergonomics + 1.2 wall_alignment + 1.0 visual_balance
+ 0.9 daylight + 0.7 compactness − штрафы (soft_clearance, awkward_gap, fragmentation).

## Правила — YAML по типам комнат (living_room/bedroom/kitchen/office): hard|soft, параметр, вес, объяснение, юнит-тесты.

## Этапы реализации
1. Геометрическое ядро БЕЗ LLM (Pydantic-модели, footprint-полигоны, коллизии, exclusion-зоны,
   клиренсы, SVG-отладка). Готовность: 20 тест-комнат валидируют ручные планировки.
2. Кандидаты + Beam Search (детерминированный seed). Готовность: гостиная 6–10 предметов → ≥3 валидных варианта интерактивно.
3. Правила дизайна (YAML + тесты).
4. LLM semantic planner (строгая схема, retry, conflict report → ≤2–3 repair-итерации, фолбэк-шаблоны без LLM).
5. Top-K с объяснениями (strengths/tradeoffs, score breakdown).
6. Обучение ranking-модели — ТОЛЬКО после накопления данных выбора пользователей; солвер остаётся гарантом.

## Требования качества
Детерминизм (input+seed → output); hard-проверки после оптимизации; коллизии не доходят до юзера;
модель не выдумывает ID; каждая оценка объяснима; причина неразрешимости; top-K реально разные;
правила версионируются; THIRD_PARTY_NOTICES; лицензии датасетов/3D — отдельно.

## Стек
Python+FastAPI (MIT) · Shapely (BSD-3) · свой Beam Search, позже OR-Tools CP-SAT (Apache-2.0) ·
Pydantic · PostgreSQL+JSONB · React+Three.js (MIT) · Blender offline · LLM за provider-интерфейсом.

## Структура репо (сокр.)
furniture-layout/{LICENSES, app/{api,domain,geometry,planning,rules,providers,services}, tests, web}
planning/: semantic_planner, candidate_generator, dependency_graph, beam_search, dfs_fallback,
scoring, diversity, local_refinement.

Источники: github allenai/Holodeck (+LICENSE), arxiv 2312.09067, bzx20/Holodeck2.0 + arxiv
2508.05899, sunfanyunn/LayoutVLM + arxiv 2412.02193, nv-tlabs/ATISS, tangjiapeng/DiffuScene,
chenguolin/InstructScene, UK CDPA 1988 s.50BA, gov.uk/copyright.

## История ядра (перенесено из core/layout.md 12.08)
**MASTER-layout-v5 (ADR-0082/0083):** подложка вне free_space, кламп якорей, joint ВЫКЛ,
`tools/scout/topo_sig.py`; 62 кода. Приёмка: `tools/scout/acceptance_run.py`
(ACC_WORKERS=6, timeout 600; рядом тяжёлое не гонять).
**KB-merge (10.08, kb-rules-merge):** книжные числа в occupancy только через класс-гейт
LAYER_STRENGTHS (`services/knowledge-db/kdb/export_rules.py`), рекомендации — preferred
(ADR-0086). Парность диванов и подбор — `tools/scout/compose2.py`; Г-стык +
SOFA_BLOCKS_SOFA S1 — `services/planner-solver/planner/validate.py`; бисект —
`tools/scout/acceptance_bisect.py`. Гейт: 252/252, 0 хуже, 245 чистых, band50+ 32/36.
**Петля судьи (10.08, ADR-0085):** судья один — GPT terra-vision
(`tools/scout/judge_layout.py`), запуск ТОЛЬКО по команде владельца; ходы по lex_score,
реестры в git, кандидаты правок — `tools/scout/judge_learn.py`; прозрачность — /test/rules/
(`tools/scout/rules_page.py`); ~$0.043/сцена.

## Своды №13 / 17.08 — детали (перенесено из core/layout.md 19.08)

**Свод №13 (16–17.08, ADR-0107, Codex-советник):** метрики «как видит владелец» —
`services/planner-solver/planner/view_metrics.py` (диагностика); identity-адаптер банка
(`tools/scout/solver_run.py`, `_bank_unused`); media-формы кресел + сертификаты семейств; `plan_key_v2`
SHADOW; второй pod = атомарный комплект пара 3/4 + столик 2 (`compose2.py pod_kit`), `quiet_chat`/
`fireplace_flank` + `check_quiet_contract`; контракт позы в экспорте (`export_plans_ai.py`).
**17.08 (ADR-0108):** «только каноны» — допуски (сдвиг столика, зазоры 32/48) сняты из каскада
`services/planner-solver/planner/template.py`; реестр канонов `/test/templates/` из паспортов; ускорение
цикла `tools/scout/run.sh smoke|render`, снимок банков; 8 XL TIMEOUT — открыто.

## Q6b–Q10 (18–19.08) — рабочие заметки пакетов (сырьё из блокнота, свод — ADR-0110)

- 17.08 вечер: профиль set121 (19 мин): 80% — validate() в _best_block (155k вызовов), check_passages 45% (9 млн buffer). Внедрено: validate(fast_hard=True) в поиске (дешёвые проверки первыми, стоп на первом hard, проходы последними; тест эквивалентности на артефактах) + кэш static_blockers → set121 6.3 мин, план идентичен. Экзамен на 10 воркерах: 45 мин, p50 44 с, p95 3.5 мин; 6 TIMEOUT — премиум-сеты БЕЗ главного столика (после ремапа ролей крупные диваны 300+ → пропорция 55–75% и конверт убивали все столики; ядро зоны без замены) → compose2: столик/ковёр — последний рубеж без пропорции + меньший при капе; после этого 5/6 сцен 35–90 с, set68-base 11 мин. Итог 272/272 TIMEOUT 0; галерея опубликована. run.sh scenes: очищать -scenes отчёт (резюм подхватывал старое).
- 18.08 Q6b–Q6e внедрены (мастер-план MASTER-zones-v7):
  · Q6b уголок: `build_edge_nook`/`place_edge_nook` (банкетка спинкой к глухой стене + стол кромкой вровень 0–3 см + ≥2 стула; формы edge_nook_4/5/6), `check_edge_nook_contract` (NOOK_* H0: опора на стену, ≥4 места, зазор, торец ≥60, отодвигание ≥55), `Item.caps` (места — из caps.guaranteed_seats, не из ширины), банкетка — член обеденной группы (иначе ACCESS_BLOCKED везде). Codex-правки учтены (`codex-prompts/q6b-edge-nook.answer.md`): окно спинкой — вне Q6b (→Q8), inferred-высота только для backless.
  · Q6a-фикс: категория банкетки по РЕГЕКСУ (divan.ru лист «Пуфы» терял 20 SKU) + высота сиденья backless-банкетки как inferred → годных для уголка 0 → 7 (divan.ru 5, nonton 2); банкеток в индексе 27→53.
  · Q6c: альтернативный комплект столовой в compose2 (≤25 м², банкетка совместимая со столом 0.5–1.2, разнообразие по стилю; 49 сетов) + каскад island → EDGE_NOOK → голый edge в place_dining; проверено: set46-base (23 м²) — уголок встал.
  · Q6d: `Item.round_shape` — круглый стол/столик как окружность реального диаметра (Ø110: 0.95 м² вместо bbox 1.21); адаптер ставит флаг по dia или имени «круглый/овальный» при w≈d; dining_round_compact из sleeping → implemented.
  · Q6e: `place_console_behind_sofa` + `check_console_contract` (CONSOLE_* H0: глубина ≤40, высота ≤ спинки+5, длина ≥половины дивана, вплотную ≤10 см); исключения NOT_AT_WALL/ACCESS для связки диван↔консоль.
- 18.08 ГРАБЛИ (моя ошибка): `git checkout <commit> -- <путь>` при бисекте СТЁР несохранённые правки Q6b (файлы не были закоммичены) — пришлось восстанавливать по памяти. Правило: перед любым checkout/stash в диагностике — коммит или явная копия.
- 18.08 тесты: mirror-тест переписан на МЕХАНИЗМ (победитель = минимальный quality-ключ; после снятия допусков обе стороны дают равный ключ), render-semantics смотрит render_plan.py, FAR-планка 41→42 с зафиксированным долгом (ремап ролей).
- 18.08 Q8 «окно» ВНЕДРЁН (владелец по галерее №3 + Codex `codex-prompts/q8-window.answer.md`): `services/planner-solver/planner/back_gap.py` — единый класс полосы за спинкой (hugged <15 | air 15–30 | route ≥91 | functional | orphan 31–90 пусто), данные `occupancy.window_sofa.back_gap_policy` (Livingetc 6–8″/3 ft, Ideal Home ~12″; запрет orphan — продуктовое правило владельца). КОРЕНЬ проблемы: наше правило SOFA_SLIVER разрешало ровно 80 см и ЗАПРЕЩАЛО норму 15–30 → 79 сцен «диван далеко от окна». Переписано на класс; SOFA_ORPHAN_BACK_GAP (S1) + ярус orphan в plan_key v1/v2 выше мягких термов; радиатор — по лицевой грани (иначе отчёты врали: 32 см от стены = 17 см от радиатора = air); Г-диван — только диагностика (габаритный bbox не описывает две спинки); при MEDIA_MISSING правило ОСЛАБЛЯЕТСЯ (retry + `back_gap_forced`) — отступ не выше required-зон.
- 18.08 Q9 (тень): `tools/scout/rules/practice_priors.json` (исходы по возможностям + частота предметов, status shadow_hypothesis, честный провенанс: BHG/H&G/AD подтверждают направление, не проценты) + `services/planner-solver/planner/opportunities.py` (window/seating_center/free_corner/primary_wall → выбранный исход) + `_opportunities` в артефакте и `prior_would_choose` в трейсе. Приоры — ordinal tie-break между равноценными достижимыми исходами, включение только после слепых пар (Codex `q9-zone-priors.answer*.md`); rules_audit расширен на rules/*.json конвейера.
- 18.08 регрессы «только каноны» вскрылись и починены: Г-диван — столик канонически к активной оси + допуск оси от полной длины посадки (иначе ни один диван не вставал в 57 м², set113); сторож «тихого edge» принимает задокументированный отказ острова (island_candidates_failed + счётчики).
- 18.08 ИТОГ экзамена: 269 ok + 3 честных MEDIA_MISSING, TIMEOUT 0, p50 34 с; полоса за спинкой: 143 проход / 70 прижат / 56 воздух / 3 orphan (было 93 orphan); у окна: диван 73 (было 87), кресла 43 (было 21); столовая 238, медиа 269, уголков 10.
- 19.08 Q10 «приблизиться к практике» (владелец прислал частоты; Codex `codex-prompts/q10-close-gap.answer.md`, `q10-seat-distribution.answer.md`):
  · Q10-0 честный сертификат возможности (`planner/opportunities.py: certify`): состояния occupied_by_required_zone / forced_empty_inventory / forced_empty_geometry / not_attempted / free_intentional; углы больше не считают дверь и радиатор; исход по зоне/варианту, не по пересечению полосы. ОТКРЫТИЕ: «пусто у окна 52%» — это не выбор, а «не пробовали» (у нас не было оконной зоны).
  · Q10b `place_window_reading` (`tpl_variant=window_anchor`, тег цепочки `+wr`, до общего reading): кандидаты у проёма и по бокам, лицо в комнату/к главной группе, отступ от лицевой грани радиатора; у ОКНА кресло самодостаточно — паспорт снимает `min_composition` для формы window_anchor (`reading.variant_invariants_exempt`), у произвольной стены правило осталось. Форма схемы (`variant`) теперь в `_templates` артефакта.
  · Замер после Q10b (272): уголок пробуется везде — встал 10, «нет свободного кресла» 113, «нет валидной позиции» 149.
  · КОРЕНЬ: ключ сравнения считал богатством только НОМИНАЛЬНУЮ ступень лестницы (`-seat_rank`), поэтому «диван+кресло во фланге» всегда бил «диван + кресло у окна» при равном числе мест. Внедрено В ТЕНЬ: `realized_capacity` (паспортные места главной группы + валидные кресла зон quiet/reading/bay) + ярус `primary_sofa_missing` («диван обязателен, когда достижим») + `plan_key_capacity`; в трейсе `capacity_would_choose`. Замер по 272: другой выбор в 108 сценах, из них 9 — в пользу кресла у окна.
  · Семейство `window_armchair_transfer` добавлено в паспорт beam (reserved) — гипотеза «нижняя диванная ступень + кресло у окна».
  · Экзамен после всех правок: 269 ok + 3 честных MEDIA_MISSING, TIMEOUT 0.

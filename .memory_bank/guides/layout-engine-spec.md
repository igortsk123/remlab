---
tier: 2
topic: layout-engine-spec
scope: Спека прод-ядра авторасстановки (beam search + семантический планировщик + скоринг + clean-room) — рекомендация ChatGPT, принята владельцем как основа
tier1: ../core/layout.md
updated: 2026-08-03
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

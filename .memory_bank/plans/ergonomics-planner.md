---
workstream: furniture
slug: ergonomics-planner
title: Планировщик расстановки — эргономика + гибрид Gemini/Holodeck (Ф3–Ф4)
status: draft
created: 2026-08-01
updated: 2026-08-01
completed:
---

## Цель
Расстановка списка мебели (габариты из каталога) в прямоугольной комнате 2D top-down:
модуль правил эргономики (TS, данные) + гибрид «Gemini выдаёт пространственные отношения →
солвер Holodeck DFS считает координаты → TS-валидатор проверяет hard-правила».

## Источник задачи
Владелец 2026-08-01 (мебельный трек, ADR-0042). Зависит от `gdeslon-catalog` (габариты).
Дорезерч: коммерчески чистых обученных моделей НЕТ (все на 3D-FRONT → non-commercial);
берём НЕ-ML солвер `DFS_Solver_Floor` из Holodeck (Apache-2.0).

## Прочитай сначала
- ADR-0042; ресёрч-факты в `~/.claude/plans/divan-ru-sunny-marble.md` (эргономика-таблица, дорезерч моделей).
- Holodeck: `ai2holodeck/generation/floor_objects.py` строки ~456–1138 (`DFS_Solver_Floor`),
  `prompts.py` (онтология отношений). MILP-ветку (GUROBI) НЕ брать.
- Few-shot: HF `B3rrYang/3D-SynthPlace_indoor_scenes_dataset` (Apache-2.0) — ТОЛЬКО uid `HOLODECK-*`
  (`3DFRONT-*` — non-commercial родословная, НЕ трогать).
- `lib/providers/traced.ts` — Gemini через трейсинг (ADR-0013); `deployment.md` (docker, remlab-net).

## Скоуп — что входит
**Ф3 эргономика (TS, данные отдельно от солвера):**
- `lib/ergonomics/rules.ts` — диапазоны {min, comfort, optimal} см + source (Нойферт/DIN 18011,
  NKBA, RU-практика): проходы 60/70/90/110; диван↔столик 30–50; диван↔ТВ = диагональ×2.54×k
  (1.2–1.6, мин 180); диван↔кресло ≤200; кровать 70 с боков; стол 80 до стены, 60–70/чел;
  створка шкафа 80, ящики +45; заполнение ≤50%. Госнорм между мебелью НЕТ — это эвристики.
- `lib/ergonomics/clearances.ts` — requiredClearances(role, dims) → зоны отступов по сторонам.
- `contracts/planner.ts` — FurnitureRole, RoomSpec (w/d, двери с дугой, окна, радиаторы), PlacedItem, LayoutResult.
**Ф4 планировщик:**
- `services/planner-solver/` — мини-Python-сервис (CPU, БЕЗ ML/GPU): скопированный
  `DFS_Solver_Floor`+`SolutionFound` (Apache-2.0 хедер+NOTICE сохранить; milp_dfs/visualize_grid
  выбросить); deps numpy/scipy/shapely/rtree; FastAPI `/solve`; docker в `remlab-net`, mem_limit.
- `modules/planner/constraints-gen.ts` — Gemini structured output по онтологии Holodeck
  (edge/middle, near/far, in front of/side of, center aligned, face to); few-shot из
  `data/planner/fewshot/*.json` (20–50 living-room HOLODECK-* сцен); Gemini чисел НЕ считает.
- `modules/planner/validate.ts` — hard-правила ПОВЕРХ солвера (проход ≥70 связный, зоны
  открывания, диван↔ТВ ≥180, окна/радиаторы) → violations[] + повторный прогон с блокировками.
- `modules/planner/index.ts` — planLayout: Gemini → солвер → валидатор; детерминированный сид;
  фолбэк без Gemini — статичные констрейнты по ролям (диван edge, столик in front of, ТВ face to).
- `tools/planner-render.ts` — SVG top-down для отладки и чекпоинтов владельца.

## Скоуп — что НЕ входит
Непрямоугольные комнаты; «комната из фото» (протокол съёмки: 3–5 фото, А4 на полу, уголок
потолка в кадре — зафиксирован, реализация в `room-measurement-a4`/`unified-measurement-pipeline`);
UI (в `living-room-sets` Ф6); MILP-эскалация (только если DFS не тянет: SCIP/CBC/HIGHS);
переписывание CV-кода mltest.

## Файлы к изменению
- [ ] `lib/ergonomics/{rules,clearances}.ts`, `contracts/planner.ts` (новые)
- [ ] `services/planner-solver/{solver.py,main.py,requirements.txt,Dockerfile,NOTICE}` (новый сервис)
- [ ] `modules/planner/{constraints-gen,validate,index}.ts`, `tools/planner-render.ts` (новые)
- [ ] `data/planner/fewshot/*.json` (отобранные HOLODECK-* сцены)
- [ ] compose (новый сервис в `remlab-net`; VPN-ноду remnanode НЕ трогать), `lib/env.ts` (PLANNER_SOLVER_URL)
- [ ] `tests/unit/{ergonomics,planner-validate,constraints-gen}.test.ts`, golden-комнаты, контракт-тест Zod↔pydantic, python-smoke в CI

## Задачи
- [ ] Ф3: rules + clearances + контракты + тесты (владелец ревьюит таблицу правил)
- [ ] Ф4: выдрать солвер + сервис + constraints-gen + validate + оркестрация + SVG + few-shot отбор
- [ ] Golden-комнаты (5–6): hard-правила проверяются программно, сид воспроизводим
- [ ] Чекпоинт владельца: SVG-раскладки golden × 2–3 набора мебели → итерация промпта/весов

## Критерии приёмки
- [ ] Lint / build / тесты (TS + python-smoke) проходят; нет ошибок типов
- [ ] Типовой набор (6–8 предметов) в комнате 18 м² решается ≤ ~5 с на CPU
- [ ] 0 hard-нарушений на golden-комнатах (программная проверка, не снапшот)
- [ ] Фолбэк без Gemini работает; вызовы Gemini — через traced (трейсинг)
- [ ] Apache-2.0 хедер + NOTICE на месте; ничего из 3D-FRONT-родословной не использовано

## Definition of Done — память (без этого `completed` запрещён)
- [ ] Memory Bank: новая область → `core/planner.md` (decision tree), `core/architecture.md`
  (+сервис planner-solver), `deployment.md` (если менялся compose)
- [ ] «Уроки» заполнены; отброшенное → `core/lessons.md`
- [ ] `/memory-check` выполнен, audit «чисто»

## Лог выполнения
- 2026-08-01 — план создан (draft); дорезерч моделей: готовых коммерчески чистых нет,
  выбран гибрид Gemini+Holodeck DFS (обоснование в ADR-0042)

## Completion summary

### Уроки (ОБЯЗАТЕЛЬНО; для partial/cancelled — особенно)

## Follow-up work
- [ ] Письмо в Planner 5D B2B про API авторасстановки (опция, владелец; план на этом не строим)
- [ ] MILP-эскалация (SCIP/CBC/HIGHS), если DFS не потянет плотные комнаты

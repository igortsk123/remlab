---
workstream: layout+catalog+viz
slug: MASTER-truth-first
title: "Мастер: truth-first — итог аудита рефери v2 (данные → eval → реальные комнаты → SKU)"
status: in_progress
created: 2026-08-08
updated: 2026-08-08
completed:
---

## Цель
Закрыть четыре «сдвигающих оценку» разрыва по итогам полного аудита рефери (8.2 R&D / 8.7
солвер / ~6.0 готовность) и его финального вердикта: солвер НЕ трогаем, следующий скачок —
**истина данных на входе → истина оценки → реальные комнаты → идентичность SKU на выходе**.
Плюс дешёвые P0-предохранители и принятые P1 (глобальная сборка сетов, constraint-CI).

## Источник задачи
Диалог с рефери 07–08.08 (3 раунда): его md-аудит на 49 разделов → наш ответ v2 с пруфами
(`/home/pakar/referee-reply-audit-v2.md`, https://remont-lab.online/test/referee/reply-audit-v2.html)
→ его разбор ответа (оценки подняты, solver evidence 6.8→8.0). Критическая оценка каждого
пункта уже сделана и зафиксирована: `MASTER-zones-first.md`, секции «Аудит рефери v2» и
«Раунд 2» (принято / частично с нашими пруфами / отклонено с причиной). Его правило принято:
**«принято в план ≠ исправлено»** — ничего не объявляем solved без измеримой приёмки;
числа бенчей подписываются commit'ом и между ревизиями не переносятся.

## Критическая оценка (сводно; полная — MASTER-zones-first)
- Наш пруф по габаритам подтвердил его P0 другим механизмом: `unit=` в фидах НЕТ, но
  `>400→/10` калечит ~46 см-товаров (диваны 440–442 см → «44 см») и одновременно нужен
  tvoydom/gipfel (мм). Его поправка принята: manual-override не проигрывает свежему фиду.
- Его гипотеза-ловушка про side-table проверена кодом и НЕ подтвердилась (приставной —
  отдельная роль в солвере) → в T6 только smoke-инвариант.
- Отклонено (с причиной, см. MASTER-zones-first): deterministic 3D shell сейчас, слепая
  миграция TRELLIS.2, немедленный полный Constraint-IR.

## Скоуп — что входит (волны T0–T6, порядок = ROI рефери)

### T0 — P0-предохранители конвейера (дёшево, до всего остального)
- `enrich_wait.sh` + `enrich.fetch`: терминальность по РЕЗУЛЬТАТУ — инварианты
  `completed && готово==0 → FAIL+алерт`, `error_rate>порога → FAIL`, `gate_age>SLA → FAIL`;
  разклинить текущий гейт (батч 1 859 карточек divan/mdm) и дообогатить хвост.
- Алерт «исторически непустой фид отдал 0 офферов» (сейчас пустой 10-й фид молчит) и
  freshness SLA: `feed_age_hours` → `fresh|degraded|stale`; stale-товары не попадают в
  НОВЫЕ сеты (heal существующих — можно).
- Метрики best-effort трейсинга прод-сайта: `trace_write_failure_rate`, `missing_trace_count`.

### T1 — Resolver размеров (data truth; его пункт №1)
- Dimension evidence вместо одного числа: `feed_param / title_parse / product_page / manual`,
  каждый с provenance и датой; манипуляции `>400→/10` в `load3.py` больше нет.
- Приор единиц **shop × parameter/category** (confidence, support_count, learned_from),
  defeasible: per-item свидетельство (единица в ИМЕНИ параметра «…, мм/см», титул «Ш×Г×В»,
  страница) перебивает приор. Manual — с authority (`verified`, TTL, снятие только
  ревалидацией/человеком), recency сравнивается внутри уровня доверия.
- Автотесты: resolved-значение против распределения (role, shop, parameter); явная проверка
  гипотез ×10/÷10; починить 46 известных битых офферов (список — по прогону 08.08).
- Evidence ledger приоров (version/sample_count/confirmed_by/conflicts/generated_at) — как
  provenance внешних правил.

### T2 — Истина оценки (human gold + merge)
- `gold-human-v1`: 300–500 товаров, стратификация (роль/магазин/качество фото/полнота
  размеров/описание/редкие подтипы), метка `uncertain`. Схема разметки: A+B на всём,
  арбитр C на конфликтах, НЕЗАВИСИМЫЙ C-прогон на 25–30% (для честного agreement);
  Krippendorff α (nominal/ordinal), по каждому стилю отдельно; низкий α по признаку =
  чинить guideline/объединять лейблы. **Оплата разметчиков — решение владельца.**
- Метрики: macro-F1 роли, per-role P/R, confusion, калибровка; текущие 92.6/89.8/97
  везде переименованы в «model-agreement». Порог `quality 0.65` пересчитан по реальному
  precision/coverage. Судья сетов (gpt-5-mini) откалиброван на 100–300 human-оценённых
  коллажах (rank-correlation, 2 перестановки против position bias).
- Merge text/vision починен + ablation (text / image / оба / rules+оба) на human gold;
  мультимодальность не даёт прироста → упростить, не тащить.

### T3 — Реальные комнаты (главный product gap)
- Подключить `services/room-measure` к мебельному треку: выход замера (контур, проёмы,
  радиаторы) → вход `solver_run` (формат `SCENE_CONTOUR` уже есть).
- Второй frozen-бенчмарк: 100–300 реальных/репрезентативных планировок (narrow, L, эркер,
  колонны, трапеция, дверь у угла, несколько проёмов, радиатор под окном); 252 синтетики
  остаются regression-набором. + property-based fuzzing легальных полигонов (no crash /
  valid / deterministic / bounded runtime).
- Метрики приёмки против деэскалации состава: `required_recall`,
  `optional_weighted_retention`, `target_seating_achieved`, `mean_items_placed`, runtime p95.

### T4 — SKU-identity QA (commerce-верность кадра)
- Свой бенчмарк same-series hard-negatives из каталога (та же серия: другой цвет / ножки /
  подлокотники / число ящиков / конфигурация), positives (карточки одного SKU, доверенные
  Trellis-рендеры, принятые кропы, C1↔C2); **split по product family**; метрики Recall@1/5,
  ROC/PR-AUC, приоритет — false accept чужого SKU. Референс для sanity — DeepFurniture
  (source: external:arXiv 1911.09299 — проверить при реализации).
- Пайплайн проверки: mask/silhouette + DINOv2/DreamSim baseline (порог ТОЛЬКО с бенча) +
  сравнение структурных атрибутов из обогащения (arms/legs/base/ящики) + retrieval своего
  SKU в top-K; провал hard-пар у zero-shot → маленькая contrastive-голова.
- Cross-view identity C1↔C2; mesh-QA: сравнивать соответствующий ракурс/несколько фото
  (novel views — только self-consistency); pin снапшота gpt-image-2; бенч финальной модели
  на 30–100 сетах (один сет = smoke).

### T5 — Глобальная сборка сетов (P1)
- `compose2`: top-K на роль → beam/CP-SAT/local search с set-level целью (style_fit +
  парная совместимость + гармония материалов/массы/цвета + пропорции + цена корзины +
  живучесть наличия + разнообразие между сетами). Приёмка против текущего greedy: те же
  126 слотов, замер style_fit/судья/proportions/выживаемость.
- Whole-basket budget: `target_total(area, tier)` + эластичность ролей; heal → глобальный
  rescore, при просадке — локальная переоптимизация 1–3 связанных слотов.
  **Целевые суммы — решение владельца.**
- Ontology: шторы геометрией от окна (WINDOW-стадия, без floor-footprint) — закрыть дыру
  126/126.

### T6 — Солвер-гигиена и CI (без изменения архитектуры)
- **Constraint-contract CI** (обобщение уроков 203/204): (1) пересечение допусков каждой
  required-пары непусто; (2) satisfiability каждой atomic-группы в канонической пустой
  комнате; (3) монотонность (комната больше → не стало невозможным); (4) smoke «каждый тип
  якоря даёт ≥1 позицию»; (5) rule-delta регрессия порогов.
- ТВ: одна каноническая функция distance-first (candidates/validate/scene_build/prompt).
- Вычистить legacy `sofa_table_cm` из candidates/score; развести буферы 40/65/30 семантикой.
- Повороты: (а) wall-tangent корпусной мебели у косой стены — geometry correctness, отдельно
  и раньше; (б) кресла ±15/30/45/60 — только после замера binding-частоты (challenger A/B на
  frozen-бенче: rescue-rate, score delta, runtime p95, human preference).
- Smoke-инвариант «приставной не ловит правила столика»; ProcTHOR-дуга: дописать commit
  SHA+path или переименовать в «internal heuristic inspired by».

## Скоуп — что НЕ входит
- Переписывание/замена солвера и отказ от explainable-правил стиля (вердикт рефери: не менять).
- Deterministic 3D shell вместо ControlNet (P2, вернуться при architectural drift).
- Миграция TRELLIS.2 (только A/B-челленджер на 50–100 трудных SKU в T4, «test before spend»).
- Полный Constraint-IR (остаётся W7 — после T6, когда стоимость поддержки реестра оправдает).
- Юр. вопросы лицензий картинок магазинов — TODO + решение владельца (по CLAUDE.md).
- ML-обучение стиला с нуля (урок 195); спальня; UK.

## Зависимости и связанные планы
- `MASTER-zones-first.md` — очередь солвера (вытянутые комнаты, регулярность, human A/B)
  живёт там; T6 не дублирует её. `inventory-additions.md` (ADR-0078) — завершить до T5.
- `MASTER-catalog-ai.md` (in_progress) — T1/T2 его продолжают; А1 (дельта→переобогащение)
  закрывается вместе с T1.
- Блокер: кредиты OpenAI (батчи T0-хвоста, судья T2) — пополнение = владелец.

## Решения владельца (не Claude)
Оплата разметчиков gold-human-v1 и дизайнеров human A/B · целевые суммы корзины (T5) ·
пополнение биллинга OpenAI · юр. проверка использования картинок магазинов.

## Файлы к изменению (основные; уточняется на «деплой» каждой волны)
- [ ] `tools/scout/enrich_wait.sh`, `tools/scout/enrich.py`, `tools/scout/refresh_daily.sh` — T0
- [ ] `tools/scout/load3.py` (+ новая `tools/scout/dim_resolver.py`, миграция
      `002-dimension-evidence.sql`) — T1
- [ ] `tools/scout/golden_*` (+ новые gold-human скрипты/страница разметки) — T2
- [ ] `tools/scout/solver_run.py`, `services/room-measure/*` (мост), новый
      `tools/scout/acceptance_real.py` — T3
- [ ] `tools/scout/viz_qa.py` (+ новый `sku_identity.py`, `sku_bench.py`) — T4
- [ ] `tools/scout/compose2.py` (+ set-level scorer) — T5
- [ ] `services/planner-solver/tests/test_contracts.py` (новый CI-джоб), `candidates.py`,
      `validate.py`, `score.py` — T6

## Критерии приёмки (мера = «solved», не «принято»)
- [ ] T0: искусственный битый батч и пустой фид дают алерт ≤1 прогона; гейт разклинен,
      1 859 карточек обогащены.
- [ ] T1: 46 известных битых офферов исправлены; на выборке 200 товаров с известной истиной
      resolver ошибается ≤2%; ни одного товара без provenance размера.
- [ ] T2: gold-human-v1 существует (α ≥ порога по объективным признакам), метрики
      переименованы, порог 0.65 пересчитан, merge даёт измеренный вердикт (нужен/не нужен).
- [ ] T3: замер → солвер работает end-to-end на ≥20 реальных комнатах; real-бенч frozen
      и закоммичен; метрики retention публикуются рядом с clean-rate.
- [ ] T4: SKU-бенч frozen; false-accept чужого SKU на hard-парах ниже согласованного порога;
      QA включён в batch_collage как ворота.
- [ ] T5: set-level сборка ≥ greedy по судье/style_fit при не худшей выживаемости; бюджет
      корзины соблюдается в заданном коридоре.
- [ ] T6: constraint-CI зелёный в GitHub Actions; одна ТВ-функция; legacy-шкала удалена;
      повороты — по результату замера binding.
- [ ] Каждый бенч-результат подписан commit/config.

## Definition of Done — память (без этого `completed` запрещён)
- [ ] Memory Bank обновлён: `core/catalog.md` (resolver), `core/regression-net.md` (CI и
      бенчи), `core/layout.md`, `core/furniture.md`, `decisions.md` (ADR на resolver,
      gold-human, SKU-QA), `project-state.md` (снимок).
- [ ] Новая область «SKU-identity QA» видна в decision tree (при появлении кода — core-сводка).
- [ ] Уроки перенесены в `core/lessons.md`; `/memory-check` выполнен, audit «чисто».

## Лог выполнения
- 2026-08-08 — план создан (draft) по итогам 3 раундов диалога с рефери.

## Completion summary
[при завершении]

### Уроки (ОБЯЗАТЕЛЬНО)
[при завершении]

## Follow-up work
- [ ] W7 Constraint-IR (после T6) · P2: persona/activity-сценарии, deterministic shell,
      слой регулярности LEGO-Net (очередь MASTER-zones-first).

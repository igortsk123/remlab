---
workstream: layout
slug: referee-hardening
title: Правки по арбитражу рефери (Q1–Q7 + 5 доп. находок)
status: in_progress
created: 2026-08-07
updated: 2026-08-07
completed:
---

## Цель
Довести движок и пакет правил по вердиктам внешнего рефери (арбитраж 08.08): что принято —
внедрить; что принято частично/в очередь — зафиксировать с обоснованием.

## Источник задачи
Отчёт рефери по `rules-for-referee-*.xlsx` (11 листов). Общий вердикт: production-core не
менять, zoned остаётся; 95% internal clean ≠ «дизайнерское качество» (нужен слепой human A/B).
Стоящее правило: планы исполняются подряд без спроса (владелец, мастер-план zones-first).

## Партия 1 — внедрено 08.08 (эта сессия)
- ✅ **Q5**: `FLOOR_OVERFILL` HARD→S1 (`validate.py check_floor_cap`, `rules/severity.json`);
  authoritative-метрика — band-scale `floor_cap_pct` валидатора.
- ✅ **Q6**: `FIREPLACE_FAR_FROM_SEATING` (S1): вне вилки 200–450 см от посадки ИЛИ вне
  сектора ≤75° от оси взгляда дивана (`check_fireplace_seating`, данные из zones.json).
- ✅ **Q7**: раздельно — доступ уже H0 (`WINDOW_BLOCKED`/`RADIATOR`); `SOFA_WINDOW_GAP` (S1,
  зазор <15 к окну за спинкой); `SOFA_BACK_ABOVE_SILL` (S2, спинка выше sill_cm проёма).
- ✅ **Q1 + п.3.3**: ярусы = приоритет удержания, не обязательный инвентарь — не влезшие
  dining/storage дропаются ярусом в skipped (`beam.solve`), обеденная «целиком или никак»
  (стол + ≥2 стульев, вердикт владельца); 6 м² остаётся префильтром состава.
- ✅ **P0×8 экспорта**: комментарии size-bands/zones/placement_tiers/armchair_to_table,
  один provenance-блок weights, дата из одного источника, лист «вердикты рефери» в xlsx.
- ✅ Попутно: DFS-фолбэк убран из ENGINE=zoned (контаминировал A/B, давал таймауты);
  `SKIPPED` наружу в solver_run/acceptance (no silent caps).
- Тесты: test_fireplace_far_is_soft, test_sofa_window_gap_and_sill, test_floor_overfill_is_soft,
  test_dining_storage_drop_not_fail; 79 зелёных.

## Партия 2 — внедрено 08.08 (решение владельца: «делаем как рефери советует»;
## расхождение допустимо только с самостоятельно найденным пруфом из источников)
- ✅ **Q3**: `_behind_strip` локализована — ширина дивана + 100 см бокового запаса (покрывает
  «торшер за плечом», сет 25), не вся комната; «камин» убран из DEAD_BEHIND_ROLES — focal-behind
  ловит угловой чек `FIREPLACE_FAR_FROM_SEATING` (сектор 75°). Тест test_verdicts_0807 переписан.
- ✅ **Q4**: `requires_wall_back` / `room_divider_capable` (стеллаж) / `room_divider_capable_active`
  (пусто — divider-сценариев нет) в `occupancy.layout_rules`; `check_wall_only` читает из данных.
- ✅ **Q2**: валидатор — существует ли диагональ под дистанцию при приоре экран/тумба 0.70–0.90
  (не точка 0.70): hard [1.2·d_min, 2.5·d_max]; генератор (zones_brief) — distance-first
  инструкция (diag ≈ дистанция/1.6, clamp 70–90% тумбы).
- ✅ **5.1**: `proportions.json` — флаг `hard` у каждого правила; эстетические (chair_h, rug×2,
  pouf_area, sofa_vs_wall, storage_vs_wall) вне allowed → штраф −1.5, НЕ отсев (proportions.py).
- ✅ **5.2**: канон высоты столика — zones `height_vs_seat_cm [-5,0]`; proportions
  `table_h_vs_seat` переведён в производную (allowed 0.78–1.08, preferred 0.89–1.0, why→канон).
- ✅ **5.3**: карта классов маршрутов в `occupancy.distances_cm._route_classes`
  (primary_route/secondary_route/object_access/tight_fallback ↔ существующие ключи);
  переименование ключей — в IR (W7).
- ✅ **5.4**: `dynamic.narrow_room` помечен как КАНДИДАТ-ШАБЛОНЫ (не канон-констрейнты);
  enforcement в коде и не было — вытянутые провалы это солверная работа (см. очередь).

## Партия 3 — рефери-ФИНАЛ 08.08 (9.2/10; «после этих правок и полного прогона вопрос
## архитектуры практически закрыт») — внедрено
- ✅ SOFA_SLIVER: H0→H1 в реестре («не физика, а качество планировки» — его «самая явная
  ошибка таксономии»); H0 переопределён как physical/mandatory operability.
- ✅ Stale-описания «шкалы от площади» убраны из docstring check_distances (реестр кодов
  генерится из него).
- ✅ TOC: size-bands «priors, не гейт», proportions «hard functional + soft aesthetic».
- ✅ Единый canonical приор экран/тумба 70–90% (item_share был 66–75 — рассинхрон с Q2).
- ✅ zones fireplace `behind_seating: forbidden → penalized` (данные соответствуют S1-коду).
- ✅ floor_cap: provenance «internal empirical furnishing-density prior» (не норматив).
- ✅ table_h_vs_seat: overshoot до 1.08 — «tolerable fallback ограниченного каталога, не target».
- ✅ `--date=` в rules_export: имя файла и оглавление из одного STAMP (P0.1).
- ✅ ADR-0076 «один лейбл движка — один алгоритмический путь» + test_engine_purity.
- Реестр: 48 кодов — H0×9, H1×26, S1×10, S2×3 (после переноса SOFA_SLIVER в H1 и добавления
  SERVICE_SURFACE; ранняя редакция этой строки писала «H0×10/H1×25» — исправлено по сверке
  из сводного документа конвейера).
- Его п.12 (frozen visual/function A/B людьми) = наш пункт очереди №5.

## Очередь (остаток)
1. **Вытянутые комнаты** — солверная работа над long-сценами (кандидаты/оси), замер на 63 long.
2. **5.5 слой регулярности** (LEGO-Net): collinearity/co-circularity/rotations в aesthetics-низ.
3. **FOCAL_BEHIND_MAIN_SEAT** отдельным правилом при мульти-focal сценариях (сейчас покрывает
   угловой чек камина).
4. **Развод floor-cap метрик** (3 representations → 4 метрики) + **W7 constraint-IR**.
5. **Human blind A/B** (50–100 сцен, functional?/well-composed?) — РЕШЕНИЕ ВЛАДЕЛЬЦА (дизайнеры);
   VLM-челленджер top-K — после оплаты судьи.

## Критерии приёмки
- Партия 1: 252-прогон без «шумовых» провалов (не влезшие dining/storage не валят сцену),
  новые S-коды видны в SOFT-выдаче; xlsx с листом вердиктов пересобран; тесты зелёные.
- Партия 2: свой замер на каждом пункте (long-сцены, фикстуры ТВ, единый канон столика).

## Материалы для рефери
- Сводный документ «весь конвейер: фиды → каталог → обогащение → сеты → зонный солвер →
  визуализация» (обзор для рефери, собран 2026-08-07 разбором кода/dev-БД/банка):
  https://claude.ai/code/artifact/0aaa437b-26f5-47d3-b878-aac54f8c52ba
  В нём же — найденные при сборке расхождения: H0×9/H1×26 в реестре vs «H0×10/H1×25» в этом
  плане (SOFA_SLIVER перенесён, прозаический счётчик не пересчитан — см. строку 70);
  заклинивший vision-батч обогащения 1859 карточек (completed/0 готово, гейт закрыт,
  enrich_wait.sh не алертит); пустой 10-й фид; NameError в viz_final.py --cam.
- Пакет правил: `rules_export.py --referee --date=...` (13 листов xlsx).

## Связанные
`plans/MASTER-zones-first.md` (секция «Рефери-арбитраж 08.08») · `rules/severity.json` ·
`core/layout.md`

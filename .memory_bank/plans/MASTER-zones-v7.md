---
workstream: layout
slug: MASTER-zones-v7
title: МЕТАПЛАН — свод №13 (слепая оценка раунд 1 + каталог nook): ключ по глазу владельца, кресла к ТВ, фронтальная зона, банк→солвер, nook/консоль из фида
status: in_progress
created: 2026-08-16
updated: 2026-08-16
completed:
---

## Цель
Привести выбор плана (plan_key) к тому, как реально ранжирует владелец (слепая оценка), закрыть
дыру передачи банка солверу (большие комнаты недомеблированы не из-за каталога), дать креслам
медиапригодные формы, ввести фронтальную зону, и разбудить nook/консоль из уже имеющегося фида
(без «Кухонных уголков» и «Столов-книжек» — решение владельца).

## Источник задачи
Слепая оценка владельца, раунд 1 (10/20 пар: beam 2, greedy 5, оба плохи 3 —
`_intake/blind-round1-owner.md`) → самоанализ → аудит Кодекса с замерами по артефактам
(`_intake/codex-audit-blind-round1.md`, /test/codex-blind-round1.md) — мнения совпали;
+ каталожный аудит nook/консоль (`_intake/codex-audit-catalog-nook.md`, /test/codex-catalog-nook.md,
выгрузка `_intake/catalog-extract-nook.txt`) — владелец согласен с моделью Кодекса.
Ревью драфта Кодексом (`_intake/codex-review-v7-draft.md`): порядок исправлен (формы кресел ДО ключа,
сертификатный контракт, identity-адаптер, Q5 разбит, слепой протокол 80+12); учтено ниже.

## Диагноз (проверено по коду/артефактам)
1. **plan_key ≠ глаз владельца.** Номинальный `seat_rank` (имя ступени) стоит выше прохода/
   функционала (04: beam взял «богаче по имени», у greedy реально пуф; 07: floating Г-диван
   победил hugged); нижние ярусы (суммы штрафов) для глаза неразличимы (02/03/06/09).
2. **Нет правил, которыми владелец ранжирует:** (а) маршрут от двери через коридор диван→ТВ
   (01: 49 vs 166 см) — в `zones.json:403` `route_between_sofa_and_tv: forbidden` есть,
   runtime-проверки нет; (б) кресло медиапригодно ≤45° к ТВ (02/05/09) — `armchair_faces_tv`
   слабый терм и считает только роль `кресло`; (в) столовая во фронтальном конусе (05/06/10:
   100/31/94% перекрытия) — терма нет; (г) наполнение ТВ-стены компаньонами (02/08/09/10) —
   терма нет, `TALL_ON_TV_WALL` штрафует желаемое; (д) дальность кресла до ТВ (03).
3. **Формы кресел:** default 90/270 (поперёк), facing 180 (к дивану), bridge 135/225 (назад),
   tandem поперёк — ни одна не даёт «параллельно дивану / полуоборот к ТВ» (`template.py:646`).
4. **Банк не доезжает до солвера.** `solver_run._extra` строит экземпляры только из `qty`
   базовой роли + `диван 2`; отдельные роли `кресло 3/4` (второй pod) и alt-`кресло 2` (P4)
   в FLOOR не попадают → «57 м² и одно кресло» (set110/set126: в банке есть, в `its` нет).
   `_bank_unused` в артефакте нет — нельзя отличить «отфильтровано» от «не влезло».
5. **plan_key.have** не учитывает `storage` как preferred (есть в JSON).
6. **Каталог (nook/консоль):** товары есть — 17 банкеток (в роли «пуф»), 42 кушетки 120–130×55–58
   (в роли «диван», 152 всего), 3 скамьи, 572 узких комода Г 33–45, 8 «консольных тумб» 150×35×22
   (это низкие ТВ-элементы), 124 «раскладных» (только 8 ≤90 в сложенном; слово не доказывает
   посадку в сложенном), 7 круглых ≤110. Разделять категории размером нельзя (высота 68 —
   подлокотники, не сиденье; длинный пуф ≠ банкетка).

## Пакеты (порядок критичен; зависимости указаны)
Общий гейт каждого selection-changing пакета: frozen manifest 272 сцен + hash банка/правил/флагов;
ни одна планка не снижается (планки — по базе №1–252: dining ≥220, медиа 252; сцены №253+
append-only, отдельно: 269 ok + 3 сертифицированных MEDIA_MISSING); пороги только в JSON с
`value/unit/semantics/provenance/status`; новые приоритеты — ОТДЕЛЬНЫЕ лексо-поля, НЕ веса
(`weights.json` не трогаем); 0 фантомных габаритов; детерминизм (hash повтора); новых
таймаутов нет, p95 ≤1.5× baseline.

### Q0 — Baseline + диагностика + metric contract (выбор не меняется)
- Метрики ТОЛЬКО в артефакт (`_view`): `entry_sightline_gap_cm` (мин. зазор дверь→коридор
  диван–ТВ), `armchair_tv_angles` + `media_seat_ok(≤45°)`, `dining_view_cone_overlap_pct`
  (конус 45°), `frontal_companions` (стеллаж/витрина/комод/кашпо на стене носителя),
  `armchair_tv_dist_cm` vs `sofa_tv_dist_cm`, `realized_armchairs`, `realized_valid_flex_seats`,
  `has_actual_footrest` (пуф в зоне ног ≤110 см от посадки, не любой пуф).
- Fixtures: rectangle/L/trapezoid, несколько дверей, стенка как носитель.
- Гейт: выбор плана бит-в-бит прежний; blind-сигнатуры воспроизводятся (01: 49/166 см;
  05: 34.5° vs 54/81°; 10: dining-cone 0/94%) с допуском; pytest.

### Q1 — Identity-адаптер банк→солвер (shadow → scoped on)
- `solver_run`: raw bank без разрушительной нормализации; каждый SKU — `instance_id`,
  `base_role`, `bank_role`, `usage_scope`; qty-копии только если нет явной роли с тем же именем
  (`кресло 2` alt-SKU не перетирается qty-копией); `диван 2` семантику не расширять;
  `кресло 3/4` активировать сначала как `secondary_quiet` (исключены из counts главной лестницы);
  `стеллаж 2`/`комод 2` — shadow до storage-пакета. Phantom-check — по SKU id, не по имени роли.
- Артефакт: `_input_bank` и `_bank_unused` с терминальной причиной ∈ {adapter_excluded,
  not_claimed_by_enabled_template, template_infeasible, quality_rejected, feasible_not_selected,
  reserved_alternative, placed}.
- Гейт: при флагах off — hash == Q0; каждый SKU имеет ровно одну причину; set110/set126
  передают кресла 3/4 с габаритами SKU; экзамен без новых таймаутов.

### Q2 — Правила и provenance (данные)
- `zones.json → view_contracts`: `entry_sightline_min_gap_cm` (76 — действующий проход, H&G
  «не вести трафик перед ТВ», status=measured), `media_seat_angle_max_deg` 45 (Wayfair; measured
  на blind), `dining_view_cone_deg` 45 + `overlap_max_pct` 10 (owner-derived, status=hypothesis
  → shadow до контрфактуалов), `frontal_companions_min` по площади (≥20 м² 1, ≥30 м² 2 — только
  если атомарная сборка достижима; hypothesis → shadow), `armchair_tv_dist_extra_cm` 30
  (d_chair_tv ≤ d_sofa_tv + 30; hypothesis) + screen-based range, corner-контракт <30 м².
- `TALL_ON_TV_WALL`: освобождает ТОЛЬКО компаньона того же атомарного `media_installation`.
- Гейт: rules_audit 0; нет новых порогов-литералов в Python; ничего не добавлено в weighted score.

### Q3 — Медиапригодные формы кресел + сертификаты достижимости (зависит от Q1+Q2)
- `build_block`: `media_parallel` (одиночное кресло 0°/45°/315°), `media_bridge` (пара
  45°/315° вместо 135°/225°); intent-метки шаблонов `media_primary/conversation/quiet/fireplace`
  (паспорт `seating_groups[].shapes` + `intent`); квота beam на ≥1 media-aware форму, в т.ч. в
  `large_xl`. Проверка угла — к ФАКТИЧЕСКОМУ ТВ на готовом плане, не к локальной ротации.
- Сертификат `reachable_media_seat_ok` = существует hard-valid media_primary-гипотеза с креслом
  ≤45° к фактическому ТВ; иначе `SEARCH_GAP_MEDIA_SEAT` в артефакте.
- Гейт: для каждого media_primary fixture с достижимой геометрией в пуле есть такой кандидат;
  conversation/quiet/u остаются достижимыми; pair05/09 — smoke.

### Q4 — Новый plan_key (shadow, затем default после Q7; зависит от Q3)
```
(hard_count, missing_required_zones, unplaced_required_items,
 entry_sightline_violation, media_seat_violation_if_reachable, dining_view_cone_violation,
 small_room_corner_violation(<30 м²),
 missing_reachable_valid_preferred (столовая в конусе — НЕ покрытие; storage учитывается),
 frontal_composition_deficit, seating_deficit(armchair_policy count_by_area_m2),
 -realized_armchairs, -realized_valid_flex_seats, -has_actual_footrest,
 axis_class, circulation, functional, zone_quality, aesthetics)
```
- Номинальный `seat_rank` убран. Unit-тесты доминирования каждого яруса над нижними.
- Гейт: 10 пар раунда 1 — smoke (01/02/04/05/07 → greedy-выбор, 08/10 → beam), production —
  ТОЛЬКО после Q7; планки не хуже.

### Q5 — Посадка по площади и второй pod (зависит от Q1+Q4)
- `кресло 3/4` для large с 25 м² (композитор), парой ОДНОЙ модели/коллекции (случайная пара
  запрещена); `seating_deficit` в ключе; в сцене не допускается одно кресло, если существует
  кандидат с ≥2 и не худшим префиксом ключа до `seating_deficit`; 40+ — hard-valid second-zone
  кандидат либо причина ∈ {inventory_gap, template_infeasible, quality_rejected,
  search_budget_exhausted}. Бюджет large_xl — квота на второй pod.

### Q6a — Capability-модель каталога (данные)
- `cat_role` не менять; capabilities SKU (`seat_length/depth/height`, `has_back`,
  `wall_seat_capable`, `dining_seat_capable`, `nominal_seats`, `source_role`, `console_capable`,
  evidence per attribute); одна планировочная роль-слот `банкетка`; 152 кушетки сохраняют
  категорию (capability на 42); `seat_height` ≠ общая h; исключённые категории (уголки, книжки)
  проверяются по source/category ID; `dining_foldable` sleeping до state-data
  (closed/open, usable_seats_closed, closed_state_is_dining).
### Q6b — `build/place_edge_nook` (зависит от Q6a)
- Атом: банкетка спинкой к стене + стол + ≥2 стула со свободных сторон, или ничего; уникальный
  zone instance; door swing/pullout/route hard. Синтетические тесты.
### Q6c — Nook bundles + production каскад dining (зависит от Q6b)
- Композитор `alternative_bundles` (взаимоисключающие паспорта, ≤1 dining/residual bundle на
  сет; после добавления заново считаются total/style/diversity/identity/envelope — НЕ «после
  total» как alt-armchair); каскад island → round_compact → edge_nook → naked edge.
- Гейт: на frozen cohort «остров infeasible» доля naked edge строго ↓; ни один hard-valid
  island не заменён nook; role conservation.
### Q6d — Round compact (зависит от Q6a): круг = окружность реального диаметра, не bbox.
### Q6e — Low storage / console capability (последним; зависит от Q6a)
- `консоль` роли нет; узкие комоды/тумбы `console_capable` (Г ≤40 за диваном; h ≤ спинка+5 hard /
  ≤ спинка preferred; ширина ≥⅔ дивана — свести zones.json:376/749); service envelope ящиков;
  wall-run раньше behind-sofa.

### Q7 — Слепая валидация раунд 2 + rollout (зависит от всех активируемых)
- Протокол: 10 пар раунда 1 — только smoke; **80 новых пар** на ранее не использованных сценах
  (по 15 one-property контрфактуалов на каждый из 5 контрактов: маршрут, media-seat, dining-cone,
  corner, frontal + 5 целостных) + **12 скрытых повторов** с инверсией A/B; стратификация:
  ≥20 сцен <20 м², ≥20 20–29.9, ≥20 ≥30 (из них ≥10 40+); ≥20 elongated, ≥20 сложных контуров,
  ≥20 с 2+ проёмами; покрыть 0/1/2/4 кресла, прямой/Г-диван, банки с/без инсталляции.
  Пороги/порядок ключа заморожены ДО раунда.
- Фальсификация яруса: нарушающий вариант выбран ≥8/15 → ярус не включать; <10 решающих ответов
  → неопределённо (не «пройдено»). Deploy-гейт: нижняя граница 95% Wilson CI доли побед нового
  выбора > 0.5; повторяемость ≥10/12. Иначе — остаётся shadow.
- Два релиза: (1) core-ranking + second pod (Q0–Q5, Q7), (2) каталожная волна (Q6a–e) со своим
  раундом.

## Скоуп — что НЕ входит
- «Кухонные уголки», «Столы-книжки» (владелец); LLM-расстановщик; изменение размеров SKU;
  скорость (после «нормально работает» — владелец).

## Файлы к изменению (ориентир)
- [ ] `tools/scout/solver_run.py` — Q0 (FLOOR все роли; _input_bank/_bank_unused; _view метрики)
- [ ] `services/planner-solver/planner/{quality,score,validate,zones,template}.py` — Q0–Q3
- [ ] `services/planner-solver/rules/{zones,templates,occupancy,registry,severity}.json` — Q2/Q3/Q6 (weights.json НЕ трогаем)
- [ ] `tools/scout/{compose2.py,category_map.py?,capabilities.py(new)}` — Q4/Q5
- [ ] `services/planner-solver/tests/*` — гейты всех пакетов; `tools/scout/blind_pairs.py` — раунд 2

## Критерии приёмки мастера
- [ ] Q0: выбор бит-в-бит прежний; метрики воспроизводят blind-сигнатуры
- [ ] Q1: каждый SKU банка — ровно одна терминальная причина; флаги off ⇒ hash == Q0
- [ ] Q3: для media_primary fixtures есть hard-valid кандидат ≤45° к фактическому ТВ
- [ ] Q4: 10 пар раунда 1 — smoke; production только после Q7
- [ ] Q5: ≥25 м² — ≥2 кресла при наличии SKU одной модели; 40+ — вторая зона или причина
- [ ] Q6: nook там, где остров infeasible и bundle есть; role conservation; naked-edge ↓
- [ ] Q7: 80+12 пар, Wilson CI >0.5, повторяемость ≥10/12 — иначе shadow

## Definition of Done — память
- [ ] ADR; `core/layout.md`; уроки; `/memory-check` чисто

## Решения владельца (16.08)
1. Слепые раунды — **по 20 пар за заход** (сумма 80+12 добирается заходами; правила между заходами не трогаем).
2. Owner-derived пороги (столовая в конусе 45°/10%, компаньоны ТВ-стены) — **shadow** до своих контрфактуалов.
3. Три сцены без места под ТВ — **честный отказ** пользователю («решение с ТВ не найдено — вот план без ТВ, причина»), релиз не блокируется.
4. **Два релиза**: сначала (а) ключ + кресла к ТВ + второй pod (Q0–Q5, Q7) — показать владельцу сразу; затем (б) каталожная волна (Q6a–e) со своим раундом.

## Лог выполнения
- 2026-08-16 — план создан (draft) по слепой оценке раунд 1 + каталожному аудиту; переписан по ревью Кодекса; решения владельца зафиксированы.
- 2026-08-16 — «деплой» (владелец); старт Q0.

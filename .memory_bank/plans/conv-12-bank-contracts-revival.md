---
workstream: conveyor
slug: conv-12-bank-contracts-revival
title: Банк комплектов снова под контрактами — честный статус шага, синхронизация пары, миграция под Р1, тесты расстановщика не молчат
status: in_progress
created: 2026-10-20
updated: 2026-10-20
completed:
plan_kind: sub
parent_plan: MASTER-conveyor-gaps
---

## Цель
Банк комплектов (`tools/scout/sets3.json`) перестаёт расходиться с контрактами подбора; ночная цепочка показывает
«не применено», а не «ок»; тесты расстановщика ловят поломку и в CI, и на DEV.

## Источник задачи
Разбор T-20261020-04 (рабочий, 20.10): 8 тестов `services/planner-solver/tests/` падают на DEV (281 проходят), регресса
солвера не найдено. Корень — шаг `sets_contracts` (`tools/scout/refresh_daily.sh:366` →
`tools/scout/sets_incremental.py:enforce_contracts`) с 05.09 ни разу не применён: предохранитель `heal_policy.run_allowed`
(`sets_incremental.py:888`) каждый день отказывает («затронуло бы 112–126 из 126, предел 25 %»; `tools/scout/refresh.log` — 46 раз),
а шаг при этом пишет `ok` (`refresh-status.json`: `sets_contracts ok`) — `return` без кода ошибки (`sets_incremental.py:893`).
Совпадает с cc3525af (03.09, Р1 `footprint_known`); `completed_plans/stock-and-dims-honesty.md:153–155` предупреждал о
предохранителе и предлагал «новый банк рядом» — не сделано. Книга о продукте §5.1 п.5 («контракты… применяются») сегодня неверна.

## Что сломано (по отчёту, сверено ведущим: счётчик refresh.log, `sets_incremental.py:868–898`, статус шага)
| Тест | Причина | Класс |
|---|---|---|
| `test_bank_coverage::…second_armchair_alternative` | 4 large-сета без кресла 2 и без `coverage_gap` (инцидент 29.08, урок 323; heal :632–634 снимает без gap) | данные + дыра heal |
| `test_bank_coverage::…second_pod_pair_is_one_sku` | 27 сетов: кресло 2 ≠ экземпляр основного (heal/refresh меняют основное, синхронизация только в contracts) | данные + дыра конвейера |
| `test_contour_features::test_dining_share_watchdog` | `TypeError` на `templates=None` (:184); доля 201/252 < 220 | дефект теста + не установлено |
| `test_pose_contract::test_pose_hash_round_trip` | `~/scout-scenes/plans-export/` от 26.08 не обновляется кроном | устаревшие данные |
| `test_seating_selection::…210_sofa_2armchairs` | сет 105 без кресла 2 с 29.08 | данные |
| `test_sofa_mirror::…pick_beats_first_clean` | берёт живой `sets3[20]`, диван сменил refresh 28.09 (на бэкапах 20.08–01.09 проходит) | тест на живых данных |
| `test_template_integrity::test_no_phantom_dimensions` | сверяет старые артефакты упавших сцен (диван «Кинг Твин» без глубины, поставлен refresh 12.10) | дефект теста + данные |
| `test_svod13_q1_q3::…full_chain_cap` (мигает) | TIMEOUT `set86-long` > 900 с почти каждую ночь с 05.09 | не установлено |
В CI все пропускаются: `.gitignore:34` `tools/scout/*` — данных нет (с ce02a9a7, 28.08).

## Скоуп — что входит (по шагам; каждый — отдельная задача рабочему с отчётом)
1. **Честный статус (малый, первым).** Отказ предохранителя → шаг `sets_contracts` = `warn` с причиной в
   `refresh-status.json` и в Telegram тем же путём, что другие `warn`; `except Exception` вокруг `heal_policy`
   (:889) — не глотать (ImportError = `fail`). Тот же разбор для молчаливого `except` у проверки каталога (:221–222).
2. **Синхронизация пары и `coverage_gap` — отдельным шагом** после `heal` и после еженедельного `--refresh`
   (сейчас живёт только внутри contracts :845–865). Ветка heal «снять кресло 2» пишет `coverage_gap`, как ветка pod
   (:607–612). `--refresh` пишет в `set_changes`. Через тот же предохранитель и журнал (27 сетов < 25 %).
3. **Разбивка «112–126 из 126»** (сухой прогон, бесплатно): по каждому сету — какой контракт нарушен (Р1 неизвестная
   глубина/ширина в напольном слоте, ковёр, конверт дивана…). Итог — таблица «причина → сетов». Без неё п.4 не решается.
4. **Миграция банка под Р1** по итогу п.3: «новый банк рядом» → полный экзамен → сравнение демо-вариантов до/после →
   ⚑ владелец смотрит демо → подмена. Либо, если причина одна и узкая, — точечная правка правила/данных. Решение — после п.3,
   с Codex.
5. **Тесты.** `test_dining_share_watchdog`: `(r.get('templates') or '')`, упавшие сцены — отдельный счётчик. `test_pose_hash`:
   пропуск с понятным текстом, если `plans-export` старше отчёта экзамена (или экспорт — в ночной экзамен).
   `test_no_phantom_dimensions`: только сцены `ok` сегодняшнего отчёта, сверка `_set_hash`. `test_sofa_mirror`,
   `test_seating_selection`: живой банк → предметы, зафиксированные в самом тесте (как `_items()` там же) — пойдут в CI.
   CI печатает «пропущено N тестов без данных DEV». Полный pytest planner — после ночного экзамена, итог — `warn`.
6. **`set86-long` TIMEOUT** — замер одной сцены после п.4 (на старом и новом банке), затем решить: лимит или солвер.

## Скоуп — что НЕ входит
- Правила подбора и пороги (они верны; чиним то, что их не применяет). Платное (обогащение, меши). Изменение витрины демо до ⚑.

## Файлы к изменению (предварительно)
- [ ] `tools/scout/sets_incremental.py` — статус отказа, шаг синхронизации пары, gap в heal, журнал refresh
- [ ] `tools/scout/refresh_daily.sh` — новый шаг после heal/refresh, статус `warn`
- [ ] `tools/scout/heal_policy.py` — если статусу нужна причина
- [ ] `services/planner-solver/tests/test_{contour_features,pose_contract,template_integrity,sofa_mirror,seating_selection}.py`
- [ ] `.github/workflows/*` — счётчик пропущенных
- [ ] `guides/product-book.md` §5.1 п.5 — абзац «Сегодня»; `core/catalog.md` / `core/pipeline-order.md`

## Критерии приёмки
- [ ] Ночь после п.1: при отказе предохранителя `refresh-status.json` показывает `sets_contracts warn` + причину, пришёл Telegram
- [ ] После п.2: `test_second_pod_pair_is_one_sku_from_25m2` и `…second_armchair_alternative` зелёные на DEV без ручных правок банка
- [ ] После п.5: `test_sofa_mirror`, `test_seating_selection` идут в CI (не skip); на DEV падений с `TypeError` и по старым артефактам нет
- [ ] После п.4: `enforce_contracts` применяется ночью (в refresh.log «sets3.json обновлён» или «заменено 0»), демо-варианты не хуже (⚑)
- [ ] `pnpm test`, pytest planner на DEV, lint зелёные

## Риски
- п.4 меняет состав демо для партнёра — только через «новый банк рядом» и ⚑ владельца. п.2 трогает 27 сетов — бэкап `.bak` и журнал.

## Definition of Done — память (без этого `completed` запрещён)
- [ ] `core/catalog.md`, `core/pipeline-order.md`, книга §5.1 п.5 «Сегодня»; ADR по решению п.4; урок «шаг пишет ok при отказе»
- [ ] `/memory-check` выполнен, audit «чисто»

## Лог выполнения
- 2026-10-20 — план создан (draft) по разбору T-20261020-04; ведущий сверил счётчик отказов (46), код :868–898, статус `ok`.
- 2026-10-20 — критика Codex не получена: подписка ChatGPT отказывает во всех моделях (scratch 20.10); п.3 (разбивка причин) закрывает главный вопрос к советнику фактами до п.4.
- 2026-10-20 — владелец: «деплой» → in_progress; п.1+п.3 — T-20261020-05 (рабочий 1). Добавка владельца к п.2: пара кресел — всегда одна модель.
- 2026-10-20 — T-05 (рабочий 1): п.1 — отказ предохранителя contracts = `WARN:contracts_fuse` (статус warn, дайджест), без heal_policy — FAIL, сбой каталога в `_slot_ok` — отклонение + `WARN:slot_gate_catalog`, тест `tools/scout/tests/test_contracts_fuse.py`; п.3 — 107/126 сетов, 192 из 239 слотов «каталог gone» (divan.ru archived при живой странице — 61 сет; tvoydom мёртвые/нет в наличии), Р1 — 13 сетов, мёртвые фото — 33.
- 2026-10-20 — T-07 (рабочий 1): п.2 — шаг `sets_pairs` (`--sync-pairs`, после heal и еженедельного refresh; `sync_pairs` общая с contracts), журнал pair_sync/refresh_upgrade, gap при снятии кресла 2; на копии банка 27/126 сетов (21 % < 25 %) → `…pod_pair_is_one_sku` зелёный, `…second_armchair` — 4 сета (83/100/118/119: «кресло» = банкетка/кресло-кровать) ждут п.4; п.1 — heal/pairs/stock_check/ворота (`WARN:slot_gate`)/catalog_media rc — видимы.

## Completion summary

### Уроки

## Follow-up work
- [ ] Читает ли кто-то `alert.sh` (рабочий не проверял) — сверить в п.1.

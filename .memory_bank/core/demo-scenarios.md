---
tier: 1
topic: demo-scenarios
scope: Сценарии демо /demo — карта кнопок «ожидание → факт», живые проверки, дефекты прогона и планы demo-01…03
tier2: "../domain/demo-scenario-map.md"
updated: 2026-10-17
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-16
review_after: 2026-11-28
---

# Сценарии демо — Tier 1 сводка

**Что это:** карта всех кнопок и путей покупателя на `/demo` с колонкой «факт» (Tier 2). Страница —
`tools/scout/flat215-demo/index.html`.

**Путь покупателя (16.10, окно v3):** карточка стиля → окно варианта `#shot` с вкладками Фото · 3D · План («‹ ›» ракурсы,
список «Заменить / В магазин», ♡ / Ссылка / Сохранить; в «План» — «Изменить план», старая `#shEdit` скрыта) → лента замен
`#sheet` → конструктор `#cons` (долгое нажатие 450 мс — перетаскивание; тап показывает стрелки ±90°, угловая ручка — шаг 5°)
→ «Посмотреть фото с изменениями» (серверный кадр, страница обещает «20–25 секунд», тесты ждут до 60 с) → «Улучшить фото» (платно).

**Живые проверки (`demo-03`):** номер строки карты — в начале названия теста `e2e/live/*.live.ts` (`demo-scenarios.live.ts` —
кнопки, `demo-frame.live.ts` — кадр обоих ракурсов и картинка коллекции), ночной шаг `demo_live` (`tools/ops/demo-live.sh`);
строка без теста — `WARN:demo_map_uncovered` (`tools/ops/demo-map-check.mjs`). Платный путь — без трат (`/api/draft/paid`).

**Починено 14.10** (список — Tier 2 § 1–2): `camFit` (тест `tests/unit/demo-cams.test.ts`), `totalsOf` (ADR-0286), задания
кадров переживают деплой (`tools/scout/draft_jobs.py`, ADR-0287), картинка коллекции (`PATCH /api/collections/[id]`).
**Открыто:** фото ≠ список (2.2), 3D без несохранённых правок (2.16) → `demo-02`. **/flat** 2.18–2.22 приняты вручную 16.10;
`e2e/live/flat-walk.live.ts` покрывает только «1д», строки 2.19–2.22 без теста (`demo_map_uncovered`, долг demo-03).
2.23 — строки-входы шторки v5 (`e2e/live/floor.live.ts`); 2.24–2.26 — режимы окна demo-09 (`e2e/live/demo-scenarios.live.ts`).

**Куда идёт:** этап 4+ `plans/MASTER-cost-first.md` — `demo-01` (движок `lib/viewer3d`) завершён 14.10; `demo-03` — `partial`
(ждёт три зелёные ночи); `demo-02` (окно v3 + шторка v4, ADR-0290/0299) — `in_progress`, принято по частям 16.10; дальше
`demo-04…08` (вид сцены, артефакты 3D, пол, стены, досье). Связано: [[demo-planner]], [[apartment-configurator]].

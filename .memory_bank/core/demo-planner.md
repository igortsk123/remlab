---
tier: 1
topic: demo-planner
scope: Демо-планировщик для партнёра — расстановка и кадр
tier2: "../domain/demo-planner-ui.md"
updated: 2026-10-28
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-18
review_after: 2026-12-05
---

# Демо-планировщик — Tier 1 сводка

**Что это:** демо `/demo` (ADR-0201). Квартира №215, 73,7 м².
Витрина: сертификат → стили → комнаты → окно варианта; план — в конструкторе.
Код: `tools/scout/flat215-demo/index.html`, сборка `flat215_demo.py`, публикация `publish_demo.sh`.

- **Главная «стили → комнаты» (ADR-0307):** `index.html:#styleTabs` → комнаты `#hmRooms` из реестра
  (`contracts/partner.ts:apartmentRoom`); избранное — `#screen-fav`, корзина — `lib/basket/basket.ts`.
- **Окно варианта (demo-09/02):** «Фото» — только реалистичный снимок этой расстановки, иначе 3D с ценниками;
  изменение → 3D (`index.html:vwRealShots/vwAfterChange`, ADR-0300).
- **Состав (20.10):** банкетка «уголком» — при ≥ `nook_min_benches` в ленте стиля (`tools/scout/flat215_demo.py:drop_lonely_nook`);
  обеденный стол — `tools/scout/unfit.py:unfit` (h 65–90, d ≥ 50). Карта 2.47–2.48.
- **EN-демо = британский двойник** `demo-uk-215` (£ по курсу, ADR-0298); пересчёт — одна функция `toCard()` (через неё `money()`).
- **Замена мебели (ADR-0203/0245/0271/0277):** пул `tools/scout/demo_swap_pool.py`, правила `tools/scout/rules/demo-swap.json`;
  проверка `tests_chain.py:live_swap_feeds`. Правила ленты — Tier 2.
- **Ключ модели — `msid`** (ADR-0204, GLB по представителю семейства); вариант — `/demo/#v=<id>` (ADR-0205).
- **Коллекции покупателя (ADR-0264/0306):** ♡ → снимок на сервере (`app/api/collections/route.ts`), ссылка `/demo/#c=<id>`;
  цены — сервер из витрины (`lib/collections/prices.ts`).
- **Декор, управление, наличие** (ADR-0206/0140/0144) — Tier 2. Шапка квартиры — [[partners]].
- **Русский = протокол логики:** данные не переводить, только показ.

**Вариант = стиль (13.10, ADR-0244):** `pick_banks` — по набору на стиль (самый собираемый);
кнопка «в 3D» → `/flat?demo=<вариант>&flat=…`, у коллекции — `/flat?coll=<id>`; встраивание на сайт застройщика —
`/embed/<партнёр>/<квартира>` (ADR-0283).
- **Кадры (ADR-0280/0291/0304):** прогрев `tools/ops/demo-warm.mjs`; поза 135 см; пара точек `index.html:camPair`.
- **Сценарии, дефекты, живые проверки, планы demo-01…03** — [[demo-scenarios]].

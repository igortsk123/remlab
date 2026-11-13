---
tier: 1
topic: demo-planner
scope: Демо-планировщик для партнёра — расстановка и кадр
tier2: "../domain/demo-planner-ui.md"
updated: 2026-11-13
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-11-12
review_after: 2026-12-05
---

# Демо-планировщик — Tier 1 сводка

**Что это:** `/demo` (ADR-0201), квартира №215: комнаты → окно варианта.
Код: `tools/scout/flat215-demo/index.html`, сборка `flat215_demo.py`, публикация `publish_demo.sh` (копия, `--rollback`;
[[pipeline-order]]).

- **Главная (07.11, home-mix):** вкладок стилей нет; один выбор `index.html:mixWant` → комнаты `#hmRooms` из реестра
  (`contracts/partner.ts:apartmentRoom`); «Выбрано» — сумма комнат (`index.html:homeChosen`), избранное скрыто.
- **Окно варианта:** «Фото» — снимок расстановки, иначе 3D (`index.html:vwRealShots`, ADR-0300); после правки — `vwStalePick`.
- **Состав:** банкетка «уголком» — `tools/scout/flat215_demo.py:drop_lonely_nook`; обеденный стол — `tools/scout/unfit.py:unfit`.
- **EN-демо** = двойник `demo-uk-215` (£ через `toCard()`, ADR-0298) + временная маска товаров `demoMask` (`data/partners/demo-uk.json`, ADR-0328).
- **Замена мебели (ADR-0203/0245/0271/0277):** пул `tools/scout/demo_swap_pool.py`, правила `tools/scout/rules/demo-swap.json`;
  проверка `tests_chain.py:live_swap_feeds`.
- **Ключ модели — `msid`** (ADR-0204, GLB по представителю семейства); вариант — `/demo/#v=<id>` (ADR-0205).
- **Коллекции (ADR-0264/0306):** ♡ → снимок (`app/api/collections/route.ts`), `/demo/#c=<id>`; раздела «по ссылке» нет (П1.57).
- **Масштаб страницы на телефоне запрещён** — `lib/page/no-zoom.ts` (ADR-0409).
- **Декор, управление, наличие** (ADR-0206/0140/0144), подвесное, картины — Tier 2; шапка — [[partners]].
- **Русский = протокол:** данные не переводим.

**Вариант = стиль (ADR-0244):** `choose_banks`/`fill_banks` (ADR-0259) — по набору на стиль (самый собираемый);
встраивание — `/embed/<партнёр>/<квартира>` (ADR-0283).
- **Кадры (ADR-0280/0291/0304/0320/0329/0332):** прогрев `tools/ops/demo-warm.mjs`; одна расстановка и пара точек — `index.html:camPairAll`.
  Обложка `camPosterBad`; пара на все стили, `cams_own` — на стиль (`tools/flat3d/demo-cams.mjs`); `camPairV2` — Tier 2 § «Ракурсы v3».
- **22–24.10 (ADR-0319…0326) и 12.11:** мягкое — без 3D; цвета образцами; карточка выбранного (12.11 — вариант Б,
  `index.html:vwCardInfo`); свайп у края фото = ракурс — Tier 2 § «Демо 22–24.10».
- **Сценарии, дефекты, живые проверки** — [[demo-scenarios]].

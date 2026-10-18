---
tier: 1
topic: furniture
scope: Мебель — сеты, визуализация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-10-18
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-10-18
review_after: 2026-12-05
---

# Мебельный трек — Tier 1 сводка

**Статус:** разведка в `tools/scout/`; в app-слое — корзина сертификата `lib/basket/basket.ts` (demo-16), остальной прод-код мебели не начат (ADR-0042).

- **Каталог**: 20 588 тов. (03.09), 6 магазинов, dev-БД `remlab-devdb`; фото у 100% офферов;
  cron 10:40 UTC `refresh_daily.sh`. Состав/дыры — [[catalog]] (`../core/catalog.md`).
- **Сеты**: v2 «как дизайнер» (ADR-0044/0046); «сперва допустимость, потом красота» (ADR-0064..0066): пропорции и
  подтип жёстко фильтруют до скоринга (`proportions.json`, `item_function.py`), ковёр по двум схемам или его нет.
- **Стили** (ADR-0047/0048): 6 паспортов + стиль-скор → `sets3.json` (126 сетов); судья, замены. `../domain/interior-styles.md`.
- **Состав от посадочных групп (ADR-0074)**: группа по площади диктует состав; столик 55–75% дивана; обеденная — при
  свободном регионе по числу мест 2 → 3 м², 4 → 6 м², 6 → 8 м² (`services/planner-solver/rules/zones.json:dining_region_m2`); поле `group` в сете.
- **Расстановка**: дефолт **zoned** (ADR-0075, приёмка 239 vs 119 из 252) — см. [[layout]].
- **Визуализация — двухпроходная (28.08, ADR-0128..0130):** проход А — сценовый z-buffer
  рендер 3D-моделей товаров (`scene_mesh.py`; приёмка `mesh_gate`, фронт — `mesh_front`+`orient_selftest`, VLM-фоллбэк qwen3-vl — Tier 2 §Роли); проход Б — «только улучшить» (с 17.10 gpt-image-2.5-sunburst medium — `tools/scout/systemd/remlab-render.service`; промпт improve-v3 по умолчанию, в сервисе v4 по `IMPROVE_PROMPT=v4` — ADR-0302/0305, Tier 2). Ремонт по кропам
  (ADR-0127) — страховка. Демо — [[demo-planner]] (спрайты моделей сверху на канвасе).
- **Ветка B** (ADR-0061..0063, `viz_build.py`): вставка → приёмка числами → 3D непрошедшим (`archive/plans/viz-regional-masks.md`).
- **Меши (ADR-0131/0132):** только свой Hunyuan3D 2.1 на Salad — [[mesh-pipeline]]. **А4/А6:** `viz_qa.py` гейтит батчи; 3 ретрая; A/B `viz_ab.py`.

**Реалистичное фото (17.10):** бенч 7 моделей через шлюз (flare — лучшее цена/время, 25 с, $0.05); выбор владельца — sunburst medium (ADR-0302; Tier 2 § «Бенч 17.10»).
**Tier 2:** `../domain/viz-fidelity-playbook.md` · `../domain/lr-composition-guide.md` · `../domain/integrations.md`.

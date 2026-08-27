---
tier: 1
topic: furniture
scope: Мебель — сеты, визуализация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-08-28
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-28
---

# Мебельный трек — Tier 1 сводка

**Статус:** разведка в `tools/scout/`, прод-код не начат (ADR-0042).

- **Каталог**: 25 034 тов., 5 магазинов с товарами, dev-БД `remlab-devdb`; фото у 100% офферов;
  cron 09:40 `refresh_daily.sh`. Состав/дыры — [[catalog]] (`../core/catalog.md`).
- **Сеты**: v2 «как дизайнер» (ADR-0044/0046). С 08-05 — «сперва допустимость, потом красота»
  (ADR-0064/0065/0066): пропорции и подтип ЖЁСТКО фильтруют до скоринга (`proportions.json`,
  `item_function.py`), ковёр по двум схемам или его нет. Замер 126 сетов: 0 нарушений
  (было 107+88). Планы [[sets-feasibility-first]], [[catalog-enrichment-pipeline]].
- **Стили** (ADR-0047/0048, [[sets-style-v3]]): 6 паспортов + стиль-скор → sets3.json
  (126 сетов); судья, замены. `../domain/interior-styles.md`.
- **Состав от посадочных групп (08.08, ADR-0074)**: группа по usable-площади диктует диван 2/
  кресла×N/пуф; столик 55–75% дивана при подборе; обеденная только при остатке ≥6 м²; extras_max;
  поле `group` в сете; судья ждёт пополнения OpenAI-кредитов (честная ошибка квоты в judge.py).
- **Расстановка**: дефолт **zoned** (ADR-0075, приёмка 239 vs 119 из 252) — см. [[layout]].
- **Визуализация — прод-путь демо (26–28.08, ADR-0125..0127):** трек А на gpt-image-2 через
  Vercel-шлюз (`draft_render.py`, сервис `remlab-draft`): clay+разметка+эталоны, вид = запрос,
  камеры по замеру; локальный ремонт по кропам. Точность мест — [[viz-regional-masks]]
  (двухпроходная схема). Демо — [[demo-planner]].
- **Ветка B** (ADR-0061..0063, `viz_build.py`): вставка → приёмка числами → 3D непрошедшим;
  теперь основа двухпроходной схемы Трека 2 [[viz-regional-masks]].
- **А4/А6 (06.08):** пост-QA финала `viz_qa.py` гейтит батчи; 3 ретрая; меш-фолбэк Hunyuan3D;
  A/B финала `viz_ab.py`.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · `../domain/lr-composition-guide.md` · `../domain/integrations.md`.

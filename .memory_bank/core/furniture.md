---
tier: 1
topic: furniture
scope: Мебель — каталог, сеты, визуализация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-08-05
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-02
---

# Мебельный трек — Tier 1 сводка

**Статус 2026-08-02:** разведка в `tools/scout/` (вне git); прод-код НЕ начат
(планы: [[gdeslon-catalog]] → [[ergonomics-planner]] → [[living-room-sets]], ADR-0042).

- **Каталог**: 87 635 тов., 7 магазинов, dev-БД `remlab-devdb`; размеры мебель 87–100%.
  Свежесть (ADR-0045): наличие ТОЛЬКО по карточкам (`available` в фидах пуст); цикл cron 09:40
  (`refresh_daily.sh`). Дыры: ковры/картины/шторы.
- **Сеты**: v2 «как дизайнер» (ADR-0044) + валидатор состава (ADR-0046). С 08-05 подбор —
  «сперва допустимость, потом красота» (ADR-0064/0065/0066): пропорции и функциональный подтип
  ЖЁСТКО фильтруют до скоринга (`proportions.json` 9 правил с источниками, `item_function.py`),
  ковёр по двум схемам или его нет. Замер 126 сетов: было 107 маленьких столиков и 88 крупных
  пуфов, стало 0 нарушений. Планы [[sets-feasibility-first]], [[catalog-enrichment-pipeline]].
- **Стили** (ADR-0047/0048, [[sets-style-v3]]): 6 паспортов + стиль-скор 0–10 → sets3.json
  (126 = 7 метражей × 6 стилей × 3 тира); судья, замены по порогу. `../domain/interior-styles.md`.
- **Расстановка**: Holodeck DFS-солвер (`solver_run.py`, venv `~/venvs/scout`): правила по 15
  ролям + hard-проверки (ТВ ≥180, столик 30–50, дверь). Плотные сеты 8/10, эскалация MILP позже.
- **Визуализация** (ADR-0043, [[viz-pipeline]]): `pipeline2.py`, любая комната/стиль; кадр ~$0.07.
  Детали и дыры: `../domain/viz-fidelity-playbook.md`. Далее: C (все сеты), D (прод).
- **Сборка кадра** (ADR-0061/0062/0063, `tools/scout/viz_build.py`): фото товара по умолчанию →
  приёмка числами (`collage_audit.py`, ворота перед оплатой) → 3D непрошедшим (`mesh_need/
  mesh_make/mesh_render`, Trellis ≈$0.02 и свой рендер без видеокарты) → приёмка снова.
  Подвесное и стоящее на мебели не моделим; модель проходит самопроверку по силуэту И цвету.
  База под вклейку — фотореалистичная пустая комната по нашим картам (`shell_make.py`), кэш по
  комнате. Полные карточки из фида — `feed_cards.py` (параметры, описание, оригинал фото 1080 px).
Ключи: fal (mltest), OpenAI (соседский), Gemini МЁРТВ.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · `../domain/lr-composition-guide.md` · `../domain/integrations.md`.

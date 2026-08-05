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

**Статус:** разведка в `tools/scout/`, прод-код не начат (ADR-0042).

- **Каталог**: 87 635 тов., 7 магазинов, dev-БД `remlab-devdb`; размеры мебель 87–100%; фото у
  100% офферов. Свежесть (ADR-0045): наличие только по карточкам, cron 09:40 `refresh_daily.sh`.
  Дыры: ковров для гостиной НЕТ вовсе (ADR-0066), картины/шторы.
- **Сеты**: v2 «как дизайнер» (ADR-0044) + валидатор состава (ADR-0046). С 08-05 подбор —
  «сперва допустимость, потом красота» (ADR-0064/0065/0066): пропорции и функциональный подтип
  ЖЁСТКО фильтруют до скоринга (`proportions.json` 9 правил с источниками, `item_function.py`),
  ковёр по двум схемам или его нет. Замер 126 сетов: было 107 маленьких столиков и 88 крупных
  пуфов, стало 0 нарушений. Планы [[sets-feasibility-first]], [[catalog-enrichment-pipeline]].
- **Стили** (ADR-0047/0048, [[sets-style-v3]]): 6 паспортов + стиль-скор 0–10 → sets3.json
  (126 сетов); судья, замены. `../domain/interior-styles.md`.
- **Расстановка**: Holodeck DFS-солвер (`solver_run.py`, venv `~/venvs/scout`): правила по 15
  ролям + hard-проверки (ТВ ≥180, столик 36–46, пуф за столиком, дверь), замер по настоящему следу.
- **Визуализация** (ADR-0043, [[viz-pipeline]]): `pipeline2.py`, любая комната/стиль; кадр ~$0.07.
  Детали и дыры: `../domain/viz-fidelity-playbook.md`. Далее: C (все сеты), D (прод).
- **Сборка кадра** (ADR-0061/0062/0063, `viz_build.py`): фото по умолчанию → приёмка числами
  (`collage_audit.py`, ворота перед оплатой) → 3D непрошедшим → приёмка снова. Подвесное и стоящее
  на мебели не моделим. Полные карточки фида — `feed_cards.py`.
Ключи: fal (mltest), OpenAI (соседский), Gemini МЁРТВ.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · `../domain/lr-composition-guide.md` · `../domain/integrations.md`.

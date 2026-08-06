---
tier: 1
topic: furniture
scope: Мебель — каталог, сеты, визуализация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-08-06
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-02
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
- **Расстановка**: два движка, дефолт всё ещё DFS — см. [[layout]] (`../core/layout.md`).
- **Визуализация** (ADR-0043, [[viz-pipeline]]): ветка A `pipeline2.py`; факт цены кадра
  $0.14–0.35 (2–5 вызовов), не $0.07.
- **Сборка кадра — ветка B** (ADR-0061/0062/0063, `viz_build.py`): фото по умолчанию → приёмка
  числами (`collage_audit.py`, ворота перед оплатой) → 3D непрошедшим → приёмка снова; финал —
  лист двух видов $0.128. Подвесное и стоящее на мебели не моделим.
Ключи: fal (mltest), OpenAI (соседский — из чужих `.env`, хрупко), Gemini МЁРТВ.
- **Волны А4/А6 (06.08, [[MASTER-pipeline-hardening]]):** пост-QA финала `viz_qa.py`
  (ΔRGB+VLM, вшит в `run_pair`, гейтит батчи — уже ловит реальный брак); 3 ретрая
  edit/fal; shell-база дефолт; приёмка блокирует батч; меш-фолбэк Hunyuan3D
  (`mesh_make model=`); A/B финала — `viz_ab.py` (NB Pro на fal есть; первый замер:
  чуть лучше по цвету, состав врёт так же). Плейбук Tier 2 — ветка A (помечен).

**Tier 2:** `../domain/viz-fidelity-playbook.md` · `../domain/lr-composition-guide.md` · `../domain/integrations.md`.

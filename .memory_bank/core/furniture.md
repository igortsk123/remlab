---
tier: 1
topic: furniture
scope: Мебель — сеты, визуализация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-09-03
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-28
review_after: 2026-12-05
---

# Мебельный трек — Tier 1 сводка

**Статус:** разведка в `tools/scout/`, прод-код не начат (ADR-0042).

- **Каталог**: 32 347 тов. (БД 28.08), 5 магазинов, dev-БД `remlab-devdb`; фото у 100% офферов;
  cron 09:40 `refresh_daily.sh`. Состав/дыры — [[catalog]] (`../core/catalog.md`).
- **Сеты**: v2 «как дизайнер» (ADR-0044/0046). С 08-05 — «сперва допустимость, потом красота»
  (ADR-0064/0065/0066): пропорции и подтип ЖЁСТКО фильтруют до скоринга (`proportions.json`,
  `item_function.py`), ковёр по двум схемам или его нет. Замер 126 сетов: 0 нарушений
  (было 107+88); планы — в архиве.
- **Стили** (ADR-0047/0048, план sets-style-v3 (архив)): 6 паспортов + стиль-скор → sets3.json
  (126 сетов); судья, замены. `../domain/interior-styles.md`.
- **Состав от посадочных групп (08.08, ADR-0074)**: группа по площади диктует состав;
  столик 55–75% дивана; обеденная при остатке ≥6 м²; поле `group` в сете.
- **Расстановка**: дефолт **zoned** (ADR-0075, приёмка 239 vs 119 из 252) — см. [[layout]].
- **Визуализация — двухпроходная (28.08, ADR-0128..0130):** проход А — сценовый z-buffer
  рендер 3D-моделей товаров (`scene_mesh.py`; Trellis $0.02/SKU, приёмка `mesh_gate` профильным
  замером, брак→Hunyuan→замена товара; фронт — `mesh_front`+`orient_selftest`, VLM-фоллбэк
  qwen3-vl с признаковым промптом; скоуп ролей перед/зад ≈11.9k — Tier 2 §Роли); проход Б — gpt-image-2 «только улучшить». Ремонт по кропам
  (ADR-0127) — страховка. Демо — [[demo-planner]] (спрайты моделей сверху на канвасе).
- **Ветка B** (ADR-0061..0063, `viz_build.py`): вставка → приёмка числами → 3D непрошедшим;
  теперь основа двухпроходной схемы Трека 2 [[viz-regional-masks]].
- **Меши (ADR-0131/0132):** только свой Hunyuan3D 2.1 на Salad — [[mesh-pipeline]].
- **А4/А6 (06.08):** пост-QA финала `viz_qa.py` гейтит батчи; 3 ретрая; A/B `viz_ab.py`.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · `../domain/lr-composition-guide.md` · `../domain/integrations.md`.

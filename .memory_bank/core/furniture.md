---
tier: 1
topic: furniture
scope: Мебель — каталог, сеты, визуализация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-08-02
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
  Свежесть (ADR-0045): `available` в фидах НЕ проставляется → наличие ТОЛЬКО по карточкам;
  ежедневный цикл cron 09:40 (`refresh_daily.sh`: фиды→upsert+direct_url→health-карточки→
  автозамены sets2→пересчёт цен/размеров/тиров). Ссылки 7 выгрузок — `_secrets/ACCESS.md`.
  Дыры: ковры/картины/шторы — ждём cozyhome + большую тройку.
- **Сеты**: v1 заморожен (11 позиций мертвы — отчёт владельцу); v2 «как дизайнер» (ADR-0044) +
  валидатор состава по чек-листу гостиной и правила пригодности товаров (ADR-0046,
  `../domain/living-room-checklist.md`); декор-зелень/картины — НЕ товары (рисует нейронка).
  Планы [[sets-compose-v2]], [[catalog-freshness]].
- **Стили** (ADR-0047/0048, [[sets-style-v3]]): 6 паспортов + стиль-скор товаров 0–10 →
  sets3.json (126: 7 метражей × 6 стилей × 3 тира); судья со style_grade, замены по порогу;
  генерация = ремонт под стиль. Детали: `../domain/interior-styles.md`.
- **Расстановка**: Holodeck DFS-солвер живьём (`solver_run.py`, venv `~/venvs/scout`):
  правила-«пожелания» по 15 ролям + hard-проверки (ТВ напротив дивана ≥180, столик 30–50,
  дверь); комната из `m2` сета. Плотные сеты (10 напольных) — 8/10, эскалация MILP позже.
- **Визуализация** (ADR-0043, [[viz-pipeline]]): `pipeline2.py` сам, любая комната/стиль
  (нормализация мира по дивану, `_room` от солвера); кадр ~$0.07. Витрина-7 отдана владельцу.
  Детали и дыры: `../domain/viz-fidelity-playbook.md`. Далее: C (все сеты), D (прод).
Ключи: fal (mltest), OpenAI (соседский), Gemini МЁРТВ.

**Tier 2:** `../domain/viz-fidelity-playbook.md` · `../domain/lr-composition-guide.md` · `../domain/integrations.md`.

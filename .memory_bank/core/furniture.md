---
tier: 1
topic: furniture
scope: Мебельный трек — каталог Гдеслона, сеты, витринная визуализация
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-08-01
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-08-01
---

# Мебельный трек — Tier 1 сводка

**Статус 2026-08-01:** разведка в scratch-инструментах (`tools/scout/`, вне git); прод-код НЕ начат
(планы: [[gdeslon-catalog]] → [[ergonomics-planner]] → [[living-room-sets]], ADR-0042).

- **Каталог**: 87 635 товаров 7 магазинов в локальной БД `remlab-devdb` (docker, pg17);
  размеры Ш×Г×В: мебель 87–100%, скрейп tvoydom добил свет/декор до 76–99%.
  Дыры: ковры (~15), картины (0), шторы — ждём cozyhome/лемана + большую тройку (divan/askona/ormatek).
- **Сеты**: 21 (7 метражей × 3 тира) автосборкой по справке владельца (доли площади —
  `../domain/lr-composition-guide.md`) + цвета миниатюр локально (60-30-10). Мудборды —
  Excel у владельца, ждём утверждения.
- **Визуализация (согласован план A→B→C→D, «деплой» 2026-08-01):** 3-этапный конвейер
  «pinhole-проекция комнаты кодом → черновик из фото товаров (позиции/масштабы = наш код) →
  чистовой gpt-image-2 (~$0.07) → VLM-QA». Правила схожести (сватчи цвета ΔE 0.9, VLM-инварианты
  формы, назначение предметов) — `../domain/viz-fidelity-playbook.md`. Тюнинг-лист — в плане.
- Ключи: fal (`FAL_KEY` mltest), OpenAI (соседский, v0-health-card), Gemini — МЁРТВ (пересоздать).

**Tier 2:** `../domain/viz-fidelity-playbook.md` (схожесть, модели, цены) ·
`../domain/lr-composition-guide.md` (справка долей площади) · `../domain/integrations.md` (Гдеслон).

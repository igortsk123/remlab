---
tier: 1
topic: styles
scope: Стили — паспорта, скоринг, сеты
tier2: ../domain/interior-styles.md
updated: 2026-09-02
last_verified: 2026-09-05
importance: high
source: manual
status: working
review_after: 2026-12-05
---

# Стили интерьера — Tier 1

Канон: 6 стилей (сканди, современный, минимализм, лофт, неоклассика, джапанди) как
данные-паспорта `tools/scout/styles.json`: веса признаков (метод владельца «доля влияния») +
prompt-блок ремонта. Каждый товар гостиной имеет ВЕКТОР оценок 0–10 по всем стилям + флаг
`universal` (style-scores.json; LLM+правила+CLIP; новинки — дельтой в cron). Вклад товара в
стиль сета = вес роли × площадь (диван решает). Сборка: `compose2 --style [--bands all]` →
sets3.json; судья со style_grade, замены только ниже порога и по максимальному стиль-вектору
(ADR-0047/0048). Генерация: полный ремонт комнаты под стиль, товары с фото неизменны.

**Tier 2:** ../domain/interior-styles.md

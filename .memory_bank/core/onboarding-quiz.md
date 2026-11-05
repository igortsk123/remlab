---
tier: 1
topic: onboarding-quiz
scope: Опрос-знакомство на /demo — где показываем, правило подбора 3 стилей, события менеджеру и застройщику, матрица приёмки комнат
tier2: "../domain/onboarding-quiz.md"
updated: 2026-11-05
importance: med
source: manual
status: draft
source_of_truth: canonical
review_after: 2026-12-05
---

# Опрос-знакомство — Tier 1 (метаплан `onb-00-quiz-master`, ADR-0330)

Первый экран демо: приветствие → 3 вопроса (фото гостиной в 5 стилях · кто живёт · цвета) → итог «3 стиля с фото» → новая
главная. Код страницы пишет `onb-03`; ступень 0 (`onb-02`) — разбор, правило, тест. Детали — [[onboarding-quiz-details]].

**Где показываем**
- Только по флагу квартиры `apartments[].quiz.enabled`. По умолчанию он выключен, у двойника `demo-uk-215` — свой.
- Обход:
  - `?quiz=0` — так ходит вся автоматика;
  - `/embed`;
  - `#v=/#c=/#fav/#plan`, `?style=`;
  - отозванная `?s=`;
  - повторный заход.
- `?quiz=1` — показать (кроме `/embed`). По webdriver не обходим.

**Подбор**
- Правило — `tools/scout/rules/quiz.json`, функция `quizPick` (блок QUIZPICK в `tools/ops/quiz-colour-audit.mjs` → `index.html`).
- Выбранное на фото всегда в тройке, остальное — по палитре. «Кто живёт» на стиль не влияет.
- Стили — только `homeModel().styles`, сейчас 5.
- Эталоны — `tests/fixtures/quiz-golden.json`, тест — `tests/unit/quiz-pick.test.ts`.

**Цвета.** Аудит — `node tools/ops/quiz-colour-audit.mjs --data <demo-data.json> --items --dist`. Вопрос 3 весит в подборе, но
не перекрашивает: у стиля можно перекрасить 0–4 предмета.

**События**
- Менеджеру — `quiz_done` и `style_change`: поля из словарей, дубль отсекается за 30 минут, имени нет.
- Застройщику — счётчики `quiz_*`.
- Миграции нет.

**Приёмка комнат** — [[onb-acceptance-matrix]]. «Да» сейчас только у гостиной. Санузлы и прихожая — `onb-13`.

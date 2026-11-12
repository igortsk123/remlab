---
tier: 1
topic: onboarding-quiz
scope: Опрос-знакомство на /demo — где показываем, правило подбора 3 стилей, события менеджеру и застройщику, матрица приёмки комнат
tier2: "../domain/onboarding-quiz.md"
updated: 2026-11-12
importance: med
source: manual
status: draft
source_of_truth: canonical
last_verified: 2026-11-12
review_after: 2026-12-05
---

# Опрос-знакомство — Tier 1 (метаплан `onb-00-quiz-master`, ADR-0330)

Первый экран демо: приветствие → до 2 пар гостиной → кто живёт → до 2 пар спальни (`index.html:STEPS`; пары — `quiz.json:style_pairs`,
`quizPairs`, только с фото нейросети) → «Квартира готова» → главная из ответов (`mixFromPairs`). Вопрос цветов выключен (`quiz.json` `enabled:false`, `colOn`). С 07.11 — [[onboarding-quiz-details]] после главы 5.

**Где показываем.** Имя — `lib/quiz/name.ts` (поле менеджера выкл., `QUIZ_NAME_FIELD`).
- Флаг `apartments[].quiz.enabled` (`contracts/partner.ts:apartmentQuiz`, умолч. выкл.); вкл. у `flat215` и `demo-uk-215` (`tests/unit/partners.test.ts`).
- Порядок (`index.html:shouldOpen`): `?quiz=0` (автоматика), `/embed`, `/try` без `?quiz=1` → нет; перезагрузка посреди → с того
  же шага; `#v=/#c=/#fav/#plan`, коллекция, `?style=`/`?mix=`, отозванная `?s=` → нет; `?quiz=1` → да; флаг выкл. или повтор → нет.
  По webdriver не обходим.

**Подбор**
- Правило — `tools/scout/rules/quiz.json`, `quizPick` (блок QUIZPICK в `index.html`, одна копия).
- Выбранное на фото гостиной всегда в тройке (спальня — лишь в раскладку), остальное — по палитре. «Кто живёт» на стиль не влияет.
- Стили — только `homeModel().styles`.
- Эталоны — `tests/fixtures/quiz-golden.json`, тест — `tests/unit/quiz-pick.test.ts`.

**Цвета.** Аудит — `node tools/ops/quiz-colour-audit.mjs --data <demo-data.json> --items --dist`. Вес цвета 3 (`quiz.json:weights`), пока вопрос выключен — 0. Перекраска (не сделана) —
шаг `onb-03`, только предмет, чья модель есть в нужном цвете (сперва диван); у стиля таких 0–4.

**События** (страница шлёт, `index.html:finish` → `remlab:quiz`)
- Менеджеру по `?s=` — `quiz_done` (повтор ≥30 мин) и `style_change` (в сводку); без имени (`modules/sends/service.ts`).
- Застройщику (заход без `?s=`, не webdriver) — счётчики `quiz_*` (`contracts/analytics.ts`). Миграции нет.

**Приёмка комнат** — `domain/onboarding-quiz.md` § «Матрица приёмки всех комнат». Готова (`contentState: ready`) только гостиная; кухня — лишь опциями застройщика у `demo-uk-1`. Прихожая —
`onb-13`, по образцу спальни после её приёмки; санузлы — «скоро».

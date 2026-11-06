---
tier: 1
topic: onboarding-quiz
scope: Опрос-знакомство на /demo — где показываем, правило подбора 3 стилей, события менеджеру и застройщику, матрица приёмки комнат
tier2: "../domain/onboarding-quiz.md"
updated: 2026-11-06
importance: med
source: manual
status: draft
source_of_truth: canonical
last_verified: 2026-11-05
review_after: 2026-12-05
---

# Опрос-знакомство — Tier 1 (метаплан `onb-00-quiz-master`, ADR-0330)

Первый экран демо: приветствие → 3 вопроса (фото гостиной в 5 стилях · кто живёт · цвета) → итог «3 стиля с фото» → новая
главная. Код страницы пишет `onb-03`; ступень 0 (`onb-02`) — разбор, правило, тест. Детали — [[onboarding-quiz-details]].

**Где показываем — ЗАПЛАНИРОВАНО (план `onb-03`): кода опроса на странице ещё нет, правила ниже — замысел.** Уже в коде (выключено):
флаги `contracts/partner.ts:apartmentQuiz`, имя `lib/quiz/name.ts` + поле `components/manager/SendRow.tsx` (`QUIZ_NAME_FIELD = false`).
- Только по флагу квартиры `apartments[].quiz.enabled`. По умолчанию он выключен, у двойника `demo-uk-215` — свой.
- Обход:
  - `?quiz=0` — так ходит вся автоматика;
  - `/embed`;
  - `#v=/#c=/#fav/#plan`, `?style=`;
  - отозванная `?s=`;
  - повторный заход.
- `?quiz=1` — показать (кроме `/embed`). По webdriver не обходим.

**Подбор**
- Правило — `tools/scout/rules/quiz.json`, функция `quizPick` (блок QUIZPICK в `tools/ops/quiz-colour-audit.mjs`; в `index.html` переносится в `onb-03`).
- Выбранное на фото всегда в тройке, остальное — по палитре. «Кто живёт» на стиль не влияет.
- Стили — только `homeModel().styles`, сейчас 5.
- Эталоны — `tests/fixtures/quiz-golden.json`, тест — `tests/unit/quiz-pick.test.ts`.

**Цвета.** Аудит — `node tools/ops/quiz-colour-audit.mjs --data <demo-data.json> --items --dist`. Вопрос 3 весит в подборе. Перекраска —
отдельный шаг `onb-03`, только у предмета, чья модель есть в цвете нужного семейства (сперва диван); у стиля таких 0–4 (аудит `onb-02`).

**События (план `onb-03`; сейчас в `contracts/send.ts` их нет)**
- Менеджеру — `quiz_done` и `style_change`: поля из словарей, дубль отсекается за 30 минут, имени нет.
- Застройщику — счётчики `quiz_*` (и `quiz_kids:*`).
- Миграции нет.

**Приёмка комнат** — `domain/onboarding-quiz.md` § «Матрица приёмки всех комнат». Готова только гостиная; кухня есть лишь опциями застройщика в `/flat` у `demo-uk-1`. Прихожая —
`onb-13`, открывать по образцу спальни после её приёмки; санузлы — «скоро», не в этом треке.

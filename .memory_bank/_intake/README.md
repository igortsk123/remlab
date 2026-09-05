# _intake — входная папка (сырьё, не хранилище)

> Здесь живёт только то, что ещё предстоит свести в канон банка: `brief/` и `history/` (вход для
> `/memory-init`), `session-scratch.md` (блокнот захвата на ходу), `codex/` (вопросы и ответы
> советника Codex — провенанс для ADR/планов), `owner/` (сырьё владельца: разметки, вердикты,
> выгрузки). **Правила:** (1) логи прогонов — НЕ в банк (складывать в `~/scout-logs/`);
> (2) basename intake-файлов не переименовывать — на них ссылаются ADR и планы по имени;
> (3) сведённое — остаётся как провенанс, но факты живут в `core/`, `domain/`, `decisions/`;
> (4) папка вне аудита кита (`tools/memory-audit.mjs`) — «чисто» её не проверяет; этот индекс
> регенерирует `node tools/intake-index.mjs` (проектный аудит проверяет, что canonical-доки
> не ссылаются сюда как на истину).

Обновлено: 2026-09-05. Файлов в git: 164 — кит (вход): 5 · не сведён: 72 · сведён/цитируется: 77 · сырьё владельца: 10.
«Сведён/цитируется» = имя файла встречается в банке/docs/правилах (где — в колонке).

| Файл | В git с | О чём | Ссылок | Где цитируется | Статус |
|------|---------|-------|-------:|----------------|--------|
| `brief/README.md` | 2026-07-01 | _intake/brief — цель и описание проекта | 156 | .memory_bank/INDEX.md, .memory_bank/METADATA_SCHEMA.md, .memory_bank/README.md | кит (вход) |
| `brief/_project-type.txt` | 2026-07-01 | dev | 2 | .claude/skills/memory-init/SKILL.md, tools/memory-audit.mjs | кит (вход) |
| `history/README.md` | 2026-07-01 | _intake/history — история проекта | 156 | .memory_bank/INDEX.md, .memory_bank/METADATA_SCHEMA.md, .memory_bank/README.md | кит (вход) |
| `brief/_memory-canon.txt` | 2026-07-09 | /home/pakar/igor/remlab/.memory_bank | 1 | .memory_bank/anti-patterns.md | кит (вход) |
| `session-scratch.md` | 2026-07-12 | Session scratch — блокнот захвата на ходу (append-only) | 34 | .memory_bank/README.md, .memory_bank/archive/plans/MASTER-layout-v5.md, .memory_bank/changelog/project-history.md | кит (вход) |
| `codex/answer-dresser-living.md` |  | Вердикт: вариант (в) — оставить, но не как универсальный «комод», а как функциональный `li | 0 |  | не сведён |
| `codex/answers-to-referee-4q.md` |  | Ответы на 4 уточняющих вопроса рефери (свод №9, поправки; remlab 14.08) | 0 |  | не сведён |
| `codex/answers-to-referee-q37-45.md` |  | Ответы агента на Q37–Q45 свода №10 (remlab, 15.08) | 0 |  | не сведён |
| `codex/catalog-onboard.md` |  | You are being onboarded as the PERSISTENT adviser for the CATALOG/PIPELINE domain of proje | 0 |  | не сведён |
| `codex/codex-catalog-load-plan-prompt.md` |  | Запрос критики плана `catalog-load-hardening` (03.09.2026) | 0 |  | не сведён |
| `codex/codex-catalog-onboard-answer.md` |  | Сейчас `bash refresh_daily.sh --force` запускать нельзя: второй пробный прогон в 16:44 обн | 0 |  | не сведён |
| `codex/codex-color-prompt.md` |  | Цвет мешей Hunyuan3D 2.1: разбор гипотез перед платным прогоном | 0 |  | не сведён |
| `codex/codex-demand-answer.md` |  | Вывод: расширить `mesh_demand` до 12 092 — правильно. Но класть туда `glb_path/glb_url/mes | 0 |  | не сведён |
| `codex/codex-demand-prompt.md` |  | Владелец 01.09 решил: свет (люстры 2439, бра 977) и вазы ВХОДЯТ в сеты, меши им нужны → | 0 |  | не сведён |
| `codex/codex-idle-answer.md` |  | Диагноз верный. Пачка 5 при 10 репликах экономически не может дать нужную цену: даже во вр | 0 |  | не сведён |
| `codex/codex-idle-prompt.md` |  | Пилот мешей (Hunyuan3D на Salad, 10 реплик batch-тарифа). Владелец требует сократить цену  | 0 |  | не сведён |
| `codex/codex-inpaint.md` |  | Ты независимый старший инженер-рецензент. Разбери сам, не считая нашу реализацию верной. Р | 0 |  | не сведён |
| `codex/codex-mnogomebeli-answer.md` |  | Вывод: обрезку Mnogomebeli надо отменить. Но план смешивает две разные ссылки: адрес карто | 0 |  | не сведён |
| `codex/codex-mnogomebeli-prompt.md` |  | Вопрос: отменяем обрезку ссылок mnogomebeli (наличие + реф-ссылки) | 0 |  | не сведён |
| `codex/codex-node-breaker-prompt.md` |  | Ты — независимый senior-ревьюер. Разбери задачу сам, по коду репозитория. Не считай ничьи | 0 |  | не сведён |
| `codex/codex-overlap-prompt.md` |  | Контекст с прошлого раза: демо flat215 — кнопка теперь отдаёт серверный кадр 3D-сцены | 0 |  | не сведён |
| `codex/codex-q3-design.md` |  | Подготовка Q3 правильная: формы в конце сохраняют greedy, а media-квота гарантирует достиж | 0 |  | не сведён |
| `codex/codex-quality-answer.md` |  | Вывод: я бы не включал глобально `octree=512` и тем более `paint=1024`. Для оставшегося пи | 0 |  | не сведён |
| `codex/codex-quality-prompt.md` |  | Пилот мешей идёт (Hunyuan3D 2.1 на Salad, ~170 моделей). Владелец: «можем заставить модель | 0 |  | не сведён |
| `codex/codex-queue-priority-answer.md` |  | 1. Выводы | 0 |  | не сведён |
| `codex/codex-queue-priority-prompt.md` |  | Ты — независимый senior-ревьюер. Разбери задачу сам, по коду репозитория. Не считай ничьи | 0 |  | не сведён |
| `codex/codex-stock-honesty-prompt.md` |  | Критика плана `stock-and-dims-honesty` (03.09.2026) | 0 |  | не сведён |
| `codex/prompt-audit-julia.md` |  | Контекст: владелец получил аудит галереи канонов /test/canons/ (64 карточки, tools/scout/c | 0 |  | не сведён |
| `codex/prompt-cascade-wiring.md` |  | Продолжение аудита Юли (ADR-0115/0116). Владелец подтвердил: каноны должны УЧИТЫВАТЬСЯ при | 0 |  | не сведён |
| `codex/prompt-doctrine-0117.md` |  | Владелец сформулировал ДОКТРИНУ чтения канонов (ADR-0117) и просит твою независимую оценку | 0 |  | не сведён |
| `codex/prompt-dresser-living.md` |  | Владелец спрашивает принципиально: «комоды в гостиной вообще ставят?» — стоит ли роли «ком | 0 |  | не сведён |
| `codex/prompt-dresser-rule.md` |  | Новое правило владельца (21.08, проверить и внедрить): «Комод не должен быть на взгляде от | 0 |  | не сведён |
| `codex/prompt-rug-audit.md` |  | Владелец на галерее планов заметил ковёр 80×50 («такого канона нет») и велел: полный аудит | 0 |  | не сведён |
| `codex/q-cull-rule-dynamic.answer.md` |  | 1. Вывод | 0 |  | не сведён |
| `codex/q-cull-rule-dynamic.md` |  | Вопрос: динамическое правило снятия медленных нод (скачивание образа) | 0 |  | не сведён |
| `codex/q-shot-modal-actions.answer.md` |  | Выбор закреплённой панели верный, но текущая реализация имеет два серьёзных дефекта: кнопк | 0 |  | не сведён |
| `codex/q-shot-modal-actions.md` |  | Вопрос: компоновка действий в модалке просмотра кадра (демо flat215, один статический html | 0 |  | не сведён |
| `codex/q11-canon-library.answer.md` |  | Главная поправка: не заводить `corner`, `window` и `bay` как равноправные функциональные з | 0 |  | не сведён |
| `codex/q11-canon-library.md` |  | Продолжаем (layout-сессия). Владелец: «завёл ли ты соответствующие каноны? у нас вроде не  | 0 |  | не сведён |
| `codex/q12-route-vs-coverage.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q12-route-vs-coverage.md` |  | Вопрос ПОРЯДКА ЯРУСОВ ключа выбора плана (владелец: «ошибка в планах — исключение, поправь | 0 |  | не сведён |
| `codex/q12-tandem-square-norms.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q12-tandem-square-norms.md` |  | Вопрос НОРМЫ (нужны источники). Две наши схемы посадки не имеют обоснования в паспорте — т | 0 |  | не сведён |
| `codex/q13-rug-fill-sofa.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q13-rug-fill-sofa.md` |  | Три СИСТЕМНЫХ дефекта галереи планов (замечания владельца 22.08). Нужен корень и правка в  | 0 |  | не сведён |
| `codex/q14-bank-img-drift.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q14-bank-img-drift.md` |  | Ты — независимый senior-ревьюер. Не предполагай, что гипотеза другого агента верна. | 0 |  | не сведён |
| `codex/q14-interactive-planner.md` |  | КРИТИКА МЕТАПЛАНА до показа владельцу (правило проекта: новый метаплан — сперва на разбор) | 0 |  | не сведён |
| `codex/q15-anchors.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q15-anchors.md` |  | Ты — независимый senior-ревьюер. Не считай гипотезу другого агента верной. | 0 |  | не сведён |
| `codex/q16-depth.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q16-depth.md` |  | Ты — независимый senior-ревьюер. Не считай гипотезу другого агента верной. | 0 |  | не сведён |
| `codex/q17-dims.answer.md` |  | 1. Вывод | 0 |  | не сведён |
| `codex/q17-dims.md` |  | Ты — независимый старший инженер-ревьюер. Разбери задачу сам, не подстраиваясь под чужую г | 0 |  | не сведён |
| `codex/q18-marks.answer.md` |  | 1. Вывод | 0 |  | не сведён |
| `codex/q18-marks.md` |  | Ты — независимый старший инженер-ревьюер. Разбери задачу сам, не подстраиваясь под чужую г | 0 |  | не сведён |
| `codex/q19-plan.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q19-plan.md` |  | Ты — независимый старший инженер-ревьюер. Раскритикуй план ДО того, как я покажу его владе | 0 |  | не сведён |
| `codex/q20-plan-recheck.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q20-plan-recheck.md` |  | Ты — независимый старший инженер-ревьюер. Это ПОВТОРНАЯ проверка уже переработанного плана | 0 |  | не сведён |
| `codex/q21-gpt-advice.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q21-gpt-advice.md` |  | Ты — независимый старший инженер-ревьюер. Разбери ВНЕШНИЙ совет (от GPT, передан владельце | 0 |  | не сведён |
| `codex/q22-orient.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q23-canonical.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q26-repair-stage.answer.md` |  | Вывод | 0 |  | не сведён |
| `codex/q26-repair-stage.md` |  | Где чинить дефекты мешей: до генерации, параметрами, постпроцессом или перегоном | 0 |  | не сведён |
| `codex/q27-eligibility.answer.md` |  | Сейчас | 0 |  | не сведён |
| `codex/q27-eligibility.md` |  | Канон mesh-eligible ролей и плиты у диванов | 0 |  | не сведён |
| `codex/q28-floor-prior.answer.md` |  | Вывод: входом этот прайор, скорее всего, полностью не убрать. Сегодня лучший ход — дешёвый | 0 |  | не сведён |
| `codex/q28-floor-prior.md` |  | Плита-«пол» под мебелью: прайор генератора. Как давить на входе? | 0 |  | не сведён |
| `codex/q5_degradation_patch.py` |  | --- template.py: пометки допусков в tpl_variant (+table_axis_shifted, +gapNN), enumeration | 0 |  | не сведён |
| `codex/q5_pod_patch.py` |  | Q5 pod (Codex): quiet_chat = пара + ОБЯЗАТЕЛЬНАЯ поверхность, 30–45° к центру; fireplace_f | 0 |  | не сведён |
| `codex/q9-zone-priors.answer2.md` |  | Вывод | 0 |  | не сведён |
| `codex/q9_wiring_patch.py` |  | «практика vs движок»; на выбор плана не влияет до включения после слепых пар | 0 |  | не сведён |
| `codex/report-to-referee-svod10-done.md` |  | Отчёт советнику: свод №10 (аудит V4) внедрён полностью (remlab, 15.08) | 0 |  | не сведён |
| `codex/report-to-referee-svod9-done.md` |  | Отчёт рефери: свод №9 внедрён полностью (remlab, 14.08, вечер) | 0 |  | не сведён |
| `codex/speedup_patch.py` |  | УСКОРЕНИЕ 17.08 (Codex): ACC_MANIFEST=<json-список id> или ACC_SCENES=id1,id2 — подмножест | 0 |  | не сведён |
| `codex/answer-audit-julia.md` |  | Вывод: рефери права по визуальным симптомам №1/3, №14–16, №27/31 и №41/57; слишком категор | 2 | .memory_bank/completed_plans/canons-audit-julia.md, .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/answer-cascade-wiring.md` |  | Вывод: A нужен — это реальный wiring-дефект. Но helper не должен быть простым `joint first | 1 | .memory_bank/completed_plans/plans-rebuild-post-canons.md | сведён/цитируется |
| `codex/answer-doctrine-0117.md` |  | Вывод: доктрина хороша как визуальная легенда, но неверна как источник машинной семантики. | 3 | .memory_bank/completed_plans/plans-rebuild-post-canons.md, .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/answer-dresser-rule.md` |  | Вывод: это продуктовая доктрина, не общая норма. Если владелец говорит «не должен», её мож | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/answer-rug-audit.md` |  | Вывод: F2 верен по направлению, F3 уже частично существует, а F1 нельзя вводить с предложе | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/answers-to-referee-q1-12.md` |  | Ответы исполняющего агента на Q1–Q12 свода №9 (remlab, 14.08) | 1 | .memory_bank/completed_plans/MASTER-zones-v3.md | сведён/цитируется |
| `codex/codex-audit-blind-round1.md` |  | Итог: проблема не в beam как поиске, а в несоответствии `plan_key` реальным приоритетам. В | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/codex-audit-catalog-nook.md` |  | Краткий вывод: направление в целом правильное, но три решения я бы изменил. | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/codex-audit-svod12.md` |  | Итог: владелец прав в главном — текущая система недостаточно сравнивает целостные планиров | 1 | .memory_bank/completed_plans/MASTER-zones-v6.md | сведён/цитируется |
| `codex/codex-audit-v5.md` |  | Аудит Кодекса (gpt-5.6, xhigh) — независимая экспертиза алгоритма расстановки (15.08) | 3 | .memory_bank/completed_plans/MASTER-zones-v5.md, .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/codex-catalog-load-plan.md` |  | Вывод | 2 | .memory_bank/completed_plans/catalog-load-hardening.md | сведён/цитируется |
| `codex/codex-color-answer.md` |  | Вывод: массовую волну A/B/C сейчас запускать рано. «Сжатие светлоты» правдоподобно, но рег | 2 | .memory_bank/core/mesh-color.md, .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/codex-color2.md` |  | Ты независимый старший инженер-рецензент. Разбери задачу сам, не считая нашу текущую реали | 1 | .memory_bank/decisions/adr-0151-0200.md | сведён/цитируется |
| `codex/codex-goal-addendum-templates.md` |  | Дополнение принимаю. Оно подтверждает прошлый вывод: библиотека шаблонов выглядит богатой  | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/codex-goal-review.md` |  | Цель по сути верная, но сейчас её можно формально выполнить и всё равно получить плохой пл | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/codex-node-breaker-answer.md` |  | Вывод | 3 | .memory_bank/completed_plans/mesh-idle-between-batches.md, .memory_bank/completed_plans/mesh-node-health-breaker.md, .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/codex-onboarding-notes.md` |  | A. Продукт и ограничения | 1 | .memory_bank/domain/integrations.md | сведён/цитируется |
| `codex/codex-overlap-answer.md` |  | Вывод: полный 2D-pushout A как общее решение неверен — он выталкивает законно задвинутый с | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/codex-owner-gallery-rotation-answer.md` |  | Вердикт: `rot` надо поднять до жёсткого контракта позы. `set91-base` — семантически неполн | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/codex-q5-design-answer.md` |  | Рекомендация: с 25 м² давать солверу согласованную пару кресел как возможность; с 40 м² га | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/codex-q5-regress-answer.md` |  | Короткий вывод: клоны откатывать нельзя. Здесь одновременно два дефекта: размерозависимая  | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/codex-review-v7-draft.md` |  | Вердикт: [MASTER-zones-v7.md](/home/pakar/igor/remlab/.memory_bank/plans/MASTER-zones-v7.m | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/codex-stock-honesty-answer.md` |  | Вывод | 2 | .memory_bank/completed_plans/stock-and-dims-honesty.md, .memory_bank/domain/stock-and-dims.md | сведён/цитируется |
| `codex/codex-zones-practice.md` |  | Итог: базовый репертуар у нас уже широкий, но покрытие переоценено. Главные реальные дыры  | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/orient-v2.answer.md` |  | Вывод | 9 | .memory_bank/core/mesh-pipeline.md, .memory_bank/decisions/adr-0151-0200.md, .memory_bank/plans/README.md | сведён/цитируется |
| `codex/owner-gallery-rotation.md` |  | Продолжаем (сессия-советник по расстановке). Владелец смотрит новую галерею (после Q1–Q4)  | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q-deploy-db-init-scope.answer.md` |  | Вывод | 1 | .memory_bank/completed_plans/deploy-db-init-scope-fix.md | сведён/цитируется |
| `codex/q-deploy-db-init-scope.md` |  | Разбор: «Deploy prod» падает с 01.09, smoke-тест и авто-откат не выполняются | 1 | .memory_bank/completed_plans/deploy-db-init-scope-fix.md | сведён/цитируется |
| `codex/q-mesh-owner-audit-2.answer.md` |  | Вывод | 1 | .memory_bank/plans/mesh-owner-audit.md | сведён/цитируется |
| `codex/q-mesh-owner-audit-2.md` |  | Второй заход: аудит ПЕРЕРАБОТАННОГО плана mesh-owner-audit | 1 | .memory_bank/plans/mesh-owner-audit.md | сведён/цитируется |
| `codex/q-mesh-owner-audit.answer.md` |  | Вывод | 1 | .memory_bank/plans/mesh-owner-audit.md | сведён/цитируется |
| `codex/q-mesh-owner-audit.md` |  | Критика плана: страница ручной приёмки мешей владельцем (mesh-owner-audit) | 1 | .memory_bank/plans/mesh-owner-audit.md | сведён/цитируется |
| `codex/q-salad-mesh-pool.answer.md` |  | Вывод | 4 | .memory_bank/completed_plans/mesh-dino-baked.md, .memory_bank/decisions/adr-0151-0200.md, .memory_bank/domain/integrations.md | сведён/цитируется |
| `codex/q-salad-mesh-pool.md` |  | Вопрос: конфигурация пула Salad для генерации 3D-мешей — что мы делаем не так | 4 | .memory_bank/completed_plans/mesh-dino-baked.md, .memory_bank/decisions/adr-0151-0200.md, .memory_bank/domain/integrations.md | сведён/цитируется |
| `codex/q-ssh-run-dynamic-nodes.answer.md` |  | 1. Вывод | 2 | .memory_bank/decisions/adr-0101-0150.md, .memory_bank/plans/mesh-dynamic-node-pool.md | сведён/цитируется |
| `codex/q-ssh-run-dynamic-nodes.md` |  | Вопрос: динамический состав нод в прогоне мешей (ssh_run.py) | 2 | .memory_bank/decisions/adr-0101-0150.md, .memory_bank/plans/mesh-dynamic-node-pool.md | сведён/цитируется |
| `codex/q10-close-gap.answer.md` |  | Вердикт | 2 | .memory_bank/guides/layout-engine-spec.md, .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q10-close-gap.md` |  | Продолжаем (layout-сессия). Владелец: «как нам приблизиться к практике — советуйся с Codex | 2 | .memory_bank/guides/layout-engine-spec.md, .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q10-seat-distribution.answer.md` |  | Вывод | 1 | .memory_bank/guides/layout-engine-spec.md | сведён/цитируется |
| `codex/q10-seat-distribution.md` |  | Продолжаем (layout-сессия). Q10b внедрён (оконный уголок `place_window_reading`, форма `wi | 1 | .memory_bank/guides/layout-engine-spec.md | сведён/цитируется |
| `codex/q11-canon-visual-defects.answer.md` |  | 1. Вывод | 1 | .memory_bank/completed_plans/q11-canon-reference-contract.md | сведён/цитируется |
| `codex/q11-canon-visual-defects.md` |  | Ты — независимый старший инженер-рецензент. Проанализируй сам, не считай гипотезу другого  | 1 | .memory_bank/completed_plans/q11-canon-reference-contract.md | сведён/цитируется |
| `codex/q11-gallery-review-1.answer.md` |  | Короткий вывод: пункты 1, 3 и 4 — реальные дефекты геометрии/поиска. Пункт 2 смешивает раз | 3 | .memory_bank/completed_plans/q11-canon-reference-contract.md, .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/q11-gallery-review-1.md` |  | Контекст: владелец смотрит галерею канонов /test/canons (коммит a82031f) и прислал замечан | 3 | .memory_bank/completed_plans/q11-canon-reference-contract.md, .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/q11-window-chair-orientation.answer.md` |  | Вывод | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/q11-window-chair-orientation.md` |  | Вопрос НОРМЫ предметной области (нужны источники, не мнение). | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/q12-canon-audit.answer.md` |  | Вывод | 4 | .memory_bank/decisions/adr-0101-0150.md, .memory_bank/plans/q12-situational-canon.md | сведён/цитируется |
| `codex/q12-canon-audit.md` |  | АУДИТ БИБЛИОТЕКИ КАНОНОВ (задача владельца 19.08: «сделай аудит канонов с Codex, предложи  | 4 | .memory_bank/decisions/adr-0101-0150.md, .memory_bank/plans/q12-situational-canon.md | сведён/цитируется |
| `codex/q12-situational-canon.answer.md` |  | Вывод | 11 | .memory_bank/archive/plans/MASTER-pipeline-hardening.md, .memory_bank/archive/plans/catalog-freshness-chain.md, .memory_bank/changelog/project-history.md | сведён/цитируется |
| `codex/q12-situational-canon.md` |  | СТРАТЕГИЧЕСКИЙ ВОПРОС АРХИТЕКТУРЫ (решение владельца 19.08, нужна критика и план). | 11 | .memory_bank/archive/plans/MASTER-pipeline-hardening.md, .memory_bank/archive/plans/catalog-freshness-chain.md, .memory_bank/changelog/project-history.md | сведён/цитируется |
| `codex/q24-orienter.answer.md` |  | Вывод | 1 | .memory_bank/plans/viz-mesh-orientation.md | сведён/цитируется |
| `codex/q24-orienter.md` |  | Ты — независимый ревьюер. Владелец предложил конвейер канонической ориентации мешей (внешн | 1 | .memory_bank/plans/viz-mesh-orientation.md | сведён/цитируется |
| `codex/q24-salad-mesh.answer.md` |  | Вывод | 1 | .memory_bank/plans/mesh-bulk-salad-hunyuan.md | сведён/цитируется |
| `codex/q24-salad-mesh.md` |  | Критика плана: массовая генерация PBR-мешей на своём образе (Salad + Hunyuan3D 2.1) | 1 | .memory_bank/plans/mesh-bulk-salad-hunyuan.md | сведён/цитируется |
| `codex/q25-queue.answer.md` |  | 1. Вывод | 1 | .memory_bank/plans/mesh-queue-orientation.md | сведён/цитируется |
| `codex/q25-queue.md` |  | You are an independent senior software-engineering reviewer. | 1 | .memory_bank/plans/mesh-queue-orientation.md | сведён/цитируется |
| `codex/q5-axis-shift-tier.answer.md` |  | Вердикт: нужен отдельный лексикографический признак деградации шаблона; optional-зоны счит | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/q5-axis-shift-tier.md` |  | Продолжаем (layout-сессия). Замечание владельца по галерее (№31 set16-base, 14.9 м²): «поч | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/q5-design.md` |  | Продолжаем (сессия-советник по расстановке). Что изменилось: Q1–Q4 закоммичены (0d40589):  | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q5-exam-gate.answer.md` |  | Вывод: Q5 по поиску прошёл, production-выбор менять до Q7 не надо. Но каталог Q5 пока нель | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q5-exam-gate.md` |  | Продолжаем (сессия-советник, remlab layout). Q5 доведён по твоим правкам: ay per-armchair, | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q5-pod-surface.answer.md` |  | Вывод: делать только атомарный `quiet_pod = кресло 3 + кресло 4 + столик 2`. Камин — альте | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q5-pod-surface.md` |  | Ты — независимый советник по каталогу/сборке сетов remlab (read-only). Проект тот же, сесс | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q5-regress.md` |  | Продолжаем (сессия-советник). Q5 применён по твоему дизайну: composer — кресло 2 = КЛОН ос | 1 | .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q6a-capabilities.answer.md` |  | Вердикт: направление правильное — отдельная capability-проекция без изменения `cat_role`.  | 1 | tools/scout/rules/capabilities.json | сведён/цитируется |
| `codex/q6a-capabilities.md` |  | Продолжаем (каталожная сессия). Q6a свода №13 (MASTER-zones-v7 §Q6a): capability-модель ка | 1 | tools/scout/rules/capabilities.json | сведён/цитируется |
| `codex/q6b-edge-nook.answer.md` |  | Вердикт: концепция правильная, но до реализации я бы исправил четыре контракта: не использ | 1 | .memory_bank/guides/layout-engine-spec.md | сведён/цитируется |
| `codex/q6b-edge-nook.md` |  | Продолжаем (layout-сессия). Q6b мастер-плана: шаблон edge_nook — «банкетка спинкой к стене | 1 | .memory_bank/guides/layout-engine-spec.md | сведён/цитируется |
| `codex/q8-window.answer.md` |  | Вывод: диагноз владельца верный, но `31–90 = hard` напрямую вводить нельзя. Правильнее сде | 2 | .memory_bank/guides/layout-engine-spec.md, .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q8-window.md` |  | Продолжаем (layout-сессия). Q8 свода №13 — владелец поднял по галерее (План №3, set2-base) | 2 | .memory_bank/guides/layout-engine-spec.md, .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q9-zone-priors.answer.md` |  | Главный вывод: частоты нельзя превращать в случайный выбор или напрямую заставлять экзамен | 2 | .memory_bank/guides/layout-engine-spec.md, .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/q9-zone-priors.md` |  | Продолжаем (layout-сессия). Владелец прислал ЧАСТОТЫ практики дизайнеров по зонам и просит | 2 | .memory_bank/guides/layout-engine-spec.md, .memory_bank/plans/MASTER-zones-v7.md | сведён/цитируется |
| `codex/reply-to-referee-svod8.md` |  | Ответ рефери на свод №8 (переработка выбора зон) — от исполняющего агента remlab | 2 | .memory_bank/completed_plans/MASTER-zones-v2.md | сведён/цитируется |
| `codex/report-to-referee-svod8-done.md` |  | Отчёт рефери: свод №8 v2 внедрён (remlab, 14.08) | 1 | .memory_bank/completed_plans/MASTER-zones-v2.md | сведён/цитируется |
| `codex/speedup-plan.answer.md` |  | Вывод: пункты 1–4 правильные. `large_xl cap 3→2` для боевого режима не делать; 10 воркеров | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `codex/speedup-plan.md` |  | Продолжаем (layout-сессия). Владелец: «разработка идёт очень долго — всё считается/пересчи | 1 | .memory_bank/decisions/adr-0101-0150.md | сведён/цитируется |
| `README.md` | 2026-09-05 | _intake — входная папка (сырьё, не хранилище) | 156 | .memory_bank/INDEX.md, .memory_bank/METADATA_SCHEMA.md, .memory_bank/README.md | сведён/цитируется |
| `owner/blind-round1-owner.md` |  | Слепая оценка, раунд 1 (16.08) — ответы владельца дословно (пары 1–10 из 20) | 1 | .memory_bank/plans/MASTER-zones-v7.md | сырьё владельца |
| `owner/catalog-extract-nook.txt` |  | == РОЛИ КАТАЛОГА (in_stock, с ценой и фото): роль \| кол-во \| медиана Ш×Г×В см \| медиана це | 1 | .memory_bank/plans/MASTER-zones-v7.md | сырьё владельца |
| `owner/dialog-catalog-load-0309.md` |  | remlab: как работает проект и загрузка каталога. Диалог владельца и агента, 3 сентября 202 | 5 | .memory_bank/changelog/project-history.md, .memory_bank/completed_plans/catalog-load-hardening.md, .memory_bank/core/catalog.md | сырьё владельца |
| `owner/exposure-effect-0109.json` |  | [ | 1 | .memory_bank/domain/viz-fidelity-playbook.md | сырьё владельца |
| `owner/mesh-dims-calibration-0309.json` |  | { | 1 | .memory_bank/completed_plans/catalog-load-hardening.md | сырьё владельца |
| `owner/owner-comments-svod12.md` |  | Комментарии владельца по галерее приёмки (/test/acceptance-plans/), 2026-08-15 — ДОСЛОВНО | 1 | .memory_bank/completed_plans/MASTER-zones-v6.md | сырьё владельца |
| `owner/owner-marks-mesh-color-0109.txt` |  | светлее (15): | 1 | .memory_bank/core/mesh-color.md | сырьё владельца |
| `owner/owner-verdict-exposure-0109.txt` |  | Вердикт владельца по опыту со сдвигом экспозиции входа (01.09, страница /test/mesh-color/) | 1 | .memory_bank/core/mesh-color.md | сырьё владельца |
| `owner/self-analysis-svod12.md` |  | Самоанализ агента ДО консультации Кодекса — комментарии владельца по галерее (свод №12) | 1 | .memory_bank/completed_plans/MASTER-zones-v6.md | сырьё владельца |
| `owner/zones-practice-vs-ours-agent.md` |  | Варианты зон гостиной в практике дизайнеров vs наши шаблоны — поиск агента (16.08) | 1 | .memory_bank/plans/MASTER-zones-v7.md | сырьё владельца |

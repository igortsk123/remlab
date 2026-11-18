# Триаж планов — предложение директору (T-20261118-60/3), НЕ применено

Основа: поле `status`/`updated`/`pause_reason`/`resume_trigger` в `plans/*.md` на 18.11 (63 in_progress, 45 partial, 30 draft = 138 из `plans/`). Сверки с кодом по каждому плану не делал — это предложение по шапкам и датам; спорное помечено «?» — решает директор/владелец. Применение: `completed` → `completed_plans/`, `archive` → `archive/plans/` с `archive_reason`, оба — с строкой в `changelog/memory-log.md`.

## А. partial старше 30 дней (21) — предложение по каждому
| План | Предложение | Почему |
|---|---|---|
| b2b-00-hypothesis-research | оставить partial | ждёт интервью владельца; причина в шапке есть |
| b2b-02-lead-flow-developer | оставить partial | нужен номер телефона владельца |
| b2b-04-legal-pdn-gdpr | archive ? | юридическое владелец велел не приносить (12.11, TG 1038) — решает владелец |
| b2b-05-demo-save-share | completed ? | «всё, кроме п.5b сделано и выкачено»; п.5b — отдельным пунктом, если нужен |
| b2b-09-ops-reliability | оставить partial | ждёт ответов владельца 12–13 |
| b2b-10-rooms-beyond-living | archive | поглощён room-*/onb-* (комнаты вне гостиной идут там) |
| b2b-11-uk-market-pack | оставить partial | ждёт доступ к UK-посреднику; РФ первым |
| book-memory-sync | completed | механизм целиком сделан 14.10, работает (BOOK-STALE=0 в аудите) |
| conv-01-style-gold-and-bench | оставить partial | ждёт отметок владельца |
| conv-04-mesh-quarantine | оставить partial | п.5 при следующей волне |
| conv-06-process-tests | completed | «сделано 14.10: 19 стыков, тест»; хвост — «следующий проход» не обязателен |
| conv-07-cutout-before-style-experiment | оставить partial | ждёт выбора метода conv-01 |
| conv-09-set-to-variant-integrity | completed ? | код выкачен 13.10; ждёт только «посмотрел /demo» — владелец уже много раз смотрел |
| conv-11-mesh-wave-autostart | оставить partial | ждёт «волна до $N до даты»; для владельца важное |
| demo-03-demo-scenario-tests | completed | «всё сделано и выкачено 14.10»; критерий «три сводки без WARN» — следить в сводке, не планом |
| demo-04-scene-look | completed ? | пункты 1–6 закрыты, остался вердикт владельца по виду |
| demo-05-scene-artifacts-3d | оставить partial | ждёт замер на iPhone |
| demo-14-product-references | оставить partial | ждёт ночную очередь |
| flat3d-sims-ux | оставить partial | 23 из 24, A1 — решение владельца |
| memory-kit-v19-migration | archive | относится к sup2; в remlab кит давно v1.9+ (`_kit/VERSION`) |

## Б. draft старше 30 дней (4)
| План | Предложение |
|---|---|
| MASTER-conveyor-gaps | archive — поглощён `conveyor-guards-01` и план-задач |
| MASTER-developer-product | оставить draft ? — B2B-ветка, владелец решает |
| conv-02-style-single-vector | archive — conv-01 (золото и бенч) его заменил |
| demo-08-collection-dossier | archive ? — коллекции покупателя выкачены (ADR-0264/0306), досье отдельно не нужно |

## В. partial со «слабой» причиной «без движения с 23.10 / триаж ведущим после приёмки демо комнат» (кандидаты закрыть или оживить)
catalog-holes-bank, conv-14b-bank-kept, demo-24-soft-in-list, demo-26-preload-3d, demo-27-phone-view-quality, demo-28-color-variants, demo-29-night-realistic, mesh-audit-comments — **предложение: по каждому одна строка директору «сделано/нет» после сверки кодом** (demo-26/27/28 по ADR-0319…0326 в Tier 2 уже описаны как работающие — вероятно `completed`: «Демо 22–24.10: ракурсы, мягкое, цвета, карточка, подгрузка 3D»). Плюс demo-06/07/18 «без движения с 16–19.10 (PLAN-STUCK)» — `archive`, если владелец не вернёт.

## Г. in_progress, которых нет ни в плане задач, ни в отчётах (по 18.11 — вероятно закрыты и не переведены)
Группы и предложение (каждая — сверить с `core/*` и `git log`, затем completed):
- **onb-\*** (onb-00, 01, 03, 04, 05, 0A, 13; draft: 06, 07, 09, 10, 11, 12) — опрос и спальня; `core/onboarding-quiz.md` и `core/bedroom.md` описывают как работающее → большинство `completed`; draft-хвосты (06, 07, 09–12) — `archive` или partial с причиной.
- **room-\*** (room-bank-01, room-bank-nightly-04, room-conveyor-02, room-photos-07, room-pipeline-01; draft room-templates-rules-01) — ночной конвейер комнат живёт (`core/room-templates.md`) → completed, кроме room-templates-rules-01 (partial?).
- **photo-\*** (before-publish, model-rebench, sharp-keep, speed, speed-monitor, swipe-pan, prompt-chunks, tariff-mass; draft render-first) — часть живёт (`core/photo-render.md`); photo-tariff-mass-01/prompt-chunks 13–17.11 — свежие, оставить.
- **trial-\*, tour-\*, floorplan-\*** (trial-buyer-gate, confirm-plan, reparse, room-edit; tour-as-demo, auto-photos, auto-reissue; floorplan-advisor-trials, raster-bench) — проба агента UK; `core/agent-trial.md` — сверить.
- **bedroom-\*, quiz-pairs-01, home-mix-01, home-figma-02, kids-room-01, kitchen-show-01, hall-catalog-09, orient-cabinet-01, style-color-01, style-fallback-01, dims-effective-01, plan-blob-01, mem-freshness-01, merge-queue-01, ops-token-policy-01, design-02-figma-components** — по одному `completed`/`partial` после сверки.
- Свежие (17–18.11), не трогать: memory-code-audit-01, mesh-grey-top-01, render-key-01, render-machine-01, render-materials-01, render-prep-speed-01, tour-render-01, wall-finishes-01, bedroom-life-01, set-composition-01, render-3d-01, render-qa-gate-01.

## Выигрыш
После закрытия А–Б и ~25 из Г в `plans/` останется ≈ 70 из 138; `plans/README.md` (25 чтений/мес) станет вдвое короче. Каждое закрытие — `completed:` дата + «Completion summary» одной строкой (иначе аудит `PLAN-COMPLETED-NO-DATE`).

Если одобряешь — скажи группы, возьму сам (сверка по `core/*`+`git log` без субагентов, ≈ 2 ч). Без твоего слова не трогаю.

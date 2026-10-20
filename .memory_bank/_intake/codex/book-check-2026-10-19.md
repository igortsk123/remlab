Сверил 39 пометок «Сегодня» (включая встроенные) и названия файлов и функций в скобках вне них. «Верно» означает, что описание согласуется с исходниками; числа из прошлых прогонов, состояние домашнего компьютера и подключение внешних сервисов по репозиторию подтвердить нельзя.

| Абзац (глава) | Что сказано | Что в коде (файл:строка) | Итог |
|---|---|---|---|
| 85 (1) | Валюта и доля заданы карточкой; есть британский двойник | `lib/partners/registry.ts:52`; `data/partners/demo.json:314` | Верно |
| 113 (1) | Карточка из реестра, геометрия демо — отдельно | `lib/partners/registry.ts:8`; `tools/scout/flat215_demo.py:443` | Верно |
| 132 (1) | Бот создаёт ссылку, когда у застройщика одна квартира **в демо** | `modules/sends/apartments.ts:8` отдаёт все квартиры партнёра; `modules/sends/bot.ts:77` требует ровно одну. У `demo-uk` их две: `data/partners/demo-uk.json:25`, `data/partners/demo-uk.json:100` | **Неверно** |
| 150 (1) | Полные варианты публикуются; прежнего лимита в четыре нет | `tools/scout/flat215_demo.py:781`; `tools/scout/flat215-demo/index.html:1062` (`MAXV=6`) | Верно по логике |
| 164 (1) | `hintFor()` рассчитает подсказку, но `HINTS_ON=false` скрывает её | `tools/scout/flat215-demo/index.html:4256`, `tools/scout/flat215-demo/index.html:4322` | Верно |
| 181 (1) | Предел ожидания кадра — 3/8 минут | `tools/scout/flat215-demo/index.html:3519`: пределы **12/16 минут** | **Неверно** |
| 204 (1) | Комнаты-заглушки и варианты отделки | `tools/scout/flat215-demo/index.html:3200`; `data/partners/demo-uk.json:236` | Верно по коду |
| 218 (1) | Кнопки обращения ведут к менеджеру при наличии его ссылки | `tools/scout/flat215-demo/index.html:5579` | Верно |
| 237 (1) | События отправки, сигналы и отчёт | `modules/sends/dispatch.ts:18`; `modules/partner-report/report.ts:55` | Верно |
| 316 (2) | `demo_swap_pool.py` требует все три размера, в отличие от `footprint.py` | `tools/scout/demo_swap_pool.py:68` подставляет диаметр за ширину **и** глубину; `tools/scout/footprint.py:42` тоже допускает диаметр | **Неверно** |
| 430 (3) | Обогащение: 200 карточек, дневной денежный предел | `tools/scout/refresh_daily.sh:296`; `tools/scout/openai_budget.py:33` | Верно по настройкам |
| 453 (3) | Текущий скоринг, порог 6,6 и стенд | `tools/scout/rules/demo-swap.json:5`; `tools/scout/style_bench.py:39` | Верно |
| 457 (3) | `candidates.py` читает живость фото **по-прежнему только из кэша** | `tools/scout/candidates.py:71` уже отсекает по `photo_alive` **в БД**, а `tools/scout/candidates.py:89` дополнительно сверяет кэш | **Неверно** |
| 497 (4) | Волна требует разрешения и потолка расходов | `tools/scout/salad/wave_guard.py:1` | Верно по коду |
| 517 (4) | Признаки карантина — коллаж и подложка; пропорции справочные | `tools/scout/mesh_quarantine.py:39` включает ещё признак **`dark`** | **Неверно** |
| 524 (4) | Готовность модели считается несколькими путями | `tools/scout/mesh_ready.py:23`; `tools/scout/demo_swap_pool.py:72` | Верно |
| 532 (4) | Лёгкие копии обязательны для публикации демо | `tools/assets/demo_rt.sh:1`; `tools/scout/flat215_demo.py:1237` | Верно по коду |
| 553 (5) | Лечение комплектов и пороги столов | `tools/scout/heal_policy.py:1`; `services/planner-solver/rules/zones.json:706` | Верно по правилам |
| 568 (5) | Демосцены добавлены в ночной экзамен | `tools/scout/nightly_exam.sh:22` | Верно по коду |
| 591 (5) | Прогрев кадров и первых четырёх вариантов | `tools/ops/demo-warm.mjs:31`; `tools/scout/draft_service.py:677` | Верно |
| 594 (5) | Замены, порог 6,6 и отбор полных вариантов | `tools/scout/rules/demo-swap.json:5`; `tools/scout/flat215_demo.py:781` | Верно по правилам |
| 610 (6) | Переводится слой показа, не внутренние роли | `tools/scout/flat215-demo/index.html:6231` | Верно |
| 630 (6) | Номер отправки сохраняется в снимке, но не восстанавливается из общей ссылки | `tools/scout/flat215-demo/index.html:5883`; `tools/scout/flat215-demo/index.html:5857` | Верно |
| 634 (6) | Сердечко, ссылка на коллекцию и отправка в Telegram | `tools/scout/flat215-demo/index.html:6098`; `app/api/leads/tg-client/route.ts:1` | Верно по коду |
| 645 (6) | Точки съёмки, фоновые задания и проверки | `tools/scout/flat215-demo/index.html:1388`; `e2e/live/demo-scenarios.live.ts:1` | Верно по коду |
| 651 (6) | После правки показывается живая 3D-сцена | `lib/viewer3d/demo-scene.ts:119`; `tools/scout/flat215-demo/index.html:4803` | Верно |
| 657 (6) | Режимы фото/3D и указанная модель генерации | `tools/scout/flat215-demo/index.html:5211`; `tools/scout/systemd/remlab-render.service:17` | Верно по настройкам |
| 681 (6) | Сигналы отправляет `dispatch.ts` | `modules/sends/dispatch.ts:18` | Верно |
| 698 (7) | Базовая 3D-квартира — британская демо | `data/flat3d/apartment.json:3`; `lib/configurator/source.ts:131` | Верно |
| 710 (7) | Базовая кухня и управление предметами | `data/flat3d/apartment.json:112`; `components/flat3d/useFlatConfig.ts:38` | Верно по коду |
| 718 (7) | Конфигурация сохраняется, коллекция переносится в 3D | `app/api/flat/config/route.ts:21`; `lib/configurator/source.ts:131` | Верно |
| 727 (7) | Интерфейс переведён, каталог товаров остаётся российским | `lib/configurator/i18n.ts:1`; `components/flat3d/BuildBar.tsx:184` | Верно по коду |
| 753 (8) | У бота есть статусы; партнёрский API пока описан документом | `modules/sends/bot.ts:49`; `docs/partner-api.md:1` | Верно по коду |
| 767 (8) | Страница менеджера находится по `/manager/[key]` | Маршрут — `app/manager/page.tsx:9`; ключ читается из **`#`**, а не из пути: `components/manager/ManagerPage.tsx:11` | **Неверно** |
| 787 (9) | Образ домашнего контейнера предусмотрен | `infra/dev/Dockerfile:1` | Верно по коду |
| 797 (9) | Тревога конвейера приходит **только** при смене состояния | `tools/scout/pipeline_map.py:193` повторяет её по истечении интервала напоминания | **Неверно** |
| 806 (9) | Заданы копии, репетиция восстановления и порог диска | `tools/ops/backup-pull.sh:3`; `infra/dev/crontab:11`; `tools/ops/dev-checks.sh:6` | Верно по расписанию |
| 818 (9) | `share_requests` удаляются через 90 дней | Срок задаёт `modules/share-requests/repository.ts:19`, но очистка вызывается **при новой заявке**: `app/api/internal/share-request/route.ts:37`; плановая очистка их не охватывает: `modules/retention/run.ts:85` | **Неверно** |
| 847 (10) | Два автоматических среза ещё включены | `tools/scout/salad/pipeline.py:497`, `tools/scout/salad/pipeline.py:501`; дополнительный срез обломков — под флагом | Верно |

Отдельно — утверждения при именах функций **в скобках**, не в пометках «Сегодня»:

| Абзац (глава) | Что сказано | Что в коде (файл:строка) | Итог |
|---|---|---|---|
| 289 (2), `step()` | При `openai.off` пропускается только обогащение | `tools/scout/refresh_daily.sh:235` пропускает также платный `rug_kids` | **Неверно** |
| 574 (5), `catalog_media.media().state` | Состояние читается этим выражением | `tools/scout/catalog_media.py:111`: `media(mid, eid)` требует аргументы и возвращает словарь либо `None`; фактическое чтение — `tools/scout/flat215_demo.py:424` | **Неверно** |
| 791 (9), `buildHealth()` | Функция сама проверяет базу и витрину | `lib/health.ts:20` собирает ответ из результатов; проверки вызывает `app/api/health/route.ts:7` | **Неверно** |

**Итого: 11 расхождений.** Файлы не менял.
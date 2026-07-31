---
workstream: ui
slug: uui-migration
title: Миграция UI на Untitled UI React (Tailwind v4 + React Aria) — мастер с подпланами U0–U4
status: in_progress
created: 2026-07-31
updated: 2026-07-31
completed:
---

## Цель
Полностью перевести фронтенд remlab с ручного CSS (337 строк globals.css, 17 самописных
компонентов) на дизайн-систему **Untitled UI React** (copy-paste-модель: Tailwind CSS v4 +
React Aria Components, MIT), сохранив бренд-преемственность прода (терракота/тёплый japandi)
и не сломав ни одного пользовательского флоу, e2e-теста и цели Метрики.

## Источник задачи
Владелец выбрал Untitled UI React из топ-3 (ресёрч awesome-design-systems, 2026-07-31) и
попросил план «с серией подпланов» полного перехода + анализ преднастроенных палитр с
фиксацией выбора в плане.

## Решение по палитре (зафиксировано; владелец может изменить словом — это его зона)
Анализ пресетов: в `styles/theme.css` UUI — 15 готовых шкал (brand=фиолетовый по умолчанию,
amber, blue, emerald, fuchsia, green, indigo, neutral, orange, pink, purple, red, sky, slate,
yellow). Смена бренда = переопределение `--color-brand-50..950` (11 переменных) — штатный
механизм. Терракоты/шалфея среди пресетов НЕТ; пресет orange (~#EF6820) — яркий
«маркетплейсный», ломает узнаваемость и тёплый japandi-тон прода (реклама сейчас НЕ идёт —
уточнение владельца 2026-07-31; аргумент — преемственность бренда, а не кампании).
Гибрид подтверждён владельцем 2026-07-31. Итог — **гибрид**:

| Слот | Выбор | Почему |
|------|-------|--------|
| brand-шкала | **кастом-терракота** от прод-CTA `#b06a4a` (см. значения ниже) | преемственность бренда; штатный механизм UUI |
| нейтраль (текст/рамки/фоны) | **пресет Tailwind `stone`** → маппится в `--color-neutral-*` | тёплый серый ≈ наш greige/крем, japandi сохраняется |
| статусные error/warning/success | **пресеты red / yellow(amber) / green как есть** | не изобретать; наши `--danger #a4462f`/`--ok #5f7a54` близки |
| фон страницы / карточек | оверрайд `--color-bg-secondary: #f3eee7` (крем) и `--color-bg-primary: #fbf8f3` | сохранить тёплый фон прода |
| шрифт | **Inter** через `next/font` (self-host на билде, без runtime-запросов к Google — важно для РФ) | родной шрифт UUI, отличная кириллица |
| тёмная тема | НЕ включаем (токены `.dark-mode` остаются на будущее) | сайт светлый; не расширять скоуп |
| шалфей `#8a9a7b` (вторичный акцент) | упраздняется как отдельная шкала; смысловые места → brand-tint / success-токены | у UUI один бренд-акцент; двухакцентность — источник разнобоя |

Терракотовая brand-шкала (черновик, U0 уточняет контраст WCAG ≥4.5:1 для текста на 600):
50 `#faf3ef` · 100 `#f4e4db` · 200 `#e8c8b7` · 300 `#d9a78e` · 400 `#c78767` · 500 `#b06a4a`
· 600 `#9a5a3d` · 700 `#7f4a33` · 800 `#683d2c` · 900 `#563327` · 950 `#2f1a13`.
(500/600 = текущие CTA/hover прода — пиксельная преемственность кнопок.)

## Скоуп — что входит
- Tailwind v4 + стили UUI (`styles/globals|theme|typography.css`) в проект; кастом-палитра.
- Копирование нужных компонентов UUI (base + application) в `components/ui/` (наш код, MIT).
- Перевод всех 17 компонентов и всех страниц (`app/**`) на UUI-примитивы и utility-классы.
- Демонтаж старого CSS (классы `.btn/.chip/.card/...`) и старых токенов после миграции.
- Обновление `ui-rules.md` под реальные токены UUI; ADR о выборе системы и палитры.

## Скоуп — что НЕ входит
- PRO-подписка ($349) — не нужна для ядра; решение об апгрейде — владельца.
- Тёмная тема, редизайн флоу, новые фичи, смена текстов.
- Ядро сметы М1–М3 (отдельный мастер-план) — но U3 готовит ему Table/EmptyState.

## Подпланы (каждый — отдельный деплой: зелёные typecheck/lint/test/build + e2e, push, прод)

### U0 — Фундамент (инфраструктура, видимых изменений почти нет)
- Депсы: `tailwindcss@4`, `@tailwindcss/postcss`, `react-aria-components`, `tailwind-merge`,
  `tailwindcss-react-aria-components`, `tailwindcss-animate`, `@untitledui/icons`.
  (`motion`, `recharts`, `sonner`, `react-hook-form` — НЕ ставить до реальной нужды.)
- `postcss.config.mjs`; `styles/uui/{globals,theme,typography}.css` из репо UUI;
  поверх — `styles/brand.css`: терракота-шкала, neutral→stone, фоны-крем (таблица выше).
- Inter через `next/font/google` в `app/layout.tsx` (self-host на билде), `--font-inter`.
- `utils/cx.ts` (tailwind-merge) из UUI.
- **Мост совместимости:** старые токены (`--bg`, `--surface`, `--text`, `--accent-strong`…)
  объявить алиасами семантических токенов UUI — старый CSS продолжает работать без правок.
- Проверить: `body { zoom }` (масштаб П4) не конфликтует с rem-вёрсткой Tailwind.
- Файлы: `package.json`, `postcss.config.mjs`, `app/layout.tsx`, `app/globals.css` (импорты),
  `styles/**` (новые), `utils/cx.ts`.
- Приёмка: прод выглядит как раньше (допустимая разница — шрифт Inter); e2e зелёные.

### U1 — Примитивы форм и кнопок (ядро взаимодействий)
- Скопировать в `components/ui/`: buttons, input, textarea, select, checkbox, radio-buttons,
  badges, tags, tooltip, progress-indicators, form.
- Заменить: `.btn`/`.btn-secondary` (все вхождения), `.chip`+`SelectChips`/`SelectRoom` (Tags/
  Checkbox-group UUI), поля `CalcForm` и форм лида (`ReportProblem`, city-autocomplete —
  Input+Dropdown), `PayButton`, `ShareButton`, `TrackedSubmit` (обёртка над Button UUI —
  событcandidateМетрики сохранить как есть, урок №9), `Progress`, бейджи (`LabBadge`,
  `.soon-pill/.soon-badge/.auto-badge` → Badge), `.help`-тултип → Tooltip, `.icon-del` →
  ButtonUtility (тап-зона ≥44px сохранить).
- Приёмка: оба калькулятора и форма лида проходят руками + e2e; цели Метрики стреляют.

### U2 — Каркас: шапка, вкладки, модалки, лоадеры
- Скопировать: tabs, modals, loading-indicator, (dropdown при нужде).
- Заменить: `SiteHeader` (+коллапс-поведение на мобиле сохранить 1:1), `.lab-tabs` → Tabs,
  `.modal-overlay/.modal` → Modal (React Aria: фокус-трап, Esc — бесплатно), `.spinner` →
  LoadingIndicator, `ZoomControl` (стили на utility-классы, логика без изменений).
- Осторожно: сворачивание шапки уже ловило мерцание (`overflow-anchor` — коммент в CSS) — не
  менять механику скролла; e2e-локаторы навигации скоупить `getByRole("navigation")` (урок №12).

### U3 — Страницы, карточки, смета-паттерны
- Скопировать: table, empty-state, pagination (задел под М1–М3), checkbox-checklist паттерн.
- Заменить: `.card`/`.grid-cards`/`.note`/`.divider`/`.lead-card`/`.locked`/`.checklist`/
  `.calc-sticky` (липкий итог сохранить sticky-поведение), страницы `app/{page,calc,estimate,
  estimates,lab,rooms,sovety,start,soon,e,p}` — вёрстка на utility-классы + UUI; `StyleQuiz`
  свотчи; `img.preview`; `.city-hits`; `.pulse-highlight` (оставить как локальную анимацию).
- Приёмка: визуальный проход всех маршрутов (скриншоты до/после), e2e зелёные.

### U4 — Чистка, канонизация, память
- Удалить мост U0 и все старые классы/токены из `app/globals.css` (остаются только импорты
  UUI + `brand.css` + действительно локальные хаки: zoom П4, overflow-anchor).
- `grep`-контроль: ни одного `var(--bg)`/`.btn`/`.chip`… в коде; сырые hex вне `brand.css` — 0.
- Переписать `.claude/rules/ui-rules.md`: реальные токены UUI (`text-primary`, `bg-brand-solid`…),
  запрет сырых цветов, паттерн «компоненты — из components/ui, не править сгенерированное».
- Память: ADR «Untitled UI React + палитра» в `decisions.md`; `core/architecture.md` (слой ui);
  `project-state.md`; уроки → `core/lessons.md`; `anti-patterns.md` §6 дополнить UUI-граблями.
- Запустить субагента `verify` (миграция >5 файлов) до `/memory-check`.

## Файлы к изменению (сводно; точечные списки — в подпланах при деплое)
- [ ] `package.json`, `postcss.config.mjs` — Tailwind v4 + депсы UUI (U0)
- [ ] `styles/**` (новое), `utils/cx.ts` (новое), `app/globals.css`, `app/layout.tsx` (U0)
- [ ] `components/ui/**` (новое, копии UUI) (U1–U3)
- [ ] `components/*.tsx` — все 17 (U1–U2)
- [ ] `app/**/*.tsx` — страницы (U3)
- [ ] `.claude/rules/ui-rules.md`, память (U4)

## Задачи
- [ ] U0 фундамент → деплой
- [ ] U1 примитивы → деплой
- [ ] U2 каркас → деплой
- [ ] U3 страницы → деплой
- [ ] U4 чистка + память → деплой, план completed

## Риски и страховки
- **React Aria ↔ React 19.1.1:** UUI собран под React 19.2; при капризах peer-deps — поднять
  react/react-dom до 19.2.x в U0 (минорный апдейт, e2e прикрывают).
- **`body { zoom }` × rem:** zoom масштабирует и rem — ожидаемо ок; проверка в U0 на 1920/2560
  и data-font-scale L–XXL. Провал → перевести масштаб на `font-size` html (только U0, отдельно).
- **Цели Метрики** привязаны к JS-событиям (TrackedSubmit и др.) — обёртки сохраняют события;
  ручная проверка целей после U1 (урок №9: цель = реальное действие).
- **e2e-локаторы** могут зацепиться за изменившиеся роли/тексты — чинить локаторы, не UI
  (урок №12); тексты не меняем.
- **Каждый подплан — атомарный деплой** с бэкапом и авто-откатом `./deploy.sh` (CI, не DEV-VM —
  урок №1); прод никогда не остаётся в полусмигрированном состоянии дольше одного подплана,
  мост U0 гарантирует сосуществование старого и нового CSS.
- Функциональность не удаляем без явного «да» владельца (урок №8) — миграция 1:1 по поведению.

## Критерии приёмки (мастер)
- [ ] Все маршруты переведены; старые классы/токены удалены (grep-чисто)
- [ ] `pnpm typecheck && pnpm lint && pnpm test && pnpm build` + e2e — зелёные после каждого U
- [ ] Палитра соответствует таблице решения (терракота-бренд, stone-нейтраль, крем-фоны)
- [ ] Цели Метрики работают (ручная сверка после U1 и U4)
- [ ] Не задеты файлы вне scope; VPN-нода не тронута

## Definition of Done — память (без этого `completed` запрещён)
- [ ] ADR: выбор Untitled UI React + палитра-гибрид → `decisions.md`
- [ ] `core/architecture.md` (ui-слой: Tailwind v4 + React Aria + components/ui) обновлён
- [ ] `ui-rules.md` переписан под UUI-токены
- [ ] `project-state.md` — снимок переписан
- [ ] Уроки → `core/lessons.md`; `/memory-check` выполнен, audit «чисто»

## Лог выполнения
- 2026-07-31 — план создан (draft); ресёрч: клон untitleduico/react изучен (theme.css: 15 шкал,
  brand-оверрайд штатный; free-набора хватает на U0–U3; PRO не требуется)

## Completion summary
[при завершении]

### Уроки (ОБЯЗАТЕЛЬНО)
[при завершении]

## Follow-up work
- [ ] М1–М3 (ядро сметы) строить сразу на UUI Table/EmptyState — внести в MASTER-cost-first
- [ ] Решение владельца: нужен ли PRO ($349, once) ради готовых секций/страниц

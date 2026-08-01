---
description: UI-правила remlab — Untitled UI (Tailwind v4 + React Aria), палитра-гибрид
paths:
  - "app/**/*.tsx"
  - "app/**/*.jsx"
  - "components/**/*.tsx"
  - "components/**/*.jsx"
  - "**/globals.css"
---

# UI-правила (Untitled UI, план uui-migration)

Дизайн-система — **Untitled UI React** (copy-paste): примитивы скопированы в
`components/base/**` и `components/application/**` (React Aria + Tailwind v4).
Токены: `styles/uui/theme.css` (семантика UUI) + `styles/brand.css` (палитра-гибрид:
терракота-бренд от #b06a4a, stone-нейтраль, крем-фоны). Обновление компонентов — копированием
из github.com/untitleduico/react (main), правки копий — минимальные (линт/строгий TS).

## Дизайн-токены
- Только **семантические** токены/утилиты UUI: `bg-primary`, `bg-brand-solid`, `text-primary`,
  `text-tertiary`, `text-fg-quaternary`, `ring-primary`, `border-secondary`, `text-error-primary`…
  В inline-style — `var(--color-*)` (напр. `var(--color-border-secondary)`).
- ЗАПРЕЩЕНЫ сырые цвета (`bg-white`, hex, `text-gray-*`) и старые токены (`--bg`, `--accent`…,
  удалены в U4). Бренд меняется ТОЛЬКО в `styles/brand.css`.
- Второго акцента нет: прежний «шалфей» упразднён (гибрид U0); смысловой зелёный — только
  `success`-токены.

## Компоненты
- Кнопка — `components/base/buttons/button` (`color`: primary/secondary/tertiary/link-gray…,
  `size`, `href` для ссылок — клиентскую навигацию даёт RouterProvider в `components/Providers.tsx`).
  Кнопки-пилюли «+ добавить…» — `size="sm" className="rounded-full"`.
- Поля — `base/input`, `base/textarea` (RAC: `onChange` отдаёт СТРОКУ, не event); селекты —
  `base/select/select-native` (нативный select, лучше на мобиле); чекбоксы — `base/checkbox`;
  чипы-переключатели — наш `base/chip` (ToggleButton); бейджи — `base/badges`; подсказки —
  ТОЛЬКО наш `base/hint/hint-popover` (тап; RAC Tooltip не работает на тач-экранах); модалки — `application/modals`
  (`ModalOverlay isOpen isDismissable` + `Modal` + `Dialog`); лоадер — `application/loading-indicator`.
- Числовые поля — наш `components/calc/NumInput` (строка-буфер «1,2», UUI-классы).
- В **серверных** формах (server actions, без JS) — нативные `<input>/<select>` с utility-классами
  в стиле InputBase (см. `app/e/[id]/page.tsx: inputCls`); `name` обязателен.
- Не править скопированные примитивы под задачу — оборачивать или расширять props.
- Иконки — из одного набора (`@untitledui/icons`); разовые SVG — inline, `stroke="currentColor"`.

## Раскладка и адаптивность
- Mobile-first. Раскладочные хелперы проекта (`.container`, `.stack`, `.row`, `.card`, `.note`,
  `.eyebrow`, `.muted`) живут в `app/globals.css` НА ТОКЕНАХ UUI — использовать их, не плодить копий.
- Масштаб П4 (`body{zoom}` + `data-font-scale`) — не трогать без отдельного плана.
- Тап-зоны ≥44px (кнопки-крестики: `min-h-11 min-w-11`).

## Состояния и аналитика
- Каждый экран: `loading` / `error+retry` / `empty` / `success`.
- Цели Метрики — на РЕАЛЬНОЕ действие (ADR-0036); при замене кнопок события сохранять 1:1,
  новые цели не вешать без решения владельца.

## Грабли (см. также anti-patterns.md §6–7)
- RAC `onChange`/`onPress` вместо DOM-событий; `isDisabled`/`isLoading`, не `disabled`.
- `label` у Badge/Checkbox — проп, а `aria-label` Badge НЕ пробрасывает (оборачивать span'ом).
- Пустые `interface X extends Y {}` в копиях UUI валят CI-гейт (`no-empty-object-type`) → `type X = Y`.
- Препролёт Tailwind гасит маркеры списков и рамки нативных полей — контентные `ol/ul` чинит
  правило в globals.css; нативные поля всегда с классами.
- Element-резеты (`a{...}`, `h1{...}`) вне `@layer` перебивают ЛЮБЫЕ утилиты — новые резеты
  в globals.css не добавлять (кейс: чёрный текст href-кнопок из-за `a{color:inherit}`).

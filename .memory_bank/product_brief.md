---
tier: 1
topic: product
scope: Бизнес-контекст — зачем продукт, для кого, что в scope
tier2: "../docs/cjm-ux-v0.2.md"
updated: 2026-07-01
importance: high
source: _intake/brief
status: working
source_of_truth: supporting
last_verified: 2026-07-01
review_after: ""
---

# Product Brief — remlab (remont-lab)

## Проблема
Человек хочет обновить гостиную/спальню без капитального ремонта, но не понимает: что купить, как сочетать цвет/свет/мебель, сколько это будет стоить и где взять товары.

## Целевая аудитория
B2C. Сегменты: **A** «хочу обновить комнату» (главный), **B** «хочу понять стоимость» (Stage 1B), C «часть сделаю сам», D «повторить интерьер с фото» (позже), E «ремонт под ключ» (позже).

## Цель / ценность
Быстро дать первую ценность: AI-preview обновлённой комнаты + 3–5 идей + preview товаров + диапазон бюджета → продать полный **room pack** (полный список товаров, цены, ссылки, чек-лист, план, PDF). Формула Stage 1: **фото → style cards → AI-preview → ограниченный free-результат → paywall → room pack → workspace**.

## Scope — что входит
Stage 1 (landing, короткий flow, гостиная/спальня, style cards, AI-preview, free preview, paywall, paid room pack, workspace, PDF, базовый каталог) + Stage 1B (сценарий стоимости через Renovation Cost Engine).

## Scope — что НЕ входит
Repeat-reference как главный сценарий, кухня/ванная, точная смета, чертежи, 3D-редактор, сложные инженерные советы, подрядчики, маркетплейс внутри, полная товарная выдача бесплатно.

## Метрики успеха
Прохождение укороченного flow (10 шагов), конверсия free→paid, воспринимаемое совпадение товар↔картинка по hero (цель >~60%), латентность генерации <45с (paid), удержание маржи на кадр.

## Позиционирование (из рыночного исследования RU/UK)
Не «AI-генератор картинок», а **consumer renovation copilot** — доведение от неуверенности до покупки/ремонта. Moat = last mile (локальный каталог/цены + честные объяснения + execution), а не генерация. Оценки: RU 8/10, UK 7/10, две страны ~8/10 при «общий AI-core + локальный execution». Детали: `core/market.md` → `../docs/market-research-ru-uk.md`.

## Ссылки
- CJM/UX: `../docs/cjm-ux-v0.2.md`
- Тех-спека: `../docs/tech-spec-ts-stack.md`
- Рынок/позиционирование: `core/market.md` → `../docs/market-research-ru-uk.md`
- Решения: `../docs/DECISIONS.md`

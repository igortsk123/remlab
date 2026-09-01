---
tier: 1
topic: demo-planner
scope: Демо-планировщик для партнёра — интерактивная расстановка и AI-фото
tier2: "../domain/viz-fidelity-playbook.md"
updated: 2026-09-01
importance: high
source: manual
status: working
source_of_truth: canonical
last_verified: 2026-09-01
---

# Демо-планировщик — Tier 1 сводка

**Что это:** демо `https://remont-lab.online/test/flat215-demo/` (партнёру): план квартиры (чертёж №180,
76,5 м²) → расстановка гостиной → кадр с товарами → отправка подборки. Страница —
`tools/scout/flat215-demo/index.html`, сборка — `flat215_demo.py`, публикация — `publish_demo.sh`
(в `/opt/remlab/test/`; спрайты переживают выкатку — ADR-0150).

- **Вкладки:** «План квартиры» · помещения (работает Гостиная; Кухня/Спальни серые). Варианты —
  подразделы сверху; кадры и подборка живут В РАЗРЕЗЕ варианта (`vid`).
- **Кадр (ADR-0139/0140/0149):** серверный рендер 3D-сцены из мешей БЕЗ ИИ (`scene3d_frame`);
  считает DEV через ssh-туннель, фолбэк — контейнер `remlab-draft` (правится `docker cp`; ОБА
  держат код в памяти — перезапускать после правок). Два кадра из ПРОТИВОПОЛОЖНЫХ углов,
  объектив 72°, вынос за стену до 200 см; право камеры = `fwd × up` (`services/planner-solver/planner/scene.py`, иначе
  кадр зеркалит план). ТВ — `draft_render.tv_spec` (`--tv-selftest`).
- **План — только схемы (ADR-0149):** накладка `topsprites/<sid>.png` снята; спрайты остались
  в 3D-сцене и серверном кадре.
- **Комплекты (ADR-0151):** «стул 2» берёт товар базовой роли; покупок = `ceil(слотов /
  sku.pack)`, `pack` — из `pack_qty.lookup()`.
- **Управление (ADR-0140):** поворот с наездом разрешён; тап — ±90°, долгий — drag.
- **Отправка себе:** контакт (Telegram/MAX/SMS) → `/api/share`, очередь
  `/opt/remlab/test/share/_queue`; токенов ботов на проде нет.
- **Наличие (ADR-0144):** сборка снимает не продающееся (`drop_unavailable` →
  `catalog_media.media`), не дожидаясь ночного лечения; ссылки ПАРТНЁРСКИЕ.
- **Проверка страницы:** прогон функций из `index.html` на мини-DOM; `str.replace` без assert запрещён.
- **Планы:** `plans/viz-regional-masks.md` (ADR-0127) · `plans/demo-planner-structure.md`.

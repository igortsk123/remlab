---
tier: 1
topic: goals-furnish-fit
scope: Цели продукта — меблировка/замена по одному фото с проверкой «влезет/не влезет»
tier2: "../goals-one-photo-furnish-fit.md"
updated: 2026-07-09
importance: high
source: manual
status: working
source_of_truth: supporting
last_verified: 2026-07-09
review_after: ""
---

> ⚠️ ADR-0016: **v0.4 «Смета-first»** — `plans/MASTER-cost-first.md`; ниже — v0.3.

# Goals — Tier 1: одно фото → подбор мебели

## Суть
Одно фото комнаты → детект объектов → «что заменить/обставить?» → товар из каталога в правильном
МАСШТАБЕ + вердикт «влезет / велик на N см» + совет «убери стол — встанет». Козырь vs First Chair:
они вставляют вслепую, мы знаем размеры зоны И товара. ±10% ок; недопустимо 1.5 м в зону 1 м.

## Этапы
- **Одно фото (СЕЙЧАС), видимая зона:** A — заменить один объект + fit-check по footprint;
  C — «освежить всё»: убрать мебель → замер ВСЕЙ комнаты → вписать набор из каталога.
- **10-сек видео (ПОЗЖЕ):** ремонт/полный план (multi-view, истинная Г).

## Принципы (owner 2026-07-06)
- Само-проверяющий движок: мульти-замер + приоры + self-check + confidence/provenance;
  настройка — на датасете разных комнат.
- Human-in-the-loop: редактируемые Ш/В/Г; правка человеком снимает нагрузку на точность.
- Словарь детекции и приоры — из фидов Гдеслон; детектор не «чиним кодом».
- Показываем только крупное; мелочь — «+предметы:N». Цифры рисует наш код, не image-gen.

## Стек (рабочий vs план)
A4+solvePnP (масштаб), Grounding DINO tiny (детектор; Mask R-CNN — ранние опыты), Depth
Anything V2 + A4-якорь, SegFormer, SAM 2 + LaMa (fal.ai). SD-inpaint — план, в коде НЕТ.
Из 1 фото надёжны ширина+позиция footprint; Г — каталог/видео-тир.

## Статус (2026-07-09; код ВНЕ репо `/home/pakar/mltest/`)
v1 готово: замер `run_f3.py` (стулья 104–109 vs 108), план пола `run_plan.py`, fit-check
`fit_check.py`+`run_fit.py` (Shapely), подбор `product_match.py`/`run_match.py` (демо-каталог),
вставка в масштабе `run_viz.py` (SAM2+LaMa); дальше — confidence, датасет, фотореализм.

**Tier 2:** `../goals-one-photo-furnish-fit.md`. План fit — `../archive/plans/MASTER-roadmap.md`.

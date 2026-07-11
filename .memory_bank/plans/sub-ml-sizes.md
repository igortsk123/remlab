---
workstream: ml
slug: sub-ml-sizes
title: "ML: стабилизация замера (контур, площади пола, footprint)"
status: draft
created: 2026-07-11
updated: 2026-07-11
completed:
---

## Цель
Замер стабилен: ≥80% объектов golden в ±10%, обе площади пола в ±10%, 0 жёстких фейлов, прогон бит-в-бит. Ф1 из [[MASTER-roadmap]] — вход для fit-check и Э5.

## Источник задачи
«ML ∥» из [[commercial-master-plan]] (2026-07-11): габариты и площадь пола плавают. Предусловие: код из `/home/pakar/mltest/` перенесён в `ml/` (Э0 шаг 1, `sub-e0-stopkran`); нет переноса — сначала он (без рефакторинга), в mltest НЕ работать.

## Прочитай сначала
1. `plans/MASTER-roadmap.md` — принципы 1–7 (особенно 6 — человек-фолбэк, 7 — две площади); «СТЕК 2026» узел 2.
2. `plans/`: `unified-measurement-pipeline.md` (реестр методов — НЕ переоткрывать провалившееся), `object-size-reference.md`, `room-measurement-a4.md`, `round-oval-footprint.md`, `accuracy-upgrade-fal.md`.
3. Код (после переноса): в `ml/run_plan.py` RANSAC-контур (`seq_ransac`, углы `isect`, фолбэк `contour_ok`) и эллипс-footprint УЖЕ есть inline — выносить, НЕ строить заново. Опоры: `Solver.floor()`, `refine_a4`, `fit_in_zone`, `CATALOG` (avg/tol/min/max).
4. `guides/execution-playbook.md` — правила чекпоинтов.

## Скоуп — что входит
- Golden-набор с рулеткой владельца; регресс-скрипт; контур + две площади; footprint; итерационный цикл с показом владельцу (Задачи A–E).

## Скоуп — что НЕ входит
- Видео-тир (Ф7), мультивью; свитчи глубины MoGe-2/Metric3D (решение владельца).
- Фотореализм вставки (Ф4+), подбор (Э2), интеграция в Next.js (Э5/Ф8); высоты окон/дверей/эркера сверх имеющегося.

## Файлы к изменению
`ml/*` — после переноса (в репо пока НЕТ). НЕ трогать `geometry_solver.py` (`solve_walls` — vision-рёбра, не контур).
- [ ] (новые) `ml/golden/` (README.md, `rooms/<id>/` photo+truth.json, `cache/`), `ml/run_regress.py`, `ml/contour.py`, `ml/footprint.py`
- [ ] `ml/run_plan.py` — оркестрация: inline-код → вызовы contour/footprint
- [ ] `ml/object_catalog.py` — дозаполнить `d` для классов golden
- [ ] `.memory_bank/plans/`: unified-measurement-pipeline, MASTER-roadmap (Ф1), commercial-master-plan — реестры/статусы

## Задачи

### A — Golden-набор
- [ ] README: съёмка (A4 на голом полу целиком в кадре; фото оригиналом — мессенджер режет EXIF; линия стена-пол ≥2 стен); мерить: пол Ш×Г, 3–5 предметов Ш×Г×В, ширины зон; схема `truth.json`: `{room_id, phone_model, floor:{w_cm,d_cm}, objects:[{name,w_cm,d_cm,h_cm,shape:"rect"|"round"|"oval"}], zones:[{name,w_cm}]}`.
- [ ] ⏸ Чекпоинт №1 → получить 10–15 комнат.
- [ ] Разложить по `ml/golden/rooms/`; валидация в run_regress: поля по схеме, границы CATALOG min/max.

### B — Регресс
- [ ] Замер каждой комнаты (функцию вынести из run_plan.py, НЕ копипастить) vs truth. Метрики: ошибка % по объектам, % в ±10%, max, жёсткие фейлы (`fit_in_zone` по измеренным ≠ по эталонным, пара объект-зона).
- [ ] Отчёт `ml/golden/report/latest.{md,json}` (json БЕЗ timestamp — ради diff) + overlay: план поверх фото, объект и след ОДНИМ цветом.
- [ ] Детерминизм: fal/OpenAI-вызовы кэшировать по хэшу входа (`ml/golden/cache/`); сеть — только `--refresh`; `np.random.seed(0)` сохранить.

### C — Контур
- [ ] Вынести в `ml/contour.py`: точки линии стена-пол (маска SegFormer + `in_furn`) → `seq_ransac` в метрике (`Solver.floor`) → углы `isect` → полигон.
- [ ] Углы амодально (эркер/перекрытые — пересечением, не «стык встык»); полная = полигон стен (Shapely), свободная = проекция маски пола — ДВА числа, НЕ вычитанием.
- [ ] Линия за мебелью → достроить прямой + `needs_review` (принцип 6). SegFormer не тянет → fal-сегментация (SAM / Mask2Former), в кэш.
- [ ] run_regress → ⏸ Чекпоинт №2. В блок D — после «принято».

### D — Footprint
- [ ] Перенести в `ml/footprint.py`: ширина+позиция = проекция низа рамки; круглые/овальные — `cv2.fitEllipse`+`approxPolyDP`, лучи ∩ плоскость z=h (из каталога) → эллипс в метрике → диаметры; поле `shape`.
- [ ] Глубина прямоугольных = `CATALOG[class]["d"]` (avg), понижение conf, границы tol/min/max.
- [ ] Неуверенно → `needs_review: true` + «вероятно <имя>, Ш×Г×В — поправь»; в ±10% не засчитывать (отдельная метрика).
- [ ] run_regress → ⏸ Чекпоинт №2.

### E — Итерации
- [ ] ОДНО улучшение → run_regress → ⏸ показ → «принято/ещё». По гейту: ⏸ Чекпоинт №3 → MASTER-roadmap Ф1 🔶→✅ с датой; реестры (методов, подпланов).

## Гейты
- [ ] `python3 ml/run_regress.py --all` — код 0; в `latest.json`: `pct_objects_within_10>=80`, `hard_fails==0`, `pct_rooms_both_areas_within_10>=80`.
- [ ] Два прогона подряд → `diff` двух `latest.json` пуст; overlay для каждой комнаты (`ls ml/golden/report/`).
- [ ] `node tools/memory-audit.mjs` — чисто.

## Чекпоинты владельца
- ⏸ №1 (блок A): инструкция + «что померить», пример truth.json. Всё понятно? сколько комнат? срок? Минимум — 5.
- ⏸ №2 (КАЖДАЯ итерация C/D/E): таблица (±10%, обе площади, 3 худших) + 2–3 overlay. «Узнаёте комнату? Контур совпадает? Принято/ещё?» Без ответа — стоп.
- ⏸ №3 (финал): «было → стало» по гейту. «Закрываем Ф1 — размеры стабильны для "влезет/не влезет"?»

## Если пошло не по плану
- **Нет 10 комнат** → старт на 5 с пометкой; <5 — эскалация.
- **A4 не детектится** (`refine_a4`) → переснять; системно → Gemini seed → cornerSubPix.
- **RANSAC не находит линию** → маска пола через fal; стена не видна → достроить + `needs_review`, длину спросить. НЕ выдумывать молча.
- **Недетерминизм / расходы fal** → проверить кэш (сеть — только `--refresh`) и seed; одна комната, diff промежуточных json.
- **Метрика не растёт 3 итерации на классе** → human-fallback; владельцу выбор: принять или копать.

## Критерии приёмки
- [ ] Гейты зелёные на golden ≥10 комнат (старт от 5) с валидными truth.json.
- [ ] Контур визуально совпадает с фото (владелец, №2); круглые/овальные — эллипсом.
- [ ] Чекпоинт №3 принят; статус Ф1 и реестр методов обновлены.

## Definition of Done — память (без этого `completed` запрещён)
- [ ] Memory Bank: `core/*`, `decisions.md`, `project-state.md`; golden-регресс виден в decision tree (INDEX)
- [ ] `/memory-check` выполнен, audit «чисто»; статус в реестре [[commercial-master-plan]] обновлён

## Лог выполнения
- 2026-07-11 — создан (draft)

## Completion summary

## Follow-up work
- Видео-тир Ф7 (VideoScene); свитч глубины MoGe-2/Metric3D V2 (решение владельца).
- Golden → eval-база Э6 (`sub-e6-eval`), гейт Э5 (`sub-e5-fit-integration`); перцентили фида → CATALOG (после Э2).

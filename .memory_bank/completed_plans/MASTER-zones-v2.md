---
workstream: layout
slug: MASTER-zones-v2
title: МАСТЕР — свод №8 (внешний рефери, v2 согласована): dining island, экран ТВ, зеркала L, гейты цепочки зон
status: completed
created: 2026-08-14
updated: 2026-08-14
completed: 2026-08-14
---

## Цель
Внедрить свод №8 в согласованной редакции v2 (внешний ИИ-рефери ↔ наш ответ с пруфами):
dining через каскад классов island→edge с объяснимым выбором, паспортная эргономика вместо
хардкодов, виртуальная плоскость экрана ТВ, зеркала L-дивана в боевом пути, гейты
«собственного качества» зоны перед not_worse, инструментация новых осей, регресс №253+.

## Источник задачи
Свод №8 v1 (Google Drive, 14.08) → наш ответ с пруфами
(`_intake/reply-to-referee-svod8.md`, опубликован `/test/reply-to-referee-svod8.md`) →
**свод №8 v2** (Google Drive, 14.08): рефери принял поправки. По ADR-0077 вердикты рефери
внедряются по умолчанию.

## Критическая оценка (итог сверки v1 → v2)
**Рефери в v2 ОТОЗВАЛ** (по нашим пруфам): «score награждает заполнение» (скор — только
штрафы, `score.py:34,88`); «island or nothing» для optional dining (ломал планку покрытия);
скалярный `score_with − score_without` (уроки 236/161/208 — вместо него именованные оси
и векторный `not_worse`); полный routing-граф entry_ports (наша достижимость+эрозия
`validate.py:201-250` достаточна); искусственные KPI «% island по метражу».

**Рефери ПОДТВЕРДИЛ, принимаем:** корень wall-hugging — паспорт объявляет эргономику
(`operational_envelope_cm: 90`, `edge_per_diner_cm`, `seats_by_area` —
`templates.json:251`), которую код не читает (pullout 55 захардкожен `clearances.py:79-80`,
места — `template.py:1375`); выбор island/edge — лексикографический приоритет КЛАССОВ после
hard-гейтов, не вес; edge — самостоятельный режим с асимметричным envelope (сторона у стены
без стула — уже так), не «сломанный island»; зеркала L в шаблонном пути реально не
перебираются (`candidates.py:600-607` — только поштучный путь); недостающий слой цепочки
зон — «зона сама по себе качественна?» (eligibility / self-quality / role-redundancy) ДО
`not_worse`; новые оси (residual_fragmentation, visual_balance) — сначала только измерять,
пороги позже отдельным ADR; 90 см — внешние пруфы Room&Board (36″) и Paolo Moschino (90–100).

**Ключевой принцип v2 (регресс-инвариант):** покрытие dining не снижаем; но если полный
island hard-valid — edge не выигрывает «тихо»: либо island, либо явная `fallback_reason`.

## Сверка конфликтов
| Существующее | Риск | Решение |
|---|---|---|
| Планка dining ≥196/252 «только вверх» (ADR-0096/0097) | каскад island уронит покрытие | Гейт каждого пакета: dining ≥196; edge-фолбэк легален; сторож «тихого edge» вместо запретов |
| `zone_priority` — единственный источник порядка (ADR-0094) | статусы зон создадут двоевластие | Поле `status` внутри того же блока; `fill_policy`-дубль (`zones.json:715`) снести (пакет A) |
| Обеденная за спинкой floating-дивана легальна (ADR-0078) | «all-side access» её запретит | island-валидность по доступным сторонам региона; спинка дивана = легальная граница |
| R≥260 → dining обязательна (ADR-0092), `dining_region_m2` (ADR-0096) | — | Сохраняются (v2 §11), становятся видимыми через `why_selected` |
| Урок 236/161 (бонусы проигрывают порогам) | mode_rank как вес повторит грабли | `dining_mode_rank` — лексикографический tie-break классов, НЕ вес (v2 §6.2) |
| Второй проход при fill<30 (`zones.py:728-761`) | v2 §1.1: «fill<30» — не основание принять зону | Второй проход РАСШИРЯЕТ поиск кандидатов, но приём — только через новые гейты (пакет F) |
| Планы: `seating-template-ladder` (in_progress), `template-library-v2` (draft), `entry-low-storage` (draft) | пересечение | TEMPLATE_GAP питает template-library-v2; entry-low-storage перепроверить после C; лестницу посадки не трогаем |
| Нумерация №1–252 стабильна (правило владельца) | новые сцены собьют номера | Только append №253+ (пакет H) |
| Solver-speed | зеркала ×2 кандидатов | Замер времени экзамена до/после E; бюджет ≤1.5× |

## Пакеты (порядок согласован с рефери v2 §17; гейт каждого: экзамен 252/252 чистых, медиа 252/252, dining ≥196, сторожа зелёные, rules_audit 0, коммит + галерея)

### A — Dining passport wiring (+ санация данных)
- Паспорт становится source of truth: код читает `seats_by_area` (вместо хардкода
  `template.py:1375`), `edge_per_diner_cm`, `operational_envelope_cm` (вместо pullout 55
  в `clearances.py:79-80`). Параллельную clearance-модель НЕ заводить (v2 §4).
- Island-валидность: `table edge → wall/furniture/blocking zone` ≥ паспортного envelope
  по всем рабочим сторонам. Edge — асимметричный envelope: пристенная сторона без стула и
  без 90 см, активные стороны — envelope обязателен.
- Санация: снести `zones.json → fill_policy` (устаревший дубль zone_priority + мёртвый
  «algorithm»); `floor_occupancy_policy` остаётся диагностикой; registry/rules_audit чисто.
- **DoD:** паспортные поля реально читаются (тест-сторож); экзамен чистый; dining ≥196.

### B — Dining explainability (до правок выбора — иначе замеры слепые)
- В артефакт и экспорт: `mode` (full_island/compact_island/round_island/edge),
  `island_feasible` (bool: хоть один island-шаблон проходит hard+envelope+route),
  `island_reject_reasons`, `why_selected` (preferred_coverage / mandatory_residual_R /
  region_capacity / edge_fallback_*), `fallback_reason`; словарь причин — v2 §11.
- Прогнать 9 сцен-кандидатов рефери боевым солвером и ответить на 4 вопроса
  (island существует? на каком гейте режется? меняет ли envelope 90? почему edge выиграл?):

  | приоритет | планы | м² |
  |---|---|---|
  | 1 (визуально очевидные) | №184, №193, №217 | 45.4 / 45.3 / 57.5 |
  | 2 | №160, №164, №165, №120 | 35.4 / 35.4 / 35.2 / 27.9 |
  | 3 (перепроверить door/circulation) | №100, №108 | 22.8 / 22.8 |
- `export_plans_ai.py`: новые поля в plan-NNN.json/md; `_templates` + variant схемы.
- **DoD:** по экспорту различимо «edge потому что island не проходит» vs «баг генерации»;
  отчёт по 9 сценам в логе плана.

### C — Island-vs-edge selection (каскад классов)
- Каскад среди hard-valid вариантов: FULL_ISLAND → COMPACT_ISLAND → ROUND/OVAL_COMPACT
  (реализовать паспортную схему `dining_round_compact` по форме региона) → EDGE.
  Механизм — приоритет класса кандидатов / лексикографический tie-break ПОСЛЕ hard-гейтов;
  ни весов, ни процентов по метражу (v2 §3, §6.2).
- Сторож: **0 сцен с «тихим edge»** (island_feasible=true ∧ mode=edge ∧ fallback_reason пуст).
- TEMPLATE_GAP: каскаду нужен класс, шаблона нет → структурное событие
  `{type, zone, requested_mode, room_class, region_cm, reason}` в артефакт (формализация
  stdout NOTPL); агрегатор → `missing_templates.md`; следить за классами: compact/round
  island, large-room dining, mirror L-seating, large-room communication (v2 §13).
- Продуктовые триггеры (R≥260, dining_region_m2, sacrifice ADR-0097) не трогаем.
- **DoD:** dining ≥196 (не упало); тихий edge = 0; missing_templates.md сгенерирован;
  медиана «стол↔стена» среди island-планов ≥ envelope.

### D — Media virtual screen
- Паспорт media: `virtual_screen_plane` / `screen_projection` (ширина от ниши стенки /
  `diag_from_stand` в `tv.py`), высоты; отдельного предмета «телевизор» НЕ создавать.
- Hard `SCREEN_OVER_WINDOW` (H0): проекция экрана перекрывает окно → reject постановки
  (текущий `WINDOW_BLOCKED` ловит только носитель h>80 в 10 см).
- Единый замер: `seat_axis_origin → screen_plane` везде — сейчас три разных
  (score полигоны / validate front_gap / экспорт по центрам `solver_run.py:756-760`).
- **DoD:** 0 планов с экраном на окне; `_tv.viewing_distance_cm` от оси посадки; severity/registry.

### E — L-sofa mirror + точечный bbox-аудит
- `place_template` перебирает `corner_left` оба (если `not corner_side_fixed`); сравнение
  существующими hard + quality-гейтами, нового скора нет; шезлонг на low-traffic (ADR-0095).
- Точечный аудит остаточных bbox-мест (access_zone `geometry.py:102-134`, замеры
  validate/score) — чинить только влияющие, полигонную геометрию не переписывать (v2 §9).
- Экспорт `corner_left` из Placement (убрать IoU-подбор `solver_run.py:729-741`).
- **DoD:** оба зеркала встречаются в экзамене (доля LEFT/RIGHT в отчёте); время ≤1.5×.

### F — Zone-chain gates (недостающий слой цепочки)
- Статусы в `zones.json → zone_priority.status`: seating/media REQUIRED, dining PREFERRED
  (от 15 м²), storage PREFERRED, decor OPTIONAL.
- Перед существующим `not_worse` (`zones.py:598-609`) — три гейта (v2 §7):
  1. ZONE_ELIGIBILITY: статус/продуктовый триггер/документированная роль; «есть место» и
     «fill<30» — не основание (второй проход только расширяет поиск);
  2. ZONE_SELF_QUALITY: зона сама валидна (dining envelope+mode, storage front access,
     decor не маскирует зонирование);
  3. ROLE/REDUNDANCY: роль уже закрыта и новой документированной роли нет → reject
     (актуально для повторных storage/decor).
- **DoD:** гейты в данных+коде со сторожами; экзамен чистый; «глупых» сцен не больше базовой.

### G — Инструментация новых осей (только измерение)
- `residual_fragmentation` (плохие остаточные карманы после добора зоны) и `visual_balance`
  (центроиды зон, масса у периметра, пустая половина) — считать и экспортировать по всем
  сценам БЕЗ порогов и весов; распределение → решение о пороге отдельным ADR (v2 §6.3–6.4).
- Проверка топологии «стул выдвинут пересекает маршрут»: повторно использовать
  эрозию/достижимость с dining-envelope как препятствием (ACTIVE_DINING_STATE, v2 §8);
  если после A класс закрыт автоматически — зафиксировать и ничего не делать.
- **DoD:** метрики в артефакте/экспорте; гистограммы в логе плана; порогов не введено.

### H — Regression expansion №253+
- Append-сцены: вытянутые 1:1.7/2.0/2.3, 2 двери, дверь+балкон, 2–3 окна, окно на
  медиастене, профили dining required/forbidden, зеркальные L. Номера №1–252 не трогаем.
- Планки/сторожа по расширенному набору; старые планки на №1–252 неизменны.
- **DoD:** экзамен по полному набору чистый; галерея опубликована, номера стабильны.

## Порядок
**A → B → C → D → E → F → G → H** (v2 §17). Каждый пакет — свой прогон, коммит,
публикация галереи (`/test/acceptance-plans/`), запись в лог плана.

## Скоуп — что НЕ входит
- Снижение покрытия dining; проценты island/edge по метражу (отклонено v2 §3).
- Полный routing-граф entry_ports (отозвано v2 §8).
- Скалярный marginal score, новые веса за геометрию (отозвано v2 §6).
- Новые числовые пороги кроме паспортного envelope 90 (пруфы Room&Board/Moschino, v2 §15).
- Состав сетов/обогащение компоузера; open-plan; свободные повороты; новые SKU.

## Файлы к изменению (по пакетам)
- [ ] `services/planner-solver/rules/templates.json` — A (dining читаемый), D (screen_plane)
- [ ] `services/planner-solver/rules/zones.json` — A (снос fill_policy), F (status)
- [ ] `services/planner-solver/rules/severity.json` + `registry.json` — C/D коды, A санация
- [ ] `services/planner-solver/planner/clearances.py` — A (envelope из паспорта)
- [ ] `services/planner-solver/planner/template.py` — A/C (place_dining, каскад), E (зеркала)
- [ ] `services/planner-solver/planner/zones.py` — C (TEMPLATE_GAP), F (гейты)
- [ ] `services/planner-solver/planner/validate.py` — D (SCREEN_OVER_WINDOW), E (bbox-аудит)
- [ ] `services/planner-solver/planner/quality.py` — G (новые оси), D (единый замер)
- [ ] `services/planner-solver/planner/geometry.py` — E (access_zone по полигону)
- [ ] `tools/scout/solver_run.py`, `tools/scout/export_plans_ai.py` — B (объяснимость), G
- [ ] `tools/scout/template_gaps.py` (новый) — C (агрегатор missing_templates.md)
- [ ] `tools/scout/acceptance-scenes.json` — H (append №253+)
- [ ] `services/planner-solver/tests/test_contour_features.py` + новые тесты — сторожа пакетов

## Критерии приёмки мастера (v2 §16)
- [ ] Экзамен чистый (252/252; после H — весь набор), медиа 252/252
- [ ] Dining ≥196/252 на каждом пакете; edge остаётся легальным фолбэком
- [ ] Паспортный `operational_envelope_cm` реально читается кодом (тест)
- [ ] 0 сцен «тихого edge» (island feasible, а причина фолбэка не названа)
- [ ] 0 планов «экран на проекции окна»; дистанция — ось посадки → плоскость экрана
- [ ] Оба зеркала L перебираются в шаблонном пути; время экзамена ≤1.5×
- [ ] `why_selected` присутствует для каждой dining-постановки; missing_templates.md есть
- [ ] По 9 сценам-кандидатам рефери дан ответ A–D (island был? где резался? что изменил envelope?)
- [ ] rules_audit 0; новые числа только с пруфами

## Definition of Done — память (без этого `completed` запрещён)
- [ ] ADR на мастер (свод №8 v2: принято/отозвано) + ADR на содержательные пакеты
- [ ] `core/layout.md` обновлён (каскад dining, screen plane, зеркала, гейты цепочки)
- [ ] Уроки → `core/lessons.md`; `/memory-check`, audit «чисто»

## Лог выполнения
- 2026-08-14 — план создан (draft) по своду №8 v1; разведка кода/памяти, ответ рефери с пруфами.
- 2026-08-14 — пакеты A–D исполнены (d5880d1, bc54dff, ad9cb24, ad098c6): dining-паспорт в коде, объяснимость, каскад island→edge (dining 196 честных, режимы 36/48/112, тихий edge 0), экран+вейвер +tvw (медиа 252); планка dining ребейс 210→196 (ADR-0099, брак «экран на окне» вскрыт).
- 2026-08-14 — получена v2 рефери (принял поправки, отозвал 4 рекомендации, дал 9 сцен-кандидатов);
  план переработан под согласованную редакцию: пакеты A–H, каскад классов вместо весов,
  island_feasible вместо процентов, гейты цепочки зон.

## Completion summary (2026-08-14)
Все 8 пакетов исполнены за один проход (коммиты d5880d1, bc54dff, ad9cb24, ad098c6,
60a766b, 8200174, +G, bd27aac). Итог: **269/269 чистых** (252 базовых + 17 новых сцен),
медиа 269/269 (3 явных вейвера +tvw), dining 196/252 базовых + 11/17 новых, режимы
36 full_island / 48 compact_island / 112 edge, тихий edge 0, rules_audit 0, тестов 154.
Ключевые решения: ADR-0098 (мастер), 0099 (экран+вейвер+ребейс планки 210→196 —
каузальный пруф брака «экран на окне»), 0100 (зеркала L, статусы зон), 0101 (оси, №253+).
9 сцен рефери: 8/9 остров честно невозможен (клиренсы+резерв маршрута, не футпринты),
№217 — compact_island. Отчёт рефери: /test/report-to-referee-svod8-done.md; экспорт
269 планов с dining/axes: /test/plans-export.zip.
**Упрощено/отложено честно:** dining_round_compact/foldable как отдельные СХЕМЫ не
реализованы (нет разнотипных столов в сете — выбор стола за компоузером; TEMPLATE_GAP
их подсветит); access_zone Г-дивана остался bbox (v2 §9: не переписывать работающую
геометрию, риск>пользы); профили dining required/forbidden не введены (нет входа
«профиль» в продукте); пороги новых осей — после корпуса вердиктов.

### Уроки (ОБЯЗАТЕЛЬНО)
Уроки 253-256 в core/lessons.md: retry другим классом после гейта цепочки; ребейс
планки с каузальным пруфом; вейвер в точке потери зоны; не править код при бегущем
экзамене. Без иных отклонений.

## Follow-up work
- [ ] `entry-low-storage` — перепроверить актуальность после пакета C
- [ ] `template-library-v2` — принять входом missing_templates.md
- [ ] Пороги residual_fragmentation / visual_balance — отдельный ADR после корпуса замеров (G)

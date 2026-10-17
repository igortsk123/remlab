---
workstream: demo
slug: demo-11-photo-quality
title: Реалистичное фото — модель gpt-image-2.5-sunburst (medium), блок «фотографический вид», тёплые гайды стилей, каталожная форма товара, пересъёмка 5 вариантов
status: in_progress
created: 2026-10-17
updated: 2026-10-17
completed:
plan_kind: sub
parent_plan: MASTER-cost-first
assignee: opus-5.5
review_after: 2026-11-28
---

## Цель
«Сделать реалистичнее» выдаёт фото, которое читается как настоящее, тёплое и в характере стиля, за ~28 с и ~5 центов,
и не искажает купленный товар (форма — как в каталоге). Пять демо-вариантов получают такие фото на карточки и во вкладку «Фото».

## Источник задачи
Бенч d8 17.10 (18 платных прогонов, `tools/ops/bench-realistic*.py`, страница `/test/share/bench-17.10/`, таблица —
`domain/viz-fidelity-playbook.md` § «Бенч 17.10»). Решения владельца 17.10: модель **`openai/gpt-image-2.5-sunburst`, quality `medium`**
(«давай оставим пока»); «GPT 2 теплее и больше сканди» → причина в тексте стиля, тёплый гайд проверен (3/3 тёплые); «реалистичности
недостаточно» → блок PHOTOGRAPHIC LOOK проверен (3/3 живее; `high` даёт мало за двойную цену — не по умолчанию); «подлокотники есть —
оставляем, нет — дорисовывать подлокотники и подушки нельзя» → правило каталожной формы (проверено: 3/3 без выдумок).

## Что есть
- Модель — `REALISTIC_MODEL` в окружении сервиса (`tools/scout/draft_render.py:59`, default `openai/gpt-image-2`); сервис кадров для прода
  поднимает DEV (`tools/scout/dev_render_backend.sh`, переменные в `nohup`-строке); прод-контейнер `remlab-draft` — запасной путь со своим
  окружением (`/opt/remlab/.env`). Качество — `GPT_IMAGE_QUALITY` (default `medium`).
- Промпт — `tools/scout/improve_mode.py:prompt_for` (`PROMPT_VERSION = 'improve-v1'`); гайды стилей — `tools/scout/styles.json`
  (`styles.<стиль>.render_guide`, `_decor_policy`). Проверенные тексты — в `tools/ops/bench-realistic4.py` (`WARM`, `PHOTO`).
- Съёмка вариантов — `tools/ops/demo-realistic.mjs` (`--go` один, `--go --all` остальные; пишет `stateId`, обе точки).

## Решение
1. **Модель.** `REALISTIC_MODEL=openai/gpt-image-2.5-sunburst` и `GPT_IMAGE_QUALITY=medium` — в `dev_render_backend.sh` (nohup-строка) И в
   окружении прод-контейнера (`.env` + перезапуск по playbook `deployment.md`), чтобы запасной путь рисовал той же моделью. Перезапуск DEV-сервиса
   (kill по PID из `ss -ltnp :8600`, крон поднимет; без `pkill -f`). Проверка: ответ `/render` содержит `model: improve/openai/gpt-image-2.5-sunburst`.
2. **Промпт `improve-v2`** (`prompt_for`): (а) блок `PHOTOGRAPHIC LOOK — MANDATORY` из `bench-realistic4.py:PHOTO` (24 мм, глобальное
   освещение, контактные тени, фактура ткани/дерева, микронеровности стен, виньетка/зерно, без CGI-глянца); (б) правило каталожной формы:
   «armrests only if the catalogue product has them; never add armrests, cushions, throws or any textile to furniture; each product keeps
   exactly its catalogue shape» — в STATIC HARD RULES и в FORBIDDEN (`_decor_policy.deny_always` += «cushions, throws or textiles on
   furniture; armrests or parts the catalogue product does not have»). `PROMPT_VERSION = 'improve-v2'` (ключ кэша меняется — старые ответы не
   переиспользуются, это ожидаемо).
3. **Гайды шести стилей** в `styles.json` (`render_guide`): сканди — текст `WARM` из `bench-realistic4.py` (проверен); остальные пять
   (современный, минимализм, лофт, джапанди, неоклассика) переписать по той же схеме: цвет и фактура стен, пол, потолок/плинтус, **температура
   и характер света (К)**, шторы/жалюзи, допустимый декор (1–2 предмета), радиатор, «настоящая недавно отремонтированная квартира,
   обычные доступные материалы», запреты стиля. Без изменения списка `deny_always` сверх п.2. Тексты — ⚑ показать владельцу страницей
   `/test/share/style-guides/` (6 текстов + по одному пробному фото на стиль из п.5).
4. **Точки съёмки** — `demo-05` (запись 17.10): C2 в 3 см от стены → «ниша» на фото; отступ ≥ 60 см, соседняя стена вне кадра, цель —
   центр мебели. Делать ДО пересъёмки (иначе 5 вариантов снимутся с дефектом). Если `demo-05` не успевает — минимально: правило отступа
   в `cams_from_request` (`draft_render.py`) + тест.
5. **Пересъёмка.** `tools/ops/demo-realistic.mjs --go` (один вариант) → глазами d8/владелец → `--go --all`; Сканди пересъёмка тоже
   (её фото 11:46 снято старой моделью и с «нишей»): флаг `--force <style>` или временное удаление записи из `shots.json` по правилу
   «старые — история». Итого 5 × ~5.5 ¢.
6. **Живая проверка 2.29:** ответ `/render` (подмена) → `model` = sunburst, `prompt` содержит `PHOTOGRAPHIC LOOK` и правило формы,
   `version = improve-v2`; юнит-тест `prompt_for` на наличие блоков и на `deny_always`.

## Критика Codex (17.10, `_intake/codex/2026-10-17-photo-quality-critique.md`) — обязательные уточнения
1. **Кто рисует и где модель.** «Реалистично» рисует DEV-процесс (`127.0.0.1:8600`), прод-контейнер только проксирует через туннель
   (`draft_service.py:403,424`); при недоступном DEV realistic отвечает 503 (`:441`), а не рисует сам. Окружение контейнера — `/opt/remlab/draft/.env`
   (`docker-compose.yml:179`, `deployment-details.md:175`), не `/opt/remlab/.env`. Делать: модель и качество — в строке запуска
   `dev_render_backend.sh:23`; `/opt/remlab/draft/.env` — только если резерв реально работоспособен. **Без простоя:** blue/green — второй DEV-процесс
   на 8602 с новой моделью + второй туннель, `/health` и канарейка, затем атомарно переключить `/opt/remlab/test/share/render-proxy.conf`
   (перечитывается на каждый запрос, `draft_service.py:176`); старый процесс погасить после завершения заданий. «kill и ждать крон» — окно недоступности.
2. **Версионирование промпта.** `PROMPT_VERSION` ничего не инвалидирует: кэш читается по `src_id` до сборки промпта (`draft_render.py:3304`,
   ключ `SRC_DIR/<src_id>/result.json` `:1673`), `from_sources()` читает старый `prompt.txt` без проверки версии (`improve_mode.py:458,483`).
   Делать: валидировать кэш и исходник по `prompt_version + model + quality + prompt_sha`; старые результаты — история, не ответ v2.
3. **Проверка 2.29.** Ответ `/render` и реестр не содержат `prompt`/`prompt_version` (`draft_render.py:3346`, `draft_service.py:488`; `version`
   в `/health` — версия образа, `:320`). Делать: писать в ответ и реестр `prompt_version`, `prompt_sha`, `model`, `quality`; живая проверка —
   через безопасный `dry_run` (без оплаты), текст промпта — по сохранённому `prompt.txt`; мок `/render` ничего не доказывает о живом DEV.
4. **Пересъёмка.** `demo-realistic.mjs` снимает только варианты без подходящего фото, `--force` нет (`:12,24`); `find(style,stateId)` может
   принять старую запись (`:38`); камеры не в `stateId` (`index.html:3765`). Делать: `--force <style|all>`, запомнить прежние `id`, требовать
   новую запись с новым `id/ts`, сигнатурой камер, моделью и двумя кадрами; `shots.json` не чистить. **Камера C2:** глобальный clamp 60 см
   нарушит WYSIWYG-контракт «камера там, где поставил человек» (`draft_render.py:330`) — чинить позу в ДАННЫХ demo-05 (точки съёмки 5 вариантов),
   не правилом в `cams_from_request`.
5. **Текст промпта.** «24 mm lens» конфликтует с hard rule «не менять перспективу» (`improve_mode.py:101`) и произвольным FOV (`draft_render.py:349`):
   писать «match IMAGE 1 lens and perspective; a wide-angle property-listing look only when consistent». В FORBIDDEN запрещать только
   *invented detachable* cushions/throws/armrests — каталожные части и исправление обивки по эталону (`improve_mode.py:120`) остаются разрешены;
   `deny_always` выводится под «Never add, remove or replace» (`:192`) — формулировать как «cushions, throws or armrests that the catalogue product does not have».

## Скоуп — что НЕ входит
- Кадры из браузера (`demo-10`), досье (`demo-08`), ступень «ещё реалистичнее» (`high`, 12.6 ¢) — отдельным решением владельца.

## Файлы к изменению
- [ ] `tools/scout/dev_render_backend.sh`, `/opt/remlab/.env` (+ перезапуск по `deployment.md`) — модель и качество
- [ ] `tools/scout/improve_mode.py` — `prompt_for` v2 (блоки), `PROMPT_VERSION`
- [ ] `tools/scout/styles.json` — `render_guide` ×6, `_decor_policy.deny_always`
- [ ] `tools/scout/draft_render.py` — отступ поз съёмки (если не через demo-05)
- [ ] `tools/ops/demo-realistic.mjs` — `--force <style>`; `tools/scout/tests/test_improve_prompt.py` (новый); `e2e/live/demo-scenarios.live.ts` (2.29)
- [ ] Память: `domain/viz-fidelity-playbook.md` (рабочий рецепт → sunburst medium + improve-v2), `core/furniture.md`, `core/styles.md`
  (гайды), ADR-0302 (модель и промпт по бенчу), книга «Сегодня» (глава фото), `domain/demo-scenario-map.md` 2.29

## Задачи
- [ ] П.1 модель + проверка ответа
- [ ] П.2 промпт v2 + юнит-тест
- [ ] П.3 гайды ×6 + страница для владельца ⚑
- [ ] П.4 отступ поз (demo-05) → п.5 пробное фото → владелец → `--all`
- [ ] П.6 живая 2.29; память; ADR

## Критерии приёмки
- [ ] Ответ `/render` на проде: `model` = `improve/openai/gpt-image-2.5-sunburst`, время модели ≤ 35 с, списание ≤ 7 ¢ за лист
- [ ] Пробное фото «Сканди» с новым промптом: тёплый свет, радиатор, диван без подлокотников и подушек, вид 2 без «ниши» (камера ≥ 60 см от стены)
- [ ] Все 5 вариантов — фото своей расстановки на карточке и во вкладке «Фото», в реестре `stateId`; старые записи — история
- [ ] Шесть гайдов показаны владельцу страницей; юнит-тест промпта и живая 2.29 зелёные

## Где обязательно советоваться с Codex
- Критика плана до передачи — `_intake/codex/2026-10-17-photo-quality-critique.md`.

## Definition of Done — память
- ADR-0302, плейбук, `core/furniture.md`, `core/styles.md`, книга, `/memory-check`.

## Лог выполнения
- 2026-10-17 — d8: план по решениям владельца; критика Codex (5 рисков + переключение без простоя + версионирование) учтена; передан исполнителю remlab-7b.

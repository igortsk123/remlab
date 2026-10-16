---
tier: 2
topic: codex-sheet-v4-dossier
scope: Критика Codex спеки «Шторка v4» и плана demo-08 (досье), 16.10
updated: 2026-10-16
source: external:codex
---

Короткий вердикт: A — брать собственную механику на Pointer Events + `translateY`; диагноз верный, но местами преувеличен. B — в текущем виде исполнителю не отдавать: нужны приватный ключ записи, нормализованное хранение и сокращение MVP.

## A. «Шторка v4»: 5 рисков и решение

1. **Риск — неточный диагноз производительности.** `height` и `--vsh` действительно меняются на каждом движении ([index.html:4067](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4067)), причём сцена ещё догоняет палец через `transition: bottom .28s` ([index.html:3919](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3919)). Но three.js не пересчитывается на каждом `pointermove`: `liveFit()` вызывается по таймеру и `transitionend` ([index.html:4083](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4083), [index.html:4117](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4117)).
   **Делать иначе:** написать «layout/paint и запаздывание DOM-области сцены», а не «three.js reflow на каждом кадре». Убрать изменение геометрии сцены полностью.

2. **Риск — неверный выбор реализации.** Выбирать **А: Pointer Events API + transform**, не CSS-свойство `pointer-events`. Он оставляет открытый участок WebGL кликабельным и даёт единые detents/скорость/резинку. Минусы А: своя физика, борьба с native scroll и больше тестов. Б даёт инерцию браузера, но полный scrollport может перехватывать жесты холста, появляется сложный единый скролл «detents + длинный список», Safari bounce/re-snap и различная физика браузеров; стандарт намеренно не фиксирует физику snap и требует re-snap при layout change ([CSS Scroll Snap](https://www.w3.org/TR/css-scroll-snap-1/)).
   **Делать иначе:** Б допустим только как изолированный прототип; для этой сцены не делать его основной веткой.

3. **Риск — передача списка описана как уже решённая.** Прыжок подтверждён: после 40 px вызывается `vwSheet(2)` ([index.html:4111](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4111)). Но обвинение `#vside touch-action:auto` недостаточно: ручка уже `none`, список переключается `none/pan-y` ([index.html:3901](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3901)). `touch-action` определяется в начале жеста; переключить владельца потока посередине ненадёжно.
   **Делать иначе:** отдельно спроектировать arbitration: ручка/шапка всегда тянут; список при `scrollTop>0` скроллится; при старте вниз на `scrollTop=0` шторка получает поток до native scroll. Проверять на реальном Safari; не обещать «JS вообще не работает».

4. **Риск — неполный жизненный цикл жеста и viewport.** Сейчас `pointercancel` обрабатывается как обычный `up`, значит отменённый жест может получить флик ([index.html:4110](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4110)); `visualViewport.height` только читается ([index.html:4062](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4062)), но его `resize/scroll`, клавиатура и `offsetTop` не слушаются.
   **Делать иначе:** `setPointerCapture`, отдельные `pointercancel/lostpointercapture`, защита от второго пальца; detents обновлять по `visualViewport.resize`, orientation и клавиатуре после завершения drag. Учесть safe-area без двойного padding. Спецификация подтверждает отдельные события `VisualViewport` ([CSSOM View](https://www.w3.org/TR/cssom-view/)).

5. **Риск — «Фото» потеряет композицию 3:2.** Сейчас телефон отдаёт камере портретный размер wrap ([index.html:4422](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4422)), тогда как экспорт меняет aspect на заданный кадр ([viewer.ts:1298](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:1298)). Полноэкранный холст сам по себе этого не исправляет.
   **Делать иначе:** в режиме «3D» — полноэкранный responsive canvas; в «Фото» — неизменная композиционная область 3:2 для готового фото и live-замены. В peek центрировать её в видимой зоне над плашкой; в половине закреплять сверху без смены FOV/crop, допускается перекрытие снизу шторкой. После detent пины должны смещаться не «на высоту плашки», а максимум на 1–2 px.

В приёмку A добавить: клавиатуру и rotation во время каждого detent; cancel/второй палец; VoiceOver/TalkBack; grip как настоящий `button` с `aria-expanded`/названием состояния и клавишами; focus/inert; reduced-motion для snap, bump и opacity; 44×44 — вся активная зона, не только пилюля. Фраза «как Apple Maps» остаётся субъективной финальной проверкой, не единственным критерием.

## B. demo-08: 5 рисков и решение

1. **Риск — публичная ссылка становится правом записи.** Сейчас ID — 128-битный публичный ключ ([token.ts:1](/home/pakar/igor/remlab/lib/token.ts:1)); для автосохранения одного `collectionId` недостаточно: получатель ссылки сможет добавлять состояния и закреплять файлы.
   **Делать иначе:** отдельные `readId` и случайный `editToken`, на сервере только хеш edit-токена; токен записи хранить локально и никогда не включать в `/c/...`. Добавить revoke/delete. `noindex` — не контроль доступа; странице нужен также `referrer: no-referrer`.

2. **Риск — `states[]` в JSON создаст гонки и дубли.** Текущий payload ограничен 64 КБ ([route.ts:17](/home/pakar/igor/remlab/app/api/collections/route.ts:17)), а `stateId` не включает камеры ([index.html:3699](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3699)). Нынешний `bestShot()` выбирает последнюю revision, не точное состояние ([index.html:2520](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2520)).
   **Делать иначе:** `collections` + `collection_states` с `UNIQUE(collection_id,state_id)` + `state_assets(state,camera,kind,batch,object_key,bytes)`. Snapshot состояния неизменяемый; star/name и assets обновляемы. `bestImage` вычислять, а не считать источником истины. Сервер повторно канонизирует товары, как текущий POST ([route.ts:39](/home/pakar/igor/remlab/app/api/collections/route.ts:39)). Для двух ракурсов определить атомарность: realistic-набор становится главным только после готовности обоих.

3. **Риск — правило «≥3 секунды» плодит случайные точки и теряет закрытие.** Текущий `HIST` фиксирует семантические правки и дедуплицирует соседей ([index.html:3737](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3737)); существующий лимит — лишь 30 записей за 10 минут с IP ([ratelimit/index.ts:45](/home/pakar/igor/remlab/lib/ratelimit/index.ts:45)).
   **Делать иначе:** кандидат возникает только после семантической правки; commit — после 3 секунд видимости без новых правок либо немедленно при Improve/★/Share/смене режима. «Настоящая точка» — только после успешного idempotent server upsert. `pagehide` — `keepalive/sendBeacon`, не гарантия; неотправленное держать в retry-очереди. Открытие, drag шторки, orbit камеры и проход через undo точек не создают.

4. **Риск — неконтролируемый объём и ложное `pinned`.** 50×200 КБ уже ≈10 МБ на сессию без realistic-фото. Реестр реально ограничен 120 записями ([draft_guard.py:90](/home/pakar/igor/remlab/tools/scout/draft_guard.py:90)); флаг в `shots.json` не защищает сам файл от очистки. `exportFrame` временно меняет renderer и projection ([viewer.ts:1290](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:1290)).
   **Делать иначе:** объектное хранилище, content hash, ссылки и refcount, квоты byte/state/session, TTL и GC. Live JPEG 3:2 с циклом качества до ≤200 КБ — только для ★/Share или когда нет серверного кадра; история может использовать маленький thumbnail. Хранить отдельно суммы «на момент» и «сейчас», явно подписывать обе.

5. **Риск — первая версия перегружена миграцией, отчётом и печатью.** Старый `/p` — статический каталог с отдельным 10-символьным ID ([draft_service.py:524](/home/pakar/igor/remlab/tools/scout/draft_service.py:524)); соответствия collection/state нет, поэтому честный редирект старых ссылок невозможен без backfill. Аналитика, partner-report, RU/EN, print, старые редиректы и pinning всех кадров резко расширяют контур.
   **Делать иначе:** demo-08 MVP = защищённый upsert состояний, точное правило image-per-state/camera, список/restore, одно RU-досье и share URL. Отложить report, старые `/p`, EN, специальную печать и массовые live-снимки. Текущий `/p` пока оставить неизменным.

Отдельный блокер B: утверждение «без ПДн» должен подтвердить владелец/юрист. `sendId`, история поведения и постоянный локальный идентификатор делают данные связываемыми; внутренняя карта уже оставляет правовое основание для действий по ссылке нерешённым ([data-map.md:11](/home/pakar/igor/remlab/docs/data-map.md:11)). Нужны срок, удаление, политика доступа и решение, видит ли получатель общей ссылки «Другие мои расстановки».
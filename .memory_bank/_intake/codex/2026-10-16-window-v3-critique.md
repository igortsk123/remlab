---
tier: 2
topic: codex-window-v3
scope: Критика Codex спеки окна варианта v3 (16.10) — модель состояний, шторка, план, жесты, undo
updated: 2026-10-16
source: external:codex
---

Вердикт: v3 нельзя отдавать в работу без уточнения модели состояний и жестов. Главные 5 рисков:

1. **«Фото» смешано с ракурсами.** Сейчас `VW.mode=c1|c2|walk`, а не `photo|walk|plan`: [index.html:3783](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3783), кнопки всё ещё «Ракурс 1/2»: [index.html:3810](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3810). «План» сразу открывает редактор: [index.html:3911](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3911).
   **Делать:** разнести `mode` и `photoIndex`; явно решить, что показывает «Фото» после рендера — готовое фото или LIVE-сцену.
   **Иначе:** точки, свайп и возврат из `#cons` будут менять не тот уровень состояния.

2. **Шторка описана четырьмя состояниями, код имеет три.** `0/1/2`: [index.html:3864](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3864); `0` уже высотой 268 px, то есть это peek, а настоящего collapsed нет: [index.html:3754](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3754). Вся `.vside` прокручивается, поэтому ручка уезжает: [index.html:3764](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3764). Свайп из списка работает лишь при `scrollTop<=0`: [index.html:3935](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3935).
   **Делать:** четыре detent-состояния; ручку вынести из внутреннего скролла; вниз по контенту сворачивать только при `scrollTop=0`, из любого места — только за ручку.
   **Иначе:** требование «из середины списка» отнимет обычный жест прокрутки. Также collapsed противоречит «сертификат/доплата видны всегда» — либо денежный чип остаётся на ручке, либо «всегда» заменить на «начиная с peek».

3. **Читаемый «План» несовместим с сохранением положения шторки.** При full над шторкой остаётся 104 px, при half около 354 px; план с названиями и нормами там не читается. На 390×400 без потери одновременно показать план, подсказки и peek невозможно. Код отдельного read-only-плана в сцене не имеет: `#cons` переносит единственный `#work` в полноэкранный редактор: [index.html:2632](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2632). «Готово» возвращает прежний кадр, но не режим Plan: [index.html:2661](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:2661).
   **Делать:** отдельный read-only renderer; в Plan временно ограничивать шторку уровнем peek, запоминая и восстанавливая её прежнее состояние; перед возвратом ставить `mode=plan`.
   **Иначе:** убрать либо «та же высота/состояние шторки», либо подписи норм.

4. **Контракт жестов 3D отсутствует.** Холст сейчас: drag поворачивает, tap выбирает предмет: [index.html:4093](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4093). Тапы по краям и по полу не реализованы; мост сцены возвращает только предмет: [demo-scene.ts:165](/home/pakar/igor/remlab/lib/viewer3d/demo-scene.ts:165), хотя движок умеет `goTo`: [viewer.ts:746](/home/pakar/igor/remlab/lib/viewer3d/viewer.ts:746).
   **Делать:** зафиксировать приоритет: Photo — горизонтальный swipe; 3D — движение >8 px всегда drag, короткий tap в крайних 20% поворачивает, центральный tap по предмету выбирает, по полу идёт. Шторка владеет жестом, начатым внутри неё.
   **Иначе:** крайний предмет будет то выбираться, то поворачивать камеру. Колёсико лучше убрать; клавиши листают фото только при фокусе сцены и только в Photo. Добавить приёмку «tap по полу».

5. **Undo и ≤2 с пока не специфицированы проверяемо.** Код всегда рисует ↶/↷ и счётчик: [index.html:3813](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3813), [index.html:3821](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3821). Загрузка показывается общей крутилкой сцены, не у товара: [index.html:4148](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4148); обновления выполняются последовательно: [demo-scene.ts:119](/home/pakar/igor/remlab/lib/viewer3d/demo-scene.ts:119).
   **Делать:** скрывать историю при `stack.length=1`; после правки показывать активный ↶ и disabled ↷, после undo — активировать ↷. Крутилку ставить в строку товара немедленно; определить ≤2 с как «из прогретого кэша до подтверждённой модели», иначе гарантировать лишь placeholder и предзагрузку.
   **Иначе:** SLA на произвольной мобильной сети невыполним.

Добавить в спеку: таблицу владельцев жеста, правило источника изображения в Photo, поведение Plan при half/full, safe-area/динамический viewport, rapid-swap и offline-тесты. Убрать «свайп вниз из любого места» и колесо.

Сопутствующий блокер страницы: soon-вкладки сейчас некликабельны [index.html:479](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:479), а кухня и спальня программно «оживают» ([index.html:4267](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4267), [index.html:4350](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:4350)); для единой заглушки эти ветки показа нужно отключить, оставив данные для суммы.
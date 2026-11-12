## Вердикт

1. Порядок **A → B → C не оптимален**. Лучше: **A → S → измерение → lazy**, где S — механически разнести исходник по фрагментам, но собирать прежний classic-HTML без изменения поведения. Это решает (b) дешевле, чем полноценный C. B оставить условным.

2. A полезен для LCP, но не «низкорисковый»: утверждение плана «код не читает свой текст» неверно.

## Пропущенные риски A

- `index.html:6952–6954`, `camWorker()` ищет `// CAMFIT START/END` в `document.scripts[].textContent`. Esbuild удалит комментарии — fallback Web Worker перестанет работать. Синтаксическая проверка этого не обнаружит.
- `tests/unit/demo-cam-worker.test.ts` и CAMFIT-тесты читают **исходный** HTML, поэтому останутся зелёными при сломанном собранном HTML.
- Аналогично большинство из ~55 потребителей — `tests/unit/*`, `tools/flat3d/demo-cams.mjs`, `cam-masks.mjs`, `hall-snap.mjs`, `tools/ops/demo-walk/*.cjs` — проверяют source, не результат `flat215_demo.py`.
- `tools/ops/demo-warm.mjs:295` и `demo-realistic.mjs:234` используют `Function#toString()` функций страницы; это надо проверить именно на minified build.
- Нельзя резать `<script>/<style>` наивным regex: строка/шаблон с `</script>` станет будущей скрытой поломкой.
- Запись результата должна остаться атомарной, как `atomic_io.write_text`; `WARN + исходник` допустим для доступности, но не должен считаться успешным выполнением критерия скорости.
- `precompress.mjs` уже рекурсивно поддерживает `.js` и `.css`; атомарная перезапись HTML изменит mtime и заставит пересжать его. Нужен тест против устаревшего `.br`, а не новая логика сжатия.

## Пропущенные риски B

- Вынесенный main-script имеет пустой `script.textContent`; CAMWORK сломается даже при сохранённых комментариях. CAMFIT следует сделать явным worker-источником/asset.
- Нельзя переходить на `type=module` или IIFE без адаптации глобалов. Есть inline handlers `hmHq(this)` (`index.html:7410`) и `onerror=…`, а поздние блоки патчат `window.pickVariant`, `tryOn`, `showTab`.
- Несколько classic-script блоков взаимно зависят от порядка и переназначают функции (`index.html:9006`, `12144+`). Один `defer` рядом с оставшимися inline-блоками изменит порядок исполнения.
- `/demo/lib/page.<hash>.*` сейчас получит `Cache-Control: no-cache`: `caddy/Caddyfile:146–159` помечает так все non-image. Для immutable нужен отдельный matcher.
- `tourTarget()` разрешает лишь `scene.*.js`/`basket.*.js`; нужны строгие regex для page JS/CSS, MIME CSS и включение их в ветку `IMMUTABLE`.
- `pinRelease()` должен атомарно читать manifest и включать все page-assets в hash релиза. Иначе публикация и pin могут дать смешанную версию.
- `publish_demo.sh` делает `rsync --delete` в живую папку, не атомарное переключение версии. Новый `index.html` может кратко сослаться на ещё не приехавший asset; файлы надо класть до HTML/manifest.
- Откат приложения на версию без нового whitelist даст 404 новым закреплённым турам; нужен порядок deploy: серверная поддержка → публикация страницы, плюс проверка rollback.
- `stage-proxy.mjs` пропускает `/demo/lib/*`, но не знает MIME `.css` и не сжимает CSS.
- `.br/.gz` не входят в pinned release. HTML тура сжимает `brotliPage`, но JS/CSS пойдут через Next/Caddy gzip/zstd, если отдельно не реализовать precompressed serving.
- CSP сейчас не препятствие: `caddy/Caddyfile:50–54` задаёт только `frame-ancestors`. Но B не приближает строгий CSP: остаются injected inline boot и inline handlers.

## Стоит ли B

Слабое обоснование. Покупательский тур уже получает `private, no-cache + ETag` и 304 (`tour-cache.ts:REVALIDATE`); только агентский HTML с `k` — `no-store`.

Главное: `/try/<id1>/tour/lib/page.hash.js` и `/try/<id2>/…` — разные cache keys. Поэтому обещание «второй тур — 0 КБ» неверно без общего content-addressed URL и гарантированного хранения старых hash-файлов.

B имеет смысл только если замер покажет выигрыш холодного LCP от ранней параллельной загрузки либо как основа настоящего lazy-loading. Сам по себе он может добавить блокирующий CSS/JS-запрос и RTT.

## Что изменить в плане

- После A поставить **S: composer + механическое разбиение по нынешним script/style-блокам**, сохранив classic semantics и байтовый порядок; lazy-loading — отдельным этапом.
- Перенести V-0 перед B; generated `index.html` не считать редактируемым исходником. Все marker-тесты должны читать `composePageSource()`.
- Перед A устранить self-reading CAMFIT или добавить обязательный smoke собранного файла: worker отвечает, `demo-warm` извлекает функции.
- Сделать B экспериментом с gate: cold LCP/bytes/long tasks; внедрять только при измеримом выигрыше.
- Добавить матрицу `/demo`, buyer tour, agent tour; cold/revisit/same tour/different tour; старый и новый pinned release.
- Не считать три прогона достаточными при разбросе 4.4–8.1 с: минимум 5–7, медиана и p75.

Неопределённости: HAR/сырые замеры вне репозитория не проверены; неизвестна доля повторных открытий одного тура и реальный Safari/WebView; не подтверждена стоимость extra RTT на целевой slow-4G сети. Файлы не изменялись.
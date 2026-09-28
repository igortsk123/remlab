## 1. Вывод

Самый дешёвый и безопасный первый шаг — добавить `/work/*` как второй URL-маршрут к тому же физическому `/srv/test`, сделать `/work/` каноническим только для хаба и отчётов, но пока не переносить каталог и не переписывать все 91 вхождение.

При этом:

- `/test` и `/test/` перенаправить на `/work/`;
- `/test/*` временно оставить работающим;
- `/test/buildup*` сохранить как 410;
- обновить `hub_page.py`, чтобы его ссылки вели на `/work/*`;
- сначала свести серверный Caddyfile с репозиторием. Отсутствие в репо `@nextrce` и `log` — блокер выкладки.

Полный редирект `/test/* → /work/*` сейчас преждевременен: `/test` является не только старым адресом хаба, но и рабочим transport namespace для демо, рендера и mesh-audit.

## 2. Доказательства

### `/test` — не просто хаб

Демо на `/demo` продолжает читать:

- снимки из `/test/share/shots.json`: [index.html:1898](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:1898);
- меши из `/test/mesh-pilot10/`: [index.html:3084](/home/pakar/igor/remlab/tools/scout/flat215-demo/index.html:3084);
- индекс мешей по абсолютному URL: [flat215_demo.py:181](/home/pakar/igor/remlab/tools/scout/flat215_demo.py:181).

Рендер также использует `/test/share` и `/test/mesh-pilot10`: [draft_render.py:657](/home/pakar/igor/remlab/tools/scout/draft_render.py:657), [draft_render.py:2153](/home/pakar/igor/remlab/tools/scout/draft_render.py:2153).

Mesh-audit публикует постеры и модели физически в `/opt/remlab/test/mesh-audit` и записывает публичный URL `/test/mesh-audit/...`: [mesh_audit_sync.py:251](/home/pakar/igor/remlab/tools/scout/mesh_audit_sync.py:251), [mesh_audit_publish.py:32](/home/pakar/igor/remlab/tools/scout/mesh_audit_publish.py:32).

Поэтому глобальная замена `/test` затрагивает работающий `/demo`, хотя сам `/demo` менять не просили.

### 91 вхождение — не 91 ссылки

Там смешаны три разных контракта:

- HTTP URL `/test/...`;
- физический путь `/opt/remlab/test/...`;
- комментарии и диагностический вывод.

Например, `nightly_exam.sh` публикует непосредственно в файловый каталог: [nightly_exam.sh:15](/home/pakar/igor/remlab/tools/scout/nightly_exam.sh:15), а хаб генерирует именно HTTP-ссылки: [hub_page.py:101](/home/pakar/igor/remlab/tools/scout/hub_page.py:101). Массовая текстовая замена смешает storage migration с URL migration.

### Хаб действительно прибит к старому адресу

- Все ссылки строятся с `/test/`: [hub_page.py:96](/home/pakar/igor/remlab/tools/scout/hub_page.py:96).
- В самой странице написана закладка `/test/`: [hub_page.py:123](/home/pakar/igor/remlab/tools/scout/hub_page.py:123).
- Публикация только ручная через `--publish`: [hub_page.py:132](/home/pakar/igor/remlab/tools/scout/hub_page.py:132).

В ежедневном участке публикуются изменения, layout и `/demo`, но не сам хаб: [refresh_daily.sh:337](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:337). Поэтому одного Caddy-маршрута недостаточно: `/work/` покажет старую страницу со ссылками обратно на `/test/*`.

### `templates` удалил не cleanup

`templates_page.py` прямо помечен устаревшим и сообщает, что страница заменена `/canons`: [templates_page.py:2](/home/pakar/igor/remlab/tools/scout/templates_page.py:2). Но хаб всё ещё содержит ссылку на неё: [hub_page.py:25](/home/pakar/igor/remlab/tools/scout/hub_page.py:25).

`cleanup.sh` удаляет Docker-артефакты и старые дампы БД, но вообще не трогает `/opt/remlab/test`: [cleanup.sh:22](/home/pakar/igor/remlab/infra/server/cleanup.sh:22), [cleanup.sh:51](/home/pakar/igor/remlab/infra/server/cleanup.sh:51). Значит 404 — протухший хаб, а не работа очистки.

## 3. Рекомендуемый Caddy-конфиг

Добавлять его нужно в уже сведённый конфиг, сохранив серверные `log` и `@nextrce`.

На первом этапе редиректы лучше сделать временными `302`, чтобы ошибка не закэшировалась навсегда:

```caddy
# Канонический корень нового хаба.
redir /work /work/ 302

# Только корень старого хаба. Потом можно заменить 302 на 308.
redir /test /work/ 302
redir /test/ /work/ 302

# Закрытое старое демо не должно воскреснуть через новый alias.
handle /test/buildup* {
	header Content-Type "text/html; charset=utf-8"
	header X-Robots-Tag "noindex, nofollow"
	respond "<!doctype html><meta charset=utf-8><title>Страница закрыта</title><body>Страница закрыта.</body>" 410
}
handle /work/buildup* {
	header Content-Type "text/html; charset=utf-8"
	header X-Robots-Tag "noindex, nofollow"
	respond "<!doctype html><meta charset=utf-8><title>Страница закрыта</title><body>Страница закрыта.</body>" 410
}

# Специальная политика тяжёлых неизменяемых ассетов.
handle_path /work/mesh-audit/* {
	root * /srv/test/mesh-audit
	file_server
	header X-Robots-Tag "noindex, nofollow"
	header Cache-Control "public, max-age=604800, immutable"
}
handle_path /test/mesh-audit/* {
	root * /srv/test/mesh-audit
	file_server
	header X-Robots-Tag "noindex, nofollow"
	header Cache-Control "public, max-age=604800, immutable"
}

# Новый канонический URL, старый физический каталог.
handle_path /work/* {
	root * /srv/test
	file_server browse
	header X-Robots-Tag "noindex, nofollow"
	header Cache-Control "no-store, no-cache, must-revalidate, max-age=0"
	header Pragma "no-cache"
}

# Старые ссылки и рабочие зависимости /demo пока не ломаем.
handle_path /test/* {
	root * /srv/test
	file_server browse
	header X-Robots-Tag "noindex, nofollow"
	header Cache-Control "no-store, no-cache, must-revalidate, max-age=0"
	header Pragma "no-cache"
}
```

### Почему порядок сработает

Caddy переставляет директивы согласно встроенному порядку: `redir` выполняется раньше `handle`, а `handle`/`handle_path` являются взаимно исключающимися. Среди path matcher более специфичный путь сортируется выше общего. Поэтому `/test/mesh-audit/*` окажется перед `/test/*`. [Документация Caddy по порядку директив](https://caddyserver.com/docs/caddyfile/directives), [семантика handle](https://caddyserver.com/docs/caddyfile/directives/handle).

Конкретно:

- `/test` совпадает только с точным `redir /test`;
- `/test/` — с точным `redir /test/`;
- `/test/x` — с `handle_path /test/*`;
- `/test/mesh-audit/x` — со специальным более специфичным блоком;
- `/test/buildup...` — с 410-блоком;
- `handle_path` удаляет префикс перед `file_server`, поэтому `/work/canons/index.html` ищется как `/srv/test/canons/index.html`. [Документация handle_path](https://caddyserver.com/docs/caddyfile/directives/handle_path).

`route` здесь не нужен: матчеры можно сделать непересекающимися и проверить адаптированный JSON. Он понадобился бы при глобальном редиректе `/test/*`, который должен иметь исключения для buildup, mesh-audit и runtime-ассетов.

## 4. Риски и краевые случаи

### Блокер: конфиг сервера содержит защиту, которой нет в репо

ADR требует навсегда сохранить:

- фильтр неправильного `Next-Action`;
- access log.

Это зафиксировано в [ADR-0207](/home/pakar/igor/remlab/.memory_bank/decisions/adr-0201-0250.md:127). Текущий репо-Caddyfile их не содержит.

Утверждение «деплой Caddyfile не синхронизирует» верно только для CI: workflow копирует compose, SQL и скрипты, но не Caddyfile: [deploy.yml:80](/home/pakar/igor/remlab/.github/workflows/deploy.yml:80). Ручной `deploy.sh`, наоборот, пытается скопировать Caddyfile и лишь останавливается при различии: [deploy.sh:33](/home/pakar/igor/remlab/deploy.sh:33). То есть рассинхрон уже влияет на эксплуатацию.

### Два URL

При одновременной доступности `/test/x` и `/work/x`:

- браузер и прокси держат два независимых кэша;
- логи и присланные ссылки раздваиваются;
- страницы с абсолютными `/test/...` будут уводить пользователя обратно;
- переименование не делает раздел приватным.

Индексацию частично сдерживает `X-Robots-Tag`, но это не контроль доступа. Более того, `file_server browse` публикует список содержимого 4,6 ГБ: [Caddyfile:63](/home/pakar/igor/remlab/caddy/Caddyfile:63). Если «внутренний» означает действительно закрытый, понадобится аутентификация и последующее ограничение старого `/test/*`; смена имени пути этого не обеспечивает.

### Полный редирект `/test/*`

Он, вероятно, технически переживётся обычным браузером, но создаст лишний hop для:

- каждого GLB и постера mesh-audit;
- каждой загрузки меша и `shots.json` в `/demo`;
- серверных `urllib`/`curl`-потребителей;
- Range-запросов `<model-viewer>`.

Главная проблема не сам HTTP 301, а отсутствие инвентаризации клиентов. До этого шага нужен crawl живых HTML и логов обращений.

### Физический перенос

`mv /opt/remlab/test /opt/remlab/work` на одном FS был бы дешёвым, но потребовал бы одновременно менять:

- bind mount `./test:/srv/test`: [docker-compose.yml:18](/home/pakar/igor/remlab/docker-compose.yml:18);
- десятки publishers;
- catalog watchdog: [catalog-watchdog.sh:10](/home/pakar/igor/remlab/infra/server/scripts/catalog-watchdog.sh:10);
- mesh-audit и рендер.

Копирование вместо rename временно съест ещё 4,6 ГБ на хосте, где уже был инцидент с заполнением диска. Практической пользы нет: URL не обязан совпадать с именем каталога.

## 5. Рекомендуемый порядок

1. Снять бэкап и SHA живого серверного Caddyfile.
2. Перенести точные серверные блоки `log` и `@nextrce` в репозиторный кандидат без пересочинения.
3. Добавить `/work` alias и только точные редиректы `/test`, `/test/`.
4. Исправить `hub_page.py`: ссылки, текст закладки и публикационное сообщение на `/work`; физический `/opt/remlab/test/index.html` оставить.
5. Удалить из хаба устаревший пункт `templates` либо заменить его ссылкой на `canons`.
6. Перегенерировать и опубликовать хаб.
7. Проверить конфиг тем же образом `caddy:2.8-alpine`:

```bash
docker run --rm \
  -v "$PWD/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine \
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile

docker run --rm \
  -v "$PWD/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
  caddy:2.8-alpine \
  caddy adapt --config /etc/caddy/Caddyfile --adapter caddyfile --pretty
```

8. На сервере проверить `docker compose config --quiet`, затем validate кандидата, reload Caddy без перезапуска всего compose-стека.
9. Проверить матрицу:

```text
/demo                 → 301 /demo/
/demo/                → 200
/test                 → 302 /work/
/test/                → 302 /work/
/work                 → 302 /work/
/work/                → 200
/work/canons/         → 200 + no-store
/test/share/shots.json → 200
/test/mesh-pilot10/mesh-index.json → 200
/test/buildup         → 410
/work/buildup         → 410
mesh-audit GLB        → 200 + immutable
/api/health           → 200
Next-Action: x        → 403
```

После суток без ошибок точные 302 можно сделать постоянными. Глобальный редирект дочерних `/test/*` — отдельная миграция, не часть текущей просьбы.

## 6. Альтернативы

- **Переписать все генераторы сразу:** даст чистый namespace, но риск высок, потому что поиск смешивает URL, файловые пути и комментарии. Польза сейчас небольшая.
- **Физически перенести каталог:** наиболее дорогой вариант по числу зависимостей, хотя сам `mv` дешёв.
- **Оставить `/test/` и только добавить `/work/`:** технически безопасно, но не исправит замеченный владельцем `/test → 404` и оставит старую закладку канонической.
- **Редиректировать весь `/test/*`:** годится как финальная фаза после перевода `/demo`, mesh-audit и рендера на отдельный asset prefix либо после доказанного redirect-теста.

## 7. Допущения и что изменило бы вывод

Я не видел содержимое живых 4,6 ГБ и точный серверный `@nextrce`. До полного редиректа вывод изменили бы:

- отсутствие в live HTML абсолютных `/test/...`;
- access-log, показывающий, что `/test/share`, `/test/mesh-pilot10` и `/test/mesh-audit` никто программно не использует;
- решение владельца, что `/work` должен быть не просто новым адресом, а закрытым авторизацией разделом;
- готовность выделить отдельный публичный `/assets/*` для зависимостей `/demo`.

Без этих данных alias + точные корневые редиректы — минимальная безопасная миграция.
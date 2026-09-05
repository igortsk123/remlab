---
workstream: infra/caddy
slug: health-map-apex-redirect
title: Апекс health-map.online — 302-редирект на 2mnenie.online (домен перестаёт быть мёртвым)
status: draft
created: 2026-09-05
updated: 2026-09-05
completed:
---

## Цель
Апекс `health-map.online` (и `www`) сейчас не открывается вообще. Отдать с него
302 на `https://2mnenie.online/`, не тронув работающий `remont-lab.online`.

## Источник задачи
Пользователь: «http://health-map.online/ посмотри на cloudflare лендинг не открывается
почини разберись» → затем выбор: «редирект прикрытие можно на https://2mnenie.online/»
→ затем: «только не сломай ничего существующего».

## Диагноз (проверено live 2026-09-05)
- CF-зона `health-map.online` (zone `0bb21bb3eaa6c730c8b96bf2adad92cc`), 13 записей.
  `health-map.online` и `www` — A → `89.167.127.0` (exit-fi), **grey-cloud**:
  Cloudflare в цепочке не участвует, браузер идёт прямо на сервер.
- На exit-fi `:443` держит `remlab-caddy`, в его Caddyfile прописан **только**
  `remont-lab.online`. Для апекса сертификата нет → Caddy рвёт handshake
  `TLS alert 80 (internal error)` → «сайт не открывается».
- `:80` снаружи закрыт (`iptables INPUT policy DROP`, правила для 80 нет) → `http://`
  виснет по таймауту. Это и видел пользователь.
- **Лендинга там никогда не было**: `/var/www/html` — заглушка Debian, в caddy-data
  один сертификат (`remont-lab.online`), в `/opt/remlab` про health-map ни строчки.
  Апекс — осиротевшая A-запись.
- Репо-`caddy/Caddyfile` **идентичен** серверному (`diff` чист) — чистая база отката.
- Остальная зона жива: `sub.` 200, `sub-ru.` 200, `panel.`/`hook.`/`hy22.` на месте.
  `app.` 520 на :443 — ожидаемо, он XHTTP-транспорт на :2096, не сайт.

## Скоуп — что входит
- Новый site-блок `health-map.online, www.health-map.online` в `caddy/Caddyfile` → `redir 302`.
- Доставка Caddyfile на сервер + graceful `caddy reload`.
- Верификация: апекс редиректит, `remont-lab.online` не пострадал.

## Скоуп — что НЕ входит
- Блок `remont-lab.online` — не трогаем ни строкой.
- `deploy.sh` не запускаем: пересборка образа и перезапуск контейнеров для правки
  конфига не нужны и создают лишний риск.
- Firewall/`:80` — вынесено в опциональную Фазу 2, отдельным решением.
- DNS-записи в Cloudflare — не меняем, апекс уже указывает куда надо.
- TXT `config.health-map.online` (отсутствует, документирован в VPN
  `network_map.md:131`) — по решению пользователя отложено, отдельная задача.

## Файлы к изменению
- [ ] `caddy/Caddyfile` — добавить один site-блок в конец файла (репо-версия обязательна:
      `deploy.sh:39` падает с FATAL, если на сервере есть строки, которых нет в репо)
- [ ] `/opt/remlab/caddy/Caddyfile` на `89.167.127.0` — та же правка, через `cp` поверх
      (не `mv`/`scp` напрямую: файл bind-mount'ится по одному иноду,
      см. `anti-patterns.md:133` — замена инода не видна контейнеру)

## Задачи
- [ ] 1. Бэкап: `cp /opt/remlab/caddy/Caddyfile /opt/remlab/caddy/Caddyfile.bak-20260905`
- [ ] 2. Правка репо `caddy/Caddyfile` — добавить блок:
      ```
      health-map.online, www.health-map.online {
      	redir https://2mnenie.online/ 302
      }
      ```
- [ ] 3. `scp` во временный путь на сервере, затем `cp` поверх целевого (сохранить инод)
- [ ] 4. `docker exec remlab-caddy caddy validate --config /etc/caddy/Caddyfile` — до reload
- [ ] 5. `docker exec remlab-caddy caddy reload --config /etc/caddy/Caddyfile` (graceful,
      zero-downtime; при невалидном конфиге Caddy оставляет старый — remont-lab не падает)
- [ ] 6. Дождаться выпуска сертификата по TLS-ALPN-01 на :443 (порт 80 закрыт → HTTP-01 не
      вариант; Caddy выберет ALPN сам)
- [ ] 7. Верификация (см. критерии)

## Критерии приёмки
- [ ] `curl -sI https://health-map.online/` → `302`, `location: https://2mnenie.online/`
- [ ] `curl -sI https://www.health-map.online/` → `302`
- [ ] `https://remont-lab.online/` → `200` (**не сломали существующее**)
- [ ] `https://remont-lab.online/api/health` → `200`
- [ ] `https://sub.health-map.online/` → `200`, `https://sub-ru.health-map.online/` → `200`
      (VPN-каналы не задеты)
- [ ] `docker ps`: `remlab-caddy` и `remlab-app` без рестарта (uptime не обнулился)
- [ ] Репо-Caddyfile == серверный (`deploy.sh` guard не сломан на будущее)

## Известное ограничение (сообщить пользователю)
`http://health-map.online/` — та ссылка, что открывал пользователь — **останется недоступной**:
:80 закрыт фаерволом на exit-узле. Работать будет `https://health-map.online/`. Современные
браузеры при вводе домена в адресную строку сами идут в HTTPS, так что практически домен
откроется; жёсткая `http://`-ссылка — нет.

### Фаза 2 (опциональная, только по отдельной команде)
Чтобы чинить и `http://`: `iptables -I INPUT -p tcp --dport 80 -j ACCEPT` + server-блок
в host-nginx с 301 на HTTPS. **Не делаю по умолчанию**: это меняет профиль открытых портов
VPN exit-узла (сейчас наружу торчит только 443/22/22222/8443-8445/9443), а host-nginx на :80
отдаёт дефолтную заглушку Debian на любой Host — лишний фингерпринт.

## Откат
```bash
ssh root@89.167.127.0 "cp /opt/remlab/caddy/Caddyfile.bak-20260905 /opt/remlab/caddy/Caddyfile \
  && docker exec remlab-caddy caddy reload --config /etc/caddy/Caddyfile"
```
Плюс `git checkout -- caddy/Caddyfile` локально. Сертификат апекса в caddy-data при откате
остаётся — безвреден, никем не отдаётся.

## Оценка риска
**Низкий.** Добавляется изолированный site-блок; существующий блок не редактируется.
`caddy validate` до reload, reload атомарный. Худший исход — не выпустился сертификат
апекса: тогда апекс остаётся ровно в том состоянии, что сейчас (не открывается),
а `remont-lab.online` работает как работал.

## Definition of Done — память (без этого `completed` запрещён)
- [ ] `decisions.md` — ADR: апекс VPN-домена отдаёт 302 на витрину, почему не лендинг
- [ ] `project-state.md` — Caddy обслуживает 2 домена, а не 1
- [ ] Кросс-проект: в VPN `.memory_bank/infra/network_map.md` дописать апекс
      (сейчас там апекса нет вообще) + зафиксировать отложенный TXT `config.`
- [ ] `/memory-check` выполнен, audit «чисто»

## Лог выполнения
- 2026-09-05 — диагностика проведена (CF API, exit-fi, Caddy, firewall); план создан (draft)

## Completion summary
[Заполняется при переводе в completed]

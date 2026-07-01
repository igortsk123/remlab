# DECISIONS — ADR (Architecture Decision Records)

Формат: Контекст → Решение → Последствия/альтернативы. Отклонения от тех-спеки фиксируются здесь (правило §0 «гипотезы, не аксиомы»).

---

## ADR-0001 — Хостинг: self-host docker-compose на Hetzner exit-fi вместо Vercel
**Дата:** 2026-07-01
**Контекст:** Тех-спека дефолтом предлагает Vercel + Supabase Cloud. У владельца есть свой сервер exit-fi (89.167.127.0, Hetzner EU, 2 vCPU / 3.7 GB), где уже работает внутренняя VPN-нода. Задача — стартовать дёшево и с полным контролем, migration-ready.
**Решение:** Приложение = изолированный `docker-compose` стек на exit-fi: Caddy(:443) → Next.js(`next start`) → postgres+pgvector. Сборка локально, на сервер уезжает образ. Отдельная docker-сеть `remlab-net`, щедрые лимиты памяти, swap 4 GB — чтобы не задеть VPN-ноду.
**Последствия:** Дёшево, полный контроль, переезд = копирование compose+env+volume-dump+образ. Минусы: сами держим uptime/бэкапы/масштаб; сосед — боевой VPN (изоляция обязательна). Альтернатива (Vercel+Supabase) остаётся fallback.

## ADR-0002 — БД: самохостед postgres:17 + pgvector в контейнере (не Supabase Cloud)
**Дата:** 2026-07-01
**Контекст:** Спека завязана на Supabase (Auth/Realtime/Storage/pgvector). Полный self-host Supabase (~8 контейнеров, ~4 GB) не влезает рядом с VPN-нодой на 3.7 GB.
**Решение:** Держим только `postgres:17 + pgvector` в контейнере (volume + ночной pg_dump). Auth/Realtime/Storage реализуем по мере фич: интерим — anonymous session id + polling статуса job (спека допускает polling как fallback Realtime). Полноценный Supabase-стек либо отдельные контейнеры (GoTrue и т.п.) — позже, при необходимости, отдельным ADR.
**Последствия:** Лёгкий футпринт, полная автономия БД. Минус: часть удобств Supabase (готовый Auth/Realtime/RLS-тулинг) реализуем руками. Drizzle + Zod + RLS в самом Postgres — сохраняем.

## ADR-0003 — TLS: Let's Encrypt через TLS-ALPN-01 на :443 (Caddy), без открытия :80
**Дата:** 2026-07-01
**Контекст:** Домен remont-lab.online — A-запись GoDaddy напрямую на сервер (без Cloudflare-прокси). На сервере iptables INPUT=DROP; :443 открыт, :80 закрыт снаружи.
**Решение:** Caddy выпускает и авто-продлевает сертификат Let's Encrypt через TLS-ALPN-01 (challenge на :443). :80 не открываем.
**Последствия:** Автопродление из коробки, минимум изменений firewall. Fallback: открыть :80 для HTTP-01, если ALPN будет капризничать.

## ADR-0004 — Лимиты памяти контейнеров: щедрые (страховка blast-radius)
**Дата:** 2026-07-01
**Контекст:** exit-fi несёт боевую VPN-ноду. Без лимитов OOM-killer при аварии remlab может убить rw-core/remnanode и уронить VPN.
**Решение:** mem_limit: remlab-app 1 GB, postgres 1 GB (shared_buffers=128MB), caddy 128 MB. Высокие настолько, что в норме не достигаются — ловят только runaway. Подтверждено владельцем.
**Последствия:** VPN-нода защищена (OOM бьёт по нашему контейнеру, он рестартует). Ничего не «режется» в нормальной работе.

## ADR-0005 — Дисковая гигиена / автоочистка
**Дата:** 2026-07-01
**Контекст:** Источники переполнения: логи контейнеров, старые образы после деплоев, рост БД.
**Решение:** (1) ротация логов Docker json-file max-size=10m max-file=3; (2) очистка старых образов после деплоя (последние 2 тега remlab-app + prune dangling, scoped — VPN-образ не трогаем); (3) weekly systemd-timer remlab-cleanup (dangling + build-cache + stopped remlab); (4) ротация pg_dump-бэкапов (последние 7); (5) df-watchdog при >80%; (6) swappiness=10.
**Последствия:** Диск не переполняется сам, VPN-образы не затрагиваются (без глобального `system prune -a`).

## ADR-0006 — Целевая платформа образов: linux/arm64 (сервер aarch64)
**Дата:** 2026-07-01
**Контекст:** При первом деплое обнаружено, что exit-fi — **ARM (aarch64)** (Hetzner ARM/Ampere), а не amd64. Образ, собранный на amd64-машине разработчика, не запускался (app в Restarting; «platform linux/amd64 does not match host linux/arm64»).
**Решение:** Все образы remlab собираем под `linux/arm64` кросс-сборкой: `docker buildx build --platform linux/arm64 --load` + эмуляция `tonistiigi/binfmt --install arm64` + builder `remlabx`. `deploy.sh` настраивает и делает это сам.
**Последствия:** Сборка на amd64 идёт под QEMU-эмуляцией (медленнее — минуты, приемлемо). Альтернатива на будущее — self-hosted arm64 GitHub Actions runner или нативная сборка на самом сервере (но там мало RAM — держим сборку локально). Migration-ready сохраняется: на другой arm64-хост образ переносится как есть; на amd64-хост — сменить `--platform` в `deploy.sh`.

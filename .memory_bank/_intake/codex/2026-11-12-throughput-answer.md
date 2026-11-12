## Топ-5

1. **Перейти на проверки по затронутому коду.** В каждом цикле: `vitest --changed <base>` либо `vitest related <files>`; pytest — конкретный тест/пакет плюс тесты, импортирующие изменённый модуль. Полные typecheck/lint/vitest/pytest/build/e2e — один раз в PR CI. Ожидаемый эффект: **−50–80% запусков очереди, обратная связь быстрее в 3–10 раз**. Риск: средний — неполная карта зависимостей; компенсируется обязательным полным CI. Сейчас pre-push специально исключает pnpm и pytest: [prepush_check.py:19](/home/pakar/igor/remlab/tools/ops/prepush_check.py:19), [prepush_check.py:126](/home/pakar/igor/remlab/tools/ops/prepush_check.py:126).

2. **Вынести полные проверки с pakardev.** GitHub уже запускает полный последовательный набор: [ci.yml:76](/home/pakar/igor/remlab/.github/workflows/ci.yml:76). Разделить его на параллельные jobs `typecheck+lint`, `vitest`, `build`, `e2e`, сделать PR-проверкой. На algor/common запускать только serial/1–2-worker затронутые pytest/vitest/typecheck, но из локального clone/worktree с локальными venv/node_modules; не через sshfs. Эффект: **−15–30% нагрузки/ожидания pakardev**. Риск: средний — дрейф окружений и лимиты Actions.

3. **Убрать refresh из рабочего окна.** Перенести старт с 10:40 на примерно **20:00 London**; при текущих 6:17 он завершится до экзамена в 03:00. Все шаги запускаются напрямую, не только через heavy-slot: [refresh_daily.sh:57](/home/pakar/igor/remlab/tools/scout/refresh_daily.sh:57); расписание — [crontab:3](/home/pakar/igor/remlab/infra/dev/crontab:3). Одновременно переделать watchdog на проверку предыдущей ночи: сейчас он ожидает дневной старт и проверяет в 15:30 [catalog-watchdog.sh:6](/home/pakar/igor/remlab/infra/server/scripts/catalog-watchdog.sh:6). Эффект в часы конфликта: **−20–40% ожидания**, освобождение до 6 ядер. Риск: средний — SLA свежести каталога. Просто ограничивать крон 2 ядрами невыгодно: он растянется.

4. **Сделать `--cores` истинным резервированием.** Для WebGL/SwiftShader требовать **7**, запретить явное `<6` для распознанного Playwright либо добавить профиль `webgl`. Автоопределение уже даёт 6 [heavy_slot.py:301](/home/pakar/igor/remlab/tools/ops/heavy_slot.py:301), но явный ключ его перекрывает [heavy_slot.py:1797](/home/pakar/igor/remlab/tools/ops/heavy_slot.py:1797). Добавить историю CPU p95 по типу команды и использовать `max(заявка, p95)` при допуске; текущая статистика хранит только память/время [heavy_slot.py:1731](/home/pakar/igor/remlab/tools/ops/heavy_slot.py:1731). Эффект: **−15–30% p95 wall-time/таймаутов**. Риск: низкий; формальное ожидание иногда вырастет, реальное завершение ускорится.

5. **Ограничить WIP, не число полезных работников.** Одновременно не более 5–6 работников в стадии тяжёлой проверки; остальные кодируют, ревьюят или готовят следующий маленький патч. Дедуплицировать одинаковую команду для одного tree hash. Отдельно устранить idle-spin `draft_service` и лишние tsserver: это около **2,3 ядра/15% машины**. Ожидаемо **−20–40% очередного p95**, риск средний.

## Не делать

- Не увеличивать слоты/overcommit и не уменьшать CPU margin: уже разрешены 8 слотов и 1,5× заявок [heavy_slot.py:203](/home/pakar/igor/remlab/tools/ops/heavy_slot.py:203), [heavy_slot.py:1129](/home/pakar/igor/remlab/tools/ops/heavy_slot.py:1129).
- Не применять blanket `pytest-xdist -n auto`: RAM ограничена; максимум `-n 2` при выданных ядрах.
- Не считать `--cores` CPU-лимитом: это заявка. Для реального ограничения крона нужен cgroup/`CPUQuota`.
- Не тратить время на уже имеющееся: tsc incremental включён [tsconfig.json:16](/home/pakar/igor/remlab/tsconfig.json:16), Playwright переиспользует локальный сервер [playwright.config.ts:29](/home/pakar/igor/remlab/playwright.config.ts:29). `pytest --lf` полезен только после падения.

## Чего не хватает

CPU p50/p95/peak по метке, распределения queue wait/arrival rate, CPU-профиля фаз refresh, пробных замеров локальных окружений algor/common, длительности/квоты GitHub Actions и бизнес-SLA свежести каталога. Ничего не менял.
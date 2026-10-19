---
tier: 2
topic: lessons-dev-ops
scope: Уроки DEV-машины — память, earlyoom, туннели, systemd
updated: 2026-10-19
source: manual
status: working
---
# Уроки DEV-ops

- **511 (18.10)** — `oom_score_adj` юнитов `systemd --user`: по умолчанию 200, минимум 100 без root (`DefaultOOMScoreAdjust`); маленький ssh в юните earlyoom оценивает выше гигабайтного процесса из крона. Перенос в юнит пользователя сам по себе повышает риск убийства; защита — `--avoid` в `/etc/default/earlyoom` (root). Источник: T-20261018-04, journalctl -u earlyoom.
- **512 (18.10)** — Playwright-пробы на DEV при тесной памяти: earlyoom первым снимает рендерер headless_shell (`oom_score_adj` 300 у
  Playwright) → «Target crashed» без следа в логе пробы, а не рендер-сервис. Перед пробой: `systemctl --user stop remlab-render.service` и
  закомментировать строку сторожа в crontab (`#PAUSE-<кто>`, бэкап `crontab -l`), после — вернуть; `?live=0` рендер не нужен. Источник: probe19
  (demo-16 шаг 3), `journalctl | grep earlyoom.*sending`.
- **514 (18.10)** — живые тесты прода запускать ТОЛЬКО по пути файла и сверять `--list`: фильтр playwright по имени совпал с именем папки worktree исполнителя, и дважды ушёл весь живой набор — лишние события демо и анонимные коллекции в счётчиках flat215 за 18.10 (БД не правили). Файл со своими `launchOptions` в `test.use` ЗАМЕНЯЕТ аргументы конфига — добавлять `LIVE_BROWSER_ARGS` из `e2e/live/browser.ts`, иначе Метрика в нём не блокируется. Источник: T-20261018-18, T-17.

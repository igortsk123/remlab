---
tier: 2
topic: lessons-dev-ops
scope: Уроки DEV-машины — память, earlyoom, туннели, systemd
updated: 2026-10-18
source: manual
status: working
---
# Уроки DEV-ops

- **511 (18.10)** — `oom_score_adj` юнитов `systemd --user`: по умолчанию 200, минимум 100 без root (`DefaultOOMScoreAdjust`); маленький ssh в юните earlyoom оценивает выше гигабайтного процесса из крона. Перенос в юнит пользователя сам по себе повышает риск убийства; защита — `--avoid` в `/etc/default/earlyoom` (root). Источник: T-20261018-04, journalctl -u earlyoom.

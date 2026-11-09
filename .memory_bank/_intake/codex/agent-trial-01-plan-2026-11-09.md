---
source: manual
topic: codex-agent-trial-01-plan
updated: 2026-11-09
---
# Вопрос Codex — подплан «загрузка → задание → серый тур» (09.11, ведущий common)

Прочитай `.memory_bank/plans/agent-trial-01-upload-grey-tour.md` (подплан по твоему же совету «ранний вертикальный срез»; мастер —
`.memory_bank/plans/MASTER-agent-trial.md`, твой прошлый ответ — `.memory_bank/_intake/codex/agent-trial-master-2026-11-09-answer.md`).
Сверь с кодом: `lib/mesh-review/auth.ts`, `tools/scout/mesh_audit_sync.py`, `lib/ratelimit/index.ts`, `modules/retention/run.ts`,
`caddy/Caddyfile`, `docker-compose.yml`, `db/schema.ts`, `db/init/`, `contracts/apartment.ts`, `tools/ops/heavy_slot.py`.

## Мой вывод (до тебя)
План годный, стартую T-A (прод-рантайм) сейчас — он не зависит от стенда; T-B — после влития стенда T-04. Сомнения:
1. Ограждение lease: `lease_token` + `attempt`; достаточно ли, чтобы поздний результат старого воркера не перетёр новый?
2. Файл ≤ 15 МБ через `formData` в Next на проде с 1 ГБ памяти app — не лучше ли потоковая запись на диск (busboy) сразу?
3. Таблица `trial_workers.breaker` + `queuePos` — не лишнее ли для v1 (страница может показывать просто «в очереди N»)?
4. Срок хранения: файл 14 дней, результат 90 — разумно для UK (GDPR, агент грузит план чужого дома)?
5. Чего не хватает в тестах T-A, чтобы ловить гонки и утечки файлов наружу?

Ответ — по-русски, кратко, по пунктам, со ссылками на файлы; только то, что стоит поменять в плане.

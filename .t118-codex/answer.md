Итог: направление правильное, но в текущем виде гарантия «ничего не теряется» не выполняется. Основные проблемы — удаление decisions, отсутствие идемпотентности notes, порядок двух вкладок и необратимая прополка после временного `ok`.

### Что принять

- Два журнала событий плюс денормализованное текущее состояние в `mesh_audit_items` — правильная архитектура. Считать последнее состояние через `DISTINCT ON` для каждого экрана и счётчика не стоит.
- `role → section` оставить чистой функцией в TS. В БД нужен только `role`; обязательно предусмотреть раздел «Другое / неизвестно».
- Сбрасывать mark/note при смене `generation_key` правильно. Уже существующий upsert отличает то же поколение от нового и сбрасывает поколенческое состояние: [repo-items.ts:64–110](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-audit/repo-items.ts:64).
- `poster_hd_url` как nullable read-model допустим.
- `sendBeacon` с JSON Blob и той же origin технически сработает с кукой. Но GET-вход ставит cookie как `SameSite=Lax`, а не всегда Strict: [session/route.ts:14](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/app/api/lab/mesh-review/session/route.ts:14), [session/route.ts:37](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/app/api/lab/mesh-review/session/route.ts:37).

### Что обязательно поменять

- Не доверять `reviewer` из тела запроса. Текущая cookie содержит только фиксированный HMAC и не кодирует человека: [auth.ts:10–32](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-review/auth.ts:10). После общей авторизации нужна отдельная подписанная HttpOnly-cookie с reviewer из серверного allowlist. Из неё сервер заполняет marks, notes, decisions и cancellations. Сейчас `decide()` reviewer вообще не передаёт, поэтому остаётся default `owner`: [repo-decisions.ts:16–38](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-audit/repo-decisions.ts:16).

- Для notes добавить `op_id UUID UNIQUE`. Сейчас `client_seq` сам по себе не защищает от дубля `fetch + beacon + retry`.

- `client_seq int = Date.now()` недопустим: миллисекунды эпохи уже около `1.8×10¹²`, а Postgres `integer` заканчивается на `2.1×10⁹`. Нужны:

  - `editor_id UUID`;
  - локальный монотонный `client_seq bigint`;
  - `op_id UUID UNIQUE`;
  - серверный `note_revision bigint`;
  - желательно `base_revision`.

  Сервер под `FOR UPDATE` присваивает revision. Внутри одной вкладки меньший seq журналируется, но не применяется. Между вкладками честного автоматического порядка нет: либо CAS по `base_revision` с конфликтом, либо явно документированный server-arrival-wins. Я рекомендую CAS; конфликт тоже писать в журнал с `applied=false`.

- Notes должны сохранять точный `body`, без `.trim()`. Образец сейчас обрезает текст и считает его отправленным до ответа сервера: [style_bench.py:278–287](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/tools/scout/style_bench.py:278). Это хороший UX-образец, но не гарантия доставки; там также используется `fetch(... keepalive)`, а не `sendBeacon`.

- На каждый input синхронно обновлять localStorage-outbox. Удалять запись только после подтверждения именно её `op_id`. Аналогичный outbox нужен и для кликов, если требование «каждое нажатие» буквальное.

- Старую note при уже сменившемся поколении не выбрасывать с одним 409: записать событие как `stale/applied=false`, не менять текущий `items.note`, вернуть понятный результат. Иначе beacon старой вкладки формально теряется.

- Bad и текущую note лучше отправлять одним запросом и записывать одной транзакцией. Иначе note-fetch может приехать после bad, а `decision.comment` получит предыдущую версию. Кроме того, note до 2000 символов не помещается в существующий decision comment ≤500: [021-mesh-audit-comment.sql:5](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/db/init/021-mesh-audit-comment.sql:5). Либо увеличить decision comment до 2000, либо хранить `decision_note_id` и отдавать мосту полный текст.

- Нельзя вызывать существующий `decide()`/`cancel()` «внутри той же транзакции»: обе функции сами открывают транзакцию и блокируют строку: [repo-decisions.ts:23](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-audit/repo-decisions.ts:23), [repo-decisions.ts:53](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-audit/repo-decisions.ts:53). Нужны внутренние `decideTx(tx, …)` / `cancelTx(tx, …)`.

- Mark API лучше принимать как команду с `op_id`, ожидаемым `state_version` и желаемым состоянием. Одного CAS по `generation_key` мало: две вкладки одного поколения могут перетирать друг друга. Каждый конфликтующий клик всё равно журналировать с `applied=false/reason='state_conflict'`.

### Decisions и мост — критическая дыра

Сейчас `cancel()` физически удаляет decision: [repo-decisions.ts:49–80](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-audit/repo-decisions.ts:49). Поэтому:

- `marks.decision_id` станет висячим;
- теряются reviewer, comment и время исходного решения;
- уникальность `(sku, manual_attempt_no)` освобождается только благодаря удалению.

Для нового контракта decisions удалять нельзя. Добавить `cancelled_at` как read-state и оставить append-only cancellation с собственными `idem_key`, `reviewer`, `created_at`. Уникальность активной попытки должна быть partial по `cancelled_at IS NULL`, либо полагаться на блокировку item.

Есть и существующая гонка двух курсоров:

- decisions отдаются максимум по 200: [repo-decisions.ts:95–111](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-audit/repo-decisions.ts:95);
- sync забирает одну страницу decisions, затем сразу cancellations: [mesh_audit_sync.py:137](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/tools/scout/mesh_audit_sync.py:137), [mesh_audit_sync.py:200](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/tools/scout/mesh_audit_sync.py:200).

Cancellation для decision №250 может быть применена раньше самого decision, после чего decision приедет следующим тиком и уже не будет отменён. Предпочтительно сделать единый упорядоченный workflow-event stream `decision|cancel`. Минимальный вариант — DEV-tombstone по `decision_id`, чтобы позднее решение не применялось.

### Семантика bad/pending/limit

Рекомендую разделить «человеческая отметка» и «состояние переделки»:

- `bad` всегда сохраняет mark.
- `status=open|redo_blocked`, attempts `<2` → создать `redo`.
- attempts `=2`, status open/blocked → создать `replace_needed`.
- `redo_requested|redo_queued|replace_needed` → нового decision нет, mark связывается с активным decision.
- Повторный bad всегда может снять mark. Если `redo_requested` — одновременно отменить decision. Если `redo_queued` — mark снять, но очередь не отменять; вернуть `reworkCancelled:false` и показать предупреждение.
- Аналогично `ok` можно сохранить при queued, но оно не должно считаться принятием, пока status не `open`.

Иначе обещание «повторное нажатие снимает» несовместимо с вашим вариантом 409.

Также серверное правило сейчас позволяет `replace_needed` при `redo_requested/redo_queued`, если уже две попытки: проверка pending есть только в ветке redo: [rules.ts:47–60](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-audit/rules.ts:47). Это нужно закрыть.

### Принятие и прополка

`mark='ok'` безопасно привязан к поколению, но небезопасно как немедленный сигнал прополке:

- удаление `shape.glb` необратимо;
- mark по требованиям обратим;
- для старого комплекта shape может уйти на следующем запуске, поскольку текущий minimum age считается от комплекта, не от `mark_at`: [prune_shapes.py:244–274](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/tools/scout/salad/prune_shapes.py:244).

Лучше отделить `review_mark=ok` от `accepted_for_prune_at`: выставлять последнее после grace-периода или явного завершения раздела.

Формула `mark='ok' OR seen_at IS NOT NULL` также опасна после явного clear: старый `seen_at` снова сделает меш принятым. Старая страница автоматически ставит seen всем карточкам страницы при монтировании: [MeshAuditSeen.tsx:9–14](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/components/lab/MeshAuditSeen.tsx:9). Нужен признак `mark_touched_at`; legacy seen учитывать только когда пользователь новой страницы ещё не касался mark.

### Остальные риски

- Абсолютную гарантию при закрытии вкладки дать нельзя: `sendBeacon() === true` означает только постановку в очередь браузера. Реальная гарантия здесь — at-least-once через localStorage-outbox и идемпотентный retry при следующем входе.
- `retireItems()` сейчас защищает только SKU с decisions: [repo-items.ts:139–149](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/lib/mesh-audit/repo-items.ts:139). Нужно определить политику для items с marks/notes и не получить случайный FK failure либо сироты.
- `posterHdUrl` пока неоткуда взять: генератор делает только 320×320: [mesh_audit_posters.py:27–29](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/tools/scout/mesh_audit_posters.py:27), а push отправляет только `posterUrl`: [mesh_audit_sync.py:267–275](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/tools/scout/mesh_audit_sync.py:267). Нужны отдельный рендер, публикация, Zod-поле и `upsertItems`.
- Миграция должна выдерживать повторный запуск: все init-файлы действительно применяются на каждом деплое: [apply-db-init.sh:10–11](/home/pakar/igor/remlab/.claude/worktrees/mesh-check-1112/tools/apply-db-init.sh:10). Добавьте CHECK для mark/body и идемпотентное создание именованных constraints.

### Обязательные тесты

Одних чистых правил недостаточно. Нужны Vitest integration-тесты с настоящим Postgres:

- параллельные клики двух вкладок, блокировка и `state_version`;
- повтор одного `op_id`, включая разные payload с тем же ключом;
- `fetch` и beacon одной note → одна строка;
- поздняя старая note не затирает новую;
- гонка note/mark и атомарный snapshot comment;
- смена поколения одновременно с mark/note;
- pending, limit, blocked, queued и replace_needed;
- cancel не удаляет decision;
- rollback всей операции при ошибке decision;
- legacy `seen`, clear и accepted-for-prune;
- повторное применение `035` на пустой и уже созданной схеме;
- клиентские fake-timer тесты: debounce, blur, pagehide, offline, восстановление outbox.

Отдельно в Python selftest обязательно воспроизвести «201+ decisions и cancellation для ещё не вычитанного decision» — Vitest этого мостового дефекта не поймает.
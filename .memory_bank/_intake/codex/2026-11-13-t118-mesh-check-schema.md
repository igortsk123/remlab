Ты — независимый советник по схеме БД и контрактам. Репозиторий remlab (TS strict, Next.js, Drizzle, Postgres), только чтение.
Отвечай по-русски, кратко, пунктами: что принять, что поменять, риски. Проверяй по коду, ссылайся на файлы:строки.

## Задача
Новая внутренняя страница «проверка мешей» рядом с `/lab/mesh-audit` (вход той же кукой `lib/mesh-review/auth.ts:reviewerOk`).
Жена владельца проверяет все ~2765 мешей: фото товара и снимок модели рядом, кнопки «ок» и «брак» (повторное нажатие снимает),
необязательный комментарий, сохраняется сам (через 1 с после ввода, при уходе из поля, при закрытии вкладки через sendBeacon),
разделы по типу товара (роль `mesh_audit_items.role`) со счётчиком «проверено N из M». ВСЁ должно сохраняться: каждое нажатие и
каждая версия комментария, ничего не теряется. «Кто проверяет» выбирается один раз при входе и пишется в журнал.

Существующее: `db/schema.ts:198-290` (mesh_audit_items/decisions/cancellations/batches), `lib/mesh-audit/repo-decisions.ts`
(decide/cancel одной транзакцией, `for update`, idem_key), `lib/mesh-audit/rules.ts` (checkDecision/checkCancel/isAccepted),
`lib/mesh-audit/repo-items.ts` (upsertItems: новое поколение сбрасывает seen_at/status; acceptedGenerationKeys для прополки
болванок на DEV, ADR-0233), мост DEV `tools/scout/mesh_audit_sync.py` (курсор решений → инбокс `mesh_rework_requests`;
платная переделка только волной `tools/scout/mesh_priority.py:take_top`). Образец «сохраняется само» — `app/api/lab/review/route.ts`.

## Мой вывод (проверь и покритикуй)
Миграция `db/init/035-mesh-audit-marks.sql` (идемпотентная, применяется на каждом деплое):
1. `mesh_audit_marks` append-only: id bigserial, item_id, sku, generation_key, mark ('ok'|'bad'|'clear'), reviewer text,
   decision_id int null (строка mesh_audit_decisions, если «брак» её создал), idem_key text unique, created_at.
   Индекс (item_id, id).
2. `mesh_audit_notes` append-only: id bigserial, item_id, sku, generation_key, body text (≤2000, пустая = стёрт), reviewer,
   client_seq int, created_at. Индекс (item_id, id).
3. В `mesh_audit_items` (read-model текущего состояния, для быстрых счётчиков): mark text null, mark_at, mark_by,
   note text null, note_seq int null, poster_hd_url text null. Раздел считаю в TS из role (одна таблица разделов в коде),
   колонку section не храню.
4. Семантика:
   - «ок»: строка marks + items.mark='ok' (CAS по generation_key: другая — 409 stale).
   - «брак»: та же транзакция вызывает существующую логику decide (redo, а после 2 переделок replace_needed) → строка
     mesh_audit_decisions → мост → инбокс. items.mark='bad'. Если лимит/pending — mark всё равно 'bad'? (сомневаюсь:
     предлагаю при pending — mark='bad' без новой decision; при limit — decision replace_needed).
   - повтор «брак» (снять): cancel() если статус позволяет (redo_requested/replace_needed) → mark 'clear'; если уже
     redo_queued — 409 «уже на переделке», mark остаётся 'bad'.
   - «ок» при текущем 'bad' с pending-решением: сначала отменить решение (как снятие), иначе 409.
   - idem_key = `${generationKey}:${mark}:${clientNonce}`; повтор того же запроса — 200 duplicate без второй строки.
   - Комментарий: каждая версия = строка notes; items.note обновляется только если client_seq > items.note_seq (поздно пришедшая
     старая версия журналится, но не затирает текущую). client_seq = Date.now() вкладки (монотонно в пределах вкладки;
     две вкладки — побеждает последняя по времени). Комментарий брака: при decide в comment кладу текущий items.note.
   - Новое поколение (upsertItems, другой generation_key): mark, mark_at, mark_by, note, note_seq → null (журналы остаются).
   - isAccepted: (`mark='ok'` OR seen_at not null) AND status='open'; acceptedGenerationKeys — то же в SQL.
     Новая страница seen_at не ставит.
5. sendBeacon: POST JSON (Blob application/json) на ту же ручку заметок; кука SameSite=Strict уходит (same-origin);
   originOk пропускает. Черновик ещё и в localStorage до подтверждения сервера.
6. Мост: поле posterHdUrl в push (optional), заметки мост пока не тянет (комментарий брака уходит через decisions.comment).

## Вопросы
- Хватает ли этого для «ни одно нажатие и ни одна буква не теряются»? Где дыры (гонки двух вкладок, порядок beacon/fetch,
  ретраи, 409 устаревшей вкладки при закрытии)?
- client_seq = Date.now() — нормально или нужен счётчик/версия на сервере?
- Хранить ли текущее состояние в items (денормализация) или считать последней строкой журнала (distinct on)?
- «брак» при pending/limit — как правильно?
- Сброс при новом поколении — не ломает ли что-то в мосте/прополке (ADR-0233)? Принятие по «ок» безопасно для прополки?
- Что ещё обязательно протестировать vitest-ом (repo-слой тестируется только чистыми функциями правил)?

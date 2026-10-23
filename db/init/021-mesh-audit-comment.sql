-- Комментарий владельца к браку меша (план mesh-audit-comments, владелец 23.10): «фото не дорезалось», «ножки пропали».
-- Необязательный, ≤ 500 символов; доезжает до DEV вместе с решением (курсор after_id) и ложится в журнал решений.
-- Добавочная nullable-колонка: старые строки не переписываются, прежняя версия приложения колонку не видит и не ломается.
-- Откат (только руками, после pg_dump): alter table mesh_audit_decisions drop column if exists comment;
alter table mesh_audit_decisions add column if not exists comment text
  constraint mesh_audit_decisions_comment_len check (char_length(comment) <= 500);

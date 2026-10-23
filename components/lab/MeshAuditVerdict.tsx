"use client";

// Кнопки решения в карточке меша: «переделать» / «нужна замена» → поле «что не так» (необязательно, план mesh-audit-comments,
// владелец 23.10) → «Отправить»; «Назад» — без решения. Отмена случайного клика уносит комментарий вместе с решением.

import { useState } from "react";
import { Button } from "@/components/base/buttons/button";
import { TextArea } from "@/components/base/textarea/textarea";
import { COMMENT_MAX } from "@/lib/mesh-audit/decision-body";
import type { Verdict } from "@/lib/mesh-audit/rules";

interface Props {
  canRedo: boolean;
  canReplace: boolean;
  canCancel: boolean;
  busy: boolean;
  sentComment: string | null; // комментарий отправленного решения — виден, пока решение можно отменить
  onDecide: (verdict: Verdict, comment: string) => Promise<boolean>;
  onUndo: () => void;
}

export function MeshAuditVerdict({ canRedo, canReplace, canCancel, busy, sentComment, onDecide, onUndo }: Props) {
  const [draft, setDraft] = useState<Verdict | null>(null);
  const [comment, setComment] = useState("");

  async function send() {
    if (!draft) return;
    if (await onDecide(draft, comment)) {
      setDraft(null);
      setComment("");
    }
  }

  if (draft) {
    return (
      <div className="flex flex-col gap-2">
        <TextArea
          rows={3}
          maxLength={COMMENT_MAX}
          value={comment}
          onChange={setComment}
          placeholder="Что не так? Необязательно"
          aria-label="Что не так с мешем (необязательно)"
        />
        {comment.length > COMMENT_MAX - 100 && (
          <span className="text-xs text-tertiary">
            {comment.length}/{COMMENT_MAX}
          </span>
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" color="primary" isDisabled={busy} isLoading={busy} onClick={() => void send()}>
            {draft === "redo" ? "Отправить на переделку" : "Отправить: нужна замена"}
          </Button>
          <Button size="sm" color="tertiary" isDisabled={busy} onClick={() => setDraft(null)}>
            Назад
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {canCancel && sentComment && <p className="text-xs text-secondary">Комментарий: {sentComment}</p>}
      <div className="flex flex-wrap gap-2">
        {canRedo && (
          <Button size="sm" color="primary" isDisabled={busy} onClick={() => setDraft("redo")}>
            Переделать
          </Button>
        )}
        {canReplace && (
          <Button size="sm" color="secondary" isDisabled={busy} onClick={() => setDraft("replace_needed")}>
            Нужна замена товара/фото
          </Button>
        )}
        {canCancel && (
          <Button size="sm" color="tertiary" isDisabled={busy} isLoading={busy} onClick={onUndo}>
            Отменить (нажал случайно)
          </Button>
        )}
      </div>
    </div>
  );
}

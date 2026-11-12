"use client";

// Нажатие «ок»/«брак» — общее для карточки и окна увеличения: запрос, занятость, текст ошибки. Перед нажатием досылается
// комментарий (beforePress), чтобы решение о переделке ушло с последней версией текста.

import { useState } from "react";
import { sendPress, type Press } from "@/lib/mesh-audit/check-client";
import type { AuditItemView } from "@/lib/mesh-audit/types";

const NOTICE: Record<string, string> = {
  queued_kept: "отметка снята, но переделка уже в работе и продолжится",
  queued: "отметка снята, но переделка уже в работе и продолжится",
  state_conflict: "в другой вкладке отметку уже поменяли, показываю, как сейчас",
  stale: "модель уже заменена, обновите страницу",
};

export function useMeshPress(item: AuditItemView, reviewer: string, onChange: (it: AuditItemView) => void, beforePress?: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function press(p: Press) {
    if (busy) return; // двойной тап не шлёт второе нажатие, пока первое не вернулось
    setBusy(true);
    setError(null);
    await beforePress?.().catch(() => undefined);
    const r = await sendPress(item, p, reviewer);
    if (r.kind === "ok") {
      onChange(r.item);
      if (r.reason) setError(NOTICE[r.reason] ?? null);
    } else if (r.kind === "login") {
      setError("вход истёк, обновите страницу");
    } else {
      if (r.item) onChange(r.item); // свежая карточка с сервера: кнопки показывают правду
      setError((r.code && NOTICE[r.code]) || r.message);
    }
    setBusy(false);
  }

  return { busy, error, press: (p: Press) => void press(p) };
}

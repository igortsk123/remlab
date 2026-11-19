"use client";

// Нажатие «ок»/«не ок» карточки вырезки: запрос, занятость, текст ошибки. Перед нажатием досылается «что не так», чтобы в журнале
// отметка и текст шли в правильном порядке.

import { useState } from "react";
import { sendPress } from "@/lib/cutout-check/client";
import type { Mark } from "@/lib/cutout-check/rules";
import type { CutoutItemView } from "@/lib/cutout-check/types";

const NOTICE: Record<string, string> = {
  state_conflict: "в другой вкладке отметку уже поменяли, показываю как сейчас / changed in another tab, showing current",
  stale: "вырезка уже заменена, обновите страницу / cutout replaced, reload the page",
  race: "уже нажато, обновите страницу / already pressed, reload the page",
};

export function useCutoutPress(item: CutoutItemView, reviewer: string, onChange: (it: CutoutItemView) => void, beforePress?: () => Promise<void>) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function press(p: Mark) {
    if (busy) return; // двойной тап не шлёт второе нажатие, пока первое не вернулось
    setBusy(true);
    setError(null);
    await beforePress?.().catch(() => undefined);
    const r = await sendPress(item, p, reviewer);
    if (r.kind === "ok") {
      onChange(r.item);
    } else if (r.kind === "login") {
      setError("вход истёк, обновите страницу / session expired, reload");
    } else {
      if (r.item) onChange(r.item); // свежая карточка с сервера: кнопки показывают правду
      setError((r.code && NOTICE[r.code]) || r.message);
    }
    setBusy(false);
  }

  return { busy, error, press: (p: Mark) => void press(p) };
}

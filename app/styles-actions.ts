"use server";

import { z } from "zod";
import { getSessionId } from "@/lib/session";
import { track } from "@/lib/analytics";
import { styleResultRepo } from "@/modules/style/repository";
import { STYLES, type StyleId } from "@/lib/styles/quiz";

const styleId = z.string().refine((s): s is StyleId => s in STYLES, "неизвестный стиль");

// Финал игры «узнай свой вкус»: сохраняем определившийся стиль за сессией (карточка
// «Мой стиль» в /lab; повторная игра перезаписывает) и фиксируем событие воронки.
// Серверный экшен — ключ PostHog не уезжает в браузер, distinctId = анонимная сессия.
export async function completeQuiz(style: string): Promise<void> {
  const parsed = styleId.safeParse(style);
  if (!parsed.success) {
    console.error("completeQuiz: неизвестный стиль", style);
    return;
  }
  const sessionId = await getSessionId();
  await styleResultRepo().upsert(sessionId, parsed.data);
  await track("quiz_completed", sessionId, { style: parsed.data });
}

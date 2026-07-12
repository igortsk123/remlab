"use server";

import { getSessionId } from "@/lib/session";
import { track } from "@/lib/analytics";

// Мини-воронка раздела «Стили»: фиксируем завершение игры и определившийся стиль.
// Серверный экшен (клиентский StyleQuiz дёргает его на экране результата) — ключ PostHog
// не уезжает в браузер, distinctId = анонимная сессия. Без ключа track() — no-op.
export async function trackQuizCompleted(style: string): Promise<void> {
  const sessionId = await getSessionId();
  await track("quiz_completed", sessionId, { style });
}

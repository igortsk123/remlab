// Доставка сигналов менеджеру (план b2b-02). Зовётся таймером раз в минуту
// (`/api/internal/signals/flush`) и после событий: сперва превращает созревшие сводки выбора в
// сигналы, потом отправляет очередь. Повтор при сбое сети/Telegram — 1, 5, 15, 60 минут, затем
// `failed`; нет бота или менеджер не подключён — `no_channel` (видно на странице менеджера).

import { statusKeyboard, tgCall, type TgFetch } from "@/lib/telegram/api";
import { SUMMARY_DELAY_MS, sendStore } from "@/modules/sends/service";
import { summaryText } from "@/modules/sends/signals";
import type { SendStore } from "@/modules/sends/types";

export const MANAGER_TG_TOKEN = () => process.env.MANAGER_TG_TOKEN || "";
const BACKOFF_MIN = [1, 5, 15, 60];

export type FlushReport = { summaries: number; sent: number; retried: number; failed: number; noChannel: number };

export async function flushSignals(now = new Date(), store: SendStore = sendStore(), fetchImpl?: TgFetch): Promise<FlushReport> {
  const r: FlushReport = { summaries: 0, sent: 0, retried: 0, failed: 0, noChannel: 0 };

  for (const s of await store.dueSummaries(now, 50)) {
    const since = (s.summaryDueAt?.getTime() ?? now.getTime()) - SUMMARY_DELAY_MS;
    const recent = (await store.events(s.id, 100)).filter((e) => e.createdAt.getTime() >= since);
    await store.updateSend(s.id, { summaryDueAt: null });
    const text = summaryText(s, recent);
    if (text) {
      await store.enqueue({ sendId: s.id, managerId: s.managerId, kind: "summary", text, nextAt: now });
      r.summaries++;
    }
  }

  const token = MANAGER_TG_TOKEN();
  for (const o of await store.dueOutbox(now, 100)) {
    const [m, s] = await Promise.all([store.managerById(o.managerId), store.getSend(o.sendId)]);
    if (!token || !m?.tgChatId || !m.active || !s) {
      await store.markOutbox(o.id, { status: "no_channel", lastError: !token ? "no_token" : "manager_not_connected" });
      r.noChannel++;
      continue;
    }
    const reply = s.originMessageId && s.originChatId === m.tgChatId
      ? { reply_parameters: { message_id: s.originMessageId, allow_sending_without_reply: true } } : {};
    const res = await tgCall(token, "sendMessage", { chat_id: m.tgChatId, text: o.text, reply_markup: statusKeyboard(s.id), ...reply }, fetchImpl);
    if (res.ok) {
      await store.markOutbox(o.id, { status: "sent", attempts: o.attempts + 1, sentAt: now, lastError: null });
      r.sent++;
    } else if (res.retry && o.attempts < BACKOFF_MIN.length) {
      const next = new Date(now.getTime() + BACKOFF_MIN[o.attempts]! * 60_000);
      await store.markOutbox(o.id, { attempts: o.attempts + 1, nextAt: next, lastError: res.error });
      r.retried++;
    } else {
      await store.markOutbox(o.id, { status: "failed", attempts: o.attempts + 1, lastError: res.error });
      r.failed++;
    }
  }
  return r;
}

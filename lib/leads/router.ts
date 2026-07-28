// Маршрутизация лид-канала (П7). Карточка заявки → служебный TG-бот; ответ владельца (реплаем в
// служебном боте) → клиенту в ЕГО канал: письмо / клиентский TG-бот / MAX (пока деградация).
// Чистые format-функции тестируются; сетевые вызовы — через tg.ts/mailer.ts (no-op без токенов).

import { CALC_META, type CalcKind } from "@/lib/estimate/companions";
import type { Lead } from "@/modules/leads/repository";
import { leadRepo } from "@/modules/leads/repository";
import { ADMIN_TG_CHAT, ADMIN_TG_TOKEN, CLIENT_TG_TOKEN, tgSend } from "./tg";
import { sendLeadEmail } from "./mailer";

const CHANNEL_LABEL: Record<string, string> = { email: "почта", tg: "Телеграм", max: "MAX" };

// Карточка заявки для служебного бота: владелец должен сразу видеть, от кого и о чём.
export function formatLeadCard(lead: Lead): string {
  const kind = lead.kind && (CALC_META as Record<string, { title: string }>)[lead.kind]?.title;
  const lines = [
    `Заявка #${lead.leadNo ?? "?"} · ${CHANNEL_LABEL[lead.channel] ?? lead.channel}`,
    lead.city ? `Город: ${lead.city}` : null,
    lead.ipRegion ? `Регион по IP: ${lead.ipRegion}` : null,
    kind ? `Калькулятор: ${kind}` : null,
    lead.email ? `E-mail: ${lead.email}` : null,
    lead.url ? `Товар: ${lead.url}` : null,
    "",
    "Ответьте РЕПЛАЕМ на это сообщение — уйдёт клиенту.",
  ];
  return lines.filter((l) => l != null).join("\n");
}

// Подпись пересылаемого сообщения клиента (входящие из клиентского бота).
export function formatIncoming(lead: Lead, text: string): string {
  return `Заявка #${lead.leadNo ?? "?"} · клиент пишет:\n${text}\n\nОтветьте реплаем — уйдёт клиенту.`;
}

// Новая заявка: карточка владельцу в служебный бот + маппинг для будущего reply.
export async function notifyAdminOfLead(lead: Lead): Promise<void> {
  const sent = await tgSend(ADMIN_TG_TOKEN(), ADMIN_TG_CHAT(), formatLeadCard(lead));
  if (sent) await leadRepo().addMessage({ leadId: lead.id, direction: "in", text: "(заявка)", adminTgMessageId: sent.message_id });
}

// Ответ владельца → канал заявки. true = доставлено (или принято к доставке).
export async function replyToLead(lead: Lead, text: string): Promise<boolean> {
  if (lead.channel === "email" && lead.email) {
    return sendLeadEmail(lead.email, `remont-lab: нашли варианты по вашей заявке #${lead.leadNo ?? ""}`.trim(), text);
  }
  if (lead.channel === "tg" && lead.messengerChatId) {
    return (await tgSend(CLIENT_TG_TOKEN(), lead.messengerChatId, text)) != null;
  }
  // MAX: API-возможности проверим при получении токена (деградация — вручную).
  return false;
}

// Kind-guard для карточки (валидация не строгая: карточка — не граница доверия, только текст).
export function isCalcKind(k: string | undefined): k is CalcKind {
  return k === "oboi" || k === "plitka" || k === "kraska" || k === "laminat";
}

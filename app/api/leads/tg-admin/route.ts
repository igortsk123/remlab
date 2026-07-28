import { NextResponse } from "next/server";
import { leadRepo } from "@/modules/leads/repository";
import { replyToLead } from "@/lib/leads/router";
import { ADMIN_TG_CHAT, ADMIN_TG_TOKEN, TG_WEBHOOK_SECRET, tgSend, type TgUpdate } from "@/lib/leads/tg";
import { track } from "@/lib/analytics";

export const runtime = "nodejs";

// Вебхук СЛУЖЕБНОГО TG-бота (П7): владелец отвечает РЕПЛАЕМ на карточку заявки/пересылку —
// ответ маршрутизируется клиенту в его канал (почта / клиентский TG-бот / MAX). Секрет —
// заголовок X-Telegram-Bot-Api-Secret-Token (задаётся в setWebhook). Без токенов — вебхук не настроен.
export async function POST(req: Request): Promise<Response> {
  const secret = TG_WEBHOOK_SECRET();
  if (secret && req.headers.get("x-telegram-bot-api-secret-token") !== secret) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }
  const update = (await req.json().catch(() => null)) as TgUpdate | null;
  const msg = update?.message;
  // Реагируем только на реплаи с текстом в служебном чате.
  if (!msg?.text || !msg.reply_to_message) return NextResponse.json({ ok: true });

  const lead = await leadRepo().byAdminMsg(msg.reply_to_message.message_id);
  if (!lead) {
    await tgSend(ADMIN_TG_TOKEN(), msg.chat.id, "Не нашёл заявку по этому сообщению — ответьте реплаем на карточку заявки.");
    return NextResponse.json({ ok: true });
  }

  const delivered = await replyToLead(lead, msg.text);
  await leadRepo().addMessage({ leadId: lead.id, direction: "out", text: msg.text });
  await tgSend(
    ADMIN_TG_TOKEN(),
    ADMIN_TG_CHAT() || msg.chat.id,
    delivered
      ? `✓ Отправлено клиенту (заявка #${lead.leadNo ?? "?"}, канал: ${lead.channel}).`
      : `✗ Не доставлено (заявка #${lead.leadNo ?? "?"}): канал «${lead.channel}» не активирован или клиент не привязал чат.`,
  );
  await track("lead_replied", lead.sessionId ?? "admin", { channel: lead.channel, delivered });
  return NextResponse.json({ ok: true });
}

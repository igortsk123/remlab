import { NextResponse } from "next/server";
import { leadRepo } from "@/modules/leads/repository";
import { formatIncoming } from "@/lib/leads/router";
import { ADMIN_TG_CHAT, ADMIN_TG_TOKEN, CLIENT_TG_TOKEN, TG_WEBHOOK_SECRET, tgSend, type TgUpdate } from "@/lib/leads/tg";

export const runtime = "nodejs";

// Вебхук КЛИЕНТСКОГО TG-бота (П7): «/start <id заявки>» связывает чат клиента с заявкой (бот не может
// писать первым — ограничение платформы, поэтому deep-link + Start); прочие сообщения пересылаются
// владельцу в служебный бот с подписью заявки (ответ — реплаем там же).
export async function POST(req: Request): Promise<Response> {
  const secret = TG_WEBHOOK_SECRET();
  if (secret && req.headers.get("x-telegram-bot-api-secret-token") !== secret) {
    return NextResponse.json({ ok: false }, { status: 401 });
  }
  const update = (await req.json().catch(() => null)) as TgUpdate | null;
  const msg = update?.message;
  if (!msg?.text) return NextResponse.json({ ok: true });
  const chatId = String(msg.chat.id);
  const repo = leadRepo();

  const start = /^\/start\s+([\w-]+)/.exec(msg.text);
  if (start) {
    const lead = await repo.get(start[1]!);
    if (lead) {
      await repo.setChat(lead.id, chatId);
      await tgSend(CLIENT_TG_TOKEN(), chatId, `Вы на связи по заявке #${lead.leadNo ?? ""}: ищем, где дешевле. Напишем сюда, когда найдём. Можно писать вопросы прямо в этот чат.`);
      const sent = await tgSend(ADMIN_TG_TOKEN(), ADMIN_TG_CHAT(), `Заявка #${lead.leadNo ?? "?"}: клиент подключил Телеграм ✓`);
      if (sent) await repo.addMessage({ leadId: lead.id, direction: "in", text: "(клиент подключил TG)", adminTgMessageId: sent.message_id });
    } else {
      await tgSend(CLIENT_TG_TOKEN(), chatId, "Здравствуйте! Оставьте заявку на remont-lab.online — и возвращайтесь по кнопке из неё.");
    }
    return NextResponse.json({ ok: true });
  }

  // Входящее от клиента → пересылка владельцу с подписью заявки (reply-маппинг сохраняем).
  const lead = await repo.byChat(chatId);
  if (lead) {
    const sent = await tgSend(ADMIN_TG_TOKEN(), ADMIN_TG_CHAT(), formatIncoming(lead, msg.text));
    await repo.addMessage({ leadId: lead.id, direction: "in", text: msg.text, adminTgMessageId: sent?.message_id });
  } else {
    await tgSend(CLIENT_TG_TOKEN(), chatId, "Не вижу вашей заявки. Оставьте её на remont-lab.online и вернитесь по кнопке из неё.");
  }
  return NextResponse.json({ ok: true });
}

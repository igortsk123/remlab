// Тонкий клиент Telegram Bot API (П7): два бота — СЛУЖЕБНЫЙ (карточки заявок владельцу, ответы
// реплаем) и КЛИЕНТСКИЙ (диалог с клиентом). Токены в env; без токена — no-op (деградация).

const API = "https://api.telegram.org";

export const ADMIN_TG_TOKEN = () => process.env.LEADS_ADMIN_TG_TOKEN || "";
export const ADMIN_TG_CHAT = () => process.env.LEADS_ADMIN_TG_CHAT_ID || "";
export const CLIENT_TG_TOKEN = () => process.env.LEADS_CLIENT_TG_TOKEN || "";
export const TG_WEBHOOK_SECRET = () => process.env.LEADS_TG_WEBHOOK_SECRET || "";

export type TgSent = { message_id: number } | null;

// Отправка сообщения ботом. Возвращает message_id (для reply-маппинга) или null (нет токена/ошибка).
export async function tgSend(token: string, chatId: string | number, text: string): Promise<TgSent> {
  if (!token || !chatId) return null;
  try {
    const res = await fetch(`${API}/bot${token}/sendMessage`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ chat_id: chatId, text }),
      signal: AbortSignal.timeout(10000),
    });
    const data = await res.json();
    return data?.ok && data.result?.message_id ? { message_id: data.result.message_id } : null;
  } catch {
    return null;
  }
}

// Update от Telegram (минимально нужные поля).
export type TgUpdate = {
  message?: {
    message_id: number;
    text?: string;
    chat: { id: number };
    reply_to_message?: { message_id: number };
  };
};

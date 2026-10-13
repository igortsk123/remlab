// Бот менеджеров застройщика (план b2b-02, ADR-0257). Без состояния на нашей стороне:
//  • подключение — менеджер делится СВОИМ номером (contact.user_id == from.id), номер ищется среди
//    заведённых застройщиком; только личный чат;
//  • «Новая ссылка» → бот просит заметку ответом (force_reply); ответ на эту просьбу = новая
//    отправка, ссылка приходит ответом на заметку. Текст заметки («Вася, после показа») мы НЕ храним —
//    только id сообщения, чтобы сигналы потом приходили ответом на него;
//  • кнопки статуса под сигналами — только владельцу отправки.

import { managerStatus } from "@/contracts/send";
import { tgCall, statusKeyboard, type TgFetch } from "@/lib/telegram/api";
import { apartmentsOf, sendUrl } from "@/modules/sends/apartments";
import { normalizePhone } from "@/modules/sends/phone";
import { createSend, sendStore, setStatusByManager } from "@/modules/sends/service";
import type { SendStore } from "@/modules/sends/types";

export type BotUpdate = {
  update_id: number;
  message?: {
    message_id: number;
    from?: { id: number };
    chat: { id: number; type: string };
    text?: string;
    contact?: { phone_number: string; user_id?: number };
    reply_to_message?: { message_id: number; from?: { is_bot?: boolean }; text?: string };
  };
  callback_query?: { id: string; from: { id: number }; data?: string };
};

export const NEW_LINK = "Новая ссылка";
export const NOTE_PROMPT = "Кому ссылка? Напишите заметку для себя ответом на это сообщение";
const MENU = { keyboard: [[{ text: NEW_LINK }]], resize_keyboard: true };
const ASK_PHONE = { keyboard: [[{ text: "Поделиться номером", request_contact: true }]], resize_keyboard: true, one_time_keyboard: true };

export async function handleBotUpdate(u: BotUpdate, token: string, store: SendStore = sendStore(), f?: TgFetch, now = new Date()): Promise<void> {
  if (!(await store.firstSeenUpdate(u.update_id))) return; // Telegram повторил апдейт
  const say = (chat: number, text: string, extra: Record<string, unknown> = {}) => tgCall(token, "sendMessage", { chat_id: chat, text, ...extra }, f);

  const cq = u.callback_query;
  if (cq) {
    const [tag, sendId, st] = (cq.data ?? "").split(":");
    const m = await store.managerByTgUser(cq.from.id);
    const to = managerStatus.safeParse(st);
    const ok = tag === "st" && !!m && to.success && (await setStatusByManager(m, sendId ?? "", to.data, now, store));
    await tgCall(token, "answerCallbackQuery", { callback_query_id: cq.id, text: ok ? "Статус сохранён" : "Не получилось — это не ваша ссылка?" }, f);
    return;
  }

  const msg = u.message;
  if (!msg?.from || msg.chat.type !== "private") return;
  const chat = msg.chat.id;
  const me = await store.managerByTgUser(msg.from.id);

  if (msg.contact) {
    if (msg.contact.user_id !== msg.from.id) return void (await say(chat, "Поделитесь своим номером кнопкой ниже.", { reply_markup: ASK_PHONE }));
    const phone = normalizePhone(msg.contact.phone_number);
    const found = phone ? await store.managersByConnectPhone(phone) : [];
    if (found.length !== 1) return void (await say(chat, "Номер не найден среди менеджеров застройщика. Попросите добавить вас и нажмите /start."));
    await store.bindTelegram(found[0]!.id, msg.from.id, chat);
    return void (await say(chat, `Готово, ${found[0]!.displayName}. После показа нажмите «${NEW_LINK}».`, { reply_markup: MENU }));
  }
  if (!me) return void (await say(chat, "Здравствуйте! Чтобы получать ссылки для покупателей, поделитесь номером телефона.", { reply_markup: ASK_PHONE }));

  if (msg.text === NEW_LINK) {
    return void (await say(chat, `${NOTE_PROMPT} (например «Вася, после показа»). Заметку мы не сохраняем — она остаётся только у вас в чате.`,
      { reply_markup: { force_reply: true, input_field_placeholder: "Вася, после показа" } }));
  }
  if (msg.reply_to_message?.from?.is_bot && msg.reply_to_message.text?.startsWith(NOTE_PROMPT)) {
    const apts = apartmentsOf(me.partnerId);
    const s = apts.length === 1 ? await createSend(me, apts[0]!.id, "bot", { chatId: chat, messageId: msg.message_id }, now, store) : null;
    if (!s) return void (await say(chat, "Не удалось создать ссылку: у застройщика не одна квартира в демо — напишите нам.", { reply_markup: MENU }));
    return void (await say(chat, `Ссылка для покупателя (${apts[0]!.title}):\n${sendUrl(s.id)}\n\nПерешлите её клиенту. Когда он откроет и выберет — напишу сюда ответом на вашу заметку.`,
      { reply_parameters: { message_id: msg.message_id }, reply_markup: statusKeyboard(s.id) }));
  }
  await say(chat, `Чтобы сделать ссылку покупателю, нажмите «${NEW_LINK}».`, { reply_markup: MENU });
}

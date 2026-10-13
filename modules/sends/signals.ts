// Тексты сигналов менеджеру (план b2b-02). Сигнал приходит ОТВЕТОМ на его сообщение «Вася, кв 215»,
// поэтому имя клиента в тексте не нужно и у нас не хранится. Для ссылок со страницы менеджера
// (без исходного сообщения) — короткий номер ссылки: заметку менеджер держит у себя в браузере.

import type { AlternativeReason, BuyerEvent } from "@/contracts/send";
import type { Send, SendEventRow } from "@/modules/sends/types";

const REASON: Record<AlternativeReason, string> = {
  price: "дорого",
  style: "не тот стиль",
  space: "не помещается / тесно",
  color: "другой цвет",
  other: "другое",
};

export const shortRef = (id: string) => id.slice(0, 4).toUpperCase();

export function money(sum: number, market: string): string {
  const n = Math.round(sum).toLocaleString("ru-RU").replace(/ /g, " ");
  return market === "uk" ? `£${n}` : `${n} ₽`;
}

function head(send: Send): string {
  return send.originMessageId ? "" : `Ссылка ${shortRef(send.id)} · `;
}

export function openText(send: Send, repeat: boolean): string {
  return `${head(send)}${repeat ? "Клиент снова открыл свою квартиру" : "Клиент открыл ссылку на квартиру"} (${send.apartmentId}).`;
}

export function contactText(send: Send, ev: BuyerEvent): string {
  const what = ev.purpose === "mortgage" ? "ипотеку/рассрочку" : "консультацию";
  const via = ev.channel === "whatsapp" ? "WhatsApp" : ev.channel === "telegram" ? "Telegram" : ev.channel === "phone" ? "звонок" : "";
  const sum = ev.sum ? `, выбрано на ${money(ev.sum, send.market)}` : "";
  const variant = ev.variant ? ` Вариант «${ev.variant}».` : "";
  const items = ev.items?.length ? ` В комнате: ${ev.items.slice(0, 5).join(", ")}.` : "";
  return `${head(send)}Клиент нажал «${what}»${via ? ` (${via})` : ""}${sum}.${variant}${items} Это клик, не звонок: если не написал — напишите ему сами.`;
}

export function alternativeText(send: Send, ev: BuyerEvent): string {
  return `${head(send)}Клиент просит другой вариант: ${REASON[ev.reason ?? "other"]}.`;
}

/** Сводка выбора: последнее состояние по событиям «смотрел вариант / заменил предмет». */
export function summaryText(send: Send, recent: SendEventRow[]): string | null {
  const last = recent.find((e) => e.kind === "variant_view" || e.kind === "item_swap");
  if (!last) return null;
  const p = last.payload as BuyerEvent;
  const swaps = recent.filter((e) => e.kind === "item_swap").length;
  const parts = [p.variant ? `вариант «${p.variant}»` : null, swaps ? `замен: ${swaps}` : null, p.sum ? `на ${money(p.sum, send.market)}` : null];
  const items = (p.items ?? []).slice(0, 5).join(", ");
  return `${head(send)}Клиент выбирает: ${parts.filter(Boolean).join(", ")}${items ? `. Сейчас в комнате: ${items}` : ""}.`;
}

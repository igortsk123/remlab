// Тексты сигналов менеджеру (план b2b-02). Сигнал приходит ОТВЕТОМ на его сообщение «Вася, кв 215»,
// поэтому имя клиента в тексте не нужно и у нас не хранится. Для ссылок со страницы менеджера
// (без исходного сообщения) — короткий номер ссылки: заметку менеджер держит у себя в браузере.

import { QUIZ_CHILD_RU, QUIZ_COLOUR_RU, QUIZ_HOUSEHOLD_RU, QUIZ_KIDS_RU, QUIZ_STYLE_RU, type QuizStyle } from "@/contracts/quiz";
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
  // комната без выбранного стиля молча показала похожий (style-fallback-01) — менеджер видит правду
  const sub = ev.chosen && ev.shown_style && ev.chosen !== ev.shown_style
    ? ` Выбран стиль «${QUIZ_STYLE_RU[ev.chosen]}», в этой комнате его нет — показан похожий «${QUIZ_STYLE_RU[ev.shown_style]}».` : "";
  return `${head(send)}Клиент нажал «${what}»${via ? ` (${via})` : ""}${sum}.${variant}${sub}${items} Это клик, не звонок: если не написал — напишите ему сами.`;
}

export function alternativeText(send: Send, ev: BuyerEvent): string {
  return `${head(send)}Клиент просит другой вариант: ${REASON[ev.reason ?? "other"]}.`;
}

/** Прошёл опрос-знакомство: что понравилось, кто живёт, цвета, что показали и что выбрал. Без имени (ADR-0330 п.4). */
export function quizText(send: Send, ev: BuyerEvent): string {
  const q = (id: QuizStyle) => `«${QUIZ_STYLE_RU[id]}»`;
  // при «с детьми» в скобках — сколько детей и возраст: «с детьми (двое детей; 3–7 лет)» (T-20261106-94)
  const kid = [ev.kids ? QUIZ_KIDS_RU[ev.kids] : null, ev.childAge?.length ? ev.childAge.map((a) => QUIZ_CHILD_RU[a]).join(", ") : null].filter(Boolean);
  const ages = kid.length ? ` (${kid.join("; ")})` : "";
  const parts = [
    ev.picked?.length ? `понравились ${ev.picked.map(q).join(", ")}` : null,
    ev.household?.length ? `живут: ${ev.household.map((h) => QUIZ_HOUSEHOLD_RU[h] + (h === "child" ? ages : "")).join(", ")}` : null,
    ev.colours?.length ? `цвета: ${ev.colours.map((c) => QUIZ_COLOUR_RU[c]).join(", ")}` : null,
  ].filter(Boolean);
  const shown = ev.result?.length ? ` Показали: ${ev.result.map((id) => QUIZ_STYLE_RU[id]).join(", ")}` : "";
  const chosen = ev.chosen ? `${shown ? " — в" : " В"}ыбрал ${q(ev.chosen)}` : "";
  return `${head(send)}Клиент прошёл знакомство${parts.length ? `: ${parts.join("; ")}` : ""}.${shown}${chosen}${shown || chosen ? "." : ""}`;
}

/** Сводка выбора: последнее состояние по событиям «смотрел вариант / заменил предмет» и последний стиль после опроса. */
export function summaryText(send: Send, recent: SendEventRow[]): string | null {
  const last = recent.find((e) => e.kind === "variant_view" || e.kind === "item_swap");
  const style = (recent.find((e) => e.kind === "style_change")?.payload as BuyerEvent | undefined)?.chosen;
  if (!last && !style) return null;
  const p = (last?.payload ?? {}) as BuyerEvent;
  const swaps = recent.filter((e) => e.kind === "item_swap").length;
  const parts = [style ? `сменил стиль на «${QUIZ_STYLE_RU[style]}»` : null, p.variant ? `вариант «${p.variant}»` : null, swaps ? `замен: ${swaps}` : null,
    p.sum ? `на ${money(p.sum, send.market)}` : null];
  const items = (p.items ?? []).slice(0, 5).join(", ");
  return `${head(send)}Клиент выбирает: ${parts.filter(Boolean).join(", ")}${items ? `. Сейчас в комнате: ${items}` : ""}.`;
}

// Тексты сигналов менеджеру (план b2b-02). Сигнал приходит ОТВЕТОМ на его сообщение «Вася, кв 215»,
// поэтому имя клиента в тексте не нужно и у нас не хранится. Для ссылок со страницы менеджера
// (без исходного сообщения) — короткий номер ссылки: заметку менеджер держит у себя в браузере.

import type { QuizChildAge, QuizColour, QuizHousehold, QuizStyle } from "@/contracts/quiz";
import type { AlternativeReason, BuyerEvent } from "@/contracts/send";
import type { Send, SendEventRow } from "@/modules/sends/types";

const REASON: Record<AlternativeReason, string> = {
  price: "дорого",
  style: "не тот стиль",
  space: "не помещается / тесно",
  color: "другой цвет",
  other: "другое",
};

// Слова опроса для менеджера (onb-03): названия стилей — как на вкладках демо (`index.html:STYLE_IDS`), цвета — как в вопросе
// (`tools/scout/rules/quiz.json`), состав — в форме «живут: …»; совпадение словарей сверяет `tests/unit/quiz-events.test.ts`.
export const QUIZ_STYLE_RU: Record<QuizStyle, string> = {
  scandi: "Сканди", modern: "Современный", minimal: "Минимализм", loft: "Лофт", neoclassic: "Неоклассика", japandi: "Джапанди",
};
export const QUIZ_HOUSEHOLD_RU: Record<QuizHousehold, string> = {
  single: "один", couple: "вдвоём", child: "с детьми", pet: "кошка или собака", guest: "часто родители или гости",
};
export const QUIZ_CHILD_RU: Record<QuizChildAge, string> = { "0-3": "до 3 лет", "3-7": "3–7 лет", "7-12": "7–12 лет", teen: "подросток" };
export const QUIZ_COLOUR_RU: Record<QuizColour, string> = {
  light: "светлые нейтральные", warm: "тёплые природные", cool: "графит и холодные", accent: "с яркими акцентами",
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

/** Прошёл опрос-знакомство: что понравилось, кто живёт, цвета, что показали и что выбрал. Без имени (ADR-0330 п.4). */
export function quizText(send: Send, ev: BuyerEvent): string {
  const q = (id: QuizStyle) => `«${QUIZ_STYLE_RU[id]}»`;
  const ages = ev.childAge?.length ? ` (${ev.childAge.map((a) => QUIZ_CHILD_RU[a]).join(", ")})` : "";
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

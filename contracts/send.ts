// Отправка ссылки менеджером покупателю (план b2b-02, ADR-0257).
//
// Одна отправка = одна ссылка одному покупателю: по ней видно, что смотрели и о чём просили, без
// имени и телефона покупателя. Словарь событий покупателя совпадает с `b2b-03` (одни имена в
// демо, в отчёте и в сигналах). Статусы делятся на две части: «открыл/выбирает» ставит система по
// событиям, «связались/встреча/сделка/отказ» — только менеджер (публичная страница их не трогает).

import { z } from "zod";

import { quizChildAge, quizColour, quizHousehold, quizKids, quizRoom, quizStyle } from "@/contracts/quiz";

/** События покупателя — единственное, что принимает публичная ручка. */
export const buyerEventKind = z.enum([
  "designer_open", // открыл ссылку
  "variant_view", // посмотрел вариант
  "item_swap", // заменил предмет
  "manager_contact_click", // нажал «консультация»/«ипотека» — это клик, не состоявшийся контакт
  "alternative_request", // «хочу другой вариант» с причиной из списка
  "flat3d_open", // открыл квартиру в 3D по этой ссылке (b2b-03); сохранение коллекции считается из `collections`
  "item_move", // передвинул мебель (владелец 14.10)
  "share", // поделился: ссылка на вариант, «отправить себе» (владелец 14.10)
  "floor_pick", // выбрал пол из вариантов застройщика (demo-06)
  "walls_pick", // выбрал стены из вариантов застройщика (demo-07)
  "quiz_done", // прошёл опрос-знакомство и выбрал стиль в итоге (onb-03)
  "style_change", // «Выбрать другой» стиль после опроса (onb-03)
]);
export type BuyerEventKind = z.infer<typeof buyerEventKind>;

/** Причины «хочу другой вариант» — только из списка: свободный текст мог бы принести имена и телефоны. */
export const alternativeReason = z.enum(["price", "style", "space", "color", "other"]);
export type AlternativeReason = z.infer<typeof alternativeReason>;

export const buyerEvent = z.object({
  kind: buyerEventKind,
  variant: z.string().max(80).optional(),
  items: z.array(z.string().max(120)).max(30).optional(),
  sum: z.number().int().min(0).max(1_000_000_000).optional(),
  purpose: z.enum(["consult", "mortgage"]).optional(),
  channel: z.enum(["telegram", "whatsapp", "phone"]).optional(),
  reason: alternativeReason.optional(),
  // Ответы опроса (onb-03, ADR-0330 п.4) — только перечисления из `contracts/quiz.ts`, без имени и свободного текста.
  picked: z.array(quizStyle).max(2).optional(),
  household: z.array(quizHousehold).max(5).optional(),
  childAge: z.array(quizChildAge).max(4).optional(),
  kids: quizKids.optional(),
  colours: z.array(quizColour).max(2).optional(),
  result: z.array(quizStyle).max(3).optional(),
  chosen: quizStyle.optional(),
  // Комната без выбранного стиля показала похожий (план style-fallback-01): `chosen` — стиль вкладки, здесь — стиль показанного варианта.
  shown_style: quizStyle.optional(),
  // Выбор квартиры (план home-mix-01, T-20261107-35): ответ шага «Какая спальня вам ближе?», выбранные стили (первый — основной) и
  // раскладка «комната → запрошено / показано» (показано отличается — в комнате нет запрошенного, показан похожий). `chosen` не трогаем.
  pickedBedroom: z.array(quizStyle).max(2).optional(),
  styles: z.array(quizStyle).min(1).max(2).optional(),
  rooms: z.array(z.object({ room: quizRoom, requested: quizStyle, shown: quizStyle })).max(10).optional(),
});
export type BuyerEvent = z.infer<typeof buyerEvent>;

/** Статусы по порядку: система двигает только вперёд и только по своим ступеням. */
export const sendStatus = z.enum(["sent", "opened", "engaged", "contacted", "meeting", "deal", "lost"]);
export type SendStatus = z.infer<typeof sendStatus>;
export const AUTO_STATUSES: readonly SendStatus[] = ["sent", "opened", "engaged"];
export const managerStatus = z.enum(["contacted", "meeting", "deal", "lost"]);
export type ManagerStatus = z.infer<typeof managerStatus>;

/** Какой статус система ставит по событию покупателя; null — не трогает. */
export function autoStatusFor(kind: BuyerEventKind): SendStatus | null {
  return kind === "designer_open" ? "opened" : "engaged";
}

/** Можно ли системе сменить `from` на `to`: только вперёд и только пока менеджер ничего не ставил. */
export function autoAdvanceAllowed(from: SendStatus, to: SendStatus): boolean {
  if (!AUTO_STATUSES.includes(from)) return false;
  return AUTO_STATUSES.indexOf(to) > AUTO_STATUSES.indexOf(from);
}

/** Публичная карточка для страницы покупателя: только то, что менеджер готов показать. */
export type SendCard = {
  id: string;
  apartmentId: string;
  lang: string;
  market: string;
  manager: { name: string; phone: string | null; telegram: string | null; whatsapp: string | null };
};
